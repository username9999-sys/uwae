# ADR-023: Backfill jumlah run ke n=30 (§6.3) — slot E18/E19 menggantikan E14/E15

## Status
Accepted (2026-10-29 — evidence: engine-results-e18.json, engine-results-e19.json)

## Context

ADR-022 merangkum seluruh benchmark lintas-implementasi UWAE vs Botasaurus
jadi satu matriks korpus, dan mencatat satu batasan secara terbuka:

> **E14 dan E15 masih n=5.** Vonis korpus untuk `http-transport` dan
> `session-flow` dihitung dari 5 run per sel. E16 (n=30) sudah memenuhi
> §6.3; dua slot lain belum — dan matriks korpus tidak mengubah itu.

TEXT.md §6.3 menetapkan ambang **minimal 30 pengulangan** untuk setiap
benchmark yang dipakai jadi dasar keputusan. Dua dimensi korpus — transport
HTTP dan alur sesi — belum memenuhi ambang itu, jadi vonis yang mereka
sumbangkan ke korpus berasal dari pengulangan yang terlalu sedikit untuk
dijadikan dasar keputusan yang layak.

Yang **tidak** boleh dilakukan: menaikkan angka `runs` di harness dan
menganggap evidence lama jadi n=30. Evidence E14/E15 adalah rekaman 5 run
yang benar-benar dijalankan; menulisnya ulang seolah-olah 30 run terjadi
akan memalsukan bukti historis.

## Decision

### 1. Backfill membuat slot BARU, bukan menulis ulang slot lama

| Slot | Dimensi | n | Status |
|---|---|---|---|
| E14 | http-transport | 5 | superseded oleh E18 |
| E18 | http-transport | 30 | **aktif** |
| E15 | session-flow | 5 | superseded oleh E19 |
| E19 | session-flow | 30 | **aktif** |
| E16 | browser-arm | 30 | **aktif** (tidak berubah) |

Evidence lama **tidak ditimpa**. File `engine-results-e14.json` dan
`engine-results-e15.json` tetap utuh sebagai rekaman historis n=5, dengan
isi yang persis seperti sebelumnya. Yang berubah adalah **slot mana yang
dihitung** — dan itu dinyatakan eksplisit di dalam file evidence baru
(bukan di dalam aggregator), supaya sumber kebenaran ikut travels bersama
buktinya.

### 2. Supersession dideklarasikan di dalam evidence

Field `supersedes` pada `engine-results-e18.json` bernilai `["E14"]`, dan
pada `engine-results-e19.json` bernilai `["E15"]`. aggregator E17 membacanya
dari sana lewat `_read_supersedes()`.

Konsekuensinya: slot lama **tidak hilang**. Ia tetap tercetak di korpus
dengan `status: "superseded"` dan `superseded_by`, supaya pembaca bisa
melihat bukti lamanya sekaligus alasan penggantinya. Kalau deklarasi
superseession diletakkan di kode aggregator, maka bukti dan keputusan
harus di tempat yang berbeda — dan slot baru bisa diam-diam menggantikan
slot lama tanpa jejak.

Aggregator menolak supersession yang menunjuk slot tidak dikenal
(`_apply_supersessions()` melempar `ValueError`). Jadi E18 tidak bisa
menggantikan slot yang tidak ada.

### 3. Closure gap harus menunjuk slot AKTIF

Celah `a05_protected` ditutup oleh slot session-flow. Setelah E15
digantikan E19, closure itu **harus** menunjuk E19: closure harus berdiri di
atas bukti yang sedang dihitung korpus, bukan bukti yang sudah disisihkan.
`_validate_gap_closures()` menolak closure yang menunjuk slot yang tidak
ada di korpus aktif atau yang tidak punya perbandingan.

### 4. Fingerprint harness memisahkan n=5 dan n=30

`_harness_fingerprint()` E14/E15 meng-hash material pengukuran — termasuk
jumlah run. Checkpoint lama n=5 dan checkpoint baru n=30 punya sidik jari
berbeda, jadi run lama **tidak pernah** tercampur dengan run baru: mismatch
diabaikan dengan sendirinya dan dihitung di `records_ignored`.

Untuk E14, sidik jari n=30 (`06cba775…`) sudah ada dari run n=30 yang
sem selesai, sehingga backfill E18 **memakai ulang 786 run yang sudah
terukur** dan tidak menjalankan ulang satu pun run. Itu bukan penghematan
waktu semata: menjalankan ulang menghasilkan run baru dengan kondisi
perangkat berbeda, sedangkan evidence harus merekam satu rangkaian
pengukuran yang konsisten.

Untuk E15 tidak ada checkpoint lama, jadi E19 menjalankan 360 run penuh.

### 5. Konfigurasi backfill lewat env var, default tetap perilaku lama

Harness E14/E15 membaca `RUNS`, `RESULTS_PATH`, `BENCHMARK_ID`, dan
`SUPERSEDES` dari env var dengan **default yang sama seperti sebelumnya**
(`RUNS=5`, path dan id slot asli). Konsekuensinya:

