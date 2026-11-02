"""E5 — failure isolation: satu job bermasalah tidak boleh merusak yang lain.

TEXT.md eksperimen E5: *"satu URL mengalami timeout atau error permanen
sementara pekerjaan lain harus tetap selesai."*

Tes ini memakai fixture server sungguhan dan timeout sungguhan — bukan
mock — karena yang diuji adalah sifat isolasi pada batch runner
produksi (``uwae crawl --concurrency N``).
"""

import time

import pytest

from universal_web_acquisition.artifact.storage import FilesystemArtifactStorage
from universal_web_acquisition.benchmark import failure_isolation_bench
from universal_web_acquisition.benchmark.failure_isolation_bench import (
    CrashingWorker,
    _build_registry,
)
from universal_web_acquisition.benchmark.fixture_server import FixtureServer
from universal_web_acquisition.core.concurrent_runner import ConcurrentJobRunner
from universal_web_acquisition.core.job_model import Job, JobStatus
from universal_web_acquisition.core.job_repository import JobRepository
from universal_web_acquisition.core.job_worker import JobWorker
from universal_web_acquisition.http_transport.registry import RetryPolicy

FIXTURE_PORT = 8782
CLIENT_TIMEOUT = 0.5


class CrashingAfterSuccessWorker(JobWorker):
    """Worker yang berhasil lalu melempar exception SETELAH status terminal.

    Kasus nyata: artifact tersimpan, DB ter-update, tapi exception muncul
    pada langkah sesudahnya. Guard isolasi TIDAK boleh menimpa status
    SUCCEEDED menjadi FAILED — akuisisi memang berhasil.
    """

    def __init__(self, *args, crash_job_ids=frozenset(), **kwargs):
        super().__init__(*args, **kwargs)
        self._crash_job_ids = set(crash_job_ids)

    async def _execute_job(self, job: Job) -> None:
        await super()._execute_job(job)
        if job.job_id in self._crash_job_ids:
            raise RuntimeError("injected failure setelah job sukses")


@pytest.fixture
def fixture_server():
    with FixtureServer(port=FIXTURE_PORT) as base_url:
        yield base_url


@pytest.fixture
def storage(tmp_path):
    return FilesystemArtifactStorage(base_path=str(tmp_path / "artifacts"))


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "jobs.db")


def _runner(db_path, storage, crash_ids=frozenset(), n_threads=4, timeout=CLIENT_TIMEOUT):
    registry = _build_registry(timeout_seconds=timeout)

    def _factory():
        return CrashingWorker(
            JobRepository(db_path),
            scheduler=None,
            registry=registry,
            storage=storage,
            retry_policy=RetryPolicy(max_retries=0, base_backoff_seconds=0.05),
            crash_job_ids=crash_ids,
        )

    return ConcurrentJobRunner(
        db_path=db_path,
        storage=storage,
        n_threads=n_threads,
        retry_policy=RetryPolicy(max_retries=0, base_backoff_seconds=0.05),
        worker_factory=_factory,
    )


def _jobs(base_url, fault_path=None, healthy=5):
    jobs = [Job(job_id=f"ok-{i:02d}", url=f"{base_url}/html") for i in range(healthy)]
    if fault_path is not None:
        jobs.append(Job(job_id="fault", url=f"{base_url}{fault_path}"))
    return jobs


