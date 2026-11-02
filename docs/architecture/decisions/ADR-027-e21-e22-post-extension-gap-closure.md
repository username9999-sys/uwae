# ADR-027: Penutupan celah POST E20 via slot E21 (HTTP ekstensi) dan E22 (browser form POST)

## Status
Accepted (2026-10-31 — evidence: engine-results-e21.json, engine-results-e22.json, engine-results-e17.json regenerated)

## Konteks
E20 (ADR-025) mengukur POST dasar (form, JSON, empty, large-body) dan mendeklarasikan tiga celah terbuka: `post_multipart_form_data`, `post_redirect_307_preserves_method`, dan `post_browser_arm`. Korpus E17 sebelumnya: 5 celah dideklarasikan, 2 tertutup, **3 terbuka** — ketiganya dari E20.

## Keputusan
Dua slot baru, keduanya n=30 dengan protokol fairness identik E20/E18 (target, expected output, device conditions, run counts, success criteria sama untuk kedua arm):

1. **E21** (`post_ext_diff_bench.py`, dimensi `http-post`) — arm HTTP saja:
   - `p05_post_multipart`: body multipart dibandingkan **byte-for-byte** terhadap konstanta `MULTIPART_BODY` (boundary `----uwae-post-fixture-boundary-7d1a` ikut diuji). Arm yang membangun multipart dengan boundary acak akan gagal — itu memang yang diukur.
   - `p06_post_redirect307`: ground truth = respons AKHIR (200 + `REDIRECT_OK_BODY`); observasi server membuktikan dua hop (POST `/post/redirect307` → 307, lalu POST `/post/redirect-target` → 200 ok). Arm yang mengubah POST menjadi GET setelah 307 akan menerima 405.
2. **E22** (`post_browser_diff_bench.py`, dimensi `http-post`) — arm browser (chromium headless, port CDP 9384/9385):
   - `p07_post_browser_form`: browser membuka GET `/post/form-page`, lalu submit form via JS yang **body-nya identik untuk kedua arm** ke `/post/form-page-target`. Ground truth `FORM_OK_BODY`. Browser tidak bisa mengirim header kustom, jadi protokol target longgar (method + body saja).

Kedua slot didaftarkan di `SLOT_DIMENSIONS` sebagai `http-post` (bukan dimensi baru — ekstensi dari E20) dan closure didaftarkan di `DECLARED_GAP_CLOSURES`.

## Hasil (terukur, bukan klaim)

| Slot | Skenario | UWAE | Botasaurus | Vonis |
|---|---|---|---|---|
| E21 | p05_post_multipart | 30/30 | 30/30 | tie |
| E21 | p06_post_redirect307 | 30/30 | 30/30 | tie |
| E22 | p07_post_browser_form | 30/30 | 30/30 | tie |

Bukti sisi server E21: 60× observasi 307 pada `/post/redirect307` dan 60× observasi 200 `ok` pada target — artinya method+body POST benar-benar dipertahankan setelah redirect oleh kedua arm. E22: 30 GET halaman + 30 POST target `ok` per arm.

**Korpus E17 setelah regenerasi:** 13 UWAE wins / **28 ties** / 0 baseline wins / 0 untested across **41** comparison instances; **6 celah dideklarasikan, 5 tertutup, 1 terbuka** (`post_browser_multipart_upload` — upload file via `<input type=file>` tidak diukur, butuh file chooser CDP).

## Bug yang ditemukan dan diperbaiki selama pengerjaan (dicatat karena nyata)

1. **`ext_request_headers()` crash pada path redirect**: mengakses `spec["content_type"]` padahal `/post/redirect307` tidak punya key itu → `KeyError`. Diperbaiki dengan `.get("content_type")`.
2. **Halaman form tidak dirender browser**: `_send` selalu mengirim `text/plain`, jadi chromium tidak merender `<form>`. Diperbaiki: route `is_page` mengirim `text/html`. Lalu ditemukan lagi: browser otomatis meminta `/favicon.ico` (path tak dikenal, `spec=None`) dan baris baru saya crash `AttributeError` — diperbaiki dengan guard `spec is not None`.
3. **Arm UWAE gagal total di E22 (0/1) sementara Botasaurus lolos**: probe CDP mentah menunjukkan `Runtime.evaluate` **menolak** `return` di top-level (`SyntaxError: Illegal return statement`), sementara Botasaurus `Tab.evaluate` **mewajibkan** prefix `return`. Solusi: body JS sama untuk kedua arm, pembungkus berbeda per API (`(function(){...})()` untuk UWAE, `return (function(){...})()` untuk Botasaurus). Setelah perbaikan: tie 1/1 di smoke test, lalu 30/30 di run penuh.
4. **E22 tidak terbaca korpus sebagai `no_evaluable_runs`**: skema `e16_like` mengharapkan field `runs`/`uwae_evaluated_runs`/`uwae_successes` di `summary.comparisons`, bukan `uwae.primary_success_runs`. Diperbaiki di harness DAN di evidence yang sudah terbit (dengan koreksi eksplisit, bukan ditimpa diam-diam).
5. **Invariant tes korpus terlalu ketat**: "satu dimensi = satu slot aktif" tidak lagi berlaku karena E20/E21/E22 sengaja berbagi dimensi `http-post` sebagai ekstensi skenario berbeda. Diperbaiki menjadi invariant yang benar: tidak ada pasangan (dimensi, skenario, uwae_arm, baseline_arm) yang dihitung dua kali.

## Apa yang TIDAK diklaim
- **Tidak ada klaim UWAE mengungguli Botasaurus.** Ketiga slot baru adalah **tie** — dan tie memang yang menutup celah paritas, bukan kemenangan.
- `post_browser_multipart_upload` tetap terbuka (dideklarasikan di E22 sebagai `unsupported_scenarios`).
- Latency: UWAE lebih lambat di semua slot (E21 multipart ~159 ms vs ~24 ms; E22 browser ~1.950 ms vs ~9.474 ms median) — dilaporkan apa adanya, itu harga overhead framework.

## Link
- Evidence: `docs/benchmark/engine-results-e21.json`, `docs/benchmark/engine-results-e22.json`, `docs/benchmark/engine-results-e17.json`, `docs/benchmark/corpus-verdict-matrix.md`
- Harness: `src/universal_web_acquisition/benchmark/post_ext_diff_bench.py`, `post_browser_diff_bench.py`
- Fixture: `src/universal_web_acquisition/benchmark/fixture_post.py` (diperluas; `fixture_server.py` milik user tetap tidak disentuh)
- Korpus: `src/universal_web_acquisition/benchmark/corpus_matrix.py` (`SLOT_DIMENSIONS` + `DECLARED_GAP_CLOSURES`)
- Tes: `tests/test_corpus_matrix.py` (36 passed)
- Matriks: `docs/benchmark/competitive-matrix.md`
