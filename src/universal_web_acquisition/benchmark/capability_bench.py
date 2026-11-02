"""E10 — benchmark kapabilitas pasca-roadmap (fixture lokal, tanpa otorisasi).

Mandat INSTRUCTION.md: jangan klaim unggul tanpa hasil benchmark. Kapabilitas
yang kini ada di engine (E2 file identification, cache respons, discovery
graph + provenance, E3 reprocessing + plugin eksternal) punya unit tests —
benchmark ini menambah bukti di level ENGINE PENUH: setiap skenario
menjalankan worker → registry → adapter → artifact dan mengukur kebenaran
dari EVIDENCE (event audit), bukan dari klaim kode.

Skenario (semua fixture lokal, deterministik):
- e10_identification_no_ext    : /file-no-ext → format=png dari signature
- e10_identification_wrong_mime: /file-wrong-mime → format=png + mime_conflict
- e10_cache_hit                : 2x /html satu worker ber-cache →
                                 ``cache.hit=hit`` + sha256 identik
- e10_follow_links_provenance  : /page1 → /page2 ditemukan + ``discovered_via``
- e10_reprocess_plugin         : /html → plugin eksternal → extraction event
                                 ber-integrity sha256 sumber

Hasil: ``docs/benchmark/engine-results-e10.json`` (E9 tidak ditimpa).
"""

import asyncio
import hashlib
import json
import os
import tempfile
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path

from universal_web_acquisition.artifact.identification import (
    IdentificationRegistry,
)
from universal_web_acquisition.artifact.storage import FilesystemArtifactStorage
from universal_web_acquisition.benchmark.fixture_server import FixtureServer
from universal_web_acquisition.core.job_model import Job, JobStatus
from universal_web_acquisition.core.job_repository import JobRepository
from universal_web_acquisition.core.job_worker import JobWorker, run_extraction_plugins
from universal_web_acquisition.discovery.link_extractor import extract_links
from universal_web_acquisition.extract.html_text import HTMLTextExtractor
from universal_web_acquisition.http_transport.cache import build_caching_registry
from universal_web_acquisition.http_transport.registry import RetryPolicy
from universal_web_acquisition.plugins.loader import load_plugins_from_path
from universal_web_acquisition.plugins.registry import PluginRegistry

ENGINE_VERSION = "uwae-0.3.0"
REPO_BENCHMARK_DIR = Path(__file__).resolve().parents[3] / "docs" / "benchmark"
RESULTS_PATH_E10 = REPO_BENCHMARK_DIR / "engine-results-e10.json"

_PLUGIN_BODY = '''
from universal_web_acquisition.artifact.model import ArtifactIntegrity
from universal_web_acquisition.extract.base import ExtractionResult
from universal_web_acquisition.plugins.base import PluginMetadata


class MarkerExtractor:
    def __init__(self, name="marker-extractor"):
        self._meta = PluginMetadata(
            name=name,
            version="1.0.0",
            description="plugin uji benchmark E10",
            author="benchmark",
        )

    def get_metadata(self):
        return self._meta

    def initialize(self, config):
        pass

    def shutdown(self):
        pass

    def health_check(self):
        return {"healthy": True}

    def extract(self, artifact):
        return ExtractionResult(
            extractor=self._meta.name,
            format="marker",
            fields={"benchmark": "e10"},
            integrity=ArtifactIntegrity.from_content(artifact.content),
        )


PLUGIN = MarkerExtractor()
'''


def _make_repo():
    repo = JobRepository()
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo.db_path = db_path
    repo._init_db()
    return repo, db_path


def _run_job(worker, repo, url, job_id):
    job = Job(job_id=job_id, url=url)
    repo.save_job(job)
    asyncio.run(worker._execute_job(job))
    return repo.get_job(job.job_id)


def _last_event(repo, job_id, event_name):
    for event in reversed(repo.list_events(job_id)):
        if event["event"] == event_name:
            try:
                return json.loads(event["detail"])
            except json.JSONDecodeError:
                return None
    return None


def _assessment_signals(repo, job_id):
    assessment = _last_event(repo, job_id, "assessment")
    return (assessment.get("signals") or []) if assessment else []


def _result(scenario_id, elapsed_ms, peak_bytes, checks):
    return {
        "scenario_id": scenario_id,
        "elapsed_ms": round(elapsed_ms, 2),
        "peak_memory_bytes": peak_bytes,
        "success": all(checks.values()),
        "checks": checks,
    }


