"""Concrete SessionRecoveryProvider implementations (A05, ACP §4).

``HTTPSessionRecoveryProvider``: jalur autentikasi resmi berbasis HTTP untuk
satu origin — sesi direpresentasikan sebagai cookie:

- ``detect``   : True = masalah terdeteksi (sesi tidak ada / tidak valid
                 terhadap resource terproteksi);
- ``recover``  : fetch endpoint login RESMI dan tangkap cookie yang
                 diterbitkan server — bukan bypass;
- ``validate`` : fetch resource terproteksi dengan kandidat — harus benar-
                 benar dapat diakses (validasi pascarecovery, §5.2);
- ``commit``   : publikasikan generasi baru (bertambah setiap commit);
- ``audit``    : tanpa kredensial — nilai cookie tidak pernah masuk payload
                 audit (§6.3).
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List

import httpx

from universal_web_acquisition.session.recovery import SessionGeneration


@dataclass
class HTTPSessionRecoveryProvider:
    """Provider pemulihan sesi berbasis HTTP (login resmi + resource terproteksi)."""

    origin: str
    login_url: str
    protected_url: str
    cookie_name: str
    timeout_seconds: float = 15.0
    audit_events: List[Dict[str, str]] = field(default_factory=list)
    _generation: int = 0

    def detect(self, session: Any) -> bool:
        """True = masalah terdeteksi (sesi tidak ada atau sudah tidak valid)."""
        return not self.validate(session)

    def quarantine(self, session: Any) -> None:
        # v1: tidak ada pencabutan sisi server — sesi lama hanya berhenti dipakai
        # (store menandai RECOVERY_PENDING, job baru tidak memakainya).
        return None

    def recover(self, session: Any) -> Any:
        """Jalur autentikasi resmi: endpoint login menerbitkan cookie sesi."""
        resp = httpx.get(
            self.login_url, timeout=self.timeout_seconds, follow_redirects=True
        )
        token = resp.cookies.get(self.cookie_name, "")
        return {"cookies": {self.cookie_name: token}}

    def validate(self, candidate: Any) -> bool:
        """Validasi pascarecovery: kandidat harus benar-benar mengakses resource."""
        if not candidate:
            return False
        try:
            resp = httpx.get(
                self.protected_url,
                cookies=candidate.get("cookies") or {},
                timeout=self.timeout_seconds,
                follow_redirects=True,
            )
        except httpx.HTTPError:
            return False
        return resp.status_code == 200

    def commit(self, candidate: Any) -> SessionGeneration:
        self._generation += 1
        return SessionGeneration(self.origin, self._generation, datetime.now())

    def resume_allowed(self, job: Any, generation: SessionGeneration) -> bool:
        return True

    def audit(self, event: Dict[str, str]) -> None:
        self.audit_events.append(event)
