"""HTML link extractor tests (discovery graph — dedup, origin scope, fragment).

Yang diverifikasi:
- URL relatif di-resolve terhadap base; fragmen dibuang; self-link dilewati;
- skema non-HTTP(S) (mailto/javascript/tel) bukan kandidat akuisisi;
- dedup menjaga urutan kemunculan pertama (deterministik);
- ``same_origin_only`` mengikat discovery pada origin sumber;
- harvest dari artifact nyata melalui engine penuh (fixture /page1) menemukan
  /page2 dan menyaring self/eksternal/mailto;
- provenance edge induk→anak (event ``discovered_via``) terekam dan terbaca
  via ``_collect_evidence`` — kontrak DiscoveryResult (sumber + URL induk);
- ``crawl --follow-links`` berjalan berbatas dan tidak pernah bocor lintas
  origin; tanpa flag, perilaku crawl tidak berubah (regresi BFS refactor).
"""

import asyncio
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from universal_web_acquisition.artifact.identification import IdentificationRegistry
from universal_web_acquisition.artifact.storage import FilesystemArtifactStorage
from universal_web_acquisition.benchmark.fixture_server import FixtureServer
from universal_web_acquisition.cli.main import _collect_evidence, cli
from universal_web_acquisition.core.job_model import Job, JobStatus
from universal_web_acquisition.core.job_repository import JobRepository
from universal_web_acquisition.core.job_worker import JobWorker
from universal_web_acquisition.discovery.link_extractor import extract_links
from universal_web_acquisition.http_transport.registry import RetryPolicy

BASE = "http://127.0.0.1:8000"


def _make_repo():
    repo = JobRepository()
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo.db_path = path
    repo._init_db()
    return repo, path


class TestExtractLinks:
    def test_relative_resolved_against_base(self):
        html = b'<a href="/a">1</a><a href="b/c">2</a>'
        assert extract_links(html, BASE + "/idx") == [
            BASE + "/a",
            BASE + "/b/c",
        ]

    def test_fragment_stripped_and_self_skipped(self):
        # #sec dibuang; #top → halaman itu sendiri → tidak ada nilai baru
        html = b'<a href="/a#sec">1</a><a href="#top">2</a>'
        assert extract_links(html, BASE + "/idx") == [BASE + "/a"]

    def test_non_http_schemes_skipped(self):
        html = (
            b'<a href="mailto:x@y.z">m</a>'
            b'<a href="javascript:void(0)">j</a>'
            b'<a href="tel:+62">t</a>'
            b'<a href="/ok">ok</a>'
        )
        assert extract_links(html, BASE + "/") == [BASE + "/ok"]

    def test_dedup_preserves_order(self):
        html = b'<a href="/b">1</a><a href="/a">2</a><a href="/b">3</a>'
        assert extract_links(html, BASE + "/") == [BASE + "/b", BASE + "/a"]

    def test_same_origin_filter(self):
        html = (
            b'<a href="/in">in</a>'
            b'<a href="https://other.example.com/out">out</a>'
        )
        assert extract_links(html, BASE + "/") == [BASE + "/in"]
        # same_origin_only=False → lintas origin dipertahankan (keputusan caller)
        assert extract_links(html, BASE + "/", same_origin_only=False) == [
            BASE + "/in",
            "https://other.example.com/out",
        ]

    def test_no_links(self):
        assert extract_links(b"<p>no links here</p>", BASE + "/") == []


