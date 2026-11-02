"""G6 durability tests: job/artifact recovery after simulated process death.

Alur §5.2 INSTRUCTION.md yang diverifikasi:
- attempt yang masih RUNNING saat proses mati ditandai INTERRUPTED (bukan
  SUCCESS), lalu job diantrekan ulang — DALAM anggaran retry lintas-restart;
- attempt SUCCEEDED dengan artifact menyelesaikan job dari bukti — TANPA
  re-akuisisi (tidak ada artifact ganda, A10);
- NEEDS_USER tidak pernah dipulihkan otomatis (ACP §2.2); job terminal tidak
  disentuh;
- transisi tercatat di job_events (audit, §5.1).
"""

import asyncio
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from universal_web_acquisition.artifact.storage import FilesystemArtifactStorage
from universal_web_acquisition.benchmark.fixture_server import FixtureServer
from universal_web_acquisition.core.job_model import Job, JobStatus
from universal_web_acquisition.core.job_repository import JobRepository
from universal_web_acquisition.core.job_worker import JobWorker
from universal_web_acquisition.http_transport.registry import RetryPolicy


def _make_repo():
    """JobRepository dengan database sementara (jangan sentuh jobs.db proyek)."""
    repo = JobRepository()
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo.db_path = path
    repo._init_db()
    return repo, path


def _crash_state(repo, job_id="crash-1", url="http://fixture.test/x", retry_count=0):
    """Simulasikan state pasca-crash: job RUNNING + attempt RUNNING di DB."""
    job = Job(job_id=job_id, url=url, retry_count=retry_count)
    job.mark_started()
    repo.save_job(job)
    repo.start_attempt(job_id, f"{job_id}-att-0", "curl_cffi")
    return job


class TestAttemptRecording:
    def test_attempt_lifecycle(self):
        repo, path = _make_repo()
        try:
            repo.start_attempt("j1", "j1-att-0", "curl_cffi")
            latest = repo.latest_attempt("j1")
            assert latest["status"] == "running"
            assert latest["finished_at"] is None

            repo.finish_attempt("j1-att-0", "succeeded", artifact_id="art-1")
            latest = repo.latest_attempt("j1")
            assert latest["status"] == "succeeded"
            assert latest["artifact_id"] == "art-1"
            assert latest["finished_at"] is not None
        finally:
            os.unlink(path)

    def test_failed_attempt_records_error(self):
        repo, path = _make_repo()
        try:
            repo.start_attempt("j1", "j1-att-0", "curl_cffi")
            repo.finish_attempt("j1-att-0", "failed", error="boom: connection_error")
            latest = repo.latest_attempt("j1")
            assert latest["status"] == "failed"
            assert "connection_error" in latest["error"]
        finally:
            os.unlink(path)

    def test_latest_attempt_is_most_recent(self):
        repo, path = _make_repo()
        try:
            repo.start_attempt("j1", "j1-att-0", "curl_cffi")
            repo.finish_attempt("j1-att-0", "failed", error="x")
            repo.start_attempt("j1", "j1-att-1", "httpx")
            assert repo.latest_attempt("j1")["attempt_id"] == "j1-att-1"
            assert len(repo.list_attempts("j1")) == 2
        finally:
            os.unlink(path)


class TestRecovery:
    def test_running_attempt_interrupted_and_job_requeued(self):
        repo, path = _make_repo()
        try:
            _crash_state(repo)
            processed = repo.recover_interrupted()
            assert processed == ["crash-1"]
            # §5.2 langkah 3: attempt INTERRUPTED, bukan SUCCESS
            assert repo.latest_attempt("crash-1")["status"] == "interrupted"
            job = repo.get_job("crash-1")
            assert job.status == JobStatus.QUEUED
            assert job.retry_count == 1
            events = [e["event"] for e in repo.list_events("crash-1")]
            assert "recovered_requeued" in events
        finally:
            os.unlink(path)

    def test_succeeded_attempt_completes_job_from_evidence(self):
        # TANPA re-akuisisi → tidak ada artifact ganda (A10)
        repo, path = _make_repo()
        try:
            job = Job(job_id="ev-1", url="http://fixture.test/x")
            job.mark_started()
            repo.save_job(job)
            repo.start_attempt("ev-1", "ev-1-att-0", "curl_cffi")
            repo.finish_attempt("ev-1-att-0", "succeeded", artifact_id="art-ev-1")

            processed = repo.recover_interrupted()
            assert processed == ["ev-1"]
            final = repo.get_job("ev-1")
            assert final.status == JobStatus.SUCCEEDED
            assert final.artifact_id == "art-ev-1"
            # recovery tidak memulai attempt baru — selesai dari bukti
            assert repo.latest_attempt("ev-1")["attempt_id"] == "ev-1-att-0"
            events = [e["event"] for e in repo.list_events("ev-1")]
            assert "recovered_completed" in events
        finally:
            os.unlink(path)

    def test_recovery_respects_retry_budget(self):
        # crash-loop lintas restart dibatasi anggaran retry job
        repo, path = _make_repo()
        try:
            _crash_state(repo, job_id="bl-1", retry_count=3)
            processed = repo.recover_interrupted()
            assert processed == ["bl-1"]
            final = repo.get_job("bl-1")
            assert final.status == JobStatus.FAILED
            assert "budget_exhausted" in final.error
            assert repo.latest_attempt("bl-1")["status"] == "interrupted"
            events = [e["event"] for e in repo.list_events("bl-1")]
            assert "recovery_budget_exhausted" in events
        finally:
            os.unlink(path)

    def test_needs_user_never_auto_recovered(self):
        # ACP §2.2: NEEDS_USER tidak boleh berubah hanya karena waktu berlalu
        repo, path = _make_repo()
        try:
            job = Job(job_id="nu-1", url="http://fixture.test/x")
            job.mark_started()
            repo.save_job(job)
            job.mark_needs_user()
            repo.save_job(job)
            repo.start_attempt("nu-1", "nu-1-att-0", "curl_cffi")

            assert repo.recover_interrupted() == []
            assert repo.get_job("nu-1").status == JobStatus.NEEDS_USER
            assert repo.latest_attempt("nu-1")["status"] == "running"  # tidak disentuh
        finally:
            os.unlink(path)

    def test_terminal_job_untouched(self):
        repo, path = _make_repo()
        try:
            job = Job(job_id="done-1", url="http://fixture.test/x")
            job.mark_completed("art-1")
            repo.save_job(job)
            assert repo.recover_interrupted() == []
        finally:
            os.unlink(path)

    def test_queued_job_without_attempt_untouched(self):
        repo, path = _make_repo()
        try:
            repo.save_job(Job(job_id="q-1", url="http://fixture.test/x"))
            assert repo.recover_interrupted() == []
        finally:
            os.unlink(path)


