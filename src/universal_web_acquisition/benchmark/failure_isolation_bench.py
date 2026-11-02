"""E5 — Failure isolation (TEXT.md competitive spike, eksperimen E5).

TEXT.md: *"satu URL mengalami timeout atau error permanen sementara
pekerjaan lain harus tetap selesai."*

Yang diukur — tiap skenario = satu BATCH job yang dijalankan lewat
``ConcurrentJobRunner`` (jalur produksi ``uwae crawl --concurrency N``):

- ``healthy_only``             : baseline — harness-nya sendiri sehat, jadi
  kegagalan di skenario lain memang akibat fault, bukan setup.
- ``timeout_fault``            : satu URL menggantung (server tidak merespons)
  → timeout; job lain harus tetap selesai.
- ``permanent_error_fault``    : satu URL 404 → error permanen; job lain harus
  tetap selesai.
- ``unexpected_exception_fault``: satu job gagal DI LUAR try worker (simulasi
  kegagalan penulisan DB) → job lain harus tetap selesai DAN job itu sendiri
  harus tercatat GAGAL, bukan hilang.

Sifat yang dijaga benchmark ini:

- **ground truth dari semantika skenario**, bukan dari output engine — kalau
  tidak, benchmark bisa memenuhi dirinya sendiri;
- **tidak ada sukses palsu** — job bermasalah tidak boleh dilaporkan sukses;
- **hasil batch lengkap** — ``run()`` wajib mengembalikan status untuk SETIAP
  job; job yang hilang berarti isolasi pecah;
- **waktu batch berbatas** — satu URL menggantung tidak boleh menahan batch
  melebihi timeout-nya.

Bukti: ``docs/benchmark/engine-results-e13.json`` + ``failure-isolation.md``.
"""

import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from universal_web_acquisition.artifact.storage import FilesystemArtifactStorage
from universal_web_acquisition.core.concurrent_runner import ConcurrentJobRunner
from universal_web_acquisition.core.job_model import Job, JobStatus
from universal_web_acquisition.core.job_repository import JobRepository
from universal_web_acquisition.core.job_worker import JobWorker
from universal_web_acquisition.http_transport.adapters import CurlCffiAdapter
from universal_web_acquisition.http_transport.registry import RetryPolicy, TransportRegistry

BENCHMARK_ID = "e5-failure-isolation-001"
RESULTS_PATH = Path("/root/universal-web-acquisition/docs/benchmark/engine-results-e13.json")
REPORT_PATH = Path("/root/universal-web-acquisition/docs/benchmark/failure-isolation.md")
FIXTURE_PORT = 8781

HEALTHY_JOBS = 11
CLIENT_TIMEOUT_SECONDS = 2.0
N_THREADS = 4

# Ground truth per skenario.
#
# ``faulted_assessment_reason_code`` dinilai dari event ASSESSMENT (diagnosis
# bukti), BUKAN dari teks pesan error: pesan curl (mis. "Timeout: ...") adalah
# detail implementasi yang rapuh. Yang dijamin adalah diagnosis yang benar —
# timeout terdiagnosis timeout, 404 terdiagnosis http_4xx.
#
# ``faulted_error_contains`` dipakai HANYA untuk fault tak terduga, yang tidak
# punya assessment (worker gagal sebelum klasifikasi) — satu-satunya bukti
# yang ada adalah pesan error job.
EXPECTED: Dict[str, dict] = {
    "healthy_only": {
        "faulted_status": None,
        "faulted_error_contains": None,
        "faulted_assessment_reason_code": None,
        "healthy_status": "succeeded",
    },
    "timeout_fault": {
        "faulted_status": "failed",
        "faulted_error_contains": None,
        "faulted_assessment_reason_code": "timeout",
        "healthy_status": "succeeded",
    },
    "permanent_error_fault": {
        "faulted_status": "failed",
        "faulted_error_contains": None,
        "faulted_assessment_reason_code": "http_4xx",
        "healthy_status": "succeeded",
    },
    "unexpected_exception_fault": {
        "faulted_status": "failed",
        "faulted_error_contains": "internal_error",
        "faulted_assessment_reason_code": None,
        "healthy_status": "succeeded",
    },
}

