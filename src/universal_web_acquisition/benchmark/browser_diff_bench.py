"""E16 — Browser-arm differential: UWAE vs Botasaurus pada dimensi browser.

E14 mengukur alur HTTP; E15 mengukur alur sesi. Keduanya menutup dua gerbang
TEXT.md §9, tapi **dimensi browser belum pernah diukur lintas-implementasi**.
E14 sendiri mendeklarasikannya sebagai skenario tak didukung::

    {"scenario_id": "js_rendering_browser_arm",
     "reason": "Kedua arm di benchmark ini adalah arm HTTP. Rendering
                JavaScript butuh arm browser; Botasaurus memakai driver CDP
                (bukan chromedriver) dan UWAE memakai raw CDP (ADR-014) —
                keduanya belum diukur pada device ini, jadi tidak diklaim
                sebagai perbedaan engine."}

E16 menutup celah itu. Pertanyaan yang dijawab:

1. Apakah browser automation benar-benar bisa dijalankan di device Android/
   Termux ini — untuk KEDUA implementasi? (gerbang TEXT.md §9 #3)
2. Kapan HTTP-only lebih baik daripada membuka browser? (#4)
3. Di skenario mana masing-masing menang, seri, atau gagal? (#7)

Keputusan desain yang menentukan fairness:

- **Kriteria berbasis marker, bukan byte-for-byte.** Output browser adalah
  ``document.documentElement.outerHTML`` — doctype hilang, newline tambahan,
  sehingga TIDAK pernah byte-identik dengan body sumber. Kriteria byte-for-byte
  akan otomatis membuat browser gagal di SEMUA skenario, termasuk yang
  seharusnya ia menang. Karena itu tiap skenario punya ground truth dari
  *semantika protokol fixture* (marker wajib / terlarang), dan kriteria itu
  diterapkan IDENTIK ke semua lengan.

- **Tiga jenis kriteria, masing-masing dengan alasan yang dinyatakan.** Sumbu
  "body acquired" (kapabilitas), "byte faithful" (fidelitas byte mentah),
  dan "signal preserved" (apakah sinyal kegagalan terlihat). Kriteria primer
  per skenario dipilih dari semantika fixture, bukan dari mana pun yang
  kebetulan terlihat bagus.

- **Bukti sisi server, bukan laporan arm.** Fixture merekam setiap request yang
  benar-benar diterima — termasuk request sampingan ``/favicon.ico`` yang
  dilakukan chromium, jadi path breakdown wajib reported, bukan cuma total.

- **Satu subprocess per run.** State browser dan state server bisa bocor antar
  run; isolating subprocess memastikan tiap run mulai dari kondisi identik.
  Biayanya mahal (chromium ~4.6-7.1 s cold start per run) tapi itu justru
  biaya produksi yang harus diukur, bukan disembunyikan dengan warm reuse.
"""

import hashlib
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from universal_web_acquisition.benchmark._checkpoint import (
    Checkpoint,
    execution_sessions,
    timing_evidence,
)
from universal_web_acquisition.benchmark.cross_impl_bench import (
    _arm_env,
    _interpreter_identity,
    _median,
    _package_versions,
    _percentile,
    _preflight,
    _run_arm,
)
from universal_web_acquisition.benchmark.fixture_server import (
    GROUND_TRUTHS,
    FixtureServer,
)

BENCHMARK_ID = "e16-browser-arm-differential-001"
RESULTS_PATH = Path("/root/universal-web-acquisition/docs/benchmark/engine-results-e16.json")

# TEXT.md §6.3: "Minimal 30 pengulangan untuk skenario benchmark utama
# sebelum membandingkan performa." E14/E15 jalan di n=5 dan harus menyatakan
# p95-nya belum bermakna; E16 sejak awal memenuhi gerbang ini.
RUNS = 30

# Timeout per run: cold start chromium terukur 4.6-7.1 s (E4: 5432 ms), dan
# lengan botasaurus mungkin lebih lambat di device yang sama. 180 s memberi
# ruang tanpa membiarkan run gantung mengaburkan benchmark.
ARM_TIMEOUT_S = 180

# Ambang jeda antar-run yang dianggap INTERUPSI, bukan jeda normal. Jeda
# normal di device ini <= ~37 s (run UWAE dengan rantai retry + cold start
# chromium). Jeda jauh di atas itu berarti perangkat mati / harness restart,
# dan itu harus terlihat di evidence sebagai batas segmen eksekusi.
INTERRUPTION_GAP_THRESHOLD_S = 60.0

# Maksimum content yang dikembalikan arm ke parent — fixture kecil, tapi
# capping menjaga file payload tetap wajar.
MAX_CONTENT_CHARS = 20000

# Port CDP per lengan — tetap (run sekuensial), tapi TIDAK boleh sama antar
# lengan supaya tidak ada kontak tak terduga.
CDP_PORTS = {
    "uwae-adaptive": 9381,
    "uwae-browser-only": 9382,
    "botasaurus-browser": 9383,
}

# Checkpoint per run. Run penuh butuh ~2,7 jam; device Android/Termux bisa
# reboot atau sesi agent bisa di-restore, dan proses THEN mati tanpa jejak.
# Dulu evidence hanya ditulis di akhir main(), sehingga 393/480 run hilang
# sekali saja. Checkpoint JSONL ditulis SETIAP run selesai (flush + fsync),
# jadi restart melanjutkan dari cell terakhir — bukan dari nol.
#
# Path default DI LUAR repo supaya tidak ikut ter-commit.
CHECKPOINT_PATH = Path(
    os.environ.get("UWAE_E16_CHECKPOINT", "/root/.qwen/tmp/e16_checkpoint.jsonl")
)


# --------------------------------------------------------------------------
# Skenario + ground truth (dari semantika protokol fixture)
# --------------------------------------------------------------------------

SCENARIOS = [
    {
        "id": "b01_small_get",
        "path": "/html",
        "criterion": "body_acquired",
        "expect_status": 200,
        "required_markers": ["fixture-ok"],
        "forbidden_markers": [],
        "failure_signal": None,
        "description": (
            "HTML biasa tanpa JavaScript. Yang diukur di sini adalah BIAYA: "
            "HTTP-only seharusnya cukup dan jauh lebih murah daripada membuka "
            "browser — inilah kasus di mana HTTP menang."
        ),
    },
    {
        "id": "b07_js_render",
        "path": "/js",
        "criterion": "body_acquired",
        "expect_status": 200,
        "required_markers": ["rendered-by-js"],
        "forbidden_markers": ["please enable javascript"],
        "failure_signal": None,
        "description": (
            "Gerbang JavaScript: body mentah berisi teks 'please enable "
            "javascript', dan skrip mengganti isinya jadi 'rendered-by-js'. "
            "Hanya render browser yang menghasilkan konten target — inilah "
            "kasus di mana browser obligatory."
        ),
    },
    {
        "id": "a11_invalid_html",
        "path": "/invalid-html",
        "criterion": "signal_preserved",
        "expect_status": 200,
        "required_markers": [],
        "forbidden_markers": [],
        "failure_signal": {
            "kind": "invalid_content",
            "body_channel": "byte_faithful",
            "diagnosis_states": ["content_invalid"],
        },
        "description": (
            "Body 200 yang BUKAN HTML valid (byte biner). Semantika protokol "
            "fixture: 200 dengan body rusak BUKAN keberhasilan. Yang diuji "
            "adalah apakah sinyal 'konten rusak' TERTUTUP — browser yang "
            "merekonstruksi byte korup jadi HTML valid akan melaporkan "
            "access_granted/succeeded dan menutup sinyal (temuan E4). "
            "Byte mentah yang tiba apa adanya = sinyal terjaga."
        ),
    },
    {
        "id": "a07_challenge",
        "path": "/challenge",
        "criterion": "signal_preserved",
        "expect_status": 403,
        "required_markers": [],
        "forbidden_markers": ["just a moment", "checking your browser"],
        "failure_signal": {
            "kind": "challenge",
            "body_channel": "forbidden_markers",
            "diagnosis_states": ["challenge_present"],
        },
        "description": (
            "Interstitial challenge 403. Yang diuji BUKAN pemecahan challenge "
            "— tapi apakah sinyal challenge TERLIHAT dan tidak tertutup. "
            "Hipotesis yang diukur (bukan diasumsikan): merender ulang "
            "halaman challenge di browser bisa menutup signature-nya, "
            "sedangkan HTTP yang menerima body apa adanya tidak bisa."
        ),
    },
]

SCENARIO_IDS = [entry["id"] for entry in SCENARIOS]

# Body sumber per skenario — untuk sumbu "byte faithful".
SOURCE_BODIES = {
    "b01_small_get": GROUND_TRUTHS["b01_small_get"]["body"],
    "b07_js_render": GROUND_TRUTHS["b07_js_render"]["body"],
    "a11_invalid_html": GROUND_TRUTHS["a11_invalid_html"]["body"],
    "a07_challenge": GROUND_TRUTHS["a07_challenge"]["body"],
}


ARMS = {
    "uwae-adaptive": {
        "transport": "http_then_browser",
        "description": (
            "Jalur produksi UWAE: JobWorker default. HTTP dulu; browser "
            "hanya bila bukti diagnosis memintanya (gerbang JS). "
            "CDPBrowserAdapter keep_alive=False — satu siklus chromium per "
            "acquire, sama seperti jalur produksi."
        ),
    },
    "uwae-browser-only": {
        "transport": "browser_only",
        "description": (
            "Browser sebagai transport PERTAMA untuk setiap job — "
            "mengisolasi dimensi browser dari keputusan planner, supaya "
            "selisih dengan uwae-adaptive attributable pada strategi, bukan "
            "pada implementasi browser."
        ),
    },
    "botasaurus-http": {
        "transport": "http_only",
        "description": (
            "Baseline HTTP Botasaurus yang sudah TERBUKTI di E14 — jalur "
            "publik botasaurus_requests. Lengan ini menjadi pembanding "
            "apakah dimensi browser menambah kemampuan atau hanya menambah "
            "biaya."
        ),
    },
    "botasaurus-browser": {
        "transport": "browser_only",
        "description": (
            "Lengan browser Botasaurus via driver CDP publik. Diberi bentuk "
            "TERKUAT yang Botasaurus tawarkan; kalau lengan ini gagal, "
            "hanya bukti platform yang bisa disimpulkan — bukan kelemahan "
            "penulisan skrip."
        ),
    },
}


# Konfigurasi per lengan dicatat EKSPLISIT, bukan hanya diklaim lewat boolean
# ``identical_conditions``. Asimetri di sini adalah desain yang berbeda dari
# dua engine, bukan pilihan harness — dan supaya pembaca bisa mengauditnya.
#
# Catatan retry: UWAE memakai RetryPolicy(max_retries=2) sehingga planner
# escalate ke browser selama ``retry_attempt <= max_retries`` lalu berhenti
# di ``needs_user`` — batas 4 attempt. Botasaurus memakai default pustakanya
# (``max_retry`` tidak disetel) dan retry-nya HANYA menyala bila task melempar
# exception; ia tidak punya mekanisme yang bisa bereaksi pada sinyal yang
# TERDETEKSI (mis. challenge). Karena itu jumlah attempt per lengan pada
# skenario failure berbeda, dan itu terlihat langsung dari path breakdown
# sisi server.
ARM_CONFIGURATION = {
    "uwae-adaptive": {
        "transport": "http_then_browser",
        "retry": "RetryPolicy(max_retries=2, base_backoff_seconds=0.05) — batas 4 attempt",
        "browser_lifecycle": "CDPBrowserAdapter keep_alive=False — satu siklus chromium per acquire",
        "status_source": (
            "jalur HTTP: status dari respons HTTP; jalur browser: "
            "performance.getEntriesByType('navigation')[0].responseStatus "
            "(browser/cdp.py) dengan fallback 0->200 (browser/adapter.py)"
        ),
        "diagnosis_layer": "ada — AccessState/ReasonCode dari assessment",
    },
    "uwae-browser-only": {
        "transport": "browser_only",
        "retry": "RetryPolicy(max_retries=2, base_backoff_seconds=0.05) — batas 4 attempt",
        "browser_lifecycle": "CDPBrowserAdapter keep_alive=False — satu siklus chromium per acquire",
        "status_source": (
            "performance.getEntriesByType('navigation')[0].responseStatus "
            "(browser/cdp.py) dengan fallback 0->200 (browser/adapter.py)"
        ),
        "diagnosis_layer": "ada — AccessState/ReasonCode dari assessment",
    },
    "botasaurus-http": {
        "transport": "http_only",
        "retry": "default Botasaurus (max_retry tidak disetel) — retry hanya bila task melempar exception",
        "browser_lifecycle": "tidak ada browser",
        "status_source": "r.status_code dari respons HTTP",
        "diagnosis_layer": "tidak ada",
    },
    "botasaurus-browser": {
        "transport": "browser_only",
        "retry": "default Botasaurus (max_retry tidak disetel) — retry hanya bila task melempar exception",
        "browser_lifecycle": "satu siklus chromium per run (@browser, cache=False, reuse_driver=False)",
        "status_source": (
            "performance.getEntriesByType('navigation')[0].responseStatus via "
            "Tab.evaluate — botasaurus_driver tidak mengekspos status HTTP; "
            "TIDAK ada fallback 0->200 (botasaurus mencatat 0 apa adanya)"
        ),
        "diagnosis_layer": "tidak ada",
    },
}

