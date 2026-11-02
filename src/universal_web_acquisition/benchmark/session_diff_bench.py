"""E15 — Session-flow differential: UWAE vs Botasaurus (cross-implementation).

Menutup gap yang dideklarasikan E14 sendiri: ``unsupported_scenarios`` pada
``engine-results-e14.json`` mencantumkan ``a05_protected`` — "memerlukan alur
sesi terautentikasi" — sebagai skenario yang TIDAK dibandingkan. E15 juga
menjawab pertanyaan gerbang INSTRUCTION.md §9: "Apakah pemulihan sesi berhasil
pada fixture yang mendukungnya?" (G5).

Desain
------
1. **Satu interpreter, satu PYTHONPATH, satu fixture server.** Kedua arm
   adalah subprocess dari interpreter yang sama dengan PYTHONPATH yang sama,
   melawan satu instance fixture server. Mesin "identical conditions" milik E14
   di-IMPORT, bukan disalin — supaya ada satu sumber kebenaran untuk cara arm
   dijalankan dan lingkungan dicatat. Kalau mesin ini bercabang antara E14 dan
   E15, klaim keadilan repo diam-diam rusak.

2. **Satu subprocess per run.** State sesi fixture adalah state global server;
   bila arm mengulang run di dalam satu proses, parent tak bisa menyetel ulang
   state itu di antara run. Isolasi per-run juga menutup kebocoran state antar
   run — jadi setiap run benar-benar berdiri sendiri.

3. **Bukti sisi server, bukan laporan arm.** Fixture mencatat setiap request
   yang benar-benar diterima (method, path, status, cookie). "Arm mengklaim
   me-recovery" bukan bukti — yang bukti adalah log server: login benar-benar
   terjadi, lalu /protected dijawab 200 dengan cookie baru.

4. **Dua sumbu, tanpa strawman.** Botasaurus punya kapabilitas sesi nyata
   (cookie persistence pada objek ``session``). Menariknya lengan ``-auto``
   saja akan menjadi pembanding yang sengaja dibuat lemah — persis yang
   TEXT.md larang. Maka ada DUA lengan Botasaurus:

   - ``botasaurus-auto`` — satu request, tanpa kode recovery. Mengukur
     kapabilitas *generik* API publik Botasaurus.
   - ``botasaurus-explicit`` — recovery ditulis DI DALAM arm (login → ulangi).
     Mengukur apa yang *mungkin dicapai* oleh pengguna Botasaurus.

   Perbedaan yang diukur bukan "apakah bisa" (dua-duanya bisa) melainkan
   "apakah perlu kode per-skenario" — dan itu dilaporkan apa adanya, bukan
   klaim kemenangan.

5. **Pengetahuan target diberikan simetris.** UWAE dikonfigurasi dengan
   ``HTTPSessionRecoveryProvider(login_url, protected_url, cookie_name)``;
   lengan ``botasaurus-explicit`` diberi URL login yang sama di dalam kodenya.
   Keduanya tahu target. Yang dibedakan adalah LETAK kebijakan: generik di
   engine, atau per-task di kode pengguna.

Ground truth berasal dari semantika protokol fixture (resource terproteksi
mengembalikan 200 HANYA bila cookie sesi yang sedang aktif di server), bukan
dari output engine mana pun.
"""

import hashlib
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

# Penyimpanan run + helper durasi dipakai bersama oleh harness E14, E15, dan
# E16, supaya tiga harness tidak punya tiga salinan yang bisa berbedadrift.
from universal_web_acquisition.benchmark._checkpoint import (
    Checkpoint,
    timing_evidence,
)

# Mesin "identical conditions" milik E14 di-IMPORT, bukan disalin: satu
# sumber kebenaran untuk env, subprocess, dan pencatatan lingkungan.
from universal_web_acquisition.benchmark.cross_impl_bench import (
    _arm_env,
    _interpreter_identity,
    _median,
    _package_versions,
    _percentile,
    _percentile_note,
    _preflight,
    _run_arm,
)
from universal_web_acquisition.benchmark.fixture_server import (
    PROTECTED_BODY,
    SESSION_COOKIE,
    FixtureServer,
)

#: Id benchmark. Di-override lewat env var HANYA untuk backfill §6.3
#: (slot E19), supaya evidence lama dan baru tidak pernah tercampur sebagai
#: satu bukti.
BENCHMARK_ID = os.environ.get(
    "UWAE_E15_BENCHMARK_ID", "e15-session-flow-differential-001"
)

#: Lokasi evidence. Di-override lewat env var HANYA untuk backfill §6.3
#: (slot E19), supaya evidence slot lama tidak pernah tertimpa.
RESULTS_PATH = Path(
    os.environ.get(
        "UWAE_E15_RESULTS_PATH",
        "/root/universal-web-acquisition/docs/benchmark/engine-results-e15.json",
    )
)

#: Slot yang DIGANTIKAN oleh evidence ini (kosong untuk slot asli). Dinyatakan
#: DI DALAM file evidence, bukan di aggregator — sumber kebenaran ikut
#: travels bersama buktinya.
SUPERSEDES = [
    item.strip()
    for item in os.environ.get("UWAE_E15_SUPERSEDES", "").split(",")
    if item.strip()
]

