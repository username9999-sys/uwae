"""E4 — adaptive scheduling: HTTP-first vs browser-first vs adaptif.

Tes memakai test-double browser yang dikalibrasi dari probe chromium nyata
(lihat ``docs/benchmark/strategy-comparison.md``): status HTTP apa adanya,
body non-HTML dibungkus DOM, dan eksekusi JS pada fixture ``/js``
disimulasikan. Test chromium nyata ada di kelas terakhir (dilewati bila
binary tidak tersedia).
"""

import html
import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from universal_web_acquisition.access.classifier import Signal
from universal_web_acquisition.access.model import ReasonCode
from universal_web_acquisition.artifact.model import Artifact
from universal_web_acquisition.artifact.storage import FilesystemArtifactStorage
from universal_web_acquisition.benchmark import strategy_bench
from universal_web_acquisition.benchmark.fixture_server import FixtureServer
from universal_web_acquisition.browser.adapter import BROWSER_NAME
from universal_web_acquisition.core.job_model import Job, JobStatus
from universal_web_acquisition.core.job_repository import JobRepository
from universal_web_acquisition.core.job_worker import JobWorker
from universal_web_acquisition.http_transport.registry import RetryPolicy

FIXTURE_PORT = 8791
CHROMIUM_BIN = "/usr/bin/chromium"


class FakeBrowserAdapter:
    """Stand-in browser: meniru observasi chromium pada fixture lokal.

    - status HTTP apa adanya (403/404/429 TIDAK jadi 200 — probe nyata
      menunjukkan ``performance.navigation.responseStatus`` tersedia);
    - body non-HTML dibungkus DOM seperti chromium (``<html><head></head><body>…``);
    - eksekusi JS pada fixture ``/js`` disimulasikan (gate diganti "rendered-by-js").
    """

    name = BROWSER_NAME

    def __init__(self):
        self.last_rss_kb = None
        self.starts = 0
        self.closed = False

    def can_handle(self, url: str) -> bool:
        return url.startswith(("http://", "https://"))

    async def acquire(self, job, storage, cookies=None) -> Artifact:
        self.starts += 1
        # Marker: nilai RSS tiruan — membuktikan field biaya memori benar-benar
        # dialirkan dari adapter ke laporan (bukan selalu None).
        self.last_rss_kb = 65432
        try:
            with urllib.request.urlopen(job.url, timeout=10) as response:
                status = response.status
                body = response.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
            body = exc.read()

        text = body.decode("utf-8", errors="replace")
        if status == 200 and "<html" in text.lower():
            content = text
        else:
            content = f"<html><head></head><body>{html.escape(text)}</body></html>"
        if "/js" in job.url:
            content = content.replace(
                "please enable javascript to view this page", "rendered-by-js"
            )
        artifact = Artifact(
            job_id=job.job_id,
            url=job.url,
            content=content.encode("utf-8"),
            content_type="text/html; charset=utf-8",
            status_code=status,
            headers={"user-agent": "fake-browser"},
        )
        return await storage.store(artifact)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fixture_server():
    with FixtureServer(port=FIXTURE_PORT) as base_url:
        yield base_url


@pytest.fixture
def repo(tmp_path):
    repository = JobRepository(str(tmp_path / "jobs.db"))
    yield repository
    repository.db_path = str(tmp_path / "jobs.db")


@pytest.fixture
def storage(tmp_path):
    return FilesystemArtifactStorage(base_path=str(tmp_path / "artifacts"))


def _worker_for(strategy, repo, storage):
    worker, adapter = strategy_bench._build_worker(
        strategy,
        repo,
        storage,
        browser_factory=FakeBrowserAdapter,
    )
    return worker, adapter


def _run(strategy, scenario_id, base_url, repo, storage, worker, adapter, index=0):
    return strategy_bench.run_scenario(
        strategy,
        scenario_id,
        base_url,
        repo,
        storage,
        worker,
        adapter,
        index,
    )


