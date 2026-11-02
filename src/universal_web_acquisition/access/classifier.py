"""Deterministic access classifier (roadmap step 4, Spec v2 §3–§4.1).

Implements the evaluation order mandated by INSTRUCTION.md §3.1 exactly:

    network_error → explicit_rate_limit → explicit_auth_required →
    explicit_access_denial → challenge_evidence → target_content_valid →
    javascript_evidence → response_received → unknown

Design rules (Spec v2 + Access Control Plane):

- Deterministic rules only — no ML, no per-site heuristics (§3: "mulailah dari
  aturan deterministik yang hasilnya dapat diverifikasi").
- Observations and hypotheses stay separated: an HTTP 403 is an observation;
  ACCESS_DENIED is one hypothesis among several (§3.1).
- Bounded signal vocabulary: the classifier ignores signals it does not know,
  so an unrecognized observation can never silently produce a success state.
- Confidence is a fixed categorical constant per rule (§3.2: "gunakan kategori
  keyakinan dan reason code terlebih dahulu") — calibration against a labeled
  corpus is explicitly deferred and tracked in ADR-012.
- Pure function: ids and ``decided_at`` are supplied by the caller so results
  are reproducible bit-for-bit (Milestone B pass criterion).
"""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, Optional, Sequence, Tuple

from universal_web_acquisition.access.calibration import CalibrationTable
from universal_web_acquisition.access.model import (
    AccessAssessment,
    AccessState,
    Hypothesis,
    Observation,
    ReasonCode,
)

CLASSIFIER_VERSION = "classifier-1.0.0"

# Confidence categories (§3.2) — fixed constants pending calibration against a
# labeled corpus. Never fabricate finer-grained probabilities before that.
CONFIDENCE_HIGH = 0.95
CONFIDENCE_MEDIUM = 0.75
CONFIDENCE_LOW = 0.35


class Signal:
    """Kosakata sinyal observasi berbatas yang dipahami classifier v1.

    Nilai yang diharapkan per sinyal:

    - ``http.status``               — kode status sebagai string angka
    - ``http.header.retry-after``   — delta-seconds atau HTTP-date
    - ``body.marker.login-form``    — ``present``
    - ``body.marker.challenge``     — nama signature (mis. ``cf-mitigated``)
    - ``body.marker.target``        — ``found`` / ``missing`` (satu observasi
      per marker target yang diharapkan validator)
    - ``js.required``               — ``true``
    - ``network.error``             — ``dns`` / ``tls`` / ``timeout`` / ``connection``
    - ``cache.hit``                 — ``hit`` (respons berasal dari cache run
      ini — bukti transparansi, BUKAN input diagnosis; urutan evaluasi §3.1
      tidak menyentuhnya)
    """

    HTTP_STATUS = "http.status"
    RETRY_AFTER = "http.header.retry-after"
    LOGIN_FORM = "body.marker.login-form"
    CHALLENGE = "body.marker.challenge"
    TARGET_MARKER = "body.marker.target"
    JS_REQUIRED = "js.required"
    NETWORK_ERROR = "network.error"
    CACHE_HIT = "cache.hit"


_NETWORK_REASON: Dict[str, ReasonCode] = {
    "dns": ReasonCode.DNS_FAILURE,
    "tls": ReasonCode.TLS_ERROR,
    "timeout": ReasonCode.TIMEOUT,
    "connection": ReasonCode.CONNECTION_ERROR,
}

_STATE_HYPOTHESIS: Dict[AccessState, Hypothesis] = {
    AccessState.ACCESS_GRANTED: Hypothesis.ACCESS_GRANTED,
    AccessState.AUTH_REQUIRED: Hypothesis.AUTH_REQUIRED,
    AccessState.RATE_LIMITED: Hypothesis.RATE_LIMITED,
    AccessState.CHALLENGE_PRESENT: Hypothesis.CHALLENGE_PRESENT,
    AccessState.JAVASCRIPT_REQUIRED: Hypothesis.JAVASCRIPT_REQUIRED,
    AccessState.CONTENT_INVALID: Hypothesis.CONTENT_MISMATCH,
    AccessState.NETWORK_FAILURE: Hypothesis.NETWORK_FAILURE,
    AccessState.ACCESS_DENIED: Hypothesis.ACCESS_DENIED,
    AccessState.UNKNOWN: Hypothesis.UNKNOWN,
}

