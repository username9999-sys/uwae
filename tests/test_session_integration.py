"""A05 end-to-end: session recovery terintegrasi ke worker (ACP §4).

Skenario yang diverifikasi:
- resource terproteksi tanpa sesi → 401 → AUTH_REQUIRED → RECOVER_SESSION →
  provider melakukan login RESMI → attempt berikutnya dengan cookie → sukses;
- sesi kedaluwarsa (cookie tidak valid) → detect → recovery → sukses dengan
  generasi baru;
- recovery yang selalu gagal → anggaran habis → NEEDS_USER (tidak pernah
  dilanjutkan otomatis, ACP §2.2);
- provider unit: detect/recover/validate/commit + audit tanpa kredensial
  (§6.3);
- setiap recovery tercatat sebagai event audit (session_recovery).
"""

import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime
from urllib.parse import urlparse

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from universal_web_acquisition.artifact.storage import FilesystemArtifactStorage
from universal_web_acquisition.benchmark.fixture_server import FixtureServer
from universal_web_acquisition.core.job_model import Job, JobStatus
from universal_web_acquisition.core.job_repository import JobRepository
from universal_web_acquisition.core.job_worker import JobWorker
from universal_web_acquisition.http_transport.registry import RetryPolicy
from universal_web_acquisition.session.manager import (
    SessionRecoveryManager,
    SessionStore,
)
from universal_web_acquisition.session.providers import HTTPSessionRecoveryProvider
from universal_web_acquisition.session.recovery import (
    RecoveryAttemptTracker,
    SessionGeneration,
)


def _make_repo():
    repo = JobRepository()
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo.db_path = path
    repo._init_db()
    return repo, path


def _make_manager(base, tracker=None, store=None):
    provider = HTTPSessionRecoveryProvider(
        origin=urlparse(base).netloc,
        login_url=base + "/session-login",
        protected_url=base + "/protected",
        cookie_name="uwae_session",
    )
    manager = SessionRecoveryManager(provider=provider, tracker=tracker, store=store)
    return manager, provider


def _make_worker(repo, session_manager=None, policy=None):
    return JobWorker(
        repo,
        scheduler=None,
        storage=FilesystemArtifactStorage(base_path=tempfile.mkdtemp(prefix="uwae-a05-")),
        retry_policy=policy or RetryPolicy(max_retries=1, base_backoff_seconds=0.01),
        session_manager=session_manager,
    )


class TestProvider:
    def test_detect_without_session_is_problem(self):
        with FixtureServer() as base:
            _, provider = _make_manager(base)
            assert provider.detect(None) is True

    def test_recover_produces_valid_session(self):
        with FixtureServer() as base:
            _, provider = _make_manager(base)
            candidate = provider.recover(None)
            # login resmi menerbitkan cookie sesi
            assert candidate["cookies"]["uwae_session"] == "valid-token"
            assert provider.validate(candidate) is True
            generation = provider.commit(candidate)
            assert generation.generation == 1

    def test_detect_rejects_invalid_cookie(self):
        with FixtureServer() as base:
            _, provider = _make_manager(base)
            expired = {"cookies": {"uwae_session": "expired-token"}}
            assert provider.detect(expired) is True
            assert provider.validate(expired) is False

    def test_audit_has_no_credentials(self):
        # §6.3: payload audit tidak pernah memuat nilai token
        with FixtureServer() as base:
            manager, provider = _make_manager(base)
            manager.ensure_session(urlparse(base).netloc, datetime.now())
            assert all(
                "valid-token" not in str(event) for event in provider.audit_events
            )


class TestWorkerSessionRecovery:
    def test_protected_without_session_recovers_then_succeeds(self):
        # A05: 401 → AUTH_REQUIRED → RECOVER_SESSION → login resmi → sukses
        repo, db_path = _make_repo()
        try:
            with FixtureServer() as base:
                origin = urlparse(base).netloc
                manager, _ = _make_manager(base)
                worker = _make_worker(repo, session_manager=manager)
                job = Job(job_id="a05-1", url=base + "/protected")
                repo.save_job(job)
                asyncio.run(worker._execute_job(job))
            final = repo.get_job("a05-1")
            assert final.status == JobStatus.SUCCEEDED
            # sesi aktif tercatat dengan generasi ≥ 1
            assert manager.current_generation(origin).generation >= 1
        finally:
            os.unlink(db_path)

    def test_stale_session_recovers_with_new_generation(self):
        # sesi kedaluwarsa (cookie tidak valid) → detect → recovery → sukses
        repo, db_path = _make_repo()
        try:
            with FixtureServer() as base:
                origin = urlparse(base).netloc
                store = SessionStore()
                store.publish(
                    origin,
                    SessionGeneration(origin, 1, datetime.now()),
                    {"cookies": {"uwae_session": "expired-token"}},
                )
                manager, _ = _make_manager(base, store=store)
                worker = _make_worker(repo, session_manager=manager)
                job = Job(job_id="a05-2", url=base + "/protected")
                repo.save_job(job)
                asyncio.run(worker._execute_job(job))
            final = repo.get_job("a05-2")
            assert final.status == JobStatus.SUCCEEDED
            # generasi baru diterbitkan setelah pemulihan
            assert manager.current_generation(origin).generation >= 2
        finally:
            os.unlink(db_path)

    def test_failing_recovery_ends_needs_user(self):
        # recovery selalu gagal → anggaran habis → NEEDS_USER (ACP §2.2)
        repo, db_path = _make_repo()
        try:
            with FixtureServer() as base:
                manager, provider = _make_manager(
                    base, tracker=RecoveryAttemptTracker(max_attempts=1)
                )
                # simulasi login yang tak pernah sah: validasi selalu gagal
                provider.validate = lambda candidate: False
                worker = _make_worker(repo, session_manager=manager)
                job = Job(job_id="a05-3", url=base + "/protected")
                repo.save_job(job)
                asyncio.run(worker._execute_job(job))
            final = repo.get_job("a05-3")
            assert final.status == JobStatus.NEEDS_USER
        finally:
            os.unlink(db_path)

    def test_session_recovery_recorded_in_events(self):
        repo, db_path = _make_repo()
        try:
            with FixtureServer() as base:
                manager, _ = _make_manager(base)
                worker = _make_worker(repo, session_manager=manager)
                job = Job(job_id="a05-4", url=base + "/protected")
                repo.save_job(job)
                asyncio.run(worker._execute_job(job))
            events = repo.list_events("a05-4")
            kinds = [e["event"] for e in events]
            assert "session_recovery" in kinds
            recovery = json.loads(
                next(e["detail"] for e in events if e["event"] == "session_recovery")
            )
            assert recovery["outcome"] == "recovered"
        finally:
            os.unlink(db_path)
