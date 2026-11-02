"""Strategy planner tests (roadmap step 5, Spec v2 §4).

One test per decision rule (§4.2 contoh keputusan yang diharapkan), plus
bounded-budget and determinism checks. The planner must never produce an
unbounded retry and must never auto-retry ACCESS_DENIED (ACP §2.2).
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from datetime import datetime

import pytest

from universal_web_acquisition.access.model import (
    AccessAssessment,
    AccessState,
    Hypothesis,
    Observation,
    ReasonCode,
)
from universal_web_acquisition.access.planner import (
    NextAction,
    PlannerContext,
    StrategyDecision,
    plan,
)
from universal_web_acquisition.http_transport.registry import RetryPolicy

NOW = datetime(2026, 10, 21, 12, 0, 0)


def _assessment(state, reason=ReasonCode.UNKNOWN, retry_after=None):
    obs = Observation("o1", "http.status", "200", NOW, "curl_cffi")
    return AccessAssessment(
        assessment_id="a1",
        job_id="j1",
        attempt_id="at1",
        transport_id="curl_cffi",
        observations=(obs,),
        hypothesis=Hypothesis.UNKNOWN,
        confidence=0.75,
        reason_code=reason,
        classifier_version="classifier-1.0.0",
        decided_at=NOW,
        state=state,
        retry_after_seconds=retry_after,
    )


def _context(assessment, retry_attempt=0, browser=False, untried=("httpx",)):
    return PlannerContext(
        assessment=assessment,
        retry_attempt=retry_attempt,
        retry_policy=RetryPolicy(max_retries=3, base_backoff_seconds=1.0),
        browser_available=browser,
        current_transport="curl_cffi",
        untried_transports=untried,
    )


class TestAcceptRule:
    def test_access_granted_accepts_without_browser(self):
        # HTTP berhasil dan konten valid → simpan hasil; jangan buka browser
        decision = plan(_context(_assessment(AccessState.ACCESS_GRANTED), browser=True), "d1", NOW)
        assert decision.next_action is NextAction.ACCEPT
        assert decision.reason_code is ReasonCode.OK


class TestRateLimitRule:
    def test_with_retry_after_waits_server_time(self):
        decision = plan(
            _context(_assessment(AccessState.RATE_LIMITED, ReasonCode.HTTP_429, retry_after=30)),
            "d2", NOW,
        )
        assert decision.next_action is NextAction.WAIT_RETRY_AFTER
        assert decision.wait_seconds == 30.0

    def test_without_retry_after_backs_off_same_transport(self):
        # hindari pindah adapter hanya untuk mengulangi permintaan terlalu cepat
        decision = plan(
            _context(_assessment(AccessState.RATE_LIMITED, ReasonCode.HTTP_429)),
            "d3", NOW,
        )
        assert decision.next_action is NextAction.RETRY_SAME_TRANSPORT
        assert decision.wait_seconds == 1.0  # backoff attempt 0

    def test_budget_exhausted_aborts(self):
        decision = plan(
            _context(_assessment(AccessState.RATE_LIMITED, ReasonCode.HTTP_429), retry_attempt=4),
            "d4", NOW,
        )
        assert decision.next_action is NextAction.ABORT
        assert decision.reason_code is ReasonCode.BUDGET_EXHAUSTED

    def test_budget_gate_precedes_retry_after(self):
        # Retry-After dari server tidak mengabaikan anggaran retry
        decision = plan(
            _context(
                _assessment(AccessState.RATE_LIMITED, ReasonCode.HTTP_429, retry_after=30),
                retry_attempt=4,
            ),
            "d4b", NOW,
        )
        assert decision.next_action is NextAction.ABORT
        assert decision.reason_code is ReasonCode.BUDGET_EXHAUSTED


class TestSessionRule:
    def test_auth_required_recovers_session(self):
        # sesi kedaluwarsa → mekanisme autentikasi resmi, bukan retry buta
        decision = plan(
            _context(_assessment(AccessState.AUTH_REQUIRED, ReasonCode.AUTH_EXPIRED)),
            "d5", NOW,
        )
        assert decision.next_action is NextAction.RECOVER_SESSION


class TestChallengeRule:
    def test_challenge_with_browser_uses_browser(self):
        decision = plan(
            _context(
                _assessment(AccessState.CHALLENGE_PRESENT, ReasonCode.CHALLENGE_DETECTED),
                browser=True,
            ),
            "d6", NOW,
        )
        assert decision.next_action is NextAction.USE_BROWSER

    def test_challenge_without_browser_needs_user(self):
        # tanpa browser runtime → kegagalan yang menjelaskan kemampuan yang kurang
        decision = plan(
            _context(_assessment(AccessState.CHALLENGE_PRESENT, ReasonCode.CHALLENGE_DETECTED)),
            "d7", NOW,
        )
        assert decision.next_action is NextAction.NEEDS_USER
        assert decision.reason_code is ReasonCode.CAPABILITY_MISSING


class TestJavaScriptRule:
    def test_js_required_with_browser_uses_browser(self):
        decision = plan(
            _context(_assessment(AccessState.JAVASCRIPT_REQUIRED), browser=True),
            "d8", NOW,
        )
        assert decision.next_action is NextAction.USE_BROWSER

    def test_js_required_without_browser_aborts_capability_missing(self):
        decision = plan(
            _context(_assessment(AccessState.JAVASCRIPT_REQUIRED)),
            "d9", NOW,
        )
        assert decision.next_action is NextAction.ABORT
        assert decision.reason_code is ReasonCode.CAPABILITY_MISSING


class TestDeniedRule:
    def test_access_denied_needs_user_never_auto_retry(self):
        # DENIED tidak boleh otomatis diatasi dengan mengulang request (ACP §2.2)
        decision = plan(
            _context(
                _assessment(AccessState.ACCESS_DENIED, ReasonCode.NEEDS_USER),
                untried=("httpx", "requests"),
            ),
            "d10", NOW,
        )
        assert decision.next_action is NextAction.NEEDS_USER


class TestEscalationRules:
    def test_retryable_failure_retries_same_transport(self):
        decision = plan(
            _context(_assessment(AccessState.NETWORK_FAILURE, ReasonCode.CONNECTION_ERROR)),
            "d11", NOW,
        )
        assert decision.next_action is NextAction.RETRY_SAME_TRANSPORT
        assert decision.wait_seconds == 1.0

    def test_budget_exhausted_switches_transport(self):
        decision = plan(
            _context(
                _assessment(AccessState.NETWORK_FAILURE, ReasonCode.CONNECTION_ERROR),
                retry_attempt=4,
            ),
            "d12", NOW,
        )
        assert decision.next_action is NextAction.SWITCH_TRANSPORT
        assert decision.target_transport == "httpx"

    def test_no_alternative_left_aborts(self):
        decision = plan(
            _context(
                _assessment(AccessState.NETWORK_FAILURE, ReasonCode.CONNECTION_ERROR),
                retry_attempt=4,
                untried=(),
            ),
            "d13", NOW,
        )
        assert decision.next_action is NextAction.ABORT
        assert decision.reason_code is ReasonCode.BUDGET_EXHAUSTED

    def test_content_invalid_inspects_instead_of_transport_rotation(self):
        # §4.2: konten salah → periksa kebutuhan JavaScript/selector;
        # rotasi transport tidak menolong konten yang salah
        decision = plan(
            _context(_assessment(AccessState.CONTENT_INVALID, ReasonCode.CONTENT_INVALID)),
            "d14", NOW,
        )
        assert decision.next_action is NextAction.INSPECT_CONTENT
        assert decision.target_transport is None

    def test_content_invalid_aborts_when_budget_exhausted(self):
        decision = plan(
            _context(
                _assessment(AccessState.CONTENT_INVALID, ReasonCode.CONTENT_INVALID),
                retry_attempt=4,
            ),
            "d14b", NOW,
        )
        assert decision.next_action is NextAction.ABORT
        assert decision.reason_code is ReasonCode.CONTENT_INVALID

    def test_non_retryable_network_reason_switches_immediately(self):
        decision = plan(
            _context(_assessment(AccessState.NETWORK_FAILURE, ReasonCode.NEEDS_USER)),
            "d20", NOW,
        )
        assert decision.next_action is NextAction.SWITCH_TRANSPORT
        assert decision.target_transport == "httpx"

    def test_non_retryable_network_without_alternative_aborts_with_reason(self):
        decision = plan(
            _context(
                _assessment(AccessState.NETWORK_FAILURE, ReasonCode.NEEDS_USER),
                untried=(),
            ),
            "d21", NOW,
        )
        assert decision.next_action is NextAction.ABORT
        assert decision.reason_code is ReasonCode.NEEDS_USER


class TestUnknownRule:
    def test_unknown_collects_evidence_within_budget(self):
        # §4.2/§5: bukti tidak cukup → kumpulkan bukti, bukan rotasi transport;
        # UNKNOWN tetap diizinkan sebagai hasil jujur
        decision = plan(
            _context(_assessment(AccessState.UNKNOWN, ReasonCode.UNKNOWN)),
            "d17", NOW,
        )
        assert decision.next_action is NextAction.COLLECT_MORE_EVIDENCE

    def test_unknown_aborts_when_budget_exhausted(self):
        decision = plan(
            _context(_assessment(AccessState.UNKNOWN, ReasonCode.UNKNOWN), retry_attempt=4),
            "d18", NOW,
        )
        assert decision.next_action is NextAction.ABORT
        assert decision.reason_code is ReasonCode.UNKNOWN


class TestBudgetGatesOnEscalations:
    """Setiap aksi eskalasi non-retry juga bergerbang anggaran (G4: tanpa loop)."""

    def test_auth_required_budget_exhausted_aborts(self):
        # RECOVER_SESSION tanpa gerbang = loop login tak berujung pada 401 terus-menerus
        decision = plan(
            _context(
                _assessment(AccessState.AUTH_REQUIRED, ReasonCode.AUTH_EXPIRED),
                retry_attempt=4,
            ),
            "d22", NOW,
        )
        assert decision.next_action is NextAction.ABORT
        assert decision.reason_code is ReasonCode.AUTH_EXPIRED

    def test_challenge_with_browser_budget_exhausted_needs_user(self):
        decision = plan(
            _context(
                _assessment(AccessState.CHALLENGE_PRESENT, ReasonCode.CHALLENGE_DETECTED),
                browser=True,
                retry_attempt=4,
            ),
            "d23", NOW,
        )
        assert decision.next_action is NextAction.NEEDS_USER
        assert decision.reason_code is ReasonCode.BUDGET_EXHAUSTED

    def test_js_with_browser_budget_exhausted_aborts(self):
        decision = plan(
            _context(
                _assessment(AccessState.JAVASCRIPT_REQUIRED, ReasonCode.CONTENT_INVALID),
                browser=True,
                retry_attempt=4,
            ),
            "d24", NOW,
        )
        assert decision.next_action is NextAction.ABORT
        assert decision.reason_code is ReasonCode.BUDGET_EXHAUSTED


class TestDeterminism:
    def test_same_inputs_identical_decision(self):
        ctx = _context(_assessment(AccessState.NETWORK_FAILURE, ReasonCode.CONNECTION_ERROR))
        d1 = plan(ctx, "d15", NOW)
        d2 = plan(ctx, "d15", NOW)
        assert d1 == d2

    def test_decision_is_frozen(self):
        decision = plan(_context(_assessment(AccessState.ACCESS_GRANTED)), "d16", NOW)
        with pytest.raises(Exception):
            decision.next_action = NextAction.ABORT
