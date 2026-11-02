"""E4 — Adaptive scheduling: HTTP-first vs browser-first vs adaptif.

TEXT.md eksperimen E4: *"bandingkan biaya dan keberhasilan HTTP-first dengan
strategi browser-first pada fixture yang sama."*

Tiga lengan memakai engine dan fixture yang IDENTIK — yang dibedakan hanya
strategi awal:

- ``http_only``    : hanya transport HTTP (browser tidak tersedia). Lengan
  "murah": mengukur berapa yang hilang bila strategi adaptif tidak ada.
- ``browser_first``: setiap URL dicoba lewat browser runtime lebih dulu.
  Lengan "mahal": mengukur jangkauan maksimum.
- ``adaptive``     : default engine — HTTP dulu, eskalasi ke browser HANYA
  bila bukti (klasifikasi) memintanya.

Yang diukur (ACP §5 — uji penyebab, bukan hanya hasil akhir):

- **cakupan**     : status akhir per skenario (sukses / gagal / needs-user);
- **biaya**       : elapsed, jumlah attempt, memori (peak Python + RSS
  chromium), dan apakah ``Retry-After`` server dihormati;
- **fidelity diagnosis** : state terakhir dari event assessment vs ground
  truth — termasuk kasus di mana lengan browser MELIHKAN sinyal yang
  terlihat jelas di jalur HTTP (bytes tak valid, header ``Retry-After``).

Ground truth berasal dari semantika protokol fixture (bukan dari classifier),
sehingga benchmark ini tidak bisa "memenuhi dirinya sendiri". Semua lengan
menjalankan siklus ACP penuh yang sama (JobWorker → registry → planner →
artifact store), sehingga yang dibandingkan adalah strategi, bukan implementasi
yang berbeda.

Bukti: ``docs/benchmark/engine-results-e12.json`` + ``strategy-comparison.md``.
"""

import asyncio
import json
import os
import statistics
import tempfile
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from universal_web_acquisition.artifact.storage import FilesystemArtifactStorage
from universal_web_acquisition.benchmark.fixture_server import SCENARIOS
from universal_web_acquisition.browser.adapter import BROWSER_NAME, CDPBrowserAdapter
from universal_web_acquisition.core.job_model import Job, JobStatus
from universal_web_acquisition.core.job_repository import JobRepository
from universal_web_acquisition.core.job_worker import JobWorker
from universal_web_acquisition.http_transport.registry import RetryPolicy

BENCHMARK_ID = "e4-adaptive-scheduling-001"
RESULTS_PATH = Path("/root/universal-web-acquisition/docs/benchmark/engine-results-e12.json")
REPORT_PATH = Path("/root/universal-web-acquisition/docs/benchmark/strategy-comparison.md")
BROWSER_PORT = 9361

STRATEGIES = ("http_only", "browser_first", "adaptive")

# Skenario yang diulang (cepat, tanpa jeda server): perbandingan biaya &
# cakupan dengan pengulangan (§6.3 INSTRUCTION.md — 30 pengulangan).
REPEATED_SCENARIOS = (
    "b01_small_get",
    "b07_js_render",
    "e02_not_found",
    "a07_challenge",
)

# Skenario sekali jalan: fidelity diagnosis (ada jeda Retry-After dari server
# atau probe tambahan) — cukup satu run per lengan, bukan statistik performa.
SINGLE_SCENARIOS = (
    "a11_invalid_html",
    "a06_rate_limited",
    "a04_login",
)

