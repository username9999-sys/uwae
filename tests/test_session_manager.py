"""Session recovery manager tests (roadmap step 6, ACP §4).

Covers the guarantees mandated by INSTRUCTION.md:
- 7-phase protocol ordering (detect → quarantine → recover → validate → commit)
- single-flight per origin (recovery storm prevention)
- bounded attempts — exhausted budget yields NEEDS_USER, never auto-continue
- stale session generations denied resume
- audit trail never contains raw credentials

Catatan desain test: generasi baru HANYA lahir lewat protokol recovery
(COMMIT setelah QUARANTINE) — publish langsung saat ACTIVE sengaja ditolak
oleh state machine (ACTIVE → ACTIVE tidak sah).
"""

import json
import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from universal_web_acquisition.access.model import SessionState
from universal_web_acquisition.session.manager import (
    SessionRecoveryManager,
    SessionStore,
)
from universal_web_acquisition.session.recovery import (
    RecoveryAttemptTracker,
    SessionGeneration,
)

NOW = datetime(2026, 10, 21, 12, 0, 0)
ORIGIN = "example.com"


class FakeProvider:
    """Provider uji: perilaku tiap fase dapat dikontrol; kandidat memuat kredensial palsu.

    ``next_generation`` adalah nomor generasi berikutnya yang akan di-commit —
    helper ``_published_manager`` menyinkronkannya dengan store (gen 1 sudah ada).
    """

    def __init__(self, needs_recovery=True, validate_ok=True, next_generation=0):
        self.needs_recovery = needs_recovery  # True = detect() melaporkan sesi kedaluwarsa
        self.validate_ok = validate_ok
        self.next_generation = next_generation
        self.calls = []
        self.audit_events = []

    def detect(self, session):
        self.calls.append("detect")
        return self.needs_recovery

    def quarantine(self, session):
        self.calls.append("quarantine")

    def recover(self, session):
        self.calls.append("recover")
        return {"cookies": "SECRET-TOKEN", "user": "u1"}

    def validate(self, candidate):
        self.calls.append("validate")
        return self.validate_ok

    def commit(self, candidate):
        self.calls.append("commit")
        self.next_generation += 1
        return SessionGeneration(ORIGIN, self.next_generation, NOW)

    def resume_allowed(self, job, generation):
        return True

    def audit(self, event):
        self.calls.append("audit")
        self.audit_events.append(event)


def _published_manager(provider, **tracker_kwargs):
    """Manager dengan sesi gen-1 sudah terpublikasi; provider akan commit gen-2."""
    manager = SessionRecoveryManager(
        provider, tracker=RecoveryAttemptTracker(**tracker_kwargs)
    )
    manager._store.publish(ORIGIN, SessionGeneration(ORIGIN, 1, NOW), {"cookies": "old"})
    provider.next_generation = 1  # sinkron dengan store: commit berikutnya → gen 2
    return manager


class TestHealthySession:
    def test_detect_healthy_skips_recovery(self):
        provider = FakeProvider(needs_recovery=False)
        manager = _published_manager(provider)
        decision = manager.ensure_session(ORIGIN, NOW)
        assert decision.outcome == "recovered"
        assert "recover" not in provider.calls  # tidak ada pemulihan yang dijalankan
        assert decision.generation.generation == 1  # generasi tidak berubah


class TestFullRecovery:
    def test_expired_session_recovers_with_new_generation(self):
        provider = FakeProvider(needs_recovery=True, validate_ok=True)
        manager = _published_manager(provider)
        decision = manager.ensure_session(ORIGIN, NOW)
        assert decision.outcome == "recovered"
        # urutan protokol (audit terpisah lewat provider.audit)
        assert provider.calls == ["detect", "quarantine", "audit", "recover", "audit", "validate", "commit", "audit"]
        assert decision.generation.generation == 2  # generasi baru
        entry = manager._store.current(ORIGIN)
        assert entry.state == SessionState.ACTIVE
        assert manager._tracker.attempts(ORIGIN) == 0  # reset setelah sukses
        assert len(provider.audit_events) == 3  # QUARANTINE, RECOVER, COMMIT

    def test_no_prior_session_recovers_from_scratch(self):
        provider = FakeProvider(needs_recovery=True)
        manager = SessionRecoveryManager(provider)
        decision = manager.ensure_session(ORIGIN, NOW)
        assert decision.outcome == "recovered"
        assert "quarantine" not in provider.calls  # tidak ada sesi lama untuk dikarantina
        assert decision.generation.generation == 1


