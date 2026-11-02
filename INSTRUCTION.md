# INSTRUCTION — Universal Web Acquisition Engine

> **Sumber:** Percakapan ChatGPT "Audit Dan Benchmark Botasaurus" — <https://chatgpt.com/share/6ad6c878-727c-83ec-87fe-2c44d8b0171c>
> **Disusun:** 2026-10-20 dari versi final setiap rancangan. Duplikat antar-iterasi dibuang, kata-kata asli dipertahankan; tag render khas ChatGPT dikonversi ke markdown (blok `<CodeBlock>` menjadi fenced code, tautan `<Link>` menjadi link markdown). Judul Bagian 3 dan 4 ditambahkan sebagai navigasi.
> **Lampiran:** Bagian akhir file berisi varian tambahan dari snapshot MHTML percakapan `6ad6d71a-d4a0-83ec-a977-da3905ad753b` (disimpan 2026-10-20).

---

## Instruksi Inti

*(Mandat pemilik proyek — kata per kata dari percakapan sumber)*

Lanjutkan rancangan Universal Web Acquisition Engine dengan sasaran: audit Botasaurus sekaligus benchmark akses website modern. Lingkungan: Termux Android tanpa root dan tanpa PC. Prioritas: diagnosis akses, strategi adaptif, dan pemulihan sesi. Jangan ulangi blueprint generik. Berikan rencana teknis yang dapat dieksekusi, audit berbasis bukti, kontrak modul, urutan implementasi, serta kriteria benchmark yang dapat diverifikasi. Jangan klaim mengungguli Botasaurus sebelum ada hasil pengujian.

---

# Universal Web Acquisition Engine — Rencana Implementasi Kompetitif v1

**Target:** membangun mesin akuisisi web yang bisa diuji secara objektif terhadap Botasaurus, dengan Termux Android tanpa root, tanpa PC, dan prioritas pada diagnosis akses, strategi adaptif, serta pemulihan sesi.

Kita tidak akan langsung membuat puluhan direktori dan ratusan modul. Langkah pertama adalah menghasilkan dua artefak yang menjadi dasar seluruh implementasi:

1. **Botasaurus Evidence Baseline** — inventaris source code, dependensi, kapabilitas, dan perilaku yang benar-benar dapat diverifikasi.
2. **Modern Access Benchmark** — laboratorium yang menguji kapan strategi HTTP, transport alternatif, sesi, atau browser berhasil maupun gagal.

Pemisahan ini penting karena dokumentasi Botasaurus sudah menunjukkan adanya kapabilitas seperti eksekusi paralel, cache, retry, dan penggunaan browser maupun request. Karena itu, implementasi kita harus menguji kemampuan yang benar-benar menjadi pembeda, bukan sekadar menambahkan fitur yang sudah tersedia.

Ada satu batas teknis yang harus kita perhitungkan sejak awal: **Termux adalah lingkungan Android, bukan Linux desktop biasa.** Playwright mempunyai dukungan eksperimental untuk mengotomatisasi Chrome Android melalui ADB, tetapi itu berbeda dari menjalankan browser desktop yang dibundel dengan Playwright Python.  Begitu pula, `curl_cffi` memiliki kemampuan fingerprint TLS dan HTTP/2/HTTP/3 tertentu, tetapi dokumentasinya sendiri tidak menjamin bahwa sebuah situs akan menerima permintaan.

## 1. Definisi hasil akhir yang akan kita bangun

**Access Intelligence Controller**
Menganalisis bukti, menentukan strategi, dan memutuskan langkah berikutnya

**HTTP transports**
HTTPX, Requests, aiohttp, urllib3, curl_cffi jika kompatibel

**Browser adapter**
Chrome Android melalui ADB atau browser runtime lain yang telah diverifikasi

**Session recovery**
Autentikasi, kedaluwarsa, pemulihan yang sah, dan verifikasi pengguna

**Evidence & evaluation**
Hasil terukur, riwayat strategi, klasifikasi kegagalan, dan regresi

**Verified Acquisition Result**
Konten tervalidasi, artifact utuh, status akses jelas, dan bukti yang dapat diaudit

Sistem tidak boleh menyimpulkan keberhasilan hanya dari HTTP 200. Respons bisa berupa halaman login, challenge, halaman kosong, atau konten yang tidak sesuai target.

---

## 2. Fase 0 — audit source code Botasaurus dari Termux

Kita mulai dari source code yang dapat diperiksa, bukan jumlah modul yang diklaim atau jumlah paket yang terpasang.

Repositori publik Botasaurus memuat beberapa direktori dan komponen terpisah, termasuk `botasaurus`, `bota`, `botasaurus_api`, `botasaurus_server`, dan komponen cache. Audit harus memeriksa struktur serta tanggung jawab komponen tersebut.

### 2.1 Siapkan lingkungan audit

Jalankan di Termux. Perintah ini tidak memerlukan root dan tidak menginstal seluruh dependensi Botasaurus.

```bash
pkg update
pkg install -y git python ripgrep

mkdir -p ~/universal-web-acquisition
cd ~/universal-web-acquisition

git clone https://github.com/omkarcloud/botasaurus.git vendor-botasaurus
```
Jika repositori sudah pernah di-clone, jangan jalankan `git clone` lagi. Masuk ke direktori yang ada dan periksa statusnya terlebih dahulu.

```bash
cd ~/universal-web-acquisition/vendor-botasaurus

git rev-parse HEAD
git status --short
git log -1 --format='%H%n%cI%n%s'

git ls-files > ../botasaurus-tracked-files.txt
git ls-files '*.py' > ../botasaurus-python-files.txt

printf '\nTracked files: '
wc -l < ../botasaurus-tracked-files.txt

printf 'Tracked Python files: '
wc -l < ../botasaurus-python-files.txt

printf '\nTop-level structure:\n'
find . -maxdepth 2 -type f | sort | head -250
```
Simpan commit SHA yang dihasilkan. Semua hasil audit berikutnya harus merujuk SHA tersebut agar perubahan source code di masa depan tidak mengubah baseline secara diam-diam.

### 2.2 Hitung modul secara benar

Jangan mencampur empat ukuran berbeda:

| Ukuran | Definisi |
|---|---|
| File Python | Jumlah file `.py` yang terlacak |
| Modul import | Modul Python yang bisa diimpor berdasarkan struktur package |
| Paket langsung | Dependensi yang dinyatakan oleh proyek |
| Paket transitif | Dependensi yang ditarik oleh dependensi lain |

Angka lebih dari 120 modul di virtual environment belum membuktikan bahwa Botasaurus mempunyai 120 modul miliknya sendiri. Sebaliknya, jumlah file Python yang sedikit juga tidak berarti kemampuan framework sedikit.

Buat inventaris awal:

```bash
cd ~/universal-web-acquisition/vendor-botasaurus

printf '%s\n' '=== Package/build metadata ==='
rg -n 'install_requires|extras_require|dependencies|optional-dependencies|entry_points|console_scripts' \
  setup.py setup.cfg pyproject.toml setup.* 2>/dev/null

printf '%s\n' '=== HTTP, retry, cache, session ==='
rg -n -i 'httpx|requests|aiohttp|urllib3|curl_cffi|retry|backoff|cache|cookie|session|timeout|proxy' \
  --glob '*.py' --glob '*.toml' --glob '*.cfg' --glob '*.txt' .

printf '%s\n' '=== Browser, challenge, network ==='
rg -n -i 'playwright|selenium|chrome|chromium|cloudflare|captcha|fingerprint|webdriver|network|download' \
  --glob '*.py' --glob '*.js' --glob '*.md' .
```
Jangan langsung menganggap semua hasil pencarian merupakan fitur aktif. Setiap temuan harus diberi klasifikasi:

- **Implemented:** kode implementasinya ditemukan.
- **Tested:** terdapat tes yang menguji perilaku tersebut.
- **Documented:** hanya dinyatakan dalam dokumentasi.
- **Verified:** perilaku berhasil direproduksi di lingkungan pengujian.
- **Unknown:** belum ada bukti cukup.

Contoh: dokumentasi Botasaurus menerangkan penggunaan request untuk jenis challenge tertentu dan browser untuk challenge yang membutuhkan eksekusi JavaScript. Itu merupakan petunjuk audit yang berguna, tetapi belum membuktikan tingkat keberhasilan pada setiap situs atau pada Termux.

### 2.3 Hasil audit yang wajib dihasilkan

Struktur hasil audit awal:

```text
docs/
├── audit/
│   ├── environment.md
│   ├── source-inventory.json
│   ├── dependency-inventory.json
│   ├── capability-evidence.csv
│   └── botasaurus-limitations.md
├── benchmark/
│   ├── scenario-catalog.json
│   ├── benchmark-protocol.md
│   └── baseline-results.json
└── architecture/
    ├── access-state-machine.md
    └── adapter-contracts.md
```

`botasaurus-limitations.md` tidak boleh menjadi daftar asumsi negatif tentang kompetitor. Isinya harus berupa kelemahan yang benar-benar berhasil direproduksi, batasan platform yang terkonfirmasi, atau celah pengujian yang masih belum terjawab.

---

## 3. Fase 1 — verifikasi kompatibilitas transport di Android

Kita tidak akan menginstal semua transport sekaligus. Kita akan menguji setiap kandidat secara terisolasi agar satu paket native yang tidak kompatibel tidak merusak seluruh lingkungan.

### 3.1 Buat lingkungan Python terpisah

```bash
cd ~/universal-web-acquisition

python -VV
python -m pip --version

mkdir -p .venvs

python -m venv .venvs/audit
. .venvs/audit/bin/activate

python -m pip install --upgrade pip
python -m pip install httpx requests aiohttp urllib3 beautifulsoup4 lxml
python -m pip check
```
Jika suatu paket gagal dipasang atau gagal diimpor, catat kegagalannya sebagai hasil audit platform; jangan langsung mengganti paket atau menyembunyikan error.

