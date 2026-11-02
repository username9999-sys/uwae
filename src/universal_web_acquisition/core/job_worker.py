"""Job worker for the Universal Web Acquisition Engine.

Access Control Plane integration (Spec v2 §1 cycle): every attempt runs
Observe → Diagnose → Decide → Execute → Validate:

- **Observe** — the transport attempt is turned into bounded-signal
  ``Observation`` objects (``http.status``, ``network.error``,
  ``body.marker.target``).
- **Diagnose** — ``access.classifier`` produces an ``AccessAssessment``
  (ADR-012); an HTTP 200 with an empty body is never a success.
- **Decide** — ``access.planner`` produces one explainable
  ``StrategyDecision`` (ADR-013): bounded retries, cost-ordered escalation,
  ``NEEDS_USER`` for explicit denials, ``ABORT`` when the budget is out.
- **Execute/Validate** — the worker acts on the decision; ``ACCEPT`` requires
  the classifier's ``ACCESS_GRANTED`` (validated content), never a bare 200.

The worker contains no retry policy of its own: the loop only advances on
planner decisions, and every planner branch either reaches a terminal decision
or consumes attempt budget (G4: no unbounded loops — ADR-011/ADR-013).

Per-job resource accounting (P3): peak memory measured via tracemalloc
across the entire job execution (all attempts).
"""

import asyncio
import hashlib
import json
import logging
import tracemalloc
import uuid
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urlparse

from universal_web_acquisition.access.classifier import classify
from universal_web_acquisition.access.model import ReasonCode
from universal_web_acquisition.access.observe import (
    observations_from_artifact,
    observations_from_failure,
)
from universal_web_acquisition.access.planner import NextAction, PlannerContext, plan
from universal_web_acquisition.artifact.identification import (
    filename_from_headers,
)
from universal_web_acquisition.artifact.storage import (
    ArtifactStorage,
    FilesystemArtifactStorage,
)
from universal_web_acquisition.browser.adapter import BROWSER_NAME
from universal_web_acquisition.core.job_model import Job, JobStatus
from universal_web_acquisition.core.job_repository import JobRepository
from universal_web_acquisition.http_transport.adapters import (
    TransportFailure,
    build_default_registry,
)
from universal_web_acquisition.http_transport.registry import (
    RetryPolicy,
    TransportRegistry,
)
from universal_web_acquisition.http_transport.resume import ResumableDownloader
from universal_web_acquisition.plugins.registry import PluginRegistry
from universal_web_acquisition.session.manager import SessionRecoveryManager

logger = logging.getLogger(__name__)


