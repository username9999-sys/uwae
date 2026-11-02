"""Milestone C tests: recovery yang tahan race condition (ACP §4, INSTRUCTION.md).

Deliverable wajib Milestone C yang diverifikasi di sini (sisanya — session
generation, single-flight, job recovery pasca-proses-mati — sudah tercakup
di test_session_manager/test_session_store_sqlite/test_durability):

1. **Tes dua atau lebih job yang berbagi sesi** — job kedua memakai sesi
   yang sama tanpa memicu recovery kedua (anti recovery-storm), dan
   single-flight men-skip pemanggil saat recovery lain sedang berjalan;
2. **Recovery parsial** — kandidat diproduksi tetapi validasi gagal →
   outcome ``failed`` (BUKAN sukses palsu), lalu retry dalam anggaran
   berhasil dengan generasi baru;
3. **Idempotensi operasi yang dapat diulang** — recover_interrupted dua
   kali = no-op kedua; ensure_session atas sesi sehat = generasi sama
   (tanpa recovery baru); start_attempt dengan id sama = satu baris.

Kriteria lulus: tidak membuat state sukses palsu, tidak menjalankan
recovery tanpa batas, memulihkan job sesuai aturan yang teruji.
"""

import os
import sys
import tempfile
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from universal_web_acquisition.core.job_model import Job, JobStatus
from universal_web_acquisition.core.job_repository import JobRepository
from universal_web_acquisition.session.manager import (
    SessionRecoveryManager,
    SessionStore,
)
from universal_web_acquisition.session.recovery import (
    RecoveryAttemptTracker,
    RecoveryLock,
    SessionGeneration,
)

NOW = datetime(2026, 10, 22, 12, 0, 0)
ORIGIN = "example.com"


class StubProvider:
    """Provider protokol dengan perilaku yang dapat dikonfigurasi per test."""

    def __init__(self, healthy=False, validate_ok=True):
        self.healthy = healthy          # detect → True berarti ADA masalah
        self.validate_ok = validate_ok
        self.quarantined = []
        self.recover_calls = 0
        self.commit_calls = 0
        self.events = []

    def detect(self, session):
        return not self.healthy

    def quarantine(self, session):
        self.quarantined.append(session)

    def recover(self, session):
        self.recover_calls += 1
        return {"cookies": {"token": "candidate"}}

    def validate(self, candidate):
        return self.validate_ok

    def commit(self, candidate):
        self.commit_calls += 1
        return SessionGeneration(ORIGIN, self.commit_calls, NOW)

    def resume_allowed(self, job, generation):
        return True

    def audit(self, event):
        self.events.append(event)


def _manager(provider, tracker=None, store=None):
    return SessionRecoveryManager(
        provider=provider, tracker=tracker, store=store or SessionStore()
    )


class TestSharedSession:
    """Dua job berbagi satu sesi — satu recovery, tanpa recovery-storm."""

    def test_second_job_reuses_session_without_new_recovery(self):
        store = SessionStore()
        store.publish(ORIGIN, SessionGeneration(ORIGIN, 1, NOW), {"cookies": {"t": "1"}})
        provider = StubProvider(healthy=True)  # detect → sesi sehat
        manager = _manager(provider, store=store)

        # "job A" dan "job B" sama-sama memastikan sesi origin yang sama
        decision_a = manager.ensure_session(ORIGIN, NOW)
        decision_b = manager.ensure_session(ORIGIN, NOW)

        assert decision_a.outcome == "recovered"
        assert decision_b.outcome == "recovered"
        # sesi yang sama dipakai bersama — TANPA recovery kedua
        assert decision_a.generation.generation == 1
        assert decision_b.generation.generation == 1
        assert provider.recover_calls == 0
        assert provider.commit_calls == 0

    def test_single_flight_skips_concurrent_recovery(self):
        provider = StubProvider(healthy=False)
        lock = RecoveryLock()
        # manager MEMAKAI lock yang sama dengan yang dipegang "recovery lain"
        manager = SessionRecoveryManager(provider=provider, lock=lock)
        assert lock.acquire(ORIGIN) is True

        decision = manager.ensure_session(ORIGIN, NOW)

        assert decision.outcome == "skipped_single_flight"
        assert provider.recover_calls == 0  # tidak menambah recovery baru
        lock.release(ORIGIN)


class TestPartialRecovery:
    """Kandidat diproduksi tetapi validasi gagal — tanpa sukses palsu."""

    def test_validate_failure_is_failed_never_success(self):
        store = SessionStore()
        store.publish(ORIGIN, SessionGeneration(ORIGIN, 1, NOW), {"cookies": {"t": "old"}})
        provider = StubProvider(healthy=False, validate_ok=False)
        manager = _manager(provider, tracker=RecoveryAttemptTracker(max_attempts=3), store=store)

        decision = manager.ensure_session(ORIGIN, NOW)

        # kriteria lulus C: TIDAK membuat state sukses palsu
        assert decision.outcome == "failed"
        assert decision.generation.generation == 1  # generasi lama tetap current
        # sesi lama dikarantina — state konsisten dengan keputusan
        assert manager.current(ORIGIN).state.value == "recovery_pending"
        assert provider.quarantined, "sesi lama tidak dikarantina"

    def test_retry_after_partial_recovery_succeeds_with_new_generation(self):
        store = SessionStore()
        store.publish(ORIGIN, SessionGeneration(ORIGIN, 1, NOW), {"cookies": {"t": "old"}})
        provider = StubProvider(healthy=False, validate_ok=False)
        tracker = RecoveryAttemptTracker(max_attempts=3)
        manager = _manager(provider, tracker=tracker, store=store)

        first = manager.ensure_session(ORIGIN, NOW)
        assert first.outcome == "failed"

        # recovery "berhasil" pada percobaan berikutnya (dalam anggaran)
        provider.validate_ok = True
        second = manager.ensure_session(ORIGIN, NOW)

        assert second.outcome == "recovered"
        assert second.generation.generation > 1  # generasi baru monotonic
        assert manager.current(ORIGIN).state.value == "active"
        assert provider.recover_calls == 2
        assert provider.commit_calls == 1

    def test_partial_then_budget_exhausted_needs_user(self):
        store = SessionStore()
        store.publish(ORIGIN, SessionGeneration(ORIGIN, 1, NOW), {"cookies": {"t": "old"}})
        provider = StubProvider(healthy=False, validate_ok=False)
        # max_attempts=2: kegagalan pertama masih "failed" (boleh retry),
        # kegagalan kedua menghabiskan anggaran → "needs_user"
        tracker = RecoveryAttemptTracker(max_attempts=2)
        manager = _manager(provider, tracker=tracker, store=store)

        first = manager.ensure_session(ORIGIN, NOW)   # attempt 1/2 gagal
        second = manager.ensure_session(ORIGIN, NOW)  # attempt 2/2 gagal → habis

        assert first.outcome == "failed"
        assert second.outcome == "needs_user"  # tidak pernah auto-lanjut (ACP §2.2)
        assert provider.recover_calls == 2     # recovery berbatas


class TestIdempotency:
    """Operasi yang dapat diulang tidak menduplikasi efek."""

    def test_recover_interrupted_twice_is_noop(self):
        repo = JobRepository()
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        repo.db_path = path
        repo._init_db()
        try:
            job = Job(job_id="idem-1", url="http://fixture.test/x")
            job.mark_started()
            repo.save_job(job)
            repo.start_attempt("idem-1", "idem-1-att-0", "curl_cffi")

            first = repo.recover_interrupted()
            events_after_first = len(repo.list_events("idem-1"))
            second = repo.recover_interrupted()
            events_after_second = len(repo.list_events("idem-1"))

            assert first == ["idem-1"]
            assert second == []  # idempoten: tidak memproses ulang
            assert events_after_second == events_after_first
        finally:
            os.unlink(path)

    def test_ensure_session_healthy_is_idempotent(self):
        store = SessionStore()
        store.publish(ORIGIN, SessionGeneration(ORIGIN, 5, NOW), {"cookies": {"t": "1"}})
        provider = StubProvider(healthy=True)
        manager = _manager(provider, store=store)

        generations = [
            manager.ensure_session(ORIGIN, NOW).generation.generation for _ in range(3)
        ]

        assert generations == [5, 5, 5]  # generasi sama — tanpa recovery baru
        assert provider.recover_calls == 0
        assert provider.commit_calls == 0

    def test_start_attempt_same_id_is_one_row(self):
        repo = JobRepository()
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        repo.db_path = path
        repo._init_db()
        try:
            repo.start_attempt("j1", "j1-att-0", "curl_cffi")
            repo.start_attempt("j1", "j1-att-0", "curl_cffi")  # ulang id sama
            assert len(repo.list_attempts("j1")) == 1
        finally:
            os.unlink(path)
