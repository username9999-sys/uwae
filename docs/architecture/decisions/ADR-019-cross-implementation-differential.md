# ADR-019: Cross-implementation differential — mengukur UWAE vs Botasaurus di device yang sama

## Status
Accepted (2026-10-27 — evidence: engine-results-e14.json, benchmark_id `e14-cross-implementation-differential-001`)

## Context

TEXT.md competitively spike menuntut perbandingan dengan Botasaurus yang
**benar-benar tersedia**:

> *"Hasilnya tetap harus dibandingkan dengan perilaku Botasaurus yang benar-benar
> tersedia, bukan dengan implementasi pembanding yang sengaja dibuat lemah."*

INSTRUCTION.md memperjelas syaratnya (baris 580):

> *"Use identical targets, expected outputs, device conditions, run counts, and
> success criteria for Botasaurus and the new engine."*

Selama ini mandate itu **tidak bisa dipenuhi**, karena bukti yang ada di repo
menyatakan baseline HTTP Botasaurus tidak bisa dieksekusi di environment ini:

> *"engine HTTP Botasaurus TIDAK BERFUNGSI di PRoot aarch64 Termux —
> semua request gagal dengan `KeyError('headers')`."*

Klaim itu diwarisi dari `engine-results.json` (E8), `engine-results-e9.json`
(E9), dan `engine-results-e12.json` (E12), lalu dirujukkan dalam ADR-017 dan
ADR-018 sebagai alasan why cross-implementation benchmark belum dilakukan.

### Akar masalah: bug di skrip baseline milik proyek ini

Klaim "tidak berfungsi" ternyata **SALAH**. Rantai buktinya:

| Pemanggilan | Hasil | Alasan |
|---|---|---|
| `botasaurus_requests.get(url)` | **GAGAL** `KeyError('headers')` | `fix_headers` membaca `kwargs['headers']` **tanpa `.get()`** |
| `botasaurus_requests.get(url, headers={})` | OK | header dibuat lebih dulu, jadi `kwargs['headers']` ada |
| `Request().get(url)` | **OK** | `Request.get` default `referer="https://www.google.com/"` → `add_google_referer_if_given` membuat `kwargs['headers']` |
| `Request().get(url, referer=None)` | GAGAL lagi | referer `None` → header tidak pernah dibuat → bug yang sama |

Jadi `KeyError('headers')` adalah **bug pemanggilan di skrip baseline proyek
ini** (`engine_bench.BASELINE_SCRIPT` memakai `from botasaurus_requests import
get` + `get(url)`), bukan ketidakcocokan platform PRoot/aarch64. Binary native
`hrequests-cgo-2.1-linux-arm64.so` di venv berjalan normal.

Konsekuensi langsung: **perbandingan lintas-implementasi menjadi mungkin**,
dan seluruh alasan lama untuk tidak melakukannya gugur.

### Konsekuensi kedua: temuan E6 ikut terkoreksi

`docs/audit/g0-audit-report.md` T4 pernah menyimpulkan "pesan error aktual =
`'headers'`, jadi kondisi retry tidak cocok". Itu artefak baseline yang salah —
`KeyError` terjadi **sebelum** ada permintaan DNS sama sekali, sehingga pesan
resolver tidak pernah terlihat. Dengan baseline yang benar, pesan resolver
asli di device ini berbentuk Go-style:

```
dial tcp: lookup nonexistent-uwae-e14-test.invalid on 8.8.8.8:53: no such host
```

dan `retry_on_network_error` (`while True` + `sleep(20)`, gate pada
`'dial tcp: lookup'` **dan** `'no such host'`) **terpicu**. Karena pencocokan
bersifat literal atas teks, hasilnya tetap bergantung pada pesan resolver —
diukur apa adanya, bukan dirata-rata.

## Decision

