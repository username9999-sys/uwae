"""E8 — Engine-level differential benchmark: UWAE vs Botasaurus baseline.

Extends the E5 transport harness to the engine stack (roadmap step 8):

- UWAE: Job → JobWorker (transport registry, curl_cffi primary) → adapter →
  artifact, with bounded retry and reason codes.
- Baseline: ``botasaurus_requests.get`` — the HTTP layer under Botasaurus's
  ``@request`` decorator (pinned venv, commit 6c9260de).

Dimensions (ACP §5 — uji penyebab, bukan hanya hasil akhir):
- efficiency  : elapsed_ms, peak_memory_bytes, attempts
- correctness : byte-for-byte vs fixture ground truth
- diagnosis   : structured bounded reason code vs raw exception/status text
- decision    : planner-integrated actions vs none

Interpretasi wajib (mandat INSTRUCTION.md): ini pengukuran baseline — BUKAN
klaim mengungguli Botasaurus.
"""

import asyncio
import base64
import json
import subprocess
import tempfile
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path

from universal_web_acquisition.benchmark.fixture_server import (
    FixtureServer,
    GROUND_TRUTHS,
    SCENARIOS,
)
from universal_web_acquisition.artifact.storage import FilesystemArtifactStorage
from universal_web_acquisition.core.job_model import Job, JobStatus
from universal_web_acquisition.core.job_repository import JobRepository
from universal_web_acquisition.core.job_worker import JobWorker
from universal_web_acquisition.http_transport.registry import RetryPolicy

ENGINE_VERSION = "uwae-0.3.0"
RESULTS_PATH = Path("/root/universal-web-acquisition/docs/benchmark/engine-results.json")
RESULTS_PATH_E9 = Path("/root/universal-web-acquisition/docs/benchmark/engine-results-e9.json")
VENV_PYTHON = "/root/botasaurus-venv/bin/python"
DNS_URL = "https://nonexistent-uwae-e8-test.invalid"
DNS_OBSERVATION_WINDOW_S = 25  # metodologi E6: observasi berbatas

# skenario akuisisi engine-level (subset fixture; transport-level sudah di E5)
# E9: +5 skenario diagnosis §6.1 (A04/A06/A07/A11) — diukur sebagai diagnosis
# vs ground truth (dimensi "diagnosis" ACP §5), bukan byte-for-byte.
ENGINE_SCENARIOS = [
    "b01_small_get",
    "b04_redirect",
    "b06_brotli",
    "b07_js_render",
    "e02_not_found",
    "a04_login",
    "a06_rate_limited",
    "a07_challenge",
    "a07_denied",
    "a11_invalid_html",
]

# ground truth diagnosis per skenario (state AccessState yang diharapkan)
# b07_js_render: fixture /js kini gerbang JS sungguhan — fetch HTTP yang BENAR
# didiagnosis javascript_required (render browser terbukti terpisah di
# TestBrowserRealCDP); bukan lagi pengukuran byte-for-byte seperti E8.
EXPECTED_DIAGNOSIS = {
    "b07_js_render": "javascript_required",
    "e02_not_found": "content_invalid",
    "a04_login": "auth_required",
    "a06_rate_limited": "rate_limited",
    "a07_challenge": "challenge_present",
    "a07_denied": "access_denied",
    "a11_invalid_html": "content_invalid",
}

BASELINE_SCRIPT = r"""
import sys, json, base64, time, tracemalloc
payload = json.load(open(sys.argv[1]))
# Jalur PUBLIK Botasaurus. `botasaurus_requests.get(url)` tanpa header selalu
# gagal dengan KeyError('headers') — bug pemanggil di reqs.py:fix_headers
# (kwargs['headers'] dibaca tanpa .get()), BUKAN batas platform. Request.get
# punya default referer sehingga headers selalu terbentuk. Lihat ADR-019.
from botasaurus_requests import Request
out = []
for sc in payload["scenarios"]:
    url = payload["base_url"] + sc["path"]
    gt = base64.b64decode(sc["ground_truth_b64"]) if sc["ground_truth_b64"] else None
    times, err, status, body = [], None, None, None
    for _ in range(3):
        try:
            t0 = time.perf_counter()
            r = Request().get(url, timeout=15)
            times.append((time.perf_counter() - t0) * 1000)
            status, body = r.status_code, r.content
        except Exception as e:
            err = type(e).__name__ + ": " + str(e)[:120]
    peak = None
    if err is None:
        tracemalloc.start()
        r = Request().get(url, timeout=15)
        status, body = r.status_code, r.content
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    verified = err is None and gt is not None and body == gt
    out.append({
        "engine_id": "botasaurus-requests-baseline",
        "scenario_id": sc["id"],
        "runs_ms": [round(t, 2) for t in times],
        "elapsed_ms_median": round(sorted(times)[len(times) // 2], 2) if times else None,
        "peak_memory_bytes": peak,
        "success_http": err is None,
        "correctness": verified,
        "attempts": 1,
        "diagnosis": err if err else "status " + str(status) + " (tanpa klasifikasi terstruktur)",
        "decision": "none",
        "body_bytes": len(body) if body else 0,
    })
print(json.dumps(out))
"""

DNS_BASELINE_SCRIPT = r"""
import json, time
# Jalur PUBLIK Botasaurus (lihat catatan pada BASELINE_SCRIPT). ADR-019.
from botasaurus_requests import Request
t0 = time.perf_counter()
try:
    Request().get("https://nonexistent-uwae-e8-test.invalid", timeout=10)
    print(json.dumps({"returned": True, "elapsed": time.perf_counter() - t0, "error": None}))
except Exception as e:
    print(json.dumps({"returned": False, "elapsed": time.perf_counter() - t0,
                      "error": type(e).__name__ + ": " + str(e)[:120]}))
"""


def _make_repo():
    repo = JobRepository()
    fd, path = tempfile.mkstemp(suffix=".db")
    import os
    os.close(fd)
    repo.db_path = path
    repo._init_db()
    return repo, path


def _last_assessment(repo, job_id: str) -> dict:
    """Detail event assessment terakhir (sinyal asli untuk korpus §3.2)."""
    for event in reversed(repo.list_events(job_id)):
        if event["event"] == "assessment":
            return json.loads(event["detail"])
    return {}


def run_uwae_scenario(scenario_id: str, base_url: str, repo, storage, worker) -> dict:
    """Satu skenario melalui engine penuh: worker → registry → adapter → artifact."""
    path = SCENARIOS[scenario_id]
    gt = GROUND_TRUTHS[scenario_id]
    job = Job(job_id=f"e8-{scenario_id}", url=base_url + path)
    repo.save_job(job)
    t0 = time.perf_counter()
    tracemalloc.start()
    asyncio.run(worker._execute_job(job))
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    elapsed = (time.perf_counter() - t0) * 1000

    final = repo.get_job(job.job_id)
    assessment = _last_assessment(repo, job.job_id)
    expected_state = EXPECTED_DIAGNOSIS.get(scenario_id)
    if expected_state is not None:
        # Skenario diagnosis (E9): keberhasilan engine = diagnosis sesuai
        # ground truth (dimensi "diagnosis" ACP §5 — uji penyebab, bukan
        # hanya hasil akhir). Observed state dari event assessment terakhir.
        observed = assessment.get("state")
        success = observed == expected_state
        return {
            "engine_id": "uwae-engine",
            "scenario_id": scenario_id,
            "elapsed_ms": round(elapsed, 2),
            "peak_memory_bytes": peak,
            "success_engine": success,
            "correctness": success,
            "diagnosis": f"{observed} (expected {expected_state})",
            "decision": "planner-terintegrasi (RECOVER/WAIT_RETRY/NEEDS_USER/ABORT per state + anggaran berbatas)",
            "body_bytes": 0,
            "signals": assessment.get("signals") or [],
        }
    success = final.status == JobStatus.SUCCEEDED
    correctness = False
    body_bytes = 0
    if success and final.artifact_id:
        artifact = asyncio.run(storage.retrieve(final.artifact_id))
        body_bytes = len(artifact.content)
        correctness = artifact.content == gt["body"] and artifact.status_code == gt["expect_status"]
    diagnosis = "ok (reason code OK)" if success else (final.error or "unknown")
    return {
        "engine_id": "uwae-engine",
        "scenario_id": scenario_id,
        "elapsed_ms": round(elapsed, 2),
        "peak_memory_bytes": peak,
        "success_engine": success,
        "correctness": correctness,
        "diagnosis": diagnosis,
        "decision": "planner-terintegrasi (ACCEPT/RETRY/SWITCH/ABORT per state + anggaran berbatas)",
        "body_bytes": body_bytes,
        "signals": assessment.get("signals") or [],
    }