def run_extraction_plugins(repo, job_id: str, artifact, extractors) -> None:
    """Jalankan extractor terdaftar atas artifact — event audit penuh.

    Satu sumber kebenaran untuk ekstraksi (worker pasca-ACCEPT DAN
    ``uwae reprocess`` — E3): hasil sukses = event ``extraction`` dengan
    integrity konten SUMBER; kegagalan = event ``extraction_error`` —
    kegagalan extractor TIDAK pernah mengubah status job.
    """
    for metadata in extractors.list():
        try:
            extractor = extractors.get(metadata.name)
            result = extractor.extract(artifact)
            repo.record_event(
                job_id,
                "extraction",
                json.dumps(
                    {
                        "extractor": result.extractor,
                        "format": result.format,
                        "fields": result.fields,
                        "source_sha256": result.integrity.sha256,
                        "source_size_bytes": result.integrity.size_bytes,
                    },
                    ensure_ascii=False,
                ),
            )
        except Exception as exc:
            logger.warning(
                "Job %s: extractor %s gagal: %s",
                job_id, metadata.name, exc,
            )
            repo.record_event(
                job_id,
                "extraction_error",
                json.dumps(
                    {
                        "extractor": metadata.name,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                    ensure_ascii=False,
                ),
            )


class JobWorker:
    """Worker yang mengeksekusi job melalui siklus Access Control Plane.

    Setiap attempt: adapter → observasi → classifier → planner → aksi.
    Keputusan terminal: ``ACCEPT`` (SUCCEEDED), ``NEEDS_USER``, ``ABORT``
    (FAILED). Jalur browser (raw CDP, ADR-011 decision 4) ter-wire lewat
    ``browser_adapter`` opsional: bila disediakan, planner boleh memilih
    ``USE_BROWSER`` dan worker mengeksekusinya seperti adapter lain.

    ``extractors`` opsional (ADR-006): bila disediakan, SETELAH keputusan
    terminal ACCEPT setiap extractor terdaftar dijalankan atas artifact —
    hasil tercatat sebagai event audit ``extraction`` (dengan integrity
    konten sumber); kegagalan extractor TIDAK mengubah status job (akuisisi
    tetap SUCCEEDED — ekstraksi adalah nilai tambah, bukan syarat sukses).

    ``identifier`` opsional (E2, file-first): bila disediakan, SETELAH ACCEPT
    format konten diidentifikasi dari signature (magic bytes/parse) — hasil
    sebagai event audit ``identification``; MIME/ekstensi hanya petunjuk dan
    konfliknya dicatat (artifact/identification.py).
    """

    def __init__(
        self,
        job_repository: 'JobRepository',
        scheduler: 'JobScheduler',
        registry: Optional[TransportRegistry] = None,
        storage: Optional[ArtifactStorage] = None,
        retry_policy: Optional[RetryPolicy] = None,
        browser_adapter=None,
        session_manager: Optional[SessionRecoveryManager] = None,
        extractors: Optional[PluginRegistry] = None,
        target_rules=None,
        identifier=None,
        initial_transport: Optional[str] = None,
        measure_memory: bool = False,
    ):
        """Initialize the job worker.

        Args:
            job_repository: The job repository
            scheduler: The job scheduler
            registry: Transport registry (default: build_default_registry —
                curl_cffi primary per ADR-011)
            storage: Artifact storage (default: FilesystemArtifactStorage)
            retry_policy: Bounded retry policy (default: RetryPolicy)
            browser_adapter: Optional browser executor (CDPBrowserAdapter);
                bila None, planner tidak pernah memilih USE_BROWSER
            session_manager: Optional SessionRecoveryManager (A05); bila ada,
                keputusan RECOVER_SESSION menjalankan protokol pemulihan dan
                cookies sesi aktif mengalir ke setiap attempt
            extractors: Optional PluginRegistry berisi ExtractorInterface
                (ADR-006); dijalankan setelah ACCEPT, hasil sebagai event audit
            target_rules: Optional TargetRules (aturan per-situs, §3.1); bila
                origin terdaftar soft404_as_invalid, ACCEPT dibatalkan →
                FAILED content_invalid saat soft-404 terkonfirmasi
            identifier: Optional IdentificationRegistry (E2, file-first);
                bila disediakan, SETELAH ACCEPT format konten diidentifikasi
                dari signature — event audit ``identification``
            initial_transport: Transport untuk attempt PERTAMA (policy di
                caller — preseden ADR-016 "policy stays at the caller").
                Default None = urutan prioritas registry (HTTP dulu).
                Dipakai benchmark E4 untuk membandingkan HTTP-first vs
                browser-first vs adaptif pada fixture yang sama; keputusan
                SETELAH attempt pertama tetap milik planner.
            measure_memory: Bila True, ukur peak memory per job via
                tracemalloc (P3). Default False — OFF, karena tracemalloc
                aktif secara GLOBAL dan setiap ``save_job`` ekstra di
                ``finally`` mengunci SQLite: pada runner 4-thread hal itu
                terbukti memperlambat batch (regresi
                test_hanging_url_does_not_stall_batch_beyond_timeout,
                5,5s vs ambang 4,0s; lolos di HEAD tanpa pengukuran).
                Aktifkan hanya untuk benchmark yang memang mengukur memori.
        """
        self.job_repository = job_repository
        self.scheduler = scheduler
        self.registry = registry if registry is not None else build_default_registry()
        self.storage = storage if storage is not None else FilesystemArtifactStorage()
        self.retry_policy = retry_policy if retry_policy is not None else RetryPolicy()
        self.browser_adapter = browser_adapter
        self.session_manager = session_manager
        self.extractors = extractors
        self.target_rules = target_rules
        self.identifier = identifier
        self.initial_transport = initial_transport
        self.measure_memory = measure_memory
        # Soft-404 lintas-path (bukti real-target-ampnavi-001): origin →
        # sha256 artifact → url pertama yang menghasilkannya.
        self._artifact_hashes: Dict[str, Dict[str, str]] = {}
        self._running = False
        self._work_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the job worker."""
        if self._running:
            logger.warning("Worker is already running")
            return

        # G6 (§5.2): pulihkan job yang terputus proses mati sebelum mengambil
        # pekerjaan baru — attempt RUNNING → INTERRUPTED, job diantrekan ulang
        # dalam anggaran; attempt SUCCEEDED + artifact → selesai dari bukti.
        recovered = self.job_repository.recover_interrupted()
        if recovered:
            logger.info("Pemulihan pasca-crash: %d job diproses", len(recovered))
        logger.info("Starting job worker")
        self._running = True
        self._work_task = asyncio.create_task(self._work_loop())
        logger.info("Job worker started")

    async def stop(self) -> None:
        """Stop the job worker."""
        if not self._running:
            logger.warning("Worker is not running")
        else:
            logger.info("Stopping job worker")
            self._running = False
            if self._work_task:
                self._work_task.cancel()
                try:
                    await self._work_task
                except asyncio.CancelledError:
                    pass
                self._work_task = None
        # Lifecycle browser persisten ditutup saat worker berhenti (ADR-014) —
        # juga pada early-return, agar tidak ada chromium yatim.
        close = getattr(self.browser_adapter, "close", None)
        if callable(close):
            close()
        logger.info("Job worker stopped")

    async def _work_loop(self) -> None:
        """Main work loop: pick QUEUED jobs and execute them."""
        while self._running:
            try:
                jobs = self.job_repository.list_jobs(limit=100)
                ready_jobs = [job for job in jobs if job.status == JobStatus.QUEUED]
                for job in ready_jobs:
                    await self._execute_job(job)
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in work loop: %s", e)
                await asyncio.sleep(5)

    def _select_adapter(self, url: str):
        """Pilih adapter pertama (urutan prioritas ADR-011) yang dapat menangani URL."""
        for name in self.registry.ordered_names():
            adapter = self.registry.get(name)
            if adapter.can_handle(url):
                return adapter
        return None

    def _adapter_by_name(self, name: Optional[str]):
        """Adapter berdasarkan nama (target ``SWITCH_TRANSPORT``/``USE_BROWSER``)."""
        if name is None:
            return None
        if name == BROWSER_NAME:
            return self.browser_adapter
        return self.registry.get(name)

    async def _execute_job(self, job: Job) -> None:
        """Eksekusi satu job: siklus ACP, dengan akuntansi memori opsional (P3).

        Default (``measure_memory=False``) jalurnya IDENTIK dengan sebelum
        P3: langsung ke ``_execute_job_inner`` tanpa tracemalloc dan tanpa
        ``save_job`` tambahan — terbukti perlu karena versi P3 pertama
        mengaktifkan tracemalloc secara global dan menambah satu ``save_job``
        per job di ``finally``; pada runner 4-thread itu memperlambat batch
        (regresi terukur: test_hanging_url_does_not_stall_batch_beyond_timeout
        gagal 5,5s vs ambang 4,0s, sementara lolos di HEAD tanpa pengukuran).

        Bila ``measure_memory=True`` (dipakai harness benchmark), wrapper ini
        mengukur peak memory untuk SELURUH eksekusi (termasuk semua attempt)
        dan tracing SELALU dihentikan lewat ``finally`` — bukan blok sesudah
        loop, karena setiap jalur terminal keluar dengan ``return`` DI DALAM
        loop sehingga kode sesudah loop tak pernah tercapai.
        """
        if not self.measure_memory:
            await self._execute_job_inner(job)
            return
        tracemalloc.start()
        try:
            await self._execute_job_inner(job)
        finally:
            _, peak_bytes = tracemalloc.get_traced_memory()
            job.peak_memory_bytes = peak_bytes
            tracemalloc.stop()
            # Jalur terminal di dalam inner menyimpan job SEBELUM peak memory
            # dihitung, jadi simpan sekali lagi agar angka itu sampai ke DB.
            self.job_repository.save_job(job)

    async def _execute_job_inner(self, job: Job) -> None:
        """Eksekusi satu job melalui siklus ACP (Spec v2 §1).

        Setiap iterasi: eksekusi attempt → bangun observasi → classify →
        plan → eksekusi keputusan. Loop hanya maju atas keputusan planner;
        setiap cabang mencapai keputusan terminal atau menghabiskan anggaran
        attempt (anti-siklus by construction — ADR-013).
        """
        job.mark_started()
        self.job_repository.save_job(job)

        tried: List[str] = []
        # E4: policy awal dari caller (None = urutan prioritas registry).
        # Keputusan SETELAH attempt pertama tetap milik planner.
        current_name: Optional[str] = self.initial_transport
        origin = urlparse(job.url).netloc
        # Id attempt unik per eksekusi: re-eksekusi pasca-crash tidak boleh
        # menimpa jejak attempt lama di tabel attempts (G6 audit trail).
        run_id = uuid.uuid4().hex[:8]
        attempt = 0
        while True:
            adapter = self._adapter_by_name(current_name)
            if adapter is None:
                adapter = self._select_adapter(job.url)
            if adapter is None:
                job.mark_failed(
                    f"{ReasonCode.CAPABILITY_MISSING.value}: tidak ada transport untuk {job.url}"
                )
                self.job_repository.save_job(job)
                return

            decided_at = datetime.now()
            attempt_id = f"{job.job_id}-{run_id}-att-{attempt}"
            # A05: cookies sesi aktif (jika ada) mengalir ke setiap attempt.
            cookies = None
            if self.session_manager is not None:
                entry = self.session_manager.current(origin)
                if entry is not None and isinstance(entry.session, dict):
                    cookies = entry.session.get("cookies")
            # G6: attempt dicatat RUNNING SEBELUM eksekusi — crash meninggalkan
            # jejak yang dapat dipulihkan (§5.2), bukan hilang tanpa jejak.
            self.job_repository.start_attempt(job.job_id, attempt_id, adapter.name)
            artifact = None
            failure_message = ""
            try:
                if (
                    job.method.upper() == "GET"
                    and getattr(adapter, "head", None) is not None
                    and getattr(adapter, "fetch_range", None) is not None
                ):
                    # A09: adapter HTTP dengan dukungan resume — unduhan besar
                    # lewat chunked Range dengan checkpoint durabel (§5.2);
                    # konten kecil / server tanpa Range → fallback di dalam.
                    # Non-GET TIDAK lewat sini: probe HEAD dan chunk Range
                    # adalah semantik GET, dan mengulang POST per chunk akan
                    # mengirim payload berkali-kali ke server.
                    downloader = ResumableDownloader(
                        adapter, self.job_repository, self.storage, cookies=cookies
                    )
                    artifact = await downloader.acquire(job)
                else:
                    artifact = await adapter.acquire(job, self.storage, cookies=cookies)
                observations = observations_from_artifact(
                    adapter.name, artifact, attempt
                )
            except TransportFailure as tf:
                # catatan: variabel `as tf` dihapus Python saat blok except
                # berakhir — pesan kegagalan wajib diikat DI DALAM blok
                # (regresi UnboundLocalError ditemukan benchmark E8)
                failure_message = str(tf)
                observations = observations_from_failure(
                    adapter.name,
                    tf.reason_code,
                    tf.status_code,
                    attempt,
                    headers=tf.headers,
                    body=tf.body,
                )
            except Exception as exc:  # kegagalan tak terduga → koneksi
                logger.exception("Job %s: kegagalan tak terduga", job.job_id)
                failure_message = f"{type(exc).__name__}: {exc}"
                observations = observations_from_failure(
                    adapter.name, ReasonCode.CONNECTION_ERROR, None, attempt
                )

            if artifact is not None:
                self.job_repository.finish_attempt(
                    attempt_id, "succeeded", artifact_id=artifact.artifact_id
                )
            else:
                self.job_repository.finish_attempt(attempt_id, "failed", error=failure_message)

            assessment = classify(
                observations,
                assessment_id=f"{job.job_id}-asg-{attempt}",
                job_id=job.job_id,
                attempt_id=attempt_id,
                transport_id=adapter.name,
                decided_at=decided_at,
            )
            # Evidence lineage (ACP): assessment tercatat sebagai event audit —
            # sinyal sudah ter-redaksi (nilai saja, tanpa kredensial).
            self.job_repository.record_event(
                job.job_id,
                "assessment",
                json.dumps(
                    {
                        "attempt_id": attempt_id,
                        "transport": adapter.name,
                        "state": assessment.state.value,
                        "reason_code": assessment.reason_code.value,
                        "confidence": assessment.confidence,
                        "signals": [f"{o.signal}={o.value}" for o in assessment.observations],
                    },
                    ensure_ascii=False,
                ),
            )
            untried = tuple(
                name
                for name in self.registry.ordered_names()
                if name != adapter.name and name not in tried
            )
            # Per-reason retry budget (P2) — Job init perlu dipanggil di luar loop
            retry_budget = job.retry_budget
            decision = plan(
                PlannerContext(
                    assessment=assessment,
                    retry_attempt=attempt,
                    retry_policy=self.retry_policy,
                    browser_available=self.browser_adapter is not None,
                    current_transport=adapter.name,
                    untried_transports=untried,
                    retry_budget=retry_budget,
                ),
                decision_id=f"{job.job_id}-dec-{attempt}",
                decided_at=decided_at,
            )
            # Evidence lineage (ACP): keputusan planner tercatat sebagai event audit.
            self.job_repository.record_event(
                job.job_id,
                "decision",
                json.dumps(
                    {
                        "attempt_id": attempt_id,
                        "action": decision.next_action.value,
                        "reason_code": decision.reason_code.value,
                        "wait_seconds": decision.wait_seconds,
                        "target_transport": decision.target_transport,
                        "rationale": decision.rationale,
                    },
                    ensure_ascii=False,
                ),
            )

            action = decision.next_action
            if action is NextAction.ACCEPT:
                job.mark_completed(artifact.artifact_id)
                self.job_repository.save_job(job)
                logger.info(
                    "Job %s succeeded (artifact %s, transport %s)",
                    job.job_id, artifact.artifact_id, adapter.name,
                )
                # Soft-404 lintas-path (bukti real-target-ampnavi-001): dua
                # path berbeda pada origin yang sama dengan SHA-256 artifact
                # identik → event audit; diagnosis tetap jujur (konten memang
                # valid) — perubahan state menunggu aturan target per-situs
                # (§3.1: jangan aturan universal).
                artifact_sha = hashlib.sha256(artifact.content).hexdigest()
                origin = urlparse(job.url).netloc
                seen = self._artifact_hashes.setdefault(origin, {})
                first_seen_url = seen.get(artifact_sha)
                if first_seen_url is not None and first_seen_url != job.url:
                    self.job_repository.record_event(
                        job.job_id,
                        "soft404_suspected",
                        json.dumps(
                            {
                                "sha256": artifact_sha,
                                "url": job.url,
                                "first_seen_url": first_seen_url,
                            },
                            ensure_ascii=False,
                        ),
                    )
                    # Aturan target per-situs (§3.1): bila operator menyatakan
                    # soft-404 bukan konten target untuk origin ini, keputusan
                    # ACCEPT dibatalkan — job FAILED content_invalid dengan
                    # bukti tetap tercatat. Tanpa aturan → perilaku lama.
                    if (
                        self.target_rules is not None
                        and self.target_rules.soft404_as_invalid(origin)
                    ):
                        job.mark_failed(
                            f"content_invalid: soft-404 terkonfirmasi — {job.url} "
                            f"identik dengan {first_seen_url} (aturan per-situs)"
                        )
                        self.job_repository.save_job(job)
                        logger.warning(
                            "Job %s failed: soft-404 per target rule (%s)",
                            job.job_id, origin,
                        )
                        return
                else:
                    seen.setdefault(artifact_sha, job.url)
                # Identifikasi format (E2, file-first): signature konten
                # menang atas MIME/ekstensi; hasil = event audit
                # ``identification`` — bukti, bukan syarat sukses.
                if self.identifier is not None:
                    try:
                        ident = self.identifier.identify(
                            artifact.content,
                            content_type=artifact.content_type,
                            filename=filename_from_headers(artifact.headers),
                        )
                        self.job_repository.record_event(
                            job.job_id,
                            "identification",
                            json.dumps(
                                {
                                    "format": ident.format_id,
                                    "confidence": ident.confidence,
                                    "status": ident.status,
                                    "mime": ident.mime_hint,
                                    "mime_conflict": ident.mime_conflict,
                                    "filename_hint": ident.filename_hint,
                                    "evidence": [list(e) for e in ident.evidence],
                                },
                                ensure_ascii=False,
                            ),
                        )
                    except Exception as exc:
                        logger.warning(
                            "Job %s: identifikasi gagal: %s", job.job_id, exc
                        )
                # ADR-006: ekstraksi SETELAH keputusan terminal ACCEPT —
                # nilai tambah, bukan syarat sukses; kegagalan extractor tidak
                # mengubah status job (akuisisi tetap SUCCEEDED).
                if self.extractors is not None:
                    run_extraction_plugins(
                        self.job_repository, job.job_id, artifact, self.extractors
                    )
                return
            if action is NextAction.NEEDS_USER:
                job.mark_needs_user()
                self.job_repository.save_job(job)
                logger.warning(
                    "Job %s needs user (%s): %s",
                    job.job_id, decision.reason_code.value, decision.rationale,
                )
                return
            if action is NextAction.ABORT:
                detail = failure_message or assessment.reason_code.value
                job.mark_failed(
                    f"{decision.reason_code.value}: {detail} (attempt {attempt + 1})"
                )
                self.job_repository.save_job(job)
                logger.warning(
                    "Job %s aborted (%s): %s",
                    job.job_id, decision.reason_code.value, decision.rationale,
                )
                return

            # Non-terminal: RETRY_SAME_TRANSPORT / WAIT_RETRY_AFTER /
            # INSPECT_CONTENT / COLLECT_MORE_EVIDENCE / SWITCH_TRANSPORT /
            # USE_BROWSER / RECOVER_SESSION — setiap siklus menghabiskan satu
            # attempt (anggaran planner). Kurangi retry budget per reason (P2).
            if job.retry_budget is not None:
                rc_key = decision.reason_code.value
                remaining = job.retry_budget.get(rc_key, 0)
                if remaining > 0:
                    job.retry_budget[rc_key] = remaining - 1
                else:
                    # Budget habis untuk reason ini -> harus ABORT (planner seharusnya sudah handle)
                    logger.warning(
                        "Job %s: budget habis untuk %s tapi planner memilih %s",
                        job.job_id, rc_key, action.value,
                    )

            if action is NextAction.SWITCH_TRANSPORT:
                tried.append(adapter.name)
                current_name = decision.target_transport
            elif action is NextAction.USE_BROWSER:
                if adapter.name != BROWSER_NAME:
                    tried.append(adapter.name)
                current_name = BROWSER_NAME
            elif action is NextAction.RECOVER_SESSION:
                if self.session_manager is not None:
                    # A05: jalankan protokol pemulihan 7-fase (ACP §4).
                    recovery = self.session_manager.ensure_session(origin, decided_at)
                    self.job_repository.record_event(
                        job.job_id,
                        "session_recovery",
                        json.dumps(
                            {
                                "attempt_id": attempt_id,
                                "outcome": recovery.outcome,
                                "generation": (
                                    recovery.generation.generation
                                    if recovery.generation
                                    else None
                                ),
                                "detail": recovery.detail,
                            },
                            ensure_ascii=False,
                        ),
                    )
                    if recovery.outcome == "needs_user":
                        # ACP §2.2: anggaran recovery habis → NEEDS_USER,
                        # tidak pernah dilanjutkan otomatis.
                        job.mark_needs_user()
                        self.job_repository.save_job(job)
                        logger.warning(
                            "Job %s needs user (recovery %s): %s",
                            job.job_id,
                            recovery.outcome,
                            recovery.detail,
                        )
                        return
                    # "recovered"/"failed"/"skipped_single_flight" → lanjut
                    # dalam anggaran; attempt berikutnya memakai sesi baru.
            wait = decision.wait_seconds or 0.0
            if wait > 0:
                logger.info(
                    "Job %s attempt %d: %s (%s), tunggu %.2fs",
                    job.job_id, attempt + 1, action.value,
                    decision.reason_code.value, wait,
                )
                await asyncio.sleep(wait)
            else:
                logger.info(
                    "Job %s attempt %d: %s (%s)",
                    job.job_id, attempt + 1, action.value,
                    decision.reason_code.value,
                )
            attempt += 1

        # Tidak ada kode sesudah loop: setiap jalur terminal keluar dengan
        # ``return`` di dalam loop (ACCEPT/ABORT/NEEDS_USER). Akuntansi memori
        # (P3) hidup di ``finally`` milik ``_execute_job`` — kalau ditaruh di
        # sini ia tak pernah dieksekusi.
