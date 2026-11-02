"""Classifier evaluation tests (Milestone B, G3 gate).

Yang diverifikasi:
- korpus berlabel mencakup seluruh 9 kelas ``AccessState``;
- akurasi korpus 1.0 — korpus adalah spesifikasi eksekutabel: akurasi < 1.0
  berarti inkonsistensi nyata antara classifier dan spesifikasi §3.1;
- precision/recall per kelas sempurna pada korpus; confusion matrix hanya
  berisi diagonal;
- probe marker: FP-guard (kata 'captcha'/'javascript' dalam konten normal)
  dan TP (gerbang JS, interstitial challenge);
- kasus turunan respons fixture nyata (bukan observasi buatan).
"""

import asyncio
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from datetime import datetime

from universal_web_acquisition.access.classifier import Signal, classify
from universal_web_acquisition.access.model import AccessState, ReasonCode
from universal_web_acquisition.access.observe import (
    observations_from_artifact,
    observations_from_failure,
)
from universal_web_acquisition.artifact.storage import FilesystemArtifactStorage
from universal_web_acquisition.benchmark.classifier_eval import (
    LABELED_CASES,
    evaluate_corpus,
    evaluate_marker_probes,
)
from universal_web_acquisition.benchmark.fixture_server import FixtureServer
from universal_web_acquisition.core.job_model import Job
from universal_web_acquisition.http_transport.adapters import (
    CurlCffiAdapter,
    TransportFailure,
)

DECIDED_AT = datetime(2026, 1, 1)


def _classify(observations):
    return classify(
        observations,
        assessment_id="eval-test",
        job_id="eval",
        attempt_id="eval",
        transport_id="test",
        decided_at=DECIDED_AT,
    )


def _make_storage():
    return FilesystemArtifactStorage(base_path=tempfile.mkdtemp(prefix="uwae-eval-"))


class TestCorpusCoverage:
    def test_all_nine_states_covered(self):
        expected_states = {case.expected for case in LABELED_CASES}
        assert expected_states == set(AccessState)

    def test_corpus_is_nontrivial(self):
        assert len(LABELED_CASES) >= 20


class TestCorpusEvaluation:
    def test_perfect_classification_on_corpus(self):
        report = evaluate_corpus()
        assert report.mismatches == (), f"mismatch: {report.mismatches}"
        assert report.accuracy == 1.0

    def test_precision_recall_perfect_for_all_labels(self):
        report = evaluate_corpus()
        assert report.precision, "precision kosong"
        for label, value in report.precision.items():
            assert value == 1.0, f"precision {label} = {value}"
        for label, value in report.recall.items():
            assert value == 1.0, f"recall {label} = {value}"

    def test_unknown_proportion_measured(self):
        report = evaluate_corpus()
        expected_unknown = sum(
            1 for case in LABELED_CASES if case.expected is AccessState.UNKNOWN
        )
        assert expected_unknown > 0  # UNKNOWN memang bagian korpus (§5)
        assert report.unknown_proportion == pytest.approx(
            expected_unknown / report.total
        )

    def test_confusion_diagonal_only(self):
        report = evaluate_corpus()
        for expected_label, row in report.confusion.items():
            for predicted_label, count in row.items():
                if expected_label != predicted_label:
                    assert count == 0, (
                        f"off-diagonal {expected_label}→{predicted_label} = {count}"
                    )


class TestMarkerProbes:
    def _results(self):
        return {
            probe.probe_id: (actual, ok) for probe, actual, ok in evaluate_marker_probes()
        }

    def test_all_probes_pass(self):
        results = self._results()
        assert results, "probe kosong"
        for probe_id, (actual, ok) in results.items():
            assert ok, f"probe {probe_id} gagal: actual={actual}"

    def test_no_false_challenge_on_normal_content(self):
        # FP-guard eksplisit: kata 'captcha'/'javascript' dalam konten normal
        # tidak boleh memicu sinyal challenge/js (Milestone B: FP diukur).
        actual, ok = self._results()["normal-article-captcha-word"]
        signals = {signal for signal, _ in actual}
        assert Signal.CHALLENGE not in signals
        assert Signal.JS_REQUIRED not in signals
        assert ok

    def test_js_gate_detected(self):
        actual, ok = self._results()["js-gate"]
        assert (Signal.JS_REQUIRED, "true") in actual
        assert (Signal.TARGET_MARKER, "missing") in actual
        assert ok

    def test_challenge_interstitial_detected(self):
        actual, ok = self._results()["challenge-checking-browser"]
        assert (Signal.CHALLENGE, "checking your browser") in actual
        assert (Signal.TARGET_MARKER, "missing") in actual
        assert ok