Uji import dan versi:

```bash
python - <<'PY'
import importlib
import importlib.metadata as md

packages = [
    ("httpx", "httpx"),
    ("requests", "requests"),
    ("aiohttp", "aiohttp"),
    ("urllib3", "urllib3"),
    ("beautifulsoup4", "bs4"),
    ("lxml", "lxml"),
    ("curl-cffi", "curl_cffi"),
    ("playwright", "playwright"),
]

for distribution, module in packages:
    try:
        imported = importlib.import_module(module)
        try:
            version = md.version(distribution)
        except md.PackageNotFoundError:
            version = "distribution metadata unavailable"
        print(f"OK      {distribution:16} {version:30} {getattr(imported, '__file__', '')}")
    except Exception as exc:
        print(f"FAILED  {distribution:16} {type(exc).__name__}: {exc}")
PY
```
Hasil `FAILED` di sini belum tentu berarti paket tidak mendukung Android secara keseluruhan; penyebabnya bisa berupa wheel yang tidak tersedia, dependensi native, atau lingkungan yang belum memenuhi persyaratan.

### 3.2 Matriks transport yang harus diukur

| Kandidat | Peran dalam arsitektur | Pemeriksaan utama |
|---|---|---|
| `httpx` | Transport sinkron dan asinkron | Timeout, connection pooling, streaming, proxy, HTTP/2 |
| `requests` | Transport sinkron kompatibilitas luas | Sesi, redirect, cookie, streaming |
| `aiohttp` | Transport asinkron | Concurrency, timeout, streaming, koneksi |
| `urllib3` | Lapisan HTTP tingkat lebih rendah | Pooling, retry, koneksi, TLS |
| `curl_cffi` | Transport opsional dengan kapabilitas fingerprint tertentu | Wheel Android, native compatibility, protokol, session |
| Browser adapter | Render JavaScript dan interaksi | Runtime tersedia, lifecycle, DOM, network events |

`curl_cffi` tidak boleh menjadi dependensi wajib sebelum pemasangan, import, dan permintaan HTTPS berhasil diuji pada perangkat yang dituju. Dokumentasinya menjelaskan dukungan fingerprint dan protokol, tetapi tidak menjamin kompatibilitas setiap platform atau penerimaan oleh setiap target.

Demikian juga, **jangan memasukkan Playwright Python desktop ke jalur utama Termux sebelum ada bukti runtime browser yang dapat berjalan**. Untuk Chrome Android, jalur eksperimental Playwright melalui ADB adalah opsi terpisah yang harus divalidasi sendiri.

---

## 4. Fase 2 — kontrak inti yang harus stabil sebelum implementasi besar

Keunggulan mesin adaptif bergantung pada kontrak yang jelas. Adapter transport tidak boleh menentukan sendiri apakah sebuah halaman merupakan hasil sukses; keputusan itu merupakan tanggung jawab lapisan diagnosis dan validasi.

### 4.1 Access assessment

```python
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

class AccessState(StrEnum):
    ACCESS_GRANTED = "access_granted"
    AUTH_REQUIRED = "auth_required"
    RATE_LIMITED = "rate_limited"
    CHALLENGE_PRESENT = "challenge_present"
    JAVASCRIPT_REQUIRED = "javascript_required"
    CONTENT_INVALID = "content_invalid"
    NETWORK_FAILURE = "network_failure"
    ACCESS_DENIED = "access_denied"
    UNKNOWN = "unknown"

@dataclass(frozen=True)
class Evidence:
    source: str
    signal: str
    observed: str
    confidence: float
    details: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class AccessAssessment:
    url: str
    state: AccessState
    confidence: float
    evidence: tuple[Evidence, ...]
    recommended_action: str
    retry_after_seconds: float | None = None
```
Ini adalah kontrak awal, bukan classifier lengkap. Implementasinya harus menghindari kesimpulan yang terlalu yakin berdasarkan satu sinyal saja.

Contohnya:

- HTTP 200 + halaman login yang tidak diharapkan → `AUTH_REQUIRED` atau `CONTENT_INVALID`, bergantung pada target.
- HTTP 429 → `RATE_LIMITED`, kemudian hormati `Retry-After` jika valid.
- Timeout DNS → `NETWORK_FAILURE`, bukan `CHALLENGE_PRESENT`.
- HTML kosong atau struktur target hilang → perlu validasi tambahan, bukan otomatis menganggap website memblokir scraper.
- CAPTCHA atau challenge yang terdeteksi → simpan bukti, ikuti alur verifikasi yang diizinkan, atau hentikan pekerjaan.

### 4.2 Transport adapter

```python
from dataclasses import dataclass
from typing import AsyncIterator, Protocol

@dataclass(frozen=True)
class TransportCapabilities:
    sync: bool
    async_: bool
    streaming: bool
    session_cookies: bool
    proxy: bool
    http2: bool
    http3: bool
    browser_runtime: bool = False

@dataclass(frozen=True)
class RequestSpec:
    url: str
    method: str = "GET"
    headers: dict[str, str] | None = None
    timeout_seconds: float = 20.0

@dataclass(frozen=True)
class ResponseMetadata:
    requested_url: str
    final_url: str
    status_code: int
    headers: dict[str, str]
    elapsed_seconds: float
    transport_name: str

class TransportAdapter(Protocol):
    @property
    def capabilities(self) -> TransportCapabilities: ...

    async def request(self, spec: RequestSpec) -> ResponseMetadata: ...

    async def stream(
        self, spec: RequestSpec
    ) -> AsyncIterator[bytes]: ...
```
Kontrak tersebut memisahkan metadata respons dari streaming body agar artifact berukuran besar tidak perlu dimuat seluruhnya ke RAM. Implementasi sinkron dapat dibungkus dengan executor atau diberikan adapter sinkron terpisah; jangan berpura-pura bahwa setiap transport mendukung operasi asinkron.

Aturan wajib:

1. Kapabilitas harus menyatakan dukungan nyata, bukan nilai yang diasumsikan.
2. Adapter harus mempertahankan error asli melalui error type yang terstruktur.
3. Timeout koneksi dan timeout pembacaan harus dapat dibedakan jika transport mendukungnya.
4. Kredensial, cookie, dan token tidak boleh masuk ke log mentah.
5. Pergantian transport harus terjadi karena keputusan planner, bukan karena setiap error langsung mencoba seluruh library.

### 4.3 Session recovery contract

Sesi perlu memiliki identitas, status, dan siklus hidup. Jangan menyamakan penyimpanan cookie dengan pemulihan autentikasi yang berhasil.

Status minimum:

```text
NEW
  ↓
ACTIVE
  ├──→ EXPIRING
  │      ↓
  │   REAUTH_REQUIRED
  │      ↓
  │   RECOVERY_PENDING
  │      ↓
  │   ACTIVE / FAILED
  ├──→ INVALID
  └──→ CLOSED
```

Setiap recovery attempt harus merekam:

- jenis kegagalan yang memicu recovery;
- ID sesi, tanpa mencatat rahasia sesi;
- tindakan yang dilakukan;
- hasil autentikasi atau verifikasi;
- apakah konten target benar-benar dapat diakses setelah pemulihan;
- jumlah percobaan dan alasan berhenti.

Tidak boleh ada loop login atau retry tanpa batas. CAPTCHA yang memerlukan verifikasi manusia harus mempunyai status `WAITING_FOR_USER` atau status setara, bukan diubah menjadi keberhasilan palsu.

---

## 5. Fase 3 — adaptive strategy planner

Planner adalah subsistem utama yang membedakan mesin adaptif dari sekadar kumpulan transport.

Input-nya bukan hanya URL, melainkan:

- `AccessAssessment`;
- hasil strategi sebelumnya;
- kapabilitas transport yang tersedia;
- status sesi;
- anggaran waktu dan sumber daya;
- aturan akses dan batas percobaan.

Output-nya berupa keputusan yang dapat dijelaskan.

| Bukti | Tindakan berikutnya |
|---|---|
| Halaman publik berhasil dan konten valid | Simpan hasil; jangan mencoba strategi lain |
| HTML belum berisi konten yang ditargetkan | Periksa apakah perlu JavaScript atau apakah selector/target salah |
| Sesi telah kedaluwarsa | Gunakan jalur autentikasi resmi atau minta intervensi pengguna |
| HTTP 429 | Hormati `Retry-After`, turunkan concurrency, dan hindari retry agresif |
| Kegagalan DNS/TLS/koneksi | Diagnosis jaringan dan transport sebelum menyimpulkan pemblokiran |
| Challenge terdeteksi | Klasifikasikan bukti dan gunakan alur verifikasi yang diizinkan |
| Akses ditolak secara eksplisit | Berhenti atau gunakan jalur akses resmi |
| Strategi alternatif gagal berulang | Catat kegagalan terminal beserta bukti; jangan terus memutar transport |

Planner versi pertama harus berupa aturan deterministik yang dapat diuji. Kita tidak membutuhkan model machine learning sebelum memiliki corpus kegagalan dan label yang dapat dipercaya.

### Ukuran kualitas diagnosis

Classifier diuji menggunakan fixture yang label sebenarnya sudah diketahui.

- Precision dan recall per kelas.
- Confusion matrix.
- False positive: halaman normal diklasifikasikan sebagai challenge.
- False negative: challenge tidak terdeteksi.
- Persentase `UNKNOWN`, yang harus tetap diperbolehkan ketika bukti tidak cukup.
- Akurasi pemilihan tindakan berikutnya.

Jangan hanya mengukur accuracy keseluruhan. Jika mayoritas fixture merupakan halaman normal, accuracy tinggi dapat menutupi kegagalan mengenali kondisi yang jarang tetapi penting.

---

## 6. Fase 4 — bangun benchmark yang dapat direproduksi

Kita perlu membandingkan Botasaurus dan Universal Web Acquisition Engine pada **target yang sama, perangkat yang sama, kondisi jaringan yang sama, dan definisi keberhasilan yang sama**.

