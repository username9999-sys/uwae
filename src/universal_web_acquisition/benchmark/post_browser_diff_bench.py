"""E22 -- Differential lintas-implementasi untuk POST via browser form (UWAE vs Botasaurus).

Menutup celah OPEN ketiga yang dideklarasikan E20: ``post_browser_arm``.

Skenario ``p07_post_browser_form``: browser membuka halaman form
(GET ``/post/form-page``), mengisi dan men-submit form ke
``/post/form-page-target``. Ground truth = ``FORM_OK_BODY`` dari target.
Browser tidak bisa mengirim header kustom, jadi protokol target longgar
(method + body saja) — itu memang yang ingin diukur: apakah kedua mesin
browser benar-benar mengeksekusi submit form sebagai POST.

Protokol fairness identik E16/E20/E21: target identik, expected output
identik (dari semantik protokol fixture), device conditions identik (kedua
arm sebagai subprocess dari SATU interpreter dengan SATU PYTHONPATH, chromium
headless yang sama), run count identik (n=30), success criteria identik
(status + sha256(body) byte-for-byte).

Pola skema mengikuti E16 (``summary.comparisons`` -> ``e16_like``) supaya
``discover_slots()`` di corpus_matrix menemukannya sebagai slot baru.

Peringatan API yang sudah terverifikasi (jangan diulangi kesalahannya):
- Botasaurus ``Tab.evaluate`` WAJIB diawali ``return`` (kalau tidak, hasil
  selalu None).
- ``raise_exception=False`` menelan exception — tangkap di dalam task.
- ``headless=True`` WAJIB di device ini (tanpa X server).
- Port CDP harus berbeda antar arm (E16: 9381/9382/9383); di sini 9384/9385.

Usage:
    PYTHONPATH=/root/botasaurus-venv/lib/python3.14/site-packages:src \\
        /root/uwae-comparison-venv/bin/python \\
        -m universal_web_acquisition.benchmark.post_browser_diff_bench
"""

import hashlib
import json
import os
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from universal_web_acquisition.benchmark._checkpoint import (
    Checkpoint,
    timing_evidence,
)
from universal_web_acquisition.benchmark.cross_impl_bench import (
    COMPARISON_PYTHONPATH,
    _interpreter_identity,
    _package_versions,
    _preflight,
    _run_arm,
)
from universal_web_acquisition.benchmark.fixture_post import (
    POST_EXT_GROUND_TRUTHS,
    POST_EXT_SCENARIOS,
    PostFixtureServer,
    protocol_summary,
)

# --------------------------------------------------------------------------
# Konfigurasi slot E22
# --------------------------------------------------------------------------

RUNS = int(os.environ.get("UWAE_E22_RUNS", "30"))

RESULTS_PATH = Path(
    os.environ.get(
        "UWAE_E22_RESULTS_PATH",
        "/root/universal-web-acquisition/docs/benchmark/engine-results-e22.json",
    )
)

BENCHMARK_ID = os.environ.get(
    "UWAE_E22_BENCHMARK_ID", "e22-browser-form-post-differential-001"
)

SUPERSEDES: List[str] = [
    item.strip()
    for item in os.environ.get("UWAE_E22_SUPERSEDES", "").split(",")
    if item.strip()
]

CHECKPOINT_PATH = Path(
    os.environ.get("UWAE_E22_CHECKPOINT", "/root/.qwen/tmp/e22_checkpoint.jsonl")
)

#: Browser itu mahal di device ini (cold start ~5s). Timeout arm besar.
ARM_TIMEOUT_S = int(os.environ.get("UWAE_E22_ARM_TIMEOUT_S", "1800"))

INTERRUPTION_GAP_THRESHOLD_S = 120.0

SCENARIO_ID = "p07_post_browser_form"
PAGE_PATH = POST_EXT_SCENARIOS[SCENARIO_ID]          # /post/form-page
TARGET_PATH = POST_EXT_GROUND_TRUTHS[SCENARIO_ID]["target_path"]  # /post/form-page-target