_STATE_ACTION: Dict[AccessState, str] = {
    AccessState.ACCESS_GRANTED: "persist_result",
    AccessState.AUTH_REQUIRED: "reauthenticate_or_request_user",
    AccessState.RATE_LIMITED: "respect_retry_after",
    AccessState.CHALLENGE_PRESENT: "authorized_challenge_workflow",
    AccessState.JAVASCRIPT_REQUIRED: "check_browser_capability",
    AccessState.CONTENT_INVALID: "inspect_content_and_target",
    AccessState.NETWORK_FAILURE: "diagnose_network_before_retry",
    AccessState.ACCESS_DENIED: "stop_or_use_authorized_access",
    AccessState.UNKNOWN: "collect_more_evidence",
}


def _latest(observations: Tuple[Observation, ...], signal: str) -> Optional[Observation]:
    """Observasi terakhir untuk satu sinyal (urutan tuple = urutan waktu)."""
    found = None
    for obs in observations:
        if obs.signal == signal:
            found = obs
    return found


def _has(observations: Tuple[Observation, ...], signal: str) -> bool:
    return any(obs.signal == signal for obs in observations)


def _int_status(observations: Tuple[Observation, ...]) -> Optional[int]:
    obs = _latest(observations, Signal.HTTP_STATUS)
    if obs is None:
        return None
    try:
        return int(obs.value.strip())
    except ValueError:
        return None


def parse_retry_after(raw: Optional[str], now: datetime) -> Optional[float]:
    """Parsing deterministik header Retry-After (RFC 7231 §7.1.3).

    Menerima delta-seconds atau HTTP-date. Tanggal di masa lalu di-clamp ke
    0.0; nilai yang tidak dapat diurai mengembalikan None (planner memutuskan
    backoff sendiri). ``now`` disuplai pemanggil agar murni deterministik.
    """
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        seconds = float(text)
    except ValueError:
        try:
            when = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
        if when is None:
            return None
        if when.tzinfo is not None and now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        delta = (when - now).total_seconds()
        return max(delta, 0.0)
    if seconds < 0:
        return 0.0
    return seconds


def classify(
    observations: Sequence[Observation],
    *,
    assessment_id: str,
    job_id: str,
    attempt_id: str,
    transport_id: str,
    decided_at: datetime,
    classifier_version: str = CLASSIFIER_VERSION,
    calibration: Optional[CalibrationTable] = None,
) -> AccessAssessment:
    """Klasifikasikan kondisi akses mengikuti urutan evaluasi Spec v2 §3.1.

    Murni deterministik: id dan ``decided_at`` wajib disuplai pemanggil.
    Melempar ``ValueError`` bila tidak ada observasi — assessment tanpa
    bukti tidak sah (kontrak ``AccessAssessment``).

    ``calibration`` opsional (§3.2): bila disediakan, confidence per state
    diganti nilai terkalibrasi dari korpus berlabel; bucket dengan sampel di
    bawah ``min_samples`` tetap memakai konstanta kategorial.
    """
    obs = tuple(observations)
    if not obs:
        raise ValueError("classification tanpa observasi tidak sah (bukti wajib)")

    status = _int_status(obs)
    retry_after_raw = _latest(obs, Signal.RETRY_AFTER)
    login_form = _has(obs, Signal.LOGIN_FORM)
    challenge = _has(obs, Signal.CHALLENGE)
    target_values = [o.value for o in obs if o.signal == Signal.TARGET_MARKER]
    js_required = _has(obs, Signal.JS_REQUIRED)
    network_error = _latest(obs, Signal.NETWORK_ERROR)

    def assess(
        state: AccessState,
        reason: ReasonCode,
        confidence: float,
        retry_after_seconds: Optional[float] = None,
    ) -> AccessAssessment:
        if calibration is not None:
            confidence = calibration.confidence_for(state.value, confidence)
        return AccessAssessment(
            assessment_id=assessment_id,
            job_id=job_id,
            attempt_id=attempt_id,
            transport_id=transport_id,
            observations=obs,
            hypothesis=_STATE_HYPOTHESIS[state],
            confidence=confidence,
            reason_code=reason,
            classifier_version=classifier_version,
            decided_at=decided_at,
            state=state,
            recommended_action=_STATE_ACTION[state],
            retry_after_seconds=retry_after_seconds,
        )

    # §3.1 aturan 1 — kegagalan jaringan mendahului segalanya.
    if network_error is not None:
        reason = _NETWORK_REASON.get(network_error.value.strip(), ReasonCode.CONNECTION_ERROR)
        return assess(AccessState.NETWORK_FAILURE, reason, CONFIDENCE_HIGH)

    # §3.1 aturan 2 — rate limit eksplisit: 429 atau header Retry-After.
    if status == 429 or retry_after_raw is not None:
        return assess(
            AccessState.RATE_LIMITED,
            ReasonCode.HTTP_429,
            CONFIDENCE_HIGH,
            retry_after_seconds=parse_retry_after(
                retry_after_raw.value if retry_after_raw is not None else None, decided_at
            ),
        )

    # §3.1 aturan 3 — autentikasi eksplisit: 401 atau formulir login.
    if status == 401 or login_form:
        reason = ReasonCode.LOGIN_FORM_PRESENT if login_form else ReasonCode.HTTP_4XX
        confidence = CONFIDENCE_HIGH if status == 401 else CONFIDENCE_MEDIUM
        return assess(AccessState.AUTH_REQUIRED, reason, confidence)

    # §3.1 aturan 4 — penolakan eksplisit: 403 TANPA marker challenge.
    # 403 saja ambigu (izin, aturan aplikasi, autentikasi, kebijakan server);
    # marker challenge memindahkan keputusan ke aturan 5.
    if status == 403 and not challenge:
        return assess(AccessState.ACCESS_DENIED, ReasonCode.HTTP_4XX, CONFIDENCE_MEDIUM)

    # §3.1 aturan 5 — bukti challenge (signature tervalidasi).
    if challenge:
        return assess(AccessState.CHALLENGE_PRESENT, ReasonCode.CHALLENGE_DETECTED, CONFIDENCE_HIGH)

    # §3.1 aturan 6 — konten target valid: semua marker ditemukan.
    if target_values and all(v == "found" for v in target_values):
        return assess(AccessState.ACCESS_GRANTED, ReasonCode.OK, CONFIDENCE_HIGH)

    # §3.1 aturan 7 — bukti kebutuhan JavaScript.
    if js_required:
        return assess(AccessState.JAVASCRIPT_REQUIRED, ReasonCode.CONTENT_INVALID, CONFIDENCE_MEDIUM)

    # §3.1 aturan 8 — respons diterima tetapi konten tidak sesuai target.
    if status is not None:
        if status >= 500:
            return assess(AccessState.CONTENT_INVALID, ReasonCode.HTTP_5XX, CONFIDENCE_MEDIUM)
        if 400 <= status < 500:
            return assess(AccessState.CONTENT_INVALID, ReasonCode.HTTP_4XX, CONFIDENCE_MEDIUM)
        return assess(AccessState.CONTENT_INVALID, ReasonCode.CONTENT_INVALID, CONFIDENCE_MEDIUM)

    # §3.1 aturan 9 — bukti tidak cukup; UNKNOWN selalu diperbolehkan.
    return assess(AccessState.UNKNOWN, ReasonCode.UNKNOWN, CONFIDENCE_LOW)


def confusion_matrix(pairs: Sequence[Tuple[str, str]]) -> Dict[str, Dict[str, int]]:
    """Matriks kebingungan dari pasangan ``(label_benar, state_prediksi)``.

    Utilitas Milestone B ("Confusion matrix" wajib): dipakai oleh harness
    benchmark berlabel, bukan oleh classifier itu sendiri.
    """
    matrix: Dict[str, Dict[str, int]] = {}
    for expected, predicted in pairs:
        row = matrix.setdefault(expected, {})
        row[predicted] = row.get(predicted, 0) + 1
    return matrix


def precision_recall(matrix: Dict[str, Dict[str, int]], label: str) -> Tuple[float, float]:
    """Precision dan recall untuk satu label dari matriks kebingungan.

    Pembagi nol mengembalikan 0.0 — kelas yang tidak pernah diprediksi atau
    tidak pernah muncul bukan keberhasilan.
    """
    row = matrix.get(label, {})
    tp = row.get(label, 0)
    fp = sum(counts.get(label, 0) for expected, counts in matrix.items() if expected != label)
    fn = sum(count for predicted, count in row.items() if predicted != label)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    return precision, recall
