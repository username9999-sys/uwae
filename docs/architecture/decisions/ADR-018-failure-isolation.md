# ADR-018: Failure Isolation — satu job bermasalah tidak boleh merusak yang lain

## Status
Accepted (2026-10-26 — evidence: engine-results-e13.json, benchmark_id `e5-failure-isolation-001`)

## Context

TEXT.mdcompetitive spike mendefinisikan **enam eksperimen pembeda (E1–E6)**.
Dengan E4 (ADR-017) dan E6 (ADR-016) selesai, **E5 — failure isolation**
menjadi eksperimen terakhir yang belum punya bukti:

> *"satu URL mengalami timeout atau error permanen sementara pekerjaan lain
> harus tetap selesai."*

Sebelum ini, `ConcurrentJobRunner` (jalur produksi `uwae crawl --concurrency N`)
memuat klaim di docstring-nya:

> *"kegagalan satu job TIDAK menghentikan yang lain — hasil akhir jujur per job"*

Klaim itu **tidak pernah diverifikasi oleh tes mana pun**, dan saat
dieksplorasi, **ternyata tidak berlaku universal** — hanya berlaku untuk sebagian
kegagalan.

Dua tingkat kegagalan yang berbeda:

1. **Kegagalan transport** (timeout, 404, connection error) — `JobWorker._execute_job`
   menangkapnya di dalam `try` dan memetakannya menjadi reason code; job
   gagal dengan jujur, job lain tidak tersentuh. Ini yang **sudah bekerja**.
2. **Kegagalan non-transport** (penulisan DB, artifact store di jalur sukses,
   plugin yang melempar di luar handler) — `_execute_job` hanya melindungi
   **blok transport**. Exception dari tahap lain **lolos keluar** ke
   `ConcurrentJobRunner._execute_one`, lalu `pool.map` + `list()` meneruskannya:
   **seluruh batch meledak dan SEMUA hasil hilang** — satu job merusak
   pekerjaan lain.

Jadi ENGINE-nya tidak salah; **runtime-nya** yang tidak mengisolasi. Dan
klaim di docstring lebih lebar daripada kenyataannya — persis jenis klaim
yang tidak boleh dibiarkan tanpa bukti.

## Decision

1. **Guard isolasi di `ConcurrentJobRunner._execute_one`.** Exception yang
   lolos dari worker ditangkap di titik eksekusi job, job dicatat **GAGAL
   dengan jujur** (`internal_error: <tipe>: <pesan>`), dan eksekusi job lain
   diteruskan. Guard ini berada di **runner**, bukan di worker — karena yang
   perlu dilindungi adalah *batch*, dan hanya runner yang mengenal batch.

2. **Status yang sudah diputuskan tidak ditimpa.** Guard hanya menandai
   gagal bila status job belum diputuskan (`SUCCEEDED`/`FAILED`/`CANCELED`/
   `NEEDS_USER` = sudah diputuskan). Jika akuisisi **berhasil** dan exception
   muncul sesudahnya, status tetap `SUCCEEDED` — menimpanya jadi `FAILED`
   akan menjadi kebohongan.

3. **Ground truth dinilai dari diagnosis bukti, bukan dari teks pesan.**
   Kegagalan timeout dicocokkan ke **reason code pada event assessment**
   (`timeout`), bukan ke substring `"timeout"` di pesan error curl. Pesan
   `"Timeout: ... Operation timed out ..."` adalah detail implementasi yang
   bisa berubah kapan saja; diagnosis yang benar adalah yang dijaga.
   (Kesalahan ground truth pertama: benchmark sempat gagal mencocokkan
   `"timeout"` lowercase pada pesan error — ground truth yang rapuh, bukan
   engine yang salah. Diperbaiki ke assessment reason code.)

4. **Fault injection masuk ke fixture server.** Endpoint `/hang?seconds=N`
   membuat server tidak merespons → timeout klien nyata. Endpoint ini
   deterministik dan tidak memerlukan jaringan luar.

5. **Guard dibuktikan memuat, bukan diasumsikan.** Tes
   `TestGuardIsLoadBearing` menyimulasikan runner **pra-fix** (tanpa guard)
   dan membuktikan batch benar-benar meledak (`RuntimeError`), sementara
   runner dengan guard pada skenario yang sama bertahan utuh. Tanpa tes ini,
   guard hanya akan terlihat sebagai kode yang tidak pernah diuji.

## Measured Results (evidence: engine-results-e13.json)

Empat skenario, masing-masing satu batch 12 job (11 sehat + 1 bermasalah)
pada `ConcurrentJobRunner` 4 thread. **Tingkat kesesuaian ground truth:
100% (4/4 skenario).** Batch yang meledak: **tidak ada**. Batch dengan
hasil hilang: **tidak ada**.