class TestFixtureDerived:
    """Korpus dari respons nyata fixture server — bukan observasi buatan."""

    def test_html_fixture_is_granted(self):
        adapter = CurlCffiAdapter()
        with FixtureServer() as base:
            storage = _make_storage()
            job = Job(job_id="eval-html", url=base + "/html")
            artifact = asyncio.run(adapter.acquire(job, storage))
        observations = observations_from_artifact(adapter.name, artifact, 0, DECIDED_AT)
        assessment = _classify(observations)
        assert assessment.state is AccessState.ACCESS_GRANTED
        assert assessment.reason_code is ReasonCode.OK

    def test_missing_fixture_is_content_invalid_http_4xx(self):
        adapter = CurlCffiAdapter()
        with FixtureServer() as base:
            storage = _make_storage()
            job = Job(job_id="eval-404", url=base + "/missing")
            with pytest.raises(TransportFailure) as exc_info:
                asyncio.run(adapter.acquire(job, storage))
        observations = observations_from_failure(
            adapter.name,
            exc_info.value.reason_code,
            exc_info.value.status_code,
            0,
            DECIDED_AT,
        )
        assessment = _classify(observations)
        assert assessment.state is AccessState.CONTENT_INVALID
        assert assessment.reason_code is ReasonCode.HTTP_4XX

    def test_js_fixture_is_javascript_required(self):
        # /js kini gerbang JS sungguhan: fetch HTTP membawa teks gate,
        # sehingga diagnosis di jalur HTTP adalah JAVASCRIPT_REQUIRED.
        adapter = CurlCffiAdapter()
        with FixtureServer() as base:
            storage = _make_storage()
            job = Job(job_id="eval-js", url=base + "/js")
            artifact = asyncio.run(adapter.acquire(job, storage))
        observations = observations_from_artifact(adapter.name, artifact, 0, DECIDED_AT)
        assessment = _classify(observations)
        assert assessment.state is AccessState.JAVASCRIPT_REQUIRED


class TestFixtureDerivedDiagnosis:
    """Skenario diagnosis §6.1 dari respons fixture nyata — klasifikasi sesuai
    ground truth (A04/A06/A07/A11)."""

    def _assess_artifact(self, adapter, base, path, job_id):
        storage = _make_storage()
        job = Job(job_id=job_id, url=base + path)
        artifact = asyncio.run(adapter.acquire(job, storage))
        observations = observations_from_artifact(adapter.name, artifact, 0, DECIDED_AT)
        return _classify(observations)

    def _assess_failure(self, adapter, base, path, job_id):
        storage = _make_storage()
        job = Job(job_id=job_id, url=base + path)
        with pytest.raises(TransportFailure) as exc_info:
            asyncio.run(adapter.acquire(job, storage))
        tf = exc_info.value
        observations = observations_from_failure(
            adapter.name,
            tf.reason_code,
            tf.status_code,
            0,
            DECIDED_AT,
            headers=tf.headers,
            body=tf.body,
        )
        return _classify(observations), tf

    def test_login_fixture_is_auth_required(self):
        # A04: 200 + formulir login → AUTH_REQUIRED (LOGIN_FORM_PRESENT)
        adapter = CurlCffiAdapter()
        with FixtureServer() as base:
            assessment = self._assess_artifact(adapter, base, "/login", "eval-login")
        assert assessment.state is AccessState.AUTH_REQUIRED
        assert assessment.reason_code is ReasonCode.LOGIN_FORM_PRESENT

    def test_invalid_html_fixture_is_content_invalid(self):
        # A11: sukses tidak dilaporkan hanya karena status 200
        adapter = CurlCffiAdapter()
        with FixtureServer() as base:
            assessment = self._assess_artifact(
                adapter, base, "/invalid-html", "eval-a11"
            )
        assert assessment.state is AccessState.CONTENT_INVALID
        assert assessment.reason_code is ReasonCode.CONTENT_INVALID

    def test_rate_limited_fixture_honors_retry_after(self):
        # A06: 429 + Retry-After → RATE_LIMITED dengan waktu tunggu dari server
        adapter = CurlCffiAdapter()
        with FixtureServer() as base:
            assessment, tf = self._assess_failure(
                adapter, base, "/rate-limited", "eval-a06"
            )
        assert tf.status_code == 429
        # curl_cffi melaporkan nama header lowercase — lookup case-insensitive
        retry_after = next(
            (v for k, v in tf.headers.items() if k.lower() == "retry-after"), None
        )
        assert retry_after == "1"
        assert assessment.state is AccessState.RATE_LIMITED
        assert assessment.retry_after_seconds == 1.0

    def test_challenge_vs_denied_distinction(self):
        # A07: 403+signature → CHALLENGE_PRESENT; 403 polos → ACCESS_DENIED
        adapter = CurlCffiAdapter()
        with FixtureServer() as base:
            challenge, _ = self._assess_failure(adapter, base, "/challenge", "eval-ch")
            denied, _ = self._assess_failure(adapter, base, "/denied", "eval-den")
        assert challenge.state is AccessState.CHALLENGE_PRESENT
        assert challenge.reason_code is ReasonCode.CHALLENGE_DETECTED
        assert denied.state is AccessState.ACCESS_DENIED
        assert denied.reason_code is ReasonCode.HTTP_4XX
