# E14 — Cross-Implementation Differential: UWAE vs Botasaurus

> **SUPERSEDED — digantikan oleh E18 (n=30).** Laporan ini adalah rekaman
> pengukuran n=5 dan **tetap utuh** sebagai bukti historis. Backfill §6.3
> (ADR-023) mengukur ulang dimensi yang sama dengan 30 run per sel dan
> menghasilkan slot baru, `engine-results-e18.json` (`supersedes: ["E14"]`).
> Di korpus E17, E14 berstatus `superseded` dan **tidak ikut dihitung** —
> slot aktifnya adalah E18. Proporsinya sendiri tidak berubah (65/65 vs 30/65
> menjadi 390/390 vs 180/390), tapi jumlah run di balik tiap angka menjadi 6×.
> Laporan backfill: `docs/benchmark/engine-results-e18.json`, ADR-023.

Perbandingan dua implementasi pada device yang sama, target yang sama,
expected output yang sama, jumlah run yang sama, dan kriteria sukses yang sama.

Angka di bawah DIHASILKAN dari `engine-results-e14.json` — jangan diedit manual.

**Ini pengukuran baseline, BUKAN klaim UWAE mengungguli Botasaurus.**
Koreksi penting: klaim lama "engine HTTP Botasaurus tidak dapat dieksekusi di
PRoot aarch64" **terbukti SALAH** — penyebabnya bug pemanggilan pada skrip
baseline milik proyek ini (`botasaurus_requests.get(url)` tanpa header ->
`KeyError('headers')`), bukan ketidakcocokan platform. Detail di
[ADR-019](../architecture/decisions/ADR-019-cross-implementation-differential.md).

## Hasil utama

| Metrik | UWAE | Botasaurus |
|---|---|---|
| Primary success (kriteria per skenario) | **65 / 65** | **30 / 65** |
| Byte terverifikasi (akuisisi saja) | 45 / 65 | **65 / 65** |
| Diagnosis penyebab — TP / FN / FP | **35 / 0 / 0** | 0 / 35 / 0 |
| Diagnosis penyebab — precision / recall / F1 | **1.0 / 1.0 / 1.0** | 0.0 / 0.0 / 0.0 |
| False-problem rate (30 run skenario sehat) | 0 / 30 (0.0) | 0 / 30 (0.0) |
| Runtime failure | tidak ada | tidak ada |
| DNS failure — outcome terminal | **3 / 3** | 0 / 3 (3/3 timeout) |
| DNS failure — diagnosis terklasifikasi | **3 / 3** | 0 / 3 |
| DNS failure — siklus retry observed | 0 / 0 / 0 | **5 / 5 / 5** (tanpa batas) |

Selisih primary success berada **seluruhnya** pada tujuh skenario penyebab —
titik di mana kriteria adalah diagnosis. Enam skenario sehat bernilai 5/5 di
kedua arm. Botasaurus **tidak punya API diagnosis sama sekali**; itu celah
kemampuan yang diukur, bukan pembanding yang sengaja dilemahkan.

## Hasil per skenario

Kriteria `akuisisi` = status + body byte-for-byte. Kriteria `diagnosis` =
label penyebab yang tepat (label diambil dari semantika fixture).

| Skenario | Kriteria | Status | UWAE ok | Bota ok | UWAE med ms | Bota med ms | UWAE p95 ms | Bota p95 ms | Mem U/B (MB) | Attempt U/B | Diagnosis UWAE |
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

Keterangan kolom:

- **med ms / p95 ms** — median dan p95 waktu elapsed per run (ms). p95 memakai
  nearest-rank; pada n=5 p95 setara nilai maksimum, sehingga **belum bermakna
  secara statistik**. Semua waktu mentah ada di `elapsed_ms_runs`.
- **Mem U/B** — peak alokasi Python (`tracemalloc`); buffer C tidak dihitung.
  Batasan yang sama dipakai benchmark transport E5.
- **Attempt U/B** — jumlah attempt maksimum pada skenario tersebut.

## Kegagalan DNS — boundedness

Target `https://nonexistent-uwae-e14-test.invalid`, jendela observasi 90 s,
3 run per arm.

| Arm | Outcome terminal | Diagnosis | Attempt | Siklus retry | Elapsed (s) |
|---|---|---|---|---|---|
| UWAE | 3/3 (`failed`) | 3/3 `network_failure` / `dns_failure` -> `budget_exhausted` | 7 / 7 / 7 | 0 / 0 / 0 | 16.976 / 21.106 / 17.135 |
| Botasaurus | 0/3 (3/3 timeout) | 0/3 | — | 5 / 5 / 5 | 90.05 / 90.04 / 90.03 |

Pesan resolver yang teramati di device ini:

```
dial tcp: lookup nonexistent-uwae-e14-test.invalid on 8.8.8.8:53: no such host
```

