"""Fase 2 implementation tests: transport adapters + worker execution.

Uses the deterministic E5 fixture server (localhost) so adapter behaviour is
verified byte-for-byte without touching the network. Worker tests verify the
real execution path (registry → adapter → artifact) and the bounded-retry
contract (ADR-011) against an unreachable port.
"""

import asyncio
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from universal_web_acquisition.access.model import ReasonCode
from universal_web_acquisition.artifact.storage import FilesystemArtifactStorage
from universal_web_acquisition.benchmark.fixture_server import GROUND_TRUTHS, FixtureServer
from universal_web_acquisition.core.job_model import Job, JobStatus
from universal_web_acquisition.core.job_repository import JobRepository
from universal_web_acquisition.core.job_worker import JobWorker
from universal_web_acquisition.http_transport.adapters import (
    CurlCffiAdapter,
    HttpxAdapter,
    RequestsAdapter,
    TransportFailure,
    build_default_registry,
)
from universal_web_acquisition.http_transport.registry import RetryPolicy


def _make_repo():
    """JobRepository dengan database sementara (jangan sentuh jobs.db proyek)."""
    repo = JobRepository()
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo.db_path = path
    repo._init_db()
    return repo, path


def _make_storage():
    return FilesystemArtifactStorage(base_path=tempfile.mkdtemp(prefix="uwae-test-artifacts-"))


class TestRegistry:
    def test_priority_order_curl_cffi_first(self):
        # ADR-011: curl_cffi primary
        assert build_default_registry().ordered_names() == ["curl_cffi", "httpx", "requests"]

    def test_curl_cffi_capabilities(self):
        caps = build_default_registry().capabilities("curl_cffi")
        assert caps.tls_fingerprint is True
        assert caps.http2 is True
        assert caps.brotli is True

    def test_ordered_names_preserved_after_insert(self):
        from universal_web_acquisition.http_transport.registry import TransportCapability, TransportRegistry

        reg = TransportRegistry()
        reg.register("b", object(), TransportCapability())
        reg.register("a", object(), TransportCapability())
        assert reg.ordered_names() == ["b", "a"]  # urutan registrasi, bukan alfabetis
        assert reg.names() == ["a", "b"]  # names() tetap stabil alfabetis


@pytest.mark.parametrize("adapter_cls", [CurlCffiAdapter, HttpxAdapter, RequestsAdapter])
class TestAdaptersAgainstFixture:
    def test_acquire_success_byte_for_byte(self, adapter_cls, tmp_path):
        adapter = adapter_cls()
        with FixtureServer() as base:
            storage = FilesystemArtifactStorage(base_path=str(tmp_path))
            job = Job(job_id=f"t-{adapter.name}", url=base + "/html")
            artifact = asyncio.run(adapter.acquire(job, storage))
        assert artifact.status_code == 200
        assert artifact.content == GROUND_TRUTHS["b01_small_get"]["body"]

    def test_acquire_follows_redirects(self, adapter_cls, tmp_path):
        adapter = adapter_cls()
        with FixtureServer() as base:
            storage = FilesystemArtifactStorage(base_path=str(tmp_path))
            job = Job(job_id=f"r-{adapter.name}", url=base + "/redirect")
            artifact = asyncio.run(adapter.acquire(job, storage))
        # B04: 3-hop chain (301 → 302 → 307) → final content
        assert artifact.content == GROUND_TRUTHS["b04_redirect"]["body"]
        assert artifact.url.endswith("/final")

    def test_acquire_decodes_gzip(self, adapter_cls, tmp_path):
        adapter = adapter_cls()
        with FixtureServer() as base:
            storage = FilesystemArtifactStorage(base_path=str(tmp_path))
            job = Job(job_id=f"g-{adapter.name}", url=base + "/gzip")
            artifact = asyncio.run(adapter.acquire(job, storage))
        assert artifact.content == GROUND_TRUTHS["b06_gzip"]["body"]


