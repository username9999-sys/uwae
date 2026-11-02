"""Worker ↔ Access Control Plane integration tests (pasca-roadmap).

Verifies the Observe → Diagnose → Decide loop end-to-end with fake adapters:
explicit denial → NEEDS_USER (never auto-retried, ACP §2.2), rate limit →
bounded retry → BUDGET_EXHAUSTED, cost-ordered transport escalation on
persistent network failure, and no false success from an empty HTTP 200
(Spec v2: keberhasilan tidak boleh disimpulkan hanya dari status 200).
"""

import asyncio
import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from universal_web_acquisition.access.model import ReasonCode
from universal_web_acquisition.artifact.model import Artifact
from universal_web_acquisition.artifact.storage import FilesystemArtifactStorage
from universal_web_acquisition.benchmark.fixture_server import FixtureServer
from universal_web_acquisition.browser.adapter import CDPBrowserAdapter
from universal_web_acquisition.core.job_model import Job, JobStatus
from universal_web_acquisition.core.job_repository import JobRepository
from universal_web_acquisition.core.job_worker import JobWorker
from universal_web_acquisition.http_transport.adapters import (
    TransportFailure,
    build_default_registry,
)
from universal_web_acquisition.http_transport.registry import (
    RetryPolicy,
    TransportCapability,
    TransportRegistry,
)


def _make_repo():
    """JobRepository dengan database sementara (jangan sentuh jobs.db proyek)."""
    repo = JobRepository()
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo.db_path = path
    repo._init_db()
    return repo, path


class _FakeAdapter:
    """Adapter uji: perilaku tetap (artifact sukses atau exception)."""

    def __init__(self, name, behavior):
        self.name = name
        self.behavior = behavior
        self.calls = 0

    def can_handle(self, url):
        return True

    async def acquire(self, job, storage, cookies=None):
        self.calls += 1
        if isinstance(self.behavior, Exception):
            raise self.behavior
        return await storage.store(self.behavior)


def _worker(repo, adapters, retry_policy=None):
    registry = TransportRegistry()
    for adapter in adapters:
        registry.register(adapter.name, adapter, TransportCapability())
    return JobWorker(
        repo,
        scheduler=None,
        registry=registry,
        storage=FilesystemArtifactStorage(
            base_path=tempfile.mkdtemp(prefix="uwae-acp-artifacts-")
        ),
        retry_policy=retry_policy or RetryPolicy(max_retries=1, base_backoff_seconds=0.01),
    )


def _artifact(job_id, content=b"payload"):
    return Artifact(job_id=job_id, url="http://fixture.test/x", content=content)


def _run_job(worker, repo, job_id):
    job = Job(job_id=job_id, url="http://fixture.test/x")
    repo.save_job(job)
    asyncio.run(worker._execute_job(job))
    return repo.get_job(job_id)


class TestValidatedSuccess:
    def test_nonempty_200_succeeds_once(self):
        repo, db_path = _make_repo()
        try:
            ok = _FakeAdapter("only", _artifact("ok-1"))
            worker = _worker(repo, [ok])
            final = _run_job(worker, repo, "ok-1")
            assert final.status == JobStatus.SUCCEEDED
            assert final.artifact_id is not None
            assert ok.calls == 1  # sukses tidak pernah diulang (§4.2)
        finally:
            os.unlink(db_path)


class TestDeniedNeedsUser:
    def test_403_denied_marks_needs_user_never_retried(self):
        # ACP §2.2: DENIED tidak boleh diatasi dengan mengulang request —
        # NEEDS_USER (intervensi pengguna), bukan FAILED dan bukan retry.
        repo, db_path = _make_repo()
        try:
            denied = _FakeAdapter(
                "only", TransportFailure(ReasonCode.HTTP_4XX, "forbidden", status_code=403)
            )
            worker = _worker(repo, [denied])
            final = _run_job(worker, repo, "denied-1")
            assert final.status == JobStatus.NEEDS_USER
            assert denied.calls == 1  # tidak pernah di-retry
        finally:
            os.unlink(db_path)


