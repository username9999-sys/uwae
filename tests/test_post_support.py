"""Tes dukungan POST (paritas kompetitif — matriks baris 'HTTP GET/POST requests').

Sebelum perubahan ini, UWAE hanya bisa GET: `RequestSpec` punya field
`method` tapi tidak pernah dipakai, adapter hanya memanggil `client.get()`,
dan `Job` tidak punya cara menyatakan method maupun body. Matriks mencatat
Botasaurus `Verified` pada kapabilitas POST — jadi UWAE butuh jalur POST
yang benar-benar dieksekusi, bukan sekadar ada di kontrak.

Yang diuji di sini:
- kontrak: `RequestSpec` dan `Job` membawa method/body/header dan
  menormalkan method;
- persistensi: job POST bertahan lintas proses lewat SQLite, dan database
  lama (tanpa kolom `request_spec`) dimigrasikan, bukan rusak;
- wire: ketiga adapter benar-benar mengirim method, body, dan header —
  dibuktikan dari sisi server, bukan dari klaim adapter;
- cache: POST tidak pernah dilayani dari cache GET dan tidak pernah
  di-cache (kunci cache adalah URL saja);
- jalur worker: POST dieksekusi utuh dan TIDAK lewat jalur resume
  (probe HEAD + chunk Range adalah semantik GET);
- CLI: `--method POST --data ... --header 'K: V'` mengirim apa yang diminta.
"""

import asyncio
import contextlib
import json
import os
import sqlite3
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from click.testing import CliRunner

from universal_web_acquisition.artifact.storage import FilesystemArtifactStorage
from universal_web_acquisition.cli.main import cli
from universal_web_acquisition.core.job_model import Job, JobStatus
from universal_web_acquisition.core.job_repository import JobRepository
from universal_web_acquisition.core.job_worker import JobWorker
from universal_web_acquisition.http_transport.adapters import (
    CurlCffiAdapter,
    HttpxAdapter,
    RawResponse,
    RequestsAdapter,
    TransportFailure,
)
from universal_web_acquisition.http_transport.cache import CachingAdapter
from universal_web_acquisition.http_transport.contracts import RequestSpec
from universal_web_acquisition.http_transport.registry import RetryPolicy
from universal_web_acquisition.http_transport.resume import ResumableDownloader