Untuk target publik yang memiliki proteksi kuat, lakukan pengujian hanya pada akses yang diizinkan. Jangan menganggap perubahan fingerprint, proxy, atau browser akan selalu menyelesaikan challenge.

### 6.1 Skenario wajib

| ID | Skenario | Ground truth |
|---|---|---|
| `A01` | HTML publik | Konten dan marker target ditemukan |
| `A02` | Redirect berantai | URL final dan konten sesuai target |
| `A03` | JavaScript hydration | Elemen target tersedia setelah render |
| `A04` | Autentikasi | Sesi sah dapat mengakses resource yang ditentukan |
| `A05` | Sesi kedaluwarsa | Sistem mengenali expiry dan masuk ke recovery |
| `A06` | HTTP 429 | Retry sesuai kebijakan dan tidak mengabaikan `Retry-After` |
| `A07` | Challenge simulasi lokal | Klasifikasi dan tindakan cocok dengan ground truth |
| `A08` | DNS/TLS/timeout | Penyebab kegagalan tidak salah diklasifikasikan |
| `A09` | Unduhan terputus | Artifact dapat dilanjutkan jika server mendukung resume |
| `A10` | Proses mati | Job yang dapat dipulihkan kembali tanpa menduplikasi hasil |
| `A11` | HTML tidak valid | Sistem tidak melaporkan sukses hanya karena status 200 |
| `A12` | Transport tidak kompatibel | Fallback atau kegagalan terstruktur sesuai kebijakan |

Buat server fixture lokal untuk skenario yang dapat dikendalikan. Dengan demikian, kita bisa menguji 429, expiry, redirect, HTML invalid, dan koneksi terputus tanpa bergantung pada perilaku website eksternal yang bisa berubah sewaktu-waktu.

### 6.2 Format hasil benchmark

Simpan satu record JSON untuk setiap percobaan, bukan hanya ringkasan akhir.

```json
{
  "schema_version": 1,
  "scenario_id": "A03",
  "run_id": "generated-run-id",
  "engine": "uwae",
  "engine_version": "0.1.0",
  "source_commit": "git-commit-sha",
  "environment": {
    "platform": "android-termux",
    "python_version": "record-at-runtime",
    "transport": "httpx"
  },
  "input": {
    "target_id": "local-fixture-js-01"
  },
  "result": {
    "success": false,
    "expected_state": "access_granted",
    "observed_state": "javascript_required",
    "content_valid": false,
    "artifact_integrity": null
  },
  "performance": {
    "elapsed_ms": null,
    "peak_memory_bytes": null,
    "attempt_count": 1
  },
  "evidence": [],
  "failure_reason": "browser_adapter_not_available"
}
```
Nilai `null` berarti belum diukur atau tidak berlaku. Jangan mengisi metrik dengan angka perkiraan. Dalam implementasi nyata, `run_id`, versi Python, commit, dan waktu eksekusi harus dihasilkan otomatis.

### 6.3 Kriteria kelulusan

Sebelum benchmark kompetitif, tetapkan ambang berikut sebagai **kriteria engineering awal**, bukan hasil yang sudah tercapai.

- 100% fixture deterministik memiliki expected outcome yang eksplisit.
- 100% hasil memiliki commit, versi runtime, dan scenario ID.
- Tidak ada keberhasilan akuisisi tanpa validasi konten.
- Tidak ada retry tanpa batas.
- Tidak ada kredensial mentah pada log dan artifact metadata.
- Semua kegagalan terminal memiliki kategori dan bukti.
- Minimal 30 pengulangan untuk skenario benchmark utama sebelum membandingkan performa.
- Laporkan median, p95, rentang hasil, serta jumlah keberhasilan dan kegagalan.
- Bandingkan performa hanya pada fitur yang tersedia dan dapat dijalankan pada kedua sistem.

Ambang ini adalah gerbang kualitas internal. Untuk klaim keunggulan, kita tetap memerlukan hasil eksperimen yang mendukungnya.

---

## 7. Urutan implementasi untuk AI coding agent

Jangan meminta agent membangun semua komponen sekaligus. Gunakan urutan ini agar setiap fase meninggalkan hasil yang bisa diperiksa.

  **Audit dan baseline.** Clone serta pin commit Botasaurus, hitung source dan dependensi, catat dukungan platform, dan buat laporan evidence. Belum perlu membangun scraper baru.
  **Fixture server dan benchmark schema.** Bangun endpoint pengujian lokal, ground truth, pencatat hasil, dan runner. Pastikan pengujian deterministik berjalan sebelum menambah transport.
  **Transport registry.** Implementasikan satu adapter HTTP yang kompatibel terlebih dahulu, kemudian tambah adapter lain satu per satu berdasarkan hasil uji Termux.
  **Access classifier.** Implementasikan state dan evidence model; tambahkan unit test untuk seluruh kelas serta false positive dan false negative.
  **Strategy planner.** Hubungkan classifier dengan keputusan deterministik, anggaran retry, kebijakan akses, dan hasil strategi sebelumnya.
  **Session recovery.** Tambahkan penyimpanan sesi yang aman, expiry detection, autentikasi sah, recovery state machine, dan verifikasi hasil pascarecovery.
  **Browser capability spike.** Verifikasi apakah jalur Chrome Android/ADB benar-benar dapat menjalankan skenario JavaScript target. Jika tidak, laporkan batasan dan jangan membuat browser adapter palsu.
  **Differential benchmark.** Jalankan Botasaurus dan mesin baru pada skenario yang sama, ekspor hasil mentah, analisis selisih, dan pilih kelemahan terbesar untuk iterasi berikutnya.

## 8. Instruksi implementasi siap diberikan kepada Claude Code atau Hermes

# Mission: Build the Evidence-Driven Universal Web Acquisition Engine

## Objective

Develop a Python-first, CLI-first web acquisition engine in Termux on Android, without root and without a PC. The first competitive objective is not feature count: it is measurable improvement in access diagnosis, adaptive strategy selection, authorized session recovery, and reproducible benchmark performance against a pinned Botasaurus source revision.

## Mandatory Phase 0 — Repository and Environment Audit

1. Inspect the existing workspace before changing files.
2. Record Python version, architecture, operating environment, package manager, available storage, and existing Git state.
3. Clone or inspect Botasaurus source without assuming its entire dependency stack can run on Termux.
4. Pin the exact Botasaurus commit SHA.
5. Distinguish tracked Python files, importable modules, first-party packages, direct dependencies, and transitive dependencies.
6. Inspect implementation and tests for browser runtime, HTTP transport, sessions, retry, caching, concurrency, challenges, and download behavior.
7. Label every finding IMPLEMENTED, TESTED, DOCUMENTED, VERIFIED, or UNKNOWN.
8. Never describe a feature as verified merely because documentation claims it exists.

## Mandatory Phase 1 — Deterministic Benchmark Lab

Create local fixtures for public HTML, redirects, JavaScript hydration, authorized authentication, session expiry, HTTP 429 with Retry-After, simulated challenges, invalid content, network errors, interrupted downloads, and process interruption.

Every fixture must declare:
- Scenario ID and ground truth.
- Expected access state.
- Expected next action.
- Success validation rule.
- Resource and retry limits.

Produce machine-readable JSONL results and human-readable reports. The benchmark runner must be deterministic and must not require access to third-party anti-bot systems.

## Mandatory Phase 2 — Contracts

Implement typed contracts for:
- AccessEvidence and AccessAssessment.
- TransportCapabilities, RequestSpec, and ResponseMetadata.
- SessionState and SessionRecoveryResult.
- StrategyDecision and RetryBudget.
- AcquisitionResult and ArtifactIntegrity.
- BenchmarkRecord and FailureClassification.

All transport capabilities must be verified on the actual runtime. Do not claim HTTP/2, HTTP/3, browser execution, streaming, or session support without an executable test.

## Mandatory Phase 3 — Access Intelligence

Build a deterministic evidence-based classifier with these initial states:
ACCESS_GRANTED, AUTH_REQUIRED, RATE_LIMITED, CHALLENGE_PRESENT, JAVASCRIPT_REQUIRED, CONTENT_INVALID, NETWORK_FAILURE, ACCESS_DENIED, UNKNOWN.

Use multiple signals where available. Preserve evidence and confidence. Never infer a challenge solely from a generic timeout or HTTP 403.

Implement a planner that chooses the next action based on classification, transport capabilities, prior attempts, session state, access policy, and resource budgets.

Require a terminal decision when:
- Retry budget is exhausted.
- Access is explicitly denied.
- User verification is required.
- A required runtime is unavailable.
- Further attempts would violate the configured access policy.

## Mandatory Phase 4 — Session Recovery

Implement safe session lifecycle management, expiry detection, authorized reauthentication, user-assisted verification states, secret redaction, and post-recovery content validation.

Do not log raw credentials, tokens, or session cookies. Do not assume browser and HTTP cookies can be transferred blindly. Do not implement endless recovery loops.

## Mandatory Phase 5 — Termux Compatibility

Verify each dependency independently. Keep optional native transports optional. Do not assume a desktop Playwright browser can run inside Termux. Investigate Chrome Android/ADB automation as a separate capability and produce a working proof before integrating it.

Preserve an HTTP-only usable mode even if browser or native transport support is unavailable.

## Mandatory Phase 6 — Competitive Benchmark

Use identical targets, expected outputs, device conditions, run counts, and success criteria for Botasaurus and the new engine.

Measure:
- Verified acquisition success.
- Access-state precision, recall, and confusion matrix.
- Recovery success where recovery is possible.
- False-positive challenge classifications.
- Median and p95 latency.
- Peak memory and retry count.
- Artifact integrity and restart recovery.
- Dependency installation and runtime compatibility.

Store raw results, source revisions, runtime details, and benchmark configuration. Report failures, unsupported scenarios, and uncertainty. Do not claim superiority without reproducible evidence.