class TestRateLimitedBounded:
    def test_429_retries_within_budget_then_budget_exhausted(self):
        repo, db_path = _make_repo()
        try:
            limited = _FakeAdapter(
                "only", TransportFailure(ReasonCode.HTTP_429, "slow down", status_code=429)
            )
            worker = _worker(
                repo, [limited], RetryPolicy(max_retries=1, base_backoff_seconds=0.01)
            )
            final = _run_job(worker, repo, "rl-1")
            assert final.status == JobStatus.FAILED
            assert "budget_exhausted" in final.error
            # max_retries=1 → attempt awal + 2 siklus backoff (attempt 0 dan 1
            # masih dalam anggaran), attempt 2 di luar anggaran → ABORT
            assert limited.calls == 3
        finally:
            os.unlink(db_path)


class TestTransportEscalation:
    def test_persistent_network_failure_switches_then_succeeds(self):
        # Eskalasi biaya terurut (ADR-013): transport pertama habis anggaran →
        # transport lain yang belum dicoba → sukses.
        repo, db_path = _make_repo()
        try:
            failing = _FakeAdapter(
                "first", TransportFailure(ReasonCode.CONNECTION_ERROR, "refused")
            )
            working = _FakeAdapter("second", _artifact("esc-1"))
            worker = _worker(
                repo,
                [failing, working],
                RetryPolicy(max_retries=0, base_backoff_seconds=0.01),
            )
            final = _run_job(worker, repo, "esc-1")
            assert final.status == JobStatus.SUCCEEDED
            assert failing.calls == 2  # attempt 0 + 1 retry (max_retries=0)
            assert working.calls == 1
        finally:
            os.unlink(db_path)

    def test_all_transports_exhausted_aborts_with_budget_reason(self):
        repo, db_path = _make_repo()
        try:
            first = _FakeAdapter(
                "first", TransportFailure(ReasonCode.CONNECTION_ERROR, "refused")
            )
            second = _FakeAdapter(
                "second", TransportFailure(ReasonCode.CONNECTION_ERROR, "refused")
            )
            worker = _worker(
                repo,
                [first, second],
                RetryPolicy(max_retries=0, base_backoff_seconds=0.01),
            )
            final = _run_job(worker, repo, "esc-2")
            assert final.status == JobStatus.FAILED
            assert "budget_exhausted" in final.error
            assert first.calls == 2
            assert second.calls == 1  # satu attempt, lalu anggaran habis
        finally:
            os.unlink(db_path)


class TestNoFalseSuccess:
    def test_empty_200_body_is_not_success(self):
        # HTTP 200 dengan body kosong → CONTENT_INVALID, bukan ACCESS_GRANTED
        repo, db_path = _make_repo()
        try:
            empty = _FakeAdapter("only", _artifact("empty-1", content=b""))
            worker = _worker(repo, [empty])
            final = _run_job(worker, repo, "empty-1")
            assert final.status == JobStatus.FAILED
            assert "content_invalid" in final.error
        finally:
            os.unlink(db_path)


class TestAuthBudget:
    def test_persistent_401_ends_in_needs_user_not_infinite_loop(self):
        # 401 terus-menerus: RECOVER_SESSION bergerbang anggaran — setelah
        # anggaran habis → ABORT (bukan loop login tak berujung, §4.3).
        repo, db_path = _make_repo()
        try:
            auth = _FakeAdapter(
                "only", TransportFailure(ReasonCode.HTTP_4XX, "unauthorized", status_code=401)
            )
            worker = _worker(
                repo, [auth], RetryPolicy(max_retries=1, base_backoff_seconds=0.01)
            )
            final = _run_job(worker, repo, "auth-1")
            assert final.status == JobStatus.FAILED
            assert "http_4xx" in final.error
            # attempt 0 (RECOVER_SESSION) + attempt 1 (RECOVER_SESSION) +
            # attempt 2 (ABORT) = 3 panggilan, lalu berhenti
            assert auth.calls == 3
        finally:
            os.unlink(db_path)


