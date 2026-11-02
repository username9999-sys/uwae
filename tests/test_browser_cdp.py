"""Browser capability spike tests (roadmap step 7, ADR-011 browser path).

Bukti, bukan klaim (mandat spike): setiap test mengukur cold start,
keberhasilan render, eksekusi JavaScript, dan konsumsi memori chromium
pada fixture deterministik localhost.
"""

import asyncio
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from universal_web_acquisition.benchmark.fixture_server import FixtureServer
from universal_web_acquisition.browser.cdp import CDPBrowser, UA_OVERRIDE, RenderResult

CDP_PORT = 9341  # hindari bentrok dengan spike manual (9333) dan E3 (9222/9223)


def _render(url: str) -> RenderResult:
    with CDPBrowser(port=CDP_PORT) as browser:
        return asyncio.run(browser.render(url))


class TestRender:
    def test_static_fixture(self):
        with FixtureServer() as base:
            result = _render(base + "/html")
        assert result.status_code == 200
        assert "fixture-ok" in result.content
        assert result.title == "UWAE Fixture"
        assert result.final_url.endswith("/html")

    def test_js_fixture_executes_javascript(self):
        # bukti eksekusi JS: placeholder diganti script menjadi rendered-by-js
        with FixtureServer() as base:
            result = _render(base + "/js")
        assert "rendered-by-js" in result.content
        assert "placeholder" not in result.content

    def test_ua_override_applied(self):
        # ADR-011 decision 7: UA wajib di-override (build ini melaporkan x86_64 di aarch64)
        with FixtureServer() as base:
            with CDPBrowser(port=CDP_PORT) as browser:
                ua = asyncio.run(browser.evaluate("navigator.userAgent"))
        assert ua == UA_OVERRIDE


class TestEvidenceMetrics:
    def test_metrics_measured(self):
        # mandat spike: cold start, render, dan memori terukur
        with FixtureServer() as base:
            result = _render(base + "/html")
        assert result.cold_start_ms > 0
        assert result.render_ms > 0
        assert result.chromium_rss_kb is not None and result.chromium_rss_kb > 0


class TestEvaluate:
    def test_basic_expression(self):
        with CDPBrowser(port=CDP_PORT) as browser:
            value = asyncio.run(browser.evaluate("1 + 1"))
        assert value == 2


# ---------------------------------------------------------------------------
# Lifecycle persisten (ADR-014 "penuh"): reuse, deteksi crash, cookie
# ---------------------------------------------------------------------------

from unittest.mock import patch

from universal_web_acquisition.artifact.storage import FilesystemArtifactStorage
from universal_web_acquisition.browser.adapter import CDPBrowserAdapter
from universal_web_acquisition.benchmark.fixture_server import (
    PROTECTED_BODY,
    SESSION_COOKIE,
    SESSION_TOKEN,
)
from universal_web_acquisition.core.job_model import Job


class _FakeBrowser:
    """CDPBrowser palsu: lifecycle tercatat, render menghasilkan artifact 200."""

    def __init__(self, **kwargs):
        self.start_calls = 0
        self.stop_calls = 0
        self.alive = False
        self.last_cookies = None
        self.render_calls = 0

    def start(self):
        self.start_calls += 1
        self.alive = True

    def stop(self):
        self.stop_calls += 1
        self.alive = False

    def is_alive(self):
        return self.alive

    async def render(self, url, cookies=None):
        self.render_calls += 1
        self.last_cookies = cookies
        if not self.alive:
            raise RuntimeError("browser mati")
        return RenderResult(
            url=url,
            final_url=url,
            status_code=200,
            content="<html><body>fake-rendered</body></html>",
            title="fake",
            cold_start_ms=1.0,
            render_ms=1.0,
            chromium_rss_kb=1000,
        )


def _fake_adapter(**kwargs):
    return CDPBrowserAdapter(keep_alive=True, **kwargs)


def _job(job_id="b1", url="http://fixture.test/x"):
    return Job(job_id=job_id, url=url)


def _storage():
    return FilesystemArtifactStorage(base_path=tempfile.mkdtemp(prefix="uwae-blife-"))