class TestWorkerHarvest:
    """Panen tautan dari artifact nyata melalui engine penuh (E-graph)."""

    def test_harvest_from_real_artifact(self):
        repo, db_path = _make_repo()
        storage = FilesystemArtifactStorage(
            base_path=tempfile.mkdtemp(prefix="uwae-harvest-")
        )
        try:
            worker = JobWorker(
                repo,
                scheduler=None,
                storage=storage,
                retry_policy=RetryPolicy(max_retries=1, base_backoff_seconds=0.01),
                identifier=IdentificationRegistry.with_builtins(),
            )
            with FixtureServer() as base:
                job = Job(job_id="h1", url=base + "/page1")
                repo.save_job(job)
                asyncio.run(worker._execute_job(job))
                final = repo.get_job("h1")
                assert final.status == JobStatus.SUCCEEDED
                artifact = asyncio.run(storage.retrieve(final.artifact_id))
                links = extract_links(artifact.content, artifact.url)
            # self (dengan fragmen) + mailto + eksternal tersaring; /page2 masuk
            assert links == [base + "/page2"]
        finally:
            os.unlink(db_path)

    def test_harvest_records_provenance_edge(self):
        # simulasi langkah panen crawl --follow-links: child job di-enqueue
        # SEKARANG (G6) + event discovered_via (edge induk→anak) terbaca via
        # _collect_evidence — kontrak DiscoveryResult (sumber + URL induk)
        repo, db_path = _make_repo()
        storage = FilesystemArtifactStorage(
            base_path=tempfile.mkdtemp(prefix="uwae-harvest-")
        )
        try:
            worker = JobWorker(
                repo,
                scheduler=None,
                storage=storage,
                retry_policy=RetryPolicy(max_retries=1, base_backoff_seconds=0.01),
                identifier=IdentificationRegistry.with_builtins(),
            )
            with FixtureServer() as base:
                job = Job(job_id="h2", url=base + "/page1")
                repo.save_job(job)
                asyncio.run(worker._execute_job(job))
                final = repo.get_job("h2")
                artifact = asyncio.run(storage.retrieve(final.artifact_id))
                links = extract_links(artifact.content, artifact.url)
                child = Job(
                    job_id=f"discovery-{hashlib.sha1(links[0].encode()).hexdigest()[:12]}",
                    url=links[0],
                )
                repo.save_job(child)
                repo.record_event(
                    child.job_id,
                    "discovered_via",
                    json.dumps(
                        {
                            "url": links[0],
                            "parent": artifact.url,
                            "source": "follow_links",
                        },
                        ensure_ascii=False,
                    ),
                )
                evidence = _collect_evidence(
                    repo, storage, repo.get_job(child.job_id)
                )
            kinds = [t["kind"] for t in evidence["lineage"]]
            assert "discovered_via" in kinds
            via = next(
                t for t in evidence["lineage"] if t["kind"] == "discovered_via"
            )
            assert via["parent"] == base + "/page1"
            assert via["source"] == "follow_links"
        finally:
            os.unlink(db_path)


class TestCrawlFollowLinks:
    def _run_crawl(self, runner, args):
        db = tempfile.mktemp(suffix=".db")
        artifacts = tempfile.mkdtemp(prefix="uwae-crawl-")
        try:
            return runner.invoke(
                cli, ["crawl", *args, "--db", db, "--artifacts-dir", artifacts]
            )
        finally:
            if os.path.exists(db):
                os.unlink(db)

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_crawl_follow_links_bounded_and_origin_safe(self, runner):
        # /html (dari sitemap) dipanen: self + eksternal tersaring — tidak ada
        # job baru, tidak ada kebocoran lintas origin, volume tetap terikat.
        with FixtureServer() as base:
            result = self._run_crawl(runner, [base, "--follow-links", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["discovered"] == 1
        urls = [r["url"] for r in payload["results"]]
        assert all(u.startswith(base) for u in urls)
        assert not any("example.org" in u for u in urls)
        assert payload["results"][0]["job_status"] == "succeeded"

    def test_crawl_without_follow_unchanged(self, runner):
        # regresi refactor BFS: tanpa flag, perilaku crawl identik
        with FixtureServer() as base:
            result = self._run_crawl(runner, [base, "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["discovered"] == 1
        assert payload["summary"]["succeeded"] == 1


class TestCrawlConcurrency:
    """``crawl --concurrency N`` (E6): N=1 jalur lama; N>1 paralel per-level
    via ConcurrentJobRunner dengan wiring lengkap (cache/extractor ikut)."""

    def _run_crawl(self, runner, args):
        db = tempfile.mktemp(suffix=".db")
        artifacts = tempfile.mkdtemp(prefix="uwae-conccrawl-")
        try:
            return runner.invoke(
                cli, ["crawl", *args, "--db", db, "--artifacts-dir", artifacts]
            )
        finally:
            if os.path.exists(db):
                os.unlink(db)

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_crawl_concurrency_two_matches_sequential(self, runner):
        # hasil identik dengan sequential: 1 URL, sukses, evidence utuh
        with FixtureServer() as base:
            result = self._run_crawl(runner, [base, "--concurrency", "2", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["discovered"] == 1
        assert payload["summary"]["succeeded"] == 1
        assert payload["results"][0]["job_status"] == "succeeded"
        # evidence lineage tetap penuh (assessment + decision terekam)
        kinds = {t["kind"] for t in payload["results"][0]["lineage"]}
        assert "assessment" in kinds
        assert "decision" in kinds

    def test_crawl_concurrency_four_full_wiring(self, runner):
        # wiring lengkap di worker_factory: cache + extractor ikut paralel
        with FixtureServer() as base:
            result = self._run_crawl(
                runner,
                [base, "--concurrency", "4", "--cache", "--extract", "--json"],
            )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["summary"]["succeeded"] == 1
        lineage = payload["results"][0]["lineage"]
        # extractor berjalan di jalur paralel (event extraction tercatat)
        assert any(t["kind"] == "extraction" for t in lineage)