class TestBrowserEscalation:
    """Jalur USE_BROWSER: gerbang JS/challenge di-escalahkan ke browser."""

    def test_js_gate_escalates_to_browser_and_succeeds(self):
        repo, db_path = _make_repo()
        try:
            http = _FakeAdapter(
                "http",
                _artifact(
                    "js-1",
                    content=b"<html>please enable javascript to view this page</html>",
                ),
            )
            browser = _FakeAdapter(
                "browser", _artifact("js-1", content=b"<html>rendered-by-js</html>")
            )
            worker = _worker(repo, [http])
            worker.browser_adapter = browser
            final = _run_job(worker, repo, "js-1")
            assert final.status == JobStatus.SUCCEEDED
            assert http.calls == 1  # gerbang JS tidak di-retry via HTTP
            assert browser.calls == 1
        finally:
            os.unlink(db_path)

    def test_persistent_challenge_escalates_then_needs_user(self):
        repo, db_path = _make_repo()
        try:
            challenge_body = b"<html>Just a moment...</html>"
            http = _FakeAdapter("http", _artifact("ch-1", content=challenge_body))
            browser = _FakeAdapter("browser", _artifact("ch-1", content=challenge_body))
            worker = _worker(repo, [http])
            worker.browser_adapter = browser
            final = _run_job(worker, repo, "ch-1")
            assert final.status == JobStatus.NEEDS_USER
            assert http.calls == 1
            assert browser.calls == 2  # dua siklus browser, lalu anggaran habis
        finally:
            os.unlink(db_path)