## Engineering Rules

- Inspect before editing.
- Preserve unrelated files and user changes.
- Implement one verifiable milestone at a time.
- Add tests before expanding module scope.
- Avoid god modules, duplicated responsibilities, hidden global state, and silent exception swallowing.
- Never report a command as successful unless its exit status and resulting artifact were verified.
- Never fabricate benchmark values.
- Respect authentication requirements, rate limits, access denials, and human verification workflows.

## Required Deliverables

1. docs/audit/environment.md
2. docs/audit/source-inventory.json
3. docs/audit/dependency-inventory.json
4. docs/audit/capability-evidence.csv
5. docs/audit/botasaurus-limitations.md
6. docs/benchmark/scenario-catalog.json
7. docs/benchmark/baseline-results.json
8. docs/architecture/access-state-machine.md
9. docs/architecture/adapter-contracts.md
10. Executable tests and a CLI benchmark runner

Begin with Phase 0. Do not scaffold the entire platform before the audit and benchmark foundation are verified. Finish by reporting the exact commands run, exit codes, files created, tests passed and failed, unresolved issues, and the next evidence-backed milestone.

---

## 9. Gerbang keputusan sebelum kita mengklaim ada kemajuan kompetitif

Setelah fase pertama selesai, hasilnya harus menjawab pertanyaan nyata:

- Berapa banyak modul Botasaurus yang merupakan kode proyek sendiri, dan berapa banyak dependensi pihak ketiga?
- Fitur apa yang benar-benar berfungsi pada lingkungan yang diuji?
- Apakah browser automation yang dibutuhkan tersedia di perangkat Android tersebut?
- Kapan HTTP-only lebih baik daripada membuka browser?
- Apakah diagnosis dapat membedakan challenge, autentikasi, rate limit, dan gangguan jaringan?
- Apakah pemulihan sesi berhasil pada fixture yang mendukungnya?
- Di skenario mana mesin baru mengungguli baseline, sama, atau justru gagal?

Baru setelah itu kita memilih fitur berikutnya berdasarkan hasil pengujian. **Untuk saat ini, belum ada bukti bahwa Universal Web Acquisition Engine lebih unggul dari Botasaurus.** Rencana ini dirancang untuk menghasilkan bukti yang diperlukan agar kita dapat membangunnya secara sistematis, khususnya pada diagnosis akses, strategi adaptif, dan pemulihan sesi.

---

Saya menangkap masalahnya: rancangan sebelumnya masih berupa arsitektur, beberapa kontrak Python, dan daftar fase. Itu belum menjadi **spesifikasi engineering yang cukup ketat untuk membangun pesaing Botasaurus**.

Kekurangan terbesarnya adalah kita belum menetapkan bagaimana mesin membuat keputusan dari bukti nyata, bagaimana strategi dibandingkan, bagaimana kegagalan didiagnosis sampai ke akar masalah, bagaimana sesi dan job dipulihkan, serta bagaimana kita membuktikan bahwa pendekatan baru lebih baik.

Kita perlu satu tingkat lebih dalam: spesifikasi perilaku, kontrak antarsubsistem, model data, algoritme keputusan, eksperimen kompetitif, gerbang penerimaan, dan perintah eksekusi yang tidak mengasumsikan kemampuan Android yang belum terverifikasi.

# Universal Web Acquisition Engine — Engineering Specification v2

## 1. Prinsip desain: bukan scraper dengan banyak adapter

Mesin harus menjadi sistem yang melakukan siklus berikut untuk setiap pekerjaan:

  {#each [
  ["Observe","Kumpulkan respons, metadata, status sesi, dan sinyal runtime."],
  ["Diagnose","Klasifikasikan kondisi akses beserta bukti dan tingkat keyakinan."],
  ["Decide","Pilih tindakan berikutnya berdasarkan kebijakan, kapabilitas, dan biaya."],
  ["Execute","Jalankan strategi melalui adapter yang telah diverifikasi."],
  ["Validate","Pastikan konten benar-benar sesuai dengan tujuan akuisisi."],
  ["Learn from evidence","Simpan hasil untuk evaluasi kebijakan dan regresi."]
  ] as item,i}

**{i+1}**

**{item[0]}**

{item[1]}