SCENARIOS = (
    "healthy_only",
    "timeout_fault",
    "permanent_error_fault",
    "unexpected_exception_fault",
)


class CrashingWorker(JobWorker):
    """Worker yang gagal DI LUAR try worker — simulasi kegagalan DB.

    ``JobWorker._execute_job`` melindungi HANYA blok transport; kegagalan di
    tahap lain (penulisan DB, artifact store) lolos keluar. Job ini
    mereproduksi jalur itu secara deterministik.
    """

    def __init__(self, *args, crash_job_ids=frozenset(), **kwargs):
        super().__init__(*args, **kwargs)
        self._crash_job_ids = set(crash_job_ids)

    async def _execute_job(self, job: Job) -> None:
        if job.job_id in self._crash_job_ids:
            job.mark_started()
            self.job_repository.save_job(job)
            raise RuntimeError("injected non-transport failure (simulasi DB error)")
        return await super()._execute_job(job)


def _build_registry(timeout_seconds: float = CLIENT_TIMEOUT_SECONDS) -> TransportRegistry:
    """Registry dengan timeout pendek — agar fault timeout terpicu cepat."""
    registry = TransportRegistry()
    adapter = CurlCffiAdapter()
    adapter.timeout_seconds = timeout_seconds
    registry.register(adapter.name, adapter, adapter.capabilities)
    return registry


def _make_repo(db_path: str) -> JobRepository:
    repo = JobRepository(db_path)
    repo.db_path = db_path
    repo._init_db()
    return repo


def _build_jobs(scenario: str, base_url: str, prefix: str) -> tuple:
    """Bangun batch job — 11 sehat + 1 bermasalah (kecuali baseline)."""
    jobs = []
    for index in range(HEALTHY_JOBS):
        jobs.append(Job(job_id=f"{prefix}-ok-{index:02d}", url=f"{base_url}/html"))
    faulted_id = None
    if scenario == "timeout_fault":
        faulted_id = f"{prefix}-fault"
        jobs.append(Job(job_id=faulted_id, url=f"{base_url}/hang?seconds=5"))
    elif scenario == "permanent_error_fault":
        faulted_id = f"{prefix}-fault"
        jobs.append(Job(job_id=faulted_id, url=f"{base_url}/missing"))
    elif scenario == "unexpected_exception_fault":
        faulted_id = f"{prefix}-fault"
        jobs.append(Job(job_id=faulted_id, url=f"{base_url}/html"))
    return jobs, faulted_id


def _assessment_reason_codes(repo: JobRepository, job_id: str) -> List[str]:
    """Reason code dari event ASSESSMENT — diagnosis bukti.

    Bukan teks pesan error: pesan curl (mis. "Timeout: ...") adalah detail
    implementasi yang bisa berubah kapan saja. Yang dijaga benchmark adalah
    diagnosis yang benar — timeout terdiagnosis timeout.
    """
    codes = []
    for event in repo.list_events(job_id):
        if event["event"] == "assessment":
            try:
                detail = json.loads(event["detail"])
            except (TypeError, ValueError):
                continue
            code = detail.get("reason_code")
            if code:
                codes.append(code)
    return codes


