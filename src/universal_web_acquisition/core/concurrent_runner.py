"""Concurrent job runner (E6 — Tahap H TEXT.md: concurrency/scale).

Kapasitas eksekusi paralel di atas kontrak yang sama dengan worker
sequential — kejujuran tetap dijaga:

- G6: SEMUA job di-enqueue (save) SEBELUM eksekusi — terlihat di DB meski
  proses mati di tengah jalan;
- worker per-thread (``threading.local``): repo + registry/adapter sendiri
  per thread — JobRepository membuka koneksi SQLite baru per metode (aman
  lintas-thread), adapter transport tidak dibagi antar-thread;
- ``n_threads`` berbatas (default 4, maks 16) — tanpa klaim scale tak
  terbatas;
- kegagalan satu job TIDAK menghentikan yang lain — hasil akhir jujur per
  job (status apa adanya, bukan sukses palsu).

Perbandingan kinerja WAJIB lewat benchmark (E11 baseline sequential vs
skenario concurrent di throughput_bench) — bukan klaim.
"""

import asyncio
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional

from universal_web_acquisition.core.job_model import Job, JobStatus
from universal_web_acquisition.core.job_repository import JobRepository
from universal_web_acquisition.core.job_worker import JobWorker
from universal_web_acquisition.http_transport.registry import RetryPolicy

logger = logging.getLogger(__name__)

MAX_THREADS = 16

# Status yang SUDAH diputuskan — tidak boleh ditimpa oleh guard isolasi:
# akuisisi yang berhasil tetap sukses walau exception muncul sesudahnya.
_DECIDED_STATUSES = (
    JobStatus.SUCCEEDED,
    JobStatus.FAILED,
    JobStatus.CANCELED,
    JobStatus.NEEDS_USER,
)


class ConcurrentJobRunner:
    """Eksekusi job paralel berbatas — worker per-thread, G6 terjaga."""

    def __init__(
        self,
        db_path: str,
        storage,
        n_threads: int = 4,
        retry_policy: Optional[RetryPolicy] = None,
        worker_factory=None,
    ):
        if n_threads < 1:
            raise ValueError("n_threads minimal 1")
        self.n_threads = min(int(n_threads), MAX_THREADS)
        self.db_path = db_path
        self.storage = storage
        self.retry_policy = retry_policy or RetryPolicy(
            max_retries=1, base_backoff_seconds=0.01
        )
        # worker_factory: injeksi wiring khusus (cache/identifier) untuk
        # benchmark apple-to-apple; default = worker minimal per thread.
        self._worker_factory = worker_factory
        self._local = threading.local()
        # Durasi eksekusi per job (ms) dari run() terakhir — list.append
        # atomic di CPython, aman diisi dari thread pool tanpa lock.
        self.last_latencies_ms: Optional[List[float]] = None
        self._durations: List[float] = []

    def _worker_for_thread(self) -> JobWorker:
        """Worker satu per thread — dibuat sekali, dipakai ulang."""
        worker = getattr(self._local, "worker", None)
        if worker is None:
            if self._worker_factory is not None:
                worker = self._worker_factory()
            else:
                worker = JobWorker(
                    JobRepository(self.db_path),
                    scheduler=None,
                    storage=self.storage,
                    retry_policy=self.retry_policy,
                )
            self._local.worker = worker
        return worker

    def _execute_one(self, job: Job):
        worker = self._worker_for_thread()
        started = time.perf_counter()
        try:
            asyncio.run(worker._execute_job(job))
        except Exception as exc:  # TEXT.md E5 — failure isolation
            # Kegagalan tak terduga DI LUAR blok try worker (mis. penulisan
            # DB, artifact store di jalur sukses) tidak boleh mematikan seluruh
            # batch. Tanpa guard ini, pool.map meneruskan exception dan
            # SEMUA hasil batch hilang — satu job merusak pekerjaan lain.
            logger.exception("Job %s: kegagalan tak terduga", job.job_id)
            # Status yang SUDAH diputuskan tidak ditimpa: akuisisi yang
            # berhasil tetap sukses walau exception muncul sesudahnya.
            if job.status not in _DECIDED_STATUSES:
                try:
                    job.mark_failed(f"internal_error: {type(exc).__name__}: {exc}")
                    worker.job_repository.save_job(job)
                except Exception:
                    logger.exception("Job %s: gagal merekam kegagalan", job.job_id)
        finally:
            self._durations.append((time.perf_counter() - started) * 1000)
        return job.job_id

    def run(self, jobs: List[Job], repo: Optional[JobRepository] = None) -> List[Job]:
        """Enqueue semua job (G6) lalu eksekusi paralel berbatas.

        ``repo`` (opsional) = repository utama untuk save/get — default
        repository baru pada ``db_path`` yang sama. Mengembalikan status
        final tiap job apa adanya (termasuk kegagalan).
        """
        if not jobs:
            return []
        main_repo = repo if repo is not None else JobRepository(self.db_path)
        for job in jobs:
            main_repo.save_job(job)  # G6: enqueue sebelum eksekusi

        self._durations = []
        with ThreadPoolExecutor(max_workers=self.n_threads) as pool:
            list(pool.map(self._execute_one, jobs))
        self.last_latencies_ms = sorted(self._durations)

        return [main_repo.get_job(job.job_id) for job in jobs]