#: Port CDP tetap, berbeda antar arm (mengikuti pola E16).
CDP_PORTS = {"uwae-browser": 9384, "botasaurus-browser": 9385}

CLOSED_BY_THIS_SLOT = [
    {
        "scenario_id": "post_browser_arm",
        "reason": (
            "E20 hanya mengukur arm HTTP. E22 mengukur POST yang dieksekusi "
            "lewat submit form HTML oleh kedua mesin browser (chromium headless) "
            "pada device yang sama."
        ),
    },
]

UNSUPPORTED_SCENARIOS = [
    {
        "scenario_id": "post_browser_multipart_upload",
        "reason": (
            "Upload file via <input type=file> di browser tidak diukur — "
            "butuh file nyata di disk dan interaksi file chooser CDP yang "
            "berbeda antar mesin."
        ),
        "supported_by": [],
    },
]


# --------------------------------------------------------------------------
# Skrip arm browser
# --------------------------------------------------------------------------

#: Body JS untuk submit form — IDENTIK untuk kedua arm.
#: Perbedaannya hanya cara pembungkusan, karena kedua API memang berbeda:
#:
#: - UWAE (CDP mentah via ``Runtime.evaluate``): ``return`` di top-level
#:   DITOLAK ("SyntaxError: Illegal return statement"), jadi ekspresi harus
#:   dibungkus IIFE: ``(function(){ BODY })()``.
#: - Botasaurus (``Tab.evaluate``): ekspresi dimasukkan ke dalam body blok
#:   arrow function, jadi WAJIB diawali ``return``: ``return (function(){ BODY })()``.
#:
#: Logika di dalam BODY sama persis — tidak ada perlakuan khusus untuk salah
#: satu arm. Ini diukur dengan probe: ``evaluate("1+1")`` -> 2 di CDP mentah,
#: ``evaluate("return 1+1")`` -> SyntaxError.
SUBMIT_JS_BODY = (
    "var f=document.getElementById('f');"
    "if(!f){return 'NO_FORM';}"
    "f.submit();"
    "return 'SUBMITTED';"
)

#: Setelah submit, tunggu DOM baru lalu baca body. Dipakai sebagai dua
#: langkah terpisah supaya arm tidak perlu menggabungkan logika.
READ_BODY_JS_BODY = "return document.body ? document.body.innerText : '';"
READ_STATUS_JS_BODY = (
    "return String((performance.getEntriesByType('navigation')[0] || {}).responseStatus || 0);"
)
READY_STATE_JS_BODY = "return document.readyState;"


def _uwae_expr(body: str) -> str:
    """Bungkus body JS untuk CDP mentah UWAE (return top-level ilegal)."""
    return "(function(){" + body + "})()"


def _botasaurus_expr(body: str) -> str:
    """Bungkus body JS untuk Botasaurus Tab.evaluate (wajib prefix return)."""
    return "return (function(){" + body + "})()"