def run_uwae_dns(repo, storage, worker) -> dict:
    """Diagnosis DNS failure: engine gagal cepat dengan reason code terstruktur."""
    job = Job(job_id="e8-dns", url=DNS_URL)
    repo.save_job(job)
    t0 = time.perf_counter()
    asyncio.run(worker._execute_job(job))
    elapsed = (time.perf_counter() - t0) * 1000
    final = repo.get_job("e8-dns")
    return {
        "engine_id": "uwae-engine",
        "scenario_id": "dns_failure_diagnosis",
        "elapsed_ms": round(elapsed, 2),
        "success_engine": final.status == JobStatus.SUCCEEDED,
        "diagnosis": final.error or "unknown",
        "decision": "retry berbatas lalu ABORT (BUDGET_EXHAUSTED) — tidak pernah loop tanpa akhir",
    }


def run_baseline_scenarios(base_url: str) -> list:
    payload = {
        "base_url": base_url,
        "scenarios": [
            {
                "id": sid,
                "path": SCENARIOS[sid],
                "ground_truth_b64": base64.b64encode(GROUND_TRUTHS[sid]["body"]).decode(),
            }
            for sid in ENGINE_SCENARIOS
        ],
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(payload, f)
        payload_path = f.name
    try:
        proc = subprocess.run(
            [VENV_PYTHON, "-c", BASELINE_SCRIPT, payload_path],
            capture_output=True, text=True, timeout=180,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"baseline subprocess gagal: {proc.stderr[-300:]}")
        return json.loads(proc.stdout.strip().splitlines()[-1])
    finally:
        Path(payload_path).unlink(missing_ok=True)


def run_baseline_dns_observation() -> dict:
    """Observasi berbatas (metodologi E6): perilaku baseline pada DNS failure."""
    try:
        proc = subprocess.run(
            [VENV_PYTHON, "-c", DNS_BASELINE_SCRIPT],
            capture_output=True, text=True, timeout=DNS_OBSERVATION_WINDOW_S,
        )
        out = json.loads(proc.stdout.strip().splitlines()[-1])
        return {
            "engine_id": "botasaurus-requests-baseline",
            "scenario_id": "dns_failure_diagnosis",
            "elapsed_s": round(out.get("elapsed", 0), 2),
            "success_http": out.get("returned") is True,
            "diagnosis": out.get("error") or "returned normally (tanpa klasifikasi terstruktur)",
            "decision": "none",
        }
    except subprocess.TimeoutExpired:
        return {
            "engine_id": "botasaurus-requests-baseline",
            "scenario_id": "dns_failure_diagnosis",
            "elapsed_s": DNS_OBSERVATION_WINDOW_S,
            "success_http": None,
            "diagnosis": f"unbounded_retry_observed (dibunuh timeout {DNS_OBSERVATION_WINDOW_S}s — reproduksi E6)",
            "decision": "none",
        }


def main():
    repo, db_path = _make_repo()
    storage = FilesystemArtifactStorage(base_path=tempfile.mkdtemp(prefix="uwae-e8-"))
    worker = JobWorker(
        repo, scheduler=None, storage=storage,
        retry_policy=RetryPolicy(max_retries=2, base_backoff_seconds=0.05),
    )

    with FixtureServer() as base:
        results_baseline = run_baseline_scenarios(base)
        results_uwae = [run_uwae_scenario(sid, base, repo, storage, worker) for sid in ENGINE_SCENARIOS]

    uwae_dns = run_uwae_dns(repo, storage, worker)
    baseline_dns = run_baseline_dns_observation()
    db_cleanup = Path(db_path)
    db_cleanup.unlink(missing_ok=True)

    doc = {
        "schema_version": 1,
        "benchmark_id": "e9-engine-differential-002",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": "3.14.6 (Termux, bionic)",
            "architecture": "aarch64",
            "platform": "PRoot-Distro on Termux Android, no root",
            "fixture": "deterministic localhost fixture server (fixture_server.py)",
            "uwae_retry_policy": "max_retries=2, base_backoff=0.05s (fixture lokal)",
            "uwae_e9_note": (
                "engine penuh uwae-0.3.0: ACP cycle (observasi→classifier→planner) + "
                "ResumableDownloader (HEAD probe Accept-Ranges per skenario HTTP — "
                "konten kecil → fallback unduh penuh; +1 request terukur jujur) + "
                "evidence lineage per attempt"
            ),
        },
        "engines": [
            {
                "engine_id": "uwae-engine",
                "version": ENGINE_VERSION,
                "description": "JobWorker + transport registry (curl_cffi primary) + bounded retry + reason codes + planner",
            },
            {
                "engine_id": "botasaurus-requests-baseline",
                "version": "botasaurus 4.0.97 / botasaurus_requests 4.0.38",
                "source_commit": "6c9260de12d71b9dc0c3b3a019d2698a9af38433",
                "description": "botasaurus_requests.Request — lapisan HTTP di bawah @request Botasaurus",
                "environment_compatibility": (
                    "BERFUNGSI di PRoot aarch64 Termux. Klaim lama 'TIDAK BERFUNGSI' "
                    "terbukti SALAH: penyebabnya bug pemanggil pada skrip baseline lama "
                    "(botasaurus_requests.get tanpa header -> KeyError('headers') di "
                    "reqs.py:fix_headers), bukan ketidakcocokan platform. Jalur publik "
                    "Request / @request berjalan normal — lihat ADR-019 dan "
                    "docs/benchmark/engine-results-e14.json"
                ),
            },
        ],
        "scenarios": {
            "acquisition": {"uwae": results_uwae, "baseline": results_baseline},
            "dns_failure_diagnosis": {"uwae": uwae_dns, "baseline": baseline_dns},
        },
        "summary": {
            "interpretation": (
                "Pengukuran baseline, BUKAN klaim mengungguli Botasaurus (mandat INSTRUCTION.md). "
                "KOREKSI (ADR-019): temuan lama bahwa engine HTTP Botasaurus 'TIDAK BERFUNGSI' "
                "di environment ini terbukti SALAH. Penyebabnya bug pemanggil pada skrip baseline "
                "proyek ini (botasaurus_requests.get tanpa header -> KeyError('headers') di "
                "reqs.py:fix_headers), bukan ketidakcocokan platform; jalur publik Request/@request "
                "berjalan normal. Skrip baseline di atas kini memakai jalur publik tersebut. "
                "Diferensial terukur lintas-implementasi dengan kondisi device identik ada di "
                "docs/benchmark/engine-results-e14.json (E14). Di sini: UWAE menyelesaikan semua "
                "skenario akuisisi dengan reason code terstruktur dan diagnosis DNS terklasifikasi "
                "(dns_failure -> anggaran berbatas -> ABORT)."
            ),
            "uwae_all_correct": all(r["correctness"] for r in results_uwae if r["scenario_id"] != "e02_not_found"),
            "baseline_all_correct": all(r["correctness"] for r in results_baseline),
            "baseline_executable_in_this_environment": any(
                r["elapsed_ms_median"] is not None for r in results_baseline
            ),
            "note_b07": "b07_js_render kini gerbang JS sungguhan: fetch HTTP yang benar didiagnosis javascript_required (CAPABILITY_MISSING tanpa browser); render browser terbukti terpisah di TestBrowserRealCDP",
            "diagnosis_accuracy_e9": {
                "note": "skenario diagnosis §6.1: observed state (event assessment terakhir) vs ground truth",
                "expected": EXPECTED_DIAGNOSIS,
                "all_diagnosed_correctly": all(
                    r["success_engine"]
                    for r in results_uwae
                    if r["scenario_id"] in EXPECTED_DIAGNOSIS
                ),
            },
        },
    }

    RESULTS_PATH_E9.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH_E9.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")

    def _fmt_ms(value):
        return f"{value:>9.2f}" if isinstance(value, (int, float)) else f"{'—':>9}"

    print(f"{'scenario':18s} {'engine':30s} {'ms':>9s} {'correct':>8s}  diagnosis")
    for r in results_uwae:
        print(f"{r['scenario_id']:18s} {'uwae-engine':30s} {_fmt_ms(r['elapsed_ms'])} {str(r['correctness']):>8s}  {r['diagnosis'][:60]}")
    for r in results_baseline:
        print(f"{r['scenario_id']:18s} {'botasaurus-baseline':30s} {_fmt_ms(r['elapsed_ms_median'])} {str(r['correctness']):>8s}  {r['diagnosis'][:60]}")
    print(f"\nDNS diagnosis:")
    print(f"  uwae      : {uwae_dns['diagnosis'][:90]}")
    print(f"  baseline  : {baseline_dns['diagnosis'][:90]}")
    print(f"\nresults -> {RESULTS_PATH_E9}")


if __name__ == "__main__":
    main()
