# ADR-024: Pemilihan fitur berikutnya setelah vonis korpus

## Status
Proposed (2026-10-29 — diturunkan dari evidence E16, E17, E18, E19)

Dokumen ini adalah **shortlist dan reperensi prioritas**, bukan keputusan final
terpilih. Pemilihannya masih menunggu persetujuan manusia. Tidak ada kode yang
diubah untuk memimplementasikan apa pun yang tertulis di sini.

## Context

TEXT.md:1427 mengunci urutan kerja:

> "Baru setelah itu kita memilih fitur berikutnya berdasarkan hasil pengujian."

Gerbang itu baru terbuka setelah ADR-022 (matriks vonis korpus) ada. Saat ini
korpus berdiri di atas tiga slot aktif: E18 (`http-transport`, n=30), E19
(`session-flow`, n=30), dan E16 (`browser-arm`, n=30) — 13 menang UWAE, 21 seri,
0 menang baseline, 0 belum teruji, di 34 instansi perbandingan.

Masalahnya: **kolom Priority di `docs/benchmark/competitive-matrix.md` sudah
tidak berlaku.** Matriks itu sendiri menyatakan secara terbuka:

> "The **Priority** and **Confidence** columns are retained from the Phase-0
> assessment and were not re-derived; this update re-grounds only the UWAE
> Status, Evidence and Gap Analysis columns."

Artinya, prioritas di sana berasal dari **audit source sebelum benchmark ada**,
bukan dari hasil pengujian. TEXT.md justru meminta sebaliknya. ADR-024 ini
menurunkan ulang prioritas itu dari evidence.

### Koreksi terhadap hitungan sebelumnya

Catatan sebelumnya menyebut "30 baris `Not yet verified`". Angka yang benar
adalah **29 baris**. Hitungan 30 keliru karena satu dari 30 hitungan itu
adalah definisi kosakata di tabel status, bukan baris kapabilitas.

Distribusi 29 baris itu:

| Status Botasaurus | Jumlah |
|---|---|
| `Not verified` | 27 |
| `Not verified in audit` | 1 (pagination handling) |
| `Likely (request.py)` | 1 (HTTP connection pooling) |
| **`Verified` / `Partially verified`** | **0** |

Distribusi priority lama: 6 High, 20 Medium, 3 Low.

## Temuan penggerak: tiga fakta yang mengubah cara prioritas diturunkan

### Fakta 1 — Tidak satu pun dari 29 baris itu adalah celah paritas Botasaurus

Tidak ada baris `Not yet verified` yang kolom Botasaurus-nya `Verified` atau
`Partially verified`. Pada 29 kapabilitas itu, Botasaurus juga tidak punya
apa pun yang terukur. Artinya: **bekerja melalui 29 baris itu tidak mungkin
menghasilkan satu pun "menang baseline" terhadap UWAE.** Hasil terbaik yang
mungkin adalah `Implemented` atau `Measured (vs ground truth)` — atau seri.

Yang bisa menghasilkan menang baseline cuma ada di luar 29 baris itu. Section
"Fakta 2" menjelaskan di mana.

### Fakta 2 — Celah POST ada, tapi tidak terlihat di 29 baris

Baris `HTTP GET/POST requests` berstatus UWAE `Measured (cross-impl)` — karena
GET-nya memang terukur. Namun pada kolom Gap Analysis-nya tercatat:

> "UWAE implements no POST path: the adapters expose GET, HEAD and Range only,
> while Botasaurus's request decorator supports POST."

Verifikasi langsung ke source:

| Temuan | Lokasi |
|---|---|
| Field `method` **sudah ada** di kontrak, default `"GET"` | `src/universal_web_acquisition/http_transport/contracts.py:24` |
| Adapter hanya memanggil `client.get(...)`; tidak ada jalur POST | `src/universal_web_acquisition/http_transport/adapter.py:77` |
| Fixture hanya punya `do_HEAD` dan `do_GET`; **tidak ada `do_POST`** | `src/universal_web_acquisition/benchmark/fixture_server.py:160,175` |
| Audit Botasaurus pada kapabilitas ini: **`Verified (request_decorator.py)`** | `docs/benchmark/competitive-matrix.md` |