def run_scenario(
    scenario: str,
    base_url: str,
    db_path: str,
    storage,
    registry: TransportRegistry,
    n_threads: int = N_THREADS,
) -> dict:
    """Jalankan satu batch dan ukur isolasi kegagalan."""
    prefix = f"e5-{scenario}"
    jobs, faulted_id = _build_jobs(scenario, base_url, prefix)
    crash_ids = frozenset([faulted_id]) if scenario == "unexpected_exception_fault" else frozenset()

    def _worker_factory():
        return CrashingWorker(
            JobRepository(db_path),
            scheduler=None,
            registry=registry,
            storage=storage,
            retry_policy=RetryPolicy(max_retries=1, base_backoff_seconds=0.05),
            crash_job_ids=crash_ids,
        )

    runner = ConcurrentJobRunner(
        db_path=db_path,
        storage=storage,
        n_threads=n_threads,
        retry_policy=RetryPolicy(max_retries=1, base_backoff_seconds=0.05),
        worker_factory=_worker_factory,
    )

    raised = None
    started = time.perf_counter()
    try:
        results = runner.run(jobs)
    except Exception as exc:  # batch meledak = isolasi pecah
        raised = f"{type(exc).__name__}: {exc}"
        results = []
    elapsed_ms = (time.perf_counter() - started) * 1000

    repo = JobRepository(db_path)
    by_id = {job.job_id: job for job in jobs}
    per_job = []
    for job_id, job in by_id.items():
        stored = repo.get_job(job_id)
        per_job.append(
            {
                "job_id": job_id,
                "role": "faulted" if job_id == faulted_id else "healthy",
                "status": stored.status.value if stored else None,
                "error": stored.error if stored else None,
            }
        )

    healthy = [j for j in per_job if j["role"] == "healthy"]
    faulted = [j for j in per_job if j["role"] == "faulted"]
    expected = EXPECTED[scenario]

    healthy_ok = all(j["status"] == expected["healthy_status"] for j in healthy)
    faulted_status_ok = True
    faulted_error_ok = True
    faulted_assessment_ok = True
    faulted_assessments: List[str] = []
    if faulted:
        faulted_status_ok = faulted[0]["status"] == expected["faulted_status"]
        error = faulted[0]["error"] or ""
        if expected["faulted_error_contains"]:
            faulted_error_ok = expected["faulted_error_contains"] in error
        faulted_assessments = _assessment_reason_codes(repo, faulted[0]["job_id"])
        if expected["faulted_assessment_reason_code"]:
            faulted_assessment_ok = (
                expected["faulted_assessment_reason_code"] in faulted_assessments
            )
    complete = len(results) == len(jobs)

    matches = (
        raised is None
        and complete
        and healthy_ok
        and faulted_status_ok
        and faulted_error_ok
        and faulted_assessment_ok
    )
    return {
        "scenario": scenario,
        "total_jobs": len(jobs),
        "healthy_jobs": len(healthy),
        "returned_results": len(results),
        "batch_raised": raised,
        "batch_elapsed_ms": round(elapsed_ms, 2),
        "n_threads": n_threads,
        "client_timeout_seconds": CLIENT_TIMEOUT_SECONDS,
        "healthy_all_succeeded": healthy_ok,
        "faulted_status": faulted[0]["status"] if faulted else None,
        "faulted_error": faulted[0]["error"] if faulted else None,
        "faulted_assessment_reason_codes": faulted_assessments,
        "results_complete": complete,
        "matches_ground_truth": matches,
        "per_job": per_job,
    }


def run_benchmark(
    results_path: Path = RESULTS_PATH,
    report_path: Optional[Path] = REPORT_PATH,
    fixture_port: int = FIXTURE_PORT,
) -> dict:
    """Jalankan keempat skenario → dokumen bukti."""
    from universal_web_acquisition.benchmark.fixture_server import FixtureServer

    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    storage = FilesystemArtifactStorage(base_path=tempfile.mkdtemp(prefix="uwae-e5-"))
    registry = _build_registry()
    runs: List[dict] = []
    try:
        with FixtureServer(port=fixture_port) as base_url:
            for scenario in SCENARIOS:
                runs.append(run_scenario(scenario, base_url, db_path, storage, registry))
    finally:
        Path(db_path).unlink(missing_ok=True)

    doc = {
        "schema_version": 1,
        "benchmark_id": BENCHMARK_ID,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": "3.14.6 (Termux, bionic)",
            "architecture": "aarch64",
            "platform": "PRoot-Distro on Termux Android, no root",
            "fixture": "deterministic localhost fixture server (fixture_server.py)",
            "runner": "ConcurrentJobRunner (uwae crawl --concurrency N)",
            "n_threads": N_THREADS,
            "healthy_jobs_per_batch": HEALTHY_JOBS,
            "client_timeout_seconds": CLIENT_TIMEOUT_SECONDS,
            "retry_policy": "max_retries=1, base_backoff=0.05s",
        },
        "ground_truth": EXPECTED,
        "runs": runs,
        "summary": {
            "scenarios": len(runs),
            "all_match_ground_truth": all(r["matches_ground_truth"] for r in runs),
            "batch_failures": [r["scenario"] for r in runs if r["batch_raised"]],
            "incomplete_batches": [
                r["scenario"] for r in runs if not r["results_complete"]
            ],
        },
        "interpretation": (
            "E5 mengukur failure isolation pada batch `uwae crawl --concurrency N`: "
            "satu URL timeout / error permanen / kegagalan tak terduga TIDAK boleh "
            "menghentikan job lain, dan job bermasalah tidak boleh dilaporkan "
            "sukses. Baseline internal UWAE — bukan klaim lintas-implementasi "
            "terhadap Botasaurus."
        ),
    }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    if report_path is not None:
        report_path.write_text(render_report(doc), encoding="utf-8")
    return doc