# Ground truth per (skenario, lengan). "status" = status akhir job,
# "state" = state AccessState terakhir dari event assessment,
# "browser_used" = apakah lengan ini menyentuh browser runtime.
# "attempts" sengaja TIDAK dikunci untuk kasus gagal: jumlah attempt adalah
# hasil anggaran retry, bukan kontrak — yang dikunci adalah status + state.
EXPECTED: Dict[str, Dict[str, dict]] = {
    "b01_small_get": {
        "http_only": {"status": "succeeded", "state": "access_granted", "browser_used": False},
        "browser_first": {"status": "succeeded", "state": "access_granted", "browser_used": True},
        "adaptive": {"status": "succeeded", "state": "access_granted", "browser_used": False},
    },
    "b07_js_render": {
        # HTTP melihat gerbang JS → butuh browser; tanpa browser → gagal
        # jujur (CAPABILITY_MISSING), bukan sukses palsu.
        "http_only": {"status": "failed", "state": "javascript_required", "browser_used": False},
        "browser_first": {"status": "succeeded", "state": "access_granted", "browser_used": True},
        # adaptif: HTTP → javascript_required → eskalasi browser → sukses.
        "adaptive": {"status": "succeeded", "state": "access_granted", "browser_used": True},
    },
    "e02_not_found": {
        # 404 tidak boleh jadi sukses di lengan mana pun.
        "http_only": {"status": "failed", "state": "content_invalid", "browser_used": False},
        "browser_first": {"status": "failed", "state": "content_invalid", "browser_used": True},
        "adaptive": {"status": "failed", "state": "content_invalid", "browser_used": False},
    },
    "a07_challenge": {
        # Challenge tidak terpecahkan browser pada fixture ini → needs-user
        # di semua lengan (ACP §2.2 — verifikasi manusia, bukan sukses palsu).
        "http_only": {"status": "needs_user", "state": "challenge_present", "browser_used": False},
        "browser_first": {"status": "needs_user", "state": "challenge_present", "browser_used": True},
        "adaptive": {"status": "needs_user", "state": "challenge_present", "browser_used": True},
    },
    "a11_invalid_html": {
        # HTTP melihat byte rusak apa adanya → content_invalid. Browser
        # merekonstruksi DOM yang valid → sinyal "bukan HTML" hilang.
        "http_only": {"status": "failed", "state": "content_invalid", "browser_used": False},
        "browser_first": {"status": "succeeded", "state": "access_granted", "browser_used": True},
        "adaptive": {"status": "failed", "state": "content_invalid", "browser_used": False},
    },
    "a06_rate_limited": {
        # 429 → rate_limited di semua lengan; yang berbeda adalah apakah
        # Retry-After server dihormati (lihat field retry_after_honored).
        "http_only": {"status": "failed", "state": "rate_limited", "browser_used": False},
        "browser_first": {"status": "failed", "state": "rate_limited", "browser_used": True},
        "adaptive": {"status": "failed", "state": "rate_limited", "browser_used": False},
    },
    "a04_login": {
        # Halaman login → auth_required; tanpa session manager tidak ada
        # jalur autentikasi resmi → gagal jujur (bukan sukses palsu).
        "http_only": {"status": "failed", "state": "auth_required", "browser_used": False},
        "browser_first": {"status": "failed", "state": "auth_required", "browser_used": True},
        "adaptive": {"status": "failed", "state": "auth_required", "browser_used": False},
    },
}

STRATEGY_DEFINITIONS = {
    "http_only": {
        "description": "hanya transport HTTP — browser runtime tidak tersedia",
        "initial_transport": None,
        "browser_available": False,
    },
    "browser_first": {
        "description": "browser runtime dicoba lebih dulu untuk setiap URL",
        "initial_transport": BROWSER_NAME,
        "browser_available": True,
    },
    "adaptive": {
        "description": "default engine — HTTP dulu, eskalasi ke browser bila bukti memintanya",
        "initial_transport": None,
        "browser_available": True,
    },
}


def _make_repo() -> tuple:
    """Repository sementara (DB terpisah per benchmark run)."""
    repo = JobRepository()
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo.db_path = path
    repo._init_db()
    return repo, path


def _last_assessment(repo: JobRepository, job_id: str) -> dict:
    """Event assessment terakhir — state diagnosis yang benar-benar dipakai."""
    for event in reversed(repo.list_events(job_id)):
        if event["event"] == "assessment":
            return json.loads(event["detail"])
    return {}


