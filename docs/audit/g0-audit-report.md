# G0 Audit Report — Botasaurus & Kemampuan Aktual Termux

**Milestone:** G0 — Audit Botasaurus dan kemampuan aktual Termux (INSTRUCTION.md, Engineering Specification v2 §8)
**Tanggal:** 2026-10-20
**Prinsip:** laporan berbasis bukti, bukan kesimpulan bahwa framework baru lebih baik. Tidak ada klaim mengungguli Botasaurus sebelum ada hasil pengujian.

---

## 1. Ringkasan

| Butir G0 | Status | Bukti |
|---|---|---|
| 1. Pin commit source Botasaurus | ✅ | `git rev-parse HEAD` = `6c9260de12d71b9dc0c3b3a019d2698a9af38433` (snapshot `audit/sumber-asli/botasaurus-baseline/`, git repo utuh). `audit/baseline-kommit.txt` **dikoreksi** — sebelumnya berisi `27f4318` (commit repo `/root`, bukan Botasaurus) |
| 2. Inventaris file, package, dependensi, adapter, tes | ✅ | 618 file tracked, **113 file `.py`**, 34 entri top-level, 10 komponen (detail: `source-inventory.json`); dependensi runtime 14 paket + 1 cpython dari `setup.py` |
| 3. Kemampuan terimplementasi vs teruji | ⚠️ parsial | `capability-evidence.csv` (14 baris) seluruhnya `VERIFIED_SOURCE` — belum ada verifikasi runtime. Dijawab oleh daftar eksperimen §4 |
| 4. Verifikasi transport terpasang di Python perangkat | ✅ | Matriks G0-3 (`environment-report.md` §2): httpx/requests/urllib3/aiohttp **lolos smoke test**; niquests/curl_cffi/pycurl belum terpasang |
| 5. Verifikasi jalur browser Android | ✅ | **Chromium 151 headless terverifikasi jalan** (dump-dom, exit=0); cache Playwright lengkap; firefox PRoot rusak, firefox Termux 157.0.1 terpasang (detail: `environment-report.md` §3) |
| 6. Laporan audit + daftar eksperimen prioritas | ✅ | Dokumen ini |
| 7. Benchmark fixture + classifier | ⏳ | Sesuai urutan — **dimulai setelah G0**, belum dimulai |

## 2. Temuan Kunci (fakta → implikasi)

1. **Dua binary Python aktif.** Termux 3.14.6 (dipakai proyek/pytest) vs PRoot 3.14.4 (dipakai `pip` default). Implikasi: instalasi paket wajib eksplisit per interpreter, jika tidak terpasang salah environment.
2. **Klaim "120+ modul" terjawab dengan bukti** (Lampiran L.1): 357 paket di venv (B/C) vs 113 file `.py` milik repo Botasaurus (A). Implikasi: kekuatan Botasaurus ada di ekosistem dependensinya (botasaurus-requests, botasaurus-driver, bota, dst.), bukan jumlah file — target kompetitif berbasis kemampuan.
3. **Chromium 151 headless jalan di PRoot tanpa root** — jalur browser otomasi (CDP/Playwright) **layak**, berbeda dari asumsi awal bahwa browser desktop tidak tersedia di Termux. Cache Playwright (`chromium-1234/1243`, `firefox-1538`, `webkit-2336`) sudah terunduh — instalasi Playwright Python berpotensi tanpa unduhan ulang.
4. **TLS fingerprint layer belum ada** (curl_cffi/niquests tidak terpasang) — lapisan yang paling relevan untuk website modern belum terverifikasi di perangkat. Prioritas eksperimen tertinggi.
5. **Benchmark tidak apple-to-apple bila dicampur environment**: venv Botasaurus punya brotli 1.2.0 + requests 2.34.2; Python Termux tidak punya brotli, requests 2.33.0. Benchmark differential wajib menyamakan/mencatat ini.
6. **Artefak audit lama mengandung kesalahan faktual** (sudah dikoreksi): `baseline-kommit.txt` salah commit; `source-inventory.json` mencatat `x86_64` dan statistik nol; `environment-report.md` lama memuat konteks proyek lain.

## 3. Jawaban Butir 3 — Kemampuan Terimplementasi vs Teruji

Status `capability-evidence.csv` (semua `VERIFIED_SOURCE`, belum ada runtime):

