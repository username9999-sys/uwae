"""Access Control Plane data contracts (Fase 2).

Implements the contracts specified in INSTRUCTION.md (Access Control Plane,
Engineering Specification v2) and ADR-011:

- Three independent state machines: origin, session, job (job states live in
  ``core.job_model``).
- Observation/hypothesis separation: an HTTP 403 is an observation;
  ACCESS_DENIED is a hypothesis.
- Bounded reason codes: every terminal transition carries one.
- Consistency rules enforced in code, not convention.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, Optional, Set, Tuple

from universal_web_acquisition.core.job_model import Job, JobStatus


class InvalidTransition(Exception):
    """Raised when a state transition is not allowed by its machine."""


# ---------------------------------------------------------------------------
# State machines
# ---------------------------------------------------------------------------


class OriginState(Enum):
    """Kondisi umum suatu origin (bukan kondisi sesi atau job)."""

    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    RATE_LIMITED = "rate_limited"
    AUTH_REQUIRED = "auth_required"
    DENIED = "denied"


class SessionState(Enum):
    """Kondisi satu sesi tertentu — independen dari kondisi origin."""

    NEW = "new"
    ACTIVE = "active"
    EXPIRING = "expiring"
    RECOVERY_PENDING = "recovery_pending"
    INVALID = "invalid"
    CLOSED = "closed"


ORIGIN_TRANSITIONS: Dict[OriginState, Set[OriginState]] = {
    OriginState.UNKNOWN: {
        OriginState.HEALTHY,
        OriginState.DEGRADED,
        OriginState.RATE_LIMITED,
        OriginState.AUTH_REQUIRED,
        OriginState.DENIED,
    },
    OriginState.HEALTHY: {
        OriginState.DEGRADED,
        OriginState.RATE_LIMITED,
        OriginState.AUTH_REQUIRED,
        OriginState.DENIED,
        OriginState.UNKNOWN,
    },
    OriginState.DEGRADED: {
        OriginState.HEALTHY,
        OriginState.RATE_LIMITED,
        OriginState.AUTH_REQUIRED,
        OriginState.DENIED,
    },
    OriginState.RATE_LIMITED: {
        OriginState.DEGRADED,
        OriginState.HEALTHY,
        OriginState.DENIED,
    },
    OriginState.AUTH_REQUIRED: {
        OriginState.HEALTHY,
        OriginState.DEGRADED,
        OriginState.DENIED,
    },
    # DENIED tidak boleh otomatis diatasi dengan mengulang request melalui
    # semua transport (aturan konsistensi ACP) — tidak ada transisi keluar.
    OriginState.DENIED: set(),
}

SESSION_TRANSITIONS: Dict[SessionState, Set[SessionState]] = {
    SessionState.NEW: {SessionState.ACTIVE, SessionState.INVALID, SessionState.CLOSED},
    SessionState.ACTIVE: {
        SessionState.EXPIRING,
        SessionState.RECOVERY_PENDING,
        SessionState.INVALID,
        SessionState.CLOSED,
    },
    SessionState.EXPIRING: {
        SessionState.ACTIVE,
        SessionState.RECOVERY_PENDING,
        SessionState.INVALID,
    },
    SessionState.RECOVERY_PENDING: {SessionState.ACTIVE, SessionState.INVALID},
    SessionState.INVALID: {SessionState.CLOSED},
    SessionState.CLOSED: set(),
}


def can_transition(current: Enum, next_state: Enum, table: Dict[Enum, Set[Enum]]) -> bool:
    return next_state in table.get(current, set())


def require_transition(
    current: Enum, next_state: Enum, table: Dict[Enum, Set[Enum]], what: str
) -> None:
    if not can_transition(current, next_state, table):
        raise InvalidTransition(f"{what}: {current.value} -> {next_state.value} tidak diizinkan")


# ---------------------------------------------------------------------------
# Observation / hypothesis / assessment
# ---------------------------------------------------------------------------


class AccessState(Enum):
    """Keadaan akses hasil klasifikasi (Spec v2 §4.1) — sembilan nilai berbatas.

    Ini adalah OUTPUT classifier per attempt. Berbeda dari OriginState
    (kondisi origin yang bertahan lintas attempt) dan dari Hypothesis
    (penjelasan kandidat atas observasi).
    """

    ACCESS_GRANTED = "access_granted"
    AUTH_REQUIRED = "auth_required"
    RATE_LIMITED = "rate_limited"
    CHALLENGE_PRESENT = "challenge_present"
    JAVASCRIPT_REQUIRED = "javascript_required"
    CONTENT_INVALID = "content_invalid"
    NETWORK_FAILURE = "network_failure"
    ACCESS_DENIED = "access_denied"
    UNKNOWN = "unknown"


class Hypothesis(Enum):
    """Hipotesis tentang kondisi akses — dipisahkan dari observasi mentah."""

    ACCESS_GRANTED = "access_granted"
    RATE_LIMITED = "rate_limited"
    ACCESS_DENIED = "access_denied"
    CHALLENGE_PRESENT = "challenge_present"
    AUTH_REQUIRED = "auth_required"
    JAVASCRIPT_REQUIRED = "javascript_required"
    APPLICATION_ERROR = "application_error"
    NETWORK_FAILURE = "network_failure"
    CONTENT_MISMATCH = "content_mismatch"
    UNKNOWN = "unknown"


class ReasonCode(Enum):
    """Kumpulan reason code berbatas. Setiap transisi terminal wajib membawa satu."""

    OK = "ok"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    DNS_FAILURE = "dns_failure"
    CONNECTION_ERROR = "connection_error"
    TLS_ERROR = "tls_error"
    HTTP_4XX = "http_4xx"
    HTTP_429 = "http_429"
    HTTP_5XX = "http_5xx"
    CHALLENGE_DETECTED = "challenge_detected"
    LOGIN_FORM_PRESENT = "login_form_present"
    AUTH_EXPIRED = "auth_expired"
    CONTENT_INVALID = "content_invalid"
    VALIDATION_FAILED = "validation_failed"
    BUDGET_EXHAUSTED = "budget_exhausted"
    CAPABILITY_MISSING = "capability_missing"
    NEEDS_USER = "needs_user"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Observation:
    """Fakta terukur (mis. status 403) — bukan hipotesis. Nilai wajib ter-redaksi."""

    observation_id: str
    signal: str  # mis. "http.status", "body.marker", "tls.error"
    value: str  # nilai ter-redaksi, tanpa kredensial
    recorded_at: datetime
    source: str  # transport_id / validator id


@dataclass(frozen=True)
class AccessAssessment:
    """Keputusan classifier atas sekumpulan observasi.

    ``state``/``recommended_action``/``retry_after_seconds`` melengkapi
    kontrak Spec v2 §4.1; field lama (``hypothesis`` dll.) dipertahankan.
    """

    assessment_id: str
    job_id: str
    attempt_id: str
    transport_id: str
    observations: Tuple[Observation, ...]
    hypothesis: Hypothesis
    confidence: float
    reason_code: ReasonCode
    classifier_version: str
    decided_at: datetime
    state: AccessState = AccessState.UNKNOWN
    recommended_action: str = ""
    retry_after_seconds: Optional[float] = None

    def __post_init__(self):
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence harus dalam 0..1")
        if not self.observations:
            raise ValueError("assessment tanpa observasi tidak sah (bukti wajib)")


@dataclass(frozen=True)
class EvidenceLineage:
    """job -> attempt -> transport + observasi + keputusan; dapat ditelusuri penuh."""

    job_id: str
    attempt_id: str
    transport_id: str
    observation_ids: Tuple[str, ...]
    classifier_version: str
    assessment_id: str
    strategy_decision: str
    validation_result: str


# ---------------------------------------------------------------------------
# Job consistency rules (ACP §2.2) — dipaksakan terhadap core.job_model.Job
# ---------------------------------------------------------------------------


def assert_terminal_reason(job: Job, reason_code: ReasonCode) -> None:
    """Transisi terminal wajib membawa reason code yang konsisten dengan status."""
    if not job.is_terminal():
        raise ValueError(f"job {job.job_id} belum terminal ({job.status.value})")
    if job.status is JobStatus.FAILED and reason_code is ReasonCode.OK:
        raise ValueError("FAILED wajib reason code selain OK")
    if job.status is JobStatus.SUCCEEDED and reason_code is not ReasonCode.OK:
        raise ValueError("SUCCEEDED hanya boleh membawa reason code OK")


def assert_retry_wait_has_trigger(retry_at: Optional[datetime], reason_code: ReasonCode) -> None:
    """RETRY_WAIT wajib memiliki waktu/kondisi pemicu berikutnya."""
    if reason_code is not ReasonCode.OK and retry_at is None:
        raise ValueError("RETRY_WAIT wajib memiliki waktu/kondisi pemicu berikutnya")


def assert_needs_user_not_auto_resolved(current_status: JobStatus, next_status: JobStatus) -> None:
    """NEEDS_USER tidak boleh berubah menjadi sukses hanya karena waktu berlalu."""
    if current_status is JobStatus.NEEDS_USER and next_status is JobStatus.SUCCEEDED:
        raise ValueError("NEEDS_USER tidak boleh auto-resolve menjadi SUCCEEDED")