class TestPersistentLifecycleFake:
    def _run_acquire(self, adapter, job, cookies=None):
        return asyncio.run(adapter.acquire(job, _storage(), cookies=cookies))

    def test_keep_alive_reuses_browser(self):
        with patch(
            "universal_web_acquisition.browser.adapter.CDPBrowser", _FakeBrowser
        ):
            adapter = _fake_adapter()
            self._run_acquire(adapter, _job("b1"))
            self._run_acquire(adapter, _job("b2"))
            assert adapter.starts == 1  # dua acquire → satu peluncuran chromium
            assert adapter.restarts == 0
            adapter.close()
            assert adapter._browser is None

    def test_close_is_idempotent(self):
        with patch(
            "universal_web_acquisition.browser.adapter.CDPBrowser", _FakeBrowser
        ):
            adapter = _fake_adapter()
            adapter.close()
            adapter.close()  # tanpa browser → no-op, tanpa error

    def test_crash_detected_and_restarted(self):
        with patch(
            "universal_web_acquisition.browser.adapter.CDPBrowser", _FakeBrowser
        ):
            adapter = _fake_adapter()
            self._run_acquire(adapter, _job("b1"))
            # simulasi crash: proses mati di antara acquire
            adapter._browser.alive = False
            self._run_acquire(adapter, _job("b2"))
            assert adapter.restarts == 1
            assert adapter.starts == 2

    def test_non_keep_alive_starts_each_time(self):
        with patch(
            "universal_web_acquisition.browser.adapter.CDPBrowser", _FakeBrowser
        ):
            adapter = CDPBrowserAdapter(keep_alive=False)
            self._run_acquire(adapter, _job("b1"))
            self._run_acquire(adapter, _job("b2"))
            assert adapter.starts == 2  # satu siklus chromium per acquire

    def test_cookies_forwarded_to_render(self):
        with patch(
            "universal_web_acquisition.browser.adapter.CDPBrowser", _FakeBrowser
        ):
            adapter = _fake_adapter()
            cookies = {"uwae_session": "token-x"}
            self._run_acquire(adapter, _job("b1"), cookies=cookies)
            assert adapter._browser.last_cookies == cookies


class TestWorkerClosesBrowser:
    def test_stop_closes_persistent_browser(self):
        from universal_web_acquisition.core.job_repository import JobRepository
        from universal_web_acquisition.core.job_worker import JobWorker

        closed = {"n": 0}

        class _CloseOnly:
            def close(self):
                closed["n"] += 1

        worker = JobWorker(JobRepository(), scheduler=None, browser_adapter=_CloseOnly())
        asyncio.run(worker.stop())  # worker tak pernah start — tetap menutup
        assert closed["n"] == 1


class TestPersistentLifecycleReal:
    """Bukti chromium nyata: reuse lifecycle + injeksi cookie (A05 jalur browser)."""

    def test_two_acquisitions_one_start(self):
        adapter = CDPBrowserAdapter(port=CDP_PORT, keep_alive=True)
        try:
            with FixtureServer() as base:
                first = asyncio.run(
                    adapter.acquire(_job("rl-1", base + "/html"), _storage())
                )
                second = asyncio.run(
                    adapter.acquire(_job("rl-2", base + "/html"), _storage())
                )
            assert first.status_code == 200
            assert second.status_code == 200
            assert adapter.starts == 1  # reuse — bukan dua peluncuran
            assert adapter.restarts == 0
        finally:
            adapter.close()

    def test_cookie_injection_reaches_protected_resource(self):
        adapter = CDPBrowserAdapter(port=CDP_PORT, keep_alive=True)
        try:
            with FixtureServer() as base:
                # tanpa cookie → 401 (resource terproteksi menolak)
                denied = asyncio.run(
                    adapter.acquire(_job("ck-1", base + "/protected"), _storage())
                )
                # dengan cookie sesi sah → 200 + konten terproteksi
                granted = asyncio.run(
                    adapter.acquire(
                        _job("ck-2", base + "/protected"),
                        _storage(),
                        cookies={SESSION_COOKIE: SESSION_TOKEN},
                    )
                )
            assert denied.status_code == 401
            assert granted.status_code == 200
            assert PROTECTED_BODY in granted.content
        finally:
            adapter.close()