| Kemampuan Botasaurus | Bukti source | Verifikasi runtime |
|---|---|---|
| @request (HTTP) | `request_decorator.py` | ❌ belum |
| @browser (Selenium-based) | `browser_decorator.py` | ❌ belum — catatan: venv memakai `botasaurus_driver` 4.0.101 (driver sendiri, menerima `chrome_executable_path`), bukan selenium langsung |
| Paralel (@task + joblib) | `task_decorator.py`, setup.py | ❌ belum |
| Cache (FileCacheStorage) | `cache.py` | ❌ belum |
| Retry | `request_decorator.py` | ❌ belum |
| Proxy | `request.py`, `browser.py` | ❌ belum |
| Anti-detection | `anti-detect-driver.md`, `bot_detection_tests.py` | ❌ belum |

Implikasi: sebelum klaim kompetitif apa pun, minimal satu skenario differential harus dijalankan pada baseline ter-pin (eksperimen E5).

## 4. Daftar Eksperimen Prioritas

| # | Eksperimen | Tujuan | Bukti yang diharapkan | Kriteria selesai |
|---|---|---|---|---|
| **E1** ✅ | Instal `curl_cffi` di Python Termux 3.14.6 | Verifikasi lapisan TLS fingerprint di aarch64/py3.14 | Import OK + smoke 200; atau bukti kegagalan build/wheel | **SELESAI 2026-10-20** — hasil di §7 |
| **E2** ✅ | Instal `playwright` (Python) + pakai cache `~/.cache/ms-playwright` yang ada | Jalur browser penuh tanpa unduhan ulang | Launch chromium-1243 headless via sync API, navigasi 1 halaman | **SELESAI 2026-10-20** — hasil di §7 (catatan: hanya di PRoot python) |
| **E3** ✅ | Chromium CDP mentah via `websockets` (sudah terpasang 15.0.1) | Jalur browser minimalis tanpa dependency baru | Sambung ke `chromium --headless --remote-debugging-port`, evaluasi 1 ekspresi JS | **SELESAI 2026-10-20** — hasil di §7 |
| **E4** ✅ | Instal `brotli` + `selectolax` di Python Termux | Menyamakan content-encoding & parsing cepat | Import OK; decode brotli 1 payload | **SELESAI 2026-10-20** — hasil di §7 |
| **E5** ✅ | **Fixture server + benchmark differential pertama** (httpx vs requests vs curl_cffi vs botasaurus-venv) | Baseline terukur pada skenario deterministik lokal | `docs/benchmark/transport-results.json` terisi; latency/success/memory per skenario | **SELESAI 2026-10-20** — 6 skenario × 4 engine, 24/24 sukses — hasil di §7 |
| **E6** ✅ | Regression test isu publik Botasaurus (L.6: Cloudflare bypass timeout + DNS infinite retry) pada commit ter-pin | Memisahkan fakta vs hipotesis pada kelemahan yang diklaim | Reproduce / tidak-reproduce terdokumentasi | **SELESAI 2026-10-20** — infinite retry REPRODUCE (source + runtime); bagian Cloudflare timeout tidak diuji (butuh otorisasi) — hasil di §7 |
| **E7** ✅ | Instal `niquests` (HTTP/3) | Cakupan protokol | Import + smoke | **SELESAI 2026-10-20** — niquests 3.21.2 terpasang, smoke 200 (HTTP/2; h3 bergantung iklan server) — hasil di §7 |

Urutan: **E1 → E5** adalah jalur kritis (E5 butuh E1/E4 untuk perbandingan adil); E2/E3 paralel; E6/E7 menyusul.

## 5. Checklist Exit G0 (Lampiran L.2 INSTRUCTION.md)

