# ADR-025: Dukungan HTTP POST end-to-end + slot E20 differential benchmark

## Status
Accepted (2026-10-30 — evidence: engine-results-e20.json, engine-results-e17.json regenerated)

## Konteks
Matriks kompetitif (TEXT.md:1427) mencatat Botasaurus `Verified` pada baris **HTTP GET/POST requests**, sedangkan UWAE sebelum perubahan ini hanya mengimplementasikan GET/HEAD/Range. Jalur POST tidak ada sama sekali di adapter, `RequestSpec` punya field `method` tapi tidak pernah dipakai, dan `Job` tidak punya cara menyatakan method maupun body. Ini satu-satunya **celah paritas kompetitif nyata** di seluruh matriks: 0 dari 29 baris "Not yet verified" punya Botasaurus `Verified`, sementara baris yang Botasaurus `Verified` (POST) tersembunyi di dalam baris yang UWAE `Measured (cross-impl)` karena vocabulary status tidak bisa mengekspresikan "sebagian ada".

TEXT.md §9 #3 mensyaratkan: "Di skenario mana mesin baru mengungguli baseline, sama, atau justru gagal?" — pengukuran POST adalah salah satu jawaban.

## Keputusan
1. **Kontrak transport** (`RequestSpec`, `Job`) dibuat load-bearing: method/body/header dinormalisasi di satu tempat, diserialisasi ke SQLite, dan diteruskan ke adapter.
2. **Adapter HTTP** (`CurlCffiAdapter`, `HttpxAdapter`, `RequestsAdapter`) mengekspos `fetch(method, body, headers)` keyword-only dengan default `GET` — call site lama (GET-only) tidak tersentuh.
3. **Cache** bypass non-GET sepenuhnya (kunci cache adalah URL saja, jadi POST ke URL yang sama dengan GET yang ter-cache akan disajikan dengan respons GET — itu jawaban yang salah).
4. **Resume path** (HEAD probe + chunked Range) ditolak untuk non-GET: mengulang POST per chunk akan mengirim payload berulang ke server.
5. **Fixture POST** (`fixture_post.py`) dibuat BARU — `fixture_server.py` milik user tidak disentuh. Fixture protokol POST menvalidasi method, Content-Type, header wajib, dan body; respons sukses adalah body KONSTAN per skenario (ground truth milik protokol, bukan echo).
6. **Harness E20** (`post_diff_bench.py`) baru dijalankan n=30, identik protokol fairness E18: target identik, expected output identik, device conditions identik, run counts identik, success criteria identik.
7. **Corpus matrix** memperoleh dimensi baru `http-post` (slot E20) — E18 `http-transport` tetap aktif, bukan digantikan.

## Bukti
- `docs/benchmark/engine-results-e20.json` — E20: 4 skenario (form, JSON, empty, large-body) × 30 runs = 120 run per arm. **120/120 primary success** kedua arm; **120/120 server-side observations** exact POST match (method=POST, body SHA-256 cocok, Content-Type cocok, header protokol cocok). 0 `content_type_mismatch`.
- `docs/benchmark/engine-results-e17.json` + `corpus-verdict-matrix.md` — dimensi `http-post` ditambah: 4 ties, 0 UWAE wins, 0 baseline wins. Total korpus: 13 UWAE wins, 25 ties, 0 baseline wins.
- `docs/benchmark/competitive-matrix.md` — baris `HTTP GET/POST requests` diperbarui merujuk E20.
- `tests/test_post_support.py` — 20 passed: kontrak, persistensi (inkl. migrasi DB lama), wire per adapter dibuktikan server-side, cache isolation, worker end-to-end POST, resume guard, CLI flags.

## Apa yang TIDAK diklaim
- **Tidak diklaim UWAE mengungguli Botasaurus secara keseluruhan.** E20 adalah pengukuran baseline lintas-implementasi — selisih latency terukur (Botasaurus ~30–80 ms, UWAE ~180–250 ms) dilaporkan apa adanya; perbedaan ini mencerminkan overhead framework UWAE (ACP, classifier, planner, artifact storage) vs Botasaurus decorator yang langsung memanggil `session.post`.
- **POST multipart/form-data** tidak diukur (fixture hanya form-urlencoded, JSON, empty, octet-stream).
- **Redirect 307/308 preserve method** tidak diukur (fixture POST tidak punya route redirect).
- **POST pada arm browser** tidak diukur (slot ini arm HTTP murni).

## Positif
- Celah paritas kompetitif **tertutup**: baris matriks yang Botasaurus `Verified` sekarang punya bukti UWAE `Measured (cross-impl)` pada n=30.
- Implementasi POST benar-benar dieksekusi (bukan sekadar ada di kontrak), dibuktikan dari sisi server.
- Jalur GET yang sudah terukur E18/E19 **tidak tersentuh** — backward compatibility terjaga.
- Migrasi DB idempotent: database lama tanpa kolom `request_spec` dibaca sebagai GET biasa, tidak rusak.

## Negatif-batasan
- UWAE POST latency 3–6× Botasaurus (overhead framework). Ini pengukuran baseline, bukan regresi — Botasaurus adalah decorator ringan, UWAE adalah engine penuh dengan ACP.
- Fixture POST baru (`fixture_post.py`) berarti dua fixture harus dipelihara berdampingan (GET/umum vs POST/protokol). Disengaja dipisah agar `fixture_server.py` milik user tidak disentuh.
- Harness E20 menambah satu slot evidence yang harus di-regenerate corpus matrix setiap kali E20 dijalankan ulang.

## Tidak diklaim
- Tidak ada klaim "UWAE lebih cepat dari Botasaurus pada POST".
- Tidak ada klaim kelengkapan POST (multipart, redirect preserve method, browser arm) — dinyatakan terbuka di `UNSUPPORTED_SCENARIOS`.

## Link
- Evidence E20: `docs/benchmark/engine-results-e20.json`
- Corpus E17 (updated): `docs/benchmark/engine-results-e17.json`, `docs/benchmark/corpus-verdict-matrix.md`
- Competitive matrix: `docs/benchmark/competitive-matrix.md`
- Test: `tests/test_post_support.py`
- Fixture: `src/universal_web_acquisition/benchmark/fixture_post.py`
- Harness: `src/universal_web_acquisition/benchmark/post_diff_bench.py`
- Core changes: `src/universal_web_acquisition/http_transport/contracts.py`, `src/universal_web_acquisition/core/job_model.py`, `src/universal_web_acquisition/http_transport/adapters.py`, `src/universal_web_acquisition/http_transport/cache.py`, `src/universal_web_acquisition/core/job_worker.py`, `src/universal_web_acquisition/http_transport/resume.py`, `src/universal_web_acquisition/core/job_repository.py`, `src/universal_web_acquisition/cli/main.py`