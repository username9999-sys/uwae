"""Session recovery manager (roadmap step 6, Access Control Plane §4).

Orchestrates the 7-phase ``SessionRecoveryProvider`` protocol with the
guarantees mandated by INSTRUCTION.md:

- **Single-flight per origin** (``RecoveryLock``): when two jobs detect an
  expired session simultaneously, exactly one recovery runs; the other gets
  ``skipped_single_flight`` instead of a recovery storm.
- **Bounded attempts** (``RecoveryAttemptTracker``): recovery is capped — the
  E6 anti-pattern (unbounded retry) is impossible by construction. When the
  budget is exhausted the outcome is ``needs_user`` and recovery never
  continues automatically (NEEDS_USER is never auto-resolved, ACP §2.2).
- **Versioned sessions** (``SessionGeneration``): jobs pin a generation;
  stale generations are denied resume.
- **Audit without credentials**: every phase transition is audited through the
  provider with sanitized payloads only.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from universal_web_acquisition.access.model import (
    SESSION_TRANSITIONS,
    SessionState,
    require_transition,
)
from universal_web_acquisition.session.recovery import (
    RecoveryAttemptTracker,
    RecoveryDecision,
    RecoveryLock,
    RecoveryPhase,
    SessionGeneration,
    SessionRecoveryProvider,
)

logger = logging.getLogger(__name__)


@dataclass
class SessionEntry:
    """Sesi aktif satu origin: generasi berversi + status + objek sesi opaque."""

    generation: SessionGeneration
    state: SessionState
    session: Any  # cookies/token — tidak pernah masuk payload audit


class SessionStore:
    """Penyimpanan sesi per origin — publikasi atomik, transisi tervalidasi.

    In-memory untuk Fase 2; persistence (SQLite) menyusul tanpa mengubah
    kontrak manager.
    """

    def __init__(self):
        self._entries: Dict[str, SessionEntry] = {}

    def current(self, origin: str) -> Optional[SessionEntry]:
        return self._entries.get(origin)

    def current_generation(self, origin: str) -> Optional[SessionGeneration]:
        entry = self._entries.get(origin)
        return entry.generation if entry else None

    def publish(self, origin: str, generation: SessionGeneration, session: Any) -> None:
        """COMMIT — publikasi atomik generasi baru sebagai ACTIVE."""
        entry = self._entries.get(origin)
        current_state = entry.state if entry else SessionState.NEW
        require_transition(current_state, SessionState.ACTIVE, SESSION_TRANSITIONS, f"session[{origin}]")
        self._entries[origin] = SessionEntry(
            generation=generation, state=SessionState.ACTIVE, session=session
        )

    def set_state(self, origin: str, next_state: SessionState) -> None:
        """Transisi status tervalidasi terhadap tabel SESSION_TRANSITIONS."""
        entry = self._entries.get(origin)
        if entry is None:
            raise KeyError(f"tidak ada sesi untuk origin {origin}")
        require_transition(entry.state, next_state, SESSION_TRANSITIONS, f"session[{origin}]")
        self._entries[origin] = SessionEntry(
            generation=entry.generation, state=next_state, session=entry.session
        )


class SessionRecoveryManager:
    """Orkestrator protokol 7-tahap: single-flight, berbatas, audit tanpa kredensial."""

    def __init__(
        self,
        provider: SessionRecoveryProvider,
        lock: Optional[RecoveryLock] = None,
        tracker: Optional[RecoveryAttemptTracker] = None,
        store: Optional[SessionStore] = None,
    ):
        self._provider = provider
        self._lock = lock if lock is not None else RecoveryLock()
        self._tracker = tracker if tracker is not None else RecoveryAttemptTracker()
        self._store = store if store is not None else SessionStore()

    # -- query ---------------------------------------------------------------

    def current(self, origin: str) -> Optional[SessionEntry]:
        """Entry sesi aktif (termasuk materi sesi proses-hidup) untuk origin.

        Dipakai worker (A05) untuk mengambil cookies sesi yang mengalir ke
        setiap attempt; setelah restart materi sesi ``None`` (batas rahasia).
        """
        return self._store.current(origin)

    def current_generation(self, origin: str) -> Optional[SessionGeneration]:
        return self._store.current_generation(origin)

    def resume_allowed(self, origin: str, pinned: Optional[SessionGeneration]) -> bool:
        """Job hanya boleh melanjutkan bila generasi yang ia sematkan masih segar."""
        if pinned is None:
            return True  # job tidak bergantung pada sesi
        current = self._store.current_generation(origin)
        if current is None:
            return False
        return not pinned.is_stale(current)

    # -- protokol ------------------------------------------------------------

    def ensure_session(self, origin: str, decided_at: datetime) -> RecoveryDecision:
        """Pastikan origin punya sesi valid; jalankan protokol bila perlu.

        Outcome:
        - ``recovered``              — sesi sehat atau berhasil dipulihkan
        - ``failed``                 — kandidat gagal validasi; boleh dicoba ulang
                                       selama anggaran attempt tersedia
        - ``needs_user``             — anggaran habis; recovery tidak boleh
                                       dilanjutkan otomatis (ACP §2.2)
        - ``skipped_single_flight``  — recovery lain sedang berjalan untuk origin
        """
        if not self._lock.acquire(origin):
            decision = RecoveryDecision(
                origin=origin,
                phase=RecoveryPhase.RECOVER,
                outcome="skipped_single_flight",
                generation=self._store.current_generation(origin),
                decided_at=decided_at,
                detail="recovery lain sedang berjalan untuk origin ini (anti recovery-storm)",
                attempts_used=self._tracker.attempts(origin),
            )
            self._provider.audit(self._sanitize(decision))
            return decision

        try:
            return self._run_protocol(origin, decided_at)
        finally:
            self._lock.release(origin)

    # -- internal ------------------------------------------------------------

    def _run_protocol(self, origin: str, decided_at: datetime) -> RecoveryDecision:
        entry = self._store.current(origin)

        # DETECT — bedakan expiry/logout/token-invalid/gangguan jaringan
        if entry is not None and not self._provider.detect(entry.session):
            # Sesi sehat; bila sebelumnya terkarantina (recovery parsial lalu
            # deteksi sehat), kembalikan ke ACTIVE agar state konsisten dengan
            # keputusan "recovered" — tanpa state sukses palsu (kriteria lulus C).
            if entry.state is SessionState.RECOVERY_PENDING:
                self._store.set_state(origin, SessionState.ACTIVE)
            self._audit(origin, RecoveryPhase.DETECT, "session_healthy", decided_at)
            return RecoveryDecision(
                origin=origin,
                phase=RecoveryPhase.DETECT,
                outcome="recovered",
                generation=entry.generation,
                decided_at=decided_at,
                detail="sesi masih valid — tidak perlu pemulihan",
                attempts_used=self._tracker.attempts(origin),
            )

        # Anggaran attempt habis → NEEDS_USER; recovery tidak boleh lanjut otomatis.
        if not self._tracker.can_attempt(origin):
            self._audit(origin, RecoveryPhase.RECOVER, "attempts_exhausted", decided_at)
            return RecoveryDecision(
                origin=origin,
                phase=RecoveryPhase.RECOVER,
                outcome="needs_user",
                generation=self._store.current_generation(origin),
                decided_at=decided_at,
                detail="anggaran recovery habis → NEEDS_USER (tidak pernah auto-lanjut)",
                attempts_used=self._tracker.attempts(origin),
            )

        # QUARANTINE — sesi lama tidak boleh dipakai job baru selama pemulihan.
        # Idempoten: sesi yang sudah RECOVERY_PENDING (retry pasca-kegagalan
        # parsial) tidak ditransisi ulang — RECOVERY_PENDING→RECOVERY_PENDING
        # bukan transisi sah menurut SESSION_TRANSITIONS.
        if entry is not None:
            self._provider.quarantine(entry.session)
            if entry.state is not SessionState.RECOVERY_PENDING:
                self._store.set_state(origin, SessionState.RECOVERY_PENDING)
            self._audit(origin, RecoveryPhase.QUARANTINE, "quarantined", decided_at)

        self._tracker.record(origin)

        # RECOVER — mekanisme autentikasi resmi yang dikonfigurasi.
        candidate = self._provider.recover(entry.session if entry else None)
        self._audit(origin, RecoveryPhase.RECOVER, "candidate_produced", decided_at)

        # VALIDATE — kandidat harus benar-benar dapat mengakses resource target.
        if not self._provider.validate(candidate):
            self._audit(origin, RecoveryPhase.VALIDATE, "candidate_invalid", decided_at)
            exhausted = not self._tracker.can_attempt(origin)
            return RecoveryDecision(
                origin=origin,
                phase=RecoveryPhase.VALIDATE,
                outcome="needs_user" if exhausted else "failed",
                generation=self._store.current_generation(origin),
                decided_at=decided_at,
                detail=(
                    "validasi kandidat gagal & anggaran habis → NEEDS_USER"
                    if exhausted
                    else "validasi kandidat gagal — boleh dicoba ulang dalam anggaran"
                ),
                attempts_used=self._tracker.attempts(origin),
            )

        # COMMIT — publikasi atomik generasi baru; job ber-generasi lama stale.
        # Monotonisitas lintas store: provider tidak mengetahui generasi
        # terkini, maka manager menjamin generasi baru SELALU lebih tinggi
        # (ACP: generasi stale tidak sah — tidak boleh ditimpa dengan nomor
        # yang sama atau lebih rendah).
        generation = self._provider.commit(candidate)
        current = self._store.current_generation(origin)
        if current is not None and generation.generation <= current.generation:
            generation = SessionGeneration(
                origin, current.generation + 1, generation.created_at
            )
        self._store.publish(origin, generation, candidate)
        self._tracker.reset(origin)
        self._audit(origin, RecoveryPhase.COMMIT, "recovered", decided_at)

        return RecoveryDecision(
            origin=origin,
            phase=RecoveryPhase.COMMIT,
            outcome="recovered",
            generation=generation,
            decided_at=decided_at,
            detail="sesi baru tervalidasi dan dipublikasikan",
            attempts_used=self._tracker.attempts(origin),
        )

    # -- audit ---------------------------------------------------------------

    @staticmethod
    def _sanitize(decision: RecoveryDecision) -> Dict[str, str]:
        """Payload audit: metadata saja — tanpa kredensial/isi sesi."""
        return {
            "origin": decision.origin,
            "phase": decision.phase.value,
            "outcome": decision.outcome,
            "generation": str(decision.generation.generation) if decision.generation else "none",
            "detail": decision.detail,
        }

    def _audit(self, origin: str, phase: RecoveryPhase, outcome: str, decided_at: datetime) -> None:
        self._provider.audit(
            {
                "origin": origin,
                "phase": phase.value,
                "outcome": outcome,
                "at": decided_at.isoformat(),
            }
        )