UWAE_BROWSER_ARM_SCRIPT = r'''
import asyncio
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

payload = json.load(open(sys.argv[1]))
out_path = sys.argv[2]

from universal_web_acquisition.benchmark._checkpoint import Checkpoint
from universal_web_acquisition.browser.cdp import CDPBrowser

CHECKPOINT = Checkpoint(Path(payload["checkpoint_path"]), payload["fingerprint"])
results = []

async def one_run(browser, run_index):
    cached = CHECKPOINT.get(payload["scenario_id"], "uwae-browser", run_index)
    if cached is not None:
        return cached
    run_started_epoch = time.time()
    t0 = time.perf_counter()
    row = {"scenario_id": payload["scenario_id"], "run_index": run_index, "browser_used": True}
    try:
        # 1. buka halaman form
        await browser.render(payload["page_url"])
        # 2. submit form via JS. Body sama dengan arm Botasaurus; pembungkus
        #    IIFE karena Runtime.evaluate CDP mentah MENOLAK ``return`` di
        #    top-level (SyntaxError: Illegal return statement).
        submit_js = "(function(){" + payload["submit_js_body"] + "})()"
        submit_result = await browser.evaluate(submit_js)
        row["submit_js_result"] = submit_result
        # 3. tunggu navigasi form selesai, lalu baca halaman hasil
        await asyncio.sleep(1.5)
        read_body_js = "(function(){" + payload["read_body_js_body"] + "})()"
        read_status_js = "(function(){" + payload["read_status_js_body"] + "})()"
        body_text = await browser.evaluate(read_body_js)
        raw_status = await browser.evaluate(read_status_js)
        try:
            status_code = int(raw_status)
        except (TypeError, ValueError):
            status_code = None
        body = (body_text or "").encode("utf-8", "replace")
        row["status_code"] = status_code
        row["body_sha256"] = hashlib.sha256(body).hexdigest()
        row["body_bytes"] = len(body)
        row["body_text"] = (body_text or "")[:200]
        row["raw_signal"] = f"status {status_code}"
    except Exception as exc:
        row["error"] = (type(exc).__name__ + ": " + str(exc))[:300]
        row["raw_signal"] = row.get("error", "")
    row["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    row["attempts"] = 1
    row["request_method"] = "POST-via-form"
    row["recorded_at"] = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    row["run_started_epoch"] = run_started_epoch
    row["recorded_epoch"] = time.time()
    row["fixture_base_url"] = payload["base_url"]
    row["invocation_id"] = payload["invocation_id"]
    CHECKPOINT.append(payload["scenario_id"], "uwae-browser", run_index, row)
    return row


async def main_async():
    with CDPBrowser(port=payload["cdp_port"], start_timeout=30.0, render_timeout=15.0) as browser:
        for run_index in range(payload["runs"]):
            results.append(await one_run(browser, run_index))

arm_started_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
arm_started_epoch = time.time()
asyncio.run(main_async())
with open(out_path, "w") as handle:
    json.dump({
        "engine_id": "uwae-browser",
        "arm_started_at": arm_started_at,
        "arm_finished_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        "arm_started_epoch": arm_started_epoch,
        "arm_finished_epoch": time.time(),
        "results": results,
    }, handle)
'''


