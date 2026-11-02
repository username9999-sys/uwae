"""Session recovery contracts (Fase 2, Access Control Plane §4).

- ``SessionGeneration``: sessions are versioned per origin; jobs pin a
  generation and stale generations must never be used.
- ``SessionRecoveryProvider``: the 7-phase recovery protocol (detect,
  quarantine, recover, validate, commit, resume, audit).
- ``RecoveryLock``: single-flight per origin — prevents recovery storms when
  many jobs detect an expired session simultaneously.
- ``RecoveryAttemptTracker``: bounded recovery attempts per origin — the same
  boundedness rule as ADR-011 retries (lesson from E6).
"""

import threading
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, Protocol

MAX_RECOVERY_ATTEMPTS = 3


@dataclass(frozen=True)
class SessionGeneration:
    """Sesi berversi per origin. Job menyematkan generasi; yang stale tidak sah."""

    origin: str
    generation: int
    created_at: datetime

    def is_stale(self, current: "SessionGeneration") -> bool:
        """True bila generasi ini bukan generasi terkini untuk origin yang sama."""
        return self.origin != current.origin or self.generation < current.generation


class RecoveryPhase(Enum):
    """Tujuh tahap wajib protokol pemulihan sesi (ACP §4)."""

    DETECT = "detect"
    QUARANTINE = "quarantine"
    RECOVER = "recover"
    VALIDATE = "validate"
    COMMIT = "commit"
    RESUME = "resume"
    AUDIT = "audit"


class SessionRecoveryProvider(Protocol):
    """Protokol pemulihan sesi — mekanisme autentikasi resmi, tanpa asumsi alur.

    Kontrak (INSTRUCTION.md, ACP §4):
    - ``detect``      : bedakan expiry, logout, token invalid, dan gangguan jaringan.
    - ``quarantine``  : tandai sesi tidak boleh dipakai job baru.
    - ``recover``     : jalankan mekanisme autentikasi yang dikonfigurasi.
    - ``validate``    : pastikan sesi baru dapat mengakses resource target.
    - ``commit``      : publikasikan generasi sesi baru secara atomik.
    - ``resume_allowed``: lanjutkan hanya job yang aman (generasi tidak stale).
    - ``audit``       : catat hasil TANPA menyimpan kredensial mentah.
    """

    def detect(self, session: Any) -> bool: ...

    def quarantine(self, session: Any) -> None: ...

    def recover(self, session: Any) -> Any: ...

    def validate(self, candidate: Any) -> bool: ...

    def commit(self, candidate: Any) -> SessionGeneration: ...

    def resume_allowed(self, job: Any, generation: SessionGeneration) -> bool: ...

    def audit(self, event: Dict[str, str]) -> None: ...


class RecoveryLock:
    """Single-flight per origin: hanya satu recovery aktif pada satu waktu.

    Mencegah recovery storm — banyak job yang mendeteksi sesi kedaluwarsa
    bersamaan dan mencoba memulihkannya sekaligus.
    """

    def __init__(self):
        self._active: set = set()
        self._guard = threading.Lock()

    def acquire(self, origin: str) -> bool:
        with self._guard:
            if origin in self._active:
                return False
            self._active.add(origin)
            return True

    def release(self, origin: str) -> None:
        with self._guard:
            self._active.discard(origin)

    def is_active(self, origin: str) -> bool:
        with self._guard:
            return origin in self._active


class RecoveryAttemptTracker:
    """Pembatas percobaan recovery per origin — recovery juga BERBATAS (E6)."""

    def __init__(self, max_attempts: int = MAX_RECOVERY_ATTEMPTS):
        if max_attempts < 1:
            raise ValueError("max_attempts minimal 1")
        self._max = max_attempts
        self._counts: Dict[str, int] = {}

    def can_attempt(self, origin: str) -> bool:
        return self._counts.get(origin, 0) < self._max

    def record(self, origin: str) -> None:
        self._counts[origin] = self._counts.get(origin, 0) + 1

    def attempts(self, origin: str) -> int:
        return self._counts.get(origin, 0)

    def reset(self, origin: str) -> None:
        """Dipanggil setelah recovery sukses tervalidasi (COMMIT)."""
        self._counts.pop(origin, None)


@dataclass(frozen=True)
class RecoveryDecision:
    """Keputusan recovery yang dapat diaudit (tanpa kredensial mentah)."""

    origin: str
    phase: RecoveryPhase
    outcome: str  # "recovered" | "failed" | "needs_user" | "skipped_single_flight"
    generation: Optional[SessionGeneration]
    decided_at: datetime
    detail: str = ""
    attempts_used: int = 0
