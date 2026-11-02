# E16 — Browser-Arm Differential: UWAE vs Botasaurus

> **Dimensi browser, diukur lintas-implementasi pada device yang sama.**
>
> E14 mengukur alur HTTP; E15 mengukur alur sesi. Dimensi **browser**
> — tempat target benar-benar harus dirender — belum pernah diukur
> lintas-implementasi, dan E14 **mendeklarasikannya sendiri** sebagai skenario
> tak didukung. E16 menutup celah itu.

Angka di bawah DIHASILKAN dari `engine-results-e16.json` — jangan diedit manual.

| | |
|---|---|
| `benchmark_id` | `e16-browser-arm-differential-001` |
| Evidence | `docs/benchmark/engine-results-e16.json` |
| Decision record | [ADR-021](../architecture/decisions/ADR-021-browser-arm-differential.md) |
| Harness | `src/universal_web_acquisition/benchmark/browser_diff_bench.py` |
| n per sel | **30** (TEXT.md §6.3: minimal 30 pengulangan untuk skenario benchmark utama) |
| Skenario × lengan | 4 × 4 = 480 run |

Celah yang ditutup:

```json
{
  "scenario_id": "js_rendering_browser_arm",
  "reason": "Kedua arm di benchmark ini adalah arm HTTP. Rendering JavaScript butuh arm browser; ... keduanya belum diukur pada device ini, jadi tidak diklaim sebagai perbedaan engine.",
  "supported_by": []
}
```

---

## Ringkasan hasil

Kriteria primer setiap skenario, diterapkan identik ke keempat lengan. Seluruh angka berasal dari `engine-results-e16.json` (benchmark_id `e16-browser-arm-differential-001`).

| Skenario | Kriteria | uwae-adaptive | uwae-browser-only | botasaurus-http | botasaurus-browser |
|---|---|---|---|---|---|
| `b01_small_get` | `body_acquired` | 30/30 | 30/30 | 30/30 | 30/30 |
| `b07_js_render` | `body_acquired` | 30/30 | 30/30 | 0/30 | 30/30 |
| `a11_invalid_html` | `signal_preserved` | 30/30 | 0/30 | 30/30 | 0/30 |
| `a07_challenge` | `signal_preserved` | 30/30 | 30/30 | 30/30 | 30/30 |

Baris terakhir = total lintas skenario (kontak dengan jumlah run, bukan penjumlahan sel yang selalu berhasil).

| Total | Runs | uwae-adaptive | uwae-browser-only | botasaurus-http | botasaurus-browser |
|---|---|---|---|---|---|
| sukses primer | — | 120/120 | 90/120 | 90/120 | 90/120 |
| run dievaluasi | — | 120 | 120 | 120 | 120 |
| belum teruji | — | 0 | 0 | 0 | 0 |
| runtime failure | — | 0 | 0 | 0 | 0 |

**Tidak ada run yang belum teruji di seluruh 480 run** — jadi perbandingan ini berdiri di atas denominator penuh dan tidak dikaburkan oleh kegagalan eksekusi.

Rekap perbandingan (kriteria primer per skenario; `tie` = hasil identik pada run yang dievaluasi; angka `x/y` adalah sukses dari run yang dievaluasi):

| Skenario | Perbandingan | UWAE | Baseline | Belum teruji | Hasil |
|---|---|---|---|---|---|
| `b01_small_get` | uwae-adaptive vs botasaurus-http | 30/30 | 30/30 | 0 | **tie** |
| `b01_small_get` | uwae-adaptive vs botasaurus-browser | 30/30 | 30/30 | 0 | **tie** |
| `b01_small_get` | uwae-browser-only vs botasaurus-browser | 30/30 | 30/30 | 0 | **tie** |
| `b07_js_render` | uwae-adaptive vs botasaurus-http | 30/30 | 0/30 | 0 | **uwae** |
| `b07_js_render` | uwae-adaptive vs botasaurus-browser | 30/30 | 30/30 | 0 | **tie** |
| `b07_js_render` | uwae-browser-only vs botasaurus-browser | 30/30 | 30/30 | 0 | **tie** |
| `a11_invalid_html` | uwae-adaptive vs botasaurus-http | 30/30 | 30/30 | 0 | **tie** |
| `a11_invalid_html` | uwae-adaptive vs botasaurus-browser | 30/30 | 0/30 | 0 | **uwae** |
| `a11_invalid_html` | uwae-browser-only vs botasaurus-browser | 0/30 | 0/30 | 0 | **tie** |
| `a07_challenge` | uwae-adaptive vs botasaurus-http | 30/30 | 30/30 | 0 | **tie** |
| `a07_challenge` | uwae-adaptive vs botasaurus-browser | 30/30 | 30/30 | 0 | **tie** |
| `a07_challenge` | uwae-browser-only vs botasaurus-browser | 30/30 | 30/30 | 0 | **tie** |