# Kondisi yang berlaku untuk SEMUA lengan — dicatat supaya pembaca bisa
# mengaudit headroom timeout dan urutan eksekusi, bukan hanya diberi klaim
# "kondisinya identik".
HARNESS_CONDITIONS = {
    "timeout_s": ARM_TIMEOUT_S,
    "timeout_note": (
        "Batas atas per run, sama untuk keempat lengan. Run yang menyentuh "
        "batas ini TIDAK diberi kredit dan tidak dihukum sebagai kegagalan "
        "kapabilitas: ia dikeluarkan dari penyebut kapabilitas dan "
        "dipublikasikan sebagai belum-teruji (TEXT.md:1427)."
    ),
    "run_order": (
        "skenario luar -> lengan dalam -> run; lengan dijalan berurutan "
        "(blocking), tidak diinterleaving. Drift termal perangkat pada run "
        "terakhir tidak dikendalikan dan tidak direkam."
    ),
    "observed_headroom": (
        "run sah terlambat yang terukur: UWAE a07_challenge ~21-26 s "
        "(empat percobaan berantai), cold start browser Botasaurus ~6-10 s. "
        "Batas 180 s memberi headroom sekitar 7x di atas jalur terlemah "
        "UWAE dan 18x di atas cold start Botasaurus."
    ),
}


# ---------------------------------------------------------------------------
# Arm scripts
#
# Semua arm mengembalikan KONTRAK YANG SAMA. Konten dikembalikan sebagai teks
# (bukan hanya sha256) karena kriteria marker harus dinilai di SATU tempat —
# parent — supaya tidak ada lengan yang bisa punya kriteria sendiri.
# ---------------------------------------------------------------------------

UWAE_ARMS = {
    "uwae-adaptive": {"initial_transport": None, "browser": True},
    "uwae-browser-only": {"initial_transport": "browser", "browser": True},
}

_UWAE_TEMPLATE = r'''
import asyncio
import hashlib
import json
import os
import sys
import tempfile
import time

payload = json.load(open(sys.argv[1]))
out_path = sys.argv[2]

from universal_web_acquisition.artifact.storage import FilesystemArtifactStorage
from universal_web_acquisition.browser.adapter import BROWSER_NAME, CDPBrowserAdapter
from universal_web_acquisition.core.job_model import Job
from universal_web_acquisition.core.job_repository import JobRepository
from universal_web_acquisition.core.job_worker import JobWorker
from universal_web_acquisition.http_transport.registry import RetryPolicy

MAX_CONTENT_CHARS = __MAX_CONTENT_CHARS__
INITIAL_TRANSPORT = __INITIAL_TRANSPORT__


def _detail(event):
    try:
        return json.loads(event.get("detail") or "{}")
    except (TypeError, ValueError):
        return {}


started = time.perf_counter()
row = {
    "status_code": None,
    "body_sha256": None,
    "body_bytes": None,
    "content": "",
    "browser_used": False,
    "diagnosis_state": None,
    "diagnosis_reason": None,
    "terminal_status": None,
    "error": None,
}

fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(fd)
repo = JobRepository(db_path=db_path)
storage = FilesystemArtifactStorage(base_path=tempfile.mkdtemp(prefix="uwae-e16-"))

browser_adapter = None
if __HAS_BROWSER__:
    browser_adapter = CDPBrowserAdapter(
        port=__CDP_PORT__,
        keep_alive=False,
        render_timeout=15.0,
        start_timeout=30.0,
    )

worker = JobWorker(
    repo,
    scheduler=None,
    storage=storage,
    retry_policy=RetryPolicy(max_retries=2, base_backoff_seconds=0.05),
    browser_adapter=browser_adapter,
    initial_transport=INITIAL_TRANSPORT,
)

job = Job(job_id="e16-browser", url=payload["target_url"])
repo.save_job(job)
try:
    asyncio.run(worker._execute_job(job))
    final = repo.get_job(job.job_id)
    events = repo.list_events(job.job_id)
    attempts = repo.list_attempts(job.job_id)

    if final is not None and final.artifact_id:
        artifact = asyncio.run(storage.retrieve(final.artifact_id))
        if artifact is not None:
            row["status_code"] = artifact.status_code
            row["body_sha256"] = hashlib.sha256(artifact.content).hexdigest()
            row["body_bytes"] = len(artifact.content)
            row["content"] = artifact.content.decode("utf-8", "replace")[:MAX_CONTENT_CHARS]

    # Browser benar-benar dipakai? Dibaca dari JEJAK attempt (kolom transport),
    # bukan dari asumsi arm — ini bukti, bukan klaim.
    row["browser_used"] = any(a.get("transport") == BROWSER_NAME for a in attempts)
    for event in events:
        if event["event"] == "assessment":
            detail = _detail(event)
            row["diagnosis_state"] = detail.get("state")
            row["diagnosis_reason"] = detail.get("reason_code")
    if final is not None:
        row["terminal_status"] = getattr(final.status, "value", None) or str(final.status)
except Exception as exc:
    row["error"] = (type(exc).__name__ + ": " + str(exc))[:400]
finally:
    if browser_adapter is not None:
        browser_adapter.close()

row["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
with open(out_path, "w") as handle:
    json.dump({"engine_id": __ENGINE_ID__, "outcome": row}, handle)
'''


def _uwae_script(engine_id: str, initial_transport: Optional[str], has_browser: bool) -> str:
    return (
        _UWAE_TEMPLATE
        .replace("__MAX_CONTENT_CHARS__", str(MAX_CONTENT_CHARS))
        .replace("__INITIAL_TRANSPORT__", repr(initial_transport))
        .replace("__HAS_BROWSER__", "True" if has_browser else "False")
        .replace("__CDP_PORT__", str(CDP_PORTS.get(engine_id, 9381)))
        .replace("__ENGINE_ID__", repr(engine_id))
    )


UWAE_ADAPTIVE_ARM_SCRIPT = _uwae_script("uwae-adaptive", None, True)
UWAE_BROWSER_ONLY_ARM_SCRIPT = _uwae_script("uwae-browser-only", "browser", True)


BOTASAURUS_HTTP_ARM_SCRIPT = r'''
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
    """Satu request HTTP lewat API publik Botasaurus.

    `Session()` eksplisit + `headers={}` — jalur yang sudah TERBUKTI di E14
    (versi `botasaurus_requests.get(url)` tanpa header selalu gagal dengan
    KeyError('headers'), dan itu bug pemanggil, bukan batas platform).
    """
    try:
        session = Session()
        r = session.get(item["url"], timeout=15, headers={})
        return {
            "status_code": r.status_code,
            "body_sha256": hashlib.sha256(r.content).hexdigest(),
            "body_bytes": len(r.content),
            "content": r.content.decode("utf-8", "replace")[:__MAX_CONTENT_CHARS__],
        }
    except Exception as exc:
        return {"error": (type(exc).__name__ + ": " + str(exc))[:300]}


started = time.perf_counter()
outcome = acquire([{"url": payload["target_url"]}])
elapsed_ms = (time.perf_counter() - started) * 1000
row = dict(outcome[0]) if outcome and isinstance(outcome[0], dict) else {}
row["browser_used"] = False
row["diagnosis_state"] = None
row["diagnosis_reason"] = None
row["terminal_status"] = None
row["elapsed_ms"] = round(elapsed_ms, 2)
row.setdefault("content", "")

with open(out_path, "w") as handle:
    json.dump({"engine_id": "botasaurus-http", "outcome": row}, handle)
'''.replace("__MAX_CONTENT_CHARS__", str(MAX_CONTENT_CHARS))