1. **Perbandingan memakai jalur publik Botasaurus, bukan API internal.**
   Baseline arm memakai dekorator `@request` (public API) dengan
   `output=None, create_error_logs=False, raise_exception=False,
   close_on_crash=True, cache=False` — semua default Botasaurus kecuali tiga
   yang disebut eksplisit agar tidak ada output interaktif. Versi ter-pin:
   botasaurus 4.0.97 / botasaurus_requests 4.0.38 / botasaurus_driver
   4.0.101, source commit `6c9260de12d71b9dc0c3b3a019d2698a9af38433`.

2. **Satu interpreter, satu PYTHONPATH, satu fixture server, dua subprocess.**
   Kedua arm adalah subprocess dari **interpreter yang sama**
   (`/root/uwae-comparison-venv/bin/python`, CPython 3.14.4,
   `Linux-6.17.0-PRoot-Distro-aarch64-with-glibc2.43`, aarch64) dengan
   **PYTHONPATH yang sama**
   (`/root/botasaurus-venv/lib/python3.14/site-packages:<repo>/src`), dan
   melawan **satu instance** fixture server deterministik. Perbedaan
   interpreter/venv — penyebab utama benchmark lama tidak adil — dihilangkan
   secara struktural, bukan dengan penyesuaian manual.

3. **Lima kondisi identik dicatat sebagai data, bukan sebagai klaim.**
   `environment.identical_conditions` dalam evidence menyimpan lima flag
   (`targets`, `expected_outputs`, `device_conditions`, `run_counts`,
   `success_criteria`) — semuanya `true` dan dapat diaudit.

4. **Tiga sumbu metrik dipisahkan, karena "sukses" tidak punya arti tunggal.**

   - **Akuisisi** — status + body byte-for-byte (sha256 + panjang). Ini
     pertanyaan "dapatkah engine mengambil konten target?".
   - **Diagnosis penyebab** — untuk skenario yang semantiknya menuntut
     diagnosis (JS gate, 404, login, 429, challenge, denied, HTML rusak).
     Ini pertanyaan "apakah engine tahu **kenapa** gagal?".
   - **False-problem rate** — pada skenario sehat, apakah engine melapor
     masalah yang sebenarnya tidak ada. Engine **tanpa API diagnosis** tidak
     diberi kredit maupun tuduhan: `diagnosis_verified` bernilai `None`
     (tidak dinilai, bukan gagal).

   Menggabungkan ketiganya menjadi satu angka akan salah: Botasaurus
   mengembalikan body respons apa adanya sehingga "sukses akuisisi" 65/65,
   sementara UWAE tidak pernah menyimpan artifact untuk respons 4xx/5xx
   (kode itu adalah diagnosis, bukan konten target) sehingga byte terverifikasi
   hanya 45/65. Kedua angka itu **benar** pada sumbunya masing-masing.

5. **Ground truth berasal dari semantika protokol fixture, bukan dari output
   engine.** Tujuh skenario penyebab punya label ground truth yang dikunci di
   harness (`javascript_required`, `content_invalid`, `auth_required`,
   `rate_limited`, `challenge_present`, `access_denied`) dan diverifikasi ke
   marker body fixture ("please enable javascript", `type="password"`,
   "just a moment", "rate limited", "access denied"). Label harus berada di
   kosakata `AccessState` yang dipakai engine.

