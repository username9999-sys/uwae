"""SQLite session store tests (pasca-roadmap, §5.1 INSTRUCTION.md).

Yang diverifikasi:
- paritas kontrak dengan ``SessionStore`` in-memory (publikasi atomik,
  transisi tervalidasi, republish saat ACTIVE ditolak);
- generasi + status BERTAHAN lintas restart proses (store baru, file sama);
- materi rahasia tidak pernah menyentuh disk (batas §6.3) — setelah restart
  entry dimuat dengan ``session=None``;
- aturan resume generasi (G5) bekerja melalui ``SessionRecoveryManager``
  sungguhan di atas store persisten.
"""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from datetime import datetime

from universal_web_acquisition.access.model import InvalidTransition, SessionState
from universal_web_acquisition.session.manager import SessionRecoveryManager
from universal_web_acquisition.session.recovery import (
    RecoveryAttemptTracker,
    SessionGeneration,
)
from universal_web_acquisition.session.store_sqlite import SqliteSessionStore

NOW = datetime(2026, 10, 21, 12, 0, 0)


def _store():
    """SqliteSessionStore pada file sementara (jangan sentuh sessions.db proyek)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return SqliteSessionStore(db_path=path), path


class _StubProvider:
    """Provider protokol minimum untuk test integrasi manager."""

    def __init__(self, healthy=False):
        self.healthy = healthy
        self.events = []

    def detect(self, session):
        # Kontrak manager: True = masalah terdeteksi (perlu recovery),
        # False = sesi sehat. None (pasca-restart, batas rahasia) selalu
        # dianggap perlu recovery — protokol meng-autentikasi ulang.
        if session is None:
            return True
        return not self.healthy

    def quarantine(self, session):
        pass

    def recover(self, session):
        return {"token": "recovered"}

    def validate(self, candidate):
        return True

    def commit(self, candidate):
        return SessionGeneration("example.com", 4, NOW)

    def resume_allowed(self, job, generation):
        return True

    def audit(self, event):
        self.events.append(event)


class TestContractParity:
    """Paritas dengan SessionStore in-memory — disiplin yang sama."""

    def test_publish_and_current_roundtrip(self):
        store, path = _store()
        try:
            store.publish(
                "example.com", SessionGeneration("example.com", 1, NOW), {"token": "t1"}
            )
            entry = store.current("example.com")
            assert entry is not None
            assert entry.state is SessionState.ACTIVE
            assert entry.generation.generation == 1
            assert entry.session == {"token": "t1"}  # materi rahasia hidup di proses
        finally:
            os.unlink(path)

    def test_state_transition_persisted(self):
        store, path = _store()
        try:
            store.publish("example.com", SessionGeneration("example.com", 1, NOW), {})
            store.set_state("example.com", SessionState.EXPIRING)
            assert store.current("example.com").state is SessionState.EXPIRING
            # generasi dipertahankan oleh set_state
            assert store.current_generation("example.com").generation == 1
        finally:
            os.unlink(path)

    def test_direct_republish_while_active_rejected(self):
        store, path = _store()
        try:
            store.publish("example.com", SessionGeneration("example.com", 1, NOW), {})
            with pytest.raises(InvalidTransition):
                store.publish(
                    "example.com", SessionGeneration("example.com", 2, NOW), {}
                )
        finally:
            os.unlink(path)

    def test_invalid_transition_rejected(self):
        store, path = _store()
        try:
            store.publish("example.com", SessionGeneration("example.com", 1, NOW), {})
            with pytest.raises(InvalidTransition):
                store.set_state("example.com", SessionState.ACTIVE)  # ACTIVE→ACTIVE ilegal
        finally:
            os.unlink(path)

    def test_set_state_missing_origin_raises(self):
        store, path = _store()
        try:
            with pytest.raises(KeyError):
                store.set_state("ghost.example", SessionState.ACTIVE)
        finally:
            os.unlink(path)


class TestRestartPersistence:
    """State/generation bertahan lintas restart; rahasia tidak."""

    def test_generation_and_state_survive_restart(self):
        store1, path = _store()
        store1.publish(
            "example.com", SessionGeneration("example.com", 7, NOW), {"token": "secret"}
        )
        store1.set_state("example.com", SessionState.EXPIRING)

        # "restart": store baru pada file yang sama, memori kosong
        store2 = SqliteSessionStore(db_path=path)
        try:
            generation = store2.current_generation("example.com")
            assert generation is not None
            assert generation.generation == 7
            assert generation.created_at == NOW
            entry = store2.current("example.com")
            assert entry.state is SessionState.EXPIRING
            # batas rahasia: materi sesi tidak hidup lintas proses
            assert entry.session is None
        finally:
            os.unlink(path)

    def test_no_secrets_on_disk(self):
        store, path = _store()
        try:
            store.publish(
                "example.com",
                SessionGeneration("example.com", 1, NOW),
                {"token": "SUPER-SECRET-VALUE"},
            )
            with open(path, "rb") as f:
                raw = f.read()
            assert b"SUPER-SECRET-VALUE" not in raw
        finally:
            os.unlink(path)

    def test_transition_discipline_enforced_after_restart(self):
        # Status durabel berarti disiplin mesin status juga durabel:
        # republish ilegal tetap ditolak pada store pasca-restart.
        store1, path = _store()
        store1.publish("example.com", SessionGeneration("example.com", 1, NOW), {})
        store2 = SqliteSessionStore(db_path=path)
        try:
            with pytest.raises(InvalidTransition):
                store2.publish(
                    "example.com", SessionGeneration("example.com", 2, NOW), {}
                )
        finally:
            os.unlink(path)


class TestResumeRulesAcrossRestart:
    """Aturan resume generasi (G5) melalui manager di atas store persisten."""

    def test_fresh_pin_allowed_then_stale_after_recovery_commit(self):
        store1, path = _store()
        store1.publish("example.com", SessionGeneration("example.com", 3, NOW), {})
        pinned = store1.current_generation("example.com")

        # restart: manager baru di atas store persisten yang sama
        store2 = SqliteSessionStore(db_path=path)
        manager = SessionRecoveryManager(provider=_StubProvider(), store=store2)
        try:
            # generasi belum berubah → job ber-pin lama masih boleh lanjut
            assert manager.resume_allowed("example.com", pinned) is True

            # sesi kedaluwarsa (detect False) → protokol berjalan → COMMIT gen 4
            decision = manager.ensure_session("example.com", NOW)
            assert decision.outcome == "recovered"
            assert decision.generation.generation == 4

            # pin lama kini stale → resume ditolak
            assert manager.resume_allowed("example.com", pinned) is False
            # pin generasi baru → sah
            assert manager.resume_allowed("example.com", decision.generation) is True
        finally:
            os.unlink(path)

    def test_recovery_bounded_across_restart(self):
        # Anggaran recovery adalah properti tracker (proses-hidup); store
        # persisten tidak menghidupkan kembali anggaran — protokol tetap
        # berbatas setelah restart.
        store1, path = _store()
        store1.publish("example.com", SessionGeneration("example.com", 1, NOW), {})

        store2 = SqliteSessionStore(db_path=path)
        tracker = RecoveryAttemptTracker(max_attempts=1)
        manager = SessionRecoveryManager(
            provider=_StubProvider(), store=store2, tracker=tracker
        )
        try:
            first = manager.ensure_session("example.com", NOW)
            assert first.outcome == "recovered"  # percobaan pertama berhasil
            assert tracker.attempts("example.com") == 0  # reset setelah COMMIT
        finally:
            os.unlink(path)