BOTASAURUS_BROWSER_ARM_SCRIPT = r'''
import hashlib
import json
import sys
import time

payload = json.load(open(sys.argv[1]))
out_path = sys.argv[2]

from botasaurus.browser_decorator import browser


@browser(
    output=None,
    cache=False,
    create_error_logs=False,
    raise_exception=False,
    close_on_crash=True,
    headless=True,
    chrome_executable_path="/usr/bin/chromium",
    add_arguments=["--no-sandbox", "--disable-dev-shm-usage"],
    port=__CDP_PORT__,
)
def acquire(driver, item):
    """Satu navigasi lewat driver CDP publik Botasaurus.

    Bentuk lengan ini adalah bentuk TERKUAT yang Botasaurus tawarkan:
    `@browser` + `driver.get` + `tab.get_content` + `tab.evaluate`.

    Dua piège API yang sudah terverifikasi empiris (probe #1-#3) dan karena
    itu harus ditangani eksplisit di dalam skrip:

    1. `Tab.evaluate` menyisipkan ekspresi ke dalam body blok
       `(() => { ... })()`. Ekspresi tanpa `return` dievaluasi menjadi
       `undefined`, lalu `json.loads("{}").get("x")` mengembalikan None —
       termasuk untuk `document.readyState`. Karena itu setiap ekspresi
       diawali `return`.
    2. `raise_exception=False` membuat dekorator menelan exception dan
       mengembalikan None, sehingga error tidak bisa diamati dari luar.
       Semua exception karena itu ditangkap DI DALAM task dan dikembalikan
       sebagai bagian dari outcome.

    `botasaurus_driver` tidak mengekspos status HTTP sama sekali, jadi status
    dibaca lewat `performance.getEntriesByType('navigation')[0].responseStatus`
    — mekanisme yang PERSIS sama dengan yang dipakai UWAE, sehingga
    adjudikasi tetap adil dan bukan privilege salah satu lengan.
    """
    try:
        tab = driver.get(item["url"], timeout=60)
        content = tab.get_content()
        raw_status = tab.evaluate(
            "return String((performance.getEntriesByType('navigation')[0] || {}).responseStatus || 0)"
        )
        try:
            status_code = int(raw_status)
        except (TypeError, ValueError):
            status_code = None
        body = content.encode("utf-8", "replace")
        return {
            "status_code": status_code,
            "body_sha256": hashlib.sha256(body).hexdigest(),
            "body_bytes": len(body),
            "content": content[:__MAX_CONTENT_CHARS__],
        }
    except Exception as exc:
        return {"error": (type(exc).__name__ + ": " + str(exc))[:300]}


started = time.perf_counter()
# `@browser` mengembalikan result[0] (dict hasil task) bila data bukan list.
outcome = acquire({"url": payload["target_url"]})
elapsed_ms = (time.perf_counter() - started) * 1000
row = dict(outcome) if isinstance(outcome, dict) else {}
row["browser_used"] = True
row["diagnosis_state"] = None
row["diagnosis_reason"] = None
row["terminal_status"] = None
row["elapsed_ms"] = round(elapsed_ms, 2)
row.setdefault("content", "")
row.setdefault("status_code", None)
row.setdefault("body_sha256", None)
row.setdefault("body_bytes", None)
row.setdefault("error", None)

with open(out_path, "w") as handle:
    json.dump({"engine_id": "botasaurus-browser", "outcome": row}, handle)
'''.replace("__MAX_CONTENT_CHARS__", str(MAX_CONTENT_CHARS)).replace(
    "__CDP_PORT__", str(CDP_PORTS["botasaurus-browser"])
)


ARM_SCRIPTS = {
    "uwae-adaptive": UWAE_ADAPTIVE_ARM_SCRIPT,
    "uwae-browser-only": UWAE_BROWSER_ONLY_ARM_SCRIPT,
    "botasaurus-http": BOTASAURUS_HTTP_ARM_SCRIPT,
    "botasaurus-browser": BOTASAURUS_BROWSER_ARM_SCRIPT,
}


# ---------------------------------------------------------------------------
# Perbandingan yang dihitung
#
# ``uwae-browser-only`` vs ``botasaurus-browser`` adalah perbandingan yang
# PALING apples-to-apples: dua implementasi browser, transport sama, kriteria
# sama. Dua lainnya menguji apakah dimensi browser menambah kemampuan
# (adaptive vs http) dan apakah engine lebih baik di kelas yang sama.
# ---------------------------------------------------------------------------

COMPARISONS = [
    ("uwae-adaptive", "botasaurus-http"),
    ("uwae-adaptive", "botasaurus-browser"),
    ("uwae-browser-only", "botasaurus-browser"),
]


# ---------------------------------------------------------------------------
# Checkpoint per-run
#
# Run penuh butuh ~2,7 jam; device Android/Termux bisa reboot atau sesi agent
# bisa di-restore, dan proses THEN mati tanpa jejak. Dulu evidence hanya
# ditulis di akhir main(), sehingga 393/480 run hilang sekali saja.
#
# Checkpoint JSONL ditulis SETIAP run selesai (flush + fsync), jadi restart
# melanjutkan dari cell terakhir — bukan dari nol. Yang disimpan adalah ROW
# KASAR (hasil pengukuran mentah per run), bukan ringkasan: kalau aturan
# adjudikasi berubah, ringkasan dihitung ulang dari row yang sama tanpa
# mengulang benchmark.
# ---------------------------------------------------------------------------


