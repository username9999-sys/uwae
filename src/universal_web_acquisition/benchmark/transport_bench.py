"""E5 — Differential transport benchmark against a deterministic fixture server.

Engines (Termux Python 3.14.6): httpx, requests, curl_cffi
Baseline: requests 2.34.2 from the pinned botasaurus-venv (subprocess).

Method per (engine, scenario):
  - 5 timed runs (median reported, fresh connection each run)
  - 1 memory run with tracemalloc (Python-level peak; C buffers not counted)
  - correctness: status == expected AND body == ground truth (byte-for-byte)

Usage: PYTHONPATH=src python -m universal_web_acquisition.benchmark.transport_bench
"""

import base64
import json
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
from datetime import datetime, timezone
from importlib.metadata import version as pkg_version
from pathlib import Path

from universal_web_acquisition.benchmark.fixture_server import (
    FixtureServer,
    GROUND_TRUTHS,
    SCENARIOS,
)

SCENARIO_META = {
    "b01_small_get": {"category": "B01", "description": "Small HTML GET (<1KB), byte-for-byte ground truth"},
    "b01_large_get": {"category": "B01", "description": "Large GET (~1.05MB), byte-for-byte ground truth"},
    "b04_redirect": {"category": "B04", "description": "3-hop redirect chain (301->302->307), final content"},
    "b06_gzip": {"category": "B06", "description": "Content-Encoding: gzip, auto-decode"},
    "b06_brotli": {"category": "B06", "description": "Content-Encoding: br, auto-decode"},
    "e02_not_found": {"category": "E02", "description": "HTTP 404 handled: correct status, no crash"},
}

RUNS = 5
VENV_PYTHON = "/root/botasaurus-venv/bin/python"
RESULTS_PATH = Path("/root/universal-web-acquisition/docs/benchmark/transport-results.json")

BASELINE_SCRIPT = r"""
import sys, json, base64, time, tracemalloc
payload = json.load(open(sys.argv[1]))
import requests
out = []
for sc in payload["scenarios"]:
    url = payload["base_url"] + sc["path"]
    gt = base64.b64decode(sc["ground_truth_b64"]) if sc["ground_truth_b64"] else None
    times, err, status, body = [], None, None, None
    for _ in range(5):
        try:
            t0 = time.perf_counter()
            r = requests.get(url, timeout=15)
            times.append((time.perf_counter() - t0) * 1000)
            status, body = r.status_code, r.content
        except Exception as e:
            err = type(e).__name__ + ": " + str(e)[:120]
    if err is None:
        tracemalloc.start()
        r = requests.get(url, timeout=15)
        status, body = r.status_code, r.content
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    else:
        peak = None
    verified = err is None and status == sc["expect_status"] and (gt is None or body == gt)
    out.append({
        "engine_id": "requests-botasaurus-venv",
        "scenario_id": sc["id"],
        "runs_ms": [round(t, 2) for t in times],
        "elapsed_ms_median": round(sorted(times)[len(times) // 2], 2) if times else None,
        "peak_memory_bytes": peak,
        "status_code": status,
        "success": verified,
        "verified_acquisition": verified,
        "output_fidelity_score": 1.0 if verified else 0.0,
        "error": err,
        "body_bytes": len(body) if body else 0,
    })
print(json.dumps(out))
"""


def engine_get(engine_id: str, url: str):
    """Returns (status_code, content). Lazy imports keep baseline subprocess clean."""
    if engine_id == "httpx":
        import httpx
        r = httpx.get(url, timeout=10, follow_redirects=True)
        return r.status_code, r.content
    if engine_id == "requests":
        import requests
        r = requests.get(url, timeout=10)
        return r.status_code, r.content
    if engine_id == "curl_cffi":
        from curl_cffi import requests as cr
        r = cr.get(url, timeout=15)
        return r.status_code, r.content
    raise ValueError(f"unknown engine: {engine_id}")


def measure(engine_id: str, base_url: str, scenario_id: str):
    path = SCENARIOS[scenario_id]
    gt = GROUND_TRUTHS[scenario_id]
    url = base_url + path
    times, err, status, body = [], None, None, None
    for _ in range(RUNS):
        try:
            t0 = time.perf_counter()
            status, body = engine_get(engine_id, url)
            times.append((time.perf_counter() - t0) * 1000)
        except Exception as e:
            err = type(e).__name__ + ": " + str(e)[:120]
    peak = None
    if err is None:
        tracemalloc.start()
        status, body = engine_get(engine_id, url)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    verified = err is None and status == gt["expect_status"] and body == gt["body"]
    return {
        "engine_id": engine_id,
        "scenario_id": scenario_id,
        "runs_ms": [round(t, 2) for t in times],
        "elapsed_ms_median": round(statistics.median(times), 2) if times else None,
        "peak_memory_bytes": peak,
        "status_code": status,
        "success": verified,
        "verified_acquisition": verified,
        "output_fidelity_score": 1.0 if verified else 0.0,
        "error": err,
        "body_bytes": len(body) if body else 0,
    }