class TestFailureClassification:
    def test_404_raises_http_4xx(self):
        adapter = CurlCffiAdapter()
        with FixtureServer() as base:
            storage = _make_storage()
            job = Job(job_id="nf", url=base + "/missing")
            with pytest.raises(TransportFailure) as exc_info:
                asyncio.run(adapter.acquire(job, storage))
        assert exc_info.value.reason_code is ReasonCode.HTTP_4XX
        assert exc_info.value.status_code == 404

    def test_dns_failure_classified(self):
        adapter = CurlCffiAdapter()
        assert adapter.classify_exception(Exception("Name or service not known")) is ReasonCode.DNS_FAILURE
        assert (
            adapter.classify_exception(Exception("dial tcp: lookup x.invalid: no such host"))
            is ReasonCode.DNS_FAILURE
        )

    def test_timeout_classified(self):
        adapter = CurlCffiAdapter()
        assert adapter.classify_exception(TimeoutError("timed out")) is ReasonCode.TIMEOUT
        assert adapter.classify_exception(Exception("connection timed out")) is ReasonCode.TIMEOUT

    def test_tls_classified(self):
        adapter = CurlCffiAdapter()
        assert (
            adapter.classify_exception(Exception("SSL certificate verify failed"))
            is ReasonCode.TLS_ERROR
        )


class TestWorkerExecution:
    def test_end_to_end_success(self, tmp_path):
        repo, db_path = _make_repo()
        try:
            storage = FilesystemArtifactStorage(base_path=str(tmp_path / "artifacts"))
            worker = JobWorker(
                repo, scheduler=None, storage=storage,
                retry_policy=RetryPolicy(max_retries=1, base_backoff_seconds=0.01),
            )
            with FixtureServer() as base:
                job = Job(job_id="e2e-1", url=base + "/html")
                repo.save_job(job)
                asyncio.run(worker._execute_job(job))
            final = repo.get_job("e2e-1")
            assert final.status == JobStatus.SUCCEEDED
            assert final.artifact_id is not None
            assert final.artifact_id in storage._get_artifact_path(final.artifact_id)
        finally:
            os.unlink(db_path)

    def test_bounded_retry_on_connection_failure(self, tmp_path):
        repo, db_path = _make_repo()
        try:
            storage = FilesystemArtifactStorage(base_path=str(tmp_path / "artifacts"))
            worker = JobWorker(
                repo, scheduler=None, storage=storage,
                retry_policy=RetryPolicy(max_retries=1, base_backoff_seconds=0.01),
            )
            # port 9 (discard) di localhost → connection refused, cepat
            job = Job(job_id="br-1", url="http://127.0.0.1:9/")
            repo.save_job(job)
            asyncio.run(worker._execute_job(job))
            final = repo.get_job("br-1")
            assert final.status == JobStatus.FAILED
            # retry berbatas: anggaran habis → BUDGET_EXHAUSTED, bukan loop tanpa akhir (E6)
            assert "budget_exhausted" in final.error
        finally:
            os.unlink(db_path)

    def test_no_adapter_capability_missing(self, tmp_path):
        repo, db_path = _make_repo()
        try:
            worker = JobWorker(
                repo, scheduler=None, storage=FilesystemArtifactStorage(base_path=str(tmp_path)),
                retry_policy=RetryPolicy(max_retries=1, base_backoff_seconds=0.01),
            )
            job = Job(job_id="cap-1", url="ftp://example.com/file")
            repo.save_job(job)
            asyncio.run(worker._execute_job(job))
            final = repo.get_job("cap-1")
            assert final.status == JobStatus.FAILED
            assert "capability_missing" in final.error
        finally:
            os.unlink(db_path)

    def test_non_retryable_404_fails_fast(self, tmp_path):
        # regresi: jalur non-retryable memicu UnboundLocalError (variabel `as tf`
        # dihapus Python saat blok except berakhir) — ditemukan oleh benchmark E8
        repo, db_path = _make_repo()
        try:
            storage = FilesystemArtifactStorage(base_path=str(tmp_path / "artifacts"))
            worker = JobWorker(
                repo, scheduler=None, storage=storage,
                retry_policy=RetryPolicy(max_retries=1, base_backoff_seconds=0.01),
            )
            with FixtureServer() as base:
                job = Job(job_id="nr-1", url=base + "/missing")
                repo.save_job(job)
                asyncio.run(worker._execute_job(job))
            final = repo.get_job("nr-1")
            assert final.status == JobStatus.FAILED
            assert "http_4xx" in final.error  # reason code terstruktur, tanpa crash
        finally:
            os.unlink(db_path)
