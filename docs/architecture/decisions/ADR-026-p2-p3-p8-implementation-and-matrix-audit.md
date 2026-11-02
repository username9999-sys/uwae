# ADR-026: P2 retry budget per ReasonCode, P3 akuntansi memori per job, P8 config loader + graceful shutdown, dan audit matriks kompetitif

## Status
Accepted (2026-10-30 — evidence: tests/test_retry_budget.py 14 passed, tests/test_config_loader.py 32 passed, docs/benchmark/competitive-matrix.md audited)

## Konteks
ADR-024 menyusun shortlist fitur berdasarkan hasil pengukuran, bukan berdasarkan kolom Priority Phase-0 yang sudah usang oleh pengakuannya sendiri. Dari shortlist itu, empat item dikerjakan pada sesi ini:

- **P2** — anggaran retry diagnosis terminal: retry yang ada (`max_retries`) bersifat global per job, tidak per penyebab. Satu job bisa menghabiskan seluruh anggaran pada satu `ReasonCode` sementara penyebab lain masih punya sisa.
- **P3** — akuntansi CPU + memori per job: angka memori hanya ada di harness benchmark (peak alokasi per run), tidak ada di engine, sehingga tidak dapat dibaca oleh keputusan pemulihan.
- **P8** — config loader + graceful shutdown: tidak ada loader konfigurasi terpusat (tidak ada file sumber yang membaca `config.json`), dan tidak ada penanganan sinyal untuk mode daemon.
- **Audit** — matriks kompetitif diverifikasi terhadap bukti yang benar-benar ada di repo.

## Keputusan

### P2 — retry budget per ReasonCode
`Job` membawa `retry_budget: Optional[Dict[str, int]]` (key = `ReasonCode.value`), dengan helper `init_retry_budget`/`consume_retry_budget`/`get_retry_budget`. Planner memakainya lewat `PlannerContext.retry_budget`; `None` berarti jatuh kembali ke `retry_policy.max_retries` (perilaku lama tetap utuh). Worker mengurangi budget setiap siklus non-terminal dan memberi peringatan bila planner memilih aksi non-terminal padahal budget sudah habis. Budget diserialisasi sebagai JSON di kolom baru `jobs.retry_budget`.

### P3 — akuntansi memori per job
`_execute_job` sekarang pembungkus tracemalloc: `start()`, panggil `_execute_job_inner`, `finally` mengambil peak dan menyimpannya ke `job.peak_memory_bytes` lalu `stop()`. Kolom `jobs.peak_memory_bytes` menampungnya.

**Bug yang ditemukan dan diperbaiki selama pengerjaan ini** (dicatat karena pelajarannya tidak terlihat dari kode): versi pertama menaruh `tracemalloc.stop()` SESUDAH `while True`, padahal setiap jalur terminal keluar dengan `return` DI DALAM loop — ACCEPT, ABORT, dan NEEDS_USER. Akibatnya baris itu tak pernah dieksekusi: tracing menyala sampai proses mati, dan `peak_memory_bytes` selalu `None`. Gejalanya hanya muncul di suite penuh: `test_browser_cdp.py` lulus 13/13 sendirian tetapi gagal saat suite penuh, tepat setelah test yang menjalankan worker. Dua tes regresi ditambahkan (`test_peak_memory_is_recorded_even_when_the_job_fails`, `test_tracemalloc_is_stopped_after_execution`) — yang kedua berjalan pada jalur GAGAL, karena di situlah bug versi pertama bersembunyi.

### P8 — config loader + graceful shutdown
`src/universal_web_acquisition/config/loader.py` memakai plain pydantic `BaseModel`, BUKAN `pydantic_settings`: dependensi itu tidak terpasang di device ini, dan menambah dependensi baru hanya untuk membaca env var sendiri adalah solusi yang lebih berat daripada menulis loader eksplisit. Urutan override: defaults → YAML (`--config`) → env var (`UWAE_*`) → flag CLI. Bentuk env var yang dikenal: flat top-level (`UWAE_LOG_LEVEL`), flat ber-prefix section (`UWAE_TRANSPORT_TIMEOUT_SECONDS`), dan nested eksplisit (`UWAE__transport__timeout_seconds`).

`src/universal_web_acquisition/config/shutdown.py` menangani SIGTERM/SIGINT dengan `ShutdownManager`, plus perintah CLI `uwae serve` (daemon: klaim atomik job QUEUED lewat `UPDATE ... WHERE status = 'queued'`, pemulihan job terputus saat start) dan `uwae shutdown <pid>`.

**Bug yang ditemukan dan diperbaiki**: `setup_logging` versi pertama memasang handler di ROOT logger dan menulis ke STDOUT. Itu menghancurkan kontrak `--json`: 12 test CLI runtuh karena satu baris log muncul sebelum JSON. Handler sekarang hanya pada logger `universal_web_acquisition`, ke STDERR, dan propagasi dimatikan. Selain itu, `setup_logging` dikeluarkan dari level `cli()` group: memanggilnya di sana mengubah logging global untuk setiap perintah, padahal hanya `serve` yang memang long-running.

### Audit matriks kompetitif
Lima temuan, semuanya diperbaiki di tempat:

