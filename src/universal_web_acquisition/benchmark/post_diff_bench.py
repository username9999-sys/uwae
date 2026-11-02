"""E20 -- Differential lintas-implementasi untuk HTTP POST (UWAE vs Botasaurus).

Mandat INSTRUCTION.md G7 berlaku sama seperti benchmark E14/E18:

    "Use identical targets, expected outputs, device conditions, run counts,
     and success criteria for Botasaurus and the new engine."

Benchmark ini mengukur SATU hal yang sebelumnya tidak terukur sama sekali:
apakah kedua implementasi benar-benar dapat mengeksekusi permintaan HTTP
POST dengan body dan header. Matriks kompetitif mencatat Botasaurus
``Verified`` pada baris ``HTTP GET/POST requests`` sementara UWAE tidak punya
jalur POST sama sekali -- jadi slot ini mengukur celah paritas yang nyata,
bukan membandingkan fitur yang sudah ada di kedua sisi.

Prinsip yang dijaga
-------------------
- **Target identik**    -- URL, body, dan header yang sama persis untuk kedua
  arm; keduanya melawan SATU instance fixture POST.
- **Expected output identik** -- ground truth diturunkan dari SEMANTIK
  PROTOKOL FIXTURE (``fixture_post.py``): status dan body konstan per
  skenario. Engine yang diuji tidak pernah menulis di sana.
- **Device conditions identik** -- kedua arm adalah subprocess dari SATU
  interpreter dengan SATU PYTHONPATH. Konstanta lingkungan di-import dari
  ``cross_impl_bench`` (E14/E18), bukan disalin ulang, supaya keduanya
  benar-benar sama dan tidak bisa berbeda diam-diam.
- **Run count identik** -- RUNS per (arm, skenario) untuk keduanya.
- **Success criteria identik** -- rumus yang sama: ``status_code`` cocok dan
  ``sha256(body)`` cocok byte-for-byte.

Bukti sisi server
-----------------
Klaim arm ("saya mengirim POST") bukan bukti. Fixture mencatat setiap
request yang benar-benar arrive -- method, content-type, sha256 body, vonis
protokol. Evidence E20 memetakan observasi itu ke run yang tepat lewat
jendela waktu, sehingga bisa dipublikasikan: berapa POST yang benar-benar
tiba di server per arm, dan apakah ada run yang arm-nya bilang sukses
padahal server tidak melihat POST.

Yang TIDAK diklaim
------------------
Ini pengukuran baseline lintas-implementasi, BUKAN klaim UWAE mengungguli
Botasaurus. Selisih yang terukur dilaporkan apa adanya. Celah yang tersisa
(posisi multipart, redirect 307, POST pada arm browser) dinyatakan terbuka,
bukan disembunyikan.

Usage:
    PYTHONPATH=/root/botasaurus-venv/lib/python3.14/site-packages:src \\
        /root/uwae-comparison-venv/bin/python \\
        -m universal_web_acquisition.benchmark.post_diff_bench
"""

import hashlib
import json
import os
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from universal_web_acquisition.benchmark._checkpoint import (
    Checkpoint,
    timing_evidence,
)
from universal_web_acquisition.benchmark.cross_impl_bench import (
    ARM_TIMEOUT_S as _SHARED_ARM_TIMEOUT_S,
)
from universal_web_acquisition.benchmark.cross_impl_bench import (
    COMPARISON_PYTHON,
    COMPARISON_PYTHONPATH,
    _arm_env,
    _interpreter_identity,
    _median,
    _package_versions,
    _percentile,
    _percentile_note,
    _preflight,
    _run_arm,
)
from universal_web_acquisition.benchmark.fixture_post import (
    POST_GROUND_TRUTHS,
    POST_PROTOCOL,
    POST_SCENARIOS,
    PostFixtureServer,
    protocol_summary,
    request_headers,
)

# --------------------------------------------------------------------------
# Konfigurasi slot E20
# --------------------------------------------------------------------------

#: Jumlah run per (arm, skenario). Default 30 karena slot ini dibuat baru --
#: ambang minimal 30 pengulangan TEXT.md §6.3 sudah terpenuhi sejak awal,
#: tidak perlu backfill.
RUNS = int(os.environ.get("UWAE_E20_RUNS", "30"))

