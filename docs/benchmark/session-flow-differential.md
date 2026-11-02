# E15 — Session-Flow Differential: UWAE vs Botasaurus

> **SUPERSEDED — digantikan oleh E19 (n=30).** Laporan ini adalah rekaman
> pengukuran n=5 dan **tetap utuh** sebagai bukti historis. Backfill §6.3
> (ADR-023) mengukur ulang dimensi yang sama dengan 30 run per sel dan
> menghasilkan slot baru, `engine-results-e19.json` (`supersedes: ["E15"]`).
> Di korpus E17, E15 berstatus `superseded` dan **tidak ikut dihitung** —
> slot aktifnya adalah E19. Proporsinya sendiri tidak berubah (15/15, 15/15,
> 5/15, 5/15 menjadi 90/90, 90/90, 30/90, 30/90), tapi jumlah run di balik
> tiap angka menjadi 6×. Bukti backfill: `docs/benchmark/engine-results-e19.json`,
> ADR-023.

Perbandingan **alur sesi** (login -> cookie -> akses resource terproteksi)
antar dua implementasi pada device yang sama, target yang sama, expected
output yang sama, jumlah run yang sama, dan kriteria sukses yang sama.

Angka di bawah DIHASILKAN dari `engine-results-e15.json` — jangan diedit manual.

| | |
|---|---|
| `benchmark_id` | `e15-session-flow-differential-001` |
| Evidence | `docs/benchmark/engine-results-e15.json` |
| Decision record | [ADR-020](../architecture/decisions/ADR-020-session-flow-differential.md) |
| Total run | 60 (3 skenario x 4 lengan x 5 run) |

**Ini pengukuran baseline, BUKAN klaim UWAE mengungguli Botasaurus.**
Pada sumbu alur eksplisit, `botasaurus-explicit` mencapai **15/15 — sama
dengan UWAE**. Detail metodologi dan keputusan di
[ADR-020](../architecture/decisions/ADR-020-session-flow-differential.md).

## Ringkasan hasil

Total 60 run: 3 skenario x 4 lengan x 5 run. **Nol runtime failure** di semua
lengan.

| Skenario | UWAE | bota-auto | bota-explicit | bota-decorator |
|---|---|---|---|---|
| `session_valid` | **5/5** | **5/5** | **5/5** | **5/5** |
| `session_required` | **5/5** | 0/5 | **5/5** | 0/5 |
| `session_expired` | **5/5** | 0/5 | **5/5** | 0/5 |
| **Total** | **15/15** | 5/15 | **15/15** | 5/15 |

### Sumbu recovery otomatis (10 run per lengan — dua skenario yang butuh recovery)

| Lengan | Kebijakan recovery | Berhasil | Rate |
|---|---|---|---|
| `uwae-engine` | `engine_generic` | **10/10** | **1.0** |
| `botasaurus-auto` | `none` | 0/10 | 0.0 |
| `botasaurus-explicit` | `written_in_arm_code` | **10/10** | **1.0** |
| `botasaurus-decorator-request` | `written_in_arm_code` | 0/10 | 0.0 |

## Tiga sumbu yang dipisah

Kegagalan recovery bisa berarti tiga hal berbeda. Benchmark ini memisahkan
ketiganya dengan empat lengan:

1. **Kapabilitas** — `botasaurus-auto` (tanpa kode recovery) menjawab: tanpa
   menulis recovery sendiri, Botasaurus **tidak** bisa melewati proteksi sesi.
   0/10.
2. **Letak kebijakan** — `botasaurus-explicit` menjawab: menulis recovery
   manual **berhasil**, 10/10. Jadi selisih UWAE vs lengan ini **bukan**
   selisih kemampuan, tapi selisih **policy generik engine vs policy per-task**.
   Botasaurus harus ditulis per-task; UWAE memusatkannya di engine.
3. **Bentuk objek** — `botasaurus-decorator-request` menjalankan **kode
   recovery yang identik** pada objek `reqs` bawaan dekorator. Hasilnya 0/10:
   login **terjadi**, tetapi cookie tidak pernah masuk ke jar objek itu.

Lengan `botasaurus-explicit` sengaja diikutsertakan agar perbandingan ini
bukan pembanding yang sengaja dibuat lemah.

## Bukti sisi server

Fixture merekam setiap request yang benar-benar diterima: method, path,
status, dan header `Cookie` di wire. "Arm mengklaim me-recovery" bukan bukti.

### `session_required` — klien tanpa cookie

| Lengan | Cookie pada request `/protected` | Total request | Login | Status akhir | Capai? |
|---|---|---|---|---|---|
| `uwae-engine` | `''`, `valid-token`, `valid-token` | 4 | 1 | **200** | ya |
| `botasaurus-auto` | `''` | 1 | 0 | 401 | tidak |
| `botasaurus-explicit` | `''`, `valid-token` | 3 | 1 | **200** | ya |
| `botasaurus-decorator-request` | `''`, `''` | 3 | 1 | 401 | tidak |

### `session_expired` — cookie lama, dicabut di sisi server

Server memutar token aktif (`valid-token` -> `valid-token-v2`), sehingga cookie
lama secara sintaksis **valid** tetapi ditolak 401 — kondisi "sesi kedaluwarsa
di server sementara klien tidak tahu".

| Lengan | Cookie pada request `/protected` | Total request | Login | Status akhir | Capai? |
|---|---|---|---|---|---|
| `uwae-engine` | `valid-token`, `valid-token`, `valid-token-v2`, `valid-token-v2` | 5 | 1 | **200** | ya |
| `botasaurus-auto` | `valid-token` | 1 | 0 | 401 | tidak |
| `botasaurus-explicit` | `valid-token`, `valid-token-v2` | 3 | 1 | **200** | ya |
| `botasaurus-decorator-request` | `valid-token`, `''` | 3 | 1 | 401 | tidak |

