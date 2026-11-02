"""Cache respons HTTP tests (dimensi kompetitif — hit selalu jujur di bukti).

Mandat TEXT.md (matriks kompetitif): Botasaurus punya cache. Yang
diverifikasi:
- ResponseCache: LRU berbatas; non-200 dan body oversize tidak di-cache;
- CachingAdapter: miss → fetch inner; hit → inner TIDAK dipanggil dan
  respons ditandai ``X-Uwae-Cache: hit``; cookies melewati cache (varian
  per-sesi tidak boleh tertukar); head/fetch_range selalu lewat server;
- evidence: job kedua pada worker ber-cache membawa sinyal ``cache.hit=hit``
  di assessment — job pertama tidak; worker tanpa cache tidak pernah
  menghasilkan sinyal itu;
- ``crawl --cache`` berjalan normal (wiring, regresi).
"""

import asyncio
import json
import os
import sys
import tempfile

import pytest
from click.testing import CliRunner

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from universal_web_acquisition.artifact.storage import FilesystemArtifactStorage
from universal_web_acquisition.benchmark.fixture_server import FixtureServer
from universal_web_acquisition.cli.main import cli
from universal_web_acquisition.core.job_model import Job, JobStatus
from universal_web_acquisition.core.job_repository import JobRepository
from universal_web_acquisition.core.job_worker import JobWorker
from universal_web_acquisition.http_transport.adapters import (
    BaseHttpAdapter,
    RawResponse,
)
from universal_web_acquisition.http_transport.cache import (
    CachingAdapter,
    ResponseCache,
    build_caching_registry,
)
from universal_web_acquisition.http_transport.registry import (
    RetryPolicy,
    TransportCapability,
)


def _make_repo():
    repo = JobRepository()
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo.db_path = path
    repo._init_db()
    return repo, path


class _FakeInner(BaseHttpAdapter):
    name = "fake"
    timeout_seconds = 5.0
    user_agent = "test-agent"

    def __init__(self, status_code=200, body=b"hello-cache"):
        self.calls = []
        self._status = status_code
        self._body = body
        self.last_method = "GET"
        self.last_body = None
        self.last_headers = None

    @property
    def capabilities(self):
        return TransportCapability()

    def fetch(self, url, cookies=None, *, method="GET", body=None, headers=None):
        self.calls.append(url)
        self.last_method = method
        self.last_body = body
        self.last_headers = headers
        return RawResponse(
            self._status, self._body, {"Content-Type": "text/plain"}, url
        )

    def head(self, url, cookies=None):
        self.calls.append("head:" + url)
        return RawResponse(200, b"", {}, url)

    def fetch_range(self, url, start, end, cookies=None):
        self.calls.append(f"range:{url}")
        return RawResponse(206, b"part", {}, url)


class TestResponseCache:
    def test_put_get_roundtrip(self):
        cache = ResponseCache()
        resp = RawResponse(200, b"body", {}, "http://x/a")
        cache.put("http://x/a", resp)
        assert cache.get("http://x/a") is resp

    def test_lru_eviction(self):
        cache = ResponseCache(max_entries=2)
        for path in ("/a", "/b", "/c"):
            cache.put(
                f"http://x{path}", RawResponse(200, b"b", {}, f"http://x{path}")
            )
        assert cache.get("http://x/a") is None  # tertua terusir
        assert cache.get("http://x/c") is not None

    def test_skip_non_200(self):
        cache = ResponseCache()
        cache.put("http://x/404", RawResponse(404, b"no", {}, "http://x/404"))
        assert cache.get("http://x/404") is None

    def test_skip_large_body(self):
        cache = ResponseCache(max_body_bytes=10)
        cache.put("http://x/big", RawResponse(200, b"x" * 11, {}, "http://x/big"))
        assert cache.get("http://x/big") is None


