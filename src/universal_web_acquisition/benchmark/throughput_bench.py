"""E11 — throughput benchmark: baseline SEQUENTIAL + skenario concurrent (E6).

Disiplin pengukuran (ukur → optimasi → ukur lagi): baseline sequential
adalah dasar ilmiah; skenario concurrent (``ConcurrentJobRunner``) dibanding-
kan terhadapnya — bukan terhadap klaim.

Skenario: N job melalui engine penuh (worker → registry → adapter →
artifact) terhadap fixture lokal deterministik; latency per job dicatat →
p50/p95; seluruh job WAJIB sukses (ada satu kegagalan, skenario gagal).
Wiring worker minimal dan terdokumentasi di hasil (tanpa cache, tanpa
identifier) agar perbandingan apple-to-apple.

Hasil: ``docs/benchmark/engine-results-e11.json`` (E9/E10 tidak ditimpa).
"""

import asyncio
import json
import math
import os
import tempfile
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path

from universal_web_acquisition.artifact.storage import FilesystemArtifactStorage
from universal_web_acquisition.benchmark.fixture_server import FixtureServer
from universal_web_acquisition.core.concurrent_runner import ConcurrentJobRunner
from universal_web_acquisition.core.job_model import Job, JobStatus
from universal_web_acquisition.core.job_repository import JobRepository
from universal_web_acquisition.core.job_worker import JobWorker
from universal_web_acquisition.http_transport.registry import RetryPolicy

ENGINE_VERSION = "uwae-0.3.0"
REPO_BENCHMARK_DIR = Path(__file__).resolve().parents[3] / "docs" / "benchmark"
RESULTS_PATH_E11 = REPO_BENCHMARK_DIR / "engine-results-e11.json"


def _make_repo():
    repo = JobRepository()
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo.db_path = db_path
    repo._init_db()
    return repo, db_path


def _percentile(sorted_values: list, fraction: float) -> float:
    """Persentil sederhana atas nilai terurut — deterministik, tanpa klaim."""
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, math.ceil(fraction * len(sorted_values)) - 1)
    return sorted_values[max(index, 0)]


def _scenario_sequential(n_jobs: int, path: str, label: str, base_url, repo, storage):
    """N job sequential melalui engine penuh — latency per job → p50/p95."""
    worker = JobWorker(
        repo,
        scheduler=None,
        storage=storage,
        retry_policy=RetryPolicy(max_retries=1, base_backoff_seconds=0.01),
    )
    latencies = []
    failures = 0
    t0 = time.perf_counter()
    tracemalloc.start()
    for index in range(1, n_jobs + 1):
        job = Job(job_id=f"e11-{label}-{index}", url=base_url + path)
        repo.save_job(job)
        job_t0 = time.perf_counter()
        asyncio.run(worker._execute_job(job))
        latencies.append((time.perf_counter() - job_t0) * 1000)
        if repo.get_job(job.job_id).status != JobStatus.SUCCEEDED:
            failures += 1
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    wall = time.perf_counter() - t0

    ordered = sorted(latencies)
    return {
        "scenario_id": f"e11_sequential_{label}",
        "wiring": "worker sequential minimal (tanpa cache, tanpa identifier)",
        "jobs": n_jobs,
        "failures": failures,
        "wall_time_s": round(wall, 3),
        "jobs_per_second": round(n_jobs / wall, 3) if wall > 0 else 0.0,
        "latency_ms_p50": round(_percentile(ordered, 0.50), 2),
        "latency_ms_p95": round(_percentile(ordered, 0.95), 2),
        "peak_memory_bytes": peak,
        "success": failures == 0,
    }


def _scenario_concurrent(
    n_jobs: int,
    n_threads: int,
    path: str,
    label: str,
    base_url,
    repo,
    db_path,
    storage,
):
    """N job paralel (n_threads berbatas) via ConcurrentJobRunner — vs baseline."""
    runner = ConcurrentJobRunner(db_path, storage, n_threads=n_threads)
    jobs = [
        Job(job_id=f"e11-{label}-c{index}", url=base_url + path)
        for index in range(1, n_jobs + 1)
    ]
    t0 = time.perf_counter()
    finals = runner.run(jobs, repo=repo)
    wall = time.perf_counter() - t0
    failures = sum(
        1 for job in finals if job is None or job.status != JobStatus.SUCCEEDED
    )
    ordered = sorted(runner.last_latencies_ms or [])
    return {
        "scenario_id": f"e11_concurrent_t{n_threads}_{label}",
        "wiring": f"ConcurrentJobRunner {n_threads} thread (worker+adapter per-thread)",
        "threads": n_threads,
        "jobs": n_jobs,
        "failures": failures,
        "wall_time_s": round(wall, 3),
        "jobs_per_second": round(n_jobs / wall, 3) if wall > 0 else 0.0,
        "latency_ms_p50": round(_percentile(ordered, 0.50), 2),
        "latency_ms_p95": round(_percentile(ordered, 0.95), 2),
        "success": failures == 0,
    }


def main(results_path: Path = RESULTS_PATH_E11):
    repo, db_path = _make_repo()
    storage = FilesystemArtifactStorage(base_path=tempfile.mkdtemp(prefix="uwae-e11-"))

    with FixtureServer() as base:
        results = [
            _scenario_sequential(10, "/html", "small", base, repo, storage),
            _scenario_sequential(20, "/html", "medium", base, repo, storage),
            _scenario_concurrent(
                10, 2, "/html", "small", base, repo, db_path, storage
            ),
            _scenario_concurrent(
                20, 4, "/html", "medium", base, repo, db_path, storage
            ),
        ]
    Path(db_path).unlink(missing_ok=True)

    doc = {
        "schema_version": 1,
        "benchmark_id": "e11-throughput-baseline-001",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": "3.14.6 (Termux, bionic)",
            "architecture": "aarch64",
            "platform": "PRoot-Distro on Termux Android, no root",
            "fixture": "deterministic localhost fixture server (fixture_server.py)",
            "note": (
                "baseline SEQUENTIAL + skenario concurrent (ConcurrentJobRunner) — "
                "seluruh job wajib sukses (ada satu kegagalan = skenario gagal)"
            ),
        },
        "engine": {"engine_id": "uwae-engine", "version": ENGINE_VERSION},
        "scenarios": results,
        "summary": {
            "all_passed": all(r["success"] for r in results),
            "interpretation": (
                "Baseline SEQUENTIAL vs concurrent (ConcurrentJobRunner, worker + "
                "adapter per-thread) engine penuh terhadap fixture lokal — "
                "perbandingan E6 berbasis angka, bukan klaim; seluruh job wajib "
                "sukses."
            ),
        },
    }

    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(
        f"{'scenario':28s} {'jobs':>5s} {'wall_s':>8s} {'jobs/s':>8s} "
        f"{'p50_ms':>8s} {'p95_ms':>8s}  passed"
    )
    for r in results:
        print(
            f"{r['scenario_id']:28s} {r['jobs']:>5d} {r['wall_time_s']:>8.3f} "
            f"{r['jobs_per_second']:>8.3f} {r['latency_ms_p50']:>8.2f} "
            f"{r['latency_ms_p95']:>8.2f}  {r['success']}"
        )
    print(f"\nresults -> {results_path}")


if __name__ == "__main__":
    main()