class _RecordingHandler(BaseHTTPRequestHandler):
    """Server lokal yang MEREkam method/body/header di sisi server.

    Bukti "arm mengklaim mengirim POST" bukan bukti. Yang diukur di sini
    adalah apa yang benar-benar arrive di socket.
    """

    def _handle(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        self.server.requests.append(
            {
                "method": self.command,
                "path": self.path,
                "body": body,
                "content_type": self.headers.get("Content-Type"),
                "user_agent": self.headers.get("User-Agent"),
            }
        )
        payload = self.server.response_body
        self.send_response(self.server.response_status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = _handle
    do_POST = _handle

    def log_message(self, *args):
        pass


@contextlib.contextmanager
def _server(response_body=b"OK", response_status=200):
    """Server HTTP lokal di port bebas (0) — tidak bentrok dengan fixture 8765."""
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _RecordingHandler)
    srv.requests = []
    srv.response_body = response_body
    srv.response_status = response_status
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:%d" % srv.server_address[1], srv.requests
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def _make_repo():
    repo = JobRepository()
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo.db_path = path
    repo._init_db()
    return repo, path


class _FakeInner:
    """Adapter palsu yang mencatat argumen fetch — dipakai untuk menguji cache."""

    name = "fake"
    timeout_seconds = 5.0
    user_agent = "test-agent"

    def __init__(self):
        self.calls = []
        self.last_method = "GET"
        self.last_body = None
        self.last_headers = None

    def fetch(self, url, cookies=None, *, method="GET", body=None, headers=None):
        self.calls.append(url)
        self.last_method = method
        self.last_body = body
        self.last_headers = headers
        return RawResponse(200, b"fake-body", {"Content-Type": "text/plain"}, url)


class TestContracts:
    def test_request_spec_normalizes_method_and_carries_body(self):
        spec = RequestSpec(url="http://x/a", method="post", body=b"payload")
        assert spec.method == "POST"
        assert spec.body == b"payload"

    def test_request_spec_rejects_empty_method(self):
        with pytest.raises(ValueError):
            RequestSpec(url="http://x/a", method="   ")

    def test_job_defaults_to_get(self):
        job = Job(job_id="j", url="http://x/a")
        assert job.method == "GET"
        assert job.body is None
        assert job.headers is None

    def test_job_normalizes_method(self):
        job = Job(job_id="j", url="http://x/a", method="post")
        assert job.method == "POST"


class TestPersistence:
    def test_post_job_round_trips_through_sqlite(self):
        repo, db_path = _make_repo()
        try:
            job = Job(
                job_id="post-1",
                url="http://x/submit",
                method="POST",
                body=b"name=uwae&value=42",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            repo.save_job(job)
            loaded = repo.get_job("post-1")
            assert loaded.method == "POST"
            assert loaded.body == b"name=uwae&value=42"
            assert loaded.headers == {
                "Content-Type": "application/x-www-form-urlencoded"
            }
        finally:
            os.unlink(db_path)

    def test_plain_get_job_stays_get_after_round_trip(self):
        repo, db_path = _make_repo()
        try:
            repo.save_job(Job(job_id="get-1", url="http://x/a"))
            loaded = repo.get_job("get-1")
            assert loaded.method == "GET"
            assert loaded.body is None
            assert loaded.headers is None
        finally:
            os.unlink(db_path)

    def test_legacy_database_without_request_spec_is_migrated(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
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
            assert "request_spec" in columns

            repo.save_job(Job(job_id="legacy", url="http://x/a"))
            assert repo.get_job("legacy").method == "GET"
        finally:
            os.unlink(path)


@pytest.mark.parametrize(
    "adapter_cls",
    [CurlCffiAdapter, HttpxAdapter, RequestsAdapter],
    ids=["curl_cffi", "httpx", "requests"],
)
class TestAdapterWire:
    def test_post_reaches_server_with_method_body_and_header(self, adapter_cls):
        adapter = adapter_cls()
        adapter.timeout_seconds = 5.0
        with _server(response_body=b"POST-OK") as (base, seen):
            resp = adapter.fetch(
                base + "/submit",
                method="POST",
                body=b"name=uwae&value=42",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        assert resp.status_code == 200
        assert resp.content == b"POST-OK"
        assert len(seen) == 1
        assert seen[0]["method"] == "POST"
        assert seen[0]["body"] == b"name=uwae&value=42"
        assert seen[0]["content_type"] == "application/x-www-form-urlencoded"

    def test_get_still_works_after_the_contract_change(self, adapter_cls):
        adapter = adapter_cls()
        adapter.timeout_seconds = 5.0
        with _server(response_body=b"GET-OK") as (base, seen):
            resp = adapter.fetch(base + "/read")
        assert resp.status_code == 200
        assert resp.content == b"GET-OK"
        assert seen[0]["method"] == "GET"


class TestCacheIsolation:
    def test_post_is_never_cached(self):
        inner = _FakeInner()
        adapter = CachingAdapter(inner)
        adapter.fetch("http://x/a", method="POST", body=b"1")
        adapter.fetch("http://x/a", method="POST", body=b"1")
        assert len(inner.calls) == 2
        assert adapter.cache.get("http://x/a") is None

    def test_post_is_not_served_from_a_cached_get(self):
        inner = _FakeInner()
        adapter = CachingAdapter(inner)
        adapter.fetch("http://x/a")
        adapter.fetch("http://x/a", method="POST", body=b"payload")
        assert inner.last_method == "POST"
        assert inner.last_body == b"payload"


class TestWorkerPath:
    def test_post_job_is_acquired_end_to_end(self):
        repo, db_path = _make_repo()
        storage = FilesystemArtifactStorage(
            base_path=tempfile.mkdtemp(prefix="uwae-post-")
        )
        try:
            worker = JobWorker(
                repo,
                scheduler=None,
                storage=storage,
                retry_policy=RetryPolicy(max_retries=1, base_backoff_seconds=0.01),
            )
            with _server(response_body=b"POST-OK") as (base, seen):
                job = Job(
                    job_id="post-job",
                    url=base + "/submit",
                    method="POST",
                    body=b"name=uwae",
                    headers={"Content-Type": "text/plain"},
                )
                repo.save_job(job)
                asyncio.run(worker._execute_job(job))

                final = repo.get_job("post-job")
                assert final.status == JobStatus.SUCCEEDED
                artifact = asyncio.run(storage.retrieve(final.artifact_id))
                assert artifact.content == b"POST-OK"
                assert seen[0]["method"] == "POST"
                assert seen[0]["body"] == b"name=uwae"
        finally:
            os.unlink(db_path)

    def test_post_job_does_not_take_the_resume_path(self):
        repo, db_path = _make_repo()
        storage = FilesystemArtifactStorage(
            base_path=tempfile.mkdtemp(prefix="uwae-post-resume-")
        )
        try:
            worker = JobWorker(
                repo,
                scheduler=None,
                storage=storage,
                retry_policy=RetryPolicy(max_retries=1, base_backoff_seconds=0.01),
            )
            with _server(response_body=b"POST-OK") as (base, seen):
                job = Job(
                    job_id="post-noresume",
                    url=base + "/submit",
                    method="POST",
                    body=b"payload",
                )
                repo.save_job(job)
                asyncio.run(worker._execute_job(job))
            methods = [entry["method"] for entry in seen]
            assert methods == ["POST"]
        finally:
            os.unlink(db_path)

    def test_resume_downloader_refuses_non_get(self):
        repo, db_path = _make_repo()
        storage = FilesystemArtifactStorage(
            base_path=tempfile.mkdtemp(prefix="uwae-post-guard-")
        )
        try:
            downloader = ResumableDownloader(CurlCffiAdapter(), repo, storage)
            job = Job(job_id="p", url="http://x/a", method="POST", body=b"x")
            with pytest.raises(TransportFailure):
                asyncio.run(downloader.acquire(job))
        finally:
            os.unlink(db_path)


class TestCli:
    def test_acquire_sends_method_data_and_header(self):
        runner = CliRunner()
        db_path = tempfile.mktemp(suffix=".db")
        artifacts_dir = tempfile.mkdtemp(prefix="uwae-post-cli-")
        try:
            with _server(response_body=b"CLI-OK") as (base, seen):
                result = runner.invoke(
                    cli,
                    [
                        "acquire",
                        base + "/submit",
                        "--method",
                        "POST",
                        "--data",
                        "name=uwae",
                        "--header",
                        "Content-Type: application/x-www-form-urlencoded",
                        "--db",
                        db_path,
                        "--artifacts-dir",
                        artifacts_dir,
                    ],
                )
            assert result.exit_code == 0, result.output
            assert seen[0]["method"] == "POST"
            assert seen[0]["body"] == b"name=uwae"
            assert (
                seen[0]["content_type"] == "application/x-www-form-urlencoded"
            )
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_malformed_header_is_rejected(self):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "acquire",
                "http://127.0.0.1:1/a",
                "--header",
                "tanpa-pemisah",
            ],
        )
        assert result.exit_code != 0
        assert "Nama: nilai" in result.output
