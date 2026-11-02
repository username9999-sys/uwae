"""Fase 2 contract tests: state machines, bounded retry, registry, session recovery.

Verifies the contracts written for Fase 2 (ADR-003/ADR-011 + Access Control
Plane spec): consistency rules are enforced in code, retry is bounded by
construction, and recovery is single-flight and capped.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from datetime import datetime

import pytest

from universal_web_acquisition.access.model import (
    ORIGIN_TRANSITIONS,
    SESSION_TRANSITIONS,
    AccessAssessment,
    Hypothesis,
    InvalidTransition,
    Observation,
    OriginState,
    ReasonCode,
    SessionState,
    assert_needs_user_not_auto_resolved,
    assert_retry_wait_has_trigger,
    assert_terminal_reason,
    can_transition,
    require_transition,
)
from universal_web_acquisition.core.job_model import Job, JobStatus
from universal_web_acquisition.http_transport.registry import (
    RetryPolicy,
    TransportCapability,
    TransportRegistry,
)
from universal_web_acquisition.session.recovery import (
    RecoveryAttemptTracker,
    RecoveryLock,
    SessionGeneration,
)


def _obs(signal="http.status", value="403"):
    return Observation(
        observation_id="obs-1",
        signal=signal,
        value=value,
        recorded_at=datetime(2026, 10, 20),
        source="test-transport",
    )


class TestOriginStateMachine:
    def test_healthy_to_rate_limited_allowed(self):
        require_transition(OriginState.HEALTHY, OriginState.RATE_LIMITED, ORIGIN_TRANSITIONS, "origin")

    def test_denied_is_terminal(self):
        # DENIED tidak boleh otomatis diatasi dengan mengulang request (ACP §2.2)
        assert ORIGIN_TRANSITIONS[OriginState.DENIED] == set()
        assert not can_transition(OriginState.DENIED, OriginState.HEALTHY, ORIGIN_TRANSITIONS)

    def test_invalid_transition_rejected(self):
        with pytest.raises(InvalidTransition):
            require_transition(OriginState.DENIED, OriginState.HEALTHY, ORIGIN_TRANSITIONS, "origin")


class TestSessionStateMachine:
    def test_active_to_recovery_pending_allowed(self):
        require_transition(SessionState.ACTIVE, SessionState.RECOVERY_PENDING, SESSION_TRANSITIONS, "session")

    def test_recovery_pending_to_active_allowed(self):
        require_transition(SessionState.RECOVERY_PENDING, SessionState.ACTIVE, SESSION_TRANSITIONS, "session")

    def test_closed_is_terminal(self):
        assert SESSION_TRANSITIONS[SessionState.CLOSED] == set()

    def test_new_to_expiring_rejected(self):
        with pytest.raises(InvalidTransition):
            require_transition(SessionState.NEW, SessionState.EXPIRING, SESSION_TRANSITIONS, "session")


class TestJobConsistency:
    def test_failed_requires_non_ok_reason(self):
        job = Job(job_id="j1", url="https://example.com")
        job.mark_failed("boom")
        with pytest.raises(ValueError):
            assert_terminal_reason(job, ReasonCode.OK)
        assert_terminal_reason(job, ReasonCode.TIMEOUT)

    def test_succeeded_requires_ok_reason(self):
        job = Job(job_id="j2", url="https://example.com")
        job.mark_completed("artifact-1")
        with pytest.raises(ValueError):
            assert_terminal_reason(job, ReasonCode.TIMEOUT)
        assert_terminal_reason(job, ReasonCode.OK)

    def test_non_terminal_rejected(self):
        job = Job(job_id="j3", url="https://example.com")  # QUEUED
        with pytest.raises(ValueError):
            assert_terminal_reason(job, ReasonCode.OK)

    def test_retry_wait_requires_trigger(self):
        with pytest.raises(ValueError):
            assert_retry_wait_has_trigger(None, ReasonCode.TIMEOUT)
        assert_retry_wait_has_trigger(datetime(2026, 10, 20, 12, 0), ReasonCode.TIMEOUT)

    def test_needs_user_not_auto_resolved(self):
        with pytest.raises(ValueError):
            assert_needs_user_not_auto_resolved(JobStatus.NEEDS_USER, JobStatus.SUCCEEDED)


class TestAccessAssessment:
    def test_requires_observations(self):
        with pytest.raises(ValueError):
            AccessAssessment(
                assessment_id="a1",
                job_id="j1",
                attempt_id="at1",
                transport_id="t1",
                observations=(),
                hypothesis=Hypothesis.ACCESS_DENIED,
                confidence=0.9,
                reason_code=ReasonCode.CHALLENGE_DETECTED,
                classifier_version="cls-1",
                decided_at=datetime(2026, 10, 20),
            )

    def test_confidence_bounds(self):
        with pytest.raises(ValueError):
            AccessAssessment(
                assessment_id="a2",
                job_id="j1",
                attempt_id="at1",
                transport_id="t1",
                observations=(_obs(),),
                hypothesis=Hypothesis.ACCESS_DENIED,
                confidence=1.5,
                reason_code=ReasonCode.CHALLENGE_DETECTED,
                classifier_version="cls-1",
                decided_at=datetime(2026, 10, 20),
            )


class TestRetryPolicy:
    def test_bounded_by_construction(self):
        policy = RetryPolicy(max_retries=3)
        assert policy.next_delay_seconds(0) is not None
        assert policy.next_delay_seconds(3) is not None
        assert policy.next_delay_seconds(4) is None  # anggaran habis — wajib berhenti

    def test_unbounded_rejected(self):
        with pytest.raises(ValueError):
            RetryPolicy(max_retries=999)

    def test_backoff_capped(self):
        policy = RetryPolicy(max_retries=10, base_backoff_seconds=1.0, max_backoff_seconds=60.0)
        assert policy.next_delay_seconds(10) == 60.0

    def test_retryable_reasons(self):
        policy = RetryPolicy()
        assert policy.is_retryable(ReasonCode.TIMEOUT)
        assert not policy.is_retryable(ReasonCode.NEEDS_USER)


class TestTransportRegistry:
    def test_select_by_capabilities(self):
        reg = TransportRegistry()
        reg.register("curl_cffi", object(), TransportCapability(tls_fingerprint=True, http2=True, brotli=True))
        reg.register("httpx", object(), TransportCapability(http2=True, brotli=True))
        assert reg.select(TransportCapability(tls_fingerprint=True)) == ["curl_cffi"]
        assert reg.select(TransportCapability(brotli=True)) == ["curl_cffi", "httpx"]

    def test_no_match_returns_empty(self):
        reg = TransportRegistry()
        reg.register("httpx", object(), TransportCapability(http2=True))
        assert reg.select(TransportCapability(tls_fingerprint=True)) == []

    def test_duplicate_registration_rejected(self):
        reg = TransportRegistry()
        reg.register("httpx", object(), TransportCapability())
        with pytest.raises(ValueError):
            reg.register("httpx", object(), TransportCapability())


class TestSessionGeneration:
    def test_stale_detection(self):
        gen1 = SessionGeneration("example.com", 1, datetime(2026, 10, 20, 10, 0))
        gen2 = SessionGeneration("example.com", 2, datetime(2026, 10, 20, 11, 0))
        assert gen1.is_stale(gen2)
        assert not gen2.is_stale(gen1)

    def test_cross_origin_is_stale(self):
        gen_a = SessionGeneration("a.com", 5, datetime(2026, 10, 20))
        gen_b = SessionGeneration("b.com", 1, datetime(2026, 10, 20))
        assert gen_a.is_stale(gen_b)


class TestRecoveryLock:
    def test_single_flight(self):
        lock = RecoveryLock()
        assert lock.acquire("example.com") is True
        assert lock.acquire("example.com") is False  # satu penerbangan saja
        assert lock.is_active("example.com")
        lock.release("example.com")
        assert lock.acquire("example.com") is True


class TestRecoveryAttemptTracker:
    def test_attempts_capped(self):
        tracker = RecoveryAttemptTracker(max_attempts=3)
        for _ in range(3):
            assert tracker.can_attempt("example.com")
            tracker.record("example.com")
        assert not tracker.can_attempt("example.com")  # recovery juga berbatas (E6)

    def test_reset_after_success(self):
        tracker = RecoveryAttemptTracker(max_attempts=3)
        tracker.record("example.com")
        tracker.record("example.com")
        tracker.reset("example.com")
        assert tracker.can_attempt("example.com")

    def test_invalid_max_rejected(self):
        with pytest.raises(ValueError):
            RecoveryAttemptTracker(max_attempts=0)
