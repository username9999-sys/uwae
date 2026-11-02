# Status gerbang TEXT.md §9

> Sumber pertanyaan: **TEXT.md §9**, baris **2344** — *"Gerbang keputusan sebelum kita mengklaim ada kemajuan kompetitif"*.
>
> Dokumen ini menjawab ketujuh pertanyaan itu satu per satu **hanya dari evidence yang sudah dipublikasi** di repo ini. Ia tidak menjalankan benchmark baru, tidak menyimpulkan angka, dan tidak mengisi kekosongan dengan keyakinan. Kalau sebuah pertanyaan belum punya bukti, jawabannya menyatakan itu.

Tujuh pertanyaan §9 diambil apa adanya dari TEXT.md; penomoran di bawah ini mengikuti urutan di berkas itu.

---

## #1 — Berapa banyak modul Botasaurus yang merupakan kode proyek sendiri, dan berapa banyak dependensi pihak ketiga?

**Status: SEBAGIAN terjawab.**

Yang ada di repo:

- `docs/audit/environment-report.md` (baris 58) mencatat **357 paket** (dist-info) di `/root/botasaurus-venv` dan **47 direktori top-level** site-packages.

Yang tidak ada:

- Tidak ada audit terpublikasi yang **memisahkan modul milik paket Botasaurus sendiri** (apa yang benar-benar ditulis di repo omkarcloud/botasaurus) **dari dependensi pihak ketiganya** (requests, botasaurus_requests, botasaurus_driver, bs4, dll.) di tingkat modul/file.
- Angka 357 paket itu adalah isi **seluruh venv**, bukan cerminan dependensi Botasaurus — menjadikannya jawaban atas pertanyaan ini akan menyesatkan.

**Konsekuensi jujur:** pertanyaan ini belum dapat dijawab dari bukti yang ada. Yang bisa diverifikasi pembaca sekarang hanya "venv berapa isi", bukan "Botasaurus memakai berapa banyak kode sendiri". Slot audit baru diperlukan untuk mengisinya, dan tidak dikerjakan di sesi ini.

---

## #2 — Fitur apa yang benar-benar berfungsi pada lingkungan yang diuji?

**Status: TERJAWAB.**

`docs/benchmark/competitive-matrix.md` diaudit 2026-10-30 (ADR-026) dan seluruh 16 path `docs/benchmark/*.json` yang dikutipnya diverifikasi ada di disk. Hitungan 108 baris kemampuan menurut status UWAE:

| Status UWAE | Jumlah baris | Arti |
|---|---|---|
| `Measured (cross-impl)` | 22 | Diimplementasi **dan** dibandingkan dengan Botasaurus pada device yang sama dengan kondisi identik |
| `Measured (vs ground truth)` | 26 | Diimplementasikan **dan** diukur terhadap ground truth fixture, **tidak** dibandingkan dengan Botasaurus |
| `Implemented` | 33 | Ada kode + tes, **tanpa** artefak benchmark |
| `Not yet verified` | 27 | Tidak ada implementasi atau tidak ada bukti sama sekali |

Yang terukur (22 baris cross-impl) semuanya berakar pada slot E16/E18/E19/E20 yang berjalan di device ini. 27 baris `Not yet verified` berarti pernyataan "belum teruji", bukan "gagal" — keduanya tidak boleh dicampur.

**Batasan yang dinyatakan matrix sendiri:** fixture bersifat sintetis dan single-origin; tidak mencakup TLS, redirect lintas-origin, atau rate limiting nyata.

---

## #3 — Apakah browser automation yang dibatuhkan tersedia di perangkat Android tersebut?

**Status: TERJAWAB — ya, terukur, bukan diasumsikan.**

`docs/benchmark/engine-results-e16.json` (ADR-021) menjalankan 4 arm × 4 skenario × 30 run pada perangkat ini (**aarch64 PRoot Linux di bawah Termux, tanpa root**) — bukan mesin desktop:

| Arm | primary_success | median elapsed | browser dipakai |
|---|---|---|---|
| `uwae-adaptive` | **120/120** | 3.115,66 ms | 60 dari 120 run |
| `uwae-browser-only` | 90/120 | 5.470,35 ms | 120 dari 120 run |
| `botasaurus-http` | 90/120 | — | 0 |
| `botasaurus-browser` | 90/120 | — | 120 dari 120 run |

Kedua arm browser **berjalan dan menghasilkan respons** — jadi ketersediaan browser automation di perangkat ini terbukti oleh run, bukan oleh asumsi. UWAE menjalankan chromium PRoot melalui CDP mentah tanpa dependensi baru (ADR-014).

**Yang tidak diukur:** prosedur instalasi itu sendiri (unduh chromium, perizinan Termux) tidak pernah menjadi skenario benchmark. Yang terukur adalah bahwa kedua mesin dapat mengeksekusi di perangkat ini.