class TestCachingAdapter:
    def test_miss_then_hit(self):
        inner = _FakeInner()
        adapter = CachingAdapter(inner)
        first = adapter.fetch("http://x/a")
        second = adapter.fetch("http://x/a")
        assert inner.calls == ["http://x/a"]  # inner hanya dipanggil sekali
        assert first.headers.get("X-Uwae-Cache") is None
        assert second.headers["X-Uwae-Cache"] == "hit"
        assert second.content == first.content
        assert second.status_code == first.status_code

    def test_cookies_bypass_cache(self):
        inner = _FakeInner()
        adapter = CachingAdapter(inner)
        adapter.fetch("http://x/a", cookies={"s": "1"})
        adapter.fetch("http://x/a", cookies={"s": "1"})
        assert len(inner.calls) == 2  # sesi terautentikasi tidak di-cache
        # cache tetap kosong → fetch anonim berikutnya tetap miss
        adapter.fetch("http://x/a")
        assert len(inner.calls) == 3

    def test_head_passthrough(self):
        inner = _FakeInner()
        adapter = CachingAdapter(inner)
        adapter.head("http://x/a")
        adapter.fetch("http://x/a")
        assert inner.calls == ["head:http://x/a", "http://x/a"]  # head tak cache

    def test_non_200_not_cached(self):
        inner = _FakeInner(status_code=404)
        adapter = CachingAdapter(inner)
        adapter.fetch("http://x/a")
        adapter.fetch("http://x/a")
        assert len(inner.calls) == 2  # kegagalan tidak di-cache


class TestCacheEvidence:
    def test_second_job_assessment_has_cache_hit(self):
        repo, db_path = _make_repo()
        storage = FilesystemArtifactStorage(
            base_path=tempfile.mkdtemp(prefix="uwae-cache-")
        )
        try:
            worker = JobWorker(
                repo,
                scheduler=None,
                storage=storage,
                retry_policy=RetryPolicy(max_retries=1, base_backoff_seconds=0.01),
                registry=build_caching_registry(),
            )
            with FixtureServer() as base:
                signals_by_job = {}
                for job_id in ("c1", "c2"):
                    job = Job(job_id=job_id, url=base + "/html")
                    repo.save_job(job)
                    asyncio.run(worker._execute_job(job))
                    assert repo.get_job(job_id).status == JobStatus.SUCCEEDED
                    events = repo.list_events(job_id)
                    assessment = next(
                        e["detail"] for e in events if e["event"] == "assessment"
                    )
                    signals_by_job[job_id] = json.loads(assessment)["signals"]
            # job pertama: fetch asli — tanpa sinyal cache
            assert not any(
                s.startswith("cache.hit=") for s in signals_by_job["c1"]
            )
            # job kedua: respons dari cache — sinyal cache.hit=hit (jujur)
            assert "cache.hit=hit" in signals_by_job["c2"]
        finally:
            os.unlink(db_path)

    def test_without_cache_no_signal(self):
        repo, db_path = _make_repo()
        storage = FilesystemArtifactStorage(
            base_path=tempfile.mkdtemp(prefix="uwae-nocache-")
        )
        try:
            worker = JobWorker(
                repo,
                scheduler=None,
                storage=storage,
                retry_policy=RetryPolicy(max_retries=1, base_backoff_seconds=0.01),
            )
            with FixtureServer() as base:
                for job_id in ("n1", "n2"):
                    job = Job(job_id=job_id, url=base + "/html")
                    repo.save_job(job)
                    asyncio.run(worker._execute_job(job))
                    events = repo.list_events(job_id)
                    assessment = next(
                        e["detail"] for e in events if e["event"] == "assessment"
                    )
                    signals = json.loads(assessment)["signals"]
                    assert not any(s.startswith("cache.hit=") for s in signals)
        finally:
            os.unlink(db_path)


class TestCrawlCacheFlag:
    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_crawl_with_cache_flag_runs(self, runner):
        db = tempfile.mktemp(suffix=".db")
        artifacts = tempfile.mkdtemp(prefix="uwae-cachecrawl-")
        try:
            with FixtureServer() as base:
                result = runner.invoke(
                    cli,
                    [
                        "crawl",
                        base,
                        "--cache",
                        "--json",
                        "--db",
                        db,
                        "--artifacts-dir",
                        artifacts,
                    ],
                )
            assert result.exit_code == 0, result.output
            payload = json.loads(result.output)
            assert payload["discovered"] == 1
            assert payload["summary"]["succeeded"] == 1
        finally:
            if os.path.exists(db):
                os.unlink(db)