class TestStrategyOutcomes:
    """Cakupan & biaya tiap lengan pada fixture yang sama."""

    def test_http_only_js_gate_fails_honestly(self, fixture_server, repo, storage):
        worker, adapter = _worker_for("http_only", repo, storage)
        run = _run("http_only", "b07_js_render", fixture_server, repo, storage, worker, adapter)

        assert run["status"] == "failed"
        assert run["state"] == "javascript_required"
        assert run["browser_used"] is False
        assert run["matches_ground_truth"] is True

    def test_adaptive_escalates_to_browser_on_js_gate(self, fixture_server, repo, storage):
        worker, adapter = _worker_for("adaptive", repo, storage)
        run = _run("adaptive", "b07_js_render", fixture_server, repo, storage, worker, adapter)

        assert run["status"] == "succeeded"
        assert run["state"] == "access_granted"
        assert run["browser_used"] is True
        # HTTP lebih dulu, browser adalah eskalasi kedua — bukan pembalikan urutan.
        assert run["transports"][0] != BROWSER_NAME
        assert run["transports"][-1] == BROWSER_NAME
        assert run["matches_ground_truth"] is True

    def test_adaptive_does_not_launch_browser_for_plain_html(self, fixture_server, repo, storage):
        worker, adapter = _worker_for("adaptive", repo, storage)
        run = _run("adaptive", "b01_small_get", fixture_server, repo, storage, worker, adapter)

        assert run["status"] == "succeeded"
        assert run["browser_used"] is False
        assert adapter.starts == 0
        assert run["matches_ground_truth"] is True

    def test_browser_first_uses_browser_even_for_plain_html(self, fixture_server, repo, storage):
        worker, adapter = _worker_for("browser_first", repo, storage)
        run = _run("browser_first", "b01_small_get", fixture_server, repo, storage, worker, adapter)

        assert run["status"] == "succeeded"
        assert run["browser_used"] is True
        assert adapter.starts == 1
        assert run["matches_ground_truth"] is True

    @pytest.mark.parametrize("strategy", ["http_only", "browser_first", "adaptive"])
    def test_challenge_ends_needs_user_in_every_strategy(
        self, strategy, fixture_server, repo, storage
    ):
        worker, adapter = _worker_for(strategy, repo, storage)
        run = _run(strategy, "a07_challenge", fixture_server, repo, storage, worker, adapter)

        # Challenge tidak boleh jadi "sukses" hanya karena halaman dirender.
        assert run["status"] == "needs_user"
        assert run["state"] == "challenge_present"
        # Upaya dibatasi (G4): tidak ada loop tanpa akhir.
        assert run["attempts"] <= 4
        assert run["matches_ground_truth"] is True

    @pytest.mark.parametrize("strategy", ["http_only", "browser_first", "adaptive"])
    def test_not_found_never_succeeds(self, strategy, fixture_server, repo, storage):
        worker, adapter = _worker_for(strategy, repo, storage)
        run = _run(strategy, "e02_not_found", fixture_server, repo, storage, worker, adapter)

        assert run["status"] == "failed"
        assert run["state"] == "content_invalid"
        assert run["matches_ground_truth"] is True

    @pytest.mark.parametrize("strategy", ["http_only", "adaptive"])
    def test_invalid_bytes_visible_over_http(self, strategy, fixture_server, repo, storage):
        worker, adapter = _worker_for(strategy, repo, storage)
        run = _run(strategy, "a11_invalid_html", fixture_server, repo, storage, worker, adapter)

        assert run["status"] == "failed"
        assert run["state"] == "content_invalid"
        assert run["matches_ground_truth"] is True

    def test_browser_normalises_invalid_bytes_into_valid_dom(self, fixture_server, repo, storage):
        """Perbedaan fidelity yang TERUKUR: DOM browser menutupi byte rusak."""
        worker, adapter = _worker_for("browser_first", repo, storage)
        run = _run(
            "browser_first", "a11_invalid_html", fixture_server, repo, storage, worker, adapter
        )

        assert run["status"] == "succeeded"
        assert run["state"] == "access_granted"
        assert run["matches_ground_truth"] is True

    @pytest.mark.parametrize("strategy", ["http_only", "adaptive"])
    def test_retry_after_honoured_over_http(self, strategy, fixture_server, repo, storage):
        worker, adapter = _worker_for(strategy, repo, storage)
        run = _run(strategy, "a06_rate_limited", fixture_server, repo, storage, worker, adapter)

        assert run["state"] == "rate_limited"
        assert run["retry_after_honored"] is True
        assert run["matches_ground_truth"] is True

    def test_browser_path_cannot_honour_retry_after_header(self, fixture_server, repo, storage):
        """Browser tidak menangkap header respons → jeda server tak terlihat."""
        worker, adapter = _worker_for("browser_first", repo, storage)
        run = _run(
            "browser_first", "a06_rate_limited", fixture_server, repo, storage, worker, adapter
        )

        assert run["state"] == "rate_limited"
        assert run["retry_after_honored"] is False
        assert run["matches_ground_truth"] is True

    @pytest.mark.parametrize("strategy", ["http_only", "browser_first", "adaptive"])
    def test_login_page_is_auth_required_not_success(
        self, strategy, fixture_server, repo, storage
    ):
        worker, adapter = _worker_for(strategy, repo, storage)
        run = _run(strategy, "a04_login", fixture_server, repo, storage, worker, adapter)

        assert run["status"] == "failed"
        assert run["state"] == "auth_required"
        assert run["matches_ground_truth"] is True


