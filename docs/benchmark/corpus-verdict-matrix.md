# Matriks vonis korpus UWAE vs Botasaurus (E17)

Satu artefak yang menggabungkan vonis seluruh benchmark lintas-implementasi: menang, seri, kalah, dan **belum teruji** dipublikasikan terpisah (TEXT.md:1427, Tahap G; gerbang TEXT.md §9 #7).

Evidence: `docs/benchmark/engine-results-e17.json` — benchmark_id `e17-corpus-verdict-matrix-001`. Matriks ini **tidak menjalankan benchmark**: ia merangkum evidence yang sudah dipublikasikan.

## Ringkasan korpus

| Vonis | Jumlah |
|---|---|
| UWAE menang | **13** |
| Seri | **28** |
| Baseline menang | **0** |
| Tidak sebanding (bukti tidak cukup memilih) | **0** |
| Tanpa run yang dapat dinilai | **0** |
| Run belum teruji (total) | **0** |

Jumlah di atas adalah **jumlah instansi perbandingan, bukan jumlah skenario unik**. Skenario yang sama bisa diukur di beberapa slot dengan lengan dan kriteria berbeda, jadi angkanya tidak boleh dibaca sebagai jumlah skenario.

**Tidak ada klaim bahwa UWAE mengungguli Botasaurus secara keseluruhan.** Yang diukur di sini adalah DUA hal yang tidak boleh dicampur: kemampuan (vonis per perbandingan) dan cakupan (celah yang dideklarasikan lalu ditutup).

## Vonis per dimensi

| Dimensi | UWAE | Seri | Baseline | Tidak sebanding | Tanpa run | Belum teruji |
|---|---|---|---|---|---|---|
| `browser-arm` | 2 | 10 | 0 | 0 | 0 | 0 |
| `http-transport` | 7 | 6 | 0 | 0 | 0 | 0 |
| `session-flow` | 4 | 5 | 0 | 0 | 0 | 0 |
| `http-post` | 0 | 7 | 0 | 0 | 0 | 0 |

## Vonis per slot

### E14 — `engine-results-e14.json` (dimensi `http-transport`)

**Status: superseded oleh E18.** Slot ini mengukur skenario dan dimensi yang sama dengan n lebih kecil, jadi TIDAK ikut dihitung pada ringkasan korpus. Evidence lamanya tetap utuh dan tetap dipublikasikan di sini sebagai rekaman historis.

Skema `e14_like`; vonis diturunkan di sini. 13 perbandingan: **7** UWAE, **6** seri, **0** baseline, 0 tidak sebanding, 0 tanpa run yang dapat dinilai.

| Skenario | Kriteria | UWAE | Baseline | Vonis |
|---|---|---|---|---|
| `b01_small_get` | `acquisition` | 5/5 | 5/5 | tie |
| `b01_large_get` | `acquisition` | 5/5 | 5/5 | tie |
| `b04_redirect` | `acquisition` | 5/5 | 5/5 | tie |
| `b06_gzip` | `acquisition` | 5/5 | 5/5 | tie |
| `b06_brotli` | `acquisition` | 5/5 | 5/5 | tie |
| `b07_js_render` | `diagnosis` | 5/5 | 0/5 | **uwae** |
| `e02_not_found` | `diagnosis` | 5/5 | 0/5 | **uwae** |
| `a04_login` | `diagnosis` | 5/5 | 0/5 | **uwae** |
| `a06_rate_limited` | `diagnosis` | 5/5 | 0/5 | **uwae** |
| `a07_challenge` | `diagnosis` | 5/5 | 0/5 | **uwae** |
| `a07_denied` | `diagnosis` | 5/5 | 0/5 | **uwae** |
| `a11_invalid_html` | `diagnosis` | 5/5 | 0/5 | **uwae** |
| `a09_large_download` | `acquisition` | 5/5 | 5/5 | tie |

### E15 — `engine-results-e15.json` (dimensi `session-flow`)

**Status: superseded oleh E19.** Slot ini mengukur skenario dan dimensi yang sama dengan n lebih kecil, jadi TIDAK ikut dihitung pada ringkasan korpus. Evidence lamanya tetap utuh dan tetap dipublikasikan di sini sebagai rekaman historis.

Skema `e15_like`; vonis diturunkan di sini. 9 perbandingan: **4** UWAE, **5** seri, **0** baseline, 0 tidak sebanding, 0 tanpa run yang dapat dinilai.

| Skenario | Kriteria | UWAE | Baseline | Vonis |
|---|---|---|---|---|
| `session_valid` | `content_acquired` | 5/5 | 5/5 | tie |
| `session_valid` | `content_acquired` | 5/5 | 5/5 | tie |
| `session_valid` | `content_acquired` | 5/5 | 5/5 | tie |
| `session_required` | `content_acquired` | 5/5 | 0/5 | **uwae** |
| `session_required` | `content_acquired` | 5/5 | 5/5 | tie |
| `session_required` | `content_acquired` | 5/5 | 0/5 | **uwae** |
| `session_expired` | `content_acquired` | 5/5 | 0/5 | **uwae** |
| `session_expired` | `content_acquired` | 5/5 | 5/5 | tie |
| `session_expired` | `content_acquired` | 5/5 | 0/5 | **uwae** |

### E16 — `engine-results-e16.json` (dimensi `browser-arm`)

Skema `e16_like`; vonis eksplisit di evidence. 12 perbandingan: **2** UWAE, **10** seri, **0** baseline, 0 tidak sebanding, 0 tanpa run yang dapat dinilai.

| Skenario | Kriteria | UWAE | Baseline | Vonis |
|---|---|---|---|---|
| `b01_small_get` | `body_acquired` | 30/30 | 30/30 | tie |
| `b01_small_get` | `body_acquired` | 30/30 | 30/30 | tie |
| `b01_small_get` | `body_acquired` | 30/30 | 30/30 | tie |
| `b07_js_render` | `body_acquired` | 30/30 | 0/30 | **uwae** |
| `b07_js_render` | `body_acquired` | 30/30 | 30/30 | tie |
| `b07_js_render` | `body_acquired` | 30/30 | 30/30 | tie |
| `a11_invalid_html` | `signal_preserved` | 30/30 | 30/30 | tie |
| `a11_invalid_html` | `signal_preserved` | 30/30 | 0/30 | **uwae** |
| `a11_invalid_html` | `signal_preserved` | 0/30 | 0/30 | tie |
| `a07_challenge` | `signal_preserved` | 30/30 | 30/30 | tie |
| `a07_challenge` | `signal_preserved` | 30/30 | 30/30 | tie |
| `a07_challenge` | `signal_preserved` | 30/30 | 30/30 | tie |

### E18 — `engine-results-e18.json` (dimensi `http-transport`)

Skema `e14_like`; vonis diturunkan di sini. 13 perbandingan: **7** UWAE, **6** seri, **0** baseline, 0 tidak sebanding, 0 tanpa run yang dapat dinilai.

| Skenario | Kriteria | UWAE | Baseline | Vonis |
|---|---|---|---|---|
| `b01_small_get` | `acquisition` | 30/30 | 30/30 | tie |
| `b01_large_get` | `acquisition` | 30/30 | 30/30 | tie |
| `b04_redirect` | `acquisition` | 30/30 | 30/30 | tie |
| `b06_gzip` | `acquisition` | 30/30 | 30/30 | tie |
| `b06_brotli` | `acquisition` | 30/30 | 30/30 | tie |
| `b07_js_render` | `diagnosis` | 30/30 | 0/30 | **uwae** |
| `e02_not_found` | `diagnosis` | 30/30 | 0/30 | **uwae** |
| `a04_login` | `diagnosis` | 30/30 | 0/30 | **uwae** |
| `a06_rate_limited` | `diagnosis` | 30/30 | 0/30 | **uwae** |
| `a07_challenge` | `diagnosis` | 30/30 | 0/30 | **uwae** |
| `a07_denied` | `diagnosis` | 30/30 | 0/30 | **uwae** |
| `a11_invalid_html` | `diagnosis` | 30/30 | 0/30 | **uwae** |
| `a09_large_download` | `acquisition` | 30/30 | 30/30 | tie |

### E19 — `engine-results-e19.json` (dimensi `session-flow`)

Skema `e15_like`; vonis diturunkan di sini. 9 perbandingan: **4** UWAE, **5** seri, **0** baseline, 0 tidak sebanding, 0 tanpa run yang dapat dinilai.

| Skenario | Kriteria | UWAE | Baseline | Vonis |
|---|---|---|---|---|
| `session_valid` | `content_acquired` | 30/30 | 30/30 | tie |
| `session_valid` | `content_acquired` | 30/30 | 30/30 | tie |
| `session_valid` | `content_acquired` | 30/30 | 30/30 | tie |
| `session_required` | `content_acquired` | 30/30 | 0/30 | **uwae** |
| `session_required` | `content_acquired` | 30/30 | 30/30 | tie |
| `session_required` | `content_acquired` | 30/30 | 0/30 | **uwae** |
| `session_expired` | `content_acquired` | 30/30 | 0/30 | **uwae** |
| `session_expired` | `content_acquired` | 30/30 | 30/30 | tie |
| `session_expired` | `content_acquired` | 30/30 | 0/30 | **uwae** |

### E20 — `engine-results-e20.json` (dimensi `http-post`)

Skema `e14_like`; vonis diturunkan di sini. 4 perbandingan: **0** UWAE, **4** seri, **0** baseline, 0 tidak sebanding, 0 tanpa run yang dapat dinilai.

| Skenario | Kriteria | UWAE | Baseline | Vonis |
|---|---|---|---|---|
| `p01_post_form` | `acquisition` | 30/30 | 30/30 | tie |
| `p02_post_json` | `acquisition` | 30/30 | 30/30 | tie |
| `p03_post_empty` | `acquisition` | 30/30 | 30/30 | tie |
| `p04_post_large_body` | `acquisition` | 30/30 | 30/30 | tie |

### E21 — `engine-results-e21.json` (dimensi `http-post`)

Skema `e14_like`; vonis diturunkan di sini. 2 perbandingan: **0** UWAE, **2** seri, **0** baseline, 0 tidak sebanding, 0 tanpa run yang dapat dinilai.

| Skenario | Kriteria | UWAE | Baseline | Vonis |
|---|---|---|---|---|
| `p05_post_multipart` | `acquisition` | 30/30 | 30/30 | tie |
| `p06_post_redirect307` | `acquisition` | 30/30 | 30/30 | tie |

### E22 — `engine-results-e22.json` (dimensi `http-post`)

Skema `e16_like`; vonis eksplisit di evidence. 1 perbandingan: **0** UWAE, **1** seri, **0** baseline, 0 tidak sebanding, 0 tanpa run yang dapat dinilai.

| Skenario | Kriteria | UWAE | Baseline | Vonis |
|---|---|---|---|---|
| `p07_post_browser_form` | `acquisition` | 30/30 | 30/30 | tie |

## Celah yang dideklarasikan

Cakupan adalah hal yang berbeda dari kemampuan. Celah yang dideklarasikan sebuah slot dicatat beserta statusnya; closure menunjuk slot yang benar-benar mengukurnya, bukan klaim naratif.

| Celah | Dideklarasikan di | Status | Ditutup oleh | Bukti closure |
|---|---|---|---|---|
| `a05_protected` | E18 | **closed** | E19 | `docs/benchmark/engine-results-e19.json` |
| `js_rendering_browser_arm` | E18 | **closed** | E16 | `docs/benchmark/engine-results-e16.json` |
| `post_multipart_form_data` | E20 | **closed** | E21 | `docs/benchmark/engine-results-e21.json` |
| `post_redirect_307_preserves_method` | E20 | **closed** | E21 | `docs/benchmark/engine-results-e21.json` |
| `post_browser_arm` | E20 | **closed** | E22 | `docs/benchmark/engine-results-e22.json` |
| `post_browser_multipart_upload` | E22 | **open** | — | — |

Celah: **6** dideklarasikan, **5** ditutup, **1** masih terbuka.

## Aturan vonis

Vonis dihitung pada DUA batas: tingkat sukses atas run yang dievaluasi dan tingkat sukses atas seluruh attempt. Kalau kedua batas memberi urutan sama, vonisnya pasti (uwae / baseline / tie). Kalau berbeda, bukti tidak cukup memilih -> not_comparable. Kalau salah satu sisi tidak punya run yang bisa dinilai -> no_evaluable_runs. Run yang tidak bisa dinilai dikeluarkan dari penyebut kapabilitas dan dipublikasikan terpisah sebagai untested_runs.

## Batasan

- **Fixture sintetis, satu origin.** Semua slot memakai fixture lokal; tidak ada TLS, redirect, rate limit, atau cookie lintas origin pada dimensi HTTP.
- **Jumlah instans, bukan skenario unik.** Lengan dan kriteria berbeda antar slot, jadi jumlah slot tidak boleh dijumlahkan menjadi klaim kapabilitas tunggal.
- **Basis run yang dievaluasi berbeda antar slot.** Evidence http-transport hanya memuat agregat per sel, evidence session-flow memuat run mentah, evidence browser-arm memuat vonis eksplisit; `evaluated_basis` pada setiap perbandingan menyatakan mana yang dipakai.
- **Slot tersuspen tidak ikut dihitung.** Backfill §6.3 (ADR-023) menggantikan slot n=5 dengan slot n=30 pada dimensi yang sama. Slot lama tetap dipublikasikan sebagai rekaman historis, tapi vonisnya tidak masuk hitungan — hanya slot aktif yang dihitung.
- **Tidak ada data historis yang ditimpa.** Matriks korpus menambah artefak baru; evidence slot lama tetap utuh, dan digantikan lewat deklarasi `supersedes` di dalam file evidence, bukan lewat penulisan ulang.

