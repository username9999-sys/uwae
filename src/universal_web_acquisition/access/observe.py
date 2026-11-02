"""Observation building — the "Observe" step of the Spec v2 §1 cycle.

Satu sumber kebenaran untuk pembangunan observasi dari hasil attempt:
dipakai oleh ``core.job_worker`` (jalur eksekusi) dan oleh harness evaluasi
classifier (Milestone B) — sehingga FP-rate marker yang diukur adalah
FP-rate marker yang benar-benar dipakai produksi, bukan salinan.

Kosakata sinyal berbatas (lihat ``access.classifier.Signal``):
- ``http.status``             — kode status sebagai string angka
- ``http.header.retry-after`` — delta-seconds atau HTTP-date (A06)
- ``body.marker.login-form``  — ``present`` (A04)
- ``body.marker.challenge``   — signature challenge yang cocok (A07)
- ``body.marker.target``      — ``found`` / ``missing``
- ``js.required``             — ``true``
- ``network.error``           — ``dns`` / ``tls`` / ``timeout`` / ``connection``

Sinyal konten diekstrak dari body 2xx maupun body KEGAGALAN (mis. interstitial
challenge 403 — A07) lewat satu helper yang sama (``_content_signals``).

Marker konten (v1, heuristik konservatif): tingkat false positive DIUKUR
lewat probe Milestone B (``benchmark.classifier_eval``), bukan diasumsikan.
"""

from datetime import datetime
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple

from universal_web_acquisition.access.classifier import Signal
from universal_web_acquisition.access.model import Observation, ReasonCode
from universal_web_acquisition.http_transport.cache import CACHE_HEADER

# Pemetaan reason code transport → nilai sinyal ``network.error``.
NETWORK_SIGNAL_VALUES = {
    ReasonCode.DNS_FAILURE: "dns",
    ReasonCode.TLS_ERROR: "tls",
    ReasonCode.TIMEOUT: "timeout",
    ReasonCode.CONNECTION_ERROR: "connection",
}

# Gerbang JS: halaman pengganti konten yang menyuruh mengaktifkan JavaScript.
JS_GATE_MARKERS = ("please enable javascript", "enable javascript to")

# Interstitial challenge: signature challenge umum. Sengaja TANPA kata
# generik seperti "captcha" — artikel biasa yang membahas captcha tidak boleh
# diklasifikasikan sebagai challenge (false positive).
# "challenge-platform" sengaja DIHAPUS (temuan target nyata komiku.asia,
# real-target-komiku-001): Cloudflare menginjeksikan path
# /cdn-cgi/challenge-platform/ ke halaman NORMAL yang disajikan sukses —
# kehadirannya bukan indikator interstitial.
CHALLENGE_MARKERS = (
    "cf-challenge",
    "cf_challenge",
    "just a moment",
    "checking your browser",
)

# Formulir login (A04): keberadaan field password adalah indikator kuat
# halaman autentikasi — konservatif, bukan kata generik.
LOGIN_FORM_MARKERS = ('type="password"',)

# Batas body kegagalan yang diikutsertakan untuk diagnosis (A07) — cukup
# untuk marker interstitial, tanpa menyalin body besar ke dalam observasi.
_FAILURE_BODY_LIMIT = 4096


class _HTMLStructureCheck(HTMLParser):
    """Menghitung tag pembuka — nol tag berarti body bukan HTML terurai (A11)."""

    def __init__(self):
        super().__init__()
        self.tags = 0

    def handle_starttag(self, tag, attrs):
        self.tags += 1


def _has_html_structure(body: str) -> bool:
    checker = _HTMLStructureCheck()
    try:
        checker.feed(body)
        checker.close()
    except Exception:
        return False
    return checker.tags > 0


def _header_value(headers: Optional[Dict[str, str]], name: str) -> Optional[str]:
    """Lookup header case-insensitive (curl_cffi/httpx/requests beda kapitalisasi)."""
    lowered = name.lower()
    for key, value in (headers or {}).items():
        if key.lower() == lowered:
            return value
    return None


def _content_signals(
    body: str,
    prefix: str,
    now: datetime,
    source: str,
    is_html: bool,
    allow_target_found: bool = True,
) -> Tuple[Observation, ...]:
    """Sinyal konten dari body 2xx maupun body kegagalan (A04/A07/A11).

    - challenge / login form / gerbang JS → sinyal eksplisit masing-masing;
    - gerbang, interstitial, dan form login BUKAN konten target;
    - HTML tanpa struktur yang dapat diurai juga bukan konten target (A11);
    - ``allow_target_found=False`` (jalur kegagalan): respons 4xx/5xx tidak
      pernah menjadi konten target — marker hanya untuk diagnosis.
    """
    lowered = body.lower()
    signals: List[Observation] = []

    challenge = next((m for m in CHALLENGE_MARKERS if m in lowered), None)
    if challenge is not None:
        signals.append(
            Observation(f"{prefix}-challenge", Signal.CHALLENGE, challenge, now, source)
        )

    login_form = any(m in lowered for m in LOGIN_FORM_MARKERS)
    if login_form:
        signals.append(
            Observation(f"{prefix}-login", Signal.LOGIN_FORM, "present", now, source)
        )

    js_gate = any(m in lowered for m in JS_GATE_MARKERS)
    if js_gate:
        signals.append(
            Observation(f"{prefix}-js", Signal.JS_REQUIRED, "true", now, source)
        )

    target_found = (
        allow_target_found and bool(body) and challenge is None and not js_gate
    )
    if login_form:
        target_found = False
    if is_html and not _has_html_structure(body):
        # A11: status 200 dengan body bukan HTML valid — bukan konten target.
        target_found = False
    signals.append(
        Observation(
            f"{prefix}-target",
            Signal.TARGET_MARKER,
            "found" if target_found else "missing",
            now,
            source,
        )
    )
    return tuple(signals)