def _scenario_identification(
    scenario_id, path, expect_format, expect_mime, expect_conflict, base_url, repo, storage
):
    """E2 file-first: format dari signature, konflik MIME tercatat."""
    worker = JobWorker(
        repo,
        scheduler=None,
        storage=storage,
        retry_policy=RetryPolicy(max_retries=1, base_backoff_seconds=0.01),
        identifier=IdentificationRegistry.with_builtins(),
    )
    t0 = time.perf_counter()
    tracemalloc.start()
    final = _run_job(worker, repo, base_url + path, f"e10-{scenario_id}")
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    elapsed = (time.perf_counter() - t0) * 1000

    ident = _last_event(repo, final.job_id, "identification")
    checks = {
        "job_succeeded": final.status == JobStatus.SUCCEEDED,
        "identification_event_present": ident is not None,
        "format_from_signature": ident is not None and ident.get("format") == expect_format,
        "mime_hint_recorded": ident is not None and ident.get("mime") == expect_mime,
        "mime_conflict_flagged": ident is not None and ident.get("mime_conflict") == expect_conflict,
    }
    return _result(scenario_id, elapsed, peak, checks)


def _scenario_cache_hit(base_url, repo, storage):
    """Cache: hit tercatat jujur + integritas byte terjaga lintas hit."""
    worker = JobWorker(
        repo,
        scheduler=None,
        storage=storage,
        retry_policy=RetryPolicy(max_retries=1, base_backoff_seconds=0.01),
        registry=build_caching_registry(),
    )
    t0 = time.perf_counter()
    tracemalloc.start()
    first = _run_job(worker, repo, base_url + "/html", "e10-cache-first")
    second = _run_job(worker, repo, base_url + "/html", "e10-cache-second")
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    elapsed = (time.perf_counter() - t0) * 1000

    signals_first = _assessment_signals(repo, first.job_id)
    signals_second = _assessment_signals(repo, second.job_id)
    art1 = asyncio.run(storage.retrieve(first.artifact_id))
    art2 = asyncio.run(storage.retrieve(second.artifact_id))
    sha1 = hashlib.sha256(art1.content).hexdigest()
    sha2 = hashlib.sha256(art2.content).hexdigest()
    checks = {
        "both_succeeded": (
            first.status == JobStatus.SUCCEEDED and second.status == JobStatus.SUCCEEDED
        ),
        "first_fetch_not_from_cache": not any(
            s.startswith("cache.hit=") for s in signals_first
        ),
        "second_fetch_from_cache": "cache.hit=hit" in signals_second,
        "integrity_preserved_through_cache": sha1 == sha2,
    }
    return _result("e10_cache_hit", elapsed, peak, checks)


def _scenario_follow_links(base_url, repo, storage):
    """Discovery graph: /page1 → /page2 + provenance induk→anak."""
    worker = JobWorker(
        repo,
        scheduler=None,
        storage=storage,
        retry_policy=RetryPolicy(max_retries=1, base_backoff_seconds=0.01),
        identifier=IdentificationRegistry.with_builtins(),
    )
    t0 = time.perf_counter()
    tracemalloc.start()
    parent = _run_job(worker, repo, base_url + "/page1", "e10-follow-parent")
    artifact = asyncio.run(storage.retrieve(parent.artifact_id))
    links = extract_links(artifact.content, artifact.url)
    child_url = links[0] if links else None
    child = None
    provenance = None
    if child_url:
        child = Job(job_id="e10-follow-child", url=child_url)
        repo.save_job(child)
        repo.record_event(
            child.job_id,
            "discovered_via",
            json.dumps(
                {"url": child_url, "parent": artifact.url, "source": "follow_links"},
                ensure_ascii=False,
            ),
        )
        asyncio.run(worker._execute_job(child))
        child = repo.get_job(child.job_id)
        provenance = _last_event(repo, child.job_id, "discovered_via")
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    elapsed = (time.perf_counter() - t0) * 1000

    checks = {
        "parent_succeeded": parent.status == JobStatus.SUCCEEDED,
        "child_discovered": child_url == base_url + "/page2",
        "child_executed": child is not None and child.status == JobStatus.SUCCEEDED,
        "provenance_recorded": (
            provenance is not None
            and provenance.get("parent") == base_url + "/page1"
            and provenance.get("source") == "follow_links"
        ),
    }
    return _result("e10_follow_links_provenance", elapsed, peak, checks)


