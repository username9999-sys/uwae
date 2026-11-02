"""A09 tests: interrupted download & resume (§5.2 INSTRUCTION.md).

Yang diverifikasi:
- fixture: HEAD probe (Accept-Ranges + Content-Length), fetch_range slice
  benar, hook interupsi memutus koneksi TEPAT SEKALI pada chunk ke-N;
- ResumableDownloader: unduhan besar lengkap dengan checkpoint per chunk;
  checkpoint stale (ETag berubah / part file hilang) → dibuang, unduh dari
  awal — jangan gabungkan byte spekulatif (§5.2);
- fallback: server tanpa Range / konten kecil → unduh penuh (tercatat);
- worker e2e: interupsi di tengah unduhan → checkpoint durabel → attempt
  berikutnya MELANJUTKAN (bukan mengulang) → artifact utuh (sha256 == body
  sumber, tanpa duplikasi/lompatan byte).
"""

import asyncio
import hashlib
import json
import os
import sys
import tempfile
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from universal_web_acquisition.artifact.storage import FilesystemArtifactStorage
from universal_web_acquisition.benchmark.fixture_server import (
    RANGE_BODY,
    RANGE_ETAG,
    RANGE_TOTAL,
    FixtureServer,
)
from universal_web_acquisition.core.job_model import Job, JobStatus
from universal_web_acquisition.core.job_repository import JobRepository
from universal_web_acquisition.core.job_worker import JobWorker
from universal_web_acquisition.http_transport.adapters import (
    CurlCffiAdapter,
    TransportFailure,
)
from universal_web_acquisition.http_transport.registry import RetryPolicy
from universal_web_acquisition.http_transport.resume import ResumableDownloader

CHUNK = 64 * 1024


def _make_repo():
    repo = JobRepository()
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo.db_path = path
    repo._init_db()
    return repo, path


def _make_storage():
    return FilesystemArtifactStorage(base_path=tempfile.mkdtemp(prefix="uwae-a09-"))


class TestFixtureRange:
    def test_head_probe_reports_accept_ranges(self):
        adapter = CurlCffiAdapter()
        with FixtureServer() as base:
            head = adapter.head(base + "/large-download")
        assert head.status_code == 200
        headers = {k.lower(): v for k, v in head.headers.items()}
        assert headers.get("accept-ranges") == "bytes"
        assert int(headers["content-length"]) == RANGE_TOTAL
        assert headers.get("etag") == RANGE_ETAG

    def test_fetch_range_returns_requested_slice(self):
        adapter = CurlCffiAdapter()
        with FixtureServer() as base:
            resp = adapter.fetch_range(base + "/large-download", 1000, 1999)
        assert resp.status_code == 206
        assert resp.content == RANGE_BODY[1000:2000]
        headers = {k.lower(): v for k, v in resp.headers.items()}
        assert headers["content-range"] == f"bytes 1000-1999/{RANGE_TOTAL}"


class TestInterruptHook:
    def test_interrupt_breaks_connection_once(self):
        adapter = CurlCffiAdapter()
        session = uuid.uuid4().hex
        with FixtureServer() as base:
            url = base + f"/large-download?session={session}&fail_after_chunks=2"
            first = adapter.fetch_range(url, 0, CHUNK - 1)
            assert first.status_code == 206  # chunk 1 normal
            with pytest.raises(Exception):
                adapter.fetch_range(url, CHUNK, 2 * CHUNK - 1)  # chunk 2 → putus
            # setelah interupsi, request berikutnya normal lagi (tepat sekali)
            third = adapter.fetch_range(url, 2 * CHUNK, 3 * CHUNK - 1)
            assert third.status_code == 206


