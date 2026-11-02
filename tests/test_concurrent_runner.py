"""ConcurrentJobRunner tests (E6 — eksekusi job paralel berbatas).

Yang diverifikasi:
- semua job lulus melalui engine penuh secara paralel (semua SUCCEEDED);
- isolasi kegagalan: satu job gagal TIDAK menghentikan yang lain;
- batas thread ditegakkan (n_threads < 1 → ValueError; > 16 → dibatasi 16);
- run([]) → [] (tanpa klaim palsu);
- G6: semua job tercatat di repo (enqueue sebelum eksekusi);
- latency per job terukur (last_latencies_ms terisi, panjangnya = jumlah job).
"""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from universal_web_acquisition.artifact.storage import FilesystemArtifactStorage
from universal_web_acquisition.benchmark.fixture_server import FixtureServer
from universal_web_acquisition.core.concurrent_runner import (
    MAX_THREADS,
    ConcurrentJobRunner,
)
from universal_web_acquisition.core.job_model import Job, JobStatus
from universal_web_acquisition.core.job_repository import JobRepository


def _make_repo():
    repo = JobRepository()
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo.db_path = path
    repo._init_db()
    return repo, path


class TestConcurrentJobRunner:
    def test_all_jobs_succeed(self):
        repo, db_path = _make_repo()
        storage = FilesystemArtifactStorage(
            base_path=tempfile.mkdtemp(prefix="uwae-conc-")
        )
        try:
            with FixtureServer() as base:
                runner = ConcurrentJobRunner(db_path, storage, n_threads=3)
                jobs = [
                    Job(job_id=f"c-{i}", url=base + "/html") for i in range(1, 7)
                ]
                finals = runner.run(jobs, repo=repo)
            assert len(finals) == 6
            assert all(j.status == JobStatus.SUCCEEDED for j in finals)
            assert all(j.artifact_id for j in finals)
            # latency per job terukur — panjangnya sama dengan jumlah job
            assert runner.last_latencies_ms is not None
            assert len(runner.last_latencies_ms) == 6
        finally:
            os.unlink(db_path)

    def test_failure_isolation(self):
        # satu job gagal (404) TIDAK menghentikan yang lain — status jujur
        repo, db_path = _make_repo()
        storage = FilesystemArtifactStorage(
            base_path=tempfile.mkdtemp(prefix="uwae-conc-")
        )
        try:
            with FixtureServer() as base:
                runner = ConcurrentJobRunner(db_path, storage, n_threads=3)
                jobs = [
                    Job(job_id="ok-1", url=base + "/html"),
                    Job(job_id="bad-1", url=base + "/missing"),
                    Job(job_id="ok-2", url=base + "/html"),
                ]
                finals = runner.run(jobs, repo=repo)
            by_id = {j.job_id: j for j in finals}
            assert by_id["ok-1"].status == JobStatus.SUCCEEDED
            assert by_id["ok-2"].status == JobStatus.SUCCEEDED
            assert by_id["bad-1"].status == JobStatus.FAILED
        finally:
            os.unlink(db_path)

    def test_thread_bounds(self):
        storage = FilesystemArtifactStorage(
            base_path=tempfile.mkdtemp(prefix="uwae-conc-")
        )
        with pytest.raises(ValueError):
            ConcurrentJobRunner("unused.db", storage, n_threads=0)
        runner = ConcurrentJobRunner("unused.db", storage, n_threads=99)
        assert runner.n_threads == MAX_THREADS  # dibatasi 16

    def test_empty_jobs(self):
        repo, db_path = _make_repo()
        storage = FilesystemArtifactStorage(
            base_path=tempfile.mkdtemp(prefix="uwae-conc-")
        )
        try:
            runner = ConcurrentJobRunner(db_path, storage, n_threads=2)
            assert runner.run([], repo=repo) == []
        finally:
            os.unlink(db_path)

    def test_g6_jobs_recorded_in_repo(self):
        # G6: semua job di-enqueue — terlihat di repo setelah run
        repo, db_path = _make_repo()
        storage = FilesystemArtifactStorage(
            base_path=tempfile.mkdtemp(prefix="uwae-conc-")
        )
        try:
            with FixtureServer() as base:
                runner = ConcurrentJobRunner(db_path, storage, n_threads=2)
                jobs = [
                    Job(job_id=f"g6-{i}", url=base + "/html") for i in range(1, 5)
                ]
                runner.run(jobs, repo=repo)
            for job in jobs:
                assert repo.get_job(job.job_id) is not None
        finally:
            os.unlink(db_path)