class TestFailureIsolation:
    """Sifat inti: kegagalan satu job tidak menghentikan job lain."""

    def test_timeout_does_not_stop_other_jobs(self, fixture_server, db_path, storage):
        runner = _runner(db_path, storage)
        jobs = _jobs(fixture_server, fault_path="/hang?seconds=5")

        results = runner.run(jobs)

        assert len(results) == len(jobs)
        statuses = {job.job_id: job.status for job in results}
        assert all(statuses[f"ok-{i:02d}"] is JobStatus.SUCCEEDED for i in range(5))
        assert statuses["fault"] is JobStatus.FAILED

    def test_permanent_error_does_not_stop_other_jobs(self, fixture_server, db_path, storage):
        runner = _runner(db_path, storage)
        jobs = _jobs(fixture_server, fault_path="/missing")

        results = runner.run(jobs)

        statuses = {job.job_id: job.status for job in results}
        assert all(statuses[f"ok-{i:02d}"] is JobStatus.SUCCEEDED for i in range(5))
        assert statuses["fault"] is JobStatus.FAILED

    def test_unexpected_exception_does_not_stop_other_jobs(self, fixture_server, db_path, storage):
        """Regresi inti: exception di luar try worker tidak boleh mematikan batch.

        Tanpa guard di ``ConcurrentJobRunner._execute_one``, ``pool.map``
        meneruskan exception dan SEMUA hasil batch hilang.
        """
        runner = _runner(db_path, storage, crash_ids=frozenset(["fault"]))
        jobs = _jobs(fixture_server, fault_path="/html")

        results = runner.run(jobs)

        assert len(results) == len(jobs), "batch kehilangan hasil"
        statuses = {job.job_id: job.status for job in results}
        assert all(statuses[f"ok-{i:02d}"] is JobStatus.SUCCEEDED for i in range(5))
        assert statuses["fault"] is JobStatus.FAILED
        assert "internal_error" in (results[-1].error or "")

    def test_batch_returns_result_for_every_job(self, fixture_server, db_path, storage):
        runner = _runner(db_path, storage, crash_ids=frozenset(["fault"]))
        jobs = _jobs(fixture_server, fault_path="/html", healthy=7)

        results = runner.run(jobs)

        assert len(results) == len(jobs)
        assert {job.job_id for job in results} == {job.job_id for job in jobs}

    def test_no_false_success_on_faulted_job(self, fixture_server, db_path, storage):
        """Job bermasalah tidak boleh pernah dilaporkan sukses."""
        runner = _runner(db_path, storage)
        jobs = _jobs(fixture_server, fault_path="/missing")

        results = runner.run(jobs)

        fault = next(job for job in results if job.job_id == "fault")
        assert fault.status is not JobStatus.SUCCEEDED

    def test_hanging_url_does_not_stall_batch_beyond_timeout(self, fixture_server, db_path, storage):
        """Satu URL menggantung tidak boleh menahan batch melebihi timeout-nya."""
        runner = _runner(db_path, storage)
        jobs = _jobs(fixture_server, fault_path="/hang?seconds=5", healthy=5)

        started = time.perf_counter()
        runner.run(jobs)
        elapsed = time.perf_counter() - started

        # Server menahan 5 s; timeout klien 0,5 s → batch harus jauh di bawah
        # 5 s (sisanya hanya kerja job sehat).
        assert elapsed < 4.0, f"batch tertahan terlalu lama: {elapsed:.2f}s"

    def test_single_thread_runner_also_isolates(self, fixture_server, db_path, storage):
        """Isolasi berlaku juga pada n_threads=1 (jalur sequential)."""
        runner = _runner(db_path, storage, crash_ids=frozenset(["fault"]), n_threads=1)
        jobs = _jobs(fixture_server, fault_path="/html", healthy=3)

        results = runner.run(jobs)

        assert len(results) == len(jobs)
        statuses = {job.job_id: job.status for job in results}
        assert statuses["fault"] is JobStatus.FAILED
        assert all(statuses[f"ok-{i:02d}"] is JobStatus.SUCCEEDED for i in range(3))


class TestIsolationHonesty:
    """Guard isolasi harus jujur: tidak menimpa status yang sudah diputuskan."""

    def test_success_is_not_overwritten_by_late_exception(self, fixture_server, db_path, storage):
        registry = _build_registry(timeout_seconds=CLIENT_TIMEOUT)

        def _factory():
            return CrashingAfterSuccessWorker(
                JobRepository(db_path),
                scheduler=None,
                registry=registry,
                storage=storage,
                retry_policy=RetryPolicy(max_retries=0, base_backoff_seconds=0.05),
                crash_job_ids=frozenset(["fault"]),
            )

        runner = ConcurrentJobRunner(
            db_path=db_path,
            storage=storage,
            n_threads=2,
            worker_factory=_factory,
        )
        jobs = _jobs(fixture_server, fault_path="/html", healthy=3)

        results = runner.run(jobs)

        fault = next(job for job in results if job.job_id == "fault")
        # Akuisisi memang berhasil → tetap SUCCEEDED meski exception menyusul.
        assert fault.status is JobStatus.SUCCEEDED
        assert fault.artifact_id is not None

    def test_faulted_job_keeps_honest_error(self, fixture_server, db_path, storage):
        runner = _runner(db_path, storage, crash_ids=frozenset(["fault"]))
        jobs = _jobs(fixture_server, fault_path="/html", healthy=2)

        results = runner.run(jobs)

        fault = next(job for job in results if job.job_id == "fault")
        assert fault.status is JobStatus.FAILED
        assert "RuntimeError" in (fault.error or "")