{#if i<5}

{/if}
  {/each}
  Siklus berulang hanya jika tindakan berikutnya masuk akal, diizinkan, dan masih berada dalam anggaran pekerjaan.

Perbedaan pentingnya: hasil satu percobaan menjadi input bagi keputusan berikutnya. Sistem tidak boleh sekadar menjalankan daftar fallback tetap seperti `requests → httpx → curl_cffi → browser`, karena semua itu bisa gagal akibat penyebab yang sama.

## 2. Audit Botasaurus berdasarkan kemampuan yang benar-benar dimilikinya

Audit harus dimulai dengan asumsi bahwa Botasaurus sudah merupakan kompetitor yang matang, bukan scraper sederhana.

Dokumentasi publiknya menjelaskan beberapa kemampuan yang relevan:

- `@request` dan `@browser`, termasuk konfigurasi retry, cache, paralelisme, serta pengelolaan error.
- Request berbasis `hrequests` melalui `botasaurus-requests`, dengan karakteristik koneksi yang ditujukan menyerupai browser.
- Browser dengan konfigurasi profil, proxy, penggunaan ulang driver, dan alur interaksi challenge tertentu.
- Penggunaan request dari browser untuk mengambil konten dengan lebih efisien setelah sesi browser dibuka.

Ini merupakan kapabilitas yang terdokumentasi, bukan hasil benchmark independen. Artinya, mesin baru tidak bisa mengklaim unggul hanya karena memiliki request, browser, cache, retry, dan proxy.

### Matriks audit kompetitif

| Area | Apa yang diperiksa di Botasaurus | Apa yang harus diuji pada mesin baru |
|---|---|---|
| HTTP request | Implementasi request, stack HTTP, cookie, redirect | Keberhasilan dan waktu respons pada fixture identik |
| Browser | Driver, lifecycle, profil, crash handling | Ketersediaan runtime Android dan pemulihan browser |
| Challenge | Detektor, kondisi aktivasi, alur pengguna | Ketepatan klasifikasi, false positive, dan hasil verifikasi |
| Session | Penyimpanan cookie, reuse, autentikasi | Expiry detection, isolasi sesi, dan recovery |
| Retry | Kondisi retry, jeda, exception | Retry berdasarkan kelas kegagalan dan anggaran |
| Cache | Cache key, invalidasi, hasil yang disimpan | Validitas cache, deduplikasi, dan penghindaran data basi |
| Paralelisme | Model concurrency, batas browser/request | Throughput dan stabilitas dalam batas memori Android |
| Unduhan | Streaming, penyimpanan, integritas | File parsial, resume, checksum, dan pemulihan |
| Diagnosis | Log dan informasi error | Bukti terstruktur dan penyebab kegagalan yang dapat diuji |
| Portabilitas | Dependensi, runtime, instalasi | Keberhasilan instalasi serta operasi pada Termux |

Satu hal yang sangat penting: dokumentasi Botasaurus menunjukkan bahwa request dan browser mempunyai fungsi berbeda ketika sebuah challenge memerlukan eksekusi JavaScript atau interaksi tambahan.  Karena itu, pengujian harus menentukan **kapan masing-masing jalur bekerja, kapan gagal, dan apakah kegagalannya dapat didiagnosis**, bukan mengasumsikan bahwa satu adapter lebih unggul untuk semua situs.

## 3. Definisi algoritme diagnosis akses

Kita memerlukan classifier yang mengubah observasi menjadi keadaan terstruktur. Jangan mulai dari machine learning; mulailah dari aturan deterministik yang hasilnya dapat diverifikasi.

### 3.1 Urutan evaluasi

```python
def classify_access(observation):
    """
    Pseudocode kontrak.
    Setiap helper harus mengembalikan bukti yang dapat diaudit.
    """

    if observation.network_error:
        return classify_network_failure(observation)

    if observation.explicit_rate_limit:
        return assessment(
            state="rate_limited",
            action="respect_retry_after",
        )

    if observation.explicit_auth_required:
        return assessment(
            state="auth_required",
            action="reauthenticate_or_request_user",
        )

    if observation.explicit_access_denial:
        return assessment(
            state="access_denied",
            action="stop_or_use_authorized_access",
        )

    if observation.challenge_evidence:
        return assessment(
            state="challenge_present",
            action="authorized_challenge_workflow",
        )

    if observation.target_content_valid:
        return assessment(
            state="access_granted",
            action="persist_result",
        )

    if observation.javascript_evidence:
        return assessment(
            state="javascript_required",
            action="check_browser_capability",
        )

    if observation.response_received:
        return assessment(
            state="content_invalid",
            action="inspect_content_and_target",
        )

    return assessment(
        state="unknown",
        action="collect_more_evidence",
    )
```
Ini pseudocode untuk menjelaskan urutan keputusan, bukan kode siap produksi. Implementasi sebenarnya harus memastikan bahwa sinyal tidak tumpang tindih secara keliru.

Contohnya, status HTTP 403 saja tidak cukup untuk menyimpulkan CAPTCHA atau deteksi bot. Status tersebut bisa berarti akses ditolak karena izin, aturan aplikasi, autentikasi, atau kebijakan server. Demikian pula, halaman tanpa elemen target tidak otomatis berarti JavaScript diperlukan.

### 3.2 Skema bukti

Setiap keputusan classifier harus menyimpan informasi seperti berikut:

```json
{
  "observation_id": "obs-000123",
  "target_id": "fixture-auth-01",
  "transport": "httpx",
  "response": {
    "status": 200,
    "final_url": "https://fixture.example.test/login",
    "content_type": "text/html"
  },
  "signals": [
    {
      "name": "login_form_detected",
      "value": true,
      "source": "html_validator"
    },
    {
      "name": "expected_marker_found",
      "value": false,
      "source": "content_validator"
    }
  ],
  "assessment": {
    "state": "auth_required",
    "confidence": 0.97,
    "reason_codes": [
      "LOGIN_FORM_PRESENT",
      "TARGET_MARKER_MISSING"
    ]
  },
  "policy": {
    "action": "reauthenticate_or_request_user",
    "attempt": 1
  }
}
```
Angka confidence di atas hanya ilustrasi format, bukan hasil pengukuran. Dalam implementasi nyata, confidence harus dikalibrasi terhadap corpus berlabel. Jika belum ada dasar statistik untuk memberi probabilitas, gunakan kategori keyakinan dan reason code terlebih dahulu.

### 3.3 Klasifikasi harus dapat diaudit

Setiap reason code mempunyai definisi, sumber bukti, dan tes.

| Reason code | Bukti minimum | Tes wajib |
|---|---|---|
| `HTTP_RATE_LIMIT` | Status 429 atau sinyal rate limit yang tervalidasi | 429 dengan dan tanpa `Retry-After` |
| `LOGIN_FORM_PRESENT` | Marker formulir login yang sesuai aturan target | Halaman login dan halaman normal |
| `TARGET_MARKER_MISSING` | Validasi konten tidak menemukan marker wajib | HTML normal, kosong, dan tidak lengkap |
| `DNS_RESOLUTION_FAILED` | Error resolver yang dapat dikenali | Host fixture yang tidak dapat di-resolve |
| `TLS_HANDSHAKE_FAILED` | Error TLS yang teridentifikasi | Sertifikat tidak valid pada fixture |
| `CHALLENGE_SIGNATURE_MATCH` | Marker challenge yang terverifikasi | Challenge fixture dan halaman normal yang mirip |
| `BROWSER_RUNTIME_UNAVAILABLE` | Runtime browser gagal ditemukan atau dijalankan | Browser tidak terpasang dan browser yang tersedia |

Dengan pendekatan ini, kita dapat memperbaiki satu jenis kesalahan diagnosis tanpa menulis ulang seluruh sistem.

---

## 4. Planner: memilih strategi berdasarkan biaya dan bukti

Planner harus mempertimbangkan bukan hanya kemungkinan berhasil, tetapi juga biaya, risiko kegagalan, status sesi, dan apakah tindakan berikutnya diizinkan.

### 4.1 Model keputusan

Untuk setiap kandidat strategi \(s\), simpan:

- Kapabilitas yang dibutuhkan.
- Bukti keberhasilan sebelumnya pada kelas skenario yang sama.
- Latensi dan penggunaan sumber daya yang terukur.
- Tingkat kegagalan.
- Persyaratan autentikasi atau intervensi pengguna.
- Batas retry dan kebijakan akses.

Skor awal dapat berupa:

\[
\operatorname{score}(s)=
w_p P_s-w_t T_s-w_m M_s-w_f F_s
\]

dengan:

- \(P_s\): estimasi keberhasilan yang dikalibrasi dari benchmark.
- \(T_s\): biaya latensi yang dinormalisasi.
- \(M_s\): biaya memori.
- \(F_s\): biaya kegagalan dan pemulihan.
- \(w_p,w_t,w_m,w_f\): bobot konfigurasi yang ditetapkan dan diuji.

Rumus ini hanya alat pengambilan keputusan. Ia tidak akan menghasilkan strategi yang baik tanpa data yang representatif. Versi pertama sebaiknya memakai aturan deterministik, kemudian evaluasi apakah skor berbasis data benar-benar memperbaiki hasil.

### 4.2 Contoh keputusan yang diharapkan

**HTTP berhasil dan konten valid**

Simpan hasil. Jangan membuka browser hanya untuk mengulangi pekerjaan yang sudah selesai.

**Sesi kedaluwarsa**

Gunakan mekanisme autentikasi resmi atau minta pengguna memperbarui sesi. Validasi kembali konten setelah pemulihan.

**Rate limit**

Patuhi waktu tunggu server, turunkan concurrency bila diperlukan, dan hindari perpindahan adapter yang hanya mengulangi permintaan terlalu cepat.

**Konten memerlukan JavaScript**

Periksa apakah browser runtime yang sesuai tersedia. Jika tidak tersedia, hasilkan kegagalan yang menjelaskan kemampuan yang kurang.

**Challenge atau penolakan akses**

Gunakan alur akses yang diizinkan, verifikasi pengguna, atau hentikan pekerjaan. Jangan melaporkan akses berhasil tanpa bukti.

Planner juga harus mencegah siklus seperti ini:

```text
HTTP gagal
  → transport lain gagal
  → browser gagal
  → kembali ke HTTP
  → ulangi tanpa batas
```

Gunakan `attempt_history`, `visited_strategy_states`, dan `retry_budget`. Jika tidak ada bukti baru yang dapat diperoleh dari percobaan berikutnya, planner harus berhenti.

---

## 5. Model penyimpanan dan pemulihan yang tahan kegagalan

Mesin yang bagus bukan hanya bisa memulai pekerjaan, tetapi juga bisa menjelaskan dan memulihkannya setelah Termux ditutup, proses mati, atau koneksi terputus.

### 5.1 Model data minimum

Gunakan SQLite sebagai penyimpanan job dan state awal. SQLite merupakan pilihan yang masuk akal untuk aplikasi CLI lokal, tetapi konfigurasi transaksi, WAL, dan perilaku saat proses berhenti tetap harus diuji pada filesystem Android yang digunakan.

Tabel minimum:

| Tabel | Tanggung jawab |
|---|---|
| `jobs` | Input, status, kebijakan, waktu pembuatan |
| `attempts` | Strategi, transport, hasil, durasi, error |
| `observations` | Bukti diagnosis yang telah disanitasi |
| `sessions` | Referensi sesi, status, expiry, metadata aman |
| `artifacts` | Path, ukuran, hash, identifikasi format |
| `job_events` | Transisi state yang dapat diaudit |
| `benchmark_runs` | Versi engine, skenario, hasil, dan konfigurasi |

Setiap job harus mempunyai ID yang stabil. Job yang diulang setelah crash tidak boleh menghasilkan artifact ganda tanpa alasan yang tercatat.

### 5.2 Pemulihan job

Alur pemulihan:

1. Baca job yang belum terminal.
2. Periksa apakah ada attempt yang statusnya masih berjalan ketika proses mati.
3. Tandai attempt tersebut sebagai `INTERRUPTED`, bukan `SUCCESS`.
4. Periksa artifact parsial dan checkpoint.
5. Validasi apakah server mendukung resume sebelum melanjutkan unduhan.
6. Lanjutkan atau mulai ulang sesuai bukti.
7. Validasi ukuran, hash, dan konten.
8. Catat transisi state dan alasan keputusan.

Untuk unduhan HTTP, jangan menganggap `Range` selalu didukung. Jika server tidak menyediakan validator atau tidak mendukung resume, strategi yang benar mungkin mengulang unduhan dari awal, bukan menggabungkan byte secara spekulatif.

### 5.3 Integritas artifact

Untuk setiap artifact, simpan:

- URL sumber dan URL final.
- Waktu akuisisi.
- Status respons dan MIME type.
- Ukuran aktual.
- SHA-256.
- Identifikasi format berdasarkan signature, bukan hanya ekstensi.
- Status validasi dan ekstraksi.
- Referensi job dan attempt asal.

**Akuisisi, identifikasi format, dan ekstraksi harus merupakan operasi terpisah.** Jika ekstraksi gagal, artifact asli tidak boleh otomatis dibuang.

---

## 6. Arsitektur proyek yang lebih konkret

Mulailah dengan modul yang mempunyai kontrak nyata dan dapat diuji, bukan struktur folder besar yang belum memiliki implementasi.

```text
universal-web-acquisition/
├── pyproject.toml
├── README.md
├── src/
│   └── uwae/
│       ├── cli.py
│       ├── config.py
│       ├── domain/
│       │   ├── models.py
│       │   ├── states.py
│       │   └── errors.py
│       ├── access/
│       │   ├── evidence.py
│       │   ├── classifier.py
│       │   ├── planner.py
│       │   └── policy.py
│       ├── transports/
│       │   ├── contracts.py
│       │   ├── registry.py
│       │   └── httpx_adapter.py
│       ├── sessions/
│       │   ├── models.py
│       │   ├── store.py
│       │   └── recovery.py
│       ├── jobs/
│       │   ├── repository.py
│       │   ├── scheduler.py
│       │   └── recovery.py
│       ├── artifacts/
│       │   ├── streaming.py
│       │   ├── integrity.py
│       │   └── identification.py
│       ├── observability/
│       │   ├── events.py
│       │   └── metrics.py
│       └── benchmark/
│           ├── runner.py
│           ├── schema.py
│           └── reporting.py
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── fixtures/
│   └── regression/
├── docs/
│   ├── audit/
│   ├── architecture/
│   └── benchmark/
└── scripts/
    ├── audit-botasaurus.sh
    └── run-benchmarks.sh
```

Browser adapter, `curl_cffi`, discovery graph, marketplace plugin, dan extraction registry ditambahkan setelah core, kontrak, dan benchmark terbukti berfungsi. Itu bukan berarti fitur tersebut tidak penting; urutannya mencegah kita membangun integrasi yang belum dapat dijalankan atau diverifikasi.

---

## 7. Gerbang penerimaan engineering

Setiap fase harus lulus pengujian sebelum dilanjutkan.

| Gerbang | Syarat lulus |
|---|---|
| G0 — Audit | Commit Botasaurus dipatok; inventaris source/dependensi dan bukti terdokumentasi |
| G1 — Fixtures | Setiap skenario mempunyai ground truth; hasil fixture deterministik |
| G2 — Transport | Adapter lulus tes timeout, redirect, error, dan cleanup |
| G3 — Diagnosis | Precision/recall dilaporkan per kelas; kesalahan klasifikasi dapat ditelusuri |
| G4 — Planner | Tidak ada retry tanpa batas atau transisi state yang tidak sah |
| G5 — Session | Expiry, recovery, dan hasil pascarecovery terverifikasi |
| G6 — Durability | Job dan artifact dapat dipulihkan setelah simulasi proses mati |
| G7 — Benchmark | Hasil mentah dan laporan perbandingan dapat direproduksi |

Untuk benchmark, 30 pengulangan per skenario dapat menjadi penyaringan awal, tetapi belum cukup untuk semua klaim statistik. Skenario eksternal yang berubah-ubah membutuhkan lebih banyak pengulangan, pengendalian kondisi, dan pelaporan ketidakpastian.

Perbandingan harus melaporkan:

- tingkat keberhasilan dengan definisi sukses yang identik;
- precision dan recall diagnosis;
- median serta p95 latency;
- peak memory dan jumlah percobaan;
- kegagalan instalasi atau runtime;
- integritas artifact;
- hasil setiap skenario, termasuk yang tidak didukung oleh salah satu engine.

Jika Botasaurus tidak dapat dijalankan pada Termux, kita tetap dapat menyelesaikan audit source dan benchmark fitur yang bisa diuji, tetapi **tidak boleh menyebut hasil tersebut sebagai kemenangan runtime langsung atas Botasaurus**.

## 8. Urutan eksekusi berikutnya

Saya merekomendasikan agar pekerjaan teknis dimulai dengan satu milestone yang dapat ditutup sepenuhnya: **G0 — Audit Botasaurus dan kemampuan aktual Termux**.

Urutannya:

1. Pin commit source Botasaurus.
2. Inventaris file Python, package, dependensi, adapter request/browser, dan tes.
3. Catat kemampuan yang terimplementasi versus yang benar-benar teruji.
4. Verifikasi transport yang bisa dipasang pada Python di perangkat.
5. Verifikasi jalur browser Android yang tersedia.
6. Hasilkan laporan audit dan daftar eksperimen prioritas.
7. Baru setelah itu buat benchmark fixture dan implementasi classifier.

Hasil G0 harus berupa laporan dengan bukti, bukan kesimpulan bahwa framework baru lebih baik.

**Kriteria keputusan utama:** jika kita belum bisa menunjukkan skenario yang gagal atau kurang efisien pada baseline Botasaurus, kita belum memiliki dasar yang cukup untuk memilih fitur kompetitif berikutnya. Itulah perbedaan antara blueprint yang panjang dan rencana engineering yang bisa menghasilkan keunggulan terukur.

---

# Access Control Plane, Diagnosis, dan Pemulihan Sesi

Saya setuju. Rancangan sebelumnya masih belum menyentuh persoalan paling sulit: **bagaimana membangun mesin yang mampu menghadapi variasi perilaku website modern secara sistematis, bukan sekadar mengidentifikasi error setelah request gagal.**

Kita perlu berhenti memperluas daftar modul. Yang kurang adalah spesifikasi kompetitif yang menetapkan mekanisme internal, strategi eksperimen, model kegagalan, batas kemampuan runtime Android, dan kriteria pembuktian.

Saya akan memperdalamnya pada empat hal:

1. **Audit berbasis implementasi** — menemukan apa yang benar-benar dilakukan Botasaurus, termasuk jalur eksekusi, bukan sekadar nama fitur.
2. **Diagnosis berbasis rangkaian bukti** — memahami apakah kegagalan disebabkan jaringan, autentikasi, rendering, kebijakan akses, konten yang salah, atau runtime.
3. **Pengendalian strategi dan sesi** — mencegah retry sia-sia, memulihkan state secara konsisten, serta mempelajari hasil eksperimen tanpa mengulang kesalahan.
4. **Competitive benchmark yang adil** — mengukur hasil pada skenario terkontrol, lalu menguji generalisasi pada website yang aksesnya memang diizinkan.

Satu hal harus eksplisit: kita dapat membangun diagnosis dan pemulihan yang jauh lebih sistematis, tetapi tidak ada transport, fingerprint, proxy, atau browser yang menjamin akses ke setiap website yang menerapkan proteksi bot.

## 1. Temuan penting: baseline kompetitor lebih kuat daripada yang diasumsikan

Dokumentasi resmi Botasaurus menyebut kemampuan yang lebih luas daripada request sederhana. Di antaranya `@request`, `@browser`, paralelisme, cache, reuse driver, konfigurasi retry, dan pengelolaan error.

Ada dua implikasi untuk rancangan kita.

Pertama, fitur-fitur tersebut harus dianggap sebagai **baseline**, bukan diferensiator. Kedua, kita harus menyelidiki apakah Botasaurus mempunyai kelemahan yang dapat diukur dalam diagnosis, pemulihan, ketahanan job, atau kompatibilitas Termux sebelum memilih area untuk dikalahkan.

Saya tidak akan menyatakan bahwa fitur-fitur tersebut lemah atau tidak andal tanpa pengujian.

## 2. Spesifikasi teknis yang belum ada: access control plane

Saya akan menjadikan *access control plane* sebagai inti mesin. Ini bukan sekadar classifier dan bukan pula pemilih library.

Tugasnya adalah mengelola keadaan akses untuk setiap origin, mempertahankan riwayat percobaan, dan menentukan kapan pekerjaan boleh dilanjutkan.

### 2.1 State machine pada tiga tingkat

Sistem perlu membedakan tiga state machine, bukan mencampur semuanya ke satu status `SUCCESS` atau `FAILED`.

  **A. Origin state**
  Kondisi umum suatu origin, seperti server sehat, sedang rate-limit, membutuhkan autentikasi, atau tidak dapat dijangkau.
  `UNKNOWN → HEALTHY / DEGRADED / RATE_LIMITED / AUTH_REQUIRED / DENIED`

  **B. Session state**
  Kondisi sesi tertentu, bukan kondisi seluruh origin.
  `NEW → ACTIVE → EXPIRING → RECOVERY_PENDING → ACTIVE / INVALID / CLOSED`

  **C. Job state**
  Kemajuan satu pekerjaan akuisisi.
  `QUEUED → RUNNING → VALIDATING → SUCCEEDED / RETRY_WAIT / NEEDS_USER / FAILED`

Ketiganya harus independen. Satu sesi yang kedaluwarsa tidak berarti seluruh origin sedang down. Satu job yang gagal mengekstrak data tidak berarti artifact hasil unduhannya rusak.

### 2.2 Aturan konsistensi

Kontrak ini harus dipaksakan dalam kode dan tes:

- Job tidak boleh `SUCCEEDED` sebelum validator menyatakan hasilnya valid.
- `RETRY_WAIT` harus memiliki waktu atau kondisi pemicu berikutnya.
- `NEEDS_USER` tidak boleh berubah menjadi sukses hanya karena waktu berlalu.
- State `DENIED` tidak boleh otomatis diatasi dengan mengulang request melalui semua transport.
- Perubahan sesi harus memiliki versi atau nomor generasi agar job tidak menggunakan state yang sudah kedaluwarsa.
- Setiap transisi terminal harus mempunyai reason code.

Dengan demikian, sistem tidak hanya menyimpan apa yang terjadi; sistem membatasi keputusan yang tidak masuk akal.

## 3. Model keputusan: diagnosis, bukan tebakan

### 3.1 Bukti dan hipotesis harus dipisahkan

Misalnya, sistem mendapatkan HTTP 403. Itu merupakan observasi. `ACCESS_DENIED` merupakan hipotesis tentang kondisi akses. `CHALLENGE_PRESENT` merupakan hipotesis lain.

Sistem perlu mempertahankan keduanya:

```text
Observation:
  status = 403
  response_body = captured_and_redacted
  final_url = /resource
  target_marker = absent

Hypotheses:
  access_denied
  challenge_present
  authentication_required
  application_error

Next action:
  inspect available evidence
  validate against known target rules
  stop or request authorized intervention if unresolved
```

Jangan membuat aturan seperti `403 → challenge → browser` secara universal. Hal tersebut akan menghasilkan diagnosis keliru pada banyak aplikasi.

### 3.2 Gunakan reason code dan evidence lineage

Setiap keputusan harus bisa ditelusuri:

```text
job_id
  └── attempt_id
       ├── transport_id
       ├── observation_ids[]
       ├── classifier_version
       ├── assessment
       ├── strategy_decision
       └── validation_result
```

Jika sistem salah mengklasifikasikan halaman, kita harus bisa menjawab:

- Sinyal mana yang memicu keputusan?
- Aturan classifier versi berapa yang dipakai?
- Apakah sinyal itu benar?
- Apakah strategi yang dipilih sesuai bukti?
- Apakah kegagalan berasal dari strategi atau dari validator?

Tanpa lineage ini, kita tidak dapat memperbaiki sistem berdasarkan bukti. Kita hanya akan menambahkan lebih banyak aturan secara ad hoc.

## 4. Session recovery harus memiliki protokol tersendiri

Pemulihan sesi tidak boleh berupa fungsi generik `refresh_cookies()`.

Buat kontrak `SessionRecoveryProvider` yang mendukung beberapa mekanisme autentikasi resmi, tanpa mengasumsikan bahwa setiap website mempunyai alur yang sama.

| Tahap | Persyaratan |
|---|---|
| Detect | Bedakan expiry, logout, token invalid, dan gangguan jaringan |
| Quarantine | Tandai sesi sebagai tidak boleh dipakai untuk job baru |
| Recover | Jalankan mekanisme autentikasi yang dikonfigurasi atau tunggu pengguna |
| Validate | Pastikan sesi dapat mengakses resource target |
| Commit | Publikasikan versi sesi baru secara atomik |
| Resume | Lanjutkan hanya job yang aman untuk dilanjutkan |
| Audit | Simpan hasil tanpa menyimpan kredensial mentah |

### Masalah yang perlu diuji

**Race condition.** Dua job dapat mendeteksi sesi kedaluwarsa secara bersamaan dan mencoba memulihkannya bersamaan.

**Stale session.** Job yang sudah berjalan bisa terus menggunakan cookie lama setelah sesi diperbarui.

**Partial recovery.** Login berhasil, tetapi resource target tetap tidak dapat diakses.

**Recovery storm.** Banyak job gagal sekaligus dan semuanya mencoba login ulang.

Solusinya membutuhkan session generation, locking per sesi, single-flight recovery, validasi setelah recovery, dan pembatasan percobaan. Setiap mekanisme harus memiliki tes konkurensi, bukan sekadar unit test fungsi tunggal.

## 5. Competitive benchmark harus menguji penyebab, bukan hanya hasil akhir

Benchmark yang hanya mencatat sukses/gagal terlalu dangkal. Kita perlu mengetahui mengapa satu engine lebih baik atau lebih buruk.

Untuk setiap skenario, ukur empat dimensi:

**Diagnosis quality**

Apakah penyebab kegagalan dikenali dengan benar? Ukur precision, recall, false positive, false negative, dan proporsi hasil UNKNOWN.

**Decision quality**

Apakah strategi berikutnya sesuai dengan ground truth? Ukur tindakan benar, percobaan sia-sia, dan biaya keputusan.

**Recovery quality**

Apakah job atau sesi dapat dipulihkan ketika recovery memang mungkin? Ukur keberhasilan, jumlah langkah, dan konsistensi state.

**Execution efficiency**

Berapa waktu, memori, CPU, jumlah percobaan, dan transfer data yang diperlukan untuk menghasilkan konten valid?

Satu ukuran tambahan penting: **unnecessary escalation rate**, yaitu persentase job yang membuka browser atau memulai recovery meskipun kondisi sebenarnya dapat diselesaikan oleh strategi yang lebih sederhana.

Ukuran tersebut membantu membuktikan apakah planner benar-benar adaptif, bukan sekadar melakukan lebih banyak percobaan.

### Eksperimen kompetitif minimum

Untuk setiap skenario yang dapat dijalankan pada kedua sistem:

1. Gunakan target dan ground truth yang sama.
2. Jalankan dengan kondisi jaringan dan batas sumber daya yang sebanding.
3. Catat versi source, runtime, konfigurasi, dan semua percobaan.
4. Ulangi cukup banyak untuk melihat variasi hasil.
5. Laporkan hasil mentah, median, p95, dan ketidakpastian.
6. Pisahkan skenario yang tidak kompatibel dengan Termux dari skenario yang benar-benar mengukur kualitas algoritme.

Website eksternal dengan proteksi yang berubah-ubah tidak boleh menjadi satu-satunya benchmark. Gunakan fixture lokal untuk diagnosis dan recovery, lalu gunakan target eksternal yang diizinkan sebagai validasi tambahan.

## 6. Strategi implementasi yang lebih disiplin

Saya menyarankan tiga milestone pertama yang jauh lebih ketat daripada langsung membangun seluruh engine.

### Milestone A — Baseline yang dapat diaudit

Hasil wajib:

- Commit Botasaurus yang dipatok.
- Inventaris source dan dependensi.
- Bukti implementasi dan tes per fitur.
- Daftar kapabilitas yang berhasil dijalankan di Termux.
- Laporan batasan runtime browser dan transport.

**Lulus jika:** orang lain dapat mengulang audit dan memperoleh inventaris yang sama pada commit yang sama.

### Milestone B — Diagnosis yang dapat dibuktikan

Hasil wajib:

- Fixture berlabel untuk setiap kelas akses.
- Classifier deterministik.
- Evidence lineage.
- Confusion matrix.
- Tes false positive dan false negative.
- Daftar keputusan yang belum dapat ditentukan dengan yakin.

**Lulus jika:** setiap keputusan dapat ditelusuri ke bukti, dan hasil tes dapat direproduksi.

### Milestone C — Recovery yang tahan race condition

Hasil wajib:

- Session generation.
- Locking dan single-flight recovery.
- Job recovery setelah proses mati.
- Idempotensi operasi yang dapat diulang.
- Tes dua atau lebih job yang berbagi sesi.
- Tes expiry, recovery gagal, dan recovery parsial.

**Lulus jika:** sistem tidak membuat state sukses palsu, tidak menjalankan recovery tanpa batas, dan dapat memulihkan job sesuai aturan yang teruji.

Setelah tiga milestone ini lulus, baru kita dapat mengetahui apakah keunggulan yang dibutuhkan berada pada classifier, session manager, browser adapter, atau bagian lain.

---

## 7. Keputusan arsitektur yang harus dibuat berdasarkan bukti

Ada tiga pertanyaan yang menentukan arah implementasi dan tidak boleh dijawab dengan asumsi.

1. Apakah runtime browser yang diperlukan benar-benar dapat dijalankan di perangkat Termux target?
2. Apakah Botasaurus bisa dipasang dan menjalankan skenario benchmark yang sama di perangkat itu, atau perbandingan harus dilakukan pada dua tingkat: audit source dan benchmark perilaku yang kompatibel?
3. Apakah masalah utama yang ingin dikalahkan adalah **tingkat keberhasilan akses**, **ketepatan diagnosis dan recovery**, atau **efisiensi sumber daya**? Ketiganya saling terkait, tetapi metrik serta strategi optimasinya berbeda.

Rekomendasi saya tetap memulai dengan audit dan benchmark yang dapat direproduksi. Dokumentasi Botasaurus telah menunjukkan fitur request, browser, retry, cache, dan reuse driver, sehingga kita harus mencari perbedaan yang lebih mendalam daripada sekadar meniru atau menambah fitur.

**Hasil yang ingin kita capai bukan blueprint yang lebih panjang, tetapi mesin yang bisa menjelaskan setiap keputusan aksesnya, memulihkan pekerjaan secara benar, dan menunjukkan dengan data kapan ia lebih baik daripada baseline.**

---

# Riset Kandidat: Framework Akuisisi, Transport, dan Browser

Saya akan memperluas pencarian ke **alternatif dan komponen yang belum kita bahas**, bukan sekadar mengulang `httpx`, `requests`, `aiohttp`, dan Playwright. Untuk Universal Web Acquisition Engine (UWAE), ada tiga kelompok yang perlu diperiksa terpisah: framework akuisisi web lengkap, browser dengan implementasi khusus, dan transport HTTP berfitur berbeda.

Satu hal penting: daftar yang banyak belum otomatis lebih kuat dari Botasaurus. Kita perlu membandingkan kemampuan nyata, status pemeliharaan, kompatibilitas Termux, dan hasil benchmark. Sebuah perbandingan teknis yang diperbarui pada Agustus 2026 juga mencakup Camoufox, Patchright, SeleniumBase, Scrapling, dan beberapa browser khusus lainnya—tetapi klaim keberhasilannya tetap perlu diverifikasi secara mandiri.

## 1. Kandidat tambahan yang layak diaudit

## 2. Framework akuisisi web dan crawling

**1. Scrapling**

**Prioritas audit tinggi**

Menggabungkan HTTP fetching, browser dinamis, spider, session, adaptive selector, dan pengambilan respons XHR. Cocok dijadikan pembanding langsung bagi desain UWAE karena mencakup beberapa lapisan yang ingin kamu bangun.

Audit: API, dependensi browser, kompatibilitas Android, session recovery, selector adaptif.

[GitHub](https://github.com/D4Vinci/Scrapling) · [Dokumentasi](https://scrapling.readthedocs.io/)

**2. Crawlee**

Kuat untuk request queue, pengaturan concurrency, retry, dan pengelolaan sesi. `SessionPool` mengelola cookies serta state sesi dan dapat menandai sesi bermasalah agar tidak terus digunakan.

Audit: persistence, antrean tahan restart, session pool, pembatasan laju, recovery.

[GitHub Python](https://github.com/apify/crawlee-python) · [Dokumentasi](https://crawlee.dev/python/)

**3. Scrapy**

Pembanding untuk crawling berskala besar: scheduler, downloader middleware, pipeline, retry, deduplikasi, dan kontrol laju. Tidak menggantikan browser untuk merender JavaScript dengan sendirinya.

Audit: arsitektur downloader, middleware, ketahanan job, penggunaan memori.

[GitHub](https://github.com/scrapy/scrapy) · [Dokumentasi](https://docs.scrapy.org/)

**4. Crawl4AI**

Relevan jika UWAE kelak perlu menghasilkan Markdown, konten bersih, atau data terstruktur untuk sistem AI. Bandingkan ekstraksi dan pemrosesan konten, bukan hanya keberhasilan membuka situs.

[GitHub](https://github.com/unclecode/crawl4ai) · [Dokumentasi](https://docs.crawl4ai.com/)

**5. Firecrawl**

Berguna sebagai pembanding hasil ekstraksi dan crawling berbasis API. Periksa secara terpisah mana yang berjalan lokal, membutuhkan layanan eksternal, atau memiliki batasan lisensi.

[GitHub](https://github.com/firecrawl/firecrawl)

## 3. Transport HTTP tambahan

Ini penting karena **HTTP client bukan sekadar pilihan nama library**. Implementasi berbeda dalam protokol, pengelolaan koneksi, DNS, TLS, cookies, dan perilaku retry.

| Kandidat | Alasan masuk audit | Hal yang harus diuji |
|---|---|---|
| Niquests | Alternatif Requests dengan dukungan HTTP/1.1, HTTP/2, dan HTTP/3 | Negosiasi protokol, QUIC, dependensi, kompatibilitas Android |
| curl_cffi | TLS dan HTTP/2 fingerprint browser tertentu | Ketersediaan wheel ARM64, TLS, proxy, stabilitas |
| urllib3 | Lapisan koneksi dan pooling HTTP | Timeout, pool, retry, koneksi persisten |
| httpx | HTTP sinkron/asinkron | Pool, timeout, streaming, HTTP/2 |
| aiohttp | Transport asinkron | Throughput, konsumsi RAM, koneksi |
| pycurl | Akses ke kapabilitas libcurl | Ketersediaan libcurl, build native, protokol |

Niquests secara resmi mendokumentasikan HTTP/1.1, HTTP/2, dan HTTP/3; `curl_cffi` mendokumentasikan dukungan fingerprint TLS/JA3 dan HTTP/2. Namun, kemampuan tersebut tidak menjamin situs tertentu akan memberikan akses.

Tautan audit:

- [Niquests](https://github.com/jawah/niquests)
- [curl_cffi](https://github.com/lexiforest/curl_cffi)
- [urllib3](https://github.com/urllib3/urllib3)
- [HTTPX](https://github.com/encode/httpx)
- [aiohttp](https://github.com/aio-libs/aiohttp)
- [PycURL](https://github.com/pycurl/pycurl)

**Catatan khusus Termux:** jangan menganggap dukungan Python di Linux desktop berarti paket native tersebut pasti terpasang di Android ARM64. Setiap kandidat perlu diuji instalasi, impor modul, request HTTPS, dan dependensinya pada perangkatmu.

## 4. Browser dan mesin otomasi yang belum boleh dilewatkan

**Camoufox**

Browser berbasis Firefox dengan modifikasi fingerprint. Layak diuji sebagai jalur browser alternatif Chromium, tetapi binary khusus dan dukungan ARM64 menjadi risiko besar di Termux.

[GitHub](https://github.com/daijro/camoufox)

**Patchright**

Alternatif berbasis Playwright yang memodifikasi implementasi driver. Audit perubahan kode, sinkronisasi versi Playwright, instalasi browser, dan risiko pemeliharaan.

[GitHub](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright)

**SeleniumBase**

Kerangka otomasi browser dengan berbagai mode driver. Cocok sebagai pembanding kematangan pengujian, konfigurasi browser, dan penanganan sesi.

[GitHub](https://github.com/seleniumbase/SeleniumBase)

**Nodriver**

Mengendalikan browser melalui Chrome DevTools Protocol tanpa pendekatan WebDriver tradisional. Perlu diuji apakah dependensi browser dan prosesnya realistis di lingkungan Android.

[GitHub](https://github.com/ultrafunkamsterdam/nodriver)

**Playwright**

Baseline browser automation untuk halaman JavaScript, navigasi, cookies, dan pengujian interaksi. Bukan solusi universal untuk semua sistem proteksi.

[GitHub](https://github.com/microsoft/playwright)

Perbandingan proyek anti-detection terbaru mencakup sebagian besar kandidat di atas dan menekankan pentingnya memeriksa source, versi binary, lisensi, serta aktivitas pemeliharaan, bukan mengandalkan klaim pemasaran.

## 5. Kandidat pendukung yang juga penting

Selain framework utama, audit komponen khusus ini:

- **Parsing dan ekstraksi:** selectolax, lxml, Beautiful Soup, Parsel.
- **Browser protocol:** Chrome DevTools Protocol (CDP), Playwright browser contexts, dan event jaringan.
- **Antrean serta pemulihan job:** SQLite sebagai baseline lokal; evaluasi antrean persisten dan idempotensi sebelum menambah database yang berat.
- **Penyimpanan artefak:** hash SHA-256, metadata respons, file sementara atomik, deteksi tipe MIME, dan dukungan unduhan yang dapat dilanjutkan bila server mengizinkan.
- **Diagnostik akses:** pencatatan status HTTP, redirect, `Retry-After`, jenis konten, ukuran body, waktu koneksi, kegagalan TLS/DNS, dan indikator halaman challenge.
- **Observabilitas:** log terstruktur JSONL, ID job/attempt/session, metrik p50/p95, dan laporan reproduksi benchmark.

## 6. Urutan audit yang saya rekomendasikan

| Prioritas | Kandidat | Pertanyaan yang harus dijawab |
|---|---|---|
| P0 | Scrapling | Apakah satu framework sudah menyediakan banyak kemampuan inti UWAE? |
| P0 | Crawlee Python | Seberapa matang pengelolaan sesi, retry, antrean, dan pemulihannya? |
| P0 | Niquests + `curl_cffi` | Apa perbedaan protokol, fingerprint, dependensi, dan hasil request? |
| P1 | Scrapy | Apakah arsitektur crawling dan middleware-nya dapat diadaptasi? |
| P1 | Playwright + Patchright | Apa biaya dan kompatibilitas jalur browser? |
| P1 | Camoufox + Nodriver + SeleniumBase | Apakah ada manfaat yang terukur dibanding baseline browser? |
| P2 | Crawl4AI + Firecrawl | Seberapa baik kualitas ekstraksi dan output untuk konsumen AI? |

**Jangan instal semua sekaligus.** Audit metadata dan source lebih dahulu, lalu uji setiap kandidat dalam lingkungan terpisah. Khusus Termux, kandidat browser yang membutuhkan binary Linux desktop mungkin tidak layak dipakai langsung walaupun API Python-nya tersedia.

Target akhirnya bukan mengumpulkan sebanyak mungkin library. UWAE perlu membuktikan bahwa ia memilih jalur akses yang tepat, mengenali penyebab kegagalan, memulihkan sesi tanpa mengulang pekerjaan secara tidak perlu, dan menyimpan hasil yang dapat diverifikasi. CAPTCHA atau penolakan akses tetap harus dapat menghasilkan status `NEEDS_USER` atau `ACCESS_DENIED`, bukan memicu percobaan tanpa batas.

---

If you want, I can:

- Jelaskan pendekatan audit untuk Scrapling
- Bandingkan keunggulan Crawlee dan Scrapy
- Rancang skenario uji untuk browser Camoufox di Termux

---

# Lampiran — Varian dari Snapshot Percakapan

> **Sumber:** Snapshot MHTML "Audit Dan Benchmark Botasaurus" (percakapan `6ad6d71a-d4a0-83ec-a977-da3905ad753b`, disimpan 2026-10-20) — varian dari percakapan yang sama dengan tambahan yang tidak ada di versi share. Kata-kata asli dipertahankan; artefak render DOM (kode inline terpotong baris) dirapikan.

## L.1 Klarifikasi makna "lebih dari 120 modul"

Sebelum membuat blueprint baru, kita perlu mengaudit struktur nyata Botasaurus yang ada di lingkunganmu. Apakah yang kamu maksud lebih dari 120 modul itu adalah:

- **A.** Lebih dari 120 file atau modul Python milik Botasaurus.
- **B.** Lebih dari 120 paket dan modul jika seluruh dependensi dalam `venv` ikut dihitung.
- **C.** Lebih dari 120 modul yang kamu hitung dari direktori `site-packages`, tetapi belum dipisahkan berdasarkan pemiliknya.

Perbedaan ini penting karena akan menentukan metode audit, perbandingan arsitektur, dan cara kita menetapkan target implementasi Universal Web Acquisition Engine.

## L.2 Phase 0 exit checklist

Gunakan checklist ini untuk memastikan agent benar-benar menyelesaikan audit, bukan sekadar menghasilkan Markdown panjang.

- [ ] Snapshot Botasaurus dan commit SHA tercatat.
- [ ] Peta dependensi mencakup kode internal dan dependensi eksternal yang relevan.
- [ ] Temuan penting memiliki bukti source, test, atau eksperimen.
- [ ] Capability matrix membedakan fakta dan hipotesis.
- [ ] Benchmark memiliki ground truth dan skema hasil.
- [ ] Pengukuran mencakup kebenaran hasil, kegagalan, latency, dan resource use.
- [ ] Kontrak Job, ArtifactManifest, AcquisitionResult, dan plugin telah ditinjau.
- [ ] ADR menyatakan alternatif, trade-off, dan keputusan yang masih terbuka.
- [ ] Roadmap Phase 1 memiliki acceptance criteria yang dapat diuji.
- [ ] Perubahan tidak merusak file atau keputusan proyek yang sudah ada.

## L.3 Deliverable audit transport (path file)

Hasil yang harus dihasilkan:

- `docs/audit/transport-ecosystem.md`
- `docs/benchmark/transport-matrix.json`
- `docs/benchmark/transport-results.json`
- `docs/architecture/decisions/ADR-transport-selection.md`

## L.4 Klarifikasi HTTPX vs HTTP/2 vs HTTP/3

Satu catatan penting: HTTPX bukan nama lengkap dari seluruh lapisan HTTP. HTTP/2 dan HTTP/3 merupakan protokol, sedangkan HTTPX adalah implementasi klien HTTP. TLS fingerprint, browser automation, dan pemulihan challenge juga merupakan lapisan yang berbeda. Memisahkan semuanya akan membuat perbandingan lebih akurat.

## L.5 Lifecycle wajib diaudit

- **Execution lifecycle:** pembuatan tugas, scheduling, retry, cancellation, error propagation, cleanup dan shutdown.
- **HTTP lifecycle:** redirect, timeout, streaming, penanganan `Content-Length`, transfer encoding, partial response, serta respons HTTP error.
- **Browser lifecycle:** startup, reuse, cookies, storage, timeout, crash recovery, dan penutupan proses.
- **Cache correctness:** cache key, invalidation, perubahan sesi, metadata yang sensitif, serta perilaku saat cache rusak.
- **Failure semantics:** apakah kegagalan dicatat, ditelan, dilempar kembali, atau menyebabkan seluruh batch berhenti.
- **File acquisition:** penentuan nama file, file tanpa ekstensi, respons berukuran besar, checksum, dan pemulihan unduhan parsial.
- **Access challenges:** deteksi halaman challenge, status autentikasi, rate limiting, dan alur verifikasi manual.

## L.6 Temuan target verifikasi (isu publik Botasaurus)

Satu temuan yang layak dijadikan target verifikasi adalah isu publik Botasaurus mengenai timeout Cloudflare bypass dan infinite retry pada kegagalan resolusi DNS. Isu tersebut merupakan sinyal untuk menyusun regression test, bukan bukti bahwa seluruh rilis mengalami masalah yang sama.