Perhatikan baris `botasaurus-decorator-request`: login **terjadi** (1 request
ke `/session-login`), tetapi retry-nya tetap tanpa cookie. Kegagalannya bukan
di kode recovery — kodenya jalan — melainkan di objek sesi yang dipakai.

### Temuan: laporan arm bisa menyesatkan

Lengan `botasaurus-decorator-request` melaporkan `recovery_outcome:
"recovered"` pada kedua skenario recovery, sementara `reached_protected`-nya
`false` dan status akhir 401. Arm "berhasil" menjalankan kodenya; cookie tidak
pernah sampai ke wire.

Tanpa log sisi server, metrik yang dibaca dari arm akan melaporkan pemulihan
sukses yang tidak pernah terjadi.

## Biaya request (median, server-observed)

| Skenario | UWAE | bota-auto | bota-explicit | bota-decorator |
|---|---|---|---|---|
| `session_valid` | 1 | 1 | 1 | 1 |
| `session_required` | 4 | 1 | 3 | 3 |
| `session_expired` | 5 | 1 | 3 | 3 |

UWAE membayar lebih banyak request karena ia melakukan **validasi
pascarecovery**: `detect()` memeriksa sesi yang ada, `recover()` memvalidasi
kandidat sesi, dan `validate()` memastikan sesi benar-benar mengakses resource
sebelum dikomit. Tanpa validasi itu, recovery bisa "berhasil" secara prosedural
sementara resource tetap 401 — persis cacat yang terlihat di lengan dekorator.

Perbedaan 4 vs 5 pada `session_expired`vs `session_required` berasal dari
`detect()`: bila store sudah punya sesi (walaupun stale), `detect()` memanggil
`validate()` dan memakai satu request; bila store kosong, `validate()`
mengembalikan `false` tanpa request sama sekali.

## Latensi

| Lengan | Median ms | p95 ms |
|---|---|---|
| `uwae-engine` | 1747.34 | 2165.45 |
| `botasaurus-auto` | 132.49 | 274.86 |
| `botasaurus-explicit` | 151.93 | 278.63 |
| `botasaurus-decorator-request` | 167.71 | 246.31 |

Pada n=5, p95 setara nilai maksimum sehingga **belum bermakna secara
statistik**. Semua waktu mentah ada di `elapsed_ms_runs`.

UWAE jauh lebih lambat pada skenario sesi karena menjalankan protokol pemulihan
7-fase (ACP §4) plus validasi, dan karena setiap lengan UWAE adalah **job
durable penuh** (repository, artifact, event) sementara lengan Botasaurus
adalah fungsi tunggal. Perbandingan ini **bukan** perbandingan throughput.

## Kondisi eksekusi

Identik dengan ADR-019 — mesin fairness yang sama, diimpor (bukan disalin)
dari `cross_impl_bench.py` sehingga ada **satu sumber kebenaran**.

| Aspek | Nilai |
|---|---|
| Interpreter | `/root/uwae-comparison-venv/bin/python` (CPython 3.14.4) |
| Platform | `Linux-6.17.0-PRoot-Distro-aarch64-with-glibc2.43`, aarch64 |
| botasaurus | 4.0.97 |
| botasaurus_requests | 4.0.38 |
| botasaurus_driver | 4.0.101 |
| requests / httpx / curl_cffi | 2.34.2 / 0.28.1 / 0.17.0 |
| Run per sel | 5 |
| Total run | 60 |
| Durasi benchmark | 325.19 s |

`environment.identical_conditions` menyimpan lima flag (`targets`,
`expected_outputs`, `device_conditions`, `run_counts`, `success_criteria`) —
semuanya `true` dan dapat diaudit.

## Ground truth

Diambil dari **semantika protokol fixture**, bukan dari komponen yang diuji:

```json
{
  "expect_status": 200,
  "expect_body_sha256": "0165ee188672c28bcef37a81dda166f7e14388ed7a7b29821d8d639d660bd276",
  "expect_body_bytes": 20,
  "source": "semantika protokol fixture: /protected 200 hanya bila cookie sesi aktif"
}
```

Kriteria sukses: status 200 **dan** sha256 body cocok **dan** panjang byte
cocok. Status 200 saja tidak cukup.

## Batasan

1. **Hanya cookie-sesi.** Challenge, MFA, dan login yang butuh interaksi
   manusia belum diukur. `needs_user` tetap jalur terminal yang benar untuk
   kasus itu, tapi belum dibuktikan di sini.
2. **Satu origin, satu skema cookie.** CSRF token, SameSite, dan cookie yang
   berganti nama belum diuji.
3. **n=5 per sel.** Cukup untuk melihat perbedaan besar dan konsisten
   (0/5 vs 5/5), tidak cukup untuk klaim fine-grained.
4. **Bukti platform Botasaurus hanya berlaku untuk versi yang ter-pin**
   (4.0.97 / 4.0.38 / 4.0.101).

## Yang TIDAK diklaim

- Tidak diklaim UWAE mengungguli Botasaurus. Pada sumbu alur eksplisit keduanya
  15/15.
- Tidak diklaim ini perbandingan throughput.
- Tidak ada bukti historis yang ditimpa — celah `a05_protected` di E14 ditutup
  lewat blok `correction` yang menunjuk ke sini, data mentah E14 utuh.

## Reproduksi

```bash
cd /root/universal-web-acquisition
PYTHONPATH=src python -m universal_web_acquisition.benchmark.session_diff_bench
```

Hasil ditulis ke `docs/benchmark/engine-results-e15.json`.