def run_baseline(base_url: str):
    """Runs the pinned botasaurus-venv requests as baseline via subprocess."""
    payload = {
        "base_url": base_url,
        "scenarios": [
            {
                "id": sid,
                "path": SCENARIOS[sid],
                "expect_status": GROUND_TRUTHS[sid]["expect_status"],
                "ground_truth_b64": base64.b64encode(GROUND_TRUTHS[sid]["body"]).decode(),
            }
            for sid in SCENARIOS
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
            raise RuntimeError(f"baseline subprocess failed: {proc.stderr[-300:]}")
        return json.loads(proc.stdout.strip().splitlines()[-1])
    finally:
        Path(payload_path).unlink(missing_ok=True)


def main():
    engines = [
        {"engine_id": "httpx", "engine_name": "httpx", "engine_version": pkg_version("httpx"), "is_baseline": False},
        {"engine_id": "requests", "engine_name": "requests", "engine_version": pkg_version("requests"), "is_baseline": False},
        {"engine_id": "curl_cffi", "engine_name": "curl_cffi", "engine_version": pkg_version("curl_cffi"), "is_baseline": False},
        {"engine_id": "requests-botasaurus-venv", "engine_name": "requests (botasaurus-venv baseline)",
         "engine_version": None, "source_commit": "6c9260de12d71b9dc0c3b3a019d2698a9af38433", "is_baseline": True},
    ]
    termux_engines = ["httpx", "requests", "curl_cffi"]

    with FixtureServer() as base_url:
        baseline_results = run_baseline(base_url)
        by_scenario = {sid: [] for sid in SCENARIOS}
        for engine_id in termux_engines:
            for sid in SCENARIOS:
                by_scenario[sid].append(measure(engine_id, base_url, sid))
        for r in baseline_results:
            by_scenario[r["scenario_id"]].append(r)

    scenarios_out = []
    for sid, meta in SCENARIO_META.items():
        gt = GROUND_TRUTHS[sid]
        scenarios_out.append({
            "scenario_id": sid,
            "category": meta["category"],
            "description": meta["description"],
            "ground_truth": f"status {gt['expect_status']} + byte-for-byte body",
            "results": by_scenario[sid],
        })

    # summary: best (fastest successful) engine per scenario vs baseline
    summary_rows = []
    for s in scenarios_out:
        ok = [r for r in s["results"] if r["success"] and r["elapsed_ms_median"] is not None]
        if not ok:
            summary_rows.append({"scenario_id": s["scenario_id"], "best_engine": None})
            continue
        best = min(ok, key=lambda r: r["elapsed_ms_median"])
        base = next((r for r in s["results"] if r["engine_id"] == "requests-botasaurus-venv"), None)
        row = {
            "scenario_id": s["scenario_id"],
            "best_engine": best["engine_id"],
            "best_elapsed_ms_median": best["elapsed_ms_median"],
            "baseline_elapsed_ms_median": base["elapsed_ms_median"] if base else None,
        }
        if base and base["success"] and base["elapsed_ms_median"]:
            row["baseline_vs_best_ratio"] = round(base["elapsed_ms_median"] / best["elapsed_ms_median"], 2)
        summary_rows.append(row)

    doc = {
        "schema_version": 1,
        "benchmark_id": "e5-transport-differential-001",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": "3.14.6 (Termux, bionic)",
            "architecture": "aarch64",
            "platform": "PRoot-Distro on Termux Android, no root",
            "fixture": "deterministic localhost fixture server (fixture_server.py)",
            "method": f"{RUNS} timed runs (median) + 1 tracemalloc run; fresh connection per run",
            "schema_note": "extends result-schema.json: scenarios[] replaces single scenario object",
        },
        "engines": engines,
        "scenarios": scenarios_out,
        "summary": {"per_scenario": summary_rows},
    }

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")

    # console summary
    print(f"{'scenario':16s} {'engine':26s} {'median ms':>10s} {'mem KB':>9s} {'ok':>4s}")
    for s in scenarios_out:
        for r in s["results"]:
            mem = f"{r['peak_memory_bytes']/1024:.1f}" if r["peak_memory_bytes"] else "-"
            print(f"{s['scenario_id']:16s} {r['engine_id']:26s} {str(r['elapsed_ms_median']):>10s} {mem:>9s} {str(r['success']):>5s}")
    print(f"\nresults -> {RESULTS_PATH}")


if __name__ == "__main__":
    main()