`retry_on_network_error` Botasaurus (`while True` + `sleep(20)`, gate pada
`'dial tcp: lookup'` **dan** `'no such host'`) memicu loop tersebut. Karena
pencocokan bersifat **literal atas teks**, client yang menghasilkan pesan lain
(mis. `Temporary failure in name resolution`) tidak akan memicu loop itu —
hasil di atas adalah yang terukur di device ini, bukan jaminan universal.

UWAE selalu berakhir terminal: 7 attempt (curl_cffi -> httpx -> requests),
anggaran retry habis, diagnosis terklasifikasi.

## Skenario yang tidak dibandingkan

| Skenario | Alasan |
|---|---|
| `a05_protected` | Memerlukan alur sesi terautentikasi (cookie login -> akses). Benchmark ini mengukur target satu-permintaan; perbandingan alur sesi belum diukur. |
| `js_rendering_browser_arm` | Kedua arm di benchmark ini adalah arm HTTP. Rendering JS butuh arm browser: UWAE memakai raw CDP (ADR-014), Botasaurus memakai driver CDP sendiri — keduanya belum diukur di device ini. |

## Metodologi

- **Dua arm, satu interpreter.** UWAE (JobWorker + transport registry +
  classifier + planner + artifact store) dan Botasaurus `@request` dijalankan
  sebagai subprocess dari **interpreter yang sama** (`/root/uwae-comparison-venv/bin/python`,
  CPython 3.14.4, `Linux-6.17.0-PRoot-Distro-aarch64-with-glibc2.43`, aarch64)
  dengan **PYTHONPATH yang sama**
  (`/root/botasaurus-venv/lib/python3.14/site-packages:<repo>/src`). Tidak ada
  perbedaan libc atau versi paket antar arm.
- **Satu fixture server** deterministik (`benchmark/fixture_server.py`) melayani
  kedua arm; koneksi baru setiap run.
- **5 run per (arm, skenario)** — 13 skenario x 2 arm = 130 run.
- **Ground truth dari semantika protokol fixture**, bukan dari output engine.
  Tujuh skenario penyebab punya label yang dikunci di harness dan diverifikasi
  ke marker body fixture (`type="password"`, "just a moment", "rate limited",
  "access denied", "please enable javascript").
- **Tiga sumbu metrik terpisah** — akuisisi (status + sha256 + panjang body),
  diagnosis penyebab, dan false-problem rate. Engine tanpa API diagnosis tidak
  diberi kredit maupun tuduhan pada sumbu diagnosis.
- **RetryPolicy UWAE** dipakai **apa adanya** (default), tidak disetel ulang,
  agar yang diukur adalah perilaku produksi.
- **Baseline Botasaurus** memakai default `@request`, kecuali tiga opsi yang
  disebut eksplisit agar tidak ada output interaktif: `output=None`,
  `create_error_logs=False`, `close_on_crash=True`; `raise_exception=False`
  dipakai agar kegagalan menjadi nilai yang tercatat, bukan exception yang
  menenggelamkan seluruh batch.

Versi paket yang dipakai bersama: botasaurus 4.0.97, botasaurus_requests
4.0.38, botasaurus_driver 4.0.101, requests 2.34.2, httpx 0.28.1,
curl_cffi 0.17.0, joblib 1.6.0, brotli 1.2.0, certifi 2026.7.22. Source commit
Botasaurus ter-pin `6c9260de12d71b9dc0c3b3a019d2698a9af38433`.

## Batasan

- **Benchmark lokal.** Fixture deterministik di localhost pada satu device.
  Target nyata (TLS fingerprint, proxy, challenge dinamis, latency jaringan)
  belum diukur — selisih latency localhost hampir pasti tidak mewakili
  selisih di internet.
- **UWAE lebih lambat dan lebih boros di localhost.** Median 137-4618 ms vs
  20-105 ms; peak memory 12.1-21.6 MB vs 0.44-3.15 MB. Penyebabnya siklus ACP
  penuh (SQLite job/attempt/event, persistensi artifact, overhead
  `asyncio.run`). Dilaporkan apa adanya.
- **UWAE tidak menyimpan artifact untuk respons 4xx/5xx.** Kode itu adalah
  diagnosis, bukan konten target. Karena itu byte terverifikasi UWAE 45/65,
  sementara Botasaurus mengembalikan body apa adanya (65/65). Kedua angka
  benar pada sumbunya.
- **Arm HTTP saja.** Perbandingan browser (raw CDP vs driver CDP Botasaurus)
  belum diukur.
- **Tidak ada klaim kemenangan produk.** Ini baseline yang dapat direproduksi,
  dengan syarat INSTRUCTION.md: target, expected output, kondisi device,
  jumlah run, dan kriteria sukses identik untuk kedua arm.