Rekap win/tie/loss: **2** UWAE, **10** seri, **0** baseline, **0** tidak sebanding (bukti tidak cukup memilih), **0** tanpa run yang dapat dinilai.

Vonis dihitung pada DUA batas: tingkat sukses atas run yang dievaluasi, dan tingkat sukses atas seluruh attempt. Kalau keduanya memberi urutan yang sama, vonisnya pasti. Kalau urutannya BERBEDA, bukti yang ada tidak cukup untuk memilih — timeout pada satu lengan bisa berarti lengan itu lebih lambat ATAU hanya masalah eksekusi — jadi vonisnya `not_comparable`, bukan diberikan ke lengan mana pun. Pada dataset tanpa run yang belum teruji, kedua batas identik.

Interpretasi harness: E16 mengukur dimensi BROWSER lintas-implementasi — celah yang dideklarasikan sendiri oleh E14 sebagai skenario tak didukung. Kriteria diterapkan IDENTIK ke semua lengan dan diturunkan dari semantika protokol fixture, bukan dari output engine mana pun. Pembacaan yang jujur: selisih pada sumbu body_acquired menunjukkan KAPABILITAS; selisih pada byte_faithful menunjukkan FIDELITAS (browser merekonstruksi byte mentah); selisih pada signal_preserved menunjukkan apakah sinyal kegagalan tertutup. BUKAN klaim mengungguli Botasaurus — ini baseline yang dapat direproduksi, dan lengan botasaurus-browser diberi bentuk terkuat yang Botasaurus tawarkan. Run yang tidak bisa dievaluasi — timeout, atau lengan gagal start sehingga tidak ada respons yang diamati — DIHAPUS dari penyebut kapabilitas dan dipublikasikan terpisah sebagai belum-teruji; menghitungnya sebagai gagal akan menghukum lengan karena masalah eksekusi, bukan karena kemampuan engine.

---

## Tiga sumbu yang dipisah

Output browser adalah `document.documentElement.outerHTML` — doctype hilang,
newline tambahan. Body browser **tidak pernah** byte-identik dengan body
sumber. Karena itu harness tidak pernah memakai "body identik byte-per-byte"
sebagai kriteria primer; ia memakai **marker** yang diturunkan dari semantika
protokol fixture, dan menerapkannya **identik** ke semua lengan.

| Sumbu | Arti | Catatan |
|---|---|---|
| `body_acquired` | status sesuai **dan** marker wajib ada **dan** marker terlarang tidak ada | kapabilitas |
| `byte_faithful` | body identik byte-per-byte dengan body sumber | fidelitas; `None` bila lengan tidak punya body — "tidak ada yang diukur", bukan "gagal" |
| `signal_preserved` | sinyal kegagalan yang dideklarasikan skenario tetap terlihat | skenario failure saja |

### Sumbu sinyal menerima dua kanal

Rancangan pertama sempat salah: `signal_preserved` menuntut marker challenge
terlihat di **body**. Itu memihak satu pihak — UWAE tidak mengirim body pada
skenario challenge (diagnosis `challenge_present` → `needs_user`, tanpa
artifact), sehingga sumbu menilai `False` **padahal sinyal justru terlihat**
lewat kanal diagnosis. Botasaurus tidak punya lapisan diagnosis, jadi
kewalianya hanya body.

Kriteria yang dipakai: `signal_preserved = kanal BODY ATAU kanal DIAGNOSIS`.
Kanal yang dipakai dicatat di `signal_channel`, jadi perbedaan arsitektur
terekspos dan tidak disembunyikan di balik satu angka.

### Kriteria primer per skenario

| Skenario | Path | Kriteria primer | Alasan |
|---|---|---|---|
| `b01_small_get` | `/html` | `body_acquired` | HTML biasa tanpa JS — yang diukur adalah **biaya** |
| `b07_js_render` | `/js` | `body_acquired` | gerbang JS — hanya render browser yang menghasilkan konten target |
| `a11_invalid_html` | `/invalid-html` | `signal_preserved` | 200 dengan body rusak **bukan** keberhasilan |
| `a07_challenge` | `/challenge` | `signal_preserved` | yang diuji bukan pemecahan challenge, tapi apakah sinyalnya tertutup |

