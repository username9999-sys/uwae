# ADR-021: Browser-arm differential — mengukur dimensi browser UWAE vs Botasaurus pada device yang sama

## Status
Accepted (2026-10-27 — evidence: engine-results-e16.json, benchmark_id `e16-browser-arm-differential-001`)

## Context

E14 mengukur alur HTTP; E15 mengukur alur sesi. Keduanya menutup dua gerbang
TEXT.md §9, tapi **dimensi browser belum pernah diukur lintas-implementasi**.
E14 sendiri mendeklarasikannya sebagai skenario tak didukung:

```json
{
  "scenario_id": "js_rendering_browser_arm",
  "reason": "Kedua arm di benchmark ini adalah arm HTTP. Rendering JavaScript butuh arm browser; Botasaurus memakai driver CDP (bukan chromedriver) dan UWAE memakai raw CDP (ADR-014) — keduanya belum diukur pada device ini, jadi tidak diklaim sebagai perbedaan engine.",
  "supported_by": []
}
```

E16 menutup celah itu. Tiga pertanyaan yang dijawab:

1. **Apakah browser automation benar-benar bisa dijalankan di device Android/
   Termux ini — untuk KEDUA implementasi?** (gerbang TEXT.md §9 #3)
2. **Kapan HTTP-only lebih baik daripada membuka browser?** (#4)
3. **Di skenario mana masing-masing menang, seri, atau gagal?** (#7)

### Probe lebih dulu, benchmark kemudian

Sebelum menulis benchmark, platform diuji empiris: driver CDP Botasaurus
dijalankan terhadap fixture lokal di PRoot aarch64. Verdict: **berhasil**.
Tanpa probe itu, kegagalan arm browser Botasaurus akan ambigu — bisa jadi
batas platform, bisa jadi skrip yang ditulis buruk. E16 tidak boleh mengukur
keduanya tanpa probe lebih dulu.

### Tiga kesalahan yang harus dihindari

1. **Strawman baseline.** Botasaurus punya API browser publik (`@browser`,
   `driver.get`, `tab.get_content`, `tab.evaluate`). Lengan browser
   Botasaurus memakai API itu — bentuk terkuat yang Botasaurus tawarkan.
   Kalau lengan itu gagal, kesimpulan yang sah hanya "bukti platform".
2. **Kriteria byte-for-byte.** Output browser adalah
   `document.documentElement.outerHTML` — doctype hilang, newline tambahan.
   Body browser **tidak pernah** byte-identik dengan body sumber. Kriteria
   byte-for-byte akan otomatis membuat browser gagal di **semua** skenario,
   termasuk yang seharusnya ia menang. Itu bukan pengukuran, itu stereotip.
3. **Self-report sebagai bukti, dan "sinyal tertutup" yang tak terlihat.**
   Status 200 dengan body rusak BUKAN keberhasilan. Kalau harness hanya
   melihat status, ia akan memberi kredit pada lengan yang justru menutup
   sinyal kegagalan.

## Decision

### 1. Empat lengan, tiga sumbu ortogonal

| Lengan | Transport |_sumbu_ yang diisolasi_ |
|---|---|---|
| `uwae-adaptive` | HTTP dulu, browser bila planner memintanya | **strategi** (kapan membuka browser) |
| `uwae-browser-only` | browser dari attempt pertama | **implementasi browser** UWAE |
| `botasaurus-http` | HTTP saja (jalur publik `@request`) | **baseline tanpa browser** |
| `botasaurus-browser` | browser saja (`@browser` + CDP driver) | **implementasi browser** Botasaurus |

`uwae-browser-only` vs `botasaurus-browser` adalah perbandingan yang paling
apples-to-apples: dua implementasi browser, transport sama, kriteria sama.
`uwae-adaptive` vs `botasaurus-http` menguji apakah dimensi browser menambah
kemampuan atau hanya menambah biaya.

### 2. Kriteria berbasis marker, bukan byte-for-byte

Tiap skenario punya ground truth dari **semantika protokol fixture** — marker
wajib dan marker terlarang yang diturunkan dari body yang benar-benar
dilayani fixture — plus `expect_status`. Kriteria itu diterapkan **IDENTIK**
ke semua lengan, dan dinilai di **satu tempat** (parent), bukan di dalam
skrip lengan. Lengan hanya mengembalikan body; ia tidak pernah menilai
dirinya sendiri.

### 3. Tiga sumbu ortogonal

| Sumbu | Arti | Kapan berlaku |
|---|---|---|
| `body_acquired` | body target benar-benar diperoleh: status sesuai, marker wajib ada, marker terlarang tidak ada | semua skenario |
| `byte_faithful` | body identik byte-per-byte dengan body sumber | semua skenario, tapi **denominator sendiri** |
| `signal_preserved` | sinyal kegagalan yang dideklarasikan skenario tetap terlihat bagi konsumen | skenario dengan `failure_signal` |

`byte_faithful` bernilai `None` bila lengan **tidak punya body sama sekali**.
`None` berarti "tidak ada yang diukur" — bukan "fidelitas gagal". Mengambil
`False` akan menyiratkan lengan mencoba menyimpan byte lalu gagal, dan
mencorot lengan yang justru berperilaku benar (menolak menyimpan byte korup).

### 4. Sumbu sinyal kegagalan menerima DUA kanal

Rancangan pertama sempat salah: `signal_preserved` menuntut marker challenge
terlihat di **body**. Itu memihak satu pihak. UWAE tidak mengirim body pada
skenario challenge (diagnosis `challenge_present` -> `needs_user`, tanpa
artifact), sehingga sumbu menilai `False` **padahal sinyal justru terlihat**
lewat kanal diagnosis. Botasaurus tidak punya lapisan diagnosis, jadi
kewalianya hanya body.

Kriteria yang dipakai:

```
signal_preserved = (kanal BODY terpenuhi) ATAU (kanal DIAGNOSIS terpenuhi)
```

Kanal yang dipakai ikut dicatat di `signal_channel`. Perbedaan kanal adalah
**perbedaan arsitektur**, bukan perbedaan kemampuan — dan tidak boleh
disembunyikan di balik satu angka.

### 5. Kriteria primer per skenario dari semantika fixture

| Skenario | Path | Kriteria primer | Alasan |
|---|---|---|---|
| `b01_small_get` | `/html` | `body_acquired` | HTML biasa tanpa JS — yang diukur adalah **biaya**: HTTP seharusnya cukup |
| `b07_js_render` | `/js` | `body_acquired` | gerbang JS: hanya render browser yang menghasilkan konten target |
| `a11_invalid_html` | `/invalid-html` | `signal_preserved` | 200 dengan body rusak **bukan** keberhasilan |
| `a07_challenge` | `/challenge` | `signal_preserved` | yang diuji bukan pemecahan challenge, tapi apakah sinyalnya **tertutup** |

Kriteria `a11_invalid_html` pernah salah dipilih `byte_faithful` — yang menghukum
UWAE **karena ia menolak menyimpan byte korup**. Itu perilaku benar, bukan
gagal menyimpan byte. Kriteria primernya karena itu `signal_preserved`, dengan
dua kanal: body byte-faithful **atau** diagnosis `content_invalid`.

### 6. Status HTTP dibaca dengan mekanisme yang sama di kedua lengan

`botasaurus_driver` **tidak mengekspos status HTTP sama sekali** (grep atas
seluruh paket: nol hasil). Karena itu lengan browser Botasaurus membacanya dari
JS:

```js
String((performance.getEntriesByType('navigation')[0] || {}).responseStatus || 0)
```

Mekanisme itu **persis sama** dengan yang dipakai UWAE (ADR-014). Tanpa
kesetaraan ini, adjudikasi memberi privilege ke salah satu lengan.

### 7. Bukti sisi server dengan path breakdown

Chromium melakukan request sampingan (`/favicon.ico`) selain navigasi. Fixture
merekam setiap request yang benar-benar diterima, dan harness melaporkan
**path breakdown**, bukan cuma total. Kalau hanya total yang dilaporkan,
"1 request" vs "2 request" terlihat seperti selisih biaya yang palsu.

### 8. Satu subprocess per run

State browser dan state server bisa bocor antar run. Isolating subprocess
memastikan tiap run mulai dari kondisi identik. Biayanya mahal — cold start
chromium dibayar penuh di tiap run — tapi itu **biaya produksi yang harus
diukur**, bukan disembunyikan dengan warm reuse. UWAE memakai
`CDPBrowserAdapter(keep_alive=False)` (default produksi) dan Botasaurus
memakai `@browser` dengan `cache=False`, `reuse_driver=False` — keduanya
start chromium baru per run.

### 9. n=30 sejak awal

TEXT.md §6.3: "Minimal 30 pengulangan untuk skenario benchmark utama sebelum
membandingkan performa." E14/E15 jalan di n=5 dan harus menyatakan p95-nya
belum bermakna. E16 memenuhi gerbang ini sejak awal, sehingga p95 boleh
dilaporkan tanpa disclaimer.

### 10. Konfigurasi lengan dicatat eksplisit

Kondisi identik tidak boleh hanya **diklaim** lewat boolean
`identical_conditions`; konfigurasi yang mendasarinya harus tercatat supaya
bisa diaudit. `arm_configuration` mencatat transport, kebijakan retry,
siklus hidup browser, sumber status HTTP, dan keberadaan lapisan diagnosis
untuk tiap lengan.

Asimetri retry memang ada dan **diproyeksikan sebagai desain yang berbeda,
bukan pilihan harness**: UWAE memakai `RetryPolicy(max_retries=2)` sehingga
planner escalate ke browser selama `retry_attempt <= max_retries` lalu berhenti
di `needs_user` — batas 4 attempt. Botasaurus memakai default pustakanya
(`max_retry` tidak disetel) dan retry-nya hanya menyala bila task melempar
exception; ia tidak punya mekanisme yang bisa bereaksi pada sinyal yang
**terdeteksi**. Jumlah attempt per lengan pada skenario failure berbeda, dan
itu terlihat langsung dari path breakdown sisi server.

### 11. Checkpoint per-run, dan evidence ditulis ulang dari checkpoint

Percobaan run penuh pertama mati di **393/480 run** karena perangkat
Android/Termux reboot — dan karena evidence hanya ditulis di akhir `main()`,
seluruh 393 run itu hilang tanpa jejak: log hanya berisi baris progres, tanpa
`status_code`, `body_sha256`, `diagnosis_state`, atau `terminal_status`.

Keputusan: **setiap run yang selesai langsung ditulis ke checkpoint JSONL**
(flush + `fsync`), di luar repo, dengan kunci `(skenario, lengan, run_index)`.
Restart melanjutkan dari cell terakhir, bukan dari nol. Yang disimpan adalah
**row kasar** (hasil pengukuran per run), bukan ringkasan — sehingga aturan
adjudikasi bisa diubah dan ringkasan dihitung ulang tanpa mengulang
benchmark.

Checkpoint membawa **sidik jari konfigurasi harness** (skrip lengan, skenario,
jumlah run, timeout, port CDP, hash body sumber). Record dengan sidik jari
berbeda **diabaikan dan dilaporkan**, supaya run lama tidak pernah diam-diam
dicampur dengan run baru yang memakai kriteria berbeda. Baris JSON yang
terpotong (proses mati tepat saat menulis) juga diabaikan tanpa menggagalkan
seluruh checkpoint.

Konsekuensi yang diakui: device yang reboot berulang kali **tidak** menghapus
pekerjaan, tapi run yang dipakai ulang berasal dari base URL fixture berbeda
karena `port=0` memakai port bebas. Base URL dan waktu rekam tiap run
disimpan bersama row-nya, dan daftar base URL yang terpakai dicatat di
`environment.fixture_base_urls` — jadi jejaknya auditable, bukan sekadar
angka tanpa asal-usul.

Konsekuensi kedua, yang baru ketahuan saat review: **checkpoint mengubah
makna "durasi benchmark"**. Field `elapsed_s` di tingkat dokumen hanya
mengukur satu pemanggilan `main()`. Kalau sebagian besar run diambil dari
checkpoint — persis yang terjadi setelah perangkat reboot — angka itu jauh
lebih kecil daripada durasi kerja sebenarnya, dan pembaca akan menyimpulkan
seluruh 480 run hanya memakan waktu itu.

Keputusan: field `elapsed_s` **dihapus**, bukan diperbaiki labelnya, karena
nama yang sama dengan makna berbeda akan terus menyesatkan. Digantikan blok
`timing` yang mempublikasikannya terpisah:

- `measured_arm_execution_s_total` — jumlah waktu eksekusi lengan yang
  terukur, dijumlahkan dari `elapsed_ms` setiap run. Ini durasi kerja yang
  sebenarnya.
- `measurement_window` — rentang rekam run pertama sampai run terakhir
  (wall-clock di perangkat).
- `execution_sessions` — run dipecah menjadi sesi berdasarkan jeda rekam
  yang melampaui ambang, sehingga restart perangkat terlihat sebagai fakta
  yang bisa diaudit ulang dari `runs[].recorded_at`, bukan sebagai klaim
  naratif.
- `harness_invocation` — durasi pemanggilan yang menulis dokumen, dengan
  cakupan dinyatakan eksplisit: kalau sebagian besar run diambil dari
  checkpoint, angka itu **tidak** mencakup eksekusi run tersebut.

Konsekuensi yang diakui: rentang pengukuran (wall-clock) lebih besar daripada
durasi kerja terukur, karena mengandung jeda antar-run dan jeda perangkat
mati. Selisih itu tidak dipoles — justru dipublikasikan sebagai dua angka
berbeda plus sesi yang menjelaskan dari mana selisih itu datang.

### 12. Run yang tidak bisa dievaluasi: "belum teruji", bukan "gagal"

TEXT.md:1427 meminta hasil menang, seri, kalah, **dan belum teruji** dipublikasikan
secara terpisah. Ada dua sumber run yang tidak bisa dinilai:

1. **Runtime failure** — harness tidak bisa mengeksekusi lengan (timeout,
   keluar-nonzero). Tidak ada respons yang pernah diamati.
2. **Lengan melaporkan error tanpa menghasilkan body maupun status** —
   misalnya chromium gagal start. Yang gagal adalah **eksekusi lengan**,
   bukan kemampuan engine.

Keduanya dikeluarkan dari **penyebut kapabilitas**: sumbu dinetralkan menjadi
`None` (makna "tidak ada yang diukur", konsisten dengan `byte_faithful` yang
sudah memakai `None` untuk "tidak ada body"), dan `primary_success` menjadi
`None`. Jumlahnya dipublikasikan terpisah sebagai `untested_runs`, baik per
sel, per lengan, maupun per perbandingan.

Konsekuensi: vonis perbandingan dihitung dari **tingkat sukses atas run yang
dievaluasi**, bukan jumlah absolut. Dengan jumlah run dievaluasi yang sama
(kondisi normal, yaitu tidak ada run yang belum teruji) urutan peringkat
tingkat sukses identik dengan jumlah absolut — jadi dataset yang bersih tidak
berubah vonisnya. Sebaliknya, sistemik yang menggantung pada satu lengan
**tidak bisa menang**: bila run yang dievaluasi sebuah lengan nol, vonisnya
`not_comparable`, bukan kemenangan.

Batas yang diakui: timeout 180 detik memberi ruang ~7x di atas run sah
terlambat (lengan UWAE pada `a07_challenge` ~21-26 s karena empat percobaan
berantai; cold start browser Botasaurus ~6-10 s). Timeout pada batas itu
menunjukkan hang, bukan sekadar lambat — dan **bukan** klaim bahwa lengan yang
timeout lambat "hampir berhasil". Laporan tetap menabulasi latensi yang
terukur.

## Probe: dua pièges API Botasaurus yang menentukan desain lengan

Kedua hal berikut ditemukan lewat probe empiris (bukan asumsi) dan harus
ditangani eksplisit di dalam skrip lengan:

1. **`Tab.evaluate` mengembalikan `None` untuk setiap ekspresi** yang tidak
   diawali `return`. Penyebabnya: ekspresi disisipkan ke body blok
   `(() => { ... })()`, sehingga ekspresi tanpa `return` dievaluasi menjadi
   `undefined`, lalu `json.loads("{}").get("x")` menghasilkan `None` — termasuk
   untuk `document.readyState`. Gejalanya menyesatkan: tampak seperti "nilai
   falsy tertelan", padahal itu kasus `undefined`.
2. **`raise_exception=False` menelan exception** dekorator dan mengembalikan
   `None`, sehingga kegagalan tidak bisa diamati dari luar. Semua exception
   karena itu ditangkap **di dalam task** dan dikembalikan sebagai bagian dari
   outcome.

## Results

Evidence: `docs/benchmark/engine-results-e16.json` — benchmark_id `e16-browser-arm-differential-001`, 120 run per sel, 4 skenario × 4 lengan = 480 run. Durasi kerja terukur **3.077.18 detik** (480 run); rentang pengukuran 5.948.58 detik wall-clock (2026-10-27T23:12:01.841453Z → 2026-10-28T00:51:10.420460Z) dalam 2 sesi eksekusi — jeda 1.597.90 detik antara sesi menandai perangkat mati di tengah benchmark. Durasi pemanggilan penulis dokumen **0.53 detik** — run yang dieksekusi pada pemanggilan itu: **0** (seluruh 480 run diambil dari checkpoint).

| Skenario | Kriteria | uwae-adaptive | uwae-browser-only | botasaurus-http | botasaurus-browser |
|---|---|---|---|---|---|
| `b01_small_get` | `body_acquired` | 30/30 | 30/30 | 30/30 | 30/30 |
| `b07_js_render` | `body_acquired` | 30/30 | 30/30 | 0/30 | 30/30 |
| `a11_invalid_html` | `signal_preserved` | 30/30 | 0/30 | 30/30 | 0/30 |
| `a07_challenge` | `signal_preserved` | 30/30 | 30/30 | 30/30 | 30/30 |

| Perbandingan | UWAE | Baseline | Belum teruji | Hasil |
|---|---|---|---|---|
| `b01_small_get` uwae-adaptive vs botasaurus-http | 30/30 | 30/30 | 0 | **tie** |
| `b01_small_get` uwae-adaptive vs botasaurus-browser | 30/30 | 30/30 | 0 | **tie** |
| `b01_small_get` uwae-browser-only vs botasaurus-browser | 30/30 | 30/30 | 0 | **tie** |
| `b07_js_render` uwae-adaptive vs botasaurus-http | 30/30 | 0/30 | 0 | **uwae** |
| `b07_js_render` uwae-adaptive vs botasaurus-browser | 30/30 | 30/30 | 0 | **tie** |
| `b07_js_render` uwae-browser-only vs botasaurus-browser | 30/30 | 30/30 | 0 | **tie** |
| `a11_invalid_html` uwae-adaptive vs botasaurus-http | 30/30 | 30/30 | 0 | **tie** |
| `a11_invalid_html` uwae-adaptive vs botasaurus-browser | 30/30 | 0/30 | 0 | **uwae** |
| `a11_invalid_html` uwae-browser-only vs botasaurus-browser | 0/30 | 0/30 | 0 | **tie** |
| `a07_challenge` uwae-adaptive vs botasaurus-http | 30/30 | 30/30 | 0 | **tie** |
| `a07_challenge` uwae-adaptive vs botasaurus-browser | 30/30 | 30/30 | 0 | **tie** |
| `a07_challenge` uwae-browser-only vs botasaurus-browser | 30/30 | 30/30 | 0 | **tie** |

Win/tie/loss: **2** UWAE, **10** seri, **0** baseline, **0** tidak sebanding (bukti tidak cukup memilih), **0** tanpa run yang dapat dinilai.

Belum teruji: **0** run (dari 480 run); runtime failure dari harness: **0**. Run yang tidak bisa dievaluasi dikeluarkan dari penyebut kapabilitas dan dipublikasikan terpisah sesuai TEXT.md:1427. Celah `js_rendering_browser_arm` yang dideklarasikan E14 tertutup: kedua implementasi menjalankan browser di device yang sama, dan lengan browser Botasaurus memperoleh konten hasil render JS sepenuhnya.

Rincian per skenario, path breakdown server, dan latensi ada di laporan `docs/benchmark/browser-arm-differential.md`.

## Consequences

### Positif

1. **Celah `js_rendering_browser_arm` tertutup** dengan bukti, bukan klaim.
2. **Gerbang §9 #3 dijawab**: browser automation berjalan di device ini untuk
   kedua implementasi.
3. **Biaya browser terukur apa adanya** — termasuk request sampingan dan
   cold start — sehingga "membuka browser" punya harga yang diketahui.
4. **Temuan closure sinyal terkomit** sebagai bukti: browser merekonstruksi
   byte korup jadi HTML valid dan reporting `access_granted`, sehingga sinyal
   `content_invalid` tertutup (pembuktian ulang temuan E4).

### Negatif / batasan

1. **Fixture sintetis.** Four skenario, satu origin, tanpa cookie, tanpa
   redirect, tanpa rate limit, tanpa TLS. Hanya gerbang JS, byte korup, dan
   interstitial challenge.
2. **Challenge fixture tidak interaktif.** `/challenge` mengembalikan 403 dengan
   body marker; ini belum challenge yang benar-benar solving, jadi
   "perbandingan terhadap challenge" hanya mencakup deteksi sinyal.
3. **Tidak ada klaim throughput.** Tiap run adalah satu job/subprocess penuh;
   ini perbandingan biaya per-target, bukan beban.
4. **Cold start mendominasi.** Mayoritas latensi lengan browser adalah start
   chromium, bukan render. Warm reuse akan mengubah angka drastis — dan itu
   **tidak** diukur di sini karena bukan jalur produksi.

### Tidak diklaim

- **Tidak diklaim UWAE mengungguli Botasaurus.** Perbandingan browser-vs-browser
  sengaja dibuat sedekat mungkin, dan hasilnya dilaporkan apa adanya.
- **Tidak diklaim selisih latency = selisih beban-manifest.**
- **Tidak ada data historis yang ditimpa.** Bukti E14 mendapat blok
  `correction_e16` yang terpisah; blok `correction` yang menunjuk E15 tetap
  utuh.

## Links

- Evidence: `docs/benchmark/engine-results-e16.json`
- Laporan: `docs/benchmark/browser-arm-differential.md`
- Harness: `src/universal_web_acquisition/benchmark/browser_diff_bench.py`
- Test: `tests/test_browser_diff_bench.py`
- ADR sebelumnya: ADR-014 (raw CDP), ADR-019 (cross-impl HTTP), ADR-020
  (session flow)