BOTASAURUS_BROWSER_ARM_SCRIPT = r'''
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

payload = json.load(open(sys.argv[1]))
out_path = sys.argv[2]

from botasaurus.browser_decorator import browser
from universal_web_acquisition.benchmark._checkpoint import Checkpoint

CHECKPOINT = Checkpoint(Path(payload["checkpoint_path"]), payload["fingerprint"])


@browser(
    output=None,
    cache=False,
    create_error_logs=False,
    raise_exception=False,
    close_on_crash=True,
    headless=True,
    chrome_executable_path="/usr/bin/chromium",
    add_arguments=["--no-sandbox", "--disable-dev-shm-usage"],
    port=payload["cdp_port"],
)
def acquire(driver, item):
    """Buka halaman form lalu submit via JS — sama persis dengan arm UWAE.

    Semua ekspresi evaluate WAJIB diawali ``return`` (kalau tidak, hasil
    selalu None karena ekspresi masuk ke body blok arrow function).
    Exception ditangkap di dalam task karena ``raise_exception=False``
    menelan error.
    """
    try:
        tab = driver.get(item["page_url"], timeout=60)
        # Body sama dengan arm UWAE; Botasaurus WAJIB prefix ``return``
        # karena ekspresi masuk ke body blok arrow function.
        submit_js = "return (function(){" + item["submit_js_body"] + "})()"
        submit_result = tab.evaluate(submit_js)
        # tunggu navigasi form selesai
        tab.wait(1.5)
        read_body_js = "return (function(){" + item["read_body_js_body"] + "})()"
        read_status_js = "return (function(){" + item["read_status_js_body"] + "})()"
        body_text = tab.evaluate(read_body_js)
        raw_status = tab.evaluate(read_status_js)
        try:
            status_code = int(raw_status)
        except (TypeError, ValueError):
            status_code = None
        body = (body_text or "").encode("utf-8", "replace")
        return {
            "status_code": status_code,
            "body_sha256": hashlib.sha256(body).hexdigest(),
            "body_bytes": len(body),
            "body_text": (body_text or "")[:200],
            "submit_js_result": submit_result,
            "raw_signal": f"status {status_code}",
        }
    except Exception as exc:
        return {"error": (type(exc).__name__ + ": " + str(exc))[:300],
                "raw_signal": "error"}


arm_started_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
arm_started_epoch = time.time()
results = []
for run_index in range(payload["runs"]):
    cached = CHECKPOINT.get(payload["scenario_id"], "botasaurus-browser", run_index)
    if cached is not None:
        results.append(cached)
        continue
    run_started_epoch = time.time()
    t0 = time.perf_counter()
    outcome = acquire({"page_url": payload["page_url"],
                       "submit_js_body": payload["submit_js_body"],
                       "read_body_js_body": payload["read_body_js_body"],
                       "read_status_js_body": payload["read_status_js_body"]})
    elapsed_ms = (time.perf_counter() - t0) * 1000
    row = dict(outcome) if isinstance(outcome, dict) else {}
    row["scenario_id"] = payload["scenario_id"]
    row["run_index"] = run_index
    row["elapsed_ms"] = round(elapsed_ms, 2)
    row["attempts"] = 1
    row["browser_used"] = True
    row["request_method"] = "POST-via-form"
    row["recorded_at"] = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    row["run_started_epoch"] = run_started_epoch
    row["recorded_epoch"] = time.time()
    row["fixture_base_url"] = payload["base_url"]
    row["invocation_id"] = payload["invocation_id"]
    CHECKPOINT.append(payload["scenario_id"], "botasaurus-browser", run_index, row)
    results.append(row)

with open(out_path, "w") as handle:
    json.dump({
        "engine_id": "botasaurus-browser",
        "arm_started_at": arm_started_at,
        "arm_finished_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        "arm_started_epoch": arm_started_epoch,
        "arm_finished_epoch": time.time(),
        "results": results,
    }, handle)
'''


# --------------------------------------------------------------------------
# Fingerprint
# --------------------------------------------------------------------------