Jadi POST adalah **satu-satunya kapabilitas di mana Botasaurus ter-audit
`Verified` dan UWAE tidak punya implementasinya** — dan ia **tidak ada di
dalam 29 baris**. Ia tersembunyi di dalam Gap Analysis sebuah baris yang
statusnya `Measured`.

Konsekuensi metodologis: **kosakata status matriks tidak bisa menyatakan
"sebagian ada"**. Satu baris `Measured (cross-impl)` bisa berarti "GET-nya
terukur" sekaligus "POST-nya tidak ada". Vocabular itu perlu ekstensi
(misalnya `Partial (cross-impl)`) atau baris pecahan — sampai itu diperbaiki,
membaca 29 baris saja akan melewatkan celah paritas satu-satunya yang ada.

### Fakta 3 — Semua kelemahan UWAE yang terukur adalah BIAYA, bukan KEMAMPUAN

Korpus mencatat 0 menang baseline di 34 instansi. Tidak ada dimensi di mana
Botasaurus menang atas UWAE. Sebaliknya, di tiga slot aktif, UWAE lebih mahal
di setiap skenario:

| Skenario (E18, n=30) | attempts UWAE | attempts Bota | median UWAE | median Bota | rasio |
|---|---|---|---|---|---|
| `b01_small_get` | 30 | 30 | 250,47 ms | 40,94 ms | 6,12x |
| `b01_large_get` | 30 | 30 | 276,64 ms | 175,18 ms | 1,58x |
| `b04_redirect` | 30 | 30 | 277,22 ms | 95,29 ms | 2,91x |
| `b06_gzip` | 30 | 30 | 264,44 ms | 39,85 ms | 6,64x |
| `b06_brotli` | 30 | 30 | 350,54 ms | 45,05 ms | 7,78x |
| `b07_js_render` | 30 | 30 | 330,48 ms | 38,25 ms | 8,64x |
| `e02_not_found` | **150** | 30 | **764,19 ms** | 38,95 ms | **19,62x** |
| `a04_login` | **150** | 30 | **712,95 ms** | 38,88 ms | **18,34x** |
| `a06_rate_limited` | 150 | 30 | 5.326,95 ms | 40,72 ms | 130,82x |
| `a07_challenge` | 30 | 30 | 234,17 ms | 37,11 ms | 6,31x |
| `a07_denied` | 30 | 30 | 233,25 ms | 40,47 ms | 5,76x |
| `a11_invalid_html` | **150** | 30 | **931,05 ms** | 50,39 ms | **18,48x** |
| `a09_large_download` | 30 | 30 | 692,85 ms | 147,53 ms | 4,70x |

Dua kelompok harus dibedakan, karena maknanya berbeda:

- **Tiga skenario dengan 150 attempt** (`e02_not_found`, `a04_login`,
  `a11_invalid_html`): UWAE membuat 5 attempt untuk mencapai diagnosis
  terminal yang sebenarnya sudah diketahui pada attempt pertama. Bukti: E18
  mencatat `observed_diagnoses: ["content_invalid"]`, `diagnosis_verified_runs:
  30/30`, `spurious_problem_runs: 0`, dan `errors: []`. E12 mengukur hal yang
  sama dari sisi lain: pada `e02_not_found` lengan `http_only`,
  `attempts=4` dengan `transports=['curl_cffi','curl_cffi','curl_cffi','curl_cffi']`
  — yaitu pengulangan permintaan yang sama, bukan eskalasi transport. Empat
  request per run terbuang, dan di situ terletak rasio latensi 18-19,6x.
- **Satu skenario `a06_rate_limited`**: 5 attempt, dan masing-masing
  menunggu `Retry-After` yang dipaksa server. Latensi 5.326,95 ms adalah
  **harga dari politeness itu**, bukan pemborosan. Botasaurus 40,72 ms karena
  tidak menghormati header itu — dan juga karena tidak punya API diagnosis.
  Kasus ini **tidak boleh** diperbaiki dengan mengurangi retry.