---

## Bukti sisi server

Fixture merekam request yang benar-benar diterima. Tabel di bawah menampilkan **path breakdown** (bukan hanya total) dari run pertama setiap sel — supaya efek samping Chromium terlihat, bukan tersembunyi di balik angka total.

| Skenario | Lengan | path breakdown (run pertama) | status | diagnosis | terminal |
|---|---|---|---|---|---|
| `b01_small_get` | uwae-adaptive | `/html`×1 | 200 | access_granted | succeeded |
| `b01_small_get` | uwae-browser-only | `/html`×1, `/favicon.ico`×1 | 200 | access_granted | succeeded |
| `b01_small_get` | botasaurus-http | `/html`×1 | 200 | — | — |
| `b01_small_get` | botasaurus-browser | `/html`×1, `/favicon.ico`×1 | 200 | — | — |
| `b07_js_render` | uwae-adaptive | `/js`×2, `/favicon.ico`×1 | 200 | access_granted | succeeded |
| `b07_js_render` | uwae-browser-only | `/js`×1, `/favicon.ico`×1 | 200 | access_granted | succeeded |
| `b07_js_render` | botasaurus-http | `/js`×1 | 200 | — | — |
| `b07_js_render` | botasaurus-browser | `/js`×1, `/favicon.ico`×1 | 200 | — | — |
| `a11_invalid_html` | uwae-adaptive | `/invalid-html`×4 | None | content_invalid | failed |
| `a11_invalid_html` | uwae-browser-only | `/invalid-html`×1, `/favicon.ico`×1 | 200 | access_granted | succeeded |
| `a11_invalid_html` | botasaurus-http | `/invalid-html`×1 | 200 | — | — |
| `a11_invalid_html` | botasaurus-browser | `/invalid-html`×1, `/favicon.ico`×1 | 200 | — | — |
| `a07_challenge` | uwae-adaptive | `/challenge`×4, `/favicon.ico`×3 | None | challenge_present | needs_user |
| `a07_challenge` | uwae-browser-only | `/challenge`×4, `/favicon.ico`×4 | None | challenge_present | needs_user |
| `a07_challenge` | botasaurus-http | `/challenge`×1 | 403 | — | — |
| `a07_challenge` | botasaurus-browser | `/challenge`×1, `/favicon.ico`×1 | 403 | — | — |

Yang terlihat eksplisit: lengan HTTP mengakses **satu** path skenario; lengan browser menambahkan request sampingan `/favicon.ico`; dan lengan `uwae-adaptive` pada `b07_js_render` serta kedua lengan UWAE pada `a07_challenge` mengakses path skenario **lebih dari sekali** karena kebijakan retry masing-masing engine. Ketiganya dibuktikan dari rekam server, bukan dari asumsi.

---

## Biaya request

Jumlah request yang benar-benar diterima fixture per run (median atau dari run pertama). Kolom `req/med` adalah median jumlah request terobservasi pada skenario tersebut.

| Skenario | Lengan | req/med | req run pertama |
|---|---|---|---|
| `b01_small_get` | uwae-adaptive | 1.0 | 1 |
| `b01_small_get` | uwae-browser-only | 1.0 | 2 |
| `b01_small_get` | botasaurus-http | 1.0 | 1 |
| `b01_small_get` | botasaurus-browser | 1.0 | 2 |
| `b07_js_render` | uwae-adaptive | 2.0 | 3 |
| `b07_js_render` | uwae-browser-only | 1.0 | 2 |
| `b07_js_render` | botasaurus-http | 1.0 | 1 |
| `b07_js_render` | botasaurus-browser | 1.0 | 2 |
| `a11_invalid_html` | uwae-adaptive | 4.0 | 4 |
| `a11_invalid_html` | uwae-browser-only | 1.0 | 2 |
| `a11_invalid_html` | botasaurus-http | 1.0 | 1 |
| `a11_invalid_html` | botasaurus-browser | 1.0 | 2 |
| `a07_challenge` | uwae-adaptive | 4.0 | 7 |
| `a07_challenge` | uwae-browser-only | 4.0 | 8 |
| `a07_challenge` | botasaurus-http | 1.0 | 1 |
| `a07_challenge` | botasaurus-browser | 1.0 | 2 |