def observations_from_artifact(
    transport_id: str,
    artifact,
    attempt: int,
    decided_at: Optional[datetime] = None,
) -> Tuple[Observation, ...]:
    """Observasi dari attempt yang menghasilkan artifact."""
    now = decided_at if decided_at is not None else datetime.now()
    observations = [
        Observation(
            observation_id=f"obs-{transport_id}-{attempt}-status",
            signal=Signal.HTTP_STATUS,
            value=str(artifact.status_code),
            recorded_at=now,
            source=transport_id,
        )
    ]
    cache_hit = _header_value(getattr(artifact, "headers", None), CACHE_HEADER)
    if cache_hit:
        # transparansi: respons berasal dari cache run ini — bukti, bukan
        # input diagnosis (urutan evaluasi §3.1 tidak menyentuhnya)
        observations.append(
            Observation(
                observation_id=f"obs-{transport_id}-{attempt}-cache",
                signal=Signal.CACHE_HIT,
                value=cache_hit,
                recorded_at=now,
                source=transport_id,
            )
        )
    if 200 <= artifact.status_code < 300:
        body = artifact.content.decode("utf-8", errors="replace")
        is_html = "text/html" in (artifact.content_type or "").lower()
        observations.extend(
            _content_signals(
                body, f"obs-{transport_id}-{attempt}", now, "content-validator", is_html
            )
        )
    else:
        # Non-2xx yang TETAP menjadi artifact: jalur browser mengembalikan
        # respons 403/404 sebagai artifact (bukan exception), sehingga tanpa
        # cabang ini marker challenge/login/JS-gate pada body non-2xx hilang
        # dan klasifikasi menyimpang dari jalur HTTP (yang memakai
        # observations_from_failure). Paritas diagnosis: body non-2xx tetap
        # diurai untuk marker, tapi TIDAK PERNAH menjadi konten target.
        body = artifact.content.decode("utf-8", errors="replace")
        is_html = "text/html" in (artifact.content_type or "").lower()
        observations.extend(
            _content_signals(
                body,
                f"obs-{transport_id}-{attempt}",
                now,
                transport_id,
                is_html,
                allow_target_found=False,
            )
        )
    return tuple(observations)


def observations_from_failure(
    transport_id: str,
    reason_code: ReasonCode,
    status_code: Optional[int],
    attempt: int,
    decided_at: Optional[datetime] = None,
    headers: Optional[Dict[str, str]] = None,
    body: Optional[bytes] = None,
) -> Tuple[Observation, ...]:
    """Observasi dari attempt yang gagal.

    - Kegagalan HTTP → sinyal ``http.status`` (+ ``retry-after`` bila server
      mengirimkannya — A06: waktu tunggu server wajib dihormati);
    - kegagalan jaringan → sinyal ``network.error`` (kosakata berbatas);
    - body kegagalan (mis. interstitial challenge 403 — A07) diurai dengan
      ekstraksi sinyal konten yang sama dengan jalur sukses.
    """
    now = decided_at if decided_at is not None else datetime.now()
    observations: List[Observation] = []
    if status_code is not None:
        observations.append(
            Observation(
                observation_id=f"obs-{transport_id}-{attempt}-status",
                signal=Signal.HTTP_STATUS,
                value=str(status_code),
                recorded_at=now,
                source=transport_id,
            )
        )
        retry_after = _header_value(headers, "Retry-After")
        if retry_after:
            observations.append(
                Observation(
                    observation_id=f"obs-{transport_id}-{attempt}-retry-after",
                    signal=Signal.RETRY_AFTER,
                    value=retry_after,
                    recorded_at=now,
                    source=transport_id,
                )
            )
    else:
        value = NETWORK_SIGNAL_VALUES.get(reason_code, "connection")
        observations.append(
            Observation(
                observation_id=f"obs-{transport_id}-{attempt}-network",
                signal=Signal.NETWORK_ERROR,
                value=value,
                recorded_at=now,
                source=transport_id,
            )
        )

    if body:
        text = body.decode("utf-8", errors="replace")
        content_type = _header_value(headers, "Content-Type") or ""
        is_html = "text/html" in content_type.lower()
        observations.extend(
            _content_signals(
                text,
                f"obs-{transport_id}-{attempt}",
                now,
                transport_id,
                is_html,
                allow_target_found=False,
            )
        )
    return tuple(observations)