class _SpyStorage(FilesystemArtifactStorage):
    """Storage perekam: artifact terakhir yang disimpan (untuk asersi isi)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.last = None

    async def store(self, artifact):
        stored = await super().store(artifact)
        self.last = stored
        return stored


class TestBrowserRealCDP:
    """Bukti ujung-ke-ujung: worker mengeskalahkan /js ke chromium nyata.

    Ini adalah bukti milestone wiring browser (mandat: bukti, bukan klaim):
    konten artifact memuat ``rendered-by-js`` — hanya mungkin bila JavaScript
    benar-benar dieksekusi oleh browser, bukan fetch HTTP.
    """

    def test_js_fixture_acquired_via_browser_render(self):
        repo, db_path = _make_repo()
        try:
            storage = _SpyStorage(base_path=tempfile.mkdtemp(prefix="uwae-cdp-"))
            worker = JobWorker(
                repo,
                scheduler=None,
                registry=build_default_registry(),
                storage=storage,
                retry_policy=RetryPolicy(max_retries=1, base_backoff_seconds=0.01),
                browser_adapter=CDPBrowserAdapter(),
            )
            with FixtureServer() as base:
                job = Job(job_id="cdp-1", url=base + "/js")
                repo.save_job(job)
                asyncio.run(worker._execute_job(job))
            final = repo.get_job("cdp-1")
            assert final.status == JobStatus.SUCCEEDED
            assert storage.last is not None
            assert b"rendered-by-js" in storage.last.content
            assert b"please enable javascript" not in storage.last.content
        finally:
            os.unlink(db_path)


class TestWorkerDiagnosisScenarios:
    """Skenario diagnosis §6.1 di jalur worker: klasifikasi → tindakan sesuai
    ground truth (A04/A06/A07/A11)."""

    def _worker_with_fixture(self, repo, policy=None):
        return JobWorker(
            repo,
            scheduler=None,
            storage=FilesystemArtifactStorage(
                base_path=tempfile.mkdtemp(prefix="uwae-scen-")
            ),
            retry_policy=policy or RetryPolicy(max_retries=1, base_backoff_seconds=0.01),
        )

    def test_rate_limited_honors_server_wait_then_budget(self):
        # A06: 429+Retry-After(1 s) → WAIT_RETRY_AFTER berbatas → budget_exhausted
        repo, db_path = _make_repo()
        try:
            worker = self._worker_with_fixture(repo)
            with FixtureServer() as base:
                job = Job(job_id="a06-1", url=base + "/rate-limited")
                repo.save_job(job)
                asyncio.run(worker._execute_job(job))
            final = repo.get_job("a06-1")
            assert final.status == JobStatus.FAILED
            assert "budget_exhausted" in final.error
            assert len(repo.list_attempts("a06-1")) == 3  # 0,1 dalam anggaran + abort
        finally:
            os.unlink(db_path)

    def test_challenge_fixture_ends_needs_user(self):
        # A07: 403+signature → CHALLENGE_PRESENT → tanpa browser → NEEDS_USER
        repo, db_path = _make_repo()
        try:
            worker = self._worker_with_fixture(repo)
            with FixtureServer() as base:
                job = Job(job_id="a07-1", url=base + "/challenge")
                repo.save_job(job)
                asyncio.run(worker._execute_job(job))
            final = repo.get_job("a07-1")
            assert final.status == JobStatus.NEEDS_USER
            assert len(repo.list_attempts("a07-1")) == 1  # tidak di-retry
        finally:
            os.unlink(db_path)

    def test_denied_fixture_never_retried(self):
        # 403 polos → ACCESS_DENIED → NEEDS_USER, tepat 1 attempt (ACP §2.2)
        repo, db_path = _make_repo()
        try:
            worker = self._worker_with_fixture(repo)
            with FixtureServer() as base:
                job = Job(job_id="a07d-1", url=base + "/denied")
                repo.save_job(job)
                asyncio.run(worker._execute_job(job))
            final = repo.get_job("a07d-1")
            assert final.status == JobStatus.NEEDS_USER
            assert len(repo.list_attempts("a07d-1")) == 1
        finally:
            os.unlink(db_path)

    def test_login_fixture_bounded_then_failed(self):
        # A04: 200+form login → RECOVER_SESSION berbatas → ABORT login_form_present
        repo, db_path = _make_repo()
        try:
            worker = self._worker_with_fixture(repo)
            with FixtureServer() as base:
                job = Job(job_id="a04-1", url=base + "/login")
                repo.save_job(job)
                asyncio.run(worker._execute_job(job))
            final = repo.get_job("a04-1")
            assert final.status == JobStatus.FAILED
            assert "login_form_present" in final.error
        finally:
            os.unlink(db_path)

    def test_invalid_html_fixture_not_success(self):
        # A11: 200 dengan body bukan HTML valid → CONTENT_INVALID → bukan sukses
        repo, db_path = _make_repo()
        try:
            worker = self._worker_with_fixture(repo)
            with FixtureServer() as base:
                job = Job(job_id="a11-1", url=base + "/invalid-html")
                repo.save_job(job)
                asyncio.run(worker._execute_job(job))
            final = repo.get_job("a11-1")
            assert final.status == JobStatus.FAILED
            assert "content_invalid" in final.error
        finally:
            os.unlink(db_path)


class TestEvidenceLineage:
    """ACP: job → attempt → observasi + keputusan dapat ditelusuri penuh."""

    def test_assessment_and_decision_recorded_as_events(self):
        repo, db_path = _make_repo()
        try:
            worker = JobWorker(
                repo,
                scheduler=None,
                storage=FilesystemArtifactStorage(
                    base_path=tempfile.mkdtemp(prefix="uwae-lin-")
                ),
                retry_policy=RetryPolicy(max_retries=1, base_backoff_seconds=0.01),
            )
            with FixtureServer() as base:
                job = Job(job_id="lin-1", url=base + "/html")
                repo.save_job(job)
                asyncio.run(worker._execute_job(job))
            events = repo.list_events("lin-1")
            kinds = [e["event"] for e in events]
            assert "assessment" in kinds
            assert "decision" in kinds
            # payload JSON dapat diurai dan berisi state/action
            assessment = json.loads(
                next(e["detail"] for e in events if e["event"] == "assessment")
            )
            decision = json.loads(
                next(e["detail"] for e in events if e["event"] == "decision")
            )
            assert assessment["state"] == "access_granted"
            assert assessment["signals"], "sinyal kosong"
            assert decision["action"] == "accept"
            assert decision["reason_code"] == "ok"
        finally:
            os.unlink(db_path)


class TestExtractionWiring:
    """ADR-006: extractor dijalankan SETELAH ACCEPT — nilai tambah, bukan
    syarat sukses; kegagalan extractor tidak mengubah status job."""

    def _worker_with_extractor(self, repo, failing=False):
        from universal_web_acquisition.extract.html_text import HTMLTextExtractor
        from universal_web_acquisition.plugins.registry import PluginRegistry

        registry = PluginRegistry()
        extractor = HTMLTextExtractor()
        if failing:
            # simulasi extractor yang selalu gagal
            extractor.extract = lambda artifact: (_ for _ in ()).throw(
                RuntimeError("boom")
            )
        registry.register(extractor)
        return JobWorker(
            repo,
            scheduler=None,
            storage=FilesystemArtifactStorage(
                base_path=tempfile.mkdtemp(prefix="uwae-ext-")
            ),
            retry_policy=RetryPolicy(max_retries=1, base_backoff_seconds=0.01),
            extractors=registry,
        )

    def test_extraction_recorded_after_accept(self):
        repo, db_path = _make_repo()
        try:
            worker = self._worker_with_extractor(repo)
            with FixtureServer() as base:
                job = Job(job_id="ext-1", url=base + "/html")
                repo.save_job(job)
                asyncio.run(worker._execute_job(job))
            final = repo.get_job("ext-1")
            assert final.status == JobStatus.SUCCEEDED
            events = repo.list_events("ext-1")
            extraction = json.loads(
                next(e["detail"] for e in events if e["event"] == "extraction")
            )
            assert extraction["extractor"] == "html-text-extractor"
            assert extraction["format"] == "html_text"
            assert extraction["fields"]["title"] == "UWAE Fixture"
            # hasil tertelusur ke konten sumber (integrity sha256)
            assert extraction["source_sha256"]
            assert extraction["source_size_bytes"] > 0
        finally:
            os.unlink(db_path)

    def test_failing_extractor_does_not_break_acquisition(self):
        repo, db_path = _make_repo()
        try:
            worker = self._worker_with_extractor(repo, failing=True)
            with FixtureServer() as base:
                job = Job(job_id="ext-2", url=base + "/html")
                repo.save_job(job)
                asyncio.run(worker._execute_job(job))
            final = repo.get_job("ext-2")
            # kegagalan ekstraksi TIDAK mengubah status akuisisi
            assert final.status == JobStatus.SUCCEEDED
            events = repo.list_events("ext-2")
            error = json.loads(
                next(e["detail"] for e in events if e["event"] == "extraction_error")
            )
            assert error["extractor"] == "html-text-extractor"
            assert "RuntimeError" in error["error"]
        finally:
            os.unlink(db_path)

    def test_no_extractors_no_extraction_events(self):
        repo, db_path = _make_repo()
        try:
            worker = JobWorker(
                repo,
                scheduler=None,
                storage=FilesystemArtifactStorage(
                    base_path=tempfile.mkdtemp(prefix="uwae-ext-")
                ),
                retry_policy=RetryPolicy(max_retries=1, base_backoff_seconds=0.01),
            )
            with FixtureServer() as base:
                job = Job(job_id="ext-3", url=base + "/html")
                repo.save_job(job)
                asyncio.run(worker._execute_job(job))
            final = repo.get_job("ext-3")
            assert final.status == JobStatus.SUCCEEDED
            kinds = [e["event"] for e in repo.list_events("ext-3")]
            assert "extraction" not in kinds
        finally:
            os.unlink(db_path)


class TestSoft404Detection:
    """Soft-404 lintas-path (bukti ampnavi): hash identik lintas path berbeda
    pada origin yang sama → event audit; path sama / lintas origin tidak."""

    def _worker(self, repo):
        return JobWorker(
            repo,
            scheduler=None,
            storage=FilesystemArtifactStorage(
                base_path=tempfile.mkdtemp(prefix="uwae-s404-")
            ),
            retry_policy=RetryPolicy(max_retries=1, base_backoff_seconds=0.01),
        )

    def test_duplicate_content_across_paths_recorded(self):
        repo, db_path = _make_repo()
        try:
            worker = self._worker(repo)
            with FixtureServer() as base:
                for job_id, path in (("s1", "/mirror/a"), ("s2", "/mirror/b")):
                    job = Job(job_id=job_id, url=base + path)
                    repo.save_job(job)
                    asyncio.run(worker._execute_job(job))
            first = repo.list_events("s1")
            second = repo.list_events("s2")
            assert not any(e["event"] == "soft404_suspected" for e in first)
            soft = json.loads(
                next(e["detail"] for e in second if e["event"] == "soft404_suspected")
            )
            assert soft["first_seen_url"].endswith("/mirror/a")
            assert soft["url"].endswith("/mirror/b")
            assert soft["sha256"]
        finally:
            os.unlink(db_path)

    def test_same_path_reacquired_not_flagged(self):
        # re-akuisisi path yang SAMA bukan soft-404 — sah dan tidak dicatat
        repo, db_path = _make_repo()
        try:
            worker = self._worker(repo)
            with FixtureServer() as base:
                for job_id in ("s1", "s2"):
                    job = Job(job_id=job_id, url=base + "/mirror/a")
                    repo.save_job(job)
                    asyncio.run(worker._execute_job(job))
            for job_id in ("s1", "s2"):
                events = repo.list_events(job_id)
                assert not any(e["event"] == "soft404_suspected" for e in events)
        finally:
            os.unlink(db_path)

    def test_cross_origin_not_flagged(self):
        # hash dilacak per origin — konten identik di origin berbeda bukan soft-404
        # (server kedua perlu port eksplisit: FixtureServer default port 8765)
        repo, db_path = _make_repo()
        try:
            worker = self._worker(repo)
            with FixtureServer() as base1:
                with FixtureServer(port=8766) as base2:
                    for job_id, base in (("s1", base1), ("s2", base2)):
                        job = Job(job_id=job_id, url=base + "/mirror/a")
                        repo.save_job(job)
                        asyncio.run(worker._execute_job(job))
            for job_id in ("s1", "s2"):
                events = repo.list_events(job_id)
                assert not any(e["event"] == "soft404_suspected" for e in events)
        finally:
            os.unlink(db_path)


class TestTargetRules:
    """Aturan target per-situs (§3.1): soft-404 terkonfirmasi → FAILED
    content_invalid HANYA bila origin terdaftar — tanpa aturan universal."""

    def _worker(self, repo, target_rules=None):
        return JobWorker(
            repo,
            scheduler=None,
            storage=FilesystemArtifactStorage(
                base_path=tempfile.mkdtemp(prefix="uwae-rules-")
            ),
            retry_policy=RetryPolicy(max_retries=1, base_backoff_seconds=0.01),
            target_rules=target_rules,
        )

    def test_registered_origin_soft404_fails_content_invalid(self):
        from urllib.parse import urlparse

        from universal_web_acquisition.access.target_rules import TargetRules

        repo, db_path = _make_repo()
        try:
            rules = TargetRules()
            with FixtureServer() as base:
                rules.register_soft404_invalid(urlparse(base).netloc)
                worker = self._worker(repo, target_rules=rules)
                for job_id, path in (("r1", "/mirror/a"), ("r2", "/mirror/b")):
                    job = Job(job_id=job_id, url=base + path)
                    repo.save_job(job)
                    asyncio.run(worker._execute_job(job))
            first = repo.get_job("r1")
            second = repo.get_job("r2")
            # path pertama tetap sukses (belum ada bukti lintas-path)
            assert first.status == JobStatus.SUCCEEDED
            # path kedua: soft-404 terkonfirmasi + aturan aktif → FAILED
            assert second.status == JobStatus.FAILED
            assert "content_invalid" in second.error
            # bukti tetap tercatat penuh meski keputusan berubah
            events = repo.list_events("r2")
            soft = json.loads(
                next(e["detail"] for e in events if e["event"] == "soft404_suspected")
            )
            assert soft["first_seen_url"].endswith("/mirror/a")
            assert soft["url"].endswith("/mirror/b")
        finally:
            os.unlink(db_path)

    def test_without_rules_both_succeed(self):
        # tanpa aturan → perilaku jujur secara teknis: konten valid = granted;
        # bukti soft-404 tetap dicatat meski keputusan tidak berubah
        repo, db_path = _make_repo()
        try:
            worker = self._worker(repo)
            with FixtureServer() as base:
                for job_id, path in (("r3", "/mirror/a"), ("r4", "/mirror/b")):
                    job = Job(job_id=job_id, url=base + path)
                    repo.save_job(job)
                    asyncio.run(worker._execute_job(job))
            assert repo.get_job("r3").status == JobStatus.SUCCEEDED
            assert repo.get_job("r4").status == JobStatus.SUCCEEDED
            events = repo.list_events("r4")
            assert any(e["event"] == "soft404_suspected" for e in events)
        finally:
            os.unlink(db_path)

    def test_rule_for_other_origin_does_not_apply(self):
        # aturan hanya berlaku untuk origin yang terdaftar (per-situs, §3.1)
        from universal_web_acquisition.access.target_rules import TargetRules

        repo, db_path = _make_repo()
        try:
            rules = TargetRules()
            rules.register_soft404_invalid("other.example.com")
            worker = self._worker(repo, target_rules=rules)
            with FixtureServer() as base:
                for job_id, path in (("r5", "/mirror/a"), ("r6", "/mirror/b")):
                    job = Job(job_id=job_id, url=base + path)
                    repo.save_job(job)
                    asyncio.run(worker._execute_job(job))
            assert repo.get_job("r5").status == JobStatus.SUCCEEDED
            assert repo.get_job("r6").status == JobStatus.SUCCEEDED
        finally:
            os.unlink(db_path)