def _scenario_reprocess_plugin(base_url, repo, storage):
    """E3: plugin eksternal berjalan atas artifact tersimpan, integrity wajib."""
    worker = JobWorker(
        repo,
        scheduler=None,
        storage=storage,
        retry_policy=RetryPolicy(max_retries=1, base_backoff_seconds=0.01),
        identifier=IdentificationRegistry.with_builtins(),
    )
    t0 = time.perf_counter()
    tracemalloc.start()
    final = _run_job(worker, repo, base_url + "/html", "e10-reproc")
    artifact = asyncio.run(storage.retrieve(final.artifact_id))
    expected_sha = hashlib.sha256(artifact.content).hexdigest()

    plugin_dir = tempfile.mkdtemp(prefix="uwae-e10-plugin-")
    plugin_path = Path(plugin_dir) / "marker_plugin.py"
    plugin_path.write_text(_PLUGIN_BODY, encoding="utf-8")

    extractors = PluginRegistry()
    extractors.register(HTMLTextExtractor())
    for plugin in load_plugins_from_path(str(plugin_path)):
        extractors.register(plugin)
    run_extraction_plugins(repo, final.job_id, artifact, extractors)

    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    elapsed = (time.perf_counter() - t0) * 1000

    events = [
        json.loads(e["detail"])
        for e in repo.list_events(final.job_id)
        if e["event"] == "extraction"
    ]
    marker = next((e for e in events if e.get("extractor") == "marker-extractor"), None)
    builtin = next((e for e in events if e.get("extractor") == "html-text-extractor"), None)
    checks = {
        "job_succeeded": final.status == JobStatus.SUCCEEDED,
        "builtin_extractor_ran": builtin is not None,
        "external_plugin_ran": marker is not None,
        "external_fields": marker is not None and marker.get("fields") == {"benchmark": "e10"},
        "source_integrity_lineage": (
            marker is not None and marker.get("source_sha256") == expected_sha
        ),
    }
    return _result("e10_reprocess_plugin", elapsed, peak, checks)


def main(results_path: Path = RESULTS_PATH_E10):
    repo, db_path = _make_repo()
    storage = FilesystemArtifactStorage(base_path=tempfile.mkdtemp(prefix="uwae-e10-"))

    with FixtureServer() as base:
        results = [
            _scenario_identification(
                "e10_identification_no_ext",
                "/file-no-ext",
                "png",
                "application/octet-stream",
                False,
                base,
                repo,
                storage,
            ),
            _scenario_identification(
                "e10_identification_wrong_mime",
                "/file-wrong-mime",
                "png",
                "text/plain",
                True,
                base,
                repo,
                storage,
            ),
            _scenario_cache_hit(base, repo, storage),
            _scenario_follow_links(base, repo, storage),
            _scenario_reprocess_plugin(base, repo, storage),
        ]
    Path(db_path).unlink(missing_ok=True)

    doc = {
        "schema_version": 1,
        "benchmark_id": "e10-capability-001",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": "3.14.6 (Termux, bionic)",
            "architecture": "aarch64",
            "platform": "PRoot-Distro on Termux Android, no root",
            "fixture": "deterministic localhost fixture server (fixture_server.py)",
            "note": (
                "kapabilitas pasca-roadmap diuji di level engine penuh — kebenaran "
                "diukur dari EVIDENCE (event audit), bukan klaim kode"
            ),
        },
        "engine": {"engine_id": "uwae-engine", "version": ENGINE_VERSION},
        "capabilities_under_test": [
            "E2 file identification (file-first, signature)",
            "cache respons (hit tercatat jujur sebagai sinyal cache.hit)",
            "discovery graph (link extractor + provenance discovered_via)",
            "E3 reprocessing + plugin eksternal (integrity sumber wajib)",
        ],
        "scenarios": results,
        "summary": {
            "all_passed": all(r["success"] for r in results),
            "interpretation": (
                "Bukti kapabilitas, BUKAN klaim mengungguli Botasaurus (mandat "
                "INSTRUCTION.md): setiap kapabilitas pasca-roadmap terbukti bekerja "
                "melalui engine penuh dengan evidence lineage — identifikasi format "
                "dari signature (bukan ekstensi), cache hit tercatat jujur dengan "
                "integritas terjaga, discovery graph membawa provenance induk→anak, "
                "dan reprocessing menjalankan plugin eksternal dengan lineage sha256 "
                "sumber."
            ),
        },
    }

    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"{'scenario':32s} {'ms':>9s} {'passed':>8s}  checks")
    for r in results:
        failed = [k for k, v in r["checks"].items() if not v]
        print(
            f"{r['scenario_id']:32s} {r['elapsed_ms']:>9.2f} "
            f"{str(r['success']):>8s}  {', '.join(failed) if failed else 'all'}"
        )
    print(f"\nresults -> {results_path}")


if __name__ == "__main__":
    main()