#: Jumlah run per (arm, skenario) — identik untuk kedua arm.
#:
#: Di-override lewat env var HANYA untuk backfill §6.3 (slot E19). Jumlah
#: run ikut ter-fingerprint, jadi checkpoint n=30 hanya sah kalau env var
#: ini diset 30 SAAT harness dijalankan — mengubahnya setelah checkpoint
#: ditulis membuat sidik jari berbeda dan run lama diabaikan dengan
#: sendirinya (itulah yang membuat konfigurasi tak bisa diam-diam bercampur).
RUNS = int(os.environ.get("UWAE_E15_RUNS", "5"))
ARM_TIMEOUT_S = 120

# Ambang jeda antar-run yang dianggap INTERUPSI, bukan jeda normal. Jeda
# normal antar-run di device ini jauh di bawah satu menit; jeda di atas itu
# berarti perangkat mati / harness restart, dan itu harus terlihat di
# evidence sebagai batas segmen eksekusi.
INTERRUPTION_GAP_THRESHOLD_S = 60.0

# Checkpoint per run. Device Android/Termux sudah reboot di tengah benchmark
# lain, dan evidence yang hanya ditulis di akhir main() hilang seketika
# tanpa jejak. Checkpoint JSONL ditulis SETIAP run selesai (flush + fsync),
# jadi restart melanjutkan dari cell terakhir — bukan dari nol.
#
# Path default DI LUAR repo supaya tidak ikut ter-commit.
CHECKPOINT_PATH = Path(
    os.environ.get("UWAE_E15_CHECKPOINT", "/root/.qwen/tmp/e15_checkpoint.jsonl")
)

EXPECTED_BODY_SHA256 = hashlib.sha256(PROTECTED_BODY).hexdigest()
EXPECTED_BODY_BYTES = len(PROTECTED_BODY)

# Skenario. "cookie_mode" menentukan cookie yang DIBERIKAN ke klien dan
# state server saat arm berjalan.
SCENARIOS = [
    {
        "id": "session_valid",
        "description": (
            "Kontrol: klien memegang sesi yang SAH di server. Resource terproteksi "
            "harus bisa diambil tanpa recovery sama sekali."
        ),
        "cookie_mode": "valid",
        "expects_recovery": False,
    },
    {
        "id": "session_required",
        "description": (
            "Klien tidak memegang sesi sama sekali; server exige cookie sesi. "
            "Resource terproteksi hanya bisa diambil bila engine mampu "
            "mengauthentikasi ulang secara otomatis."
        ),
        "cookie_mode": "none",
        "expects_recovery": True,
    },
    {
        "id": "session_expired",
        "description": (
            "Klien memegang cookie yang MASIH SAH secara sintaksis tetapi sudah "
            "DICABUT di sisi server (rotasi token). Persis situasi 'sesi "
            "kedaluwarsa tanpa klien tahu' — cookie tidak bisa dibedakan dari "
            "cookie valid oleh klien."
        ),
        "cookie_mode": "stale",
        "expects_recovery": True,
    },
]

ARMS = {
    "uwae-engine": {
        "recovery_policy": "engine_generic",
        "description": (
            "Jalur produksi UWAE: JobWorker + SessionRecoveryManager + "
            "HTTPSessionRecoveryProvider. Recovery dipicu kebijakan generik "
            "planner (RECOVER_SESSION) — tidak ada kode recovery per-skenario "
            "di arm ini."
        ),
    },
    "botasaurus-auto": {
        "recovery_policy": "none",
        "description": (
            "Satu request lewat @request (API publik Botasaurus) tanpa kode "
            "recovery. Mengukur kapabilitas generik API publik, bukan versi "
            "yang sengaja dirusak."
        ),
    },
    "botasaurus-explicit": {
        "recovery_policy": "written_in_arm_code",
        "description": (
            "Recovery ditulis DI DALAM arm: bila 401, arm memanggil endpoint "
            "login lalu mengulangi request. Mengukur apa yang mungkin dicapai "
            "pengguna Botasaurus dengan API publiknya — menjaga agar "
            "perbandingan ini bukan pembanding yang sengaja dibuat lemah."
        ),
    },
    "botasaurus-decorator-request": {
        "recovery_policy": "written_in_arm_code",
        "description": (
            "Kode recovery IDENTIK dengan botasaurus-explicit, tapi memakai "
            "objek reqs yang diberikan dekorator (botasaurus_requests."
            "request_class.Request) alih-alih Session() eksplisit. Membuktikan "
            "baseline diberi bentuk objek sesi terkuat yang Botasaurus "
            "tawarkan, dan mengisolasi perilaku cookie objek dekorator."
        ),
    },
}


# ---------------------------------------------------------------------------
# Arm scripts
# ---------------------------------------------------------------------------