Piksel memori (E18, `peak_memory_bytes`): UWAE 3,04-12,67 MB, Botasaurus
0,83-4,08 MB. E16: cold start chromium 5.432 ms pada RSS 191.368 kB; median
lengan `uwae-adaptive` 3.115,66 ms, `uwae-browser-only` 5.470,35 ms,
`botasaurus-http` 83,30 ms, `botasaurus-browser` 7.200,62 ms. E19: sumbu
recovery UWAE 2.727 ms berbanding 111 ms (auto) dan 181 ms (eksplisit) pada
Botasaurus, dengan 4-5 request berbanding 1 dan 3.

## Decision: shortlist berprioritas

Peringkat di bawah **bukan** ulangannya kolom Priority lama. Di turunkan dari
evidence dengan aturan: (a) satu kapabilitas harus bisa ditutup dengan bukti
yang dapat direproduksi, dan (b) ia harus menyentuh metrik TEXT.md §9 yang
memang lemah atau belum terukur.

### Prioritas 1 — Dukungan POST (paritas kompetitif, satu-satunya yang tersisa)

Satu-satunya kapabilitas di mana Botasaurus ter-audit `Verified` dan UWAE tidak
memilikinya. Kontraknya sudah siap (`RequestSpec.method`), jadi permukaannya
tidak perlu didesain ulang. Yang dibutuhkan:

1. Jalur POST pada adapter transport (`adapter.py` dan registry-nya).
2. Skenario POST pada fixture. **`fixture_server.py` adalah modifikasi milik
   pengguna dan tidak boleh disentuh**, jadi rute ini harus hidup di modul
   fixture baru, bukan di file yang ada.
3. Slot evidence baru (mis. E20) dengan protokol adil E18: target, expected
   output, kondisi device, jumlah run, dan kriteria sukses identik untuk kedua
   arm, n=30, ground truth dari semantika protokol fixture.

Nilai informasi tertinggi di seluruh peta: **ini satu-satunya pertanyaan terbuka
yang masih memungkinkan Botasaurus menang atas UWAE.** Semua kandidat lain
hanya bisa menghasilkan seri atau status `Implemented`.

Risiko: ketergantungan pada rute fixture baru; kemungkinan ada perbedaan
semantik POST antara UWAE dan dekorator Botasaurus yang perlu diukur, bukan
diasumsikan.

### Prioritas 2 — Anggaran retry untuk diagnosis terminal (deficit biaya terukur)

Menyerang rasio latensi terbesar yang stemmed dari pilihan, bukan dari
kewajiban server: 4 request terbuang per run pada tiga skenario, dengan rasio
18,34x-19,62x dan 4-5x jumlah request ke server pihak ketiga.

Langkah yang harus dilakukan **sebelum** mengubah apa pun:

1. Baca kebijakan retry di planner dan pahami apakah attempt berulang itu
   dipakai untuk membedakan galat transien dari 404/401 asli. Kalau iya,
   pemangkasan bisa mengorbankan akurasi diagnosis. kalau tidak, itu pemborosan
   murni.
2. Re-measure 7 skenario diagnosis pada n=30 dan pertahankan angka 210 true
   positive, 0 false negative, 0 false positive. Slot baru, bukan penulisan
   ulang E18.

Risiko: touching the retry policy menyentuh perilaku produksi, dan angka
diagnosis saat ini adalah salah satu achievement terkuat UWAE. Keakuratan
diagnosis harus dipertahankan, dan itu harus dibuktikan, bukan diasumsikan.

Catatan konsistensi: kalimat matriks "content invalid is inspected instead of
retried" pada baris `Configurable retry policies by failure type` **bertentangan
dengan data mentahnya sendiri** — E12 mencatat `attempts=4` dan E18
`attempts_max=5` untuk `content_invalid`. Salah satu dari kalimat atau
datanya yang harus dikoreksi; ini adalah temuan integritas dokumentasi, bukan
sekadar beda Pending.

### Prioritas 3 — Akuntansi resource CPU dan memori di dalam engine

Menutup dua dari 29 baris (`Memory usage monitoring and limits` — priority High,
dan `CPU usage monitoring and limits`) sekaligus dua kotak acceptance criteria
Phase 1 ("CPU usage returns to near-idle levels after acquisition completion" dan
"Storage overhead for metadata is less than 20% of acquired data size").