- Menjalankan harness tanpa env var apa pun tetap mereproduksi evidence
  slot lama persis seperti sebelumnya — tidak ada perubahan diam-diam pada
  perilaku default.
- Backfill hanya terjadi kalau env var-nya diset eksplisit.
- `RESULTS_PATH` dan `benchmark_id` sengaja **tidak** masuk fingerprint:
  keduanya memilih ke mana bukti ditulis, bukan bagaimana ukurannya. Kalau
  ikut di-hash, backfill E18 akan membuang 786 run yang sah.

### 6. Angka persentil harus jujur untuk n yang dipakai

Pada n=5, p95 nearest-rank (`ceil(0.95 * 5) = 5`) memang sama dengan
maksimum. Pada n=30, p95 adalah statistik urutan ke-29 dari 30 — **bukan**
maksimum. Kalimat "p95 = maksimum" yang tertulis di E14 lama tidak lagi
benar saat n=30, jadi catatan persentil dihitung dari n yang benar-benar
dipakai (`_percentile_note()`), dan menyertakan status ambang §6.3.

Perkiraan yang sama berlaku untuk E19.

## Results

Evidence:

- `docs/benchmark/engine-results-e18.json` — benchmark_id
  `e18-cross-implementation-differential-n30-001`, 13 skenario × 2 arm × 30
  run = 780 run, `supersedes: ["E14"]`.
- `docs/benchmark/engine-results-e19.json` — benchmark_id
  `e19-session-flow-differential-n30-001`, 3 skenario × 4 arm × 30 run =
  360 run, `supersedes: ["E15"]`.

Korpus E17 (`docs/benchmark/engine-results-e17.json`) diregenerasi setelah
kedua slot ada: slot aktif E16/E18/E19, slot tersuspen E14/E15 tetap
dipublikasikan.

### Yang TIDAK diklaim

- **Tidak ada run baru yang dianggap lebih baik.** Backfill memperbanyak
  pengulangan, bukan memperbaiki kesimpulan. Vonis perbandingan bisa saja
  tetap sama — dan kalau tetap sama, itulah hasil yang jujur.
- **Tidak ada slot lama yang dihapus.** E14/E15 tetap ada sebagai rekaman
  n=5.
- **Fixture tetap sintetis dan satu origin.** Backfill menambah keyakinan
  pada angka, tidak menambah cakupan: tidak ada TLS, redirect lintas
  origin, rate limit nyata, atau cookie lintas origin pada dimensi HTTP.
- **Tidak ada klaim superiority keseluruhan.** Vonis perbandingan
  dipublikasikan terpisah; seluruh instance bukan skenario unik.

## Consequences

### Positif

1. **§6.3 terpenuhi di ketiga dimensi korpus.** Tidak ada lagi dimensi
   yang vonisnya berasal dari 5 run.
2. **Tidak ada bukti historis yang ditimpa.** Prekeden ADR-018/ADR-019
   (blok `correction`) diteruskan dalam bentuk yang lebih kuat: slot lama
   utuh, slot baru terpisah, dan hubungan keduanya tercatat eksplisit.
3. **Checkpoint E14 dipakai, bukan dibuang.** 780 run yang sudah terukur
   tetap dipakai sebagai bukti.

### Negatif / batasan

1. **Korpus punya lebih banyak slot tapi jumlah perbandingan tidak
   bertambah.** E14/E15 dikeluarkan dari hitungan, jadi total instansi
   perbandingan korpus tetap sama — yang berubah adalah jumlah run di
   balik tiap vonis.
2. **Dokumen harus menyebut dua slot untuk satu dimensi.** Pembaca harus
   tahu bahwa E14 dan E18 mengukur hal yang sama, dan mana yang dihitung.
3. **ADR-022 perlu diperbarui.** Batasan "E14 dan E15 masih n=5" sudah
   usang; dokumentasi yang tidak diperbarui akan berbohong.

### Tidak diklaim

- **Tidak diklaim angka berubah.** Vonis korpus sebelum dan sesudah
  backfill dibandingkan satu per satu di `corpus-verdict-matrix.md`; bila
  ada yang berubah, itu dicatat sebagai perubahan, bukan-dirhamakan.
- **Tidak diklaim n=30 menghapus bias apa pun.** 30 pengulangan adalah
  ambang yang ditetapkan §6.3, bukan jaminan bebas bias.
## Links

- Evidence backfill HTTP: `docs/benchmark/engine-results-e18.json`
- Evidence backfill sesi: `docs/benchmark/engine-results-e19.json`
- Evidence korpus: `docs/benchmark/engine-results-e17.json`
- Laporan korpus: `docs/benchmark/corpus-verdict-matrix.md`
- Harness: `src/universal_web_acquisition/benchmark/cross_impl_bench.py`,
  `src/universal_web_acquisition/benchmark/session_diff_bench.py`,
  `src/universal_web_acquisition/benchmark/corpus_matrix.py`
- ADR sebelumnya: ADR-019 (cross-impl HTTP), ADR-020 (session flow),
  ADR-021 (browser arm), ADR-022 (corpus verdict matrix)
