# ADR-022: Matriks korpus vonis — menggabungkan seluruh benchmark lintas-implementasi jadi satu artefak

## Status
Accepted (2026-10-28 — evidence: engine-results-e17.json, benchmark_id `e17-corpus-verdict-matrix-001`)

## Context

TEXT.md §9 menutup daftar gerbang evaluasi dengan "#7. Di skenario mana
mesin baru mengungguli baseline, sama, atau justru gagal?" — dan gerbang itu
sendiri jadi pembatas: *"Baru setelah itu kita memilih fitur berikutnya
berdasarkan hasil pengujian."*

Gerbang #7 punya masalah bentuk. Tiga benchmark lintas-implementasi sudah
mengukurnya, masing-masing dengan dimensinya sendiri:

| Slot | Dimensi | Skenario | Bentuk vonis di evidence |
|---|---|---|---|
| E14 | transport HTTP | 13 | agregat per sel (`primary_success_rate`) — **tanpa vonis** |
| E15 | alur sesi | 3 | run mentah per arm — **tanpa vonis** |
| E16 | dimensi browser | 4 | `summary.comparisons` — **vonis eksplisit** |

Tiga hal yang hilang:

1. **Tidak ada satu artefak korpus.** Tiap benchmark punya vonisnya sendiri,
   tapi pembaca yang ingin tahu "gimana performa UWAE vs Botasaurus secara
   keseluruhan" harus menyatukan sendiri tiga dokumen dengan tiga skema
   berbeda. TEXT.md:1427 (Tahap G) secara eksplisit meminta: *"Publikasikan
   hasil menang, seri, kalah, dan belum teruji secara terpisah."*

2. **Tiga skema, tiga cara berbeda menghitung hal yang sama.** E14 tidak
   memisahkan run yang belum bisa dinilai, E15 memisahkan lewat row mentah,
   E16 memisahkan dan sudah mempublikasikan vonisnya. Menjumlahkan angka
   mentah dari ketiganya tanpa adapter akan menghasilkan angka yang terlihat
   meyakinkan dan sebenarnya tidak bermakna.

3. **Cakupan tidak pernah dipublikasikan berdampingan dengan kemampuan.**
   E14 mendeklarasikan dua celah (`a05_protected` dan
   `js_rendering_browser_arm`). E15 dan E16 masing-masing menutup satu. Tapi
   closure itu tercatat di dalam dokumen masing-masing — tidak ada tempat
   yang menyatakan "celah mana yang sudah tertutup, dan ditutup oleh bukti
   mana".

Yang **tidak** boleh dilakukan di sini: menjumlahkan perbandingan lintas slot
jadi satu angka tunggal tanpa qualifier, karena slot yang sama bisa mengukur
skenario yang sama dengan lengan dan kriteria berbeda.

## Decision

### 1. E17 adalah aggregator, bukan benchmark

`corpus_matrix.py` **tidak menjalankan benchmark**. Ia membaca evidence yang
sudah dipublikasikan dan menyusunnya. Nol run baru, nol risiko perangkat,
nol kemungkinan mengarang pengukuran.

Konsekuensinya: E17 tidak bisa memperbaiki kualitas evidence slot di bawahnya.
Kalau E14/E15/E16 salah, E17walt mewarisi kesalahannya — dan itu justru
memstoppable: bug di aggregator akan terlihat sebagai bug di ringkasan.

### 2. Aturan vonis yang sama untuk semua slot

Aturan vonis disalin dari `browser_diff_bench._comparison_outcome` (E16) yang
sudah terverifikasi:

- Batas 1 — tingkat sukses atas run yang **dievaluasi**.
- Batas 2 — tingkat sukses atas **seluruh attempt**.
- Dua batas memberi urutan sama → vonis pasti (`uwae` / `baseline` / `tie`).
- Dua batas memberi urutan berbeda → `not_comparable`: bukti tidak cukup
  memilih, jadi **tidak diberikan ke lengan mana pun**.
- Salah satu sisi tanpa run yang bisa dinilai → `no_evaluable_runs`.

