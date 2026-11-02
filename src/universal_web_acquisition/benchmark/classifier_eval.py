"""Classifier evaluation harness (Milestone B, G3 gate).

INSTRUCTION.md menuntut diagnosis yang dapat dibuktikan: "Classifier diuji
menggunakan fixture yang label sebenarnya sudah diketahui — precision dan
recall per kelas, confusion matrix, false positive, false negative,
persentase UNKNOWN." Modul ini adalah harness-nya:

- ``LABELED_CASES``    — korpus berlabel eksekutabel (sinyal → state yang
  diharapkan) mencakup seluruh 9 kelas ``AccessState``, kasus preseden
  urutan evaluasi §3.1, dan kasus robustness (status tak terurai).
- ``MARKER_PROBES``    — probe konten untuk mengukur TP/FP marker di
  ``access.observe`` (deteksi gerbang JS / interstitial challenge) —
  FP-rate DIUKUR, bukan diasumsikan.
- ``evaluate_corpus``  — menjalankan classifier atas korpus; hasil berupa
  confusion matrix, precision/recall per kelas, proporsi UNKNOWN, dan
  daftar mismatch yang tertelusur per case_id.

Korpus adalah spesifikasi eksekutabel: akurasi < 1.0 berarti ada
inkonsistensi nyata antara classifier dan spesifikasi — bukan angka untuk
dipoles. Kalibrasi confidence menunggu corpus kegagalan nyata dari
benchmark (E8+), sesuai §3.2.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from universal_web_acquisition.access.calibration import CalibrationTable
from universal_web_acquisition.access.classifier import (
    Signal,
    classify,
    confusion_matrix,
    precision_recall,
)
from universal_web_acquisition.access.model import AccessState, Observation
from universal_web_acquisition.access.observe import observations_from_artifact

# Timestamp korpus tetap — hasil evaluasi dapat direproduksi bit-per-bit.
CORPUS_DECIDED_AT = datetime(2026, 1, 1, 0, 0, 0)


@dataclass(frozen=True)
class LabeledCase:
    """Satu kasus korpus berlabel: sinyal → state yang diharapkan."""

    case_id: str
    expected: AccessState
    signals: Tuple[Tuple[str, str], ...]
    note: str = ""


@dataclass(frozen=True)
class MarkerProbe:
    """Probe konten 2xx: isi body → sinyal yang diharapkan dari observer."""

    probe_id: str
    content: str
    expected_signals: Tuple[Tuple[str, str], ...]  # di luar http.status
    note: str = ""


@dataclass(frozen=True)
class Mismatch:
    """Satu klasifikasi yang menyimpang dari label — tertelusur per kasus."""

    case_id: str
    expected: str
    predicted: str
    reason_code: str


@dataclass(frozen=True)
class EvalReport:
    """Hasil evaluasi korpus berlabel (G3: precision/recall per kelas)."""

    total: int
    correct: int
    accuracy: float
    unknown_proportion: float
    confusion: Dict[str, Dict[str, int]]
    precision: Dict[str, float]
    recall: Dict[str, float]
    mismatches: Tuple[Mismatch, ...]


# ---------------------------------------------------------------------------
# Korpus berlabel — sinyal → state (Spec v2 §3.1 urutan evaluasi)
# ---------------------------------------------------------------------------

LABELED_CASES: Tuple[LabeledCase, ...] = (
    # ACCESS_GRANTED — konten target tervalidasi
    LabeledCase(
        "granted-single-marker",
        AccessState.ACCESS_GRANTED,
        ((Signal.HTTP_STATUS, "200"), (Signal.TARGET_MARKER, "found")),
        "halaman publik, marker target ditemukan",
    ),
    LabeledCase(
        "granted-multi-marker",
        AccessState.ACCESS_GRANTED,
        (
            (Signal.HTTP_STATUS, "200"),
            (Signal.TARGET_MARKER, "found"),
            (Signal.TARGET_MARKER, "found"),
        ),
        "semua marker target ditemukan",
    ),
    # AUTH_REQUIRED
    LabeledCase("auth-401", AccessState.AUTH_REQUIRED, ((Signal.HTTP_STATUS, "401"),)),
    LabeledCase(
        "auth-login-form",
        AccessState.AUTH_REQUIRED,
        ((Signal.HTTP_STATUS, "200"), (Signal.LOGIN_FORM, "present")),
        "200 + formulir login (Spec v2 §4.1)",
    ),
    LabeledCase(
        "auth-beats-challenge",
        AccessState.AUTH_REQUIRED,
        ((Signal.HTTP_STATUS, "401"), (Signal.CHALLENGE, "cf-challenge")),
        "urutan §3.1: autentikasi mendahului challenge",
    ),
    # RATE_LIMITED
    LabeledCase("rate-429", AccessState.RATE_LIMITED, ((Signal.HTTP_STATUS, "429"),)),
    LabeledCase(
        "rate-429-retry-after",
        AccessState.RATE_LIMITED,
        ((Signal.HTTP_STATUS, "429"), (Signal.RETRY_AFTER, "30")),
    ),
    LabeledCase(
        "rate-header-only",
        AccessState.RATE_LIMITED,
        ((Signal.HTTP_STATUS, "503"), (Signal.RETRY_AFTER, "60")),
        "Retry-After eksplisit menang atas 5xx (§3.1 aturan 2)",
    ),
    # CHALLENGE_PRESENT
    LabeledCase(
        "challenge-beats-denial",
        AccessState.CHALLENGE_PRESENT,
        ((Signal.HTTP_STATUS, "403"), (Signal.CHALLENGE, "just a moment")),
        "403 + signature → challenge, bukan denial",
    ),
    LabeledCase(
        "challenge-200",
        AccessState.CHALLENGE_PRESENT,
        ((Signal.HTTP_STATUS, "200"), (Signal.CHALLENGE, "cf-challenge")),
    ),
    # JAVASCRIPT_REQUIRED
    LabeledCase(
        "js-required",
        AccessState.JAVASCRIPT_REQUIRED,
        (
            (Signal.HTTP_STATUS, "200"),
            (Signal.TARGET_MARKER, "missing"),
            (Signal.JS_REQUIRED, "true"),
        ),
    ),
    LabeledCase(
        "js-only-signal",
        AccessState.JAVASCRIPT_REQUIRED,
        ((Signal.JS_REQUIRED, "true"),),
    ),
    # CONTENT_INVALID
    LabeledCase(
        "invalid-empty-200",
        AccessState.CONTENT_INVALID,
        ((Signal.HTTP_STATUS, "200"), (Signal.TARGET_MARKER, "missing")),
    ),
    LabeledCase("invalid-404", AccessState.CONTENT_INVALID, ((Signal.HTTP_STATUS, "404"),)),
    LabeledCase("invalid-500", AccessState.CONTENT_INVALID, ((Signal.HTTP_STATUS, "500"),)),
    LabeledCase(
        "invalid-2xx-no-target",
        AccessState.CONTENT_INVALID,
        ((Signal.HTTP_STATUS, "204"),),
        "2xx tanpa observasi target → bukan granted",
    ),
    # NETWORK_FAILURE — mendahului segalanya (§3.1 aturan 1)
    LabeledCase("network-dns", AccessState.NETWORK_FAILURE, ((Signal.NETWORK_ERROR, "dns"),)),
    LabeledCase("network-tls", AccessState.NETWORK_FAILURE, ((Signal.NETWORK_ERROR, "tls"),)),
    LabeledCase(
        "network-timeout", AccessState.NETWORK_FAILURE, ((Signal.NETWORK_ERROR, "timeout"),)
    ),
    LabeledCase(
        "network-connection",
        AccessState.NETWORK_FAILURE,
        ((Signal.NETWORK_ERROR, "connection"),),
    ),
    LabeledCase(
        "network-beats-rate-limit",
        AccessState.NETWORK_FAILURE,
        ((Signal.HTTP_STATUS, "429"), (Signal.NETWORK_ERROR, "dns")),
        "urutan §3.1: kegagalan jaringan mendahului rate limit",
    ),
    # ACCESS_DENIED — 403 polos ambigu (§3.1)
    LabeledCase(
        "denied-plain-403",
        AccessState.ACCESS_DENIED,
        ((Signal.HTTP_STATUS, "403"),),
        "403 tanpa marker challenge → denial, bukan CAPTCHA",
    ),
    # UNKNOWN — bukti tidak cukup selalu diizinkan (§5)
    LabeledCase("unknown-custom-signal", AccessState.UNKNOWN, (("custom.signal", "x"),)),
    LabeledCase(
        "unknown-unparseable-status",
        AccessState.UNKNOWN,
        ((Signal.HTTP_STATUS, "not-a-number"),),
        "status tak terurai → UNKNOWN, bukan tebakan",
    ),
)


# ---------------------------------------------------------------------------
# Probe marker konten — TP/FP deteksi gerbang (access.observe)
# ---------------------------------------------------------------------------

MARKER_PROBES: Tuple[MarkerProbe, ...] = (
    MarkerProbe(
        "normal-article-captcha-word",
        "<html><body><h1>Artikel</h1><p>Ulasan tentang captcha modern.</p></body></html>",
        ((Signal.TARGET_MARKER, "found"),),
        "FP-guard: kata 'captcha' dalam artikel bukan challenge",
    ),
    MarkerProbe(
        "normal-js-mention",
        "<html><body><p>Artikel tentang sejarah JavaScript.</p></body></html>",
        ((Signal.TARGET_MARKER, "found"),),
        "FP-guard: kata 'javascript' saja bukan gerbang",
    ),
    MarkerProbe(
        "js-gate",
        "<html><body><h1>please enable javascript to view this page</h1></body></html>",
        ((Signal.TARGET_MARKER, "missing"), (Signal.JS_REQUIRED, "true")),
        "TP: gerbang JS terdeteksi",
    ),
    MarkerProbe(
        "challenge-checking-browser",
        "<html><body>Checking your browser before accessing.</body></html>",
        ((Signal.CHALLENGE, "checking your browser"), (Signal.TARGET_MARKER, "missing")),
        "TP: interstitial challenge terdeteksi",
    ),
    MarkerProbe(
        "challenge-just-a-moment",
        "<html><body>Just a moment...</body></html>",
        ((Signal.CHALLENGE, "just a moment"), (Signal.TARGET_MARKER, "missing")),
        "TP: signature Cloudflare",
    ),
    MarkerProbe(
        "cloudflare-normal-page-with-challenge-script",
        "<html><head><script src=\"/cdn-cgi/challenge-platform/scripts/jsd/main.js\"></script></head>"
        "<body><h1>Konten normal tersaji penuh</h1></body></html>",
        ((Signal.TARGET_MARKER, "found"),),
        "FP-guard (temuan target nyata komiku.asia): halaman normal di belakang "
        "Cloudflare memuat path /cdn-cgi/challenge-platform/ tanpa challenge — "
        "bukan interstitial",
    ),
)


class _ProbeArtifact:
    """Artifact minimal untuk probe (hanya field yang dibaca observer)."""

    def __init__(self, content: str, status_code: int = 200):
        self.content = content.encode("utf-8")
        self.status_code = status_code
        self.content_type = "text/html; charset=utf-8"


# ---------------------------------------------------------------------------
# Evaluasi
# ---------------------------------------------------------------------------


def evaluate_corpus(decided_at: Optional[datetime] = None) -> EvalReport:
    """Jalankan classifier atas korpus berlabel; hasil dapat ditelusuri."""
    decided_at = decided_at if decided_at is not None else CORPUS_DECIDED_AT
    pairs: List[Tuple[str, str]] = []
    mismatches: List[Mismatch] = []
    correct = 0
    unknown_count = 0

    for case in LABELED_CASES:
        observations = tuple(
            Observation(
                observation_id=f"obs-{case.case_id}-{index}",
                signal=signal,
                value=value,
                recorded_at=decided_at,
                source="corpus",
            )
            for index, (signal, value) in enumerate(case.signals)
        )
        assessment = classify(
            observations,
            assessment_id=f"eval-{case.case_id}",
            job_id="eval",
            attempt_id="eval",
            transport_id="corpus",
            decided_at=decided_at,
        )
        predicted = assessment.state
        pairs.append((case.expected.value, predicted.value))
        if predicted is AccessState.UNKNOWN:
            unknown_count += 1
        if predicted is case.expected:
            correct += 1
        else:
            mismatches.append(
                Mismatch(
                    case_id=case.case_id,
                    expected=case.expected.value,
                    predicted=predicted.value,
                    reason_code=assessment.reason_code.value,
                )
            )

    matrix = confusion_matrix(pairs)
    labels = sorted({expected for expected, _ in pairs} | {predicted for _, predicted in pairs})
    precision: Dict[str, float] = {}
    recall: Dict[str, float] = {}
    for label in labels:
        precision[label], recall[label] = precision_recall(matrix, label)

    total = len(LABELED_CASES)
    return EvalReport(
        total=total,
        correct=correct,
        accuracy=correct / total,
        unknown_proportion=unknown_count / total,
        confusion=matrix,
        precision=precision,
        recall=recall,
        mismatches=tuple(mismatches),
    )


def evaluate_marker_probes() -> List[Tuple[MarkerProbe, Tuple[Tuple[str, str], ...], bool]]:
    """Ukur perilaku marker konten (TP/FP) atas probe — bukti, bukan asumsi.

    Mengembalikan ``(probe, sinyal_aktual, ok)`` per probe; ``ok`` berarti
    himpunan sinyal aktual (di luar ``http.status``) persis sama dengan
    yang diharapkan.
    """
    results = []
    for probe in MARKER_PROBES:
        artifact = _ProbeArtifact(probe.content)
        observations = observations_from_artifact("probe", artifact, 0, CORPUS_DECIDED_AT)
        actual = tuple(
            (o.signal, o.value) for o in observations if o.signal != Signal.HTTP_STATUS
        )
        ok = set(actual) == set(probe.expected_signals)
        results.append((probe, actual, ok))
    return results


def build_calibration_table(
    decided_at: Optional[datetime] = None,
    min_samples: int = 10,
    include_real: bool = True,
) -> CalibrationTable:
    """Tabel kalibrasi confidence dari korpus aktif (§3.2).

    Bucket = state prediksi; akurasi = precision dari korpus. Dua sumber:
    korpus sintetis (``LABELED_CASES``) + kasus nyata dari run terotorisasi
    (``corpus_real`` — sinyal asli dari assessment events). Bucket dengan
    sampel di bawah ``min_samples`` → fallback konstanta kategorial (jujur
    terhadap §3.2); bucket yang melewati ambang → terkalibrasi.
    """
    report = evaluate_corpus(decided_at)
    outcomes: List[Tuple[str, bool]] = []
    for expected, row in report.confusion.items():
        for predicted, count in row.items():
            outcomes.extend([(predicted, expected == predicted)] * count)
    if include_real:
        from universal_web_acquisition.benchmark.corpus_real import real_outcomes

        outcomes.extend(real_outcomes(decided_at))
    return CalibrationTable.from_outcomes(outcomes, min_samples)