def _harness_fingerprint() -> str:
    """Sidik jari konfigurasi yang memengaruhi hasil pengukuran.

    Kalau skrip arm, skenario, jumlah run, atau timeout berubah, checkpoint
    lama TIDAK boleh dipakai ulang -- kalau dipakai, run lama dibandingkan
    dengan run baru memakai kriteria berbeda. Fingerprint membuat mismatch
    terlihat, bukan diam-diam menghasilkan angka campuran.
    """
    material = {
        "runs": RUNS,
        "arm_timeout_s": ARM_TIMEOUT_S,
        "max_content_chars": MAX_CONTENT_CHARS,
        "cdp_ports": CDP_PORTS,
        "scenarios": SCENARIOS,
        "arm_scripts": ARM_SCRIPTS,
        "source_bodies": {
            key: hashlib.sha256(
                value if isinstance(value, bytes) else value.encode("utf-8")
            ).hexdigest()
            for key, value in SOURCE_BODIES.items()
        },
    }
    payload = json.dumps(material, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class _Checkpoint(Checkpoint):
    """Checkpoint E16 — implementasi tinggal di modul checkpoint bersama.

    Modul ``_checkpoint.py`` dipakai bersama oleh harness E14, E15, dan E16
    supaya penyimpanan run tidak punya tiga salinan yang bisa berbedadrift.
    Yang tetap milik E16 hanya sidik jari konfigurasi harness-nya, karena
    material yang di-fingerprint-kan berbeda per harness.
    """

    def __init__(self, path: Path):
        super().__init__(path, _harness_fingerprint())


# ---------------------------------------------------------------------------
# Bukti sisi server
# ---------------------------------------------------------------------------


def _server_evidence(request_log: List[dict], scenario_path: str) -> Dict:
    """Ringkasan request yang benar-benar diterima server.

    Chromium melakukan request sampingan (``/favicon.ico``) selain navigasi.
    Karena itu path breakdown dilaporkan, bukan cuma total — kalau tidak,
    "2 request" untuk HTTP vs browser akan terlihat sebagai selisih biaya yang
    palsu.
    """
    breakdown: Dict[str, int] = {}
    for entry in request_log:
        path = entry["path"]
        breakdown[path] = breakdown.get(path, 0) + 1
    scenario_requests = [
        entry for entry in request_log if entry["path"].startswith(scenario_path)
    ]
    incidental = [
        entry for entry in request_log if not entry["path"].startswith(scenario_path)
    ]
    return {
        "total_requests": len(request_log),
        "scenario_requests": len(scenario_requests),
        "incidental_requests": len(incidental),
        "path_breakdown": breakdown,
        "scenario_statuses": [entry["status"] for entry in scenario_requests],
        "first_status": scenario_requests[0]["status"] if scenario_requests else None,
        "final_status": scenario_requests[-1]["status"] if scenario_requests else None,
    }


# ---------------------------------------------------------------------------
# Penilaian run — kriteria IDENTIK untuk semua lengan
# ---------------------------------------------------------------------------


def _assess_run(scenario: dict, outcome: Dict, request_log: List[dict]) -> Dict:
    """Nilai satu run terhadap ground truth skenario.

    Tiga sumbu ortogonal, dihitung dari ground truth fixture dan diterapkan
    IDENTIK ke semua lengan:

    - ``body_acquired`` — body target benar-benar diperoleh: status sesuai,
      marker wajib ada, marker terlarang tidak ada. Sumbu KAPABILITAS.
    - ``byte_faithful`` — body yang diperoleh identik byte-per-byte dengan
      body sumber. Sumbu FIDELITAS; menangkap browser yang merekonstruksi
      byte mentah. ``None`` bila lengan tidak delivers body sama sekali —
      "tidak ada yang diukur", bukan "fidelitas gagal".
    - ``signal_preserved`` — sinyal kegagalan yang dideklarasikan skenario
      tetap TERLIHAT bagi konsumen. Dijawab lewat kanal yang memang dimiliki
      lengan: kanal BODY (signature atau byte mentah terlihat di body) ATAU
      kanal DIAGNOSIS (lengan melaporkan diagnosis kegagalan). ``None`` bila
      skenario tidak punya sinyal kegagalan.

    Kanal yang dipakai ikut dicatat (``signal_channel``) supaya laporan bisa
    menyebut DARI MANA sinyal itu terlihat — perbedaan kanal adalah
    perbedaan arsitektur, bukan perbedaan kemampuan, dan tidak boleh
    disembunyikan di balik satu angka.

    Kriteria PRIMER per skenario ditentukan oleh ``scenario["criterion"]``,
    dipilih dari semantika fixture — bukan dari mana pun yang kebetulan
    terlihat bagus.
    """
    content = outcome.get("content") or ""
    lowered = content.lower()
    status = outcome.get("status_code")
    body_sha = outcome.get("body_sha256")

    source_body = SOURCE_BODIES.get(scenario["id"])
    source_sha = hashlib.sha256(source_body).hexdigest() if source_body else None

    marker_hits = {
        marker: (marker.lower() in lowered) for marker in scenario["required_markers"]
    }
    forbidden_hits = {
        marker: (marker.lower() in lowered) for marker in scenario["forbidden_markers"]
    }
    status_ok = status == scenario["expect_status"]

    body_acquired = bool(
        status_ok
        and all(marker_hits.values())
        and not any(forbidden_hits.values())
    )
    if body_sha is None:
        byte_faithful = None
    else:
        byte_faithful = bool(body_sha == source_sha)

    failure_signal = scenario.get("failure_signal")
    signal_channel = None
    signal_preserved = None
    if failure_signal:
        body_channel = False
        if failure_signal["body_channel"] == "forbidden_markers":
            body_channel = bool(
                status_ok and forbidden_hits and all(forbidden_hits.values())
            )
        elif failure_signal["body_channel"] == "byte_faithful":
            body_channel = bool(
                status_ok and body_sha is not None and body_sha == source_sha
            )
        diagnosis_channel = (
            outcome.get("diagnosis_state") in failure_signal["diagnosis_states"]
        )
        if body_channel:
            signal_channel = "body"
        elif diagnosis_channel:
            signal_channel = "diagnosis"
        signal_preserved = bool(body_channel or diagnosis_channel)

    # "Melaporkan sukses padahal sinyal kegagalan tertutup" — turunan dari
    # sumbu di atas, bukan sumbu terpisah: lengkap hanya kalau lengan
    # mengirim body yang SRUPPANYA menyamar sebagai konten target.
    false_success = bool(
        failure_signal and body_acquired and not signal_preserved
    )

    axes = {
        "body_acquired": body_acquired,
        "byte_faithful": byte_faithful,
        "signal_preserved": signal_preserved,
    }
    primary = axes[scenario["criterion"]]

    return {
        "status_code": status,
        "body_sha256": body_sha,
        "body_bytes": outcome.get("body_bytes"),
        "browser_used": bool(outcome.get("browser_used")),
        "diagnosis_state": outcome.get("diagnosis_state"),
        "diagnosis_reason": outcome.get("diagnosis_reason"),
        "terminal_status": outcome.get("terminal_status"),
        "elapsed_ms": outcome.get("elapsed_ms"),
        "error": outcome.get("error"),
        "required_marker_hits": marker_hits,
        "forbidden_marker_hits": forbidden_hits,
        "signal_channel": signal_channel,
        "false_success_reported": false_success,
        "axes": axes,
        "primary_criterion": scenario["criterion"],
        "primary_success": primary,
        "server_observed": _server_evidence(request_log, scenario["path"]),
    }


def _row_is_untested(row: dict) -> bool:
    """Run yang TIDAK bisa dinilai kapabilitasnya.

    Dua sumber, dan keduanya bermakna "tidak ada yang diukur":

    1. Runtime failure -- harness tidak bisa mengeksekusi arm (timeout atau
       keluar-nonzero). Tidak ada respons yang pernah diamati.
    2. Arm melaporkan error tanpa menghasilkan body maupun status -- misalnya
       chromium gagal start atau driver tidak berhasil konek. Yang gagal
       adalah EKSEKUSI lengan, bukan kapabilitas engine.

    Run yang diagnosis-nya sengaja tidak punya body (challenge_present ->
    needs_user, content_invalid -> failed) TIDAK masuk kategori ini: tidak
    ada error pada run itu, dan diagnosis tersebut justru sinyal yang sedang
    diukur.

    TEXT.md:1427 meminta hasil menang/seri/kalah/"belum teruji" dipublikasikan
    terpisah. Run yang tidak teruji tidak boleh masuk penyebut capability
    denominator, karena tidak ada respons yang bisa dinilai -- menghitungnya
    sebagai "gagal" akan menghukum lengan karena masalah eksekusi, bukan
    karena kemampuan engine.
    """
    if row.get("runtime_failure"):
        return True
    if (
        row.get("error")
        and row.get("body_sha256") is None
        and row.get("status_code") is None
    ):
        return True
    if (
        not row.get("error")
        and row.get("body_sha256") is None
        and row.get("status_code") is None
        and row.get("diagnosis_state") is None
        and row.get("terminal_status") is None
    ):
        # Lengan mengembalikan outcome KOSONG: tidak ada error, tidak ada body,
        # tidak ada status, tidak ada diagnosis, tidak ada terminal status.
        # Untuk lengan Botasaurus ini persis yang terjadi ketika dekorator
        # menelan exception dan mengembalikan None (`raise_exception=False`),
        # sehingga tidak ada error yang bisa diamati dari luar. Yang terjadi
        # adalah lengan TIDAK JALAN — bukan lengan yang gagal marvelous.
        # Menghitungnya sebagai "gagal" akan menghukum lengan karena eksekusi.
        return True
    return False


def _summarise(rows: List[dict]) -> Dict:
    """Ringkasan per sel (skenario x lengan).

    Denominator kapabilitas HANYA berisi run yang dievaluasi. Run "belum
    teruji" (lihat :func:`_row_is_untested`) dipublikasikan terpisah sebagai
    ``untested_runs``, sesuai TEXT.md:1427.
    """
    untested = [row for row in rows if _row_is_untested(row)]
    evaluated = [row for row in rows if not _row_is_untested(row)]
    successes = [row for row in evaluated if row["primary_success"]]
    latencies = [
        row["elapsed_ms"] for row in evaluated if row.get("elapsed_ms") is not None
    ]
    scenario_requests = [
        row["server_observed"]["scenario_requests"] for row in evaluated
    ]
    content_acquired = [row for row in evaluated if row["axes"]["body_acquired"]]
    byte_faithful = [
        row for row in evaluated if row["axes"]["byte_faithful"] is True
    ]
    byte_faithful_applicable = [
        row for row in evaluated if row["axes"]["byte_faithful"] is not None
    ]
    signal_rows = [
        row for row in evaluated if row["axes"]["signal_preserved"] is not None
    ]
    signal_preserved = [row for row in signal_rows if row["axes"]["signal_preserved"]]
    signal_channels = {}
    for row in signal_rows:
        channel = row.get("signal_channel") or "none"
        signal_channels[channel] = signal_channels.get(channel, 0) + 1
    return {
        "runs": len(rows),
        "evaluated_runs": len(evaluated),
        "untested_runs": len(untested),
        "primary_success_runs": len(successes),
        "primary_success_rate": (
            round(len(successes) / len(evaluated), 4) if evaluated else None
        ),
        "primary_success_rate_over_all_attempts": (
            round(len(successes) / len(rows), 4) if rows else None
        ),
        "runtime_failures": len(
            [row for row in rows if row.get("runtime_failure")]
        ),
        "arm_errors": len([row for row in rows if row.get("error")]),
        "browser_used_runs": len([row for row in evaluated if row["browser_used"]]),
        "body_acquired_runs": len(content_acquired),
        "byte_faithful_runs": len(byte_faithful),
        "byte_faithful_applicable_runs": len(byte_faithful_applicable),
        "signal_preserved_runs": (
            len(signal_preserved) if signal_rows else None
        ),
        "signal_preserved_applicable_runs": len(signal_rows),
        "signal_channel_counts": signal_channels,
        "false_success_runs": len(
            [row for row in evaluated if row.get("false_success_reported")]
        ),
        "server_observed_scenario_requests": scenario_requests,
        "server_observed_scenario_requests_median": _median(scenario_requests),
        "elapsed_ms_median": _median(latencies),
        "elapsed_ms_p95": _percentile(latencies, 0.95),
        "elapsed_ms_runs": latencies,
        # Run yang tidak bisa dievaluasi tidak punya latensi yang terukur, jadi
        # p95 di atas bisa MENYENSOR ekor yang paling informatif — lengan yang
        # timeout tampak lebih cepat. Karena itu jumlah run tersensor
        # dipublikasikan eksplisit, dan p95 konservatif dihitung dengan
        # menyensor run tersebut pada batas timeout (batas atas yang mungkin).
        "latency_censored_runs": len(untested),
        "timeout_cap_s": ARM_TIMEOUT_S,
        "elapsed_ms_p95_with_censored_at_cap": _percentile(
            latencies + [ARM_TIMEOUT_S * 1000.0] * len(untested), 0.95
        ),
    }


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _run_scenario(
    scenario: dict,
    server: FixtureServer,
    base_url: str,
    checkpoint: Optional[_Checkpoint] = None,
) -> Dict:
    """Jalankan semua lengan untuk satu skenario.

    Satu subprocess per run: state browser dan state server bisa bocor antar
    run, dan isolating subprocess memastikan tiap run mulai dari kondisi
    identik. Biayanya mahal (cold start chromium per run) — tapi itu biaya
    produksi yang harus diukur, bukan disembunyikan dengan warm reuse.

    Kalau ``checkpoint`` diisi, run yang sudah selesai pada sesi sebelumnya
    diambil dari checkpoint dan TIDAK dieksekusi ulang. Row yang dipakai ulang
    tetap membawa base_url dan waktu rekam aslinya, jadi jejaknya auditable
    dan bukan angka tanpa asal-usul.
    """
    source_body = SOURCE_BODIES.get(scenario["id"])
    scenario_entry = {
        "scenario_id": scenario["id"],
        "description": scenario["description"],
        "primary_criterion": scenario["criterion"],
        "ground_truth": {
            "expect_status": scenario["expect_status"],
            "required_markers": scenario["required_markers"],
            "forbidden_markers": scenario["forbidden_markers"],
            "source_body_sha256": (
                hashlib.sha256(source_body).hexdigest() if source_body else None
            ),
            "source": (
                "semantika protokol fixture: marker wajib/terlarang diturunkan "
                "dari body yang benar-benar dilayani fixture, bukan dari "
                "output engine mana pun"
            ),
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
                rows.append(cached)
                print(
                    "[E16] %-18s %-20s run %2d/%d  checkpoint        primary=%-5s"
                    % (
                        scenario["id"],
                        arm_id,
                        run_index + 1,
                        RUNS,
                        str(cached.get("primary_success")),
                    ),
                    flush=True,
                )
                continue
            server.request_log.clear()
            payload = {"target_url": base_url + scenario["path"]}
            payload_path = os.path.join(
                tempfile.mkdtemp(prefix="uwae-e16-payload-"), "payload.json"
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
                    "browser_used": False,
                    "diagnosis_state": None,
                    "diagnosis_reason": None,
                    "terminal_status": None,
                    "elapsed_ms": None,
                    "error": json.dumps(raw.get("runtime_failure"))[:400],
                    "runtime_failure": raw.get("runtime_failure"),
                    "required_marker_hits": {},
                    "forbidden_marker_hits": {},
                    "signal_channel": None,
                    "false_success_reported": False,
                    "axes": {
                        "body_acquired": None,
                        "byte_faithful": None,
                        "signal_preserved": None,
                    },
                    "primary_criterion": scenario["criterion"],
                    "primary_success": None,
                    "server_observed": _server_evidence(request_log, scenario["path"]),
                    "run_index": run_index,
                }
            else:
                row = _assess_run(scenario, raw.get("outcome") or {}, request_log)
                row["run_index"] = run_index
                row["runtime_failure"] = None
                if _row_is_untested(row):
                    # Lengan gagal dieksekusi, bukan gagal berkemampuan.
                    # Sumbu dinetralkan supaya row ini tidak pernah terbaca
                    # sebagai "gagal" pada ringkasan mana pun.
                    row["axes"] = {
                        "body_acquired": None,
                        "byte_faithful": None,
                        "signal_preserved": None,
                    }
                    row["primary_success"] = None
                    row["signal_channel"] = None
                    row["false_success_reported"] = False
            row["recorded_at"] = datetime.now(timezone.utc).isoformat()
            row["fixture_base_url"] = base_url
            rows.append(row)
            if checkpoint is not None:
                checkpoint.append(scenario["id"], arm_id, run_index, row)
            print(
                "[E16] %-18s %-20s run %2d/%d  primary=%-5s browser=%-5s %8.1f ms"
                % (
                    scenario["id"],
                    arm_id,
                    run_index + 1,
                    RUNS,
                    str(row["primary_success"]),
                    str(row["browser_used"]),
                    float(row.get("elapsed_ms") or 0.0),
                ),
                flush=True,
            )
        scenario_entry["arms"][arm_id] = {
            "runs": rows,
            "summary": _summarise(rows),
        }
    return scenario_entry


def _comparison_outcome(uwae: dict, baseline: dict) -> str:
    """Vonis perbandingan, diuji pada DUA batas.

    Batas 1 -- tingkat sukses atas run yang DIEVALUASI: "dari run yang punya
    respons, seberapa banyak yang berhasil?"
    Batas 2 -- tingkat sukses atas SELURUH attempt: "dari semua yang
    dicoba, seberapa banyak yang berhasil?"

    Kalau kedua batas memberi urutan yang SAMA, vonisnya pasti. Kalau
    urutannya BERBEDA, bukti yang ada tidak cukup untuk memilih salah satu,
    jadi vonisnya `not_comparable` — bukan diberikan ke lengan mana pun.
    Ini persis kasus "belum teruji" yang diminta TEXT.md:1427: timeout pada
    satu lengan bisa berarti lengan itu lebih lambat (batas-2 mendukung
    baseline), atau hanya masalah eksekusi (batas-1 mendukung UWAE), dan
    bukti yang ada tidak bisa memilih.

    Pada dataset bersih — tidak ada run yang belum teruji — kedua batas
    identik, jadi vonisnya sama dengan perbandingan jumlah absolut.

    `no_evaluable_runs` dipakai terpisah: satu sisi tidak punya run yang
    bisa dinilai sama sekali, jadi tidak ada yang bisa dibandingkan.
    """
    if uwae["evaluated_runs"] == 0 or baseline["evaluated_runs"] == 0:
        return "no_evaluable_runs"

    def order(left: dict, right: dict, denominator: str) -> int:
        left_den = left[denominator]
        right_den = right[denominator]
        if not left_den or not right_den:
            return 0
        left_rate = left["primary_success_runs"] / left_den
        right_rate = right["primary_success_runs"] / right_den
        if abs(left_rate - right_rate) < 1e-12:
            return 0
        return 1 if left_rate > right_rate else -1

    by_evaluated = order(uwae, baseline, "evaluated_runs")
    by_all_attempts = order(uwae, baseline, "runs")
    if by_evaluated != by_all_attempts:
        return "not_comparable"
    if by_evaluated > 0:
        return "uwae"
    if by_evaluated < 0:
        return "baseline"
    return "tie"


def _build_summary(scenarios: List[dict]) -> Dict:
    """Ringkasan + matriks menang/seri/kalah/belum-teruji (gerbang TEXT.md §9 #7)."""
    totals = {}
    for arm_id in ARMS:
        runs = 0
        evaluated = 0
        successes = 0
        untested = 0
        browser_runs = 0
        runtime_failures = 0
        arm_errors = 0
        latencies = []
        for entry in scenarios:
            summary = entry["arms"].get(arm_id, {}).get("summary")
            if not summary:
                continue
            runs += summary["runs"]
            evaluated += summary["evaluated_runs"]
            successes += summary["primary_success_runs"]
            untested += summary["untested_runs"]
            browser_runs += summary["browser_used_runs"]
            runtime_failures += summary["runtime_failures"]
            arm_errors += summary["arm_errors"]
            latencies.extend(summary["elapsed_ms_runs"])
        totals[arm_id] = {
            "runs": runs,
            "evaluated_runs": evaluated,
            "untested_runs": untested,
            "primary_success_runs": successes,
            "primary_success_rate": (
                round(successes / evaluated, 4) if evaluated else None
            ),
            "browser_used_runs": browser_runs,
            "runtime_failures": runtime_failures,
            "arm_errors": arm_errors,
            "latency_censored_runs": untested,
            "timeout_cap_s": ARM_TIMEOUT_S,
            "elapsed_ms_median": _median(latencies),
            "elapsed_ms_p95": _percentile(latencies, 0.95),
            "elapsed_ms_p95_with_censored_at_cap": _percentile(
                latencies + [ARM_TIMEOUT_S * 1000.0] * untested, 0.95
            ),
            "elapsed_ms_sample_runs": len(latencies),
        }

    comparisons = []
    for entry in scenarios:
        for uwae_arm, baseline_arm in COMPARISONS:
            uwae_data = entry["arms"].get(uwae_arm)
            baseline_data = entry["arms"].get(baseline_arm)
            if not uwae_data or not baseline_data:
                continue
            uwae_summary = uwae_data["summary"]
            baseline_summary = baseline_data["summary"]
            comparisons.append(
                {
                    "scenario_id": entry["scenario_id"],
                    "criterion": entry["primary_criterion"],
                    "uwae_arm": uwae_arm,
                    "baseline_arm": baseline_arm,
                    "uwae_successes": uwae_summary["primary_success_runs"],
                    "baseline_successes": baseline_summary["primary_success_runs"],
                    "uwae_evaluated_runs": uwae_summary["evaluated_runs"],
                    "baseline_evaluated_runs": baseline_summary["evaluated_runs"],
                    "uwae_untested_runs": uwae_summary["untested_runs"],
                    "baseline_untested_runs": baseline_summary["untested_runs"],
                    "runs": uwae_summary["runs"],
                    "outcome": _comparison_outcome(uwae_summary, baseline_summary),
                }
            )

    return {
        "per_arm_totals": totals,
        "comparisons": comparisons,
        "win_tie_loss": {
            "uwae_wins": len([c for c in comparisons if c["outcome"] == "uwae"]),
            "ties": len([c for c in comparisons if c["outcome"] == "tie"]),
            "baseline_wins": len([c for c in comparisons if c["outcome"] == "baseline"]),
            "not_comparable": len(
                [c for c in comparisons if c["outcome"] == "not_comparable"]
            ),
            "no_evaluable_runs": len(
                [c for c in comparisons if c["outcome"] == "no_evaluable_runs"]
            ),
            "untested_runs_total": sum(
                totals[arm_id]["untested_runs"] for arm_id in totals
            ),
            "comparisons_with_untested_runs": len(
                [
                    c for c in comparisons
                    if c["uwae_untested_runs"] or c["baseline_untested_runs"]
                ]
            ),
        },
        "interpretation": (
            "E16 mengukur dimensi BROWSER lintas-implementasi — celah yang "
            "dideklarasikan sendiri oleh E14 sebagai skenario tak didukung. "
            "Kriteria diterapkan IDENTIK ke semua lengan dan diturunkan dari "
            "semantika protokol fixture, bukan dari output engine mana pun. "
            "Pembacaan yang jujur: selisih pada sumbu body_acquired "
            "menunjukkan KAPABILITAS; selisih pada byte_faithful menunjukkan "
            "FIDELITAS (browser merekonstruksi byte mentah); selisih pada "
            "signal_preserved menunjukkan apakah sinyal kegagalan tertutup. "
            "BUKAN klaim mengungguli Botasaurus — ini baseline yang dapat "
            "direproduksi, dan lengan botasaurus-browser diberi bentuk "
            "terkuat yang Botasaurus tawarkan. Run yang tidak bisa dievaluasi "
            "— timeout, atau lengan gagal start sehingga tidak ada respons "
            "yang diamati — DIHAPUS dari penyebut kapabilitas dan "
            "dipublikasikan terpisah sebagai belum-teruji; menghitungnya "
            "sebagai gagal akan menghukum lengan karena masalah eksekusi, "
            "bukan karena kemampuan engine."
        ),
    }


def _execution_sessions(rows: List[dict]) -> List[dict]:
    """Segmen eksekusi -- delegasi ke helper timing bersama.

    Implementasi tinggal di ``benchmark/_checkpoint.py`` supaya harness E14,
    E15, dan E16 tidak punya tiga salinan yang bisa berbedadrift.
    """
    return execution_sessions(rows, INTERRUPTION_GAP_THRESHOLD_S)


def _timing_evidence(
    scenarios: List[dict], checkpoint_stats: Dict, invocation_wall_clock_s: float
) -> Dict:
    """Durasi benchmark, diuraikan sehingga tidak bisa disalahbaca.

    Delegasi ke helper timing bersama (``benchmark/_checkpoint.py``); bentuk
    argumen E16 (daftar skenario) diterjemahkan jadi daftar run datar.
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


def main() -> None:
    _preflight()
    started = time.perf_counter()
    checkpoint = _Checkpoint(CHECKPOINT_PATH)
    if checkpoint.rows:
        print(
            "[E16] checkpoint: %d run tersedia untuk dipakai ulang, "
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
        "generated_at": datetime.now(timezone.utc).isoformat(),
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
            "notes": (
                "Semua lengan adalah subprocess dari interpreter yang sama "
                "dengan PYTHONPATH yang sama. Satu subprocess per run agar "
                "state browser dan state server tidak bocor antar run. "
                "n=%d per sel (TEXT.md §6.3: minimal 30 pengulangan untuk "
                "skenario benchmark utama). Setiap run selesai langsung "
                "ditulis ke checkpoint JSONL di luar repo, jadi restart "
                "melanjutkan dari cell terakhir; run yang dipakai ulang "
                "memakai instance fixture ASLINYA, sehingga bila benchmark "
                "dihentikan dan dilanjutkan, jumlah instance fixture yang "
                "terpakai bisa lebih dari satu (lihat fixture_base_urls dan "
                "fixture_instance_count) — isi yang dilayani fixture tetap "
                "identik karena body sumbernya sama. Run yang tidak bisa "
                "dievaluasi tidak masuk penyebut kapabilitas dan "
                "dipublikasikan terpisah sebagai belum-teruji."
                % RUNS
            ),
        },
        "arms": ARMS,
        "arm_configuration": ARM_CONFIGURATION,
        "harness_conditions": HARNESS_CONDITIONS,
        "comparisons": [
            {"uwae_arm": a, "baseline_arm": b} for a, b in COMPARISONS
        ],
        "scenarios": scenarios,
        "summary": _build_summary(scenarios),
        "checkpoint": checkpoint_stats,
    }
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_PATH, "w") as handle:
        json.dump(document, handle, indent=2)

    print("=" * 100)
    print(
        f"{'scenario':<20}{'arm':<24}{'criterion':<20}{'ok/eval':>10}"
        f"{'untested':>9}{'browser':>9}{'med ms':>10}{'p95 ms':>10}"
    )
    print("-" * 100)
    for entry in scenarios:
        for arm_id in ARMS:
            summary = entry["arms"].get(arm_id, {}).get("summary")
            if not summary:
                continue
            print(
                f"{entry['scenario_id']:<20}{arm_id:<24}"
                f"{entry['primary_criterion']:<20}"
                f"{str(summary['primary_success_runs']) + '/' + str(summary['evaluated_runs']):>10}"
                f"{summary['untested_runs']:>9}"
                f"{summary['browser_used_runs']:>9}"
                f"{str(summary['elapsed_ms_median']):>10}"
                f"{str(summary['elapsed_ms_p95']):>10}"
            )
    print("=" * 100)
    print(json.dumps(document["summary"]["win_tie_loss"], indent=2))
    print(f"\nresults -> {RESULTS_PATH}")


if __name__ == "__main__":
    main()