class TestWorkerDurability:
    def test_worker_records_attempts_on_success(self):
        repo, path = _make_repo()
        try:
            worker = JobWorker(
                repo,
                scheduler=None,
                storage=FilesystemArtifactStorage(
                    base_path=tempfile.mkdtemp(prefix="uwae-dur-")
                ),
                retry_policy=RetryPolicy(max_retries=1, base_backoff_seconds=0.01),
            )
            with FixtureServer() as base:
                job = Job(job_id="dur-ok", url=base + "/html")
                repo.save_job(job)
                asyncio.run(worker._execute_job(job))
            final = repo.get_job("dur-ok")
            assert final.status == JobStatus.SUCCEEDED
            latest = repo.latest_attempt("dur-ok")
            assert latest["status"] == "succeeded"
            assert latest["artifact_id"] == final.artifact_id
        finally:
            os.unlink(path)

    def test_worker_records_failed_attempts(self):
        repo, path = _make_repo()
        try:
            worker = JobWorker(
                repo,
                scheduler=None,
                storage=FilesystemArtifactStorage(
                    base_path=tempfile.mkdtemp(prefix="uwae-dur-")
                ),
                retry_policy=RetryPolicy(max_retries=1, base_backoff_seconds=0.01),
            )
            job = Job(job_id="dur-fail", url="http://127.0.0.1:9/")
            repo.save_job(job)
            asyncio.run(worker._execute_job(job))
            final = repo.get_job("dur-fail")
            assert final.status == JobStatus.FAILED
            assert repo.latest_attempt("dur-fail")["status"] == "failed"
        finally:
            os.unlink(path)

    def test_crash_then_recover_then_reexecute(self):
        # Simulasi penuh §5.2: crash saat attempt RUNNING → pulihkan →
        # eksekusi ulang → sukses dengan jejak attempt lengkap.
        repo, path = _make_repo()
        try:
            _crash_state(repo, job_id="full-1")
            assert repo.recover_interrupted() == ["full-1"]
            assert repo.get_job("full-1").status == JobStatus.QUEUED

            worker = JobWorker(
                repo,
                scheduler=None,
                storage=FilesystemArtifactStorage(
                    base_path=tempfile.mkdtemp(prefix="uwae-dur-")
                ),
                retry_policy=RetryPolicy(max_retries=1, base_backoff_seconds=0.01),
            )
            with FixtureServer() as base:
                job = repo.get_job("full-1")
                job.url = base + "/html"  # arahkan ke fixture hidup
                repo.save_job(job)
                asyncio.run(worker._execute_job(job))

            final = repo.get_job("full-1")
            assert final.status == JobStatus.SUCCEEDED
            assert final.artifact_id is not None
            statuses = [a["status"] for a in repo.list_attempts("full-1")]
            assert statuses == ["interrupted", "succeeded"]
        finally:
            os.unlink(path)


class TestJobEvents:
    def test_events_recorded_in_order(self):
        repo, path = _make_repo()
        try:
            repo.record_event("j1", "recovered_requeued", "detail-1")
            repo.record_event("j1", "recovered_completed", "detail-2")
            events = repo.list_events("j1")
            assert [e["event"] for e in events] == [
                "recovered_requeued",
                "recovered_completed",
            ]
            assert events[0]["detail"] == "detail-1"
        finally:
            os.unlink(path)
