"""E14 — Differential lintas-implementasi: UWAE vs Botasaurus (interpreter identik).

Mandat INSTRUCTION.md G7 mensyaratkan perbandingan yang bisa direproduksi:

    "Use identical targets, expected outputs, device conditions, run counts,
     and success criteria for Botasaurus and the new engine."

Benchmark ini memenuhi kelima syarat itu:

- **target**        — daftar skenario fixture yang sama persis untuk kedua arm;
- **expected output** — ground truth dari SEMANTIK FIXTURE (bukan dari engine
  yang diuji): status + body byte-for-byte + label diagnosis;
- **device conditions** — kedua arm berjalan sebagai SUBPROSES dari SATU
  interpreter (``/root/uwae-comparison-venv/bin/python``, glibc aarch64) dengan
  SATU PYTHONPATH, melawan SATU instance fixture server;
- **run counts**    — jumlah run per (arm, skenario) sama untuk keduanya;
- **success criteria** — rumus penilaian yang sama persis diterapkan pada
  keluaran kedua arm.

Yang TIDAK boleh dilupakan (mandat INSTRUCTION.md): ini **pengukuran
baseline**, bukan klaim mengungguli Botasaurus. Selisih yang terukur
dilaporkan apa adanya, beserta penyebabnya.

Catatan penting — koreksi atas klaim lama (lihat ADR-019):
``botasaurus_requests.get(url)`` tanpa header GAGAL dengan ``KeyError('headers')``
karena ``reqs.py:fix_headers`` membaca ``kwargs['headers']`` tanpa ``.get()``.
Itu **bug Python pada skrip baseline benchmark milik proyek ini**, bukan
ketidakcocokan platform. Jalur publik Botasaurus yang benar — ``Request.get``
(``referer`` default) dan dekorator ``@request`` — berjalan normal. Baseline
di sini memakai jalur publik tersebut.

Usage:
    PYTHONPATH=/root/botasaurus-venv/lib/python3.14/site-packages:src \\
        /root/uwae-comparison-venv/bin/python \\
        -m universal_web_acquisition.benchmark.cross_impl_bench

Parent dan kedua arm WAJIB memakai PYTHONPATH yang sama agar resolusi modul
(brotli, certifi, requests, httpx) identik untuk semuanya.
"""

import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from universal_web_acquisition.benchmark._checkpoint import (
    Checkpoint,
    timing_evidence,
)
from universal_web_acquisition.benchmark.fixture_server import (
    FixtureServer,
    GROUND_TRUTHS,
    SCENARIOS,
)

# --------------------------------------------------------------------------
# Konfigurasi lingkungan perbandingan
# --------------------------------------------------------------------------

#: Interpreter tunggal untuk KEDUA arm (glibc aarch64, bukan Termux bionic).
COMPARISON_PYTHON = os.environ.get(
    "UWAE_COMPARISON_PYTHON", "/root/uwae-comparison-venv/bin/python"
)

#: Site-packages Botasaurus (berisi botasaurus + botasaurus_requests + .so native).
BOTASAURUS_SITE_PACKAGES = os.environ.get(
    "UWAE_BOTASAURUS_SITE_PACKAGES", "/root/botasaurus-venv/lib/python3.14/site-packages"
)

#: Sumber UWAE ( dipasang lewat PYTHONPATH agar keduanya melihat modul yang sama).
UWAE_SRC = os.environ.get("UWAE_SRC", "/root/universal-web-acquisition/src")

#: PYTHONPATH IDENTIK untuk kedua arm — syarat "device conditions identik".
COMPARISON_PYTHONPATH = f"{BOTASAURUS_SITE_PACKAGES}:{UWAE_SRC}"

#: Jumlah run per (arm, skenario) — identik untuk kedua arm.
#:
#: Di-override lewat env var HANYA untuk backfill §6.3 (slot E18). Jumlah
#: run ikut ter-fingerprint, jadi checkpoint n=30 hanya sah kalau env var
#: ini diset 30 SAAT harness dijalankan — mengubahnya setelah checkpoint
#: ditulis membuat sidik jari berbeda dan run lama diabaikan dengan
#:sendirinya (itulah yang membuat konfigurasi tak bisa diam-diam bercampur).
RUNS = int(os.environ.get("UWAE_E14_RUNS", "5"))

#: Jendela observasi berbatas untuk kegagalan DNS (detik).
DNS_OBSERVATION_WINDOW_S = 90

#: Jumlah run uji DNS per arm. Perilaku retry Botasaurus bergantung pada TEKS
#: pesan error resolver (pencocokan literal), dan teks itu berubah antar-run
#: di device ini — jadi satu run tidak cukup untuk menyimpulkan.
DNS_RUNS = 3

#: Host DNS yang pasti tidak ada — dipakai uji keterbatasan retry.
DNS_URL = "https://nonexistent-uwae-e14-test.invalid"

#: Lokasi evidence. Di-override lewat env var HANYA untuk backfill §6.3
#: (slot E18), supaya evidence slot lama tidak pernah tertimpa.
RESULTS_PATH = Path(
    os.environ.get(
        "UWAE_E14_RESULTS_PATH",
        "/root/universal-web-acquisition/docs/benchmark/engine-results-e14.json",
    )
)

#: Id benchmark. Di-override untuk backfill: slot backfill punya id sendiri
#: supaya evidence lama dan baru tidak pernah tercampur sebagai satu bukti.
BENCHMARK_ID = os.environ.get(
    "UWAE_E14_BENCHMARK_ID", "e14-cross-implementation-differential-001"
)

#: Slot yang DIGANTIKAN oleh evidence ini (kosong untuk slot asli). Dinyatakan
#: DI DALAM file evidence, bukan di aggregator — sumber kebenaran ikut
#: travels bersama buktinya.
SUPERSEDES = [
    item.strip()
    for item in os.environ.get("UWAE_E14_SUPERSEDES", "").split(",")
    if item.strip()
]