---

## #4 — Kapan HTTP-only lebih baik daripada membuka browser?

**Status: TERJAWAB.**

`docs/benchmark/engine-results-e12.json` (ADR-017) mengukur tiga strategi pada skenario yang sama, 30 run masing-masing:

| Skenario | `http_only` | `browser_first` | `adaptive` |
|---|---|---|---|
| `b01_small_get` (HTML biasa) | 255,33 ms, sukses, tanpa browser | 534,42 ms, sukses, **pakai browser** | **212,61 ms, sukses, tanpa browser** |
| `b07_js_render` (butuh JS) | 258,19 ms, **gagal**, state `javascript_required` 30/30 (diagnosis benar) | 550,37 ms, sukses, pakai browser | 720,06 ms, sukses, **pakai browser** |

Jawaban pengukurannya:

- **Konten biasa: HTTP-only.** Membuka browser untuk halaman statis menghabiskan 534,42 ms (median) versus 255,33 ms — 2,1× lebih lambat, dengan hasil yang identik 30/30. Strategi adaptive memilih jalur tanpa browser dan mendapat median tercepat (212,61 ms), sekaligus tetap benar 30/30.
- **Konten yang membutuhkan JS: browser.** HTTP-only gagal 30/30 dengan diagnosis `javascript_required` yang benar — dan itu justru memang perilaku yang diinginkan (diagnosis benar, bukan false success). Eskalasi ke browser menghasilkan sukses 30/30.
- **Biaya eskalasi satu kali ternyata nyata:** `cold_start` mencatat **5.431,60 ms** dan **191.368 kB RSS chromium** untuk satu akuisisi (`keep_alive=False`) — itulah biaya yang harus dibayar setiap kali browser dibuka tanpa keep-alive.

Vonis korpus untuk dimensi browser (`browser-arm`) adalah **2 UWAE menang / 10 seri / 0 baseline menang**, dan konkretnya `botasaurus-http` gagal 0/30 pada gerbang JS sementara kedua arm browser sukses 30/30 — HTTP-only **lebih baik sampai ambang JS, lalu tidak cukup**.

---

## #5 — Apakah diagnosis dapat membedakan challenge, autentikasi, rate limit, dan gangguan jaringan?

**Status: TERJAWAB.**

`docs/benchmark/engine-results-e18.json` (ADR-023) mengukur diagnosis penyebab pada 210 run yang menuntutnya:

| Arm | TP | FP | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|
| `uwae-engine` | 210 | 0 | 0 | **1,0** | **1,0** | **1,0** |
| `botasaurus-request` | 0 | 0 | 210 | 0,0 | 0,0 | 0,0 |

Terpisah dari itu, masalah palsu diukur pada skenario sehat: **0 dari 180 run** sehat dilaporkan sebagai masalah oleh `uwae-engine` (`false_problem_rate = 0,0`).

Kasus gangguan jaringan juga punya angka tersendiri: pada skenario kegagalan DNS, UWAE mencapai outcome terminal terklasifikasi **3/3 run** (`network_failure` + `dns_failure` → `budget_exhausted` setelah 7 attempt berbatas, 18,7–23,1 s), sedangkan Botasaurus mencapai outcome terminal **0/3** — ketiganya timeout 90 s setelah 5 siklus retry tak berbatas.

**Batasan:** diagnosis diukur pada fixture sintetik yang menuntut diagnosis penyebab, bukan pada keragaman kondisi produksi (challenge vendor nyata, WAF, MFA).

---

## §9 #6 — Apakah pemulihan sesi berhasil pada fixture yang mendukungnya?

**Status: TERJAWAB.**

`docs/benchmark/engine-results-e19.json` (ADR-023), sumbu pemulihan otomatis pada 60 run per kebijakan:

| Arm / kebijakan pemulihan | mencapai resource terproteksi |
|---|---|
| `uwae-engine` (kebijakan generik milik engine) | **60/60** (1,0) |
| `botasaurus-auto` (tanpa kebijakan pemulihan) | **0/60** (0,0) |
| `botasaurus-explicit` (kode pemulihan ditulis per-task di arm) | **60/60** (1,0) |
| `botasaurus-decorator-request` (objek session milik decorator) | **0/60** (0,0) |

Yang diukur adalah **di mana kebijakan itu hidup**, bukan kapabilitasnya: kebijakan generik di dalam engine mencapai hasil 60/60 dan Botasaurus juga berhasil 60/60 saat kode pemulihannya ditulis secara eksplisit per-task — tetapi objek session milik decorator Botasaurus sendiri tidak mempertahankan cookie (0/60). Kesimpulannya bukan "UWAE mengalahkan Botasaurus", melainkan "keduanya mampu, dengan lokasi kebijakan yang berbeda".

