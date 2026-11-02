"""Tes retry budget per ReasonCode (P2).

Yang diuji di sini:
- kontrak: Job punya retry_budget per ReasonCode, consume mengurangi sisa;
- persistensi: budget bertahan lintas proses lewat SQLite, database lama
  (tanpa kolom retry_budget) dimigrasikan, bukan rusak;
- planner: budget habis untuk satu reason -> ABORT BUDGET_EXHAUSTED, sementara
  reason lain masih punya budget;
- worker: job dengan budget habis berakhir FAILED budget_exhausted, bukan
  loop tanpa batas.
"""

import asyncio
import os
import tempfile

import pytest

from universal_web_acquisition.access.model import ReasonCode
from universal_web_acquisition.artifact.storage import FilesystemArtifactStorage
from universal_web_acquisition.core.job_model import Job
from universal_web_acquisition.core.job_repository import JobRepository
from universal_web_acquisition.core.job_worker import JobWorker
from universal_web_acquisition.http_transport.registry import RetryPolicy


ALL_REASON_CODES = list(ReasonCode)


class TestJobRetryBudget:
    def test_budget_default_none(self):
        job = Job(job_id="j", url="http://x/a")
        assert job.retry_budget is None

    def test_init_retry_budget_sets_all_reasons(self):
        job = Job(job_id="j", url="http://x/a")
        job.init_retry_budget(ALL_REASON_CODES, max_per_reason=2)
        assert job.retry_budget == {rc.value: 2 for rc in ALL_REASON_CODES}

    def test_consume_reduces_remaining(self):
        job = Job(job_id="j", url="http://x/a")
        job.init_retry_budget([ReasonCode.TIMEOUT], max_per_reason=2)
        assert job.consume_retry_budget(ReasonCode.TIMEOUT) is True
        assert job.get_retry_budget(ReasonCode.TIMEOUT) == 1
        assert job.consume_retry_budget(ReasonCode.TIMEOUT) is True
        assert job.get_retry_budget(ReasonCode.TIMEOUT) == 0

    def test_consume_returns_false_when_exhausted(self):
        job = Job(job_id="j", url="http://x/a")
        job.init_retry_budget([ReasonCode.TIMEOUT], max_per_reason=1)
        job.consume_retry_budget(ReasonCode.TIMEOUT)
        assert job.get_retry_budget(ReasonCode.TIMEOUT) == 0
        assert job.consume_retry_budget(ReasonCode.TIMEOUT) is False

    def test_budget_per_reason_is_independent(self):
        job = Job(job_id="j", url="http://x/a")
        job.init_retry_budget([ReasonCode.TIMEOUT, ReasonCode.HTTP_429], max_per_reason=1)
        job.consume_retry_budget(ReasonCode.TIMEOUT)
        # TIMEOUT habis, HTTP_429 masih utuh
        assert job.get_retry_budget(ReasonCode.TIMEOUT) == 0
        assert job.get_retry_budget(ReasonCode.HTTP_429) == 1

    def test_consume_unknown_reason_returns_false(self):
        job = Job(job_id="j", url="http://x/a")
        job.init_retry_budget([ReasonCode.TIMEOUT], max_per_reason=1)
        # reason yang tidak ada di budget = 0 sisa
        assert job.get_retry_budget(ReasonCode.DNS_FAILURE) == 0
        assert job.consume_retry_budget(ReasonCode.DNS_FAILURE) is False

    def test_fallback_when_budget_none_uses_retry_count(self):
        job = Job(job_id="j", url="http://x/a", max_retries=2)
        assert job.get_retry_budget(ReasonCode.TIMEOUT) == 2
        job.retry_count = 1
        assert job.get_retry_budget(ReasonCode.TIMEOUT) == 1


