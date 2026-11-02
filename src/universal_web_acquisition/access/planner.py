"""Deterministic strategy planner (roadmap step 5, Spec v2 §4).

Connects the access classifier's assessment to a deterministic next action:

- Cost-ordered escalation: same transport → alternate transport → browser → user.
  HTTP that already succeeded is never re-done with a browser (§4.2).
- Bounded retry budget via ADR-011 ``RetryPolicy`` — the planner can never
  produce an unbounded retry loop (anti-pattern reproduced in E6).
- Server-mandated waits are honoured: ``Rate-Limited`` + ``Retry-After`` yields
  ``WAIT_RETRY_AFTER`` with the server's own seconds.
- ``ACCESS_DENIED`` never auto-retries through transports (ACP §2.2) — it goes
  to ``NEEDS_USER``.
- Pure function: ``decision_id`` and ``decided_at`` are supplied by the caller
  so decisions are reproducible bit-for-bit (same rule style as the classifier).
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple

from universal_web_acquisition.access.model import AccessAssessment, AccessState, ReasonCode
from universal_web_acquisition.http_transport.registry import RetryPolicy

PLANNER_VERSION = "planner-1.0.0"


# Per-reason retry budget mapping (P2): ReasonCode.value -> remaining budget
RetryBudget = dict[str, int]


class NextAction(Enum):
    """Aksi berikutnya yang deterministik atas satu assessment."""

    ACCEPT = "accept"                          # konten valid — simpan hasil
    RETRY_SAME_TRANSPORT = "retry_same_transport"
    SWITCH_TRANSPORT = "switch_transport"      # eskalasi biaya: transport lain
    USE_BROWSER = "use_browser"                # butuh JS / challenge
    WAIT_RETRY_AFTER = "wait_retry_after"      # patuhi waktu tunggu server
    RECOVER_SESSION = "recover_session"        # sesi kedaluwarsa — autentikasi resmi
    NEEDS_USER = "needs_user"                  # intervensi pengguna
    INSPECT_CONTENT = "inspect_content"        # konten tidak sesuai target — inspeksi
    COLLECT_MORE_EVIDENCE = "collect_more_evidence"  # UNKNOWN — kumpulkan bukti
    ABORT = "abort"                            # anggaran habis / capability missing


@dataclass(frozen=True)
class PlannerContext:
    """Semua yang dibutuhkan planner untuk satu keputusan — tidak ada global state."""

    assessment: AccessAssessment
    retry_attempt: int                          # attempt saat ini (0-based)
    retry_policy: RetryPolicy
    browser_available: bool
    current_transport: str
    untried_transports: Tuple[str, ...]         # transport lain belum dicoba (urutan biaya)
    # Per-reason retry budget (P2) — None = fallback ke retry_policy.max_retries
    retry_budget: Optional[RetryBudget] = None


@dataclass(frozen=True)
class StrategyDecision:
    """Keputusan planner yang dapat diaudit (reason code + rationale)."""

    decision_id: str
    job_id: str
    attempt_id: str
    next_action: NextAction
    reason_code: ReasonCode
    planner_version: str
    decided_at: datetime
    rationale: str
    wait_seconds: Optional[float] = None
    target_transport: Optional[str] = None


def plan(context: PlannerContext, decision_id: str, decided_at: datetime) -> StrategyDecision:
    """Satu keputusan deterministik atas satu assessment.

    Urutan aturan mengikuti Spec v2 §4.2 (contoh keputusan yang diharapkan):
    konten valid disimpan; rate limit dihormati; sesi kedaluwarsa dipulihkan
    lewat autentikasi resmi; konten JS/challenge butuh browser runtime — bila
    tidak tersedia (atau anggaran habis), hasilkan kegagalan yang menjelaskan
    kemampuan yang kurang.
    """
    a = context.assessment
    policy = context.retry_policy

    def _budget_exhausted(reason_code: ReasonCode) -> bool:
        """Cek apakah budget untuk reason_code ini habis (per-reason atau global)."""
        if context.retry_budget is not None:
            return context.retry_budget.get(reason_code.value, 0) <= 0
        return context.retry_attempt > policy.max_retries

    def _decide(
        action: NextAction,
        reason: ReasonCode,
        rationale: str,
        wait: Optional[float] = None,
        target: Optional[str] = None,
    ) -> StrategyDecision:
        return StrategyDecision(
            decision_id=decision_id,
            job_id=a.job_id,
            attempt_id=a.attempt_id,
            next_action=action,
            reason_code=reason,
            planner_version=PLANNER_VERSION,
            decided_at=decided_at,
            rationale=rationale,
            wait_seconds=wait,
            target_transport=target,
        )

    # 1. Konten valid -> simpan hasil. Jangan membuka browser hanya untuk
    #    mengulangi pekerjaan yang sudah selesai (Spec v2 §4.2).
    if a.state is AccessState.ACCESS_GRANTED:
        return _decide(
            NextAction.ACCEPT, ReasonCode.OK,
            "konten valid -- simpan hasil; browser tidak diperlukan",
        )

    # 2. Rate limit -> patuhi waktu tunggu server, jangan pindah adapter hanya
    #    untuk mengulangi permintaan terlalu cepat (Spec v2 §4.2).
    if a.state is AccessState.RATE_LIMITED:
        if _budget_exhausted(a.reason_code):
            return _decide(
                NextAction.ABORT, ReasonCode.BUDGET_EXHAUSTED,
                "anggaran retry habis pada rate limit",
            )
        if a.retry_after_seconds is not None:
            return _decide(
                NextAction.WAIT_RETRY_AFTER, ReasonCode.HTTP_429,
                "patuhi Retry-After dari server",
                wait=float(a.retry_after_seconds),
            )
        delay = policy.next_delay_seconds(context.retry_attempt)
        return _decide(
            NextAction.RETRY_SAME_TRANSPORT, ReasonCode.HTTP_429,
            "tanpa Retry-After: backoff pada transport yang sama",
            wait=delay,
        )

    # 3. Sesi kedaluwarsa -> mekanisme autentikasi resmi; validasi ulang konten
    #    setelah pemulihan (Spec v2 §4.2). Setiap siklus pemulihan menghabiskan
    #    satu attempt -- loop login tanpa batas dilarang (§4.3).
    if a.state is AccessState.AUTH_REQUIRED:
        if _budget_exhausted(a.reason_code):
            return _decide(
                NextAction.ABORT, a.reason_code,
                "autentikasi tetap diperlukan setelah anggaran attempt habis",
            )
        return _decide(
            NextAction.RECOVER_SESSION, ReasonCode.AUTH_EXPIRED,
            "sesi kedaluwarsa -- jalankan autentikasi resmi, lalu validasi ulang",
        )

    # 4. Challenge -> butuh browser runtime; tanpa browser atau anggaran habis
    #    -> minta pengguna -- keberhasilan challenge tidak pernah dipalsukan.
    if a.state is AccessState.CHALLENGE_PRESENT:
        if context.browser_available and not _budget_exhausted(a.reason_code):
            return _decide(
                NextAction.USE_BROWSER, ReasonCode.CHALLENGE_DETECTED,
                "challenge terdeteksi -- gunakan browser runtime",
            )
        if context.browser_available:
            return _decide(
                NextAction.NEEDS_USER, ReasonCode.BUDGET_EXHAUSTED,
                "anggaran attempt habis sebelum challenge teratasi -- verifikasi pengguna",
            )
        return _decide(
            NextAction.NEEDS_USER, ReasonCode.CAPABILITY_MISSING,
            "challenge terdeteksi tetapi browser runtime tidak tersedia",
        )

    # 5. Konten memerlukan JavaScript -> periksa browser runtime; bila tidak
    #    tersedia (atau anggaran habis), hasilkan kegagalan yang menjelaskan
    #    kemampuan yang kurang.
    if a.state is AccessState.JAVASCRIPT_REQUIRED:
        if context.browser_available and not _budget_exhausted(a.reason_code):
            return _decide(
                NextAction.USE_BROWSER, a.reason_code,
                "konten memerlukan JavaScript -- gunakan browser runtime",
            )
        if context.browser_available:
            return _decide(
                NextAction.ABORT, ReasonCode.BUDGET_EXHAUSTED,
                "anggaran attempt habis sebelum konten JavaScript tercapai",
            )
        return _decide(
            NextAction.ABORT, ReasonCode.CAPABILITY_MISSING,
            "konten memerlukan JavaScript tetapi browser runtime tidak tersedia",
        )

    # 6. Penolakan akses -> DENIED tidak boleh otomatis diatasi dengan mengulang
    #    request melalui semua transport (ACP §2.2) -> intervensi pengguna.
    if a.state is AccessState.ACCESS_DENIED:
        return _decide(
            NextAction.NEEDS_USER, ReasonCode.NEEDS_USER,
            "akses ditolak -- DENIED tidak di-retry otomatis (ACP §2.2)",
        )

    # 7. NETWORK_FAILURE -> diagnosis jaringan/transport dulu (§4.2), jangan
    #    menyimpulkan pemblokiran: retry berbatas pada transport yang sama,
    #    lalu eskalasi transport lain yang belum dicoba, habis semua -> abort.
    if a.state is AccessState.NETWORK_FAILURE:
        if not policy.is_retryable(a.reason_code):
            if context.untried_transports:
                return _decide(
                    NextAction.SWITCH_TRANSPORT, a.reason_code,
                    "kegagalan tidak dapat di-retry -- eskalasi transport lain",
                    target=context.untried_transports[0],
                )
            return _decide(
                NextAction.ABORT, a.reason_code,
                "kegagalan tidak dapat di-retry dan tidak ada transport lain",
            )
        if _budget_exhausted(a.reason_code):
            if context.untried_transports:
                return _decide(
                    NextAction.SWITCH_TRANSPORT, a.reason_code,
                    "anggaran transport habis -- eskalasi transport lain",
                    target=context.untried_transports[0],
                )
            return _decide(
                NextAction.ABORT, ReasonCode.BUDGET_EXHAUSTED,
                "tidak ada transport lain dan anggaran retry habis",
            )
        delay = policy.next_delay_seconds(context.retry_attempt)
        if delay is not None:
            return _decide(
                NextAction.RETRY_SAME_TRANSPORT, a.reason_code,
                "diagnosis jaringan dulu -- backoff pada transport yang sama",
                wait=delay,
            )
        if context.untried_transports:
            return _decide(
                NextAction.SWITCH_TRANSPORT, a.reason_code,
                "anggaran transport habis -- eskalasi transport lain",
                target=context.untried_transports[0],
            )
        return _decide(
            NextAction.ABORT, ReasonCode.BUDGET_EXHAUSTED,
            "tidak ada transport lain dan anggaran retry habis",
        )

    # 8. CONTENT_INVALID -> periksa apakah perlu JavaScript atau selector/target
    #    salah (§4.2). Rotasi transport tidak menolong konten yang salah --
    #    setiap siklus inspeksi menghabiskan satu attempt; bila konten tetap
    #    invalid sampai anggaran habis -> abort dengan bukti tercatat.
    if a.state is AccessState.CONTENT_INVALID:
        if _budget_exhausted(a.reason_code):
            return _decide(
                NextAction.ABORT, a.reason_code,
                "konten tetap tidak sesuai target setelah anggaran attempt habis",
            )
        return _decide(
            NextAction.INSPECT_CONTENT, a.reason_code,
            "konten tidak sesuai target -- periksa kebutuhan JavaScript atau selector",
        )

    # 9. UNKNOWN -> kumpulkan bukti tambahan (bukan rotasi transport); UNKNOWN
    #    tetap diizinkan sebagai hasil jujur selama bukti belum cukup (§5).
    if _budget_exhausted(ReasonCode.UNKNOWN):
        return _decide(
            NextAction.ABORT, ReasonCode.UNKNOWN,
            "bukti tidak bertambah dalam anggaran attempt",
        )
    return _decide(
        NextAction.COLLECT_MORE_EVIDENCE, ReasonCode.UNKNOWN,
        "bukti tidak cukup -- kumpulkan observasi tambahan",
    )