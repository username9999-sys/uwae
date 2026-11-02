"""Benchmark model for the Universal Web Acquisition Engine."""

import enum
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from universal_web_acquisition.access.model import AccessState, ReasonCode


@dataclass
class BenchmarkResult:
    """Result of a benchmark run."""
    
    scenario_name: str
    engine: str  # "uwae" or "botasaurus"
    success: bool
    duration_ms: float
    memory_bytes: int
    timestamp: datetime = None
    error: Optional[str] = None
    
    def __post_init__(self):
        """Set timestamp if not provided."""
        if self.timestamp is None:
            self.timestamp = datetime.now()


class FailureClassification(enum.Enum):
    """Klasifikasi kegagalan benchmark yang berbatas (Mandatory Phase 2/6)."""

    NETWORK = "network"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    CHALLENGE = "challenge"
    AUTH_REQUIRED = "auth_required"
    ACCESS_DENIED = "access_denied"
    CONTENT_MISMATCH = "content_mismatch"
    CAPABILITY_MISSING = "capability_missing"
    BUDGET_EXHAUSTED = "budget_exhausted"
    UNKNOWN = "unknown"

    @classmethod
    def from_state(cls, state: AccessState) -> Optional["FailureClassification"]:
        """Klasifikasi dari state diagnosis — sumber paling akurat.

        ``ACCESS_GRANTED`` bukan kegagalan → None.
        """
        mapping = {
            AccessState.NETWORK_FAILURE: cls.NETWORK,
            AccessState.RATE_LIMITED: cls.RATE_LIMITED,
            AccessState.CHALLENGE_PRESENT: cls.CHALLENGE,
            AccessState.AUTH_REQUIRED: cls.AUTH_REQUIRED,
            AccessState.ACCESS_DENIED: cls.ACCESS_DENIED,
            AccessState.CONTENT_INVALID: cls.CONTENT_MISMATCH,
            AccessState.JAVASCRIPT_REQUIRED: cls.CONTENT_MISMATCH,
            AccessState.UNKNOWN: cls.UNKNOWN,
        }
        return mapping.get(state)

    @classmethod
    def from_reason_code(cls, reason: ReasonCode) -> "FailureClassification":
        """Klasifikasi kasar dari reason code — total (tidak pernah raise).

        ``HTTP_4XX`` ambigu (403 denial vs 404 missing) → UNKNOWN; pakai
        ``from_state`` bila state diagnosis tersedia.
        """
        mapping = {
            ReasonCode.DNS_FAILURE: cls.NETWORK,
            ReasonCode.TLS_ERROR: cls.NETWORK,
            ReasonCode.CONNECTION_ERROR: cls.NETWORK,
            ReasonCode.TIMEOUT: cls.TIMEOUT,
            ReasonCode.HTTP_429: cls.RATE_LIMITED,
            ReasonCode.CHALLENGE_DETECTED: cls.CHALLENGE,
            ReasonCode.LOGIN_FORM_PRESENT: cls.AUTH_REQUIRED,
            ReasonCode.AUTH_EXPIRED: cls.AUTH_REQUIRED,
            ReasonCode.CONTENT_INVALID: cls.CONTENT_MISMATCH,
            ReasonCode.VALIDATION_FAILED: cls.CONTENT_MISMATCH,
            ReasonCode.HTTP_5XX: cls.CONTENT_MISMATCH,
            ReasonCode.CAPABILITY_MISSING: cls.CAPABILITY_MISSING,
            ReasonCode.BUDGET_EXHAUSTED: cls.BUDGET_EXHAUSTED,
        }
        return mapping.get(reason, cls.UNKNOWN)


@dataclass(frozen=True)
class BenchmarkRecord:
    """Rekaman satu run benchmark (Mandatory Phase 2/6) — superset BenchmarkResult.

    Invarian: run sukses tidak membawa klasifikasi kegagalan. Timestamp
    disuplai pemanggil agar rekaman dapat direproduksi (§6.2).
    """

    record_id: str
    benchmark_id: str
    scenario_id: str
    engine: str
    engine_version: str
    success: bool
    duration_ms: float
    peak_memory_bytes: int
    attempts: int = 1
    classification: Optional[FailureClassification] = None
    observed_state: Optional[str] = None
    artifact_sha256: Optional[str] = None
    timestamp: Optional[datetime] = None
    notes: str = ""

    def __post_init__(self):
        if self.success and self.classification is not None:
            raise ValueError("run sukses tidak membawa klasifikasi kegagalan")