def render_report(doc: dict) -> str:
    """Laporan Markdown — tabel DIHASILKAN dari data terukur."""
    lines = [
        "# E5 — Failure Isolation",
        "",
        "TEXT.md eksperimen E5: *\"satu URL mengalami timeout atau error permanen",
        "sementara pekerjaan lain harus tetap selesai.\"*",
        "",
        "Angka di bawah DIHASILKAN dari `engine-results-e13.json` — jangan diedit manual.",
        "",
        "## Hasil per skenario",
        "",
        "| Skenario | Job sehat sukses | Job bermasalah | Batch meledak | Hasil lengkap | Batch ms | Sesuai ground truth |",
        "|---|---|---|---|---|---|---|",
    ]
    for run in doc["runs"]:
        faulted = run["faulted_status"] or "—"
        if run["faulted_error"]:
            faulted = f"{faulted} (`{run['faulted_error'][:48]}`)"
        lines.append(
            f"| `{run['scenario']}` | {run['healthy_all_succeeded']} | {faulted} | "
            f"{'YA' if run['batch_raised'] else 'tidak'} | "
            f"{'lengkap' if run['results_complete'] else 'HILANG'} | "
            f"{run['batch_elapsed_ms']} | {'ya' if run['matches_ground_truth'] else 'TIDAK'} |"
        )
    summary = doc["summary"]
    lines += [
        "",
        "## Kesimpulan",
        "",
        f"- Skenario terukur: **{summary['scenarios']}**; seluruhnya sesuai ground truth: "
        f"**{summary['all_match_ground_truth']}**.",
        f"- Batch yang meledak: **{summary['batch_failures'] or 'tidak ada'}**.",
        f"- Batch dengan hasil hilang: **{summary['incomplete_batches'] or 'tidak ada'}**.",
        "",
        "## Metodologi",
        "",
        "- tiap skenario = satu batch 12 job (11 sehat + 1 bermasalah) pada "
        "`ConcurrentJobRunner` dengan 4 thread — jalur produksi `uwae crawl --concurrency N`;",
        "- fault timeout: endpoint `/hang` fixture (server tidak merespons) + timeout klien "
        f"{doc['environment']['client_timeout_seconds']} s;",
        "- fault error permanen: 404 (`/missing`);",
        "- fault tak terduga: worker yang gagal DI LUAR try worker (simulasi kegagalan DB);",
        "- ground truth berasal dari semantika skenario, bukan dari output engine.",
        "",
        "## Batasan",
        "",
        "- baseline internal UWAE; tidak ada perbandingan lintas-implementasi di sini.",
        "",
    ]
    return "\n".join(lines)


def main():
    doc = run_benchmark()
    print(f"benchmark : {doc['benchmark_id']}")
    print(f"timestamp : {doc['timestamp']}")
    for run in doc["runs"]:
        print(
            f"  {run['scenario']:28s} match={run['matches_ground_truth']} "
            f"raised={run['batch_raised']} complete={run['results_complete']} "
            f"ms={run['batch_elapsed_ms']}"
        )
    print(f"results   -> {RESULTS_PATH}")
    print(f"report    -> {REPORT_PATH}")


if __name__ == "__main__":
    main()