Fakta yang memudahkan: `psutil>=5.9.0` **sudah dideklarasikan** di
`pyproject.toml:36` dan sudah terpasang (7.2.2) di interpreter Termux — tapi
**tidak pernah di-import** di mana pun dalam package. Jadi biaya dependensi
baru mendekati nol.

Nilai t Strategis: implementasi ini juga membuka dua baris lain yang saat ini
tergantung padanya — `Dynamic concurrency adjustment based on resource
availability` (High) dan `Resource usage tracking for recovery planning`.
Empat baris dari satu implementasi.

Batas yang harus jujur: Botasaurus tidak punya padanan, jadi baris-baris ini
tidak akan menghasilkan menang korpus. Nilainya pada metrik `Resource efficiency`
TEXT.md §9 dan pada Phase 1 completeness.

### Prioritas 4 — Resolusi canonical URL (paling murah dari 29 baris)

Priority High di audit lama, tidak ada di mana pun di source, dan murah:
baca `<link rel=canonical>` di `discovery/link_extractor.py` dan jadikan bagian
dari kunci deduplikasi (dedup saat ini hanya URL persis setelah fragment
dibuang).

Batas: Botasaurus tidak terukur punya ini, jadi ini **differentiator**, bukan
paritas. Tidak ada menang korpus yang bisa dihasilkan. Justifikasinya adalah
kelengkapan akuisisi pada `Verified acquisition rate`, bukan kompetisi.

### Prioritas 5 — Semantik pagination (priority High, fixture sudah siap)

Fixture **sudah** punya `/page1` (tautan ke `/page2`) dan `/page2` di
`fixture_server.py:258,272`, jadi skenario pengukurannya murah dibuat.

Tapi nuansanya penting: crawler BFS **sudah** menemukan `/page2` lewat
penyfolan tautan biasa. Yang hilang bukan kemampuan mencapai halaman kedua,
melainkan **semantik pagination** (`rel=next`, parameter cursor, deteksi nomor
halaman) dan cara menyajikan satu daftar multi-halaman sebagai satu unit.
Membangun "pagination" yang hanya menyalin perilaku BFS yang sudah ada
menyersesatkan.

### Prioritas 6 — Interception AJAX/XHR (basis sudah setengah ada)

`Network.enable` **sudah dikirim** di `browser/cdp.py:185` — jadi biaya
aktivasi browser sudah dibayar. Yang belum ada adalah mechanism
pengumpulannya: `_send` di `browser/cdp.py:147` **membuang seluruh event CDP**
("event CDP ... diabaikan") sambil menunggu id yang cocok. Mengimplementasikan
ini berarti menambahkan kolektor event sungguhan, bukan sekadar menyalakan
satu flag lagi.

Prioritiy Medium, Confidence Low di audit lama, dan Botasaurus tidak punya
padanan terukur — jadi ini differentiator murni.

### Prioritas 7 — Circuit breaker dan dead letter queue (dua baris, satu tema)

Keduanya absen (`breaker`/`dead_letter`/`requeue` tidak ada di source;
`"recovered_requeued"` di `job_repository.py:356` hanyalah label status).
Priority Medium keduanya, dan keduanya menjawab kasus "target mati di-setiap
job mengulanginya".

### Prioritas 8 — Config loader dan graceful shutdown (dua kotak Phase 1 yang bocor)

Ini **bukan** dari 29 baris matriks, tapi dua acceptance criteria Phase 1 yang
tidak punya implementasi apa pun:

- `config.json` ada di root dengan seksi `database`, `logging`, `http`, `job`,
  `storage` — tapi **tidak ada source file yang membacanya**, dan opsi CLI
  `--config` sebenarnya memilih database job SQLite, bukan profil konfigurasi.
- **Tidak ada** penanganan `SIGTERM`/graceful shutdown di seluruh `src/`.

Keduanya murah dan keduanya membuat Phase 1 benar-benar hijau, bukan
dicentang sebagian.

## Yang TIDAK seharusnya dibangun