class TestGuardIsLoadBearing:
    """Guard isolasi harus MEMANG menahan kerusakan — bukan hiasan.

    Tes ini menyimulasikan perilaku PRA-FIX (``_execute_one`` tanpa guard)
    dan membuktikan bahwa tanpanya batch benar-benar meledak: seluruh hasil
    hilang. Ini yang membuat regression test di atas bermakna.
    """

    class _PreFixRunner(ConcurrentJobRunner):
        """Runner dengan perilaku pra-fix: exception diteruskan ke pool."""

        def _execute_one(self, job: Job):
            import asyncio

            worker = self._worker_for_thread()
            asyncio.run(worker._execute_job(job))
            return job.job_id

    def test_without_guard_the_batch_explodes(self, fixture_server, db_path, storage):
        registry = _build_registry(timeout_seconds=CLIENT_TIMEOUT)

        def _factory():
            return CrashingWorker(
                JobRepository(db_path),
                scheduler=None,
                registry=registry,
                storage=storage,
                retry_policy=RetryPolicy(max_retries=0, base_backoff_seconds=0.05),
                crash_job_ids=frozenset(["fault"]),
            )

        runner = self._PreFixRunner(
            db_path=db_path,
            storage=storage,
            n_threads=2,
            worker_factory=_factory,
        )
        jobs = _jobs(fixture_server, fault_path="/html", healthy=3)

        with pytest.raises(RuntimeError, match="injected non-transport failure"):
            runner.run(jobs)

    def test_with_guard_the_same_batch_survives(self, fixture_server, db_path, storage):
        """Kontrol: dengan guard, skenario yang sama TIDAK meledak."""
        runner = _runner(db_path, storage, crash_ids=frozenset(["fault"]))
        jobs = _jobs(fixture_server, fault_path="/html", healthy=3)

        results = runner.run(jobs)

        assert len(results) == len(jobs)


class TestBenchmarkRunner:
    """Runner benchmark: bukti ter-commit tidak boleh tertimpa suite."""

    def test_runner_matches_ground_truth_for_every_scenario(self, tmp_path):
        results_path = tmp_path / "results.json"
        report_path = tmp_path / "report.md"

        doc = failure_isolation_bench.run_benchmark(
            results_path=results_path,
            report_path=report_path,
            fixture_port=FIXTURE_PORT + 1,
        )

        for run in doc["runs"]:
            assert run["matches_ground_truth"] is True, (
                f"{run['scenario']} menyimpang dari ground truth"
            )
        assert doc["summary"]["all_match_ground_truth"] is True
        assert doc["summary"]["batch_failures"] == []
        assert doc["summary"]["incomplete_batches"] == []
        assert report_path.exists()

    def test_committed_evidence_is_complete_and_consistent(self):
        """Bukti ter-commit: 4 skenario, semua sesuai ground truth."""
        import json
        from pathlib import Path

        path = Path("/root/universal-web-acquisition/docs/benchmark/engine-results-e13.json")
        if not path.exists():
            pytest.skip("bukti E5 belum digenerate")
        doc = json.loads(path.read_text(encoding="utf-8"))

        assert doc["schema_version"] == 1
        assert doc["benchmark_id"] == failure_isolation_bench.BENCHMARK_ID
        assert len(doc["runs"]) == len(failure_isolation_bench.SCENARIOS)
        for run in doc["runs"]:
            assert run["matches_ground_truth"] is True, run["scenario"]
            assert run["batch_raised"] is None, run["scenario"]
            assert run["results_complete"] is True, run["scenario"]
            assert run["healthy_all_succeeded"] is True, run["scenario"]