Aturan yang sama untuk semua slot adalah syarat agar perbandingan antar-slot
bermakna. Kalau E14 memakai satu aturan dan E16 memakai aturan lain, jumlah
di korpus tidak lebih bermakna daripada penjumlahan angka dari dokumen
terpisah.

### 3. Run yang belum bisa dinilai keluar dari penyebut kapabilitas

Tiga sumber (identik dengan E16): runtime failure; lengan melaporkan error
tanpa body maupun status; outcome kosong. Run seperti itu dikeluarkan dari
penyebut kapabilitas dan dipublikasikan **terpisah** sebagai
`untested_runs` — tidak pernah dihitung sebagai kegagalan engine.

Pada korpus saat ini jumlahnya **0**: seluruh 480 run E16 dan seluruh run E14/
E15 bisa dinilai.

### 4. Setiap perbandingan mencantumkan asal dan basicnya

Tiap entri membawa:

- `verdict_source` — `explicit` (diambil apa adanya dari evidence slot,
  seperti E16) atau `derived` (diturunkan di sini, seperti E14/E15);
- `evaluated_basis` — `raw_rows` (slot menyimpan run mentah) atau
  `published_runs_only` (slot hanya memuat agregat);
- angka lengkap yang dipakai: `runs`, `evaluated_runs`,
  `primary_success_runs`, `untested_runs` untuk kedua sisi.

Tujuannya auditability: setiap vonis di korpus bisa dikembalikan ke run
mentah yang memproduksinya, dan pembaca bisa melihat langsung kalau sebuah
slot tidak menyediakan run mentah.

### 5. Vonis eksplisit tidak pernah dihitung ulang

Slot E16 sudah mempublikasikan vonisnya. E17 mengambilnya apa adanya — ada
tes yang membandingkan hasil korpus dengan `summary.comparisons` E16 sel per
sel. Menghitung ulang vonis yang sudah dipublikasikan risksnya mengarang
perbedaan dari harness aslinya.

Slot E14 dan E15 tidak punya vonis, jadi vonisnya diturunkan di sini dengan
aturan yang sama dan ditandai `derived`.

### 6. Celah: closure harus menunjuk slot yang benar-benar terukur

Celah yang dideklarasikan sebuah slot dicatat beserta sumber
deklarasinya. Status closure **tidak** ditebak dari kemiripan nama skenario —
ID skenario di slot berbeda memang berbeda (E14 `a05_protected` diukur E15
sebagai `session_valid`/`session_required`/`session_expired`). Yang
dipakai adalah peta closure eksplisit, dan setiap closure diverifikasi:
slot yang ditunjuk harus ada di korpus **dan** punya perbandingan.

### 7. Jumlah korpus adalah jumlah INSTANSI perbandingan

Dinyatakan eksplisit di evidence (`method.counts_are`) dan di laporan.
Skenario yang sama bisa diukur di beberapa slot dengan lengan dan kriteria
berbeda, jadi jumlah slot tidak boleh dibaca sebagai jumlah skenario unik.

### 8. Cakupan dan kemampuan dipublikasikan terpisah

Korpus mengukur dua hal yang tidak boleh dicampur: **kemampuan** (vonis per
perbandingan) dan **cakupan** (celah yang dideklarasikan lalu ditutup).
Keduanya ada di artefak yang sama, tapi di blok terpisah, dan laporan
menyatakan bahwa tidak ada klaim superiority keseluruhan.

## Results

Evidence: `docs/benchmark/engine-results-e17.json` — benchmark_id
`e17-corpus-verdict-matrix-001`. Laporan:
`docs/benchmark/corpus-verdict-matrix.md`. Harness:
`src/universal_web_acquisition/benchmark/corpus_matrix.py`. Test:
`tests/test_corpus_matrix.py`.

Ringkasan korpus: **13** UWAE, **21** seri, **0** baseline, **0** tidak
sebanding, **0** tanpa run yang dapat dinilai, **0** run belum teruji.