def _decisions(repo: JobRepository, job_id: str) -> List[dict]:
    return [
        json.loads(event["detail"])
        for event in repo.list_events(job_id)
        if event["event"] == "decision"
    ]


def _default_browser_factory(browser_port: int):
    """Chromium persisten (ADR-014) — default untuk lengan browser."""

    def _factory():
        return CDPBrowserAdapter(
            port=browser_port,
            keep_alive=True,
            render_timeout=15.0,
            start_timeout=20.0,
        )

    return _factory


def _build_worker(
    strategy: str,
    repo: JobRepository,
    storage,
    browser_factory=None,
    browser_port: int = BROWSER_PORT,
) -> tuple:
    """Worker untuk satu lengan — wiring IDENTIK, hanya strategi awal berbeda."""
    definition = STRATEGY_DEFINITIONS[strategy]
    browser_adapter = None
    if definition["browser_available"]:
        factory = browser_factory or _default_browser_factory(browser_port)
        browser_adapter = factory()
    worker = JobWorker(
        repo,
        scheduler=None,
        storage=storage,
        retry_policy=RetryPolicy(max_retries=2, base_backoff_seconds=0.05),
        browser_adapter=browser_adapter,
        initial_transport=definition["initial_transport"],
    )
    return worker, browser_adapter


def run_scenario(
    strategy: str,
    scenario_id: str,
    base_url: str,
    repo: JobRepository,
    storage,
    worker: JobWorker,
    browser_adapter,
    run_index: int,
    measurement: str = "repeated",
) -> dict:
    """Satu run: satu skenario, satu lengan, satu job."""
    job = Job(job_id=f"e4-{strategy}-{scenario_id}-{run_index:03d}", url=base_url + SCENARIOS[scenario_id])
    repo.save_job(job)

    t0 = time.perf_counter()
    tracemalloc.start()
    asyncio.run(worker._execute_job(job))
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    elapsed_ms = (time.perf_counter() - t0) * 1000

    final = repo.get_job(job.job_id)
    assessment = _last_assessment(repo, job.job_id)
    attempts = repo.list_attempts(job.job_id)
    transports = [a["transport"] for a in attempts]
    decisions = _decisions(repo, job.job_id)
    expected = EXPECTED[scenario_id][strategy]

    status_value = final.status.value
    state = assessment.get("state")
    browser_used = BROWSER_NAME in transports
    retry_after_honored = any(
        d.get("action") == "wait_retry_after" for d in decisions
    )
    matches = (
        status_value == expected["status"]
        and state == expected["state"]
        and browser_used == expected["browser_used"]
    )
    return {
        "strategy": strategy,
        "scenario_id": scenario_id,
        "run_index": run_index,
        "measurement": measurement,
        "url": job.url,
        "status": status_value,
        "state": state,
        "reason_code": assessment.get("reason_code"),
        "error": final.error,
        "attempts": len(attempts),
        "transports": transports,
        "browser_used": browser_used,
        "retry_after_honored": retry_after_honored,
        "elapsed_ms": round(elapsed_ms, 2),
        "peak_memory_bytes": peak,
        "chromium_rss_kb": getattr(browser_adapter, "last_rss_kb", None),
        "matches_ground_truth": matches,
    }


def _median(values: List[float]) -> Optional[float]:
    return round(statistics.median(values), 2) if values else None