UWAE_ARM_SCRIPT = r'''
import asyncio
import hashlib
import json
import os
import sys
import tempfile
import time
from datetime import datetime

payload = json.load(open(sys.argv[1]))
out_path = sys.argv[2]

from universal_web_acquisition.artifact.storage import FilesystemArtifactStorage
from universal_web_acquisition.core.job_model import Job
from universal_web_acquisition.core.job_repository import JobRepository
from universal_web_acquisition.core.job_worker import JobWorker
from universal_web_acquisition.http_transport.registry import RetryPolicy
from universal_web_acquisition.session.manager import SessionRecoveryManager, SessionStore
from universal_web_acquisition.session.providers import HTTPSessionRecoveryProvider
from universal_web_acquisition.session.recovery import SessionGeneration


def _detail(event):
    try:
        return json.loads(event.get("detail") or "{}")
    except (TypeError, ValueError):
        return {}


def run_once():
    started = time.perf_counter()
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo = JobRepository(db_path=db_path)
    storage = FilesystemArtifactStorage(base_path=tempfile.mkdtemp(prefix="uwae-e15-"))

    origin = payload["origin"]
    store = SessionStore()
    cookie_value = payload.get("cookie_value")
    if cookie_value:
        # Sesi yang sudah ada sebelum job (kontrol "sesi sah" ATAU "sesi
        # kedaluwarsa") diterbitkan via store.publish() tanpa lewat
        # provider.recover() — jadiWhat's yang diuji benar-benar "memakai
        # cookie yang ada", bukan "me-recovery dari nol".
        store.publish(
            origin,
            SessionGeneration(origin, 1, datetime.now()),
            {"cookies": {payload["cookie_name"]: cookie_value}},
        )

    provider = HTTPSessionRecoveryProvider(
        origin=origin,
        login_url=payload["login_url"],
        protected_url=payload["target_url"],
        cookie_name=payload["cookie_name"],
    )
    manager = SessionRecoveryManager(provider=provider, store=store)
    worker = JobWorker(
        repo,
        scheduler=None,
        storage=storage,
        retry_policy=RetryPolicy(),
        session_manager=manager,
    )
    job = Job(job_id="e15-session", url=payload["target_url"])
    repo.save_job(job)
    asyncio.run(worker._execute_job(job))

    final = repo.get_job(job.job_id)
    events = repo.list_events(job.job_id)
    attempts = repo.list_attempts(job.job_id)

    status = None
    body_sha = None
    body_bytes = None
    if final.artifact_id:
        artifact = asyncio.run(storage.retrieve(final.artifact_id))
        if artifact is not None:
            status = artifact.status_code
            body_sha = hashlib.sha256(artifact.content).hexdigest()
            body_bytes = len(artifact.content)

    recovery_outcome = None
    recovery_generation = None
    diagnosis_state = None
    diagnosis_reason = None
    for event in events:
        if event["event"] == "session_recovery":
            detail = _detail(event)
            recovery_outcome = detail.get("outcome")
            recovery_generation = detail.get("generation")
        elif event["event"] == "assessment":
            detail = _detail(event)
            diagnosis_state = detail.get("state")
            diagnosis_reason = detail.get("reason_code")

    status_value = getattr(final.status, "value", None) or str(final.status)
    return {
        "status_code": status,
        "body_sha256": body_sha,
        "body_bytes": body_bytes,
        "attempts": len(attempts),
        "recovery_outcome": recovery_outcome,
        "recovery_generation": recovery_generation,
        "diagnosis_state": diagnosis_state,
        "diagnosis_reason": diagnosis_reason,
        "terminal_status": status_value,
        "error": (final.error or None),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
    }


try:
    outcome = run_once()
except Exception as exc:
    outcome = {"error": (type(exc).__name__ + ": " + str(exc))[:400]}

with open(out_path, "w") as handle:
    json.dump({"engine_id": "uwae-engine", "outcome": outcome}, handle)
'''


BOTASAURUS_AUTO_ARM_SCRIPT = r'''
import hashlib
import json
import sys
import time

payload = json.load(open(sys.argv[1]))
out_path = sys.argv[2]

from botasaurus.request_decorator import request
from botasaurus_requests import Session


@request(
    output=None,
    create_error_logs=False,
    raise_exception=False,
    close_on_crash=True,
    cache=False,
)
def acquire(reqs, item):
    """Satu request ke resource terproteksi — tanpa kode recovery apa pun.

    Memakai ``botasaurus_requests.Session()`` EKSPLISIT, bukan objek ``reqs``
    yang diberikan dekorator: objek latter tidak menyimpan cookie (setiap
    call membuat sesi sementara), sehingga memakainya akan membuat baseline
    terlihat "tidak punya sesi" — artefak objek, bukan batas platform.

    Cookie sesi (bila ada) dikirim lewat parameter ``cookies=`` API publik.
    """
    try:
        session = Session()
        cookies = None
        if item.get("cookie_value"):
            cookies = {item["cookie_name"]: item["cookie_value"]}
        r = session.get(item["url"], timeout=15, headers={}, cookies=cookies)
        content = r.content
        return {
            "status_code": r.status_code,
            "body_sha256": hashlib.sha256(content).hexdigest(),
            "body_bytes": len(content),
        }
    except Exception as exc:
        return {"error": (type(exc).__name__ + ": " + str(exc))[:300]}


started = time.perf_counter()
outcome = acquire(
    [
        {
            "url": payload["target_url"],
            "cookie_name": payload["cookie_name"],
            "cookie_value": payload.get("cookie_value"),
        }
    ]
)
elapsed_ms = (time.perf_counter() - started) * 1000
row = dict(outcome[0]) if outcome and isinstance(outcome[0], dict) else {}
row["attempts"] = 1
row["recovery_outcome"] = None
row["recovery_generation"] = None
row["diagnosis_state"] = None
row["diagnosis_reason"] = None
row["terminal_status"] = None
row["elapsed_ms"] = round(elapsed_ms, 2)

with open(out_path, "w") as handle:
    json.dump({"engine_id": "botasaurus-auto", "outcome": row}, handle)
'''