| Skenario | Job sehat | Job bermasalah | Diagnosis (assessment) | Batch ms | Sesuai ground truth |
|---|---|---|---|---|---|
| `healthy_only` | 11/11 sukses | — | — | 2582.6 | ya |
| `timeout_fault` | 11/11 sukses | failed | `timeout` ×3 | 8947.59 | ya |
| `permanent_error_fault` | 11/11 sukses | failed | `http_4xx` ×3 | 2909.75 | ya |
| `unexpected_exception_fault` | 11/11 sukses | failed (`internal_error`) | — (gagal sebelum klasifikasi) | 2381.53 | ya |

Tiga temuan:

1. **Isolasi pada tingkat transport sudah benar sejak awal** — timeout dan
   404 tidak pernah menghentikan job lain. Yang rusak adalah jalur
   non-transport. Mengukur E5, bukan memperbaiki kebutuhan, memisahkan keduanya:
   kemampuan yang sudah ada kini **terbukti**, kemampuan yang bocor kini
   **ditutup**.

2. **Satu URL menggantung tidak menahan batch melebihi timeout-nya.**
   Skenario `timeout_fault` selesai dalam ~8,9 s dengan timeout klien 2 s
   dan anggaran retry 1 — server menahan respons 5 s, tetapi batch tidak
   menunggu lebih lama dari yang dijanjikan. Batas waktu batch terukur,
   bukan asumsi.

3. **Diagnosis fault terbukti benar, bukan sekadar "gagal".** Timeout
   terdiagnosis `timeout` tiga kali (tiga attempt), 404 terdiagnosis
   `http_4xx` tiga kali. Yang dinilai adalah **diagnosis bukti**; job
   bermasalah tidak pernah dilaporkan sukses (tidak ada sukses palsu).

## Alternatives Considered

- **Menyuruh user handle ini** — ditolak: ini adalah kemampuan inti yang
  diklaim UWAE ("key UWAE differentiator — true failure isolation" di
  matriks kompetitif), dan klaim tanpa bukti justru **dilarang** oleh
  mandat INSTRUCTION.md.
- **Menangkap semua exception di dalam `JobWorker._execute_job`** — ditolak:
  worker tidak mengenal batch; widespread catch di worker juga menutupi
  bug. Guard di runner lebih sempit dan lebih jujur.
- **Menghapus klaim dari docstring** — ditolak: kemampuan ini memang
  bernilai dan dapat dicapai; yang salah adalah klaim tanpa implementasi
  dan tanpa bukti, bukan tujuannya.
- **Menambah circuit breaker / dead-letter queue** — ditolak untuk sekarang:
  tidak diperlukan untuk E5, dan menambah permukaan desain sebelum
  kebocoran yang nyata ditutup.

## Consequences

- `ConcurrentJobRunner._execute_one` sekarang menangkap exception per job —
  **perilaku batch berubah**: satu job yang meledak tidak lagi menghilangkan
  hasil seluruh batch. Ini perubahan yang disengaja dan terukur.
- Status terminal tidak lagi ditimpa oleh guard — dijaga oleh tes
  `test_success_is_not_overwritten_by_late_exception`.
- Endpoint fixture `/hang` baru — endpoint uji, tidak ada di jalur produksi.
- Klaim docstring runner kini **benar dan terukur** (sebelumnya lebih lebar
  dari kenyataan).
- **Nama berkas bukti**: `engine-results-e13.json` memakai slot E13 tingkat
  proyek; `benchmark_id`-nya `e5-failure-isolation-001` merujuk E5 TEXT.md.
  Perhatikan ada **dua namespace E** di proyek: `transport-results.json`
  memakai `e5-transport-differential-001` (E5 tingkat proyek) — ini bukan
  E5 TEXT.md (failure isolation). Kedua namespace berbeda dan tidak boleh
  dicampur.
- Baseline internal: **bukan** klaim mengungguli Botasaurus. Perbandingan
  lintas-implementasi **bukan** bagian ADR ini; ia diukur terpisah di
  `docs/benchmark/engine-results-e14.json` (E14) dan dicatat di ADR-019.
  KOREKSI (ADR-019): alasan lama "engine HTTP Botasaurus tidak dapat
  dieksekusi di environment ini" ternyata SALAH — itu bug pemanggilan pada
  skrip baseline proyek ini, bukan batas platform.
- 13 tes baru di `tests/test_failure_isolation.py` (termasuk uji guard
  bermuatan dan integritas bukti ter-commit).