def summarize(runs: List[dict]) -> dict:
    """Agregasi per (lengan, skenario): cakupan, biaya, fidelity."""
    summary: Dict[str, dict] = {}
    for strategy in STRATEGIES:
        for scenario_id in list(REPEATED_SCENARIOS) + list(SINGLE_SCENARIOS):
            subset = [
                r for r in runs
                if r["strategy"] == strategy and r["scenario_id"] == scenario_id
            ]
            if not subset:
                continue
            elapsed = [r["elapsed_ms"] for r in subset]
            peaks = [r["peak_memory_bytes"] for r in subset if r["peak_memory_bytes"]]
            rss = [r["chromium_rss_kb"] for r in subset if r.get("chromium_rss_kb")]
            expected = EXPECTED[scenario_id][strategy]
            summary.setdefault(strategy, {})[scenario_id] = {
                "runs": len(subset),
                "measurement": subset[0]["measurement"],
                "expected_status": expected["status"],
                "expected_state": expected["state"],
                "expected_browser_used": expected["browser_used"],
                "status_counts": {
                    status: sum(1 for r in subset if r["status"] == status)
                    for status in sorted({r["status"] for r in subset})
                },
                "state_counts": {
                    state: sum(1 for r in subset if r["state"] == state)
                    for state in sorted({r["state"] for r in subset if r["state"]})
                },
                "ground_truth_match_rate": round(
                    sum(1 for r in subset if r["matches_ground_truth"]) / len(subset), 4
                ),
                "elapsed_ms_median": _median(elapsed),
                "elapsed_ms_min": round(min(elapsed), 2),
                "elapsed_ms_max": round(max(elapsed), 2),
                "attempts_median": _median([r["attempts"] for r in subset]),
                "transports_observed": sorted({t for r in subset for t in r["transports"]}),
                "peak_memory_bytes_median": _median(peaks),
                "chromium_rss_kb_max": max(rss) if rss else None,
                "retry_after_honored": any(r["retry_after_honored"] for r in subset),
                "browser_used": any(r["browser_used"] for r in subset),
            }
    return summary


def measure_cold_start(base_url: str, browser_factory=None, browser_port: int = BROWSER_PORT) -> dict:
    """Biaya satu-shot browser: chromium baru untuk SATU akuisisi.

    Lengan berulang memakai chromium persisten (amortisasi cold start);
    biaya cold start diukur terpisah agar tidak hilang dari laporan.
    """
    repo, db_path = _make_repo()
    storage = FilesystemArtifactStorage(base_path=tempfile.mkdtemp(prefix="uwae-e4-cold-"))
    if browser_factory is None:
        adapter = CDPBrowserAdapter(port=browser_port, keep_alive=False)
    else:
        adapter = browser_factory()
    # Cold start HARUS memakai browser sebagai transport pertama — tanpa ini
    # pengukuran diam-diam jatuh ke HTTP dan melaporkan biaya cold start
    # yang palsu (browser_first ≠ HTTP-first).
    worker = JobWorker(
        repo,
        scheduler=None,
        storage=storage,
        browser_adapter=adapter,
        initial_transport=BROWSER_NAME,
    )
    try:
        run = run_scenario(
            "browser_first",
            "b01_small_get",
            base_url,
            repo,
            storage,
            worker,
            adapter,
            run_index=0,
            measurement="cold_start",
        )
    finally:
        adapter.close()
        Path(db_path).unlink(missing_ok=True)
    return {
        "measurement": "cold_start_single_acquisition",
        "elapsed_ms": run["elapsed_ms"],
        "chromium_rss_kb": run["chromium_rss_kb"],
        "status": run["status"],
        "transports": run["transports"],
        # Guard: cold start yang jatuh ke HTTP adalah pengukuran palsu.
        "browser_used": run["browser_used"],
        "note": (
            "chromium baru untuk satu akuisisi (keep_alive=False) — biaya "
            "eskalasi one-shot pada jalur produksi `uwae acquire --browser`"
        ),
    }