Selisih `req` antara lengan HTTP dan lengan browser pada skenario yang sama adalah **biaya** — bukan keuntungan kapabilitas. Membuka browser membayar navigasi tambahan dan request sampingan; yang dibeli balik adalah kemampuan merender JavaScript dan melihat sinyal interstitial.

---

## Latensi

Median dan p95 per run, dalam milidetik. p95 **bermakna** di sini: n=30 per sel memenuhi TEXT.md §6.3 (minimal 30 pengulangan untuk skenario benchmark utama), jadi tidak perlu disclaimer seperti pada E14/E15 (n=5).

| Skenario | Lengan | median (ms) | p95 (ms) |
|---|---|---|---|
| `b01_small_get` | uwae-adaptive | 519 | 688 |
| `b01_small_get` | uwae-browser-only | 4.817 | 5.274 |
| `b01_small_get` | botasaurus-http | 59 | 90 |
| `b01_small_get` | botasaurus-browser | 6.546 | 7.176 |
| `b07_js_render` | uwae-adaptive | 5.966 | 6.848 |
| `b07_js_render` | uwae-browser-only | 5.470 | 6.383 |
| `b07_js_render` | botasaurus-http | 88 | 107 |
| `b07_js_render` | botasaurus-browser | 7.499 | 8.961 |
| `a11_invalid_html` | uwae-adaptive | 1.066 | 1.164 |
| `a11_invalid_html` | uwae-browser-only | 5.411 | 6.958 |
| `a11_invalid_html` | botasaurus-http | 85 | 108 |
| `a11_invalid_html` | botasaurus-browser | 7.650 | 9.131 |
| `a07_challenge` | uwae-adaptive | 19.887 | 21.371 |
| `a07_challenge` | uwae-browser-only | 30.282 | 32.983 |
| `a07_challenge` | botasaurus-http | 89 | 124 |
| `a07_challenge` | botasaurus-browser | 6.899 | 7.924 |

| Total lintas skenario | median (ms) | p95 (ms) |
|---|---|---|
| uwae-adaptive | 3.116 | 20.453 |
| uwae-browser-only | 5.470 | 31.734 |
| botasaurus-http | 83 | 109 |
| botasaurus-browser | 7.201 | 8.292 |

Cold start chromium mendominasi lengan browser: sebagian besar waktu itu adalah menyalakan browser, bukan merender. Warm reuse akan mengubah angka ini drastis — dan **tidak** diukur di sini karena bukan jalur produksi UWAE (`keep_alive=False`).

---

## Durasi eksekusi

Tiga angka durasi, masing-masing dengan cakupan berbeda. Semuanya dari `timing` di `engine-results-e16.json` — tidak ada satu pun yang hanya mengukur pemanggilan terakhir.

| Angka | Nilai | Cakupan |
|---|---|---|
| Durasi kerja terukur | **3.077.18 s** (480 run) | jumlah `elapsed_ms` seluruh run — durasi eksekusi lengan yang sebenarnya |
| Rentang pengukuran | **5.948.58 s** | wall-clock dari rekam run pertama sampai terakhir (2026-10-27T23:12:01.841453Z → 2026-10-28T00:51:10.420460Z); mencakup jeda antar-run dan jeda restart perangkat |
| Durasi pemanggilan penulis | 0.53 s | **hanya** invocation yang menulis dokumen ini: 0 run dieksekusi, 480 run diambil dari checkpoint |

Rentang pengukuran lebih besar daripada durasi kerja terukur karena mengandung waktu yang tidak diukur sebagai kerja lengan: jeda antar-run, dan jeda perangkat mati saat benchmark dihentikan. Perbedaan itu tidak disembunyikan — dipecah menjadi sesi eksekusi di bawah, dihitung dari rekam waktu tiap run dengan ambang jeda 60.00 s.

| Sesi | Run | Mulai (UTC) | Selesai (UTC) | Durasi (s) | Jeda sebelum (s) | Instance fixture |
|---|---|---|---|---|---|---|
| 1 | 418 | 2026-10-27T23:12:01.841453Z | 2026-10-28T00:17:35.826128Z | 3.934.00 | 0.00 | `http://127.0.0.1:43247` |
| 2 | 62 | 2026-10-28T00:44:13.773538Z | 2026-10-28T00:51:10.420460Z | 416.60 | 1.597.90 | `http://127.0.0.1:38651` |

