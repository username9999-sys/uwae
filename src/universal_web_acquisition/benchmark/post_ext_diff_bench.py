"""E21 -- Differential lintas-implementasi untuk ekstensi protokol POST (UWAE vs Botasaurus).

Menutup dua dari tiga celah OPEN yang dideklarasikan E20:

- ``post_multipart_form_data``  -> skenario ``p05_post_multipart``
- ``post_redirect_307_preserves_method`` -> skenario ``p06_post_redirect307``

(Celah ketiga, ``post_browser_arm``, ditangani slot terpisah E22 pada arm
browser — modul ini sengaja hanya arm HTTP supaya perbandingan tetap
"kedua implementasi sebagai klien HTTP" seperti E20.)

Protokol fairness identik dengan E20/E18 (INSTRUCTION.md G7): target identik,
expected output identik (ground truth dari semantik protokol fixture, bukan
echo), device conditions identik (kedua arm sebagai subprocess dari SATU
interpreter dengan SATU PYTHONPATH), run count identik (n=30), success
criteria identik (status + sha256(body) byte-for-byte).

Yang spesifik di slot ini:

- **Multipart dibandingkan byte-for-byte.** Body yang benar harus sama persis
  dengan konstanta ``MULTIPART_BODY`` (boundary ``----uwae-post-fixture-boundary-7d1a``
  ikut diuji), jadi arm yang membangun multipart dengan boundary acak atau
  urutan field berbeda akan gagal — itu memang yang ingin diukur.
- **Redirect 307 mensyaratkan method+body dipertahankan.** Ground truth adalah
  respons AKHIR (200 + ``REDIRECT_OK_BODY``); observasi server membuktikan
  dua hop (POST /post/redirect307 -> 307, lalu POST /post/redirect-target
  -> 200). Arm yang mengubah POST menjadi GET setelah 307 akan menerima
  405 dari target dan gagal.

Usage:
    PYTHONPATH=/root/botasaurus-venv/lib/python3.14/site-packages:src \\
        /root/uwae-comparison-venv/bin/python \\
        -m universal_web_acquisition.benchmark.post_ext_diff_bench
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
    ARM_TIMEOUT_S as _SHARED_ARM_TIMEOUT_S,
)
from universal_web_acquisition.benchmark.cross_impl_bench import (
    COMPARISON_PYTHONPATH,
    _interpreter_identity,
    _median,
    _package_versions,
    _percentile,
    _percentile_note,
    _preflight,
    _run_arm,
)
from universal_web_acquisition.benchmark.fixture_post import (
    POST_EXT_GROUND_TRUTHS,
    POST_EXT_SCENARIOS,
    POST_PROTOCOL,
    PostFixtureServer,
    ext_request_headers,
    protocol_summary,
)

# --------------------------------------------------------------------------
# Konfigurasi slot E21
# --------------------------------------------------------------------------

RUNS = int(os.environ.get("UWAE_E21_RUNS", "30"))

RESULTS_PATH = Path(
    os.environ.get(
        "UWAE_E21_RESULTS_PATH",
        "/root/universal-web-acquisition/docs/benchmark/engine-results-e21.json",
    )
)

BENCHMARK_ID = os.environ.get(
    "UWAE_E21_BENCHMARK_ID", "e21-http-post-ext-differential-001"
)

#: Slot baru — tidak menggantikan apa pun. E20 tetap aktif.
SUPERSEDES: List[str] = [
    item.strip()
    for item in os.environ.get("UWAE_E21_SUPERSEDES", "").split(",")
    if item.strip()
]

CHECKPOINT_PATH = Path(
    os.environ.get("UWAE_E21_CHECKPOINT", "/root/.qwen/tmp/e21_checkpoint.jsonl")
)

ARM_TIMEOUT_S = _SHARED_ARM_TIMEOUT_S

INTERRUPTION_GAP_THRESHOLD_S = 60.0

SCENARIO_CRITERION: Dict[str, str] = {sid: "acquisition" for sid in POST_EXT_SCENARIOS if sid != "p07_post_browser_form"}

#: Hanya skenario HTTP di slot ini; p07 (browser) milik E22.
SCENARIO_IDS: List[str] = [sid for sid in POST_EXT_SCENARIOS if sid != "p07_post_browser_form"]

#: Celah yang ditutup slot ini — dipublikasikan sebagai declared_gaps dengan
#: status akan di-override oleh DECLARED_GAP_CLOSURES di corpus_matrix.
CLOSED_BY_THIS_SLOT = [
    {
        "scenario_id": "post_multipart_form_data",
        "reason": (
            "E20 hanya mengukur urlencoded/JSON/empty/octet-stream. E21 "
            "mengukur multipart/form-data byte-for-byte terhadap konstanta "
            "MULTIPART_BODY (boundary ikut diuji)."
        ),
    },
    {
        "scenario_id": "post_redirect_307_preserves_method",
        "reason": (
            "E20 tidak punya route redirect. E21 mengukur apakah method dan "
            "body POST dipertahankan setelah redirect 307 (ground truth = "
            "respons akhir 200; observasi server membuktikan dua hop)."
        ),
    },
]

#: Celah yang masih TIDAK diukur slot ini — dipublikasikan apa adanya.
UNSUPPORTED_SCENARIOS = [
    {
        "scenario_id": "post_browser_arm",
        "reason": (
            "POST pada arm browser tidak diukur di slot E21 (arm HTTP saja). "
            "Ditangani slot E22."
        ),
        "supported_by": ["E22"],
    },
]


# --------------------------------------------------------------------------
# Skrip arm — pola sama dengan E20, body mentah dikirim apa adanya
# --------------------------------------------------------------------------

BOTASAURUS_EXT_ARM_SCRIPT = r'''
import hashlib
import json
import sys
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path

payload = json.load(open(sys.argv[1]))
out_path = sys.argv[2]

from botasaurus.request_decorator import request
from universal_web_acquisition.benchmark._checkpoint import Checkpoint


@request(
    output=None,
    create_error_logs=False,
    raise_exception=False,
    close_on_crash=True,
    cache=False,
)
def acquire(session, item):
    """Satu permintaan POST ekstensi lewat API publik Botasaurus.

    ``session.post(url, data=bytes, headers=...)`` — body mentah dikirim apa
    adanya, jadi multipart byte-for-byte dan perilaku redirect 307 diukur
    apa adanya oleh library, bukan oleh kode khusus benchmark.
    """
    try:
        r = session.post(
            item["url"],
            data=item["body"].encode("utf-8"),
            headers=item["headers"],
            timeout=15,
        )
        content = r.content
        return {
            "status_code": r.status_code,
            "body_sha256": hashlib.sha256(content).hexdigest(),
            "body_bytes": len(content),
            "content_type": r.headers.get("content-type", ""),
            "final_url": r.url,
        }
    except Exception as exc:
        return {"error": (type(exc).__name__ + ": " + str(exc))[:300]}


arm_started_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
arm_started_epoch = time.time()
results = []
tracemalloc.start()
checkpoint = Checkpoint(Path(payload["checkpoint_path"]), payload["fingerprint"])
for sc in payload["scenarios"]:
    tracemalloc.reset_peak()
    for run_index in range(payload["runs"]):
        cached = checkpoint.get(sc["id"], "botasaurus-request", run_index)
        if cached is not None:
            results.append(cached)
            continue
        run_started_epoch = time.time()
        t0 = time.perf_counter()
        outcome = acquire(
            [
                {
                    "url": sc["url"],
                    "body": sc["body"],
                    "headers": sc["headers"],
                }
            ]
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000
        row = dict(outcome[0]) if outcome and isinstance(outcome[0], dict) else {}
        row["scenario_id"] = sc["id"]
        row["run_index"] = run_index
        row["elapsed_ms"] = round(elapsed_ms, 2)
        row["attempts"] = 1
        row["request_method"] = "POST"
        row["raw_signal"] = (
            "status " + str(row["status_code"])
            if "status_code" in row
            else row.get("error", "")
        )
        row["recorded_at"] = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        row["run_started_epoch"] = run_started_epoch
        row["recorded_epoch"] = time.time()
        row["fixture_base_url"] = payload["base_url"]
        row["invocation_id"] = payload["invocation_id"]
        checkpoint.append(sc["id"], "botasaurus-request", run_index, row)
        results.append(row)
    _, scenario_peak = tracemalloc.get_traced_memory()
    for row in results:
        if row["scenario_id"] == sc["id"] and "peak_memory_bytes" not in row:
            row["peak_memory_bytes"] = scenario_peak
            checkpoint.append(sc["id"], "botasaurus-request", row["run_index"], row)
_, process_peak = tracemalloc.get_traced_memory()
tracemalloc.stop()

with open(out_path, "w") as handle:
    json.dump(
        {
            "engine_id": "botasaurus-request",
            "peak_memory_bytes": process_peak,
            "arm_started_at": arm_started_at,
            "arm_finished_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
            "arm_started_epoch": arm_started_epoch,
            "arm_finished_epoch": time.time(),
            "results": results,
        },
        handle,
    )
'''


UWAE_EXT_ARM_SCRIPT = r'''
import asyncio
import hashlib
import json
import os
import sys
import tempfile
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path

payload = json.load(open(sys.argv[1]))
out_path = sys.argv[2]

from universal_web_acquisition.artifact.storage import FilesystemArtifactStorage
from universal_web_acquisition.benchmark._checkpoint import Checkpoint
from universal_web_acquisition.core.job_model import Job
from universal_web_acquisition.core.job_repository import JobRepository
from universal_web_acquisition.core.job_worker import JobWorker

repo = JobRepository()
fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(fd)
repo.db_path = db_path
repo._init_db()
storage = FilesystemArtifactStorage(base_path=tempfile.mkdtemp(prefix="uwae-e21-"))
worker = JobWorker(repo, scheduler=None, storage=storage, measure_memory=True)


def last_assessment(job_id):
    for event in reversed(repo.list_events(job_id)):
        if event["event"] == "assessment":
            return json.loads(event["detail"])
    return {}


arm_started_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
arm_started_epoch = time.time()
results = []
tracemalloc.start()
checkpoint = Checkpoint(Path(payload["checkpoint_path"]), payload["fingerprint"])
for sc in payload["scenarios"]:
    tracemalloc.reset_peak()
    for run_index in range(payload["runs"]):
        cached = checkpoint.get(sc["id"], "uwae-engine", run_index)
        if cached is not None:
            results.append(cached)
            continue
        job = Job(
            job_id="e21-" + sc["id"] + "-" + str(run_index),
            url=sc["url"],
            method="POST",
            body=sc["body"].encode("utf-8"),
            headers=sc["headers"],
        )
        repo.save_job(job)
        run_started_epoch = time.time()
        t0 = time.perf_counter()
        asyncio.run(worker._execute_job(job))
        elapsed_ms = (time.perf_counter() - t0) * 1000
        final = repo.get_job(job.job_id)
        assessment = last_assessment(job.job_id)
        row = {
            "scenario_id": sc["id"],
            "run_index": run_index,
            "elapsed_ms": round(elapsed_ms, 2),
            "job_status": final.status.value,
            "job_error": final.error,
            "attempts": len(repo.list_attempts(job.job_id)),
            "observed_diagnosis": assessment.get("state"),
            "reason_code": assessment.get("reason_code"),
            "signals": assessment.get("signals") or [],
            "request_method": "POST",
            "raw_signal": assessment.get("state") or final.error or final.status.value,
        }
        if final.status.value == "succeeded" and final.artifact_id:
            artifact = asyncio.run(storage.retrieve(final.artifact_id))
            if artifact is not None:
                row["status_code"] = artifact.status_code
                row["body_sha256"] = hashlib.sha256(artifact.content).hexdigest()
                row["body_bytes"] = len(artifact.content)
                row["content_type"] = artifact.content_type
                row["artifact_id"] = final.artifact_id
        else:
            for attempt in repo.list_attempts(job.job_id):
                artifact_id = attempt.get("artifact_id")
                if not artifact_id:
                    continue
                artifact = asyncio.run(storage.retrieve(artifact_id))
                if artifact is None:
                    continue
                row["status_code"] = artifact.status_code
                row["body_sha256"] = hashlib.sha256(artifact.content).hexdigest()
                row["body_bytes"] = len(artifact.content)
                row["content_type"] = artifact.content_type
                row["artifact_id"] = artifact_id
                break
        row["recorded_at"] = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        row["run_started_epoch"] = run_started_epoch
        row["recorded_epoch"] = time.time()
        row["fixture_base_url"] = payload["base_url"]
        row["invocation_id"] = payload["invocation_id"]
        checkpoint.append(sc["id"], "uwae-engine", run_index, row)
        results.append(row)
    _, scenario_peak = tracemalloc.get_traced_memory()
    for row in results:
        if row["scenario_id"] == sc["id"] and "peak_memory_bytes" not in row:
            row["peak_memory_bytes"] = scenario_peak
            checkpoint.append(sc["id"], "uwae-engine", row["run_index"], row)
_, process_peak = tracemalloc.get_traced_memory()
tracemalloc.stop()

with open(out_path, "w") as handle:
    json.dump(
        {
            "engine_id": "uwae-engine",
            "peak_memory_bytes": process_peak,
            "arm_started_at": arm_started_at,
            "arm_finished_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
            "arm_started_epoch": arm_started_epoch,
            "arm_finished_epoch": time.time(),
            "results": results,
        },
        handle,
    )
'''


# --------------------------------------------------------------------------
# Fingerprint
# --------------------------------------------------------------------------


def _harness_fingerprint() -> str:
    material = {
        "runs": RUNS,
        "arm_timeout_s": ARM_TIMEOUT_S,
        "scenario_ids": SCENARIO_IDS,
        "scenario_paths": {sid: POST_EXT_SCENARIOS[sid] for sid in SCENARIO_IDS},
        "scenario_criterion": SCENARIO_CRITERION,
        "ground_truth_status": {
            sid: POST_EXT_GROUND_TRUTHS[sid]["expect_status"] for sid in SCENARIO_IDS
        },
        "ground_truth_body_sha256": {
            sid: hashlib.sha256(POST_EXT_GROUND_TRUTHS[sid]["body"]).hexdigest()
            for sid in SCENARIO_IDS
        },
        "ground_truth_request": {
            sid: {
                "content_type": POST_EXT_GROUND_TRUTHS[sid]["expect_content_type"],
                "headers": POST_EXT_GROUND_TRUTHS[sid]["expect_headers"],
                "body_sha256": POST_EXT_GROUND_TRUTHS[sid]["expect_body_sha256"],
                "body_bytes": POST_EXT_GROUND_TRUTHS[sid]["expect_body_bytes"],
            }
            for sid in SCENARIO_IDS
        },
        "redirect_chain": POST_EXT_GROUND_TRUTHS["p06_post_redirect307"].get("redirect_chain"),
        "closed_by_this_slot": CLOSED_BY_THIS_SLOT,
        "unsupported_scenarios": UNSUPPORTED_SCENARIOS,
        "botasaurus_arm_script": BOTASAURUS_EXT_ARM_SCRIPT,
        "uwae_arm_script": UWAE_EXT_ARM_SCRIPT,
    }
    payload = json.dumps(material, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class _Checkpoint(Checkpoint):
    def __init__(self, path: Path):
        super().__init__(path, _harness_fingerprint())


# --------------------------------------------------------------------------
# Penilaian
# --------------------------------------------------------------------------


def _scenario_rows(scenario_id: str, arm_rows: List[dict]) -> List[dict]:
    return [row for row in arm_rows if row.get("scenario_id") == scenario_id]


def _assess_run(scenario_id: str, row: dict) -> Dict:
    truth = POST_EXT_GROUND_TRUTHS[scenario_id]
    expect_sha = hashlib.sha256(truth["body"]).hexdigest()
    status_ok = row.get("status_code") == truth["expect_status"]
    body_ok = row.get("body_sha256") == expect_sha
    return {
        "acquisition_verified": bool(status_ok and body_ok),
        "status_match": bool(status_ok),
        "body_match": bool(body_ok),
        "primary_criterion": SCENARIO_CRITERION[scenario_id],
        "primary_success": bool(status_ok and body_ok),
    }


def _summarise(scenario_id: str, arm_rows: List[dict]) -> Dict:
    rows = _scenario_rows(scenario_id, arm_rows)
    if not rows:
        return {"runs": 0, "primary_successes": 0, "primary_success_rate": None,
                "elapsed_ms_median": None, "elapsed_ms_p95": None,
                "elapsed_ms_min": None, "elapsed_ms_max": None,
                "elapsed_ms_runs": [], "peak_memory_bytes": None,
                "attempts_total": 0, "attempts_max": None,
                "acquisition_verified_runs": 0, "status_match_runs": 0,
                "body_match_runs": 0, "raw_signals": [], "errors": []}
    assessed = [_assess_run(scenario_id, row) for row in rows]
    timings = [float(r["elapsed_ms"]) for r in rows if r.get("elapsed_ms") is not None]
    attempts = [int(r.get("attempts") or 0) for r in rows]
    peaks = [int(r["peak_memory_bytes"]) for r in rows if r.get("peak_memory_bytes")]
    return {
        "runs": len(rows),
        "primary_successes": sum(1 for a in assessed if a["primary_success"]),
        "primary_success_rate": round(sum(1 for a in assessed if a["primary_success"]) / len(assessed), 4),
        "elapsed_ms_median": round(_median(timings), 2) if timings else None,
        "elapsed_ms_p95": round(_percentile(timings, 0.95), 2) if timings else None,
        "elapsed_ms_min": round(min(timings), 2) if timings else None,
        "elapsed_ms_max": round(max(timings), 2) if timings else None,
        "elapsed_ms_runs": [round(t, 2) for t in timings],
        "peak_memory_bytes": max(peaks) if peaks else None,
        "attempts_total": sum(attempts),
        "attempts_max": max(attempts) if attempts else None,
        "acquisition_verified_runs": sum(1 for a in assessed if a["acquisition_verified"]),
        "status_match_runs": sum(1 for a in assessed if a["status_match"]),
        "body_match_runs": sum(1 for a in assessed if a["body_match"]),
        "raw_signals": sorted({str(r.get("raw_signal")) for r in rows})[:5],
        "errors": sorted({str(r.get("error")) for r in rows if r.get("error")})[:5],
    }


def _map_observations(arm_rows: List[dict], observations: List[dict], invocation_id: str) -> Dict:
    executed = [
        row for row in arm_rows
        if row.get("invocation_id") == invocation_id and row.get("run_started_epoch")
    ]
    with_obs = 0
    without_obs = 0
    multiple = 0
    matched = []
    for row in executed:
        start = float(row["run_started_epoch"])
        end = float(row.get("recorded_epoch") or start)
        found = [e for e in observations if start <= float(e["at_epoch"]) <= end]
        if len(found) == 1:
            with_obs += 1
            matched.append(found[0])
        elif len(found) == 0:
            without_obs += 1
        else:
            multiple += 1
            matched.extend(found)
    summary = protocol_summary(matched)
    summary.update({
        "runs_executed": len(executed),
        "runs_with_observation": with_obs,
        "runs_without_observation": without_obs,
        "runs_with_multiple_observations": multiple,
        "attribution": "Observasi server dipetakan ke run lewat jendela waktu [run_mulai, run_selesai].",
    })
    return summary


def _redirect_hop_evidence(observations: List[dict]) -> Dict:
    """Bukti dua hop untuk skenario redirect: 307 lalu 200 pada target.

    Dihitung dari SELURUH observasi server (kedua arm), karena hop itu
    memang terjadi dua kali per run yang berhasil.
    """
    hops = [e for e in observations if e.get("path") in ("/post/redirect307", "/post/redirect-target")]
    by_path: Dict[str, Dict[str, int]] = {}
    for e in hops:
        b = by_path.setdefault(e["path"], {"observations": 0, "status_307": 0, "status_200": 0, "verdict_ok": 0})
        b["observations"] += 1
        if e.get("status") == 307:
            b["status_307"] += 1
        if e.get("status") == 200:
            b["status_200"] += 1
        if e.get("protocol_verdict") == "ok":
            b["verdict_ok"] += 1
    return {
        "by_path": by_path,
        "note": (
            "Redirect 307 yang benar menghasilkan tepat dua observasi per run: "
            "POST /post/redirect307 (status 307, verdict redirect_issued) lalu "
            "POST /post/redirect-target (status 200, verdict ok). Kalau klien "
            "mengubah method menjadi GET setelah 307, target akan membalas 405."
        ),
    }


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def main() -> None:
    _preflight()
    started = time.perf_counter()
    invocation_id = uuid.uuid4().hex

    checkpoint = _Checkpoint(CHECKPOINT_PATH)
    keys_before = set(checkpoint.rows.keys())

    fixture = PostFixtureServer()
    with fixture as base_url:
        payload = {
            "runs": RUNS,
            "base_url": base_url,
            "checkpoint_path": str(CHECKPOINT_PATH),
            "fingerprint": checkpoint.fingerprint,
            "invocation_id": invocation_id,
            "scenarios": [
                {
                    "id": sid,
                    "url": base_url + POST_EXT_SCENARIOS[sid],
                    "path": POST_EXT_SCENARIOS[sid],
                    "body": POST_PROTOCOL[POST_EXT_SCENARIOS[sid]]["body"].decode("utf-8"),
                    "headers": ext_request_headers(sid),
                }
                for sid in SCENARIO_IDS
            ],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(payload, handle)
            payload_path = handle.name

        botasaurus_out = payload_path + ".botasaurus.json"
        uwae_out = payload_path + ".uwae.json"
        botasaurus = _run_arm(BOTASAURUS_EXT_ARM_SCRIPT, payload_path, botasaurus_out, timeout=ARM_TIMEOUT_S)
        uwae = _run_arm(UWAE_EXT_ARM_SCRIPT, payload_path, uwae_out, timeout=ARM_TIMEOUT_S)

        observations = fixture.observations()
        for path in (botasaurus_out, uwae_out):
            Path(path).unlink(missing_ok=True)
    Path(payload_path).unlink(missing_ok=True)

    botasaurus_rows = botasaurus.get("results", [])
    uwae_rows = uwae.get("results", [])

    scenarios_out = []
    for sid in SCENARIO_IDS:
        truth = POST_EXT_GROUND_TRUTHS[sid]
        scenarios_out.append({
            "scenario_id": sid,
            "path": POST_EXT_SCENARIOS[sid],
            "primary_criterion": SCENARIO_CRITERION[sid],
            "ground_truth": {
                "expect_status": truth["expect_status"],
                "expect_body_sha256": hashlib.sha256(truth["body"]).hexdigest(),
                "expect_body_bytes": len(truth["body"]),
                "expect_content_type": truth["expect_content_type"],
                "expect_headers": truth["expect_headers"],
                "expect_request_body_sha256": truth["expect_body_sha256"],
                "expect_request_body_bytes": truth["expect_body_bytes"],
                "redirect_chain": truth.get("redirect_chain"),
            },
            "results": {
                "uwae-engine": _summarise(sid, uwae_rows),
                "botasaurus-request": _summarise(sid, botasaurus_rows),
            },
        })

    checkpoint_after = _Checkpoint(CHECKPOINT_PATH)
    keys_after = set(checkpoint_after.rows.keys())
    checkpoint_stats = checkpoint_after.stats()
    checkpoint_stats["runs_reused"] = len(keys_before & keys_after)
    checkpoint_stats["runs_executed_this_invocation"] = len(keys_after - keys_before)

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
            "method": (
                f"{RUNS} run per (arm, skenario); kedua arm sebagai subprocess dari SATU "
                "interpreter dengan SATU PYTHONPATH melawan SATU instance fixture POST"
            ),
            "identical_conditions": {
                "targets": True,
                "expected_outputs": True,
                "device_conditions": True,
                "run_counts": True,
                "success_criteria": True,
            },
            "memory_note": "peak_memory_bytes = peak alokasi Python (tracemalloc); buffer C tidak dihitung",
            "percentile_note": _percentile_note(RUNS),
        },
        "engines": [
            {
                "engine_id": "uwae-engine",
                "engine_name": "UWAE engine (JobWorker + ACP)",
                "engine_version": "uwae-0.3.0",
                "is_baseline": False,
                "description": "JobWorker + transport registry (curl_cffi primary); job POST dengan body mentah + header eksplisit",
            },
            {
                "engine_id": "botasaurus-request",
                "engine_name": "Botasaurus @request (public API)",
                "engine_version": "botasaurus 4.0.97 / botasaurus_requests 4.0.38",
                "is_baseline": True,
                "description": "session.post(url, data=bytes, headers=...) — body mentah dikirim apa adanya",
            },
        ],
        "scenarios": scenarios_out,
        "server_side_evidence": {
            "uwae-engine": _map_observations(uwae_rows, observations, invocation_id),
            "botasaurus-request": _map_observations(botasaurus_rows, observations, invocation_id),
            "redirect_hops": _redirect_hop_evidence(observations),
            "note": "Bukti dari log server, bukan klaim arm.",
        },
        # declared_gaps di sini adalah celah yang DITUTUP slot ini; korpus
        # akan meng-override statusnya via DECLARED_GAP_CLOSURES.
        "declared_gaps": CLOSED_BY_THIS_SLOT,
        "unsupported_scenarios": UNSUPPORTED_SCENARIOS,
        "summary": {
            "interpretation": (
                "Pengukuran baseline untuk ekstensi protokol POST (multipart byte-exact, "
                "redirect 307 preserve method) — BUKAN klaim mengungguli. Slot ini ada "
                "karena E20 mendeklarasikan kedua skenario ini sebagai celah terbuka."
            ),
            "primary_success_runs": {
                "uwae-engine": sum(
                    1 for sid in SCENARIO_IDS for row in _scenario_rows(sid, uwae_rows)
                    if _assess_run(sid, row)["primary_success"]
                ),
                "botasaurus-request": sum(
                    1 for sid in SCENARIO_IDS for row in _scenario_rows(sid, botasaurus_rows)
                    if _assess_run(sid, row)["primary_success"]
                ),
                "total_runs_per_arm": len(SCENARIO_IDS) * RUNS,
            },
            "runtime_failures": {
                "uwae-engine": uwae.get("runtime_failure"),
                "botasaurus-request": botasaurus.get("runtime_failure"),
            },
        },
    }

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")

    header = f"{'scenario':26s} {'arm':22s} {'ok':>3s} {'med ms':>9s} {'srv-obs':>8s}"
    print(header)
    print("-" * len(header))
    for entry in scenarios_out:
        for arm_id in ("uwae-engine", "botasaurus-request"):
            s = entry["results"][arm_id]
            med = s["elapsed_ms_median"]
            srv = doc["server_side_evidence"][arm_id]
            print(
                f"{entry['scenario_id']:26s} {arm_id:22s} {s['primary_successes']:>3d} "
                f"{(f'{med:9.2f}' if med is not None else '        —')} "
                f"{srv['runs_with_observation']:>8d}"
            )
    print()
    rh = doc["server_side_evidence"]["redirect_hops"]["by_path"]
    for path, b in rh.items():
        print(f"hop {path:24s} obs={b['observations']} 307={b['status_307']} 200={b['status_200']} ok={b['verdict_ok']}")
    print(f"\nresults -> {RESULTS_PATH}")


if __name__ == "__main__":
    main()