#: Checkpoint per-run, ditulis di luar repo supaya tidak pernah ter-commit.
#:
#: Device Android/Termux ini sudah reboot di tengah benchmark E16: karena
#: evidence hanya ditulis di akhir ``main()``, 393 dari 480 run hilang tanpa
#: jejak. E14 punya bentuk yang lebih sulit — satu subprocess per engine yang
#: menulis seluruh hasilnya di akhir. Checkpoint JSONL per-run menutup lubang
#: itu tanpa mengorbankan bentuk "satu subprocess per engine" (yang penting:
#: import Botasaurus mendominasi biaya per-proses, dan E14 akan dijalankan
#: ulang pada n=30).
CHECKPOINT_PATH = Path(
    os.environ.get("UWAE_E14_CHECKPOINT", "/root/.qwen/tmp/e14_checkpoint.jsonl")
)

#: Timeout per arm (detik). Ada di fingerprint: mengubahnya mengubah hasil
#: pengukuran, jadi checkpoint lama tidak boleh dipakai.
ARM_TIMEOUT_S = 600

#: Jeda antar-run yang dianggap INTERUPSI, bukan jeda normal.
INTERRUPTION_GAP_THRESHOLD_S = 60.0

# --------------------------------------------------------------------------
# Ground truth diagnosis — diturunkan dari SEMANTIK FIXTURE
# --------------------------------------------------------------------------
#
# Label diambil dari apa yang sebenarnya ada di fixture (mis. /login memuat
# field password; /challenge memuat signature interstitial), bukan dari
# keluaran engine mana pun. Engine yang diuji tidak pernah menulis di sini.

DIAGNOSIS_GROUND_TRUTH: Dict[str, str] = {
    "b07_js_render": "javascript_required",
    "e02_not_found": "content_invalid",
    "a04_login": "auth_required",
    "a06_rate_limited": "rate_limited",
    "a07_challenge": "challenge_present",
    "a07_denied": "access_denied",
    "a11_invalid_html": "content_invalid",
}

#: Kriteria PRIMER per skenario — rumus yang sama untuk kedua arm.
#: "acquisition" = status + body byte-for-byte harus cocok.
#: "diagnosis"   = diagnosis terstruktur harus cocok dengan ground truth.
#: (Hasil byte tetap DIUKUR pada skenario diagnosis dan dilaporkan terpisah.)
SCENARIO_CRITERION: Dict[str, str] = {
    sid: ("diagnosis" if sid in DIAGNOSIS_GROUND_TRUTH else "acquisition")
    for sid in SCENARIOS
}

#: Skenario yang TIDAK diukur, beserta alasannya — dilaporkan, bukan disembunyikan.
EXCLUDED_SCENARIOS: Dict[str, str] = {
    "a05_protected": (
        "memerlukan alur sesi terautentikasi (cookie login -> akses); benchmark ini "
        "mengukur target satu-permintaan. Perbandingan alur sesi belum diukur."
    ),
}

SCENARIO_IDS: List[str] = [sid for sid in SCENARIOS if sid not in EXCLUDED_SCENARIOS]


# --------------------------------------------------------------------------
# Skrip arm — dijalankan sebagai subprocess, ditulis ke berkas hasil
# --------------------------------------------------------------------------
#
# Kedua arm memakai ENV dan POLA UKURAN yang sama:
#   - elapsed_ms diukur di LUAR (mencakup pembuatan session + permintaan +
#   overhead framework), bukan hanya waktu jaringan;
#   - session/klien BARU per run (koneksi baru setiap run);
#   - peak memory Python diukur per skenario lewat tracemalloc.

BOTASAURUS_ARM_SCRIPT = r'''
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
    """Satu permintaan lewat API publik Botasaurus.

    Exception ditangkap DI DALAM task supaya teks kesalahannya terekam per
    item. (Tanpa itu, `raise_exception=False` milik Botasaurus menelan
    exception dan slot hasil menjadi None tanpa keterangan.)
    """
    try:
        r = session.get(item["url"], timeout=15)
        content = r.content
        return {
            "status_code": r.status_code,
            "body_sha256": hashlib.sha256(content).hexdigest(),
            "body_bytes": len(content),
            "content_type": r.headers.get("content-type", ""),
        }
    except Exception as exc:
        return {"error": (type(exc).__name__ + ": " + str(exc))[:300]}


results = []
tracemalloc.start()
# Checkpoint per-run: setiap run yang selesai langsung ditulis ke JSONL
# (flush + fsync di modul bersama), jadi restart perangkat tidak menghapus
# run yang sudah dibayar mahal dengan waktu device. Run yang sudah ada
# diambil dari checkpoint dan TIDAK dieksekusi ulang.
checkpoint = Checkpoint(Path(payload["checkpoint_path"]), payload["fingerprint"])
for sc in payload["scenarios"]:
    tracemalloc.reset_peak()
    scenario_peak = 0
    for run_index in range(payload["runs"]):
        cached = checkpoint.get(sc["id"], "botasaurus-request", run_index)
        if cached is not None:
            results.append(cached)
            continue
        t0 = time.perf_counter()
        outcome = acquire([{"url": sc["url"]}])
        elapsed_ms = (time.perf_counter() - t0) * 1000
        row = dict(outcome[0]) if outcome and isinstance(outcome[0], dict) else {}
        row["scenario_id"] = sc["id"]
        row["run_index"] = run_index
        row["elapsed_ms"] = round(elapsed_ms, 2)
        row["attempts"] = 1
        row["observed_diagnosis"] = None
        row["raw_signal"] = (
            "status " + str(row["status_code"]) if "status_code" in row else row.get("error", "")
        )
        # Rekam waktu + instance fixture: dua field yang hanya ada kalau run
        # benar-benar terjadi, dan yang membuat restart perangkat bisa
        # diaudit dari data — bukan diklaim.
        row["recorded_at"] = datetime.now(timezone.utc).isoformat()
        row["fixture_base_url"] = payload["base_url"]
        checkpoint.append(sc["id"], "botasaurus-request", run_index, row)
        results.append(row)
    _, scenario_peak = tracemalloc.get_traced_memory()
    for row in results:
        if row["scenario_id"] == sc["id"] and "peak_memory_bytes" not in row:
            row["peak_memory_bytes"] = scenario_peak
            # Baris yang sama ditulis ulang lengkap dengan peak memory
            # skenario yang baru diketahui. Checkpoint bersifat append-only,
            # jadi loader memakai baris TERAKHIR untuk kunci yang sama.
            checkpoint.append(
                sc["id"], "botasaurus-request", row["run_index"], row
            )
_, process_peak = tracemalloc.get_traced_memory()
tracemalloc.stop()

with open(out_path, "w") as handle:
    json.dump(
        {"engine_id": "botasaurus-request", "peak_memory_bytes": process_peak, "results": results},
        handle,
    )
'''


