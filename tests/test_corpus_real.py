"""Real-run corpus tests (§3.2): kalibrasi dari run nyata, bukan self-fulfilling.

Korpus nyata dibangun dari file hasil benchmark terotorisasi yang ter-commit
dengan sinyal asli dari assessment events:
- komiku 6 + ampnavi 4 = 10 kasus target nyata (semua granted);
- engine-results-e9.json = 10 kasus engine-level (3 granted + 7 diagnosis
  §6.1 dengan ground truth ``EXPECTED_DIAGNOSIS`` ter-commit).

Yang diverifikasi:
- 20 kasus termuat dengan label campur sesuai sumber;
- classifier mereproduksi diagnosis run dari sinyal yang sama
  (konsistensi 100% — bukti classifier sejalan dengan realitas);
- bucket ``access_granted`` mencapai >= 12 sampel (10 nyata + 3 E9 + 2
  sintetis) → TERKALIBRASI (confidence 1.0, source "calibrated");
- bucket lain (sampel < 10) tetap fallback kategorial — jujur terhadap §3.2.
"""

import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from universal_web_acquisition.access.classifier import CONFIDENCE_HIGH
from universal_web_acquisition.access.model import AccessState
from universal_web_acquisition.benchmark.classifier_eval import build_calibration_table
from universal_web_acquisition.benchmark.corpus_real import (
    load_real_cases,
    real_outcomes,
)

DECIDED_AT = datetime(2026, 1, 1)


class TestRealCorpus:
    def test_real_cases_loaded(self):
        # komiku 6 + ampnavi 4 + E9 10 = 20 kasus berlabel dengan sinyal asli
        cases = load_real_cases()
        assert len(cases) >= 20

    def test_real_target_cases_granted(self):
        # kasus target nyata (komiku/ampnavi): ground truth 200 + konten valid
        cases = [
            c for c in load_real_cases()
            if c.case_id.startswith(("komiku:", "ampnavi:"))
        ]
        assert len(cases) >= 10
        assert all(c.expected is AccessState.ACCESS_GRANTED for c in cases)

    def test_e9_cases_mixed_labels(self):
        # kasus E9: 3 granted + 7 diagnosis §6.1 (ground truth ter-commit)
        e9 = [c for c in load_real_cases() if c.case_id.startswith("e9:")]
        assert len(e9) >= 10
        granted = [c for c in e9 if c.expected is AccessState.ACCESS_GRANTED]
        assert len(granted) == 3
        non_granted = {c.expected for c in e9} - {AccessState.ACCESS_GRANTED}
        assert AccessState.RATE_LIMITED in non_granted
        assert AccessState.CHALLENGE_PRESENT in non_granted
        assert AccessState.AUTH_REQUIRED in non_granted
        assert AccessState.ACCESS_DENIED in non_granted
        assert AccessState.CONTENT_INVALID in non_granted
        assert AccessState.JAVASCRIPT_REQUIRED in non_granted

    def test_signals_parseable(self):
        # tiap kasus membawa sinyal http.status asli dari assessment run
        for case in load_real_cases():
            signals = dict(case.signals)
            assert "http.status" in signals
        # kasus target nyata semuanya 200; E9 membawa status sesuai skenario
        real = [
            c for c in load_real_cases()
            if c.case_id.startswith(("komiku:", "ampnavi:"))
        ]
        assert all(dict(c.signals)["http.status"] == "200" for c in real)
        e9_status = {
            c.case_id: dict(c.signals)["http.status"]
            for c in load_real_cases() if c.case_id.startswith("e9:")
        }
        assert e9_status["e9:a06_rate_limited"] == "429"
        assert e9_status["e9:a07_challenge"] == "403"
        assert e9_status["e9:e02_not_found"] == "404"

    def test_classifier_reproduces_real_runs(self):
        # konsistensi: classifier mereproduksi diagnosis run nyata dari sinyal sama
        outcomes = real_outcomes(DECIDED_AT)
        assert outcomes, "tidak ada kasus nyata"
        assert all(correct for _, correct in outcomes), outcomes

    def test_case_ids_traceable_to_runs(self):
        # setiap kasus tertelusur ke sumber run + skenario (evidence lineage)
        case_ids = {c.case_id for c in load_real_cases()}
        assert any(cid.startswith("komiku:") for cid in case_ids)
        assert any(cid.startswith("ampnavi:") for cid in case_ids)
        assert any(cid.startswith("e9:") for cid in case_ids)