class TestResumableDownloader:
    def _downloader(self, repo, storage):
        return ResumableDownloader(CurlCffiAdapter(), repo, storage)

    def test_large_download_completes_with_checkpoints(self):
        repo, db_path = _make_repo()
        try:
            storage = _make_storage()
            downloader = self._downloader(repo, storage)
            with FixtureServer() as base:
                job = Job(job_id="rd-1", url=base + "/large-download")
                repo.save_job(job)
                artifact = asyncio.run(downloader.acquire(job))
            assert artifact.content == RANGE_BODY
            events = [e["event"] for e in repo.list_events("rd-1")]
            assert events.count("download_checkpoint") == RANGE_TOTAL // CHUNK
            assert "download_completed" in events
            assert "download_full_fallback" not in events
        finally:
            os.unlink(db_path)

    def test_stale_checkpoint_discarded_when_etag_changed(self):
        repo, db_path = _make_repo()
        try:
            storage = _make_storage()
            repo.record_event(
                "rd-2",
                "download_checkpoint",
                json.dumps({"bytes": 2 * CHUNK, "total": RANGE_TOTAL, "etag": '"stale"'}),
            )
            downloader = self._downloader(repo, storage)
            with FixtureServer() as base:
                job = Job(job_id="rd-2", url=base + "/large-download")
                repo.save_job(job)
                artifact = asyncio.run(downloader.acquire(job))
            # dibuang → unduh dari awal → tetap benar (tanpa byte spekulatif)
            assert artifact.content == RANGE_BODY
            events = [e["event"] for e in repo.list_events("rd-2")]
            assert "checkpoint_discarded" in events
        finally:
            os.unlink(db_path)

    def test_checkpoint_without_part_file_discarded(self):
        repo, db_path = _make_repo()
        try:
            storage = _make_storage()
            repo.record_event(
                "rd-3",
                "download_checkpoint",
                json.dumps({"bytes": 2 * CHUNK, "total": RANGE_TOTAL, "etag": RANGE_ETAG}),
            )
            downloader = self._downloader(repo, storage)
            with FixtureServer() as base:
                job = Job(job_id="rd-3", url=base + "/large-download")
                repo.save_job(job)
                artifact = asyncio.run(downloader.acquire(job))
            assert artifact.content == RANGE_BODY
            events = [e["event"] for e in repo.list_events("rd-3")]
            assert "checkpoint_discarded" in events
        finally:
            os.unlink(db_path)

    def test_small_content_falls_back_to_full(self):
        repo, db_path = _make_repo()
        try:
            storage = _make_storage()
            downloader = self._downloader(repo, storage)
            with FixtureServer() as base:
                job = Job(job_id="rd-4", url=base + "/html")
                repo.save_job(job)
                artifact = asyncio.run(downloader.acquire(job))
            assert artifact.status_code == 200
            events = [e["event"] for e in repo.list_events("rd-4")]
            assert "download_full_fallback" in events
        finally:
            os.unlink(db_path)

    def test_no_range_server_downloads_full(self):
        repo, db_path = _make_repo()
        try:
            storage = _make_storage()
            downloader = self._downloader(repo, storage)
            with FixtureServer() as base:
                job = Job(job_id="rd-5", url=base + "/no-range")
                repo.save_job(job)
                artifact = asyncio.run(downloader.acquire(job))
            assert artifact.content == RANGE_BODY  # unduh penuh, bukan spekulatif
            events = [e["event"] for e in repo.list_events("rd-5")]
            assert "download_full_fallback" in events
        finally:
            os.unlink(db_path)


class TestWorkerA09:
    def test_worker_resumes_after_interruption(self):
        repo, db_path = _make_repo()
        try:
            storage = _make_storage()
            worker = JobWorker(
                repo,
                scheduler=None,
                storage=storage,
                retry_policy=RetryPolicy(max_retries=2, base_backoff_seconds=0.01),
            )
            session = uuid.uuid4().hex
            with FixtureServer() as base:
                job = Job(
                    job_id="a09-1",
                    url=base + f"/large-download?session={session}&fail_after_chunks=3",
                )
                repo.save_job(job)
                asyncio.run(worker._execute_job(job))
            final = repo.get_job("a09-1")
            assert final.status == JobStatus.SUCCEEDED
            # integritas: artifact utuh — tanpa duplikasi/lompatan byte
            artifact = asyncio.run(storage.retrieve(final.artifact_id))
            assert len(artifact.content) == RANGE_TOTAL
            assert (
                hashlib.sha256(artifact.content).hexdigest()
                == hashlib.sha256(RANGE_BODY).hexdigest()
            )
            # bukti resume: ≥1 checkpoint durabel + 2 attempt (putus → lanjut)
            checkpoints = [
                e for e in repo.list_events("a09-1") if e["event"] == "download_checkpoint"
            ]
            assert checkpoints, "tidak ada checkpoint"
            first_bytes = json.loads(checkpoints[0]["detail"])["bytes"]
            assert 0 < first_bytes < RANGE_TOTAL
            assert len(repo.list_attempts("a09-1")) == 2
        finally:
            os.unlink(db_path)

    def test_worker_small_page_unaffected(self):
        repo, db_path = _make_repo()
        try:
            storage = _make_storage()
            worker = JobWorker(
                repo,
                scheduler=None,
                storage=storage,
                retry_policy=RetryPolicy(max_retries=1, base_backoff_seconds=0.01),
            )
            with FixtureServer() as base:
                job = Job(job_id="a09-2", url=base + "/html")
                repo.save_job(job)
                asyncio.run(worker._execute_job(job))
            final = repo.get_job("a09-2")
            assert final.status == JobStatus.SUCCEEDED
            assert len(repo.list_attempts("a09-2")) == 1
        finally:
            os.unlink(db_path)