BOTASAURUS_EXPLICIT_ARM_SCRIPT = r'''
import hashlib
import json
import sys
import time

payload = json.load(open(sys.argv[1]))
out_path = sys.argv[2]

from botasaurus.request_decorator import request
from botasaurus_requests import Session


@request(
    output=None,
    create_error_logs=False,
    raise_exception=False,
    close_on_crash=True,
    cache=False,
)
def acquire(reqs, item):
    """Alur sesi EKSPLISIT: request target; bila 401, login lalu ulangi.

    Ini adalah alur yang ditulis pengguna Botasaurus secara manual — bukan
    pembanding yang sengaja dibuat lemah. Tujuannya mengukur apa yang MUNGKIN
    dicapai, sehingga selisih terhadap UWAE bermakna sebagai selisih
    arsitektur (letak kebijakan), bukan selisih kemampuan.

    Memakai ``botasaurus_requests.Session()`` eksplisit — satu-satunya objek
    sesi Botasaurus yang benar-benar menyimpan cookie. Percobaan ulang TIDAK
    mengirim cookie secara manual: cookie diambil otomatis oleh cookie jar
    session, seperti pemakaian normal.
    """
    try:
        session = Session()
        cookies = None
        if item.get("cookie_value"):
            cookies = {item["cookie_name"]: item["cookie_value"]}
        r = session.get(item["url"], timeout=15, headers={}, cookies=cookies)
        status = r.status_code
        content = r.content
        recovery_used = False
        if status == 401:
            session.get(item["login_url"], timeout=15, headers={})
            r2 = session.get(item["url"], timeout=15, headers={})
            status = r2.status_code
            content = r2.content
            recovery_used = True
        return {
            "status_code": status,
            "body_sha256": hashlib.sha256(content).hexdigest(),
            "body_bytes": len(content),
            "recovery_used": recovery_used,
        }
    except Exception as exc:
        return {"error": (type(exc).__name__ + ": " + str(exc))[:300]}


started = time.perf_counter()
outcome = acquire(
    [
        {
            "url": payload["target_url"],
            "login_url": payload["login_url"],
            "cookie_name": payload["cookie_name"],
            "cookie_value": payload.get("cookie_value"),
        }
    ]
)
elapsed_ms = (time.perf_counter() - started) * 1000
row = dict(outcome[0]) if outcome and isinstance(outcome[0], dict) else {}
row["attempts"] = 2 if row.get("recovery_used") else 1
row["recovery_outcome"] = "recovered" if row.get("recovery_used") else None
row["recovery_generation"] = None
row["diagnosis_state"] = None
row["diagnosis_reason"] = None
row["terminal_status"] = None
row["elapsed_ms"] = round(elapsed_ms, 2)

with open(out_path, "w") as handle:
    json.dump({"engine_id": "botasaurus-explicit", "outcome": row}, handle)
'''


BOTASAURUS_DECORATOR_ARM_SCRIPT = r'''
import hashlib
import json
import sys
import time

payload = json.load(open(sys.argv[1]))
out_path = sys.argv[2]

from botasaurus.request_decorator import request


@request(
    output=None,
    create_error_logs=False,
    raise_exception=False,
    close_on_crash=True,
    cache=False,
)
def acquire(reqs, item):
    """Alur recovery IDENTIK dengan lengan botasaurus-explicit — TAPI memakai
    objek ``reqs`` yang diberikan dekorator, bukan ``Session()`` eksplisit.

    Lengan ini ada sebagai pembuktian bahwa baseline diberi bentuk terkuat
    Botasaurus: kode recovery yang identik dijalankan pada BENTUK OBJEK
    SESI LAIN yang Botasaurus tawarkan sendiri. Selisih hasil lengan ini
    terhadap ``botasaurus-explicit`` adalah TEMUAN tentang objek sesi
    Botasaurus (batas platform yang nyata), bukan selisih kapabilitas.
    """
    try:
        cookies = None
        if item.get("cookie_value"):
            cookies = {item["cookie_name"]: item["cookie_value"]}
        r = reqs.get(item["url"], timeout=15, headers={}, cookies=cookies)
        status = r.status_code
        content = r.content
        recovery_used = False
        if status == 401:
            reqs.get(item["login_url"], timeout=15, headers={})
            r2 = reqs.get(item["url"], timeout=15, headers={})
            status = r2.status_code
            content = r2.content
            recovery_used = True
        return {
            "status_code": status,
            "body_sha256": hashlib.sha256(content).hexdigest(),
            "body_bytes": len(content),
            "recovery_used": recovery_used,
        }
    except Exception as exc:
        return {"error": (type(exc).__name__ + ": " + str(exc))[:300]}


started = time.perf_counter()
outcome = acquire(
    [
        {
            "url": payload["target_url"],
            "login_url": payload["login_url"],
            "cookie_name": payload["cookie_name"],
            "cookie_value": payload.get("cookie_value"),
        }
    ]
)
elapsed_ms = (time.perf_counter() - started) * 1000
row = dict(outcome[0]) if outcome and isinstance(outcome[0], dict) else {}
row["attempts"] = 2 if row.get("recovery_used") else 1
row["recovery_outcome"] = "recovered" if row.get("recovery_used") else None
row["recovery_generation"] = None
row["diagnosis_state"] = None
row["diagnosis_reason"] = None
row["terminal_status"] = None
row["elapsed_ms"] = round(elapsed_ms, 2)

with open(out_path, "w") as handle:
    json.dump({"engine_id": "botasaurus-decorator-request", "outcome": row}, handle)
'''