def _harness_fingerprint() -> str:
    truth = POST_EXT_GROUND_TRUTHS[SCENARIO_ID]
    material = {
        "runs": RUNS,
        "arm_timeout_s": ARM_TIMEOUT_S,
        "scenario_id": SCENARIO_ID,
        "page_path": PAGE_PATH,
        "target_path": TARGET_PATH,
        "ground_truth_status": truth["expect_status"],
        "ground_truth_body_sha256": hashlib.sha256(truth["body"]).hexdigest(),
        "expect_request_body_sha256": truth["expect_body_sha256"],
        "submit_js_body": SUBMIT_JS_BODY,
        "read_body_js_body": READ_BODY_JS_BODY,
        "read_status_js_body": READ_STATUS_JS_BODY,
        "uwae_expr_wrapper": "iife",
        "botasaurus_expr_wrapper": "return-prefix",
        "cdp_ports": CDP_PORTS,
        "closed_by_this_slot": CLOSED_BY_THIS_SLOT,
        "unsupported_scenarios": UNSUPPORTED_SCENARIOS,
        "uwae_arm_script": UWAE_BROWSER_ARM_SCRIPT,
        "botasaurus_arm_script": BOTASAURUS_BROWSER_ARM_SCRIPT,
    }
    payload = json.dumps(material, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class _Checkpoint(Checkpoint):
    def __init__(self, path: Path):
        super().__init__(path, _harness_fingerprint())


# --------------------------------------------------------------------------
# Penilaian
# --------------------------------------------------------------------------


def _assess_run(row: dict) -> Dict:
    truth = POST_EXT_GROUND_TRUTHS[SCENARIO_ID]
    expect_sha = hashlib.sha256(truth["body"]).hexdigest()
    status_ok = row.get("status_code") == truth["expect_status"]
    body_ok = row.get("body_sha256") == expect_sha
    return {
        "acquisition_verified": bool(status_ok and body_ok),
        "status_match": bool(status_ok),
        "body_match": bool(body_ok),
        "primary_success": bool(status_ok and body_ok),
    }


def _summarise(arm_rows: List[dict]) -> Dict:
    rows = [r for r in arm_rows if r.get("scenario_id") == SCENARIO_ID]
    if not rows:
        return {"runs": 0, "primary_successes": 0, "primary_success_rate": None,
                "elapsed_ms_median": None, "elapsed_ms_min": None, "elapsed_ms_max": None,
                "acquisition_verified_runs": 0, "status_match_runs": 0, "body_match_runs": 0,
                "browser_used_runs": 0, "raw_signals": [], "errors": []}
    assessed = [_assess_run(r) for r in rows]
    timings = [float(r["elapsed_ms"]) for r in rows if r.get("elapsed_ms") is not None]
    from universal_web_acquisition.benchmark.cross_impl_bench import _median
    return {
        "runs": len(rows),
        "primary_successes": sum(1 for a in assessed if a["primary_success"]),
        "primary_success_rate": round(sum(1 for a in assessed if a["primary_success"]) / len(assessed), 4),
        "elapsed_ms_median": round(_median(timings), 2) if timings else None,
        "elapsed_ms_min": round(min(timings), 2) if timings else None,
        "elapsed_ms_max": round(max(timings), 2) if timings else None,
        "acquisition_verified_runs": sum(1 for a in assessed if a["acquisition_verified"]),
        "status_match_runs": sum(1 for a in assessed if a["status_match"]),
        "body_match_runs": sum(1 for a in assessed if a["body_match"]),
        "browser_used_runs": sum(1 for r in rows if r.get("browser_used")),
        "raw_signals": sorted({str(r.get("raw_signal")) for r in rows})[:5],
        "errors": sorted({str(r.get("error")) for r in rows if r.get("error")})[:5],
    }


def _map_observations(arm_rows: List[dict], observations: List[dict], invocation_id: str) -> Dict:
    executed = [
        row for row in arm_rows
        if row.get("invocation_id") == invocation_id and row.get("run_started_epoch")
    ]
    page_hits = 0
    target_hits = 0
    target_ok = 0
    for row in executed:
        start = float(row["run_started_epoch"])
        end = float(row.get("recorded_epoch") or start)
        for e in observations:
            if start <= float(e["at_epoch"]) <= end:
                if e.get("path") == PAGE_PATH:
                    page_hits += 1
                if e.get("path") == TARGET_PATH:
                    target_hits += 1
                    if e.get("protocol_verdict") == "ok":
                        target_ok += 1
    summary = protocol_summary(
        [e for e in observations if e.get("path") in (PAGE_PATH, TARGET_PATH)]
    )
    summary.update({
        "runs_executed": len(executed),
        "page_gets_observed": page_hits,
        "target_posts_observed": target_hits,
        "target_posts_ok": target_ok,
        "attribution": (
            "Setiap run yang berhasil harus menghasilkan tepat dua observasi: "
            "GET halaman form lalu POST ke target. POST tanpa GET halaman, atau "
            "GET tanpa POST, adalah bukti yang tidak lengkap — dilaporkan apa adanya."
        ),
    })
    return summary


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def main() -> None:
    _preflight()
    started = time.perf_counter()
    invocation_id = uuid.uuid4().hex

    checkpoint = _Checkpoint(CHECKPOINT_PATH)
    keys_before = set(checkpoint.rows.keys())

    truth = POST_EXT_GROUND_TRUTHS[SCENARIO_ID]

    fixture = PostFixtureServer()
    with fixture as base_url:
        payload = {
            "runs": RUNS,
            "base_url": base_url,
            "scenario_id": SCENARIO_ID,
            "page_url": base_url + PAGE_PATH,
            "target_path": TARGET_PATH,
            "checkpoint_path": str(CHECKPOINT_PATH),
            "fingerprint": checkpoint.fingerprint,
            "invocation_id": invocation_id,
            "submit_js_body": SUBMIT_JS_BODY,
            "read_body_js_body": READ_BODY_JS_BODY,
            "read_status_js_body": READ_STATUS_JS_BODY,
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(payload, handle)
            payload_path = handle.name

        uwae_out = payload_path + ".uwae.json"
        botasaurus_out = payload_path + ".botasaurus.json"

        uwae_payload = dict(payload, cdp_port=CDP_PORTS["uwae-browser"])
        botasaurus_payload = dict(payload, cdp_port=CDP_PORTS["botasaurus-browser"])
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as h1:
            json.dump(uwae_payload, h1)
            uwae_payload_path = h1.name
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as h2:
            json.dump(botasaurus_payload, h2)
            botasaurus_payload_path = h2.name

        # Urutan sama dengan E16/E20: Botasaurus dulu, lalu UWAE.
        botasaurus = _run_arm(
            BOTASAURUS_BROWSER_ARM_SCRIPT, botasaurus_payload_path, botasaurus_out,
            timeout=ARM_TIMEOUT_S,
        )
        uwae = _run_arm(
            UWAE_BROWSER_ARM_SCRIPT, uwae_payload_path, uwae_out,
            timeout=ARM_TIMEOUT_S,
        )

        observations = fixture.observations()
        for p in (uwae_out, botasaurus_out, uwae_payload_path, botasaurus_payload_path):
            Path(p).unlink(missing_ok=True)
    Path(payload_path).unlink(missing_ok=True)

    botasaurus_rows = botasaurus.get("results", [])
    uwae_rows = uwae.get("results", [])

    checkpoint_after = _Checkpoint(CHECKPOINT_PATH)
    keys_after = set(checkpoint_after.rows.keys())
    checkpoint_stats = checkpoint_after.stats()
    checkpoint_stats["runs_reused"] = len(keys_before & keys_after)
    checkpoint_stats["runs_executed_this_invocation"] = len(keys_after - keys_before)

    uwae_summary = _summarise(uwae_rows)
    botasaurus_summary = _summarise(botasaurus_rows)

    def _cell(summary):
        # Key harus sama dengan yang dipakai ``comparison_outcome`` di
        # corpus_matrix: ``primary_success_runs`` (bukan ``primary_successes``).
        return {
            "runs": summary["runs"],
            "evaluated_runs": summary["runs"],
            "primary_success_runs": summary["primary_successes"],
            "untested_runs": 0,
        }

    from universal_web_acquisition.benchmark.corpus_matrix import comparison_outcome
    outcome = comparison_outcome(_cell(uwae_summary), _cell(botasaurus_summary))

    doc = {
        "schema_version": 1,
        "benchmark_id": BENCHMARK_ID,
        "supersedes": SUPERSEDES,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "timing": timing_evidence(
            list(botasaurus_rows) + list(uwae_rows),
            checkpoint_stats,
            time.perf_counter() - started,
            INTERRUPTION_GAP_THRESHOLD_S,
        ),
        "checkpoint": checkpoint_stats,
        "environment": {
            "interpreter": _interpreter_identity(),
            "pythonpath": COMPARISON_PYTHONPATH,
            "package_versions": _package_versions(),
            "fixture": "deterministic localhost POST-protocol fixture (fixture_post.py), port bebas per invocation",
            "browser": "chromium headless (/usr/bin/chromium) via CDP, port tetap per arm (9384/9385)",
            "method": (
                f"{RUNS} run per arm; kedua arm sebagai subprocess dari SATU interpreter "
                "dengan SATU PYTHONPATH, masing-masing meluncurkan chromium headless sendiri "
                "melawan SATU instance fixture"
            ),
            "identical_conditions": {
                "targets": True,
                "expected_outputs": True,
                "device_conditions": True,
                "run_counts": True,
                "success_criteria": True,
            },
            "submit_js_identical_for_both_arms": True,
        },
        "scenarios": [
            {
                "scenario_id": SCENARIO_ID,
                "page_path": PAGE_PATH,
                "target_path": TARGET_PATH,
                "primary_criterion": "acquisition",
                "ground_truth": {
                    "expect_status": truth["expect_status"],
                    "expect_body_sha256": hashlib.sha256(truth["body"]).hexdigest(),
                    "expect_body_bytes": len(truth["body"]),
                    "expect_request_body_sha256": truth["expect_body_sha256"],
                    "expect_request_body_bytes": truth["expect_body_bytes"],
                },
            }
        ],
        "summary": {
            "comparisons": [
                {
                    "scenario_id": SCENARIO_ID,
                    "criterion": "acquisition",
                    "uwae_arm": "uwae-browser",
                    "baseline_arm": "botasaurus-browser",
                    # Field WAJIB sesuai skema e16_like yang dibaca
                    # _slot_from_e16_like: runs + uwae_evaluated_runs +
                    # uwae_successes (BUKAN uwae.primary_success_runs).
                    "runs": uwae_summary["runs"],
                    "uwae_evaluated_runs": uwae_summary["runs"],
                    "uwae_successes": uwae_summary["primary_successes"],
                    "baseline_evaluated_runs": botasaurus_summary["runs"],
                    "baseline_successes": botasaurus_summary["primary_successes"],
                    "outcome": outcome,
                    "verdict": outcome,
                    "verdict_source": "explicit",
                    "evaluated_basis": "raw_rows",
                    "note": "POST dieksekusi lewat submit form HTML oleh kedua mesin browser.",
                }
            ],
            "uwae_summary": uwae_summary,
            "baseline_summary": botasaurus_summary,
            "interpretation": (
                "Pengukuran baseline POST via browser form — BUKAN klaim mengungguli. "
                "Slot ini ada karena E20 mendeklarasikan post_browser_arm sebagai celah terbuka."
            ),
            "runtime_failures": {
                "uwae-browser": uwae.get("runtime_failure"),
                "botasaurus-browser": botasaurus.get("runtime_failure"),
            },
        },
        "server_side_evidence": {
            "uwae-browser": _map_observations(uwae_rows, observations, invocation_id),
            "botasaurus-browser": _map_observations(botasaurus_rows, observations, invocation_id),
            "note": "Bukti dari log server: GET halaman form + POST ke target per run.",
        },
        "declared_gaps": CLOSED_BY_THIS_SLOT,
        "unsupported_scenarios": UNSUPPORTED_SCENARIOS,
    }

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"{'arm':22s} {'ok':>3s}/{'runs':<4s} {'med ms':>9s} {'page-GET':>9s} {'target-POST ok':>15s}")
    print("-" * 70)
    for arm_id, summary, rows in (
        ("uwae-browser", uwae_summary, uwae_rows),
        ("botasaurus-browser", botasaurus_summary, botasaurus_rows),
    ):
        srv = doc["server_side_evidence"][arm_id]
        med = summary["elapsed_ms_median"]
        print(
            f"{arm_id:22s} {summary['primary_successes']:>3d}/{summary['runs']:<4d} "
            f"{(f'{med:9.2f}' if med is not None else '        —')} "
            f"{srv['page_gets_observed']:>9d} {srv['target_posts_ok']:>7d}/{srv['target_posts_observed']:<7d}"
        )
    print(f"\nverdict: {outcome}")
    print(f"results -> {RESULTS_PATH}")


if __name__ == "__main__":
    main()