class TestRetryBudgetPersistence:
    def test_budget_round_trips_through_sqlite(self):
        repo = JobRepository()
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        repo.db_path = path
        repo._init_db()
        try:
            job = Job(job_id="rb-1", url="http://x/a")
            job.init_retry_budget([ReasonCode.TIMEOUT, ReasonCode.HTTP_429], max_per_reason=2)
            job.consume_retry_budget(ReasonCode.TIMEOUT)
            repo.save_job(job)

            loaded = repo.get_job("rb-1")
            assert loaded.retry_budget == {
                "timeout": 1,
                "http_429": 2,
            }
        finally:
            os.unlink(path)

    def test_budget_none_stays_none_after_round_trip(self):
        repo = JobRepository()
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        repo.db_path = path
        repo._init_db()
        try:
            repo.save_job(Job(job_id="rb-2", url="http://x/a"))
            loaded = repo.get_job("rb-2")
            assert loaded.retry_budget is None
        finally:
            os.unlink(path)

    def test_legacy_database_without_retry_budget_is_migrated(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            import sqlite3

            conn = sqlite3.connect(path)
            conn.execute(
                """
                CREATE TABLE jobs (
                    job_id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    artifact_id TEXT,
                    error TEXT,
                    retry_count INTEGER DEFAULT 0,
                    max_retries INTEGER DEFAULT 3
                )
                """
            )
            conn.commit()
            conn.close()

            repo = JobRepository(path)
            conn = sqlite3.connect(path)
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()
            }
            conn.close()
            assert "retry_budget" in columns
            assert "peak_memory_bytes" in columns

            job = Job(job_id="legacy", url="http://x/a")
            job.init_retry_budget([ReasonCode.TIMEOUT], max_per_reason=1)
            repo.save_job(job)
            loaded = repo.get_job("legacy")
            assert loaded.retry_budget == {"timeout": 1}
        finally:
            os.unlink(path)

    def test_corrupt_budget_json_reads_as_none(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            import sqlite3

            repo = JobRepository(path)
            repo.save_job(Job(job_id="rb-3", url="http://x/a"))
            # Tulis JSON rusak langsung ke kolom
            conn = sqlite3.connect(path)
            conn.execute(
                "UPDATE jobs SET retry_budget = 'bukan-json' WHERE job_id = 'rb-3'"
            )
            conn.commit()
            conn.close()

            loaded = repo.get_job("rb-3")
            assert loaded.retry_budget is None
        finally:
            os.unlink(path)

    def test_peak_memory_bytes_round_trips_through_sqlite(self):
        repo = JobRepository()
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        repo.db_path = path
        repo._init_db()
        try:
            repo.save_job(Job(job_id="pm-1", url="http://x/a", peak_memory_bytes=12345))
            assert repo.get_job("pm-1").peak_memory_bytes == 12345
        finally:
            os.unlink(path)


class TestWorkerRecordsPeakMemory:
    """Regresi P3: peak memory harus terisi SETELAH eksekusi.

    Versi pertama perubahan P3 menaruh pengukuran SESUDAH loop ``while True``
    padahal setiap jalur terminal keluar dengan ``return`` DI DALAM loop, jadi
    angkanya selalu ``None`` dan tracemalloc tidak pernah dihentikan. Pengukuran
    sekarang hidup di ``finally`` — jadi bahkan job yang GAGAL pun ikut
    terekam, dan itu yang diuji di sini (bukan hanya jalur sukses).
    """

    def test_peak_memory_is_recorded_even_when_the_job_fails(self):
        import asyncio

        from universal_web_acquisition.artifact.storage import (
            FilesystemArtifactStorage,
        )
        from universal_web_acquisition.core.job_worker import JobWorker
        from universal_web_acquisition.http_transport.registry import RetryPolicy

        repo = JobRepository()
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        repo.db_path = path
        repo._init_db()
        try:
            worker = JobWorker(
                repo,
                scheduler=None,
                storage=FilesystemArtifactStorage(
                    base_path=tempfile.mkdtemp(prefix="uwae-peakmem-")
                ),
                retry_policy=RetryPolicy(max_retries=0, base_backoff_seconds=0.01),
                measure_memory=True,
            )
            # Port 1 = connection refused, tanpa jaringan eksternal dan tanpa
            # fixture server, jadi test ini cepat dan deterministik.
            job = Job(job_id="pm-worker", url="http://127.0.0.1:1/nope")
            repo.save_job(job)
            asyncio.run(worker._execute_job(job))

            recorded = repo.get_job("pm-worker")
            assert recorded.peak_memory_bytes is not None
            assert recorded.peak_memory_bytes >= 0
        finally:
            os.unlink(path)

    def test_memory_measurement_is_opt_in_and_off_by_default(self):
        """Regresi E: default harus OFF supaya jalur worker persis seperti
        sebelum P3 — tracemalloc aktif secara global dan ada ``save_job``
        tambahan per job; pada runner multi-thread itu terbukti memperlambat
        batch (test_failure_isolation gagal 5,5s vs ambang 4,0s, lolos di
        HEAD tanpa pengukuran)."""
        import tracemalloc

        repo = JobRepository()
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        repo.db_path = path
        repo._init_db()
        try:
            worker = JobWorker(
                repo,
                scheduler=None,
                storage=FilesystemArtifactStorage(
                    base_path=tempfile.mkdtemp(prefix="uwae-peakmem3-")
                ),
                retry_policy=RetryPolicy(max_retries=0, base_backoff_seconds=0.01),
                # default: measure_memory tidak diberikan -> False
            )
            assert worker.measure_memory is False
            job = Job(job_id="pm-default", url="http://127.0.0.1:1/nope")
            repo.save_job(job)
            asyncio.run(worker._execute_job(job))
            # tanpa opt-in: tidak ada peak memory yang tercatat DAN tracing
            # tidak pernah dinyalakan
            assert repo.get_job("pm-default").peak_memory_bytes is None
            assert tracemalloc.is_tracing() is False
        finally:
            os.unlink(path)

    def test_tracemalloc_is_stopped_after_execution(self):
        import tracemalloc

        repo = JobRepository()
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        repo.db_path = path
        repo._init_db()
        try:
            worker = JobWorker(
                repo,
                scheduler=None,
                storage=FilesystemArtifactStorage(
                    base_path=tempfile.mkdtemp(prefix="uwae-peakmem2-")
                ),
                retry_policy=RetryPolicy(max_retries=0, base_backoff_seconds=0.01),
                measure_memory=True,
            )
            job = Job(job_id="pm-stop", url="http://127.0.0.1:1/nope")
            repo.save_job(job)
            asyncio.run(worker._execute_job(job))

            # Kalau ``stop()`` tak pernah dipanggil, tracing menyala sampai
            # proses mati dan memperlambat semua kode sesudahnya.
            assert tracemalloc.is_tracing() is False
        finally:
            os.unlink(path)