ARM_SCRIPTS = {
    "uwae-engine": UWAE_ARM_SCRIPT,
    "botasaurus-auto": BOTASAURUS_AUTO_ARM_SCRIPT,
    "botasaurus-explicit": BOTASAURUS_EXPLICIT_ARM_SCRIPT,
    "botasaurus-decorator-request": BOTASAURUS_DECORATOR_ARM_SCRIPT,
}


# ---------------------------------------------------------------------------
# Checkpoint per-run
#
# Benchmark E16 di device yang sama kehilangan 393 dari 480 run karena
# evidence hanya ditulis di akhir main() dan perangkat mati di tengah jalan.
# Checkpoint JSONL ditulis SETIAP run selesai (flush + fsync), jadi restart
# melanjutkan dari cell terakhir — bukan dari nol.
#
# Yang disimpan adalah ROW KASAR (hasil pengukuran mentah per run), bukan
# ringkasan: kalau aturan adjudikasi berubah, ringkasan dihitung ulang dari
# row yang sama tanpa mengulang benchmark. Row mentah harus lengkap —
# termasuk ``server_observed`` (bukti sisi server hanya ada selama run
# hidup) dan ``recorded_at`` + ``fixture_base_url`` (petunjuk kapan dan di
# mana run itu terjadi).
# ---------------------------------------------------------------------------