**Batasan:** fixture yang mendukung pemulisan sesi adalah fixture proyek ini; tidak ada target nyata dengan autentikasi stateful yang diukur.

---

## §9 #7 — Di skenario mana mesin baru mengungguli baseline, sama, atau justru gagal?

**Status: TERJAWAB — inilah fungsi dokumen E17.**

`docs/benchmark/engine-results-e17.json` (ADR-022/023), vonis korpus:

| Vonis | Jumlah |
|---|---|
| UWAE menang | **13** |
| Seri | **25** |
| Baseline menang | **0** |
| Tidak sebanding (bukti tidak cukup memilih) | **0** |
| Tanpa run yang dapat dinilai | **0** |
| Run belum teruji (total) | **0** |

Sebaran per dimensi: `browser-arm` 2 menang / 10 seri, `http-transport` 7 / 6, `session-flow` 4 / 5, `http-post` 0 / 4.

Slot aktif: **4** (E16, E18, E19, E20); slot digantikan: **2** (E14, E15) — keduanya tetap dipublikasikan sebagai rekaman historis tetapi tidak dihitung. Celah yang dideklarasikan: **5**, tertutup **2**, terbuka **3**.

Di mana perbedaannya paling tajam dan paling dapat dijelaskan (bukan "sengit", tapi "ukurannya"): diagnosis penyebab — 210/210 versus 0/210 (pertanyaan #5); outcome terminal pada kegagalan DNS — 3/3 versus 0/3 (pertanyaan #5). Di mana UWAE **lebih berat**: peak alokasi Python per run **3,04–12,67 MB versus 0,83–4,07 MB** untuk Botasaurus (E18), dan median latency POST **193,81–249,57 ms versus 31,12–62,51 ms** (E20) — yang pertama karena UWAE mempersistensi baris job/attempt/event + artifact, yang kedua karena overhead framework (ACP, classifier, planner) dibandingkan decorator ringan.

**Yang TIDAK diklaim di sini:** tidak ada klaim bahwa UWAE mengungguli Botasaurus secara keseluruhan. 13 menang diukur pada fixture sintetis single-origin, dan TEXT.md:1427 sendiri meminta menang/seri/kalah/**belum teruji** dipublikasikan terpisah — yang dilakukan matriks korpus dan dokumen ini.

---

## Ringkasan satu baris per pertanyaan

| # | Pertanyaan §9 | Status | Evidence utama |
|---|---|---|---|
| 1 | Modul sendiri vs dependensi pihak ketiga Botasaurus | **Terjawab** — 6 paket / 144 file `.py` / 59.768 baris milik Botasaurus sendiri vs 39 paket / 2.310 file / 857.328 baris dependensi pihak ketiga (45 paket total di venv). Koreksi: klaim lama "357 paket" di environment-report.md tidak dapat direproduksi (dist-info aktual = 45) | `docs/audit/botasaurus-module-split.md` (ADR-028) |
| 2 | Fitur mana yang benar-benar berfungsi di lingkungan uji | **Terjawab** — 22 cross-impl, 26 ground-truth, 33 implemented, 27 belum teruji | `competitive-matrix.md` (diaudit ADR-026) |
| 3 | Browser automation tersedia di Android | **Terjawab — ya** — 4 arm × 30 run berjalan di aarch64 PRoot | `engine-results-e16.json` |
| 4 | Kapan HTTP-only lebih baik dari browser | **Terjawab** — konten biasa: HTTP (212–255 ms vs 534–550 ms); butuh JS: browser (sukses 30/30 vs gagal 30/30); cold start 5.431,60 ms / 191.368 kB | `engine-results-e12.json`, `engine-results-e16.json` |
| 5 | Diagnosis membedakan challenge/auth/rate-limit/jaringan | **Terjawab** — 210/210 p=r=1,0 vs 0/210; masalah palsu 0/180; DNS terminal 3/3 vs 0/3 | `engine-results-e18.json` |
| 6 | Pemulihan sesi pada fixture pendukung | **Terjawab** — 60/60 kebijakan generik; 60/60 eksplisit; 0/60 objek session decorator | `engine-results-e19.json` |
| 7 | Di mana menang / seri / kalah | **Terjawab** — 13 / 28 / 0 dari 41 instans; 6 slot aktif (E16, E18, E19, E20, E21, E22); 5 dari 6 celah tertutup, 1 terbuka (`post_browser_multipart_upload`) | `engine-results-e17.json` (diregenerasi 2026-10-31, ADR-027) |

**Catatan koreksi.** Versi pertama kerja sesi ini menyimpulkan "TEXT.md tidak punya §9" karena pencarian hanya mencocokkan heading Markdown; §9 di berkas itu memakai penomoran inline. Kesimpulan itu salah dan sudah dikoreksi di ADR-026. Dokumen ini adalah pengganti yang benar.