def run_benchmark(
    repeats: int = 30,
    results_path: Path = RESULTS_PATH,
    report_path: Optional[Path] = REPORT_PATH,
    browser_port: int = BROWSER_PORT,
    browser_factory=None,
) -> dict:
    """Jalankan ketiga lengan pada fixture yang sama → dokumen bukti."""
    repo, db_path = _make_repo()
    storage = FilesystemArtifactStorage(base_path=tempfile.mkdtemp(prefix="uwae-e4-"))
    runs: List[dict] = []
    try:
        with _fixture_server() as base_url:
            for strategy in STRATEGIES:
                worker, browser_adapter = _build_worker(
                    strategy,
                    repo,
                    storage,
                    browser_factory=browser_factory,
                    browser_port=browser_port,
                )
                try:
                    for scenario_id in REPEATED_SCENARIOS:
                        for index in range(repeats):
                            runs.append(
                                run_scenario(
                                    strategy,
                                    scenario_id,
                                    base_url,
                                    repo,
                                    storage,
                                    worker,
                                    browser_adapter,
                                    index,
                                    measurement="repeated",
                                )
                            )
                    for scenario_id in SINGLE_SCENARIOS:
                        runs.append(
                            run_scenario(
                                strategy,
                                scenario_id,
                                base_url,
                                repo,
                                storage,
                                worker,
                                browser_adapter,
                                0,
                                measurement="single",
                            )
                        )
                finally:
                    if browser_adapter is not None:
                        browser_adapter.close()
            cold_start = measure_cold_start(base_url, browser_port=browser_port + 1)
    finally:
        Path(db_path).unlink(missing_ok=True)

    summary = summarize(runs)
    doc = {
        "schema_version": 1,
        "benchmark_id": BENCHMARK_ID,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": "3.14.6 (Termux, bionic)",
            "architecture": "aarch64",
            "platform": "PRoot-Distro on Termux Android, no root",
            "fixture": "deterministic localhost fixture server (fixture_server.py)",
            "uwae_retry_policy": "max_retries=2, base_backoff=0.05s (fixture lokal)",
            "browser": "chromium headless via raw CDP (ADR-014), persistent dalam lengan berulang",
            "repeats": repeats,
        },
        "strategies": STRATEGY_DEFINITIONS,
        "ground_truth": EXPECTED,
        "runs": runs,
        "summary": summary,
        "cold_start": cold_start,
        "interpretation": (
            "E4 mengukur biaya dan cakupan TIGA STRATEGI pada engine + fixture yang "
            "sama. Lengan adaptif adalah default engine: HTTP dulu, eskalasi ke "
            "browser hanya bila bukti memintanya. Semua lengan memakai klasifikasi "
            "dan planner yang sama — yang dibandingkan adalah URUTAN STRATEGI. "
            "Ini baseline internal, BUKAN klaim mengungguli Botasaurus (mandat "
            "INSTRUCTION.md). Perbandingan lintas-implementasi dengan kondisi "
            "device identik ada di engine-results-e14.json (E14); baseline "
            "Botasaurus di environment ini proved berjalan normal — klaim lama "
            "bahwa engine HTTP-nya tidak dapat dieksekusi terbukti SALAH "
            "(bug pemanggilan pada skrip baseline proyek ini, lihat ADR-019)."
        ),
    }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    if report_path is not None:
        report_path.write_text(render_report(doc), encoding="utf-8")
    return doc


def _fixture_server():
    from universal_web_acquisition.benchmark.fixture_server import FixtureServer

    return FixtureServer()