def _harness_fingerprint() -> str:
    """Sidik jari konfigurasi yang memengaruhi hasil pengukuran.

    Kalau skrip arm, skenario, jumlah run, timeout, atau definisi kebijakan
    recovery berubah, checkpoint lama TIDAK boleh dipakai ulang -- kalau
    dipakai, run lama dibandingkan dengan run baru memakai kriteria berbeda.
    Fingerprint membuat mismatch terlihat, bukan diam-diam menghasilkan
    angka campuran.
    """
    material = {
        "runs": RUNS,
        "arm_timeout_s": ARM_TIMEOUT_S,
        "scenarios": SCENARIOS,
        "arm_scripts": ARM_SCRIPTS,
        "arms": ARMS,
        "expected_body_sha256": EXPECTED_BODY_SHA256,
        "expected_body_bytes": EXPECTED_BODY_BYTES,
    }
    payload = json.dumps(material, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class _Checkpoint(Checkpoint):
    """Checkpoint E15 — implementasi tinggal di modul checkpoint bersama.

    Modul ``_checkpoint.py`` dipakai bersama oleh harness E14, E15, dan E16
    supaya penyimpanan run tidak punya tiga salinan yang bisa berbedadrift.
    Yang tetap milik E15 hanya sidik jari konfigurasi harness-nya, karena
    material yang di-fingerprint-kan berbeda per harness.
    """

    def __init__(self, path: Path):
        super().__init__(path, _harness_fingerprint())


# ---------------------------------------------------------------------------
# Parent: setup server state, jalankan arm, kumpulkan bukti
# ---------------------------------------------------------------------------


def _prepare_client_cookie(scenario: dict, server: FixtureServer) -> Optional[str]:
    """Setel state server dan tentukan cookie yang DIBERIKAN ke klien.

    State sesi fixture adalah state global server; setiap run dimulai dari
    ``reset_session()`` supaya semua arm dan semua run melihat kondisi yang
    identik. Tanpa ini, arm yang me-recovery akan mewarisi token milik arm
    sebelumnya dan perbandingannya jadi Apples-to-oranges.
    """
    server.reset_session()
    mode = scenario["cookie_mode"]
    if mode == "valid":
        return server.active_session_token
    if mode == "none":
        return None
    if mode == "stale":
        # Klien memegang cookie yang SAH, lalu server mencabutnya (rotasi
        # token) sebelum arm berjalan: dari sisi klien, cookie itu tak
        # berbeda dari cookie valid.
        stale = server.active_session_token
        server.expire_session()
        return stale
    raise ValueError("cookie_mode tidak dikenal: " + repr(mode))


def _server_evidence(request_log: List[dict]) -> Dict:
    """Ringkasan yang TERLIHAT di sisi server — bukan laporan arm."""
    protected = [entry for entry in request_log if entry["path"].startswith("/protected")]
    logins = [entry for entry in request_log if entry["path"].startswith("/session-login")]
    gets = [entry for entry in protected if entry["method"] == "GET"]
    return {
        "total_requests": len(request_log),
        "login_requests": len(logins),
        "protected_get_requests": len(gets),
        "protected_head_requests": len(
            [entry for entry in protected if entry["method"] == "HEAD"]
        ),
        "first_protected_status": protected[0]["status"] if protected else None,
        "final_protected_status": protected[-1]["status"] if protected else None,
        "cookies_seen_on_protected": [entry["cookie"] for entry in protected],
    }


def _assess_run(outcome: Dict, request_log: List[dict]) -> Dict:
    """Nilai satu run terhadap ground truth fixture.

    ``arm_reported_attempts`` SENGAJA TIDAK dibandingkan antar-lengan:
    UWAE menghitung attempt job di repository, sedangkan lengan Botasaurus
    menghitung jumlah pemanggilan HTTP di dalam arm — satuan berbeda. Metrik
    request yang COMPARABLE adalah ``server_observed.total_requests``,
    karena dihitung dari log yang benar-benar diterima server.
    """
    server_evidence = _server_evidence(request_log)
    status = outcome.get("status_code")
    body_sha = outcome.get("body_sha256")
    body_bytes = outcome.get("body_bytes")
    content_ok = status == 200 and body_sha == EXPECTED_BODY_SHA256
    row = {
        "status_code": status,
        "body_sha256": body_sha,
        "body_bytes": body_bytes,
        "content_ok": content_ok,
        "reached_protected": content_ok,
        "arm_reported_attempts": outcome.get("attempts"),
        "recovery_outcome": outcome.get("recovery_outcome"),
        "recovery_generation": outcome.get("recovery_generation"),
        "diagnosis_state": outcome.get("diagnosis_state"),
        "diagnosis_reason": outcome.get("diagnosis_reason"),
        "terminal_status": outcome.get("terminal_status"),
        "elapsed_ms": outcome.get("elapsed_ms"),
        "error": outcome.get("error"),
        "server_observed": server_evidence,
    }
    return row


def _summarise(rows: List[dict]) -> Dict:
    successes = [row for row in rows if row["reached_protected"]]
    latencies = [row["elapsed_ms"] for row in rows if row.get("elapsed_ms") is not None]
    arm_attempts = [
        row["arm_reported_attempts"] for row in rows if row.get("arm_reported_attempts") is not None
    ]
    server_requests = [
        row["server_observed"]["total_requests"] for row in rows
    ]
    recoveries = [row["recovery_outcome"] for row in rows if row.get("recovery_outcome")]
    return {
        "runs": len(rows),
        "reached_protected_runs": len(successes),
        "primary_success_rate": round(len(successes) / len(rows), 4) if rows else None,
        "runtime_failures": len([row for row in rows if row.get("error")]),
        "server_observed_login_requests": [
            row["server_observed"]["login_requests"] for row in rows
        ],
        "server_observed_final_protected_status": [
            row["server_observed"]["final_protected_status"] for row in rows
        ],
        "server_observed_total_requests": server_requests,
        "server_observed_total_requests_median": _median(server_requests),
        "arm_reported_attempts_max": max(arm_attempts) if arm_attempts else None,
        "recovery_outcomes": recoveries,
        "elapsed_ms_median": _median(latencies),
        "elapsed_ms_p95": _percentile(latencies, 0.95),
        "elapsed_ms_runs": latencies,
    }


def _run_scenario(
    scenario: dict,
    server: FixtureServer,
    base_url: str,
    checkpoint: Optional[Checkpoint] = None,
) -> Dict:
    """Jalankan semua arm untuk satu skenario.

    ``checkpoint`` opsional: bila diisi, run yang sudah selesai pada
    invocation sebelumnya diambil dari checkpoint dan subprocess TIDAK
    dijalankan lagi. Run yang dipakai ulang memakai instance fixture ASLINYA
    saat run itu terekam — base URL-nya dicatat per row, sehingga restart
    perangkat terlihat sebagai fakta di blok timing, bukan sekadar klaim.
    """
    origin = base_url.split("//", 1)[1]
    scenario_entry = {
        "scenario_id": scenario["id"],
        "description": scenario["description"],
        "expects_recovery": scenario["expects_recovery"],
        "ground_truth": {
            "expect_status": 200,
            "expect_body_sha256": EXPECTED_BODY_SHA256,
            "expect_body_bytes": EXPECTED_BODY_BYTES,
            "source": "semantika protokol fixture: /protected 200 hanya bila cookie sesi aktif",
        },
        "arms": {},
    }
    for arm_id, script in ARM_SCRIPTS.items():
        rows: List[dict] = []
        for run_index in range(RUNS):
            cached = (
                checkpoint.get(scenario["id"], arm_id, run_index)
                if checkpoint is not None
                else None
            )
            if cached is not None:
                # Row dari checkpoint adalah ROW KASAR yang sama persis dengan
                # yang akan masuk dokumen — termasuk bukti sisi server, waktu
                # rekam, dan instance fixture aslinya. Tidak ada field hilang.
                rows.append(cached)
                print(
                    "[E15] %-18s %-20s run %2d/%d  checkpoint"
                    % (scenario["id"], arm_id, run_index + 1, RUNS),
                    flush=True,
                )
                continue
            cookie_value = _prepare_client_cookie(scenario, server)
            server.request_log.clear()
            payload = {
                "base_url": base_url,
                "origin": origin,
                "target_url": base_url + "/protected",
                "login_url": base_url + "/session-login",
                "cookie_name": SESSION_COOKIE,
                "cookie_value": cookie_value,
            }
            payload_path = os.path.join(
                tempfile.mkdtemp(prefix="uwae-e15-payload-"), "payload.json"
            )
            out_path = payload_path + ".out"
            with open(payload_path, "w") as handle:
                json.dump(payload, handle)
            raw = _run_arm(script, payload_path, out_path, ARM_TIMEOUT_S)
            request_log = list(server.request_log)
            if raw.get("runtime_failure"):
                row = {
                    "status_code": None,
                    "body_sha256": None,
                    "body_bytes": None,
                    "content_ok": False,
                    "reached_protected": False,
                    "arm_reported_attempts": None,
                    "recovery_outcome": None,
                    "recovery_generation": None,
                    "diagnosis_state": None,
                    "diagnosis_reason": None,
                    "terminal_status": None,
                    "elapsed_ms": None,
                    "error": json.dumps(raw["runtime_failure"])[:400],
                    "server_observed": _server_evidence(request_log),
                }
            else:
                row = _assess_run(raw.get("outcome") or {}, request_log)
            row["run_index"] = run_index
            row["stdout_tail"] = raw.get("stdout_tail", "")[-400:]
            row["stderr_tail"] = raw.get("stderr_tail", "")[-400:]
            # Rekam waktu + instance fixture: dua fields yang hanya ada kalau
            # run benar-benar terjadi, dan yang membuat restart perangkat
            # bisa diaudit dari data — bukan diklaim.
            row["recorded_at"] = datetime.now(timezone.utc).isoformat()
            row["fixture_base_url"] = base_url
            rows.append(row)
            if checkpoint is not None:
                # Ditulis SETIAP run selesai (flush + fsync di modul bersama):
                # restart tidak boleh menghapus run yang sudah dibayar mahal
                # dengan waktu device.
                checkpoint.append(scenario["id"], arm_id, run_index, row)
            print(
                "[E15] %-18s %-20s run %2d/%d  ok=%-5s %8.1f ms"
                % (
                    scenario["id"],
                    arm_id,
                    run_index + 1,
                    RUNS,
                    str(row["reached_protected"]),
                    float(row.get("elapsed_ms") or 0.0),
                ),
                flush=True,
            )
        scenario_entry["arms"][arm_id] = {
            "recovery_policy": ARMS[arm_id]["recovery_policy"],
            "description": ARMS[arm_id]["description"],
            "runs": rows,
            "summary": _summarise(rows),
        }
    return scenario_entry


def _timing_evidence(
    scenarios: List[dict], checkpoint_stats: Dict, invocation_wall_clock_s: float
) -> Dict:
    """Durasi benchmark, diuraikan sehingga tidak bisa disalahbaca.

    Delegasi ke helper timing bersama (``benchmark/_checkpoint.py``); bentuk
    argumen E15 (daftar skenario) diterjemahkan jadi daftar run datar.
    """
    rows = [
        row
        for entry in scenarios
        for arm in entry["arms"].values()
        for row in arm["runs"]
    ]
    return timing_evidence(
        rows, checkpoint_stats, invocation_wall_clock_s, INTERRUPTION_GAP_THRESHOLD_S
    )


def _build_summary(scenarios: List[dict]) -> Dict:
    """Ringkasan dua sumbu: recovery otomatis vs alur eksplisit.

    Ringkasan ini SENGAJA tidak menyatakan "UWAE menang X vs Y" pada satu
    angka — karena angka tunggal akan menyembunyikan bahwa lengan
    ``botasaurus-explicit`` juga mencapai konten terproteksi.
    """
    primary = {
        arm_id: sum(
            scenario["arms"][arm_id]["summary"]["reached_protected_runs"]
            for scenario in scenarios
        )
        for arm_id in ARMS
    }
    total = RUNS * len(scenarios)
    recovery_axis = {}
    for arm_id in ARMS:
        reached = sum(
            scenario["arms"][arm_id]["summary"]["reached_protected_runs"]
            for scenario in scenarios
            if scenario["expects_recovery"]
        )
        recovery_total = RUNS * len(
            [scenario for scenario in scenarios if scenario["expects_recovery"]]
        )
        recovery_axis[arm_id] = {
            "recovery_policy": ARMS[arm_id]["recovery_policy"],
            "reached_protected_runs": reached,
            "of_runs": recovery_total,
            "rate": round(reached / recovery_total, 4) if recovery_total else None,
        }
    latencies = {}
    for arm_id in ARMS:
        values = []
        for scenario in scenarios:
            values.extend(scenario["arms"][arm_id]["summary"]["elapsed_ms_runs"])
        latencies[arm_id] = {
            "median_ms": _median(values),
            "p95_ms": _percentile(values, 0.95),
        }
    return {
        "primary_success_runs": primary,
        "of_total_runs": total,
        "automatic_recovery_axis": recovery_axis,
        "latency": latencies,
        "interpretation": (
            "E15 mengukur alur sesi lintas-implementasi pada kondisi device "
            "identik. Sumbu recovery OTOMATIS (tanpa kode per-skenario): "
            "UWAE mencapai resource terproteksi lewat kebijakan generik "
            "planner, sedangkan lengan Botasaurus yang tanpa kode recovery "
            "tidak. Sumbu alur EKSPLISIT: lengan botasaurus-explicit juga "
            "mencapai resource terproteksi bila recovery ditulis di dalam "
            "kode arm — jadi selisihnya adalah LETAK kebijakan (engine "
            "generik vs per-task), BUKAN kemampuan. Lengan "
            "botasaurus-explicit sengaja diikutsertakan agar perbandingan "
            "ini bukan pembanding yang sengaja dibuat lemah. Lengan "
            "botasaurus-decorator-request menjalankan kode recovery IDENTIK "
            "pada objek reqs bawaan dekorator, sehingga selisihnya terhadap "
            "botasaurus-explicit mengukur perilaku cookie objek dekorator "
            "Botasaurus — bukan selisih kapabilitas dan bukan cara "
            "melemahkan baseline. BUKAN klaim mengungguli Botasaurus — ini "
            "baseline yang dapat direproduksi."
        ),
    }


def main() -> None:
    _preflight()
    started = time.perf_counter()
    checkpoint = _Checkpoint(CHECKPOINT_PATH)
    if checkpoint.rows:
        print(
            "[E15] checkpoint: %d run tersedia untuk dipakai ulang, "
            "%d record diabaikan (fingerprint atau JSON tidak cocok)"
            % (len(checkpoint.rows), checkpoint.ignored_records),
            flush=True,
        )
    scenarios: List[dict] = []
    server = FixtureServer(port=0, record_requests=True)
    with server as base_url:
        for scenario in SCENARIOS:
            scenarios.append(
                _run_scenario(scenario, server, base_url, checkpoint=checkpoint)
            )

    base_urls = sorted(
        {
            row["fixture_base_url"]
            for entry in scenarios
            for arm in entry["arms"].values()
            for row in arm["runs"]
            if row.get("fixture_base_url")
        }
    )
    checkpoint_stats = checkpoint.stats()
    document = {
        "benchmark_id": BENCHMARK_ID,
        # Slot yang DIGANTIKAN oleh evidence ini. Dinyatakan DI DALAM evidence,
        # bukan di aggregator — supaya sumber kebenaran ikut travels bersama
        # buktinya, dan slot lama tidak bisa hilang tanpa jejak.
        "supersedes": SUPERSEDES,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        # Durasi TIDAK lagi berupa satu angka telanjang. Angka `elapsed_s`
        # tingkat dokumen hanya mengukur SATU pemanggilan harness — kalau
        # sebagian besar run diambil dari checkpoint, pembaca akan salah
        # menyimpulkan seluruh benchmark hanya memakan waktu itu. Jadi
        # durasi dipublikasikan sebagai blok timing yang menamai cakupannya:
        # durasi kerja terukur, rentang pengukuran, dan durasi pemanggilan
        # yang menulis dokumen ini.
        "timing": _timing_evidence(
            scenarios, checkpoint_stats, time.perf_counter() - started
        ),
        "environment": {
            "interpreter": _interpreter_identity(),
            "package_versions": _package_versions(),
            "identical_conditions": {
                "targets": True,
                "expected_outputs": True,
                "device_conditions": True,
                "run_counts": True,
                "success_criteria": True,
            },
            "fixture_base_urls": base_urls,
            "fixture_instance_count": len(base_urls),
            "percentile_note": _percentile_note(RUNS),
            "notes": (
                "Kedua arm berjalan sebagai subprocess dari interpreter yang "
                "sama dengan PYTHONPATH yang sama, melawan satu instance "
                "fixture server. Satu subprocess per run agar state sesi "
                "server bisa disetel ulang identik sebelum tiap run. "
                "Setiap run selesai langsung ditulis ke checkpoint JSONL di "
                "luar repo, jadi restart melanjutkan dari cell terakhir; run "
                "yang dipakai ulang memakai instance fixture ASLINYA, "
                "sehingga bila benchmark dihentikan dan dilanjutkan, jumlah "
                "instance fixture yang terpakai bisa lebih dari satu (lihat "
                "fixture_base_urls dan fixture_instance_count) — isi yang "
                "dilayani fixture tetap identik karena body sumbernya sama. "
                "Durasi benchmark dipublikasikan pada blok `timing`, bukan "
                "sebagai angka `elapsed_s` telanjang."
            ),
        },
        "arms": ARMS,
        "scenarios": scenarios,
        "summary": _build_summary(scenarios),
        "checkpoint": checkpoint_stats,
    }
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_PATH, "w") as handle:
        json.dump(document, handle, indent=2)

    print("=" * 78)
    print(f"{'scenario':<20}{'arm':<24}{'ok':>4}{'logins':>9}{'med ms':>10}")
    print("-" * 78)
    for scenario in scenarios:
        for arm_id in ARMS:
            summary = scenario["arms"][arm_id]["summary"]
            logins = summary["server_observed_login_requests"]
            print(
                f"{scenario['scenario_id']:<20}{arm_id:<24}"
                f"{summary['reached_protected_runs']:>2}/{summary['runs']:<2}"
                f"{str(logins):>9}{str(summary['elapsed_ms_median']):>10}"
            )
    print("=" * 78)
    print(json.dumps(document["summary"]["primary_success_runs"], indent=2))
    print(f"\nresults -> {RESULTS_PATH}")


if __name__ == "__main__":
    main()