class TestRealCalibration:
    def test_granted_bucket_calibrated_from_real_runs(self):
        # 10 nyata + 3 E9 + 2 sintetis = 15 >= min_samples → granted TERKALIBRASI
        table = build_calibration_table(min_samples=10)
        assert table.sample_count("access_granted") >= 15
        assert table.confidence_for("access_granted", 0.0) == 1.0

    def test_other_buckets_still_fallback(self):
        # bucket dengan sampel < 10 tetap fallback kategorial (jujur §3.2)
        table = build_calibration_table(min_samples=10)
        assert table.sample_count("rate_limited") < 10
        assert table.confidence_for("rate_limited", CONFIDENCE_HIGH) == CONFIDENCE_HIGH

    def test_without_real_corpus_falls_back(self):
        # include_real=False → hanya sintetis (2 granted) → fallback (jujur)
        table = build_calibration_table(min_samples=10, include_real=False)
        assert table.sample_count("access_granted") == 2
        assert table.confidence_for("access_granted", CONFIDENCE_HIGH) == CONFIDENCE_HIGH


class TestNonGrantedCorpus:
    """Skenario non-granted dari run nyata masuk korpus HANYA dengan
    ``ground_truth_state`` eksplisit (semantika protokol, bukan classifier)."""

    def _write_results(self, base: Path):
        doc = {
            "schema_version": 1,
            "benchmark_id": "probe-test",
            "scenarios": [
                {
                    "scenario_id": "probe_1",
                    "job_status": "succeeded",
                    "lineage": [
                        {
                            "kind": "assessment",
                            "state": "access_granted",
                            "signals": ["http.status=200", "body.marker.target=found"],
                        }
                    ],
                },
                {
                    "scenario_id": "probe_2",
                    "job_status": "failed",
                    "ground_truth_state": "rate_limited",
                    "lineage": [
                        {
                            "kind": "assessment",
                            "state": "rate_limited",
                            "signals": ["http.status=429", "http.header.retry-after=1"],
                        }
                    ],
                },
                {
                    "scenario_id": "probe_3",
                    "job_status": "failed",
                    "lineage": [
                        {
                            "kind": "assessment",
                            "state": "access_denied",
                            "signals": ["http.status=403"],
                        }
                    ],
                },
            ],
        }
        (base / "real-target-probe.json").write_text(json.dumps(doc), encoding="utf-8")

    def test_failed_scenarios_need_explicit_ground_truth(self):
        base = Path(tempfile.mkdtemp(prefix="uwae-corpus-"))
        self._write_results(base)
        cases = {c.case_id: c for c in load_real_cases(benchmark_dir=base)}
        # granted tetap masuk
        assert cases["probe:probe_1"].expected is AccessState.ACCESS_GRANTED
        # gagal + ground truth eksplisit → masuk dengan label protokol
        assert cases["probe:probe_2"].expected is AccessState.RATE_LIMITED
        assert dict(cases["probe:probe_2"].signals)["http.status"] == "429"
        # gagal TANPA ground truth → tidak diikutkan (jujur)
        assert "probe:probe_3" not in cases

    def test_non_granted_cases_consistent(self):
        base = Path(tempfile.mkdtemp(prefix="uwae-corpus-"))
        self._write_results(base)
        outcomes = real_outcomes(DECIDED_AT, benchmark_dir=base)
        assert ("access_granted", True) in outcomes
        assert ("rate_limited", True) in outcomes
        assert all(correct for _, correct in outcomes)