#: Lokasi evidence. Slot baru -- evidence lama tidak pernah ditimpa.
RESULTS_PATH = Path(
    os.environ.get(
        "UWAE_E20_RESULTS_PATH",
        "/root/universal-web-acquisition/docs/benchmark/engine-results-e20.json",
    )
)

#: Id benchmark. Slot ini mengukur DIMENSI BARU (``http-post``), jadi ia TIDAK
#: menggantikan slot mana pun -- E18 tetap aktif dan tetap dihitung.
BENCHMARK_ID = os.environ.get(
    "UWAE_E20_BENCHMARK_ID", "e20-http-post-differential-001"
)

#: Slot yang digantikan oleh evidence ini. Kosong untuk slot baru.
SUPERSEDES = [
    item.strip()
    for item in os.environ.get("UWAE_E20_SUPERSEDES", "").split(",")
    if item.strip()
]

#: Checkpoint per-run, ditulis di luar repo supaya tidak pernah ter-commit.
CHECKPOINT_PATH = Path(
    os.environ.get("UWAE_E20_CHECKPOINT", "/root/.qwen/tmp/e20_checkpoint.jsonl")
)

#: Timeout per arm (detik). Ada di fingerprint: mengubahnya mengubah hasil
#: pengukuran, jadi checkpoint lama tidak boleh dipakai.
ARM_TIMEOUT_S = _SHARED_ARM_TIMEOUT_S

#: Jeda antar-run yang dianggap INTERUPSI, bukan jeda normal.
INTERRUPTION_GAP_THRESHOLD_S = 60.0

#: Kriteria PRIMER per skenario. Satu rumus untuk kedua arm.
SCENARIO_CRITERION: Dict[str, str] = {
    sid: "acquisition" for sid in POST_SCENARIOS
}

SCENARIO_IDS: List[str] = list(POST_SCENARIOS)

#: Celah yang TIDAK diukur slot ini -- dinyatakan, bukan disembunyikan.
UNSUPPORTED_SCENARIOS: Dict[str, str] = {
    "post_multipart_form_data": (
        "POST multipart/form-data (upload berkas) tidak diukur. Fixture "
        "protokol POST E20 hanya mencakup application/x-www-form-urlencoded, "
        "application/json, body kosong, dan application/octet-stream."
    ),
    "post_redirect_307_preserves_method": (
        "Redirect 307/308 yang wajib mempertahankan method dan body tidak "
        "diukur. Fixture protokol POST E20 tidak punya route redirect, jadi "
        "perilaku library terhadap redirect POST tidak boleh diasumsikan."
    ),
    "post_browser_arm": (
        "POST pada arm browser tidak diukur. Slot ini adalah arm HTTP murni "
        "untuk kedua implementasi; arm browser punya mekanisme input yang "
        "berbeda dan tidak boleh disamakan dengan POST HTTP."
    ),
}


# --------------------------------------------------------------------------
# Skrip arm
# --------------------------------------------------------------------------
#
# Perbedaan dari E14/E18: request-nya POST, bukan GET. Sel Apartnya, bentuknya
# sama -- elapsed_ms diukur di luar (mencakup pembuatan session + permintaan
# + overhead framework), session/klient BARU per run, peak memory diukur per
# skenario lewat tracemalloc.

BOTASAURUS_POST_ARM_SCRIPT = r'''
import hashlib
import json
import os
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
    """Satu permintaan POST lewat API publik Botasaurus.

    ``session.post`` adalah jalur publik yang sama dengan ``session.get``
    yang dipakai E14/E18 -- jadi yang diukur di sini adalah POST pada
    implementasi yang sama, bukan API yang lebih longgar.

    Exception ditangkap DI DALAM task supaya teks kesalahannya terekam per
    item (Botasaurus dengan ``raise_exception=False`` menelan exception).
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
    scenario_peak = 0
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
        row["recorded_at"] = datetime.now(timezone.utc).isoformat(
            timespec="microseconds"
        )
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
            checkpoint.append(
                sc["id"], "botasaurus-request", row["run_index"], row
            )
_, process_peak = tracemalloc.get_traced_memory()
tracemalloc.stop()

with open(out_path, "w") as handle:
    json.dump(
        {
            "engine_id": "botasaurus-request",
            "peak_memory_bytes": process_peak,
            "arm_started_at": arm_started_at,
            "arm_finished_at": datetime.now(timezone.utc).isoformat(
                timespec="microseconds"
            ),
            "arm_started_epoch": arm_started_epoch,
            "arm_finished_epoch": time.time(),
            "results": results,
        },
        handle,
    )
'''