class TestWorkerInitialTransport:
    """``initial_transport`` = policy awal di caller (ADR-016 preseden)."""

    def test_default_worker_keeps_registry_order(self, fixture_server, repo, storage):
        worker = JobWorker(repo, scheduler=None, storage=storage)
        job = Job(job_id="init-default", url=fixture_server + "/html")
        repo.save_job(job)

        import asyncio

        asyncio.run(worker._execute_job(job))

        assert repo.get_job(job.job_id).status == JobStatus.SUCCEEDED
        transports = [a["transport"] for a in repo.list_attempts(job.job_id)]
        assert BROWSER_NAME not in transports

    def test_initial_transport_pins_first_attempt(self, fixture_server, repo, storage):
        adapter = FakeBrowserAdapter()
        worker = JobWorker(
            repo,
            scheduler=None,
            storage=storage,
            browser_adapter=adapter,
            initial_transport=BROWSER_NAME,
        )
        job = Job(job_id="init-pinned", url=fixture_server + "/html")
        repo.save_job(job)

        import asyncio

        asyncio.run(worker._execute_job(job))

        assert repo.get_job(job.job_id).status == JobStatus.SUCCEEDED
        transports = [a["transport"] for a in repo.list_attempts(job.job_id)]
        assert transports[0] == BROWSER_NAME


class TestBenchmarkRunner:
    """Runner benchmark: bukti ter-commit tidak boleh tertimpa suite."""

    def test_runner_matches_ground_truth_for_every_strategy(self, tmp_path):
        results_path = tmp_path / "results.json"
        report_path = tmp_path / "report.md"

        doc = strategy_bench.run_benchmark(
            repeats=2,
            results_path=results_path,
            report_path=report_path,
            browser_factory=FakeBrowserAdapter,
        )

        for strategy, scenarios in doc["summary"].items():
            for scenario_id, data in scenarios.items():
                assert data["ground_truth_match_rate"] == 1.0, (
                    f"{strategy}/{scenario_id} menyimpang dari ground truth"
                )
        assert results_path.exists()
        assert report_path.exists()
        assert "| Skenario | Lengan |" in report_path.read_text(encoding="utf-8")

    def test_runner_writes_required_evidence_fields(self, tmp_path):
        results_path = tmp_path / "results.json"
        doc = strategy_bench.run_benchmark(
            repeats=1,
            results_path=results_path,
            report_path=None,
            browser_factory=FakeBrowserAdapter,
        )

        assert doc["benchmark_id"] == strategy_bench.BENCHMARK_ID
        assert doc["schema_version"] == 1
        assert doc["environment"]["repeats"] == 1
        assert set(doc["strategies"]) == set(strategy_bench.STRATEGIES)
        for run in doc["runs"]:
            assert run["status"] in {"succeeded", "failed", "needs_user"}
            assert run["elapsed_ms"] >= 0
            assert run["attempts"] >= 1

    def test_committed_evidence_has_required_schema(self):
        """Bukti ter-commit (engine-results-e12.json) harus lengkap & konsisten."""
        path = Path("/root/universal-web-acquisition/docs/benchmark/engine-results-e12.json")
        if not path.exists():
            pytest.skip("bukti E4 belum digenerate")
        doc = json.loads(path.read_text(encoding="utf-8"))

        assert doc["schema_version"] == 1
        assert doc["benchmark_id"] == strategy_bench.BENCHMARK_ID
        assert doc["environment"]["repeats"] >= 30
        assert set(doc["strategies"]) == set(strategy_bench.STRATEGIES)
        assert doc["cold_start"]["elapsed_ms"] > 0
        for strategy, scenarios in doc["summary"].items():
            for scenario_id, data in scenarios.items():
                assert data["ground_truth_match_rate"] == 1.0, (
                    f"bukti ter-commit: {strategy}/{scenario_id} tidak sesuai ground truth"
                )