Jeda 1.597.90 s sebelum sesi 2 adalah bukti perangkat mati di tengah benchmark — bukan jeda normal antar-run. Pemisahan sesi dihitung dari rekam waktu tiap run, jadi bisa diaudit ulang dari `scenarios[].arms[].runs[].recorded_at` di evidence, bukan dari klaim naratif.

Angka durasi pemanggilan penulis sengaja dipublikasikan terpisah karena cakupannya paling mudah disalahbaca: kalau sebagian besar run diambil dari checkpoint, durasi invocation itu **tidak** mencakup eksekusi run tersebut.

---

## Kondisi eksekusi

| | |
|---|---|
| Interpreter | satu interpreter untuk semua lengan (`/root/uwae-comparison-venv/bin/python`) |
| PYTHONPATH | identik untuk semua lengan (site-packages Botasaurus + `src/` repo) |
| Fixture server | `port=0` (OS memilih port bebas) — **2 instance** terpakai karena perangkat reboot di tengah run; isi yang dilayani identik (body sumber sama), daftar base URL ada di `environment.fixture_base_urls` |
| Isolasi | **satu subprocess per run** — state browser dan state server tidak bocor antar run |
| Cold start | dibayar penuh tiap run; `CDPBrowserAdapter(keep_alive=False)` (default produksi UWAE) dan `@browser` dengan `cache=False`, `reuse_driver=False` |

Kondisi identik **tidak hanya diklaim** lewat boolean `identical_conditions`:
dokumen hasil juga memuat `arm_configuration` — transport, kebijakan retry,
siklus hidup browser, sumber status HTTP, dan keberadaan lapisan diagnosis
untuk tiap lengan.

### Asimetri retry: perbedaan desain, bukan pilihan harness

| Lengan | Kebijakan retry | Batas attempt |
|---|---|---|
| `uwae-adaptive` | `RetryPolicy(max_retries=2, base_backoff_seconds=0.05)` — planner escalate ke browser selama `retry_attempt <= max_retries`, lalu `needs_user` | 4 |
| `uwae-browser-only` | idem | 4 |
| `botasaurus-http` | default Botasaurus (`max_retry` tidak disetel) — retry hanya bila task melempar exception | 1* |
| `botasaurus-browser` | idem | 1* |

\* Botasaurus **tidak punya** mekanisme yang bisa bereaksi pada sinyal yang
terdeteksi (mis. challenge), jadi anggaran retrynya tidak bisa terpakai di
skenario failure. Akibatnya jumlah attempt berbeda — dan itu terlihat langsung
dari path breakdown sisi server, bukan dari asumsi.

---

## Ground truth

Semua marker dan status ekspektasi diturunkan dari **semantika protokol fixture** —
body yang benar-benar dilayani server — bukan dari output engine mana pun.

| Skenario | Status | Marker wajib | Marker terlarang |
|---|---|---|---|
| `b01_small_get` | 200 | `fixture-ok` | — |
| `b07_js_render` | 200 | `rendered-by-js` | `please enable javascript` |
| `a11_invalid_html` | 200 | — (kriteria = sinyal) | — |
| `a07_challenge` | 403 | — (kriteria = sinyal) | `just a moment`, `checking your browser` |

---

## Temuan

**1. Gerbang JavaScript hanya bisa dilewati oleh lengan browser.** Pada `b07_js_render`, `botasaurus-http` (0/30) gagal sementara body mentahnya berisi marker terlarang `please enable javascript`, sedangkan `uwae-adaptive` (30/30) dan `botasaurus-browser` (30/30) memperoleh body target. Ini bukti bahwa dimensi browser menambah **kapabilitas**, bukan hanya biaya.

**2. Kedua lengan browser menutup sinyal `content_invalid`.** Pada `a11_invalid_html` (HTTP 200 dengan body korup), `uwae-adaptive` signal_preserved=30/30, false_success=0; `uwae-browser-only` signal_preserved=0/30, false_success=30; `botasaurus-http` signal_preserved=30/30, false_success=0; `botasaurus-browser` signal_preserved=0/30, false_success=30. Browser merekonstruksi byte korup menjadi HTML yang valid sehingga lapisan diagnosis tidak pernah melihat isinya. Ini mengulang temuan E4 dalam setting lintas-implementasi: men-render byte korup **kehilangan** sinyal, bukan memperbaikinya. Kanal diagnosis dipakai oleh `uwae-adaptive`; kanal body oleh `botasaurus-http`.