- [x] Snapshot Botasaurus dan commit SHA tercatat — `6c9260de…`, `audit/baseline-kommit.txt` dikoreksi
- [x] Peta dependensi mencakup kode internal dan dependensi eksternal — `setup.py` + 357 paket venv (`source-inventory.json`)
- [~] Temuan penting memiliki bukti source, test, atau eksperimen — source ✅; eksperimen runtime = E1–E7 (belum dijalankan)
- [~] Capability matrix membedakan fakta dan hipotesis — kolom runtime masih kosong (§3)
- [ ] Benchmark memiliki ground truth dan skema hasil — dokumen ada (`fixtures-spec.md`, `result-schema.json`), fixture server **belum dibangun** (E5)
- [ ] Pengukuran mencakup kebenaran hasil, kegagalan, latency, resource use — menunggu E5
- [~] Kontrak Job, ArtifactManifest, AcquisitionResult, dan plugin telah ditinjau — kode Phase 1 lama ada (`job_model.py`, `artifact/model.py`); kontrak baru (access assessment, session recovery) **belum** — masuk Fase 2
- [~] ADR menyatakan alternatif, trade-off, dan keputusan yang masih terbuka — ADR-001…010 ada; ADR transport selection **belum** (deliverable L.3)
- [~] Roadmap Phase 1 memiliki acceptance criteria yang dapat diuji — `phase-1-implementation-plan.md` ada (kriteria lama); perlu rekonsiliasi dengan INSTRUCTION.md
- [x] Perubahan tidak merusak file atau keputusan proyek yang sudah ada — hanya koreksi faktual + file baru

**Kesimpulan G0:** 5/10 butir penuh, 4 parsial, 1 terbuka. G0 **cukup untuk melanjutkan** ke E1–E5 (eksperimen) dan Fase berikutnya, dengan catatan butir benchmark/contract baru selesai di jalurnya masing-masing.

## 6. Langkah Berikutnya

1. ~~Jalankan E1 (curl_cffi) dan E4 (brotli/selectolax)~~ ✅ **KEDUANYA SELESAI** (§7).
2. ~~Jalankan E2/E3 (jalur browser)~~ ✅ **KEDUANYA SELESAI** (§7) — keputusan jalur utama (Playwright/PRoot vs CDP/Termux) masuk ADR transport selection.
3. ~~Bangun fixture server + runner (E5)~~ ✅ **SELESAI** (§7) — hasil benchmark pertama tersimpan. ADR transport selection (L.3) ✅ ditulis: `docs/architecture/decisions/ADR-011-transport-selection.md`. Kontrak Fase 2 ✅ ditulis (`access/model.py`, `http_transport/registry.py`, `session/recovery.py` — 29 test hijau, termasuk fix bug `job_worker.py` + `verify_basic.py`). Implementasi transport registry ✅ (2026-10-21): `http_transport/adapters.py` (curl_cffi primary + fallback httpx/requests, klasifikasi ReasonCode) + wiring `job_worker.py` (eksekusi nyata, bounded retry) — full suite 90 passed.
4. ~~Rekonsiliasi roadmap Phase 1~~ ✅ **SELESAI** — bagian "Reconciliation with INSTRUCTION.md (2026-10-20)" ditambahkan di `docs/roadmap/phase-1-implementation-plan.md`: pemetaan 8 langkah lama → status pasca-G0, tambahan mandat (access classifier, strategy planner, session recovery, bounded retry), dan urutan implementasi baru.
5. ~~Jalankan E6 + E7~~ ✅ **KEDUANYA SELESAI** (§7) — **seluruh 7 eksperimen G0 selesai**.

## 7. Log Hasil Eksperimen

### E1 — curl_cffi ✅ SELESAI (2026-10-20)

- **Instalasi:** SUKSES — wheel resmi tersedia untuk platform ini: `curl_cffi-0.16.3-cp314-cp314-android_24_arm64_v8a.whl` (8,6 MB), terpasang di Python Termux 3.14.6 (pip 26.2.1).
- **Smoke test:**
  - `GET https://example.com` + `impersonate="chrome"` → **200** (2.891 ms), konten valid ("Example Domain" ditemukan)
  - Tanpa impersonation → 200 (246 ms)
- **Implikasi:** lapisan TLS fingerprint (browser-like) **terverifikasi tersedia** di Termux aarch64/py3.14 — fondasi Adaptive Access Engine untuk website modern.
- **Catatan pengukuran:** selisih 2.891 ms vs 246 ms diduga cold-start (TLS handshake + DNS). Pengukuran warm/cold yang benar dilakukan di benchmark E5.

### E2 — Playwright ✅ SELESAI (2026-10-20)

- **Ketersediaan wheel:**
  - Python Termux 3.14.6 (bionic): **TIDAK ADA** wheel playwright (`from versions: none`) — wheel manylinux (glibc) tidak kompatibel dengan Python bionic
  - Python PRoot 3.14.4 (glibc): **playwright 1.63.0 terpasang** — dengan `--break-system-packages` (PEP 668; environment PRoot container, risiko rendah)