UWAE_ARM_SCRIPT = r'''
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
storage = FilesystemArtifactStorage(base_path=tempfile.mkdtemp(prefix="uwae-e14-"))
# RetryPolicy DEFAULT (tidak disetel ulang): max_retries=3, backoff 1s.
worker = JobWorker(repo, scheduler=None, storage=storage)


def last_assessment(job_id):
    for event in reversed(repo.list_events(job_id)):
        if event["event"] == "assessment":
            return json.loads(event["detail"])
    return {}


results = []
tracemalloc.start()
# Checkpoint per-run: setiap run yang selesai langsung ditulis ke JSONL
# (flush + fsync di modul bersama), jadi restart perangkat tidak menghapus
# run yang sudah dibayar mahal dengan waktu device. Run yang sudah ada
# diambil dari checkpoint dan TIDAK dieksekusi ulang.
checkpoint = Checkpoint(Path(payload["checkpoint_path"]), payload["fingerprint"])
for sc in payload["scenarios"]:
    tracemalloc.reset_peak()
    for run_index in range(payload["runs"]):
        cached = checkpoint.get(sc["id"], "uwae-engine", run_index)
        if cached is not None:
            results.append(cached)
            continue
        job = Job(job_id="e14-" + sc["id"] + "-" + str(run_index), url=sc["url"])
        repo.save_job(job)
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
            # Respons 2xx yang AKHIRNYA ditolak (mis. gerbang JS, halaman login)
            # tetap menghasilkan artifact — byte-nya benar-benar diambil dan
            # dipersistensi. Artifact itu harus ikut diukur; hanya outcome job
            # yang berbeda, bukan bytes-nya.
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
        # Rekam waktu + instance fixture: dua field yang hanya ada kalau run
        # benar-benar terjadi, dan yang membuat restart perangkat bisa
        # diaudit dari data — bukan diklaim.
        row["recorded_at"] = datetime.now(timezone.utc).isoformat()
        row["fixture_base_url"] = payload["base_url"]
        checkpoint.append(sc["id"], "uwae-engine", run_index, row)
        results.append(row)
    _, scenario_peak = tracemalloc.get_traced_memory()
    for row in results:
        if row["scenario_id"] == sc["id"] and "peak_memory_bytes" not in row:
            row["peak_memory_bytes"] = scenario_peak
            # Baris yang sama ditulis ulang lengkap dengan peak memory
            # skenario yang baru diketahui. Checkpoint bersifat append-only,
            # jadi loader memakai baris TERAKHIR untuk kunci yang sama.
            checkpoint.append(sc["id"], "uwae-engine", row["run_index"], row)
_, process_peak = tracemalloc.get_traced_memory()
tracemalloc.stop()

with open(out_path, "w") as handle:
    json.dump(
        {"engine_id": "uwae-engine", "peak_memory_bytes": process_peak, "results": results},
        handle,
    )
'''


BOTASAURUS_DNS_SCRIPT = r'''
import json
import sys
import time

from botasaurus.request_decorator import request


@request(output=None, create_error_logs=False, raise_exception=False, close_on_crash=True)
def acquire(session, item):
    r = session.get(item["url"], timeout=10)
    return {"status_code": r.status_code, "body_bytes": len(r.content)}


target_url = json.load(open(sys.argv[1]))["url"]
t0 = time.perf_counter()
try:
    outcome = acquire([{"url": target_url}])
    with open(sys.argv[2], "w") as handle:
        json.dump(
            {
                "returned": True,
                "elapsed_s": round(time.perf_counter() - t0, 3),
                "result": outcome,
            },
            handle,
        )
except Exception as exc:
    with open(sys.argv[2], "w") as handle:
        json.dump(
            {
                "returned": False,
                "elapsed_s": round(time.perf_counter() - t0, 3),
                "error": (type(exc).__name__ + ": " + str(exc))[:300],
            },
            handle,
        )
'''


UWAE_DNS_SCRIPT = r'''
import asyncio
import json
import os
import sys
import tempfile
import time

from universal_web_acquisition.core.job_model import Job
from universal_web_acquisition.core.job_repository import JobRepository
from universal_web_acquisition.core.job_worker import JobWorker

repo = JobRepository()
fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(fd)
repo.db_path = db_path
repo._init_db()
worker = JobWorker(repo, scheduler=None)

job = Job(job_id="e14-dns", url=json.load(open(sys.argv[1]))["url"])
repo.save_job(job)
t0 = time.perf_counter()
asyncio.run(worker._execute_job(job))
elapsed_s = time.perf_counter() - t0
final = repo.get_job(job.job_id)
assessments = [
    json.loads(event["detail"])
    for event in repo.list_events(job.job_id)
    if event["event"] == "assessment"
]
with open(sys.argv[2], "w") as handle:
    json.dump(
        {
            "returned": True,
            "elapsed_s": round(elapsed_s, 3),
            "job_status": final.status.value,
            "job_error": final.error,
            "attempts": len(repo.list_attempts(job.job_id)),
            "observed_diagnosis": assessments[-1].get("state") if assessments else None,
            "reason_code": assessments[-1].get("reason_code") if assessments else None,
        },
        handle,
    )
'''