**3. Sinyal challenge terlihat, tapi lewat kanal berbeda.** Pada `a07_challenge`, `uwae-adaptive` signal_preserved=30/30 (kanal: diagnosis); `uwae-browser-only` signal_preserved=30/30 (kanal: diagnosis); `botasaurus-http` signal_preserved=30/30 (kanal: body); `botasaurus-browser` signal_preserved=30/30 (kanal: body). Perbedaan kanal ini adalah **perbedaan arsitektur**: UWAE melewati analisis body dan berhenti lewat diagnosis, Botasaurus hanya melihat body. Keduanya menemukan sinyalnya — tidak ada lengan yang menutupnya di skenario ini.

**4. Pada HTML biasa tanpa JS, HTTP menang telak.** `b01_small_get`: `botasaurus-http` 30/30 vs `uwae-adaptive` 30/30 dan `botasaurus-browser` 30/30. Perbedaan latensi pada skenario ini adalah harga membakar browser untuk hal yang bisa diambil HTTP biasa. Justru inilah alasan `uwae-adaptive` ada: ia HTTP dulu dan baru naik ke browser bila ada bukti yang meminta.

**5. `byte_faithful` membelah lengan secara struktural.** Lengan HTTP byte-faithful (body asli), lengan browser tidak pernah (`document.documentElement.outerHTML` membuang doctype dan menambah newline). Contoh: `b01_small_get` `uwae-adaptive` 30/30; `b01_small_get` `uwae-browser-only` 0/30; `b01_small_get` `botasaurus-http` 30/30; `b01_small_get` `botasaurus-browser` 0/30; `b07_js_render` `uwae-adaptive` 0/30; `b07_js_render` `uwae-browser-only` 0/30; `b07_js_render` `botasaurus-http` 30/30; `b07_js_render` `botasaurus-browser` 0/30; `a11_invalid_html` `uwae-browser-only` 0/30; `a11_invalid_html` `botasaurus-http` 30/30; `a11_invalid_html` `botasaurus-browser` 0/30; `a07_challenge` `botasaurus-http` 30/30; `a07_challenge` `botasaurus-browser` 0/30. Inilah alasan byte-for-byte **tidak pernah** dipakai sebagai kriteria primer — memakainya akan menghukum lengan browser di setiap skenario, termasuk yang seharusnya ia menang.

**6. Tidak ada run yang belum teruji di seluruh 480 run.** Semua run dievaluasi, jadi tidak ada yang perlu dikualifikasi dan perbandingan di atas berdiri di atas denominator penuh. Ketika lengan gagal di skenario lain, ia gagal pada kapabilitas (body tidak diperoleh, sinyal tertutup), bukan karena harness gagal menjalankan engine — kegagalan di sini adalah **data**, bukan noise.

---

## Batasan

1. **Fixture sintetis.** Empat skenario, satu origin, tanpa cookie, redirect,
   rate limit, atau TLS.
2. **Challenge fixture tidak interaktif.** `/challenge` mengembalikan 403 dengan
   body marker — belum challenge yang benar-benar solving, jadi
   "perbandingan terhadap challenge" hanya mencakup **deteksi sinyal**.
3. **Tidak ada klaim throughput.** Tiap run adalah satu job/subprocess penuh;
   ini perbandingan biaya per-target, bukan beban.
4. **Cold start mendominasi.** Mayoritas latensi lengan browser adalah start
   chromium, bukan render. Warm reuse akan mengubah angka drastis — dan itu
   **tidak** diukur di sini karena bukan jalur produksi.

---

## Yang TIDAK diklaim

- **Tidak diklaim UWAE mengungguli Botasaurus.** Perbandingan browser-vs-browser
  sengaja dibuat sedekat mungkin (transport sama, kriteria sama, status dibaca
  lewat mekanisme yang sama), dan hasilnya dilaporkan apa adanya — menang, seri,
  kalah, atau tidak sebanding.
- **Tidak diklaim selisih latensi = selisih beban-manifest.**
- **Tidak ada data historis yang ditimpa.** Bukti E14 mendapat blok
  `correction_e16` yang **terpisah**; blok `correction` yang menunjuk E15 tetap
  utuh (preseden ADR-018/ADR-019).

---

## Reproduksi

```bash
PYTHONPATH=src python -u -m universal_web_acquisition.benchmark.browser_diff_bench
```

Hasil ditulis ke `docs/benchmark/engine-results-e16.json`.
