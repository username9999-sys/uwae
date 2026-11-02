# ADR-020: Session-flow differential — mengukur alur sesi UWAE vs Botasaurus pada device yang sama

## Status
Accepted (2026-10-27 — evidence: engine-results-e15.json, benchmark_id `e15-session-flow-differential-001`)

## Context

ADR-019 membuat perbandingan lintas-implementasi **mungkin** terjadi, tetapi
mengukur target satu-permintaan. Steady-state itu tidak menjawab pertanyaan
INSTRUCTION.md §9 (gate G5):

> *"Apakah pemulihan sesi berhasil pada fixture yang mendukungnya?"*

dan meninggalkan celah yang **dideklarasikan sendiri** oleh bukti E14:

```json
{
  "scenario_id": "a05_protected",
  "reason": "memerlukan alur sesi terautentikasi (cookie login -> akses); benchmark ini mengukur target satu-permintaan. Perbandingan alur sesi belum diukur.",
  "supported_by": []
}
```

E15 menutup celah itu. Skenari `a05_protected` diukur sebagai **alur** —
login, cookie, akses resource terproteksi — bukan sebagai satu request.

### Dua kesalahan yang harus dihindari

1. **Strawman baseline.** TEXT.md melarang perbandingan dengan "implementasi
   pembanding yang sengaja dibuat lemah". Botasaurus pasti bisa menulis kode
   recovery sendiri; membandingkannya dengan UWAE yang *tidak* melakukan itu
   sama sekali akan mengukur apa yang *tidak* ditulis, bukan kemampuan.
2. **Self-report sebagai bukti.** "Arm mengklaim me-recovery" bukan bukti.
   Yang bukti adalah log sisi server: request apa yang benar-benar diterima
   dan cookie apa yang benar-benar ada di wire.

## Decision

### 1. Empat lengan, tiga sumbu ortogonal

| Lengan | Objek sesi | Kebijakan recovery |_sumbu_ |
|---|---|---|---|
| `uwae-engine` | `SessionStore` UWAE | `engine_generic` (planner) | arsitektur |
| `botasaurus-auto` | `Session()` eksplisit | `none` | kapabilitas |
| `botasaurus-explicit` | `Session()` eksplisit | `written_in_arm_code` | letak kebijakan |
| `botasaurus-decorator-request` | `reqs` dari dekorator | `written_in_arm_code` | bentuk objek |

Tiga sumbu yang dipisah:

- **Kapabilitas** — apakah recovery mungkin sama sekali? (`botasaurus-auto`
  menjawab: tanpa kode recovery, tidak.)
- **Letak kebijakan** — apakah policy generik engine cukup, atau harus ditulis
  per-task? (`botasaurus-explicit` menjawab: menulisnya manual berhasil.)
- **Bentuk objek** — apakah objek sesi yang berbeda mengubah hasilnya?
  (`botasaurus-decorator-request` menjawab: ya, dan itu temuan platform.)

### 2. Baseline diberi bentuk terkuat Botasaurus

Ini koreksi langsung terhadap probe yang menemukan cacat fairness di rancangan
pertama: rancangan awal memakai objek `reqs` yang diberikan dekorator. Probe
mengukur bahwa objek itu **tidak menyimpan cookie** — sehingga baseline akan
tampak "tidak punya sesi", sebuah **artefak objek, bukan batas platform**.

Bandung objektifnya (terukur, bukan asumsi):

| Objek | Cookie bertahan antar-call? |
|---|---|
| `botasaurus_requests.Session()` | **YA** — `RequestsCookieJar` asli |
| `botasaurus_requests.Request()` (diberikan dekorator) | **TIDAK** — tiap call membuat sesi sementara |

Maka:

- `botasaurus-auto` dan `botasaurus-explicit` memakai `Session()` eksplisit,
  `headers={}` (menghindari `KeyError('headers')` dari ADR-019), dan
  **bergantung pada cookie jar** — cookie diambil otomatis, tidak di-parse
  manual dari header `Set-Cookie`.
- `botasaurus-decorator-request` menjalankan **kode recovery yang identik**
  pada objek `reqs` bawaan dekorator. Lengan ini ada untuk dua hal:
  membuktikan baseline diberi bentuk terkuat yang Botasaurus tawarkan, dan
  mengkomit temuan perilaku cookie objek dekorator sebagai bukti.

### 3. Bukti sisi server, bukan laporan arm

