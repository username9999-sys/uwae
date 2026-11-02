"""Transport registry and bounded-retry contracts (Fase 2, ADR-011).

- ``TransportCapability``: capability metadata per adapter (ADR-011 decision 2).
- ``RetryPolicy``: bounded retry by construction — unbounded loops are rejected
  (the baseline's unbounded ``while True`` is the reproduced anti-pattern, E6).
- ``TransportRegistry``: capability-based adapter selection for the access
  assessment (never hardcode a transport).
"""

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional

from universal_web_acquisition.access.model import ReasonCode


@dataclass(frozen=True)
class TransportCapability:
    """Kapabilitas yang diiklankan sebuah transport adapter."""

    tls_fingerprint: bool = False
    http2: bool = False
    http3: bool = False
    brotli: bool = False
    supports_async: bool = False


@dataclass(frozen=True)
class RetryPolicy:
    """Kebijakan retry BERBATAS.

    Aturan (ADR-011 decision 3):
    - ``max_retries`` terbatas 0..10 — tidak ada loop tanpa akhir.
    - ``next_delay_seconds`` mengembalikan ``None`` ketika anggaran retry habis;
      pemanggil wajib berhenti, bukan mengulang tanpa batas.
    - Hanya reason code yang terdaftar di ``retryable`` yang boleh di-retry.
    """

    max_retries: int = 3
    base_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 60.0
    retryable: FrozenSet[ReasonCode] = frozenset(
        {
            ReasonCode.TIMEOUT,
            ReasonCode.DNS_FAILURE,
            ReasonCode.CONNECTION_ERROR,
            ReasonCode.TLS_ERROR,
            ReasonCode.HTTP_429,
            ReasonCode.HTTP_5XX,
        }
    )

    def __post_init__(self):
        if not (0 <= self.max_retries <= 10):
            raise ValueError("max_retries harus 0..10 (retry tanpa batas dilarang)")
        if self.base_backoff_seconds <= 0:
            raise ValueError("base_backoff_seconds harus > 0")
        if self.max_backoff_seconds < self.base_backoff_seconds:
            raise ValueError("max_backoff_seconds tidak boleh < base_backoff_seconds")

    def next_delay_seconds(self, attempt: int) -> Optional[float]:
        """Delay untuk attempt ke-``attempt`` (0-based); ``None`` jika anggaran habis."""
        if attempt > self.max_retries:
            return None
        delay = self.base_backoff_seconds * (2 ** attempt)
        return min(delay, self.max_backoff_seconds)

    def is_retryable(self, reason_code: ReasonCode) -> bool:
        return reason_code in self.retryable


class TransportRegistry:
    """Registry adapter berdasarkan nama + kapabilitas yang diiklankan.

    Adapter yang didaftarkan harus mengekspos kontrak ADR-003
    (``acquire``/``can_handle``); kapabilitas dideklarasikan terpisah agar
    kontrak tetap bebas dari detail library.
    """

    def __init__(self):
        self._adapters: Dict[str, object] = {}
        self._capabilities: Dict[str, TransportCapability] = {}
        self._order: List[str] = []  # urutan registrasi = prioritas (ADR-011: curl_cffi dulu)

    def register(self, name: str, adapter: object, capabilities: TransportCapability) -> None:
        if name in self._adapters:
            raise ValueError(f"transport sudah terdaftar: {name}")
        self._adapters[name] = adapter
        self._capabilities[name] = capabilities
        self._order.append(name)

    def get(self, name: str) -> Optional[object]:
        return self._adapters.get(name)

    def capabilities(self, name: str) -> Optional[TransportCapability]:
        return self._capabilities.get(name)

    def names(self) -> List[str]:
        return sorted(self._adapters)

    def ordered_names(self) -> List[str]:
        """Nama adapter dalam urutan registrasi (prioritas pemilihan)."""
        return list(self._order)

    def select(self, required: TransportCapability) -> List[str]:
        """Nama adapter yang memenuhi SEMUA kapabilitas yang diminta.

        Pemilihan dilakukan access assessment berdasarkan bukti per-origin;
        registry hanya menyaring berdasarkan kapabilitas.
        """
        required_set = {k for k, v in required.__dict__.items() if v}
        matched = []
        for name, caps in self._capabilities.items():
            owned = {k for k, v in caps.__dict__.items() if v}
            if required_set <= owned:
                matched.append(name)
        return sorted(matched)