class TestBoundedAttempts:
    def test_validate_failure_returns_failed(self):
        provider = FakeProvider(needs_recovery=True, validate_ok=False, next_generation=1)
        manager = _published_manager(provider)
        decision = manager.ensure_session(ORIGIN, NOW)
        assert decision.outcome == "failed"
        assert manager._tracker.attempts(ORIGIN) == 1
        # sesi lama tetap dikarantina selama pemulihan
        assert manager._store.current(ORIGIN).state == SessionState.RECOVERY_PENDING

    def test_exhausted_budget_needs_user_without_recover(self):
        # pelajaran E6: recovery BERBATAS — habis anggaran → NEEDS_USER, bukan loop
        provider = FakeProvider(needs_recovery=True, validate_ok=False, next_generation=1)
        manager = _published_manager(provider, max_attempts=1)
        manager.ensure_session(ORIGIN, NOW)  # attempt 1 → failed
        calls_after_first = list(provider.calls)
        decision = manager.ensure_session(ORIGIN, NOW)  # anggaran habis
        assert decision.outcome == "needs_user"
        new_calls = provider.calls[len(calls_after_first):]
        assert "recover" not in new_calls  # recover TIDAK dipanggil lagi
        assert "quarantine" not in new_calls

    def test_pre_exhausted_tracker_needs_user_immediately(self):
        provider = FakeProvider(needs_recovery=True)
        manager = SessionRecoveryManager(
            provider, tracker=RecoveryAttemptTracker(max_attempts=1)
        )
        manager._tracker.record(ORIGIN)  # anggaran sudah dipakai di luar
        decision = manager.ensure_session(ORIGIN, NOW)
        assert decision.outcome == "needs_user"
        assert "recover" not in provider.calls


class TestSingleFlight:
    def test_concurrent_recovery_skipped(self):
        provider = FakeProvider(needs_recovery=True, next_generation=1)
        manager = _published_manager(provider)
        assert manager._lock.acquire(ORIGIN)  # recovery lain memegang lock
        decision = manager.ensure_session(ORIGIN, NOW)
        assert decision.outcome == "skipped_single_flight"
        assert "recover" not in provider.calls  # anti recovery-storm


class TestResumeRules:
    def test_stale_generation_denied(self):
        # generasi baru HANYA lahir lewat protokol recovery (COMMIT)
        provider = FakeProvider(needs_recovery=True, next_generation=1)
        manager = _published_manager(provider)
        gen1 = manager.current_generation(ORIGIN)
        assert manager.resume_allowed(ORIGIN, gen1) is True
        manager.ensure_session(ORIGIN, NOW)  # gen1 kedaluwarsa → recovery → gen 2
        gen2 = manager.current_generation(ORIGIN)
        assert gen2.generation == 2
        assert manager.resume_allowed(ORIGIN, gen1) is False  # stale
        assert manager.resume_allowed(ORIGIN, gen2) is True

    def test_job_without_session_dependency_allowed(self):
        manager = SessionRecoveryManager(FakeProvider())
        assert manager.resume_allowed(ORIGIN, None) is True

    def test_missing_current_denies_pinned(self):
        manager = SessionRecoveryManager(FakeProvider())
        pinned = SessionGeneration(ORIGIN, 1, NOW)
        assert manager.resume_allowed(ORIGIN, pinned) is False


class TestAuditHygiene:
    def test_audit_never_contains_credentials(self):
        provider = FakeProvider(needs_recovery=True, next_generation=1)
        manager = _published_manager(provider)
        manager.ensure_session(ORIGIN, NOW)
        dumped = json.dumps(provider.audit_events)
        assert "SECRET-TOKEN" not in dumped  # kredensial tidak pernah masuk audit
        assert "cookies" not in dumped


class TestStoreTransitions:
    def test_direct_republish_while_active_rejected(self):
        # ACTIVE → ACTIVE tidak sah: generasi baru hanya lewat protokol recovery
        from universal_web_acquisition.access.model import InvalidTransition

        store = SessionStore()
        store.publish(ORIGIN, SessionGeneration(ORIGIN, 1, NOW), {"cookies": "old"})
        with pytest.raises(InvalidTransition):
            store.publish(ORIGIN, SessionGeneration(ORIGIN, 2, NOW), {"cookies": "new"})

    def test_invalid_state_transition_rejected(self):
        from universal_web_acquisition.access.model import InvalidTransition

        store = SessionStore()
        store.publish(ORIGIN, SessionGeneration(ORIGIN, 1, NOW), {"cookies": "old"})
        with pytest.raises(InvalidTransition):
            store.set_state(ORIGIN, SessionState.NEW)  # ACTIVE → NEW tidak diizinkan