- **Launch tanpa unduhan:** `executable_path` eksplisit ke cache yang ada → `~/.cache/ms-playwright/chromium-1234/chrome-linux/chrome` (Chromium 151.0.7922.34) — **jumlah unduhan = 0** ✅
- **Verifikasi:** navigasi `data:` URL → heading "E2-OK", title "uwae-e2", ekstraksi link `['/x']`, `page.evaluate` JS OK
- **Temuan fingerprint:** UA default binary ini melaporkan `X11; Linux x86_64` padahal aarch64 — UA tidak akurat; relevan untuk anti-detection (engine wajib override UA)
- **Implikasi arsitektur:** Playwright hanya jalan di **PRoot python (glibc)**; HTTP transport di **Termux python (bionic)** — engine perlu keputusan satu-environment vs dua-environment (masuk ADR)

### E3 — Chromium CDP mentah via websockets ✅ SELESAI (2026-10-20)

- **Setup:** `chromium --headless=new --no-sandbox --remote-debugging-port` → `/json/list` → page target `webSocketDebuggerUrl`
- **Klien:** `websockets` 15.0.1 (sudah terpasang — **tanpa dependency baru**)
- **Verifikasi:** `Runtime.evaluate` → `{"calc":2,"heading":"E3-OK","js":"object"}` — evaluasi JS + akses DOM sukses
- **Pelajaran teknis:** harus konek ke **page target** (bukan browser-level target dari `/json/version`) — `Runtime.evaluate` tidak didukung di browser target (percobaan pertama gagal: `KeyError: 'result'`)
- **Implikasi:** jalur browser minimalis tersedia di **Python Termux** langsung — alternatif ringan tanpa Playwright; cocok untuk transport adapter ringan, sementara Playwright (PRoot) untuk kebutuhan penuh (screenshot, multi-context)

### E4 — brotli + selectolax ✅ SELESAI (2026-10-20)

- Percobaan 1 (default `pip install`): timeout 300 s — pip build dari source.
- Percobaan 2 (`--only-binary=:all:`): **tidak ada wheel** brotli untuk platform ini (`from versions: none`) → build source satu-satunya jalur.
- Percobaan 3 (background, build source): **SUKSES** — `Successfully installed brotli-1.2.0 selectolax-1.0.1` (exit=0), C extension terkompilasi di Python Termux 3.14.6.
- **Verifikasi fungsional:**
  - brotli: roundtrip 11.526 B → 60 B (rasio 0,01) dalam 3,9 ms — decode OK
  - selectolax: backend `HTMLParser` (Modest) **deprecated** di v1.0 (ImportError dengan pesan eksplisit); backend `lexbor` OK — parse + ekstraksi 0,52 ms
- **Implikasi:** benchmark differential kini dapat apple-to-apple untuk content-encoding brotli; parsing cepat tersedia (catatan: gunakan `selectolax.lexbor`, bukan `HTMLParser`).

### E5 — Fixture server + benchmark differential ✅ SELESAI (2026-10-20)

- **Deliverable baru:**
  - `src/universal_web_acquisition/benchmark/fixture_server.py` — server fixture deterministik localhost (B01 GET kecil/besar, B04 redirect 3-hop, B06 gzip/brotli, E02 404) dengan ground truth byte-for-byte
  - `src/universal_web_acquisition/benchmark/transport_bench.py` — runner differential (5 run timing + 1 run tracemalloc per kombinasi, koneksi baru per run)
  - `docs/benchmark/transport-results.json` — hasil mentah (benchmark_id `e5-transport-differential-001`, 6 skenario × 4 engine = 24 hasil)
- **Hasil (median ms, localhost):**

| Skenario | httpx | requests | curl_cffi | baseline (venv 2.34.2) |
|---|---|---|---|---|
| b01_small_get | 37.85 | 36.13 | 23.19 | **18.75** |
| b01_large_get | 59.04 | 52.87 | 27.85 | **24.10** |
| b04_redirect | 114.86 | 106.23 | **47.60** | 55.81 |
| b06_gzip | 40.39 | 30.08 | 14.90 | **13.07** |
| b06_brotli | 44.62 | 21.74 | **14.43** | 19.23 |
| e02_not_found | 41.94 | 15.75 | 20.48 | **13.94** |