# --------------------------------------------------------------------------
# Utilitas
# --------------------------------------------------------------------------


def _percentile(values: List[float], quantile: float) -> Optional[float]:
    """Percentile nearest-rank. Pada n=5, p95 = statistik urutan ke-5 (maks)."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, int(math.ceil(quantile * len(ordered))))
    return ordered[rank - 1]


def _median(values: List[float]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _percentile_note(runs: int) -> str:
    """Catatan persentil yang jujur untuk jumlah run yang dipakai.

    p95 nearest-rank pada n kecil jatuh di statistik urutan terakhir, tapi
    pada n=30 p95 adalah statistik urutan ke-29. Jadi kalimat "p95 =
    maksimum" hanya boleh ditulis kalau memang benar untuk n yang dipakai —
    dan ambang §6.3 (minimal 30 pengulangan) juga harus disebut apa adanya.
    """
    rank = max(1, int(math.ceil(0.95 * runs)))
    if rank == runs:
        position = (
            f"p95 nearest-rank pada n={runs} setara statistik urutan terakhir "
            "(maksimum)"
        )
    else:
        position = (
            f"p95 nearest-rank pada n={runs} memakai statistik urutan ke-{rank} "
            f"dari {runs} run (bukan maksimum)"
        )
    if runs >= 30:
        tail = (
            " — ambang minimal 30 pengulangan TEXT.md §6.3 sudah terpenuhi, "
            "tetapi persentil hanya bermakna kalau dibaca bersama median dan "
            "seluruh waktu mentah di elapsed_ms_runs"
        )
    else:
        tail = (
            " — Statistik persentil belum bermakna pada jumlah run ini; "
            "semua waktu mentah tersimpan di elapsed_ms_runs"
        )
    return position + tail


def _harness_fingerprint() -> str:
    """Sidik jari konfigurasi yang memengaruhi hasil pengukuran.

    Kalau skrip arm, skenario, ground truth, jumlah run, atau timeout berubah,
    checkpoint lama TIDAK boleh dipakai ulang — kalau dipakai, run lama
    dibandingkan dengan run baru memakai kriteria berbeda. Fingerprint membuat
    mismatch terlihat, bukan diam-diam menghasilkan angka campuran.

    Body ground truth ikut di-fingerprint lewat hash-nya (body-nya bytes, bukan
    JSON-serializable), karena body yang berubah berarti kriteria byte-verified
    berubah.
    """
    material = {
        "runs": RUNS,
        "arm_timeout_s": ARM_TIMEOUT_S,
        "dns_runs": DNS_RUNS,
        "dns_observation_window_s": DNS_OBSERVATION_WINDOW_S,
        "dns_url": DNS_URL,
        "scenario_ids": SCENARIO_IDS,
        "scenario_paths": {sid: SCENARIOS[sid] for sid in SCENARIO_IDS},
        "ground_truth_status": {
            sid: GROUND_TRUTHS[sid]["expect_status"] for sid in SCENARIO_IDS
        },
        "ground_truth_body_sha256": {
            sid: hashlib.sha256(GROUND_TRUTHS[sid]["body"]).hexdigest()
            for sid in SCENARIO_IDS
        },
        "diagnosis_ground_truth": DIAGNOSIS_GROUND_TRUTH,
        "scenario_criterion": SCENARIO_CRITERION,
        "excluded_scenarios": EXCLUDED_SCENARIOS,
        "botasaurus_arm_script": BOTASAURUS_ARM_SCRIPT,
        "uwae_arm_script": UWAE_ARM_SCRIPT,
        "botasaurus_dns_script": BOTASAURUS_DNS_SCRIPT,
        "uwae_dns_script": UWAE_DNS_SCRIPT,
    }
    payload = json.dumps(material, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class _Checkpoint(Checkpoint):
    """Checkpoint E14 — implementasi tinggal di modul checkpoint bersama.

    Yang tetap milik E14 hanya sidik jari konfigurasi harness-nya, karena
    material yang di-fingerprint-kan berbeda per harness.
    """

    def __init__(self, path: Path):
        super().__init__(path, _harness_fingerprint())


def _arm_env() -> Dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = COMPARISON_PYTHONPATH
    return env


def _run_arm(script: str, payload_path: str, out_path: str, timeout: int) -> Dict:
    """Jalankan satu arm sebagai subprocess; laporkan kegagalan honestly."""
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            [COMPARISON_PYTHON, "-u", "-c", script, payload_path, out_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_arm_env(),
            cwd=tempfile.gettempdir(),
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        stderr = exc.stderr or ""
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return {
            "engine_id": None,
            "runtime_failure": {
                "kind": "timeout",
                "timeout_s": timeout,
                "elapsed_s": round(time.perf_counter() - started, 3),
                "observed_retry_cycles": stdout.count("Retrying in 20 seconds"),
                "stdout_tail": stdout[-500:],
                "stderr_tail": stderr[-500:],
            },
            "results": [],
        }
    if proc.returncode != 0:
        return {
            "engine_id": None,
            "runtime_failure": {
                "kind": "nonzero_exit",
                "returncode": proc.returncode,
                "stdout_tail": proc.stdout[-500:],
                "stderr_tail": proc.stderr[-500:],
            },
            "results": [],
        }
    with open(out_path) as handle:
        payload_out = json.load(handle)
    # Jejak retry ikut disimpan sebagai bukti: stdout Botasaurus memuat
    # "Retrying in 20 seconds..." untuk tiap siklus retry tak-terbatas.
    payload_out["observed_retry_cycles"] = proc.stdout.count("Retrying in 20 seconds")
    payload_out["stdout_tail"] = proc.stdout[-800:]
    payload_out["stderr_tail"] = proc.stderr[-800:]
    return payload_out


def _package_versions() -> Dict[str, Optional[str]]:
    """Versi paket yang dipakai kedua arm — dicatat sebagai bukti kondisi device."""
    script = (
        "import json\n"
        "from importlib.metadata import version, PackageNotFoundError\n"
        "out = {}\n"
        "for name in ('botasaurus', 'botasaurus_requests', 'botasaurus_driver',"
        " 'requests', 'httpx', 'curl_cffi', 'joblib', 'brotli', 'certifi'):\n"
        "    try:\n"
        "        out[name.strip()] = version(name)\n"
        "    except PackageNotFoundError:\n"
        "        out[name.strip()] = None\n"
        "print(json.dumps(out))\n"
    )
    proc = subprocess.run(
        [COMPARISON_PYTHON, "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
        env=_arm_env(),
    )
    if proc.returncode != 0:
        return {}
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _interpreter_identity() -> Dict:
    script = (
        "import json, platform, sys\n"
        "print(json.dumps({\n"
        "    'executable': sys.executable,\n"
        "    'version': sys.version.split()[0],\n"
        "    'platform': platform.platform(),\n"
        "    'machine': platform.machine(),\n"
        "    'implementation': platform.python_implementation(),\n"
        "}))\n"
    )
    proc = subprocess.run(
        [COMPARISON_PYTHON, "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
        env=_arm_env(),
    )
    if proc.returncode != 0:
        return {}
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _preflight() -> None:
    """Pastikan lingkungan perbandingan siap SEBELUM pengukuran.

    Kegagalan lingkungan harus terlihat sebagai pesan jelas, bukan sebagai
    hasil benchmark yang salah (mis. fixture gagal melayani /brotli lalu
    skenario itu dilaporkan gagal).
    """
    if not os.path.exists(COMPARISON_PYTHON):
        raise SystemExit(
            "Interpreter perbandingan tidak ditemukan: "
            f"{COMPARISON_PYTHON}\n"
            "Set UWAE_COMPARISON_PYTHON ke interpreter glibc yang memuat "
            "botasaurus_requests + curl_cffi (lihat ADR-019)."
        )
    probe = (
        "import brotli, certifi\n"
        "from botasaurus.request_decorator import request\n"
        "from curl_cffi import requests as cr\n"
        "import universal_web_acquisition\n"
        "print('ok')\n"
    )
    proc = subprocess.run(
        [COMPARISON_PYTHON, "-c", probe],
        capture_output=True,
        text=True,
        timeout=120,
        env=_arm_env(),
    )
    if proc.returncode != 0:
        raise SystemExit(
            "Lingkungan perbandingan tidak lengkap:\n"
            f"{proc.stderr.strip()[-600:]}\n"
            f"PYTHONPATH yang dipakai: {COMPARISON_PYTHONPATH}\n"
            "Interpreter perbandingan harus bisa meng-import botasaurus, "
            "curl_cffi, brotli, dan universal_web_acquisition."
        )


# --------------------------------------------------------------------------
# Penilaian
# --------------------------------------------------------------------------


def _scenario_rows(scenario_id: str, arm_rows: List[dict]) -> List[dict]:
    return [row for row in arm_rows if row.get("scenario_id") == scenario_id]


def _assess_run(scenario_id: str, row: dict) -> Dict:
    """Terapkan rumus kriteria yang SAMA pada kedua arm.

    Dua sumbu yang diukur terpisah dan keduanya dilaporkan:
    - acquisition: status + body byte-for-byte cocok dengan ground truth;
    - diagnosis:   label diagnosis terstruktur cocok dengan ground truth.
    """
    truth = GROUND_TRUTHS[scenario_id]
    expect_sha = hashlib.sha256(truth["body"]).hexdigest()
    status_ok = row.get("status_code") == truth["expect_status"]
    body_ok = row.get("body_sha256") == expect_sha
    expected_diagnosis = DIAGNOSIS_GROUND_TRUTH.get(scenario_id)
    observed_diagnosis = row.get("observed_diagnosis")
    if expected_diagnosis is None:
        # Skenario sehat: yang diuji adalah TIDAK adanya masalah yang salah
        # dilaporkan. "Tidak melaporkan apa pun" BUKAN diagnosis yang benar —
        # itu ketiadaan API diagnosis, dan tidak diberi kredit. Karena itu
        # diagnosis_verified = None (tidak berlaku), bukan True.
        diagnosis_verified = None
        spurious_problem = (
            observed_diagnosis is not None and observed_diagnosis != "access_granted"
        )
    else:
        diagnosis_verified = observed_diagnosis == expected_diagnosis
        spurious_problem = None
    criterion = SCENARIO_CRITERION[scenario_id]
    primary_ok = (
        diagnosis_verified if criterion == "diagnosis" else (status_ok and body_ok)
    )
    return {
        "acquisition_verified": bool(status_ok and body_ok),
        "status_match": bool(status_ok),
        "body_match": bool(body_ok),
        "diagnosis_verified": diagnosis_verified,
        "spurious_problem": spurious_problem,
        "expected_diagnosis": expected_diagnosis,
        "observed_diagnosis": observed_diagnosis,
        "primary_criterion": criterion,
        "primary_success": bool(primary_ok),
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
            "diagnosis_verified_runs": 0,
            "diagnosis_applicable_runs": 0,
            "spurious_problem_runs": 0,
            "healthy_runs": 0,
            "observed_diagnoses": [],
            "raw_signals": [],
            "errors": [],
        }
    assessed = [_assess_run(scenario_id, row) for row in rows]
    timings = [float(row["elapsed_ms"]) for row in rows if row.get("elapsed_ms") is not None]
    attempts = [int(row.get("attempts") or 0) for row in rows]
    peaks = [int(row["peak_memory_bytes"]) for row in rows if row.get("peak_memory_bytes")]
    diagnosis_applicable = [a for a in assessed if a["diagnosis_verified"] is not None]
    healthy = [a for a in assessed if a["spurious_problem"] is not None]
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
        "acquisition_verified_runs": sum(1 for a in assessed if a["acquisition_verified"]),
        "diagnosis_verified_runs": sum(
            1 for a in diagnosis_applicable if a["diagnosis_verified"]
        ),
        "diagnosis_applicable_runs": len(diagnosis_applicable),
        "spurious_problem_runs": sum(1 for a in healthy if a["spurious_problem"]),
        "healthy_runs": len(healthy),
        "observed_diagnoses": sorted({str(a["observed_diagnosis"]) for a in assessed}),
        "raw_signals": sorted({str(row.get("raw_signal")) for row in rows})[:5],
        "errors": sorted({str(row.get("error")) for row in rows if row.get("error")})[:5],
    }


def _cause_diagnosis_metrics(arm_rows: List[dict]) -> Dict:
    """Precision/recall diagnosis PENYEBAB atas ground truth yang sama.

    Hanya skenario yang benar-benar menuntut klasifikasi penyebab yang
    dihitung di sini (7 skenario x RUNS). Perhitungan dicampur dengan
    skenario sehat akan menyesatkan: engine tanpa API diagnosis akan terlihat
    "salah" pada skenario yang memang tidak butuh diagnosis.

    Definisi (eksplisit, agar bisa diaudit):
      TP = ground truth menuntut penyebab X dan arm melaporkan X
      FN = ground truth menuntut penyebab X dan arm melaporkan label lain
           (atau tidak melaporkan label sama sekali)
      FP = arm melaporkan penyebab pada skenario yang TIDAK menuntut penyebab
           (dihitung lewat metrik false-problem terpisah, bukan di sini)
    """
    tp = fn = 0
    total = 0
    for scenario_id in SCENARIO_IDS:
        expected = DIAGNOSIS_GROUND_TRUTH.get(scenario_id)
        if expected is None:
            continue
        for row in _scenario_rows(scenario_id, arm_rows):
            total += 1
            if row.get("observed_diagnosis") == expected:
                tp += 1
            else:
                fn += 1
    # FP mustahil di himpunan ini: setiap skenario yang dihitung DEMAND label
    # penyebab, jadi tidak ada run "ground truth tanpa label" yang bisa
    # dihitung sebagai false positive. FP pada skenario sehat diukur terpisah
    # lewat _false_problem_metrics.
    fp = 0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {
        "tp": tp,
        "fn": fn,
        "fp": fp,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "applicable_runs": total,
        "definition": (
            "Hanya run dari skenario yang menuntut diagnosis penyebab. "
            "Precision = TP/(TP+FP); pembagi nol -> 0.0 (kelas yang tidak pernah "
            "diprediksi bukan keberhasilan). FP pada skenario sehat diukur "
            "terpisah lewat false_problem_rate."
        ),
    }


def _false_problem_metrics(arm_rows: List[dict]) -> Dict:
    """False-problem rate atas skenario sehat (konten valid).

    Engine yang melaporkan keadaan masalah pada konten yang sebenarnya valid
    menghasilkan diagnosis palsu. Engine yang tidak punya API diagnosis tidak
    pernah melaporkan apa pun — angka 0.0 di sini berarti "tidak ada klaim
    yang salah", BUKAN "diagnosis yang benar".
    """
    spurious = total = 0
    for scenario_id in SCENARIO_IDS:
        if scenario_id in DIAGNOSIS_GROUND_TRUTH:
            continue
        for row in _scenario_rows(scenario_id, arm_rows):
            total += 1
            observed = row.get("observed_diagnosis")
            if observed is not None and observed != "access_granted":
                spurious += 1
    return {
        "spurious_problem_runs": spurious,
        "healthy_runs": total,
        "rate": round(spurious / total, 4) if total else 0.0,
        "definition": (
            "Run pada skenario sehat (konten target valid) di mana engine "
            "melaporkan keadaan masalah. 0.0 pada engine tanpa API diagnosis "
            "berarti tidak ada klaim yang salah, bukan diagnosis yang benar."
        ),
    }


def _dns_summary(runs: List[Dict]) -> Dict:
    """Ringkasan uji DNS per arm: hasil akhir, siklus retry, klasifikasi."""
    terminal = 0
    timed_out = 0
    classified = 0
    retry_cycles: List[int] = []
    elapsed: List[Optional[float]] = []
    attempts: List[int] = []
    for run in runs:
        failure = run.get("runtime_failure")
        cycles = run.get("observed_retry_cycles")
        if cycles is None and failure:
            cycles = failure.get("observed_retry_cycles")
        retry_cycles.append(int(cycles or 0))
        if failure and failure.get("kind") == "timeout":
            timed_out += 1
            elapsed.append(None)
            continue
        if run.get("returned"):
            terminal += 1
        elapsed.append(run.get("elapsed_s"))
        if run.get("observed_diagnosis"):
            classified += 1
        if run.get("attempts"):
            attempts.append(int(run["attempts"]))
    return {
        "runs": len(runs),
        "reached_terminal_outcome": terminal,
        "no_terminal_outcome_within_window": timed_out,
        "runs_with_classified_diagnosis": classified,
        "observed_retry_cycles_per_run": retry_cycles,
        "attempts_per_run": attempts,
        "elapsed_s_per_run": elapsed,
    }


# --------------------------------------------------------------------------
# Benchmark utama
# --------------------------------------------------------------------------


def main() -> None:
    _preflight()
    started = time.perf_counter()

    # Checkpoint dibuka SEBELUM arm dijalankan, supaya key yang sudah ada
    # bisa dibedakan dari key yang baru ditulis pada pemanggilan ini.
    checkpoint = _Checkpoint(CHECKPOINT_PATH)
    keys_before = set(checkpoint.rows.keys())

    with FixtureServer() as base_url:
        payload = {
            "runs": RUNS,
            "base_url": base_url,
            "checkpoint_path": str(CHECKPOINT_PATH),
            "fingerprint": checkpoint.fingerprint,
            "scenarios": [
                {
                    "id": sid,
                    "url": base_url + SCENARIOS[sid],
                    "path": SCENARIOS[sid],
                }
                for sid in SCENARIO_IDS
            ],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(payload, handle)
            payload_path = handle.name

        botasaurus_out = payload_path + ".botasaurus.json"
        uwae_out = payload_path + ".uwae.json"
        botasaurus = _run_arm(
            BOTASAURUS_ARM_SCRIPT, payload_path, botasaurus_out, timeout=ARM_TIMEOUT_S
        )
        uwae = _run_arm(UWAE_ARM_SCRIPT, payload_path, uwae_out, timeout=ARM_TIMEOUT_S)

        dns_payload_path = payload_path + ".dns.json"
        with open(dns_payload_path, "w") as handle:
            json.dump({"url": DNS_URL}, handle)
        dns_arms = {
            "botasaurus-request": (BOTASAURUS_DNS_SCRIPT, "botasaurus"),
            "uwae-engine": (UWAE_DNS_SCRIPT, "uwae"),
        }
        dns_runs: Dict[str, List[Dict]] = {arm_id: [] for arm_id in dns_arms}
        for run_index in range(DNS_RUNS):
            for arm_id, (script, tag) in dns_arms.items():
                # Uji DNS juga berjarak run-per-run, jadi ikut di-checkpoint:
                # jendela observasinya 90 detik per run dan device ini sudah
                # pernah reboot di tengah benchmark.
                cached = checkpoint.get("dns", arm_id, run_index)
                if cached is not None:
                    dns_runs[arm_id].append(cached)
                    continue
                out_path = f"{dns_payload_path}.{tag}.{run_index}.json"
                dns_t0 = time.perf_counter()
                dns_row = _run_arm(
                    script,
                    dns_payload_path,
                    out_path,
                    timeout=DNS_OBSERVATION_WINDOW_S,
                )
                dns_row["elapsed_ms"] = round((time.perf_counter() - dns_t0) * 1000, 2)
                dns_row["recorded_at"] = datetime.now(timezone.utc).isoformat()
                dns_row["fixture_base_url"] = base_url
                checkpoint.append("dns", arm_id, run_index, dns_row)
                dns_runs[arm_id].append(dns_row)
                Path(out_path).unlink(missing_ok=True)

        for path in (botasaurus_out, uwae_out):
            Path(path).unlink(missing_ok=True)
    Path(payload_path).unlink(missing_ok=True)
    Path(dns_payload_path).unlink(missing_ok=True)

    botasaurus_rows = botasaurus.get("results", [])
    uwae_rows = uwae.get("results", [])

    scenarios_out = []
    for sid in SCENARIO_IDS:
        truth = GROUND_TRUTHS[sid]
        scenarios_out.append(
            {
                "scenario_id": sid,
                "path": SCENARIOS[sid],
                "primary_criterion": SCENARIO_CRITERION[sid],
                "ground_truth": {
                    "expect_status": truth["expect_status"],
                    "expect_body_sha256": hashlib.sha256(truth["body"]).hexdigest(),
                    "expect_body_bytes": len(truth["body"]),
                    "expected_diagnosis": DIAGNOSIS_GROUND_TRUTH.get(sid),
                },
                "results": {
                    "uwae-engine": _summarise(sid, uwae_rows),
                    "botasaurus-request": _summarise(sid, botasaurus_rows),
                },
            }
        )

    unsupported = []
    for sid, reason in EXCLUDED_SCENARIOS.items():
        unsupported.append({"scenario_id": sid, "reason": reason, "supported_by": []})
    unsupported.append(
        {
            "scenario_id": "js_rendering_browser_arm",
            "reason": (
                "Kedua arm di benchmark ini adalah arm HTTP. Rendering JavaScript "
                "butuh arm browser; Botasaurus memakai driver CDP (bukan "
                "chromedriver) dan UWAE memakai raw CDP (ADR-014) — keduanya "
                "belum diukur pada device ini, jadi tidak diklaim sebagai "
                "perbedaan engine."
            ),
            "supported_by": [],
        }
    )

    # Checkpoint dibaca ULANG setelah semua arm selesai: arm script menulis ke
    # berkas yang sama, jadi key yang sudah ada sebelum invocation ini adalah
    # run yang DIPAKAI ULANG, dan key yang baru adalah run yang dieksekusi
    # pada pemanggilan ini. Bedanya itulah yang membuat blok timing tidak
    # bisa disalahbaca.
    checkpoint_after = _Checkpoint(CHECKPOINT_PATH)
    keys_after = set(checkpoint_after.rows.keys())
    checkpoint_stats = checkpoint_after.stats()
    checkpoint_stats["runs_reused"] = len(keys_before & keys_after)
    checkpoint_stats["runs_executed_this_invocation"] = len(keys_after - keys_before)

    measured_rows: List[Dict] = list(botasaurus_rows) + list(uwae_rows)
    for arm_rows in dns_runs.values():
        measured_rows.extend(arm_rows)

    doc = {
        "schema_version": 1,
        "benchmark_id": BENCHMARK_ID,
        # Slot yang DIGANTIKAN oleh evidence ini. Dinyatakan DI DALAM evidence,
        # bukan di aggregator — supaya sumber kebenaran ikut travels bersama
        # buktinya, dan slot lama tidak bisa hilang tanpa jejak.
        "supersedes": SUPERSEDES,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        # Durasi TIDAK lagi berupa satu angka telanjang. Angka `elapsed_s`
        # tingkat dokumen hanya mengukur SATU pemanggilan harness — kalau
        # sebagian besar run diambil dari checkpoint, pembaca akan salah
        # menyimpulkan seluruh benchmark hanya memakan waktu itu. Jadi
        # durasi dipublikasikan sebagai blok timing yang menamai cakupannya.
        "timing": timing_evidence(
            measured_rows, checkpoint_stats, time.perf_counter() - started,
            INTERRUPTION_GAP_THRESHOLD_S,
        ),
        "checkpoint": checkpoint_stats,
        "environment": {
            "interpreter": _interpreter_identity(),
            "pythonpath": COMPARISON_PYTHONPATH,
            "package_versions": _package_versions(),
            "fixture": "deterministic localhost fixture server (fixture_server.py)",
            "method": (
                f"{RUNS} run per (arm, skenario), koneksi baru setiap run; "
                "kedua arm sebagai subprocess dari SATU interpreter dengan SATU "
                "PYTHONPATH melawan SATU instance fixture server"
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
        },
        "engines": [
            {
                "engine_id": "uwae-engine",
                "engine_name": "UWAE engine (JobWorker + ACP)",
                "engine_version": "uwae-0.3.0",
                "is_baseline": False,
                "description": (
                    "JobWorker + transport registry (curl_cffi primary) + classifier + "
                    "planner + artifact storage; RetryPolicy default (tidak disetel ulang)"
                ),
            },
            {
                "engine_id": "botasaurus-request",
                "engine_name": "Botasaurus @request (public API)",
                "engine_version": "botasaurus 4.0.97 / botasaurus_requests 4.0.38",
                "source_commit": "6c9260de12d71b9dc0c3b3a019d2698a9af38433",
                "is_baseline": True,
                "description": (
                    "Dekorator @request publik: output=None, create_error_logs=False, "
                    "raise_exception=False, close_on_crash=True, cache=False, max_retry=None "
                    "(semua default Botasaurus kecuali tiga yang eksplisit disebut)"
                ),
            },
        ],
        "scenarios": scenarios_out,
        "dns_boundedness": {
            "url": DNS_URL,
            "observation_window_s": DNS_OBSERVATION_WINDOW_S,
            "runs_per_arm": DNS_RUNS,
            "uwae-engine": {
                "runs": dns_runs["uwae-engine"],
                "summary": _dns_summary(dns_runs["uwae-engine"]),
            },
            "botasaurus-request": {
                "runs": dns_runs["botasaurus-request"],
                "summary": _dns_summary(dns_runs["botasaurus-request"]),
            },
            "note": (
                "Perilaku retry Botasaurus pada kegagalan DNS dipicu oleh "
                "pencocokan TEKS LITERAL pada pesan error resolver ('dial tcp: "
                "lookup' DAN 'no such host') di dalam retry_on_network_error "
                "(while True, sleep 20 detik). Teks resolver berubah antar-run "
                "di device ini (mis. 'no such host' vs 'Temporary failure in name "
                "resolution'), sehingga hasil terminal dan jumlah siklus retry "
                "dapat berbeda antar-run — semuanya dicatat apa adanya, bukan "
                "dirata-rata menjadi satu angka."
            ),
        },
        "unsupported_scenarios": unsupported,
        "summary": {
            "interpretation": (
                "PENGUKURAN BASELINE lintas-implementasi — BUKAN klaim UWAE "
                "mengungguli Botasaurus. Klaim lama bahwa engine HTTP Botasaurus "
                "tidak dapat dieksekusi di environment ini SALAH: penyebabnya "
                "bug Python pada skrip baseline milik proyek ini "
                "(botasaurus_requests.get tanpa header -> KeyError('headers')), bukan "
                "ketidakcocokan platform. Jalur publik Botasaurus (@request) "
                "berjalan normal dan diukur di sini dengan kondisi device identik."
            ),
            "cause_diagnosis_metrics": {
                "uwae-engine": _cause_diagnosis_metrics(uwae_rows),
                "botasaurus-request": _cause_diagnosis_metrics(botasaurus_rows),
            },
            "false_problem_metrics": {
                "uwae-engine": _false_problem_metrics(uwae_rows),
                "botasaurus-request": _false_problem_metrics(botasaurus_rows),
            },
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
    RESULTS_PATH.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")

    header = f"{'scenario':18s} {'arm':22s} {'ok':>3s} {'med ms':>9s} {'p95 ms':>9s} {'att':>4s}"
    print(header)
    print("-" * len(header))
    for entry in scenarios_out:
        for arm_id in ("uwae-engine", "botasaurus-request"):
            summary = entry["results"][arm_id]
            median = summary["elapsed_ms_median"]
            p95 = summary["elapsed_ms_p95"]
            print(
                f"{entry['scenario_id']:18s} {arm_id:22s} "
                f"{summary['primary_successes']:>3d} "
                f"{(f'{median:9.2f}' if median is not None else '        —')} "
                f"{(f'{p95:9.2f}' if p95 is not None else '        —')} "
                f"{summary['attempts_max'] if summary['attempts_max'] is not None else '—':>4}"
            )
    print()
    for arm_id, metrics in doc["summary"]["cause_diagnosis_metrics"].items():
        print(
            f"diagnosis penyebab {arm_id:20s} precision={metrics['precision']} "
            f"recall={metrics['recall']} f1={metrics['f1']} "
            f"(tp={metrics['tp']} fn={metrics['fn']} atas {metrics['applicable_runs']} run)"
        )
    for arm_id, metrics in doc["summary"]["false_problem_metrics"].items():
        print(
            f"false-problem {arm_id:20s} rate={metrics['rate']} "
            f"({metrics['spurious_problem_runs']}/{metrics['healthy_runs']} run sehat)"
        )
    print()
    for arm_id, block in doc["dns_boundedness"].items():
        if not isinstance(block, dict) or "summary" not in block:
            continue
        metrics = block["summary"]
        print(
            f"dns {arm_id:24s} hasil akhir={metrics['reached_terminal_outcome']}/"
            f"{metrics['runs']} tanpa hasil akhir={metrics['no_terminal_outcome_within_window']} "
            f"siklus retry={metrics['observed_retry_cycles_per_run']} "
            f"diagnosis terklasifikasi={metrics['runs_with_classified_diagnosis']}"
        )
    print(f"\nresults -> {RESULTS_PATH}")


if __name__ == "__main__":
    main()