class TestEvidenceIntegrity:
    """Guard terhadap bukti yang PALSU — cacat yang sudah pernah terjadi.

    Dua cacat ditemukan saat review bukti E4 pertama:
    1. ``chromium_rss_kb`` selalu ``None`` — adapter tidak pernah mengisi
       field biaya memori, sehingga laporan menampilkan "—".
    2. Cold start melaporkan ~205 ms — karena worker cold-start tidak
       menyetel ``initial_transport``, sehingga pengukuran diam-diam jatuh
       ke HTTP dan mengukur HTTP, bukan chromium.
    """

    def test_cold_start_actually_uses_browser(self, fixture_server):
        result = strategy_bench.measure_cold_start(
            fixture_server, browser_factory=FakeBrowserAdapter
        )

        assert result["browser_used"] is True
        assert BROWSER_NAME in result["transports"]
        assert result["status"] == "succeeded"

    def test_cold_start_records_browser_memory(self, fixture_server):
        result = strategy_bench.measure_cold_start(
            fixture_server, browser_factory=FakeBrowserAdapter
        )

        # Biaya memori harus ada — bukan "—". Nilai test-double adalah
        # marker bahwa field benar-benar dialirkan dari adapter.
        assert result["chromium_rss_kb"] is not None

    def test_adapter_records_rss_after_render(self, fixture_server, repo, storage):
        """Adapter harus mengisi ``last_rss_kb`` dari hasil render CDP."""
        from universal_web_acquisition.browser.cdp import CDPBrowser

        class _StubBrowser:
            def __init__(self, *args, **kwargs):
                pass

            def start(self):
                pass

            def stop(self):
                pass

            async def render(self, url, cookies=None):
                from universal_web_acquisition.browser.cdp import RenderResult

                return RenderResult(
                    url=url,
                    final_url=url,
                    content="<html><body>ok</body></html>",
                    status_code=200,
                    title="ok",
                    cold_start_ms=1.0,
                    render_ms=1.0,
                    chromium_rss_kb=123456,
                )

        import universal_web_acquisition.browser.adapter as adapter_module

        original = adapter_module.CDPBrowser
        adapter_module.CDPBrowser = _StubBrowser
        try:
            adapter = adapter_module.CDPBrowserAdapter(port=9399, keep_alive=False)
            job = Job(job_id="rss-probe", url=fixture_server + "/html")
            repo.save_job(job)

            import asyncio

            asyncio.run(adapter.acquire(job, storage))
        finally:
            adapter_module.CDPBrowser = original

        assert adapter.last_rss_kb == 123456

    def test_committed_evidence_has_no_missing_memory_figures(self):
        """Bukti ter-commit: tidak boleh ada biaya memori yang 'None'."""
        path = Path("/root/universal-web-acquisition/docs/benchmark/engine-results-e12.json")
        if not path.exists():
            pytest.skip("bukti E4 belum digenerate")
        doc = json.loads(path.read_text(encoding="utf-8"))

        assert doc["cold_start"]["chromium_rss_kb"] is not None
        assert doc["cold_start"]["browser_used"] is True
        browser_scenarios = [
            (strategy, scenario_id, data)
            for strategy, scenarios in doc["summary"].items()
            for scenario_id, data in scenarios.items()
            if data["browser_used"]
        ]
        assert browser_scenarios, "tidak ada skenario yang memakai browser"
        for strategy, scenario_id, data in browser_scenarios:
            assert data["chromium_rss_kb_max"] is not None, (
                f"{strategy}/{scenario_id} memakai browser tapi RSS tidak tercatat"
            )


