# E4 — Adaptive Scheduling: HTTP-first vs Browser-first vs Adaptif

Benchmark biaya & cakupan strategi pada engine dan fixture yang sama.
Angka di bawah DIHASILKAN dari `engine-results-e12.json` — jangan diedit manual.

## Cara membaca

- **http_only** — hanya transport HTTP; browser runtime tidak tersedia.
- **browser_first** — browser runtime dicoba lebih dulu untuk setiap URL.
- **adaptive** — default engine: HTTP dulu, eskalasi ke browser hanya bila bukti memintanya.
- Status akhir job: `succeeded` / `failed` / `needs_user`. `needs_user` adalah hasil yang benar
  untuk challenge yang tidak dapat diselesaikan otomatis (ACP §2.2) — bukan kegagalan diam-diam.
- `browser_used` menunjukkan apakah lengan menyentuh browser runtime (biaya chromium ~
191368 kB RSS, cold start 5431.6 ms).

## Cakupan & fidelity diagnosis (per skenario)

| Skenario | Lengan | Status | State | Attempt (median) | Elapsed ms (median) | Browser | Retry-After dihormati | Sesuai ground truth |
|---|---|---|---|---|---|---|---|---|
| `b01_small_get` | http_only | 30× succeeded | access_granted | 1.0 | 255.33 | tidak | tidak | 100% |
| `b07_js_render` | http_only | 30× failed | javascript_required | 1.0 | 258.19 | tidak | tidak | 100% |
| `e02_not_found` | http_only | 30× failed | content_invalid | 4.0 | 783.24 | tidak | tidak | 100% |
| `a07_challenge` | http_only | 30× needs_user | challenge_present | 1.0 | 215.12 | tidak | tidak | 100% |
| `a11_invalid_html` | http_only | 1× failed | content_invalid | 4 | 737.11 | tidak | tidak | 100% |
| `a06_rate_limited` | http_only | 1× failed | rate_limited | 4 | 3771.54 | tidak | ya | 100% |
| `a04_login` | http_only | 1× failed | auth_required | 4 | 979.33 | tidak | tidak | 100% |
| `b01_small_get` | browser_first | 30× succeeded | access_granted | 1.0 | 534.42 | ya | tidak | 100% |
| `b07_js_render` | browser_first | 30× succeeded | access_granted | 1.0 | 550.37 | ya | tidak | 100% |
| `e02_not_found` | browser_first | 30× failed | content_invalid | 4.0 | 2028.43 | ya | tidak | 100% |
| `a07_challenge` | browser_first | 30× needs_user | challenge_present | 4.0 | 1951.03 | ya | tidak | 100% |
| `a11_invalid_html` | browser_first | 1× succeeded | access_granted | 1 | 471.36 | ya | tidak | 100% |
| `a06_rate_limited` | browser_first | 1× failed | rate_limited | 4 | 2039.67 | ya | tidak | 100% |
| `a04_login` | browser_first | 1× failed | auth_required | 4 | 1954.13 | ya | tidak | 100% |
| `b01_small_get` | adaptive | 30× succeeded | access_granted | 1.0 | 212.61 | tidak | tidak | 100% |
| `b07_js_render` | adaptive | 30× succeeded | access_granted | 2.0 | 720.06 | ya | tidak | 100% |
| `e02_not_found` | adaptive | 30× failed | content_invalid | 4.0 | 800.98 | tidak | tidak | 100% |
| `a07_challenge` | adaptive | 30× needs_user | challenge_present | 4.0 | 1521.26 | ya | tidak | 100% |
| `a11_invalid_html` | adaptive | 1× failed | content_invalid | 4 | 831.51 | tidak | tidak | 100% |
| `a06_rate_limited` | adaptive | 1× failed | rate_limited | 4 | 3691.35 | tidak | ya | 100% |
| `a04_login` | adaptive | 1× failed | auth_required | 4 | 779.78 | tidak | tidak | 100% |

## Biaya cold start browser (satu akuisisi, chromium baru)

- elapsed: **5431.6 ms**
- RSS chromium: **191368 kB**
- chromium baru untuk satu akuisisi (keep_alive=False) — biaya eskalasi one-shot pada jalur produksi `uwae acquire --browser`

## Metodologi

- pengulangan: 30 run per (lengan, skenario) untuk skenario berulang;
  skenario fidelity diagnosis dijalankan sekali per lengan (ada jeda Retry-After dari server).
- fixture lokal deterministik (`benchmark/fixture_server.py`) — ground truth berasal dari
  semantika protokol fixture, bukan dari output classifier.
- setiap lengan memakai JobWorker + registry + planner + artifact store yang sama;
  yang dibedakan hanya transport awal (`JobWorker(initial_transport=...)`).
- peak memory = `tracemalloc` (Python); RSS chromium dibaca dari `/proc` setelah render.

## Batasan yang diketahui

- Lengan browser memakai chromium persisten (cold start diukur terpisah) agar statistik
  berulang tidak didominasi biaya peluncuran proses.
- Perbandingan ini internal UWAE — tidak ada klaim lintas-implementasi di sini.
  Perbandingan lintas-implementasi yang terukur ada di `engine-results-e14.json`
  (E14) dan ADR-019; baseline Botasaurus terbukti berjalan normal di environment ini.
