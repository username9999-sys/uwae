"""Typed HTTP transport contracts (Mandatory Phase 2 — INSTRUCTION.md).

``RequestSpec`` adalah deskripsi deklaratif satu percobaan HTTP;
``ResponseMetadata`` adalah metadata respons TANPA body (body hidup di
``Artifact``/``RawResponse``). Keduanya frozen — kontrak tidak boleh
diam-diam diubah setelah dibuat.

Aturan mandat terkait: "All transport capabilities must be verified on the
actual runtime. Do not claim HTTP/2, HTTP/3, browser execution, streaming,
or session support without an executable test." — ``TransportCapability``
default tidak mengklaim apa pun (registry.py); klaim http2/http3/brotli
wajib didukung bukti eksekusi (E5).
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class RequestSpec:
    """Spesifikasi satu permintaan HTTP — deklaratif dan dapat diaudit."""

    url: str
    method: str = "GET"
    headers: Dict[str, str] = field(default_factory=dict)
    cookies: Dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 30.0
    max_bytes: Optional[int] = None
    range: Optional[Tuple[int, int]] = None  # (start, end) inklusif — A09
    body: Optional[bytes] = None  # payload untuk method non-GET (POST/PUT/...)

    def __post_init__(self):
        if not self.url.startswith(("http://", "https://")):
            raise ValueError("url harus http:// atau https://")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds harus > 0")
        if self.max_bytes is not None and self.max_bytes <= 0:
            raise ValueError("max_bytes harus > 0 bila diset")
        if self.range is not None:
            start, end = self.range
            if not (0 <= start <= end):
                raise ValueError("range harus 0 <= start <= end")
        # Method dinormalisasi: "post" dan "POST" harus menjadi permintaan
        # yang sama di jalur cache dan resume, bukan dua request berbeda.
        method = (self.method or "").strip().upper()
        if not method:
            raise ValueError("method tidak boleh kosong")
        object.__setattr__(self, "method", method)


@dataclass(frozen=True)
class ResponseMetadata:
    """Metadata respons tanpa body — untuk diagnosis dan benchmark."""

    status_code: int
    headers: Dict[str, str] = field(default_factory=dict)
    final_url: str = ""
    elapsed_ms: float = 0.0
    content_length: Optional[int] = None
    content_type: Optional[str] = None

    def header(self, name: str) -> Optional[str]:
        """Lookup header case-insensitive (kapitalisasi antar-library beda)."""
        lowered = name.lower()
        for key, value in self.headers.items():
            if key.lower() == lowered:
                return value
        return None