- **Korektivitas: 24/24 sukses** — status benar + konten byte-for-byte identik di semua kombinasi (termasuk decode gzip & brotli otomatis).
- **Pola:** baseline botasaurus-venv menang 4/6 skenario; curl_cffi menang 2/6 (redirect, brotli) dan konsisten kompetitif; httpx paling lambat di sebagian besar skenario.
- **Interpretasi jujur (sesuai mandat INSTRUCTION.md):** ini pengukuran baseline, **BUKAN klaim kompetitif**. Selisih puluhan ms pada localhost. Nilai utamanya: harness reproducible + fondasi differential yang dapat diulang.
- **Caveat terukur:**
  - Baseline berjalan di Python PRoot 3.14.4 (glibc) vs engine lain di Termux 3.14.6 (bionic) — perbedaan environment mengotori perbandingan langsung
  - tracemalloc hanya menghitung alokasi Python — memori curl_cffi (buffer C) tampak lebih rendah dari kenyataan
  - Koneksi baru per run (tanpa keep-alive) — pengukuran keep-alive/session reuse masuk iterasi benchmark berikutnya

### E6 — Regression test isu publik Botasaurus ✅ SELESAI (2026-10-20)

**Target:** botasaurus_requests 4.0.38 (venv baseline, commit ter-pin 6c9260de). Skrip: `tests/regression/e6_botasaurus_dns_retry.py`.

| Tahap | Hasil |
|---|---|
| T1 — bukti source | `retry_on_network_error` = `while True` **tanpa batas retry** (tidak ada max_retry/range/break); kondisi: error memuat `'dial tcp: lookup'` + `'no such host'` → sleep 20 dtk lalu ulang selamanya |
| T2 — runtime (crafted error) | **REPRODUCE**: 3 attempt teramati dalam window 50 dtk (sleep 20 dtk antar-attempt), proses di-kill timeout (exit 124) — tidak berterminasi |
| T3 — kontrol | Error non-DNS ("connection refused") langsung di-raise — loop selektif, bukan retry blanket |
| T4 — DNS failure nyata | **KOREKSI (ADR-019)**: temuan lama ("pesan error aktual = `'headers'`, jadi tidak cocok") berasal dari baseline yang salah — `KeyError('headers')` terjadi SEBELUM ada permintaan DNS sama sekali, sehingga pesan resolver tidak pernah terlihat. Dengan baseline yang benar (jalur publik `Request`), pesan resolver aktual di environment ini = `'dial tcp: lookup ...: no such host'` (format Go) → **kondisi retry TERPICU**. Karena pencocokan bersifat literal atas teks, teks resolver yang berbeda (mis. `Temporary failure in name resolution`) membuat trigger tidak terjadi — hasil per-run diukur apa adanya di `engine-results-e14.json` |

**Verdict:** isu infinite-retry **REPRODUCE** — defect ada di source ter-pin dan terpicu pada runtime untuk error yang cocok pola. **KOREKSI (ADR-019):** di environment ini kondisi tersebut **terpicu** untuk kegagalan DNS nyata (pesan resolver Go-style `dial tcp: lookup ...: no such host`); temuan lama "tidak terpicu" adalah artefak baseline yang salah, bukan sifat lingkungan. Karena pencocokan literal atas teks, pemicu bergantung pada pesan resolver yang dihasilkan client di bawahnya — hasil per-run diukur apa adanya di `engine-results-e14.json`.
**Tidak diuji:** bagian "Cloudflare bypass timeout" (butuh target ber-CF dengan otorisasi eksplisit).
**Implikasi UWAE:** kontrak access control plane (INSTRUCTION.md) mewajibkan retry berbatas + reason code — ini diferensiator konkret dengan bukti, bukan klaim.

### E7 — niquests (HTTP/3) ✅ SELESAI (2026-10-20)

- **Instalasi:** SUKSES — `niquests-3.21.2` (+ deps `jh2`, `urllib3-future`, `wassima`) di Python Termux 3.14.6.
- **Smoke test:** `GET https://example.com` → **200** (5.673 ms cold), HTTP version ternegosiasi = **HTTP/2** (`20`).
- **Catatan:** HTTP/3 (QUIC) hanya dipakai bila server mengiklankan `alt-svc: h3` — example.com tidak mengiklankan h3 pada koneksi ini, sehingga negosiasi h3 belum terbukti; verifikasi h3 penuh butuh server pengiklan h3 (masuk iterasi benchmark berikutnya).
- **Implikasi:** transport HTTP/2/3-ready tersedia di Python Termux — melengkapi matriks transport untuk ADR transport selection.