- **Automated challenge solving** (baris 29, priority High). E12 mengukur ketiga
  lengan berakhir di `needs_user` dengan state `challenge_present` — itu
  terminal state yang benar di bawah kebijakan engine. Membangun solver akan
  menghapus jaminan terminal outcome jujur yang jadi fondasi korpus. Baris ini
  **harus tetap kosong** dan dicatat sebagai keputusan desain, bukan deficiency.
- **Multi-factor authentication support** (baris 29) dalam bentuk sekarang.
  Perilaku yang benar untuk MFA adalah `needs_user`; celah yang sebenarnya
  adalah *alur kerja interaktif* (baris `Interactive mode/wizard` dan UX
  `needs_user`), bukan engine MFA.

## Celah evidence yang harus ditutup lebih dulu

1. **Kolom Priority matriks harus diturunkan ulang** atau ditandai basi.
   Selama masih memakai priority lama, setiap daftar prioritas berakar pada
   audit source, bukan hasil pengujian — persis yang TEXT.md:1427 larang.
2. **Kosakata status matriks tidak bisa menyatakan "sebagian ada"**, sehingga
   celah POST tidak terlihat sebagai baris. Perlu ekstensi vocabular atau baris
   pecahan.
3. **Klaim "content invalid is inspected instead of retried" bertentangan dengan
   data mentah E12** (`attempts=4`, empat kali `curl_cffi`) dan E18
   (`attempts_max=5`). Salah satu harus dikoreksi.
4. **Latensi sumbu recovery E19 masih terbuka**: 1.931,1 ms pada n=5 menjadi
   2.727 ms pada n=30, sementara lengan Botasaurus justru turun sedikit
   (126,3->111,4 dan 189,7->181,4 ms). Outcome protokol identik
   (60/60 vs 0/60 vs 60/60 vs 0/60). Ini perbedaan kondisi pengukuran yang
   belum dijelaskan, **bukan** regresi yang sudah dipahami. Tidak boleh ada
   klaim latensi apa pun yang memakai angka recovery sebelum ini ditutup atau
   dinyatakan terbuka secara eksplisit.
5. **Cross-platform test compatibility** (baris 29) tidak bisa ditutup di
   perangkat ini — seluruh artefak benchmark berasal dari satu platform
   (aarch64 PRoot Linux di bawah Termux).-butuh perangkat kedua atau CI
   matrix.
6. **Tidak ada slot evidence baru yang boleh menimpa slot lama.** Setiap
   pengukuran baru = slot baru dengan `supersedes` bila memang menggantikan,
   mengikuti pola ADR-023.

## Yang TIDAK diklaim

- **Tidak diklaim UWAE unggul atas Botasaurus.** Vonis korpus tetap 13 menang
  UWAE, 21 seri, 0 menang baseline, 0 belum teruji.
- **Tidak diklaim 29 baris itu Prioritas lama sudah diganti.** Dokumen ini
  hanya proposes; matriks belum diubah.
- **Tidak diklaim mengurangi retry akan pasti memperbaiki latensi** tanpa
  membaca kebijakan retry lebih dulu, dan tanpa membuktikan ulang akurasi
  diagnosis 210/0/0.
- **Tidak diklaim biaya resource UWAE adalah defect** pada skenario yang
  menunggu Retry-After — menghormati Retry-After adalah perilaku yang benar.
- **Tidak ada klaim superiority baru yang dibuat dari dokumen ini.** Tidak ada
  benchmark yang dijalankan untuk ADR-024 ini.

## Links

- Korpus: `docs/benchmark/engine-results-e17.json`,
  `docs/benchmark/corpus-verdict-matrix.md`
- Evidence aktif: `docs/benchmark/engine-results-e16.json` (browser-arm),
  `docs/benchmark/engine-results-e18.json` (http-transport),
  `docs/benchmark/engine-results-e19.json` (session-flow)
- Evidence kebijakan retry: `docs/benchmark/engine-results-e12.json` (ADR-017)
- Matriks kapabilitas: `docs/benchmark/competitive-matrix.md`
- Roadmap Phase 1: `docs/roadmap/phase-1-implementation-plan.md`
- ADR sebelumnya: ADR-022 (matriks vonis korpus), ADR-023 (backfill n=30)
