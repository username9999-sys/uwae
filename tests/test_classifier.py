"""Unit tests for the deterministic access classifier (roadmap step 4).

Covers the INSTRUCTION.md Milestone B requirements: one test per access
class, false positive / false negative tests, evaluation-order precedence,
Retry-After parsing, determinism, evidence lineage, and confusion-matrix
helpers.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from datetime import datetime

import pytest

from universal_web_acquisition.access.classifier import (
    CLASSIFIER_VERSION,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    Signal,
    classify,
    confusion_matrix,
    parse_retry_after,
    precision_recall,
)
from universal_web_acquisition.access.model import (
    AccessState,
    EvidenceLineage,
    Hypothesis,
    Observation,
    ReasonCode,
)

DECIDED_AT = datetime(2026, 10, 21, 12, 0, 0)

_counter = {"n": 0}


def _obs(signal, value, source="test-transport"):
    _counter["n"] += 1
    return Observation(
        observation_id=f"obs-{_counter['n']:06d}",
        signal=signal,
        value=value,
        recorded_at=DECIDED_AT,
        source=source,
    )


def _classify(obs, **kwargs):
    return classify(
        obs,
        assessment_id="asg-1",
        job_id="job-1",
        attempt_id="att-1",
        transport_id="curl_cffi",
        decided_at=DECIDED_AT,
        **kwargs,
    )


class TestClassPerState:
    """Satu skenario berlabel per kelas akses (Milestone B: fixture berlabel)."""

    @pytest.mark.parametrize(
        "obs,expected_state,expected_reason,expected_hypothesis,expected_action",
        [
            (
                [Signal.NETWORK_ERROR, "dns"],
                AccessState.NETWORK_FAILURE,
                ReasonCode.DNS_FAILURE,
                Hypothesis.NETWORK_FAILURE,
                "diagnose_network_before_retry",
            ),
            (
                [Signal.HTTP_STATUS, "429"],
                AccessState.RATE_LIMITED,
                ReasonCode.HTTP_429,
                Hypothesis.RATE_LIMITED,
                "respect_retry_after",
            ),
            (
                [Signal.HTTP_STATUS, "401"],
                AccessState.AUTH_REQUIRED,
                ReasonCode.HTTP_4XX,
                Hypothesis.AUTH_REQUIRED,
                "reauthenticate_or_request_user",
            ),
            (
                [Signal.HTTP_STATUS, "403"],
                AccessState.ACCESS_DENIED,
                ReasonCode.HTTP_4XX,
                Hypothesis.ACCESS_DENIED,
                "stop_or_use_authorized_access",
            ),
            (
                [Signal.CHALLENGE, "cf-mitigated"],
                AccessState.CHALLENGE_PRESENT,
                ReasonCode.CHALLENGE_DETECTED,
                Hypothesis.CHALLENGE_PRESENT,
                "authorized_challenge_workflow",
            ),
            (
                [Signal.HTTP_STATUS, "200", Signal.TARGET_MARKER, "found"],
                AccessState.ACCESS_GRANTED,
                ReasonCode.OK,
                Hypothesis.ACCESS_GRANTED,
                "persist_result",
            ),
            (
                [Signal.JS_REQUIRED, "true"],
                AccessState.JAVASCRIPT_REQUIRED,
                ReasonCode.CONTENT_INVALID,
                Hypothesis.JAVASCRIPT_REQUIRED,
                "check_browser_capability",
            ),
            (
                [Signal.HTTP_STATUS, "200"],
                AccessState.CONTENT_INVALID,
                ReasonCode.CONTENT_INVALID,
                Hypothesis.CONTENT_MISMATCH,
                "inspect_content_and_target",
            ),
            (
                ["body.marker.article", "present"],
                AccessState.UNKNOWN,
                ReasonCode.UNKNOWN,
                Hypothesis.UNKNOWN,
                "collect_more_evidence",
            ),
        ],
    )
    def test_labeled_scenario(
        self, obs, expected_state, expected_reason, expected_hypothesis, expected_action
    ):
        pairs = [obs[i : i + 2] for i in range(0, len(obs), 2)]
        observations = [_obs(signal, value) for signal, value in pairs]
        assessment = _classify(observations)

        assert assessment.state is expected_state
        assert assessment.reason_code is expected_reason
        assert assessment.hypothesis is expected_hypothesis
        assert assessment.recommended_action == expected_action
        assert assessment.classifier_version == CLASSIFIER_VERSION
        assert 0.0 <= assessment.confidence <= 1.0


class TestEvaluationOrder:
    """Urutan evaluasi §3.1 — aturan lebih awal menang atas yang lebih akhir."""

    def test_network_error_beats_rate_limit(self):
        assessment = _classify([_obs(Signal.HTTP_STATUS, "429"), _obs(Signal.NETWORK_ERROR, "dns")])
        assert assessment.state is AccessState.NETWORK_FAILURE

    def test_challenge_beats_denial(self):
        # 403 + signature challenge → CHALLENGE_PRESENT, bukan ACCESS_DENIED
        assessment = _classify([_obs(Signal.HTTP_STATUS, "403"), _obs(Signal.CHALLENGE, "just-a-moment")])
        assert assessment.state is AccessState.CHALLENGE_PRESENT
        assert assessment.reason_code is ReasonCode.CHALLENGE_DETECTED

    def test_auth_beats_granted(self):
        # 200 + form login + marker target ditemukan → AUTH_REQUIRED (Spec v2 §4.1)
        assessment = _classify(
            [
                _obs(Signal.HTTP_STATUS, "200"),
                _obs(Signal.LOGIN_FORM, "present"),
                _obs(Signal.TARGET_MARKER, "found"),
            ]
        )
        assert assessment.state is AccessState.AUTH_REQUIRED
        assert assessment.reason_code is ReasonCode.LOGIN_FORM_PRESENT

    def test_auth_beats_challenge(self):
        assessment = _classify([_obs(Signal.HTTP_STATUS, "401"), _obs(Signal.CHALLENGE, "captcha")])
        assert assessment.state is AccessState.AUTH_REQUIRED

    def test_rate_limit_beats_server_error(self):
        # 503 + Retry-After → sinyal rate limit eksplisit menang
        assessment = _classify(
            [_obs(Signal.HTTP_STATUS, "503"), _obs(Signal.RETRY_AFTER, "30")]
        )
        assert assessment.state is AccessState.RATE_LIMITED
        assert assessment.retry_after_seconds == 30.0

    def test_rate_limit_beats_granted(self):
        assessment = _classify(
            [_obs(Signal.HTTP_STATUS, "429"), _obs(Signal.TARGET_MARKER, "found")]
        )
        assert assessment.state is AccessState.RATE_LIMITED

    def test_javascript_beats_content_invalid(self):
        assessment = _classify(
            [
                _obs(Signal.HTTP_STATUS, "200"),
                _obs(Signal.TARGET_MARKER, "missing"),
                _obs(Signal.JS_REQUIRED, "true"),
            ]
        )
        assert assessment.state is AccessState.JAVASCRIPT_REQUIRED

    def test_missing_target_without_js_is_content_invalid(self):
        assessment = _classify(
            [_obs(Signal.HTTP_STATUS, "200"), _obs(Signal.TARGET_MARKER, "missing")]
        )
        assert assessment.state is AccessState.CONTENT_INVALID


class TestFalsePositives:
    """Milestone B: halaman normal tidak boleh diklasifikasikan sebagai challenge."""

    def test_normal_page_not_challenge(self):
        assessment = _classify(
            [_obs(Signal.HTTP_STATUS, "200"), _obs(Signal.TARGET_MARKER, "found")]
        )
        assert assessment.state is AccessState.ACCESS_GRANTED
        assert assessment.state is not AccessState.CHALLENGE_PRESENT
        assert assessment.state is not AccessState.ACCESS_DENIED

    def test_plain_403_not_challenge(self):
        # 403 tanpa marker challenge ambigu — akses ditolak, bukan CAPTCHA
        assessment = _classify([_obs(Signal.HTTP_STATUS, "403")])
        assert assessment.state is AccessState.ACCESS_DENIED
        assert assessment.state is not AccessState.CHALLENGE_PRESENT

    def test_unvalidated_success_is_not_granted(self):
        # Tanpa validasi target, 200 tidak boleh menjadi ACCESS_GRANTED
        assessment = _classify([_obs(Signal.HTTP_STATUS, "200")])
        assert assessment.state is AccessState.CONTENT_INVALID

    def test_unknown_signal_alone_is_not_granted(self):
        assessment = _classify([_obs("custom.signal", "whatever")])
        assert assessment.state is AccessState.UNKNOWN

    def test_404_not_denied(self):
        assessment = _classify([_obs(Signal.HTTP_STATUS, "404")])
        assert assessment.state is AccessState.CONTENT_INVALID
        assert assessment.state is not AccessState.ACCESS_DENIED


class TestFalseNegatives:
    """Milestone B: challenge/rate limit tidak boleh terlewat."""

    def test_challenge_with_200_detected(self):
        assessment = _classify(
            [_obs(Signal.HTTP_STATUS, "200"), _obs(Signal.CHALLENGE, "cf-mitigated")]
        )
        assert assessment.state is AccessState.CHALLENGE_PRESENT

    def test_429_without_retry_after_still_rate_limited(self):
        assessment = _classify([_obs(Signal.HTTP_STATUS, "429")])
        assert assessment.state is AccessState.RATE_LIMITED
        assert assessment.retry_after_seconds is None


class TestRetryAfterParsing:
    def test_delta_seconds(self):
        assert parse_retry_after("30", DECIDED_AT) == 30.0

    def test_whitespace_stripped(self):
        assert parse_retry_after(" 120 ", DECIDED_AT) == 120.0

    def test_negative_clamped_to_zero(self):
        assert parse_retry_after("-5", DECIDED_AT) == 0.0

    def test_garbage_returns_none(self):
        assert parse_retry_after("soon", DECIDED_AT) is None

    def test_empty_returns_none(self):
        assert parse_retry_after("", DECIDED_AT) is None
        assert parse_retry_after(None, DECIDED_AT) is None

    def test_http_date_future(self):
        assessment_date = "Wed, 21 Oct 2026 13:00:00 GMT"
        assert parse_retry_after(assessment_date, DECIDED_AT) == 3600.0

    def test_http_date_past_clamped_to_zero(self):
        assessment_date = "Wed, 21 Oct 2026 11:00:00 GMT"
        assert parse_retry_after(assessment_date, DECIDED_AT) == 0.0

    def test_aware_now_handled(self):
        from datetime import timezone

        aware_now = DECIDED_AT.replace(tzinfo=timezone.utc)
        assert parse_retry_after("Wed, 21 Oct 2026 13:00:00 GMT", aware_now) == 3600.0


class TestDeterminism:
    def test_same_input_same_output(self):
        obs = [
            _obs(Signal.HTTP_STATUS, "429"),
            _obs(Signal.RETRY_AFTER, "30"),
        ]
        first = _classify(obs)
        second = _classify(obs)
        assert first == second

    def test_confidence_categories_fixed(self):
        assert _classify([_obs(Signal.NETWORK_ERROR, "tls")]).confidence == CONFIDENCE_HIGH
        assert _classify([_obs(Signal.HTTP_STATUS, "403")]).confidence == CONFIDENCE_MEDIUM
        assert _classify([_obs("custom.signal", "x")]).confidence == CONFIDENCE_LOW


class TestEvidenceLineage:
    def test_observation_ids_preserved(self):
        obs = [_obs(Signal.HTTP_STATUS, "403"), _obs(Signal.CHALLENGE, "cf-mitigated")]
        assessment = _classify(obs)
        assert assessment.observations == tuple(obs)
        assert [o.observation_id for o in assessment.observations] == [
            o.observation_id for o in obs
        ]

    def test_lineage_constructible_from_assessment(self):
        obs = [_obs(Signal.HTTP_STATUS, "403")]
        assessment = _classify(obs)
        lineage = EvidenceLineage(
            job_id=assessment.job_id,
            attempt_id=assessment.attempt_id,
            transport_id=assessment.transport_id,
            observation_ids=tuple(o.observation_id for o in assessment.observations),
            classifier_version=assessment.classifier_version,
            assessment_id=assessment.assessment_id,
            strategy_decision=assessment.recommended_action,
            validation_result="pending",
        )
        assert lineage.observation_ids == (obs[0].observation_id,)
        assert lineage.strategy_decision == "stop_or_use_authorized_access"


class TestEmptyObservations:
    def test_rejected(self):
        with pytest.raises(ValueError):
            _classify([])


class TestConfusionMatrix:
    def test_counts(self):
        pairs = [
            ("access_granted", "access_granted"),
            ("access_granted", "access_granted"),
            ("access_granted", "challenge_present"),
            ("access_denied", "access_denied"),
        ]
        matrix = confusion_matrix(pairs)
        assert matrix["access_granted"]["access_granted"] == 2
        assert matrix["access_granted"]["challenge_present"] == 1
        assert matrix["access_denied"]["access_denied"] == 1

    def test_perfect_precision_recall(self):
        pairs = [("rate_limited", "rate_limited")] * 3
        matrix = confusion_matrix(pairs)
        precision, recall = precision_recall(matrix, "rate_limited")
        assert precision == 1.0
        assert recall == 1.0

    def test_false_positive_lowers_precision(self):
        pairs = [
            ("access_granted", "access_granted"),
            ("access_granted", "access_granted"),
            ("access_denied", "access_granted"),  # FP untuk access_granted
        ]
        matrix = confusion_matrix(pairs)
        precision, recall = precision_recall(matrix, "access_granted")
        assert precision == pytest.approx(2 / 3)
        assert recall == 1.0

    def test_false_negative_lowers_recall(self):
        pairs = [
            ("challenge_present", "challenge_present"),
            ("challenge_present", "access_denied"),  # FN untuk challenge_present
        ]
        matrix = confusion_matrix(pairs)
        precision, recall = precision_recall(matrix, "challenge_present")
        assert precision == 1.0
        assert recall == 0.5

    def test_zero_division_returns_zero(self):
        matrix = confusion_matrix([("access_granted", "access_granted")])
        precision, recall = precision_recall(matrix, "unknown")
        assert precision == 0.0
        assert recall == 0.0