class TestObservationParity:
    """Paritas diagnosis antara jalur HTTP (exception) dan jalur browser (artifact).

    Jalur browser mengembalikan respons non-2xx sebagai artifact; jalur HTTP
    melempar exception. Tanpa cabang non-2xx di ``observations_from_artifact``,
    marker challenge/login pada body 403 hilang di jalur browser dan
    klasifikasi menyimpang. Tes ini mengunci paritas itu.
    """

    def _artifact(self, status, body, content_type="text/html; charset=utf-8"):
        from universal_web_acquisition.artifact.model import Artifact

        return Artifact(
            job_id="parity",
            url="http://fixture.test/x",
            content=body.encode("utf-8"),
            content_type=content_type,
            status_code=status,
            headers={},
        )

    def _signals(self, observations):
        return {(o.signal, o.value) for o in observations}

    def test_challenge_marker_visible_on_403_artifact(self):
        from universal_web_acquisition.access.observe import observations_from_artifact

        artifact = self._artifact(403, "<html><body>Just a moment...</body></html>")
        observations = observations_from_artifact("browser", artifact, 0)

        assert (Signal.CHALLENGE, "just a moment") in self._signals(observations)

    def test_challenge_marker_visible_on_403_failure(self):
        from universal_web_acquisition.access.observe import observations_from_failure

        observations = observations_from_failure(
            "curl_cffi",
            ReasonCode.HTTP_4XX,
            403,
            0,
            headers={"Content-Type": "text/html"},
            body=b"<html><body>Just a moment...</body></html>",
        )

        assert (Signal.CHALLENGE, "just a moment") in self._signals(observations)

    def test_non_2xx_body_never_becomes_target_content(self):
        """Respons 403/404 tidak boleh pernah diklasifikasi sebagai konten target."""
        from universal_web_acquisition.access.observe import observations_from_artifact

        artifact = self._artifact(404, "<html><body>Not found</body></html>")
        observations = observations_from_artifact("browser", artifact, 0)

        assert (Signal.TARGET_MARKER, "missing") in self._signals(observations)
        assert (Signal.TARGET_MARKER, "found") not in self._signals(observations)

    def test_login_marker_visible_on_403_artifact(self):
        from universal_web_acquisition.access.observe import observations_from_artifact

        artifact = self._artifact(
            403, '<html><body><input type="password" name="p"></body></html>'
        )
        observations = observations_from_artifact("browser", artifact, 0)

        assert (Signal.LOGIN_FORM, "present") in self._signals(observations)


@pytest.mark.skipif(
    not Path(CHROMIUM_BIN).exists(), reason="chromium tidak tersedia di environment ini"
)
class TestRealChromium:
    """E4 end-to-end dengan chromium sungguhan (bukan test-double)."""

    def test_adaptive_escalates_to_real_browser_on_js_gate(self, fixture_server, repo, storage):
        from universal_web_acquisition.browser.adapter import CDPBrowserAdapter

        adapter = CDPBrowserAdapter(port=9371, keep_alive=False)
        worker = JobWorker(
            repo,
            scheduler=None,
            storage=storage,
            browser_adapter=adapter,
            retry_policy=RetryPolicy(max_retries=2, base_backoff_seconds=0.05),
        )
        job = Job(job_id="e4-real-js", url=fixture_server + "/js")
        repo.save_job(job)

        import asyncio

        try:
            asyncio.run(worker._execute_job(job))
        finally:
            adapter.close()

        final = repo.get_job(job.job_id)
        assert final.status == JobStatus.SUCCEEDED
        transports = [a["transport"] for a in repo.list_attempts(job.job_id)]
        assert transports[-1] == BROWSER_NAME