6. **Bukti historis tidak ditimpa.** `engine-results.json`, `engine-results-e9.json`,
   dan `engine-results-e12.json` **tidak diubah pada field pengukuran mentah**.
   Koreksi ditambahkan sebagai objek `correction` top-level yang menunjuk ke
   ADR-019 dan `superseded_by`, sehingga pembaca lama tetap melihat data apa
   adanya beserta koreksinya. Preseden: ADR-018 ("bukti historis E8 tidak
   ditimpa").

7. **Skenario yang tidak didukung kedua engine dicatat, bukan disembunyikan.**
   `a05_protected` (butuh alur sesi terautentikasi) dan arm
   `js_rendering_browser_arm` (kedua arm adalah HTTP; rendering JS butuh arm
   browser) dicatat di `unsupported_scenarios` beserta alasannya — mandated
   oleh G7 ("termasuk skenario yang tidak didukung engine mana pun").

8. **Tidak ada klaim "mengungguli".** `summary.interpretation` menyatakan
   eksplisit: pengukuran baseline lintas-implementasi, **BUKAN** klaim UWAE
   mengungguli Botasaurus (mandat INSTRUCTION.md).

## Measured Results (evidence: engine-results-e14.json)

13 skenario × 5 run × 2 arm = **130 run**. Tidak ada runtime failure di kedua
arm pada tabel skenario.

### Sumbu utama

| Metrik | UWAE | Botasaurus |
|---|---|---|
| Primary success (kriteria per skenario) | **65 / 65** | **30 / 65** |
| Byte terverifikasi (akuisisi saja) | 45 / 65 | **65 / 65** |
| Diagnosis penyebab — TP / FN / FP | **35 / 0 / 0** | 0 / 35 / 0 |
| Diagnosis penyebab — precision / recall / F1 | **1.0 / 1.0 / 1.0** | 0.0 / 0.0 / 0.0 |
| False-problem rate (30 run sehat) | 0 / 30 (0.0) | 0 / 30 (0.0) |
| Runtime failure | tidak ada | tidak ada |

Selisih primary success **tidak** berarti UWAE "lebih baik 65 vs 30" secara
seragam: enam skenario sehat bernilai 5/5 di kedua arm, dan **seluruh
selisihnya (35 run)** berada pada tujuh skenario penyebab — titik di mana
kriteria adalah diagnosis, dan Botasaurus **tidak punya API diagnosis sama
sekali**. Itu celah kemampuan, bukan strawman: arm Botasaurus mengembalikan
respons apa adanya (65/65 byte benar, ~20–105 ms) dan memang kompetitif pada
bidang akuisisi murni.

### Per skenario

| Skenario | Kriteria | Status | UWAE ok | Bota ok | UWAE med ms | Bota med ms | UWAE p95 ms | Bota p95 ms | Peak mem U/B (MB) | Attempt U/B | Diagnosis UWAE |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `b01_small_get` | akuisisi | 200 | 5/5 | 5/5 | 137.11 | 25.06 | 1151.54 | 56.13 | 15.98 / 0.44 | 1 / 1 | `access_granted` |
| `b01_large_get` | akuisisi | 200 | 5/5 | 5/5 | 160.13 | 104.83 | 186.61 | 175.02 | 16.26 / 2.85 | 1 / 1 | `access_granted` |
| `b04_redirect` | akuisisi | 200 | 5/5 | 5/5 | 161.32 | 64.59 | 176.91 | 95.57 | 13.15 / 0.58 | 1 / 1 | `access_granted` |
| `b06_gzip` | akuisisi | 200 | 5/5 | 5/5 | 178.95 | 29.81 | 218.30 | 36.78 | 12.10 / 0.65 | 1 / 1 | `access_granted` |
| `b06_brotli` | akuisisi | 200 | 5/5 | 5/5 | 157.57 | 32.03 | 165.51 | 50.16 | 12.12 / 0.71 | 1 / 1 | `access_granted` |
| `b07_js_render` | diagnosis | 200 | 5/5 | 0/5 | 165.84 | 31.39 | 190.47 | 43.75 | 12.14 / 0.78 | 1 / 1 | `javascript_required` |
| `e02_not_found` | diagnosis | 404 | 5/5 | 0/5 | 683.08 | 27.65 | 750.23 | 35.65 | 12.02 / 0.84 | 5 / 1 | `content_invalid` |
| `a04_login` | diagnosis | 200 | 5/5 | 0/5 | 639.54 | 32.71 | 791.15 | 51.86 | 12.22 / 0.91 | 5 / 1 | `auth_required` |
| `a06_rate_limited` | diagnosis | 429 | 5/5 | 0/5 | 4618.36 | 30.24 | 4712.08 | 45.80 | 12.10 / 0.97 | 5 / 1 | `rate_limited` |
| `a07_challenge` | diagnosis | 403 | 5/5 | 0/5 | 185.32 | 29.66 | 274.11 | 34.24 | 12.11 / 1.04 | 1 / 1 | `challenge_present` |
| `a07_denied` | diagnosis | 403 | 5/5 | 0/5 | 165.06 | 19.78 | 251.66 | 58.43 | 12.11 / 1.10 | 1 / 1 | `access_denied` |
| `a11_invalid_html` | diagnosis | 200 | 5/5 | 0/5 | 775.80 | 20.31 | 834.56 | 37.21 | 12.31 / 1.17 | 5 / 1 | `content_invalid` |
| `a09_large_download` | akuisisi | 200 | 5/5 | 5/5 | 563.03 | 96.55 | 626.38 | 105.17 | 21.63 / 3.15 | 1 / 1 | `access_granted` |

### Biaya: UWAE lebih lambat dan lebih boros di localhost

Ini hasil yang harus dilaporkan apa adanya, bukan disembunyikan:

- **Latency median**: UWAE 137–4618 ms vs Botasaurus 20–105 ms. UWAE lebih
  lambat pada **setiap** skenario. Penyebabnya siklus ACP penuh: penulisan
  job/attempt/event ke SQLite, persistensi artifact, `asyncio.run` overhead.
  Pada target nyata selisih relatif menyusut, tapi pada localhost yang
  diukur Botasaurus menang telak.
- **Peak memory (tracemalloc, alokasi Python)**: UWAE 12.1–21.6 MB vs
  Botasaurus 0.44–3.15 MB. Buffer C tidak dihitung — batasan yang sama
  dipakai benchmark transport E5, jadi konsisten antar-benchmark.
- **Attempt**: UWAE maksimum 5 attempt pada `e02_not_found`, `a04_login`,
  `a06_rate_limited`, `a11_invalid_html` (retry berbatas; 429 menghormati
  `Retry-After: 1` sehingga median ~4,6 s). Botasaurus 1 attempt di semua
  skenario — `@request` tidak me-retry secara default.
- **p95 pada n=5** setara nilai maksimum (nearest-rank) sehingga **belum
  bermakna secara statistik**; semua waktu mentah tersimpan di
  `elapsed_ms_runs`. Dicatat eksplisit di `environment.percentile_note`.

### Boundedness pada kegagalan DNS

Target: `https://nonexistent-uwae-e14-test.invalid`, jendela observasi 90 s,
3 run per arm.

| Arm | Outcome terminal | Diagnosis terklasifikasi | Attempt | Siklus retry observed | Elapsed |
|---|---|---|---|---|---|
| UWAE | **3 / 3** | **3 / 3** (`network_failure` / `dns_failure` → `budget_exhausted`) | 7 / 7 / 7 | 0 / 0 / 0 | 16.976 / 21.106 / 17.135 s |
| Botasaurus | **0 / 3** (3/3 timeout) | 0 / 3 | — | **5 / 5 / 5** | 90.05 / 90.04 / 90.03 s |

Botasaurus **tidak pernah mencapai outcome terminal** dalam jendela 90 s — proses
terbunuh timeout dengan siklus "Retrying in 20 seconds..." yang berulang. UWAE
selalu berakhir: 7 attempt (curl_cffi → httpx → requests), anggaran habis,
diagnosis terklasifikasi, `budget_exhausted` — hasil terminal yang jujur
(mandat ACP §2: kegagalan boleh terminal, asalkan **terklasifikasi**).

Catatan kehati-hatian: trigger Botasaurus bersifat **literal-text** — device ini
menghasilkan pesan Go-style (`dial tcp: lookup ...: no such host`) yang cocok;
device atau client lain yang menghasilkan `Temporary failure in name resolution`
tidak akan memicu loop tersebut. Angka di atas adalah hasil yang terukur di
device ini, bukan jaminan universal.

## Alternatives Considered

- **Membandingkan UWAE dengan `botasaurus_requests` API internal** — ditolak:
  jalur internal itu sendiri yang menyingkap bug pemanggilan proyek ini;
  `@request` adalah API publik yang benar-benar dipakai pengguna, dan
  setiap klaim "tidak bisa dieksekusi" harus dibuktikan pada jalur yang benar.
- **Menjalankan kedua arm di interpreter berbeda** (botasaurus di venv-nya,
  UWAE di Termux) — ditolak: perbedaan libc (glibc vs bionic) dan versi
  paket memotret environment, bukan engine. INSTRUCTION.md meminta device
  conditions identik.
- **Menghapus baseline "tidak bisa dieksekusi" tanpa bukti penggantinya** —
  ditolak: mandat INSTRUCTION.md G7 menuntut bukti yang dapat direproduksi.
  Yang ada baseline rusak → harus ada baseline benar.
- **Menggabungkan "primary success" menjadi satu angka** — ditolak:
  menyatukan akuisisi dan diagnosis akan melaporkan angka yang salah pada dua
  engine. Tiga sumbu dipisah, masing-masing dengan definisi tertulis.
- **Memberi UWAE kredit pada 4xx/5xx yang tidak disimpan sebagai artifact** —
  ditolak: respons 4xx/5xx bukan konten target; UWAE memilih mendiagnosis
  dan mengabort. Byte terverifikasi 45/65 dilaporkan apa adanya, tanpa
  penyesuaian.
- **Menghapus temuan E6 "infinite retry"** — ditolak: temuan itu **masih
  benar**; yang salah hanya alasannya. Source tetap `while True` tanpa batas;
  yang dikoreksi adalah klaim "tidak terpicu di device ini" → sekarang
  terbukti terpicu untuk pesan resolver Go-style.
- **Menaikkan run count untuk p95 bermakna** — ditolak untuk iterasi ini:
  5 run/arm/skenario sudah membedakan arah secara jelas, dan fixture
  `a06_rate_limited` punya jeda `Retry-After` yang membuat run banyak lambat.
  p95 pada n=5 dicatat sebagai belum bermakna, bukan dipoles.

## Consequences

- **Klaim lama "Botasaurus tidak berfungsi di PRoot" dicabut di seluruh repo**
  dengan koreksi eksplisit (bukan penghapusan diam-diam): `engine_bench.py`
  (skrip baseline + `environment_compatibility` + interpretasi),
  `strategy_bench.py`, roadmap Phase 1, ADR-017, ADR-018,
  `docs/benchmark/strategy-comparison.md`, `docs/audit/g0-audit-report.md`,
  README, dan tiga berkas evidence historis (via objek `correction`).
- **Skrip baseline `engine_bench.py` memakai jalur publik yang benar**
  (`Request().get(...)`), dan `tests/test_cross_impl_bench.py` mengunci
  bahwa `botasaurus_requests.get(` tidak boleh kembali — bug pemanggil yang
  sama tidak akan bisa masuk diam-diam.
- **Regresi untuk klaim yang sudah terbukti salah**: pola
  `"TIDAK BERFUNGSI di PRoot"`, `"engine HTTP Botasaurus tidak dapat
  dieksekusi"`, `"baseline Botasaurus tidak dapat dieksekusi"`, dan
  `"baseline_executable_in_this_environment"` diuji tidak muncul di enam
  berkas kunci.
- **Harness E14 baru** (`benchmark/cross_impl_bench.py`) +
  `docs/benchmark/engine-results-e14.json` + laporan
  `docs/benchmark/cross-implementation-differential.md`.
- **Perbandingan ini tetap baseline lokal**, bukan klaim kemenangan produk:
  fixture deterministik di localhost, satu device, dan scenario HTTP saja.
  Target nyata (TLS fingerprint, proxy, challenge dinamis) belum diukur.
- **Lengan browser belum dibandingkan**: UWAE memakai raw CDP (ADR-014),
  Botasaurus memakai driver CDP sendiri. Keduanya belum diukur di device ini,
  jadi `js_rendering_browser_arm` dicatat sebagai skenario tak didukung —
  bukan sebagai keunggulan UWAE.
- **`a05_protected` (alur sesi) belum dibandingkan**: benchmark ini
  mengukur target satu-permintaan; perbandingan alur cookie
  login→akses tetap terbuka.