UWAE_POST_ARM_SCRIPT = r'''
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
storage = FilesystemArtifactStorage(base_path=tempfile.mkdtemp(prefix="uwae-e20-"))
# RetryPolicy DEFAULT (tidak disetel ulang): max_retries=3, backoff 1s --
# sama seperti arm UWAE di E14/E18 supaya perbandingan biaya tetap adil.
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
            job_id="e20-" + sc["id"] + "-" + str(run_index),
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
            # Respons 2xx yang AKHIRNYA ditolak tetap menghasilkan artifact --
            # byte-nya benar-benar diambil dan dipersistensi. Artifact itu
            # harus ikut diukur; hanya outcome job yang berbeda.
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
        row["recorded_at"] = datetime.now(timezone.utc).isoformat(
            timespec="microseconds"
        )
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
            "arm_finished_at": datetime.now(timezone.utc).isoformat(
                timespec="microseconds"
            ),
            "arm_started_epoch": arm_started_epoch,
            "arm_finished_epoch": time.time(),
            "results": results,
        },
        handle,
    )
'''


# --------------------------------------------------------------------------
# Sidik jari konfigurasi harness
# --------------------------------------------------------------------------


def _harness_fingerprint() -> str:
    """Sidik jari konfigurasi yang memengaruhi hasil pengukuran.

    Hanya MATERIAL pengukuran yang di-fingerprint: jumlah run, timeout, target,
    ground truth, protokol fixture, dan literal skrip arm. Lokasi berkas
    evidence dan id benchmark TIDAK ikut -- keduanya bukan bagian dari
    pengukuran, dan masukkannya akan membuat checkpoint lama tidak bisa
    dipakai hanya karena evidence dipindah.
    """
    material = {
        "runs": RUNS,
        "arm_timeout_s": ARM_TIMEOUT_S,
        "scenario_ids": SCENARIO_IDS,
        "scenario_paths": {sid: POST_SCENARIOS[sid] for sid in SCENARIO_IDS},
        "scenario_criterion": SCENARIO_CRITERION,
        "ground_truth_status": {
            sid: POST_GROUND_TRUTHS[sid]["expect_status"] for sid in SCENARIO_IDS
        },
        "ground_truth_body_sha256": {
            sid: hashlib.sha256(POST_GROUND_TRUTHS[sid]["body"]).hexdigest()
            for sid in SCENARIO_IDS
        },
        "ground_truth_request": {
            sid: {
                "content_type": POST_GROUND_TRUTHS[sid]["expect_content_type"],
                "headers": POST_GROUND_TRUTHS[sid]["expect_headers"],
                "body_sha256": POST_GROUND_TRUTHS[sid]["expect_body_sha256"],
                "body_bytes": POST_GROUND_TRUTHS[sid]["expect_body_bytes"],
            }
            for sid in SCENARIO_IDS
        },
        "post_protocol": {
            path: {
                "method": spec["method"],
                "content_type": spec["content_type"],
                "headers": spec["headers"],
                "body_sha256": hashlib.sha256(spec["body"]).hexdigest(),
                "body_bytes": len(spec["body"]),
                "ok_body_sha256": hashlib.sha256(spec["ok_body"]).hexdigest(),
            }
            for path, spec in POST_PROTOCOL.items()
        },
        "unsupported_scenarios": UNSUPPORTED_SCENARIOS,
        "botasaurus_arm_script": BOTASAURUS_POST_ARM_SCRIPT,
        "uwae_arm_script": UWAE_POST_ARM_SCRIPT,
    }
    payload = json.dumps(material, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class _Checkpoint(Checkpoint):
    """Checkpoint E20 -- sidik jari konfigurasi harness-nya sendiri."""

    def __init__(self, path: Path):
        super().__init__(path, _harness_fingerprint())


# --------------------------------------------------------------------------
# Penilaian
# --------------------------------------------------------------------------


def _scenario_rows(scenario_id: str, arm_rows: List[dict]) -> List[dict]:
    return [row for row in arm_rows if row.get("scenario_id") == scenario_id]


def _assess_run(scenario_id: str, row: dict) -> Dict:
    """Terapkan rumus kriteria yang SAMA pada kedua arm.

    Kriteria primer: status + body byte-for-byte cocok dengan ground truth
    protokol fixture. Tidak ada sumbu diagnosis di slot ini -- POST bukan
    skenario diagnosis, dan mengarang sumbu diagnosis untuknya hanya akan
    menghasilkan angka yang tidak bermakna.
    """
    truth = POST_GROUND_TRUTHS[scenario_id]
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
        return {
            "runs": 0,
            "primary_successes": 0,
            "primary_success_rate": None,
            "elapsed_ms_median": None,
            "elapsed_ms_p95": None,
            "elapsed_ms_min": None,
            "elapsed_ms_max": None,
            "elapsed_ms_runs": [],
            "peak_memory_bytes": None,
            "attempts_total": 0,
            "attempts_max": None,
            "acquisition_verified_runs": 0,
            "status_match_runs": 0,
            "body_match_runs": 0,
            "raw_signals": [],
            "errors": [],
        }
    assessed = [_assess_run(scenario_id, row) for row in rows]
    timings = [
        float(row["elapsed_ms"]) for row in rows if row.get("elapsed_ms") is not None
    ]
    attempts = [int(row.get("attempts") or 0) for row in rows]
    peaks = [int(row["peak_memory_bytes"]) for row in rows if row.get("peak_memory_bytes")]
    return {
        "runs": len(rows),
        "primary_successes": sum(1 for a in assessed if a["primary_success"]),
        "primary_success_rate": round(
            sum(1 for a in assessed if a["primary_success"]) / len(assessed), 4
        ),
        "elapsed_ms_median": round(_median(timings), 2) if timings else None,
        "elapsed_ms_p95": round(_percentile(timings, 0.95), 2) if timings else None,
        "elapsed_ms_min": round(min(timings), 2) if timings else None,
        "elapsed_ms_max": round(max(timings), 2) if timings else None,
        "elapsed_ms_runs": [round(t, 2) for t in timings],
        "peak_memory_bytes": max(peaks) if peaks else None,
        "attempts_total": sum(attempts),
        "attempts_max": max(attempts) if attempts else None,
        "acquisition_verified_runs": sum(
            1 for a in assessed if a["acquisition_verified"]
        ),
        "status_match_runs": sum(1 for a in assessed if a["status_match"]),
        "body_match_runs": sum(1 for a in assessed if a["body_match"]),
        "raw_signals": sorted({str(row.get("raw_signal")) for row in rows})[:5],
        "errors": sorted({str(row.get("error")) for row in rows if row.get("error")})[:5],
    }


# --------------------------------------------------------------------------
# Bukti sisi server
# --------------------------------------------------------------------------


def _map_observations(
    arm_rows: List[dict], observations: List[dict], invocation_id: str
) -> Dict:
    """Petakan observasi server ke run yang tepat, lalu ringkas.

    Run dieksekusi berurutan (satu per satu) dalam satu arm, jadi jendela
    [run_mulai, run_selesai] setiap run tidak saling tumpang tindih. Run
    yang diambil dari checkpoint TIDAK punya observasi -- dan itu memang
    benar: tidak ada request yang dikirim untuk run itu.

    Yang dipublikasikan:
    - ``runs_executed``       -- run yang benar-benar dieksekusi di invocation ini;
    - ``runs_with_observation`` -- run dengan tepat satu observasi server;
    - ``runs_without_observation`` -- run yang arm-nya tidak menghasilkan
      request yang terlihat di server (runtuh, atau klaim yang tidak didukung);
    - ``runs_with_multiple_observations`` -- run dengan lebih dari satu
      request (retry) -- dicatat, bukan dirata-rata.
    """
    executed = [
        row
        for row in arm_rows
        if row.get("invocation_id") == invocation_id and row.get("run_started_epoch")
    ]
    with_obs = 0
    without_obs = 0
    multiple = 0
    total_obs = 0
    matched_entries = []
    for row in executed:
        start = float(row["run_started_epoch"])
        end = float(row.get("recorded_epoch") or start)
        found = [
            entry
            for entry in observations
            if start <= float(entry["at_epoch"]) <= end
        ]
        total_obs += len(found)
        if len(found) == 1:
            with_obs += 1
            matched_entries.append(found[0])
        elif len(found) == 0:
            without_obs += 1
        else:
            multiple += 1
            matched_entries.extend(found)
    summary = protocol_summary(matched_entries)
    summary.update(
        {
            "runs_executed": len(executed),
            "runs_with_observation": with_obs,
            "runs_without_observation": without_obs,
            "runs_with_multiple_observations": multiple,
            "observations_matched_to_runs": total_obs,
            "attribution": (
                "Observasi server dipetakan ke run lewat jendela waktu "
                "[run_mulai, run_selesai]. Run dari checkpoint tidak punya "
                "observasi karena tidak ada request yang dikirim."
            ),
        }
    )
    return summary


def _server_side_consistency(arm_rows: List[dict], observations: List[dict]) -> Dict:
    """Cek bahwa observasi server sesuai dengan ground truth protokol.

    Run yang arm-nya melaporkan sukses TAPI server tidak melihat POST dengan
    body yang benar adalah bukti yang saling bertentangan. Kasus ini harus
    dipublikasikan, bukan dibiarkan begitu saja.
    """
    by_scenario: Dict[str, Dict[str, int]] = {}
    for entry in observations:
        path = entry.get("path")
        spec = POST_PROTOCOL.get(path)
        if spec is None:
            continue
        bucket = by_scenario.setdefault(
            path, {"observations": 0, "protocol_ok": 0, "protocol_violations": 0}
        )
        bucket["observations"] += 1
        if entry.get("protocol_verdict") == "ok":
            bucket["protocol_ok"] += 1
        else:
            bucket["protocol_violations"] += 1
    return {
        "by_path": by_scenario,
        "note": (
            "Penghitungan di atas memakai SELURUH observasi server pada "
            "invocation ini (semua arm), jadi angkanya adalah jumlah request "
            "yang benar-benar arrive -- bukan jumlah klaim arm."
        ),
    }


# --------------------------------------------------------------------------
# Benchmark utama
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
                    "url": base_url + POST_SCENARIOS[sid],
                    "path": POST_SCENARIOS[sid],
                    "body": POST_PROTOCOL[POST_SCENARIOS[sid]]["body"].decode("utf-8"),
                    "headers": request_headers(sid),
                }
                for sid in SCENARIO_IDS
            ],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(payload, handle)
            payload_path = handle.name

        botasaurus_out = payload_path + ".botasaurus.json"
        uwae_out = payload_path + ".uwae.json"
        # Urutan arm sama dengan E14/E18 (Botasaurus dulu, lalu UWAE) supaya
        # kondisi perangkat comparable dengan slot sebelumnya.
        botasaurus = _run_arm(
            BOTASAURUS_POST_ARM_SCRIPT,
            payload_path,
            botasaurus_out,
            timeout=ARM_TIMEOUT_S,
        )
        uwae = _run_arm(
            UWAE_POST_ARM_SCRIPT, payload_path, uwae_out, timeout=ARM_TIMEOUT_S
        )

        # Log server dibaca dari instance fixture yang sedang hidup. Snapshot
        # diambil SEBELUM fixture ditutup, karena setelah keluar dari blok
        # ``with`` server sudah berhenti dan lognya tidak bisa bertambah lagi.
        observations = fixture.observations()

        for path in (botasaurus_out, uwae_out):
            Path(path).unlink(missing_ok=True)
    Path(payload_path).unlink(missing_ok=True)

    botasaurus_rows = botasaurus.get("results", [])
    uwae_rows = uwae.get("results", [])

    scenarios_out = []
    for sid in SCENARIO_IDS:
        truth = POST_GROUND_TRUTHS[sid]
        scenarios_out.append(
            {
                "scenario_id": sid,
                "path": POST_SCENARIOS[sid],
                "primary_criterion": SCENARIO_CRITERION[sid],
                "ground_truth": {
                    "expect_status": truth["expect_status"],
                    "expect_body_sha256": hashlib.sha256(truth["body"]).hexdigest(),
                    "expect_body_bytes": len(truth["body"]),
                    "expect_content_type": truth["expect_content_type"],
                    "expect_headers": truth["expect_headers"],
                    "expect_request_body_sha256": truth["expect_body_sha256"],
                    "expect_request_body_bytes": truth["expect_body_bytes"],
                },
                "results": {
                    "uwae-engine": _summarise(sid, uwae_rows),
                    "botasaurus-request": _summarise(sid, botasaurus_rows),
                },
            }
        )

    unsupported = [
        {"scenario_id": sid, "reason": reason, "supported_by": []}
        for sid, reason in UNSUPPORTED_SCENARIOS.items()
    ]

    checkpoint_after = _Checkpoint(CHECKPOINT_PATH)
    keys_after = set(checkpoint_after.rows.keys())
    checkpoint_stats = checkpoint_after.stats()
    checkpoint_stats["runs_reused"] = len(keys_before & keys_after)
    checkpoint_stats["runs_executed_this_invocation"] = len(keys_after - keys_before)

    measured_rows: List[Dict] = list(botasaurus_rows) + list(uwae_rows)

    doc = {
        "schema_version": 1,
        "benchmark_id": BENCHMARK_ID,
        "supersedes": SUPERSEDES,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "timing": timing_evidence(
            measured_rows,
            checkpoint_stats,
            time.perf_counter() - started,
            INTERRUPTION_GAP_THRESHOLD_S,
        ),
        "checkpoint": checkpoint_stats,
        "environment": {
            "interpreter": _interpreter_identity(),
            "pythonpath": COMPARISON_PYTHONPATH,
            "package_versions": _package_versions(),
            "fixture": (
                "deterministic localhost POST-protocol fixture server "
                "(fixture_post.py); port bebas per invocation"
            ),
            "method": (
                f"{RUNS} run per (arm, skenario), koneksi baru setiap run; "
                "kedua arm sebagai subprocess dari SATU interpreter dengan SATU "
                "PYTHONPATH melawan SATU instance fixture POST"
            ),
            "identical_conditions": {
                "targets": True,
                "expected_outputs": True,
                "device_conditions": True,
                "run_counts": True,
                "success_criteria": True,
            },
            "memory_note": (
                "peak_memory_bytes = peak alokasi Python (tracemalloc); buffer C "
                "tidak dihitung (batasan yang sama dipakai benchmark transport E5)"
            ),
            "percentile_note": _percentile_note(RUNS),
            "user_agent_excluded_from_ground_truth": (
                "User-Agent tidak pernah menentukan respons fixture: curl_cffi "
                "meniru Chrome sedangkan requests bawaan Botasaurus memakai "
                "Firefox. User-Agent tetap dicatat di log sisi server sebagai "
                "bukti kondisi device."
            ),
        },
        "engines": [
            {
                "engine_id": "uwae-engine",
                "engine_name": "UWAE engine (JobWorker + ACP)",
                "engine_version": "uwae-0.3.0",
                "is_baseline": False,
                "description": (
                    "JobWorker + transport registry (curl_cffi primary) + classifier + "
                    "planner + artifact storage; job diserialisasi dengan method/body/"
                    "headers; RetryPolicy default (tidak disetel ulang)"
                ),
            },
            {
                "engine_id": "botasaurus-request",
                "engine_name": "Botasaurus @request (public API)",
                "engine_version": "botasaurus 4.0.97 / botasaurus_requests 4.0.38",
                "source_commit": "6c9260de12d71b9dc0c3b3a019d2698a9af38433",
                "is_baseline": True,
                "description": (
                    "Dekorator @request publik dengan session.post(url, data=bytes, "
                    "headers=...): output=None, create_error_logs=False, "
                    "raise_exception=False, close_on_crash=True, cache=False "
                    "(semua default Botasaurus kecuali tiga yang eksplisit disebut)"
                ),
            },
        ],
        "scenarios": scenarios_out,
        "server_side_evidence": {
            "uwae-engine": _map_observations(uwae_rows, observations, invocation_id),
            "botasaurus-request": _map_observations(
                botasaurus_rows, observations, invocation_id
            ),
            "all_arms": _server_side_consistency(
                measured_rows, observations
            ),
            "note": (
                "Bukti ini berasal dari log server, bukan dari klaim arm: "
                "setiap request yang benar-benar arrive dicatat bersama method, "
                "content-type, sha256 body, dan vonis protokol."
            ),
        },
        "unsupported_scenarios": unsupported,
        "summary": {
            "interpretation": (
                "PENGUKURAN BASELINE lintas-implementasi untuk kapabilitas HTTP "
                "POST -- BUKAN klaim UWAE mengungguli Botasaurus. Ini slot "
                "PERTAMA yang mengukur POST di kedua implementasi; sebelum ini "
                "baris matriks 'HTTP GET/POST requests' tidak punya bukti UWAE "
                "sama sekali. Selisih yang terukur dilaporkan apa adanya."
            ),
            "acquisition_verified_runs": {
                "uwae-engine": sum(
                    1
                    for sid in SCENARIO_IDS
                    for row in _scenario_rows(sid, uwae_rows)
                    if _assess_run(sid, row)["acquisition_verified"]
                ),
                "botasaurus-request": sum(
                    1
                    for sid in SCENARIO_IDS
                    for row in _scenario_rows(sid, botasaurus_rows)
                    if _assess_run(sid, row)["acquisition_verified"]
                ),
                "total_runs_per_arm": len(SCENARIO_IDS) * RUNS,
            },
            "primary_success_runs": {
                "uwae-engine": sum(
                    1
                    for sid in SCENARIO_IDS
                    for row in _scenario_rows(sid, uwae_rows)
                    if _assess_run(sid, row)["primary_success"]
                ),
                "botasaurus-request": sum(
                    1
                    for sid in SCENARIO_IDS
                    for row in _scenario_rows(sid, botasaurus_rows)
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
    RESULTS_PATH.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    header = (
        f"{'scenario':22s} {'arm':22s} {'ok':>3s} {'med ms':>9s} "
        f"{'p95 ms':>9s} {'att':>4s} {'srv-obs':>8s}"
    )
    print(header)
    print("-" * len(header))
    for entry in scenarios_out:
        for arm_id in ("uwae-engine", "botasaurus-request"):
            summary = entry["results"][arm_id]
            median = summary["elapsed_ms_median"]
            p95 = summary["elapsed_ms_p95"]
            srv = doc["server_side_evidence"][arm_id]
            print(
                f"{entry['scenario_id']:22s} {arm_id:22s} "
                f"{summary['primary_successes']:>3d} "
                f"{(f'{median:9.2f}' if median is not None else '        —')} "
                f"{(f'{p95:9.2f}' if p95 is not None else '        —')} "
                f"{summary['attempts_max'] if summary['attempts_max'] is not None else '—':>4} "
                f"{srv['runs_with_observation']:>8d}"
            )
    print()
    for arm_id, block in doc["server_side_evidence"].items():
        if not isinstance(block, dict) or "runs_executed" not in block:
            continue
        print(
            f"sisi-server {arm_id:22s} observasi={block['observations']} "
            f"method={block['methods_observed']} "
            f"vonis={block['protocol_verdicts']} "
            f"run+obs={block['runs_with_observation']}/"
            f"{block['runs_executed']} "
            f"tanpa-obs={block['runs_without_observation']}"
        )
    print(f"\nresults -> {RESULTS_PATH}")


if __name__ == "__main__":
    main()