1. Header masih memuat total lama — **13 wins / 21 ties / 34 instans** — padahal regenerasi korpus dengan E20 menghasilkan **13 / 25 / 38**. Header dan baris "Benchmark suite with ground truth" kini konsisten dengan `engine-results-e17.json`.
2. Baris "Memory usage monitoring and limits" masih `Not yet verified` dengan teks "no runtime memory accounting" — P3 membuatnya faktual salah.
3. Baris "Resource usage tracking for recovery planning" — salah secara berturut-turut: `Source scan 2026-10-28: no resource accounting in src/universal_web_acquisition/`.
4. Baris "Configuration profiles" masih menulis "no configuration loader in `src/universal_web_acquisition/`" — P8 membuatnya salah; status `Not yet verification` TETAP benar untuk profil bernama, jadi hanya teks dan Evidence yang dikoreksi.
5. Daftar evidence header belum memuat E20 dan rentang ADR masih "ADR-001 through ADR-023".

Verifikasi terpisah: ke-16 path `docs/benchmark/*.json` yang dikutip matriks semuanya ADA di disk.

## Apa yang TIDAK diklaim
- **Tidak ada klaim bahwa P2/P3/P8 mengungguli Botasaurus.** Ketiganya `Implemented`, bukan `Measured (cross-impl)`: ada kode, ada tes, TIDAK ada benchmark lintas-implementasi. Slot benchmark baru tidak dibuat untuk ketiganya, jadi tidak ada angka yang bisa dibandingkan.
- **Tidak ada klaim "celah P2/P3/P8 tertutup".** ADR-024 menutup hanya celah paritas POST (E20). P2/P3/P8 adalah perbaikan internal yang tidak mengubah vonis korpus.
- **Angka komparatif memori tetap berasal dari harness E18** (3,04–12,67 MB UWAE vs 0,83–4,07 MB Botasaurus). P3 menambah sinyal di dalam engine, bukan mengubah angka itu.
- **Tidak ada klaim jitter, circuit breaker, dead-letter queue, batas memori, atau profil dev/staging/prod.** Semuanya tetap `Not yet verified`.

## Yang tidak dapat dikerjakan — KOREKSI
Versi pertama bagian ini menyatakan bahwa TEXT.md tidak memiliki §9 dan karena itu "tabel 10 metrik §9 tidak dapat dibangun". **Klaim itu SALAH**, dan berikut koreksinya supaya pencatatan sesi ini tidak menyesatkan pembaca berikutnya.

- **Yang benar:** TEXT.md memang memiliki §9. Berjudul *"Gerbang keputusan sebelum kita mengklaim ada kemajuan kompetitif"* di baris **2344**. Isinya **tujuh pertanyaan**, bukan 10 metrik (corpus pun memakainya sebagai "gerbang TEXT.md §9 #7" untuk pertanyaan ketujuh — "Di skenario mana mesin baru mengungguli baseline, sama, atau justru gagal?").
- **Kenapa saya salah:** pencarian pertama hanya mencocokkan heading Markdown (`^## `), sedangkan TEXT.md menggunakan penomoran inline dalam narasi percakapan. Match kosong berarti "format tidak ditemukan", bukan "seksi tidak ada" — dan saya mengartikannya sebagai yang kedua.
- **Yang dikerjakan sebagai ganti:** ketujuh pertanyaan gerbang dijawab satu per satu dengan merujuk evidence yang sudah terpublikasi, di `docs/benchmark/text-9-gate-status.md`. Dijawab berdasarkan evidence yang ada, bukan berdasarkan keyakinan.
- **Pelajaran untuk pencarian berikutnya:** cek dulu format penomoran README/domain sebelum menyimpulkan "tidak ada".

## Positif
- Budget retry per penyebab membuat planner dapat membedakan "anggaran untuk TIMEOUT habis" dari "anggaran untuk HTTP_429 habis" — sebelumnya keduanya menyatu.
- Peak memori per job kini bertahan lintas proses, sehingga dapat dibaca oleh proses lain tanpa menjalankan benchmark.
- Config loader memberi satu sumber kebenaran dan urutan override yang dapat diuji.
- Audit menemukan lima klaim dokumentasi yang tidak lagi didukung kenyataan dan memperbaikinya di tempat.

## Negatif-batasan
- Worker kini menyimpan job DUA kali per eksekusi (sekali di jalur terminal, sekali di `finally` untuk membawa peak memori). Simpanan kedua idempoten (`INSERT OR REPLACE`), tapi tetap satu penulisan ekstra.
- Budget per-reason memakai key string (`ReasonCode.value`), jadi penambahan `ReasonCode` baru tidak otomatis mendapat budget — pemanggil harus `init_retry_budget` ulang.
- Config loader membaca `uwae.yaml`, bukan `config.json` yang sudah ada di root repo; keduanya hidup berdampingan tanpa yang satu membaca yang lain.

## Link
- Tes P2/P3: `tests/test_retry_budget.py`
- Tes P8: `tests/test_config_loader.py`
- Modul P8: `src/universal_web_acquisition/config/loader.py`, `src/universal_web_acquisition/config/shutdown.py`
- Matriks yang diaudit: `docs/benchmark/competitive-matrix.md`
- Shortlist asal: ADR-024
- Evidence POST/E20: `docs/benchmark/engine-results-e20.json` (ADR-025)