Fixture merekam setiap request yang benar-benar diterima: method, path,
status, dan header `Cookie` yang ada di wire. Armed recovery UWAE yang
berhasil terlihat sebagai: satu request login, lalu request `/protected` dengan
cookie baru dan status 200.

Fixture juga memeriksa **dengan benar** bahwa `botasaurus-decorator-request`
tidak mengirim cookie pada retry-nya — bukan karena arm gagal menulis kode,
tetapi karena cookie tidak pernah masuk ke jar objek itu.

### 4. Sesi dicabut di sisi server, bukan hanya di sisi klien

Skenario `session_expired` tidak memakai cookie berbentuk acak. Server
memutar token aktif (`valid-token` -> `valid-token-v2`), sehingga klien yang
masih memegang cookie lama **secara sintaksis valid** tetap mendapat 401.
Ini persis kondisi "sesi kedaluwarsa di server sementara klien tidak tahu",
dan hanya bisa diuji bila pencabutan terjadi di sisi server.

### 5. Metrik yang comparable

`arm_reported_attempts` **tidak boleh dibandingkan antar-lengan**: UWAE
menghitung attempt job di repository, sedangkan lengan Botasaurus menghitung
pemanggilan HTTP di dalam arm — satuan berbeda. Metrik request yang comparable
adalah `server_observed.total_requests`, dihitung dari log server untuk semua
lengan dengan definisi yang sama.

### 6. State sesi direset sebelum tiap run

State sesi fixture bersifat global di sisi server. Sebelum tiap run, server
dikembalikan ke kondisi awal (`reset_session()`), dan log request dikosongkan.
Tanpa ini, lengan pertama yang me-recovery akan mewarisi token milik lengan
sebelumnya — lengan yang "menang" bukan karena lebih baik, tetapi karena
lebih dulu.

## Results (dari engine-results-e15.json)

Total 60 run: 3 skenario x 4 lengan x 5 run. Nol runtime failure di semua
lengan.

### Sumbu utama: mencapai resource terproteksi

| Skenario | UWAE | bota-auto | bota-explicit | bota-decorator |
|---|---|---|---|---|
| `session_valid` | **5/5** | **5/5** | **5/5** | **5/5** |
| `session_required` | **5/5** | 0/5 | **5/5** | 0/5 |
| `session_expired` | **5/5** | 0/5 | **5/5** | 0/5 |
| **Total** | **15/15** | 5/15 | **15/15** | 5/15 |

### Sumbu recovery otomatis (hanya skenario yang butuh recovery, 10 run/lengan)

| Lengan | Kebijakan | Berhasil | Rate |
|---|---|---|---|
| `uwae-engine` | `engine_generic` | **10/10** | **1.0** |
| `botasaurus-auto` | `none` | 0/10 | 0.0 |
| `botasaurus-explicit` | `written_in_arm_code` | **10/10** | **1.0** |
| `botasaurus-decorator-request` | `written_in_arm_code` | 0/10 | 0.0 |

### Bukti sisi server — jejak cookie run 0

`session_required` (klien tanpa cookie):

| Lengan | Cookie pada request `/protected` | Request | Login | Status akhir |
|---|---|---|---|---|
| `uwae-engine` | `''`, `valid-token`, `valid-token` | 4 | 1 | **200** |
| `botasaurus-auto` | `''` | 1 | 0 | 401 |
| `botasaurus-explicit` | `''`, `valid-token` | 3 | 1 | **200** |
| `botasaurus-decorator-request` | `''`, `''` | 3 | 1 | 401 |

`session_expired` (cookie lama, dicabut di server):

| Lengan | Cookie pada request `/protected` | Request | Login | Status akhir |
|---|---|---|---|---|
| `uwae-engine` | `valid-token`, `valid-token`, `valid-token-v2`, `valid-token-v2` | 5 | 1 | **200** |
| `botasaurus-auto` | `valid-token` | 1 | 0 | 401 |
| `botasaurus-explicit` | `valid-token`, `valid-token-v2` | 3 | 1 | **200** |
| `botasaurus-decorator-request` | `valid-token`, `''` | 3 | 1 | 401 |

Perhatikan `botasaurus-decorator-request`: login **terjadi** (1 request),
tetapi retry-nya tetap tanpa cookie — bukti bahwa cookie tidak pernah masuk
ke jar objek dekorator.

### Temuan: laporan arm bisa menyesatkan