| Dimensi | Slot | Perbandingan | UWAE | Seri | Baseline |
|---|---|---|---|---|---|
| `http-transport` | E18 | 13 | 7 | 6 | 0 |
| `session-flow` | E19 | 9 | 4 | 5 | 0 |
| `browser-arm` | E16 | 12 | 2 | 10 | 0 |

Total 34 instansi perbandingan. Angka ini sudah diverifikasi ulang dengan
penghitungan manual yang **independen** dari kode harness: E18 7/6/0,
E19 4/5/0, E16 2/10/0.

Slot E14 (n=5) dan E15 (n=5) **digantikan** oleh E18 (n=30) dan E19 (n=30)
lewat backfill §6.3 (ADR-023). Keduanya tetap dipublikasikan dengan status
`superseded` dan penunjuk penggantinya; bukti lamanya tidak ditimpa. Vonis
korpus **tidak berubah** setelah backfill — yang berubah hanya jumlah run di
belakang tiap vonis.

Celah: **2** dideklarasikan, **2** ditutup, **0** terbuka.

| Celah | Dideklarasikan | Ditutup oleh | Bukti |
|---|---|---|---|
| `a05_protected` | E18 | E19 | `engine-results-e19.json` |
| `js_rendering_browser_arm` | E18 | E16 | `engine-results-e16.json` |

Gerbang §9 #7 sekarang punya artefak korpus. Yang **tidak** diklaim: bahwa UWAE
mengungguli Botasaurus secara keseluruhan — 21 dari 34 hasil adalah seri, dan
fixture yang dipakai sintetis serta satu origin.

## Consequences

### Positif

1. **Tahap G terpenuhi**: menang/seri/kalah/belum-teruji dipublikasikan
   terpisah di level korpus, bukan hanya per benchmark.
2. **Gerbang §9 #7 punya artefak tunggal** yang bisa dirujuk pembaca tanpa
   menyatukan sendiri tiga skema berbeda.
3. **Cakupan jadi terlihat**: dua celah E14 yang ditutup E15/E16 sekarang
   tercetak eksplisit bersama bukti closure-nya.
4. **Nol run baru**: biaya untuk menghasilkan artefak ini nol run, nol risiko reboot.

### Negatif / batasan

1. **~~E14 dan E15 masih n=5.~~** Batasan ini **sudah teratasi** oleh
   backfill §6.3 (ADR-023): slot E18 (http-transport, n=30) menggantikan E14
   dan slot E19 (session-flow, n=30) menggantikan E15. Ketiga dimensi korpus
   sekarang dihitung dari n=30. Bukti lama E14/E15 **tidak ditimpa** — ia
   tetap dipublikasikan dengan status `superseded`.
2. **Jumlah instans, bukan skenario.** 34 bukan "34 skenario".
3. **Aggregator tidak memperbaiki evidence.** Kalau slot di bawahnya keliru,
   ringkasan ini mewarisi kesalahannya.
4. **Fixture sintetis, satu origin.** Tidak ada TLS, redirect, rate limit,
   atau cookie lintas origin pada dimensi HTTP.

### Tidak diklaim

- **Tidak diklaim UWAE mengungguli Botasaurus secara keseluruhan.** 21 dari 34
  hasil adalah seri, dan "0 baseline menang" berlaku pada fixture sintetis ini.
- **Tidak diklaim 13/34 berarti UWAE unggul secara bermakna.** Angka itu
  jumlah instansi perbandingan pada fixture tertentu, bukan parameter
  populasi.
- **Tidak ada data historis yang ditimpa.** E17 menambah artefak baru;
  evidence E14/E15/E16 tetap utuh.

## Links

- Evidence: `docs/benchmark/engine-results-e17.json`
- Laporan: `docs/benchmark/corpus-verdict-matrix.md`
- Harness: `src/universal_web_acquisition/benchmark/corpus_matrix.py`
- Test: `tests/test_corpus_matrix.py`
- ADR sebelumnya: ADR-019 (cross-impl HTTP), ADR-020 (session flow),
  ADR-021 (browser arm)
