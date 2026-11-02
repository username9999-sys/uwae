"""SQLite-backed session store (pasca-roadmap, §5.1 INSTRUCTION.md).

Tabel ``sessions`` menyimpan metadata aman per origin: generasi berversi,
status, dan penanda waktu — sehingga disiplin generasi (job menyematkan
generasi; yang stale tidak sah) bertahan lintas restart proses.

Batas rahasia (§6.3: "Tidak ada kredensial mentah pada log dan artifact
metadata"): materi sesi (cookies/token) TIDAK pernah ditulis ke disk. Ia
hidup hanya di memori proses ini (``_live_sessions``); setelah restart,
entry dimuat dengan ``session=None`` dan protokol recovery (ACP §4)
meng-autentikasi ulang secara berbatas bila sesi dibutuhkan.

Kontrak identik dengan ``SessionStore`` (``current``/``current_generation``/
``publish``/``set_state``) — ``SessionRecoveryManager`` menggunakannya tanpa
perubahan; penyimpanan in-memory tetap menjadi default.
"""

import sqlite3
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from universal_web_acquisition.access.model import (
    SESSION_TRANSITIONS,
    SessionState,
    require_transition,
)
from universal_web_acquisition.session.manager import SessionEntry
from universal_web_acquisition.session.recovery import SessionGeneration


class SqliteSessionStore:
    """Penyimpanan sesi per origin yang tahan restart proses.

    - ``publish``  : COMMIT atomik generasi baru sebagai ACTIVE — transisi
      divalidasi terhadap ``SESSION_TRANSITIONS`` (republish saat ACTIVE
      ditolak, sama seperti store in-memory).
    - ``set_state``: transisi tervalidasi; generasi dipertahankan.
    - ``current``  : entry dengan materi sesi proses-hidup (``None`` setelah
      restart — lihat batas rahasia di docstring modul).
    """

    def __init__(self, db_path: str = "sessions.db"):
        self.db_path = db_path
        self._live_sessions: Dict[str, Any] = {}  # materi rahasia — proses hidup saja
        self._init_db()

    # -- infrastruktur -------------------------------------------------------

    def _init_db(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    origin TEXT PRIMARY KEY,
                    generation INTEGER NOT NULL,
                    generation_at TEXT NOT NULL,
                    state TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def _load(self, origin: str) -> Optional[Tuple[SessionGeneration, SessionState]]:
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                "SELECT generation, generation_at, state FROM sessions WHERE origin = ?",
                (origin,),
            )
            row = cursor.fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        generation, generation_at, state = row
        return (
            SessionGeneration(origin, int(generation), datetime.fromisoformat(generation_at)),
            SessionState(state),
        )

    def _write(self, origin: str, generation: SessionGeneration, state: SessionState) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO sessions
                    (origin, generation, generation_at, state, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    origin,
                    generation.generation,
                    generation.created_at.isoformat(),
                    state.value,
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    # -- kontrak SessionStore ------------------------------------------------

    def current(self, origin: str) -> Optional[SessionEntry]:
        loaded = self._load(origin)
        if loaded is None:
            return None
        generation, state = loaded
        return SessionEntry(
            generation=generation,
            state=state,
            session=self._live_sessions.get(origin),
        )

    def current_generation(self, origin: str) -> Optional[SessionGeneration]:
        loaded = self._load(origin)
        return loaded[0] if loaded else None

    def publish(self, origin: str, generation: SessionGeneration, session: Any) -> None:
        """COMMIT — publikasi atomik generasi baru sebagai ACTIVE."""
        loaded = self._load(origin)
        current_state = loaded[1] if loaded else SessionState.NEW
        require_transition(
            current_state, SessionState.ACTIVE, SESSION_TRANSITIONS, f"session[{origin}]"
        )
        self._write(origin, generation, SessionState.ACTIVE)
        self._live_sessions[origin] = session

    def set_state(self, origin: str, next_state: SessionState) -> None:
        """Transisi status tervalidasi terhadap tabel SESSION_TRANSITIONS."""
        loaded = self._load(origin)
        if loaded is None:
            raise KeyError(f"tidak ada sesi untuk origin {origin}")
        generation, state = loaded
        require_transition(state, next_state, SESSION_TRANSITIONS, f"session[{origin}]")
        self._write(origin, generation, next_state)