def render_report(doc: dict) -> str:
    """Laporan Markdown — tabel DIHASILKAN dari data terukur (tanpa drift)."""
    summary = doc["summary"]
    lines = [
        "# E4 — Adaptive Scheduling: HTTP-first vs Browser-first vs Adaptif",
        "",
        "Benchmark biaya & cakupan strategi pada engine dan fixture yang sama.",
        "Angka di bawah DIHASILKAN dari `engine-results-e12.json` — jangan diedit manual.",
        "",
        "## Cara membaca",
        "",
        "- **http_only** — hanya transport HTTP; browser runtime tidak tersedia.",
        "- **browser_first** — browser runtime dicoba lebih dulu untuk setiap URL.",
        "- **adaptive** — default engine: HTTP dulu, eskalasi ke browser hanya bila bukti memintanya.",
        "- Status akhir job: `succeeded` / `failed` / `needs_user`. `needs_user` adalah hasil yang benar",
        "  untuk challenge yang tidak dapat diselesaikan otomatis (ACP §2.2) — bukan kegagalan diam-diam.",
        "- `browser_used` menunjukkan apakah lengan menyentuh browser runtime (biaya chromium ~",
        f"{doc['cold_start']['chromium_rss_kb'] or '—'} kB RSS, cold start {doc['cold_start']['elapsed_ms']} ms).",
        "",
        "## Cakupan & fidelity diagnosis (per skenario)",
        "",
        "| Skenario | Lengan | Status | State | Attempt (median) | Elapsed ms (median) | Browser | Retry-After dihormati | Sesuai ground truth |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for strategy in STRATEGIES:
        for scenario_id, data in summary.get(strategy, {}).items():
            status_counts = ", ".join(
                f"{count}× {status}" for status, count in data["status_counts"].items()
            )
            lines.append(
                f"| `{scenario_id}` | {strategy} | {status_counts} | "
                f"{', '.join(data['state_counts'])} | {data['attempts_median']} | "
                f"{data['elapsed_ms_median']} | {'ya' if data['browser_used'] else 'tidak'} | "
                f"{'ya' if data['retry_after_honored'] else 'tidak'} | "
                f"{data['ground_truth_match_rate'] * 100:.0f}% |"
            )
    lines += [
        "",
        "## Biaya cold start browser (satu akuisisi, chromium baru)",
        "",
        f"- elapsed: **{doc['cold_start']['elapsed_ms']} ms**",
        f"- RSS chromium: **{doc['cold_start']['chromium_rss_kb']} kB**",
        f"- {doc['cold_start']['note']}",
        "",
        "## Metodologi",
        "",
        f"- pengulangan: {doc['environment']['repeats']} run per (lengan, skenario) untuk skenario berulang;",
        "  skenario fidelity diagnosis dijalankan sekali per lengan (ada jeda Retry-After dari server).",
        "- fixture lokal deterministik (`benchmark/fixture_server.py`) — ground truth berasal dari",
        "  semantika protokol fixture, bukan dari output classifier.",
        "- setiap lengan memakai JobWorker + registry + planner + artifact store yang sama;",
        "  yang dibedakan hanya transport awal (`JobWorker(initial_transport=...)`).",
        "- peak memory = `tracemalloc` (Python); RSS chromium dibaca dari `/proc` setelah render.",
        "",
        "## Batasan yang diketahui",
        "",
        "- Lengan browser memakai chromium persisten (cold start diukur terpisah) agar statistik",
        "  berulang tidak didominasi biaya peluncuran proses.",
        "- Perbandingan ini internal UWAE — tidak ada klaim lintas-implementasi di sini.",
        "  Perbandingan lintas-implementasi yang terukur ada di `engine-results-e14.json`",
        "  (E14) dan ADR-019; baseline Botasaurus terbukti berjalan normal di environment ini.",
        "",
    ]
    return "\n".join(lines)


def main():
    doc = run_benchmark()
    print(f"benchmark : {doc['benchmark_id']}")
    print(f"timestamp : {doc['timestamp']}")
    print(f"runs      : {len(doc['runs'])}")
    for strategy in STRATEGIES:
        scenarios = doc["summary"].get(strategy, {})
        matched = sum(
            data["ground_truth_match_rate"] * data["runs"] for data in scenarios.values()
        )
        total = sum(data["runs"] for data in scenarios.values())
        print(f"  {strategy:14s} ground-truth match: {matched:.0f}/{total:.0f}")
    print(f"results   -> {RESULTS_PATH}")
    print(f"report    -> {REPORT_PATH}")


if __name__ == "__main__":
    main()