Lengan `botasaurus-decorator-request` melaporkan `recovery_outcome:
"recovered"` pada kedua skenario recovery — **sementara** `reached_protected`
-nya `false` dan status akhir 401. Arm tersebut "berhasil" menjalankan
kodenya; cookie tidak pernah sampai ke wire.

Ini bukti langsung mengapa keputusan §3 diambil: tanpa log sisi server,
metrik yang dibaca dari arm akan melaporkan pemulihan sukses yang tidak pernah
terjadi.

### Biaya request (median, server-observed)

| Skenario | UWAE | bota-auto | bota-explicit | bota-decorator |
|---|---|---|---|---|
| `session_valid` | 1 | 1 | 1 | 1 |
| `session_required` | 4 | 1 | 3 | 3 |
| `session_expired` | 5 | 1 | 3 | 3 |

UWAE membayar lebih banyak request karena ia melakukan **validasi pascarecovery**
sebelum memakai sesi — `detect()` memeriksa sesi yang ada, `recover()` memvalidasi
kandidat sesi, dan `validate()` memastikan sesi benar-benar mengakses resource
sebelum dikomit. Motifnya bukan pemborosan: tanpa validasi, recovery bisa
"berhasil" secara prosedural sementara resource tetap 401 — persis cacat yang
terlihat di lengan dekorator.

### Latensi

Median seluruh run (ms): UWAE 1747.34, bota-auto 132.49, bota-explicit
151.93, bota-decorator 167.71. p95: 2165.45 / 274.86 / 278.63 / 246.31.

UWAE jauh lebih lambat pada skenario sesi karena menjalankan protokol pemulihan
7-fase (ACP §4) plus validasi, dan karena setiap lengan UWAE adalah job
durable penuh (repository, artifact, event) sementara lengan Botasaurus adalah
fungsi tunggal. Pada n=5, p95 setara nilai maksimum sehingga **belum bermakna
secara statistik**.

## Consequences

### Positif

1. **Celah `a05_protected` tertutup.** Pertanyaan gate G5 INSTRUCTION.md §9
   dijawab dengan bukti: pemulihan sesi **berhasil** pada fixture yang
   mendukungnya — UWAE 10/10 pada dua skenario yang butuh recovery.
2. **Tidak ada klaim keunggulan yang dipalsukan.** `botasaurus-explicit`
   mencapai 15/15 — sama dengan UWAE. Perbedakannya bukan kemampuan, tapi
   **letak kebijakan**: UWAE memusatkan recovery di engine generik,
   Botasaurus harus ditulis per-task.
3. **Temuan platform Botasaurus terkomit** — objek `Request` dari dekorator
   tidak menyimpan cookie — sebagai bukti, bukan asumsi.
4. **Baseline terbukti tidak dilemahkan.** Empat lengan, tiga sumbu ortogonal,
   bentuk objek terkuat dipakai untuk baseline utama.

### Negatif / batasan

1. **Fixture hanya menguji cookie-sesi**, bukan challenge, MFA, atau login
   yang butuh interaksi manusia. `needs_user` tetap jalur yang benar untuk
   kasus itu, tapi **belum diukur** di sini.
2. **Hanya satu origin, satu skema cookie.** Bentuk challenge (CSRF token,
   SameSite, cookie berganti nama) belum diuji.
3. **n=5 per sel.** Cukup untuk melihat perbedaan yang besar dan konsisten
   (0/5 vs 5/5), **tidak** cukup untuk klaim statistik fine-grained, terutama
   p95.
4. **Selisih latensi tidak boleh dibaca sebagai beban-manifest.** UWAE
   menjalankan job durable penuh; perbandingan ini bukan perbandingan
   throughput.

### Tidak diklaim

- Tidak diklaim UWAE mengungguli Botasaurus. Pada sumbu alur eksplisit keduanya
  15/15.
- Tidak diklaim klaim runtime langsung atas Botasaurus di luar device ini.
- Tidak ada scenari yang dihapus dari bukti E14 — blok `correction` ditambahkan,
  data historis tidak ditimpa (preseden ADR-018/ADR-019).

## Links

- Evidence: `docs/benchmark/engine-results-e15.json`
- Laporan: `docs/benchmark/session-flow-differential.md`
- Harness: `src/universal_web_acquisition/benchmark/session_diff_bench.py`
- ADR sebelumnya: ADR-011 (transport registry), ADR-013 (planner),
  ADR-014 (raw CDP), ADR-016 (bounded concurrency), ADR-019 (cross-impl)
