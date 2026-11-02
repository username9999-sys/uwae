# ADR-028: Shortlist 27 baris "Not yet verified" + audit pemisahan modul Botasaurus sendiri vs dependensi (§9 #1)

## Status
Accepted (2026-10-31 — evidence: docs/benchmark/not-yet-verified-shortlist.md, docs/audit/botasaurus-module-split.md)

## Konteks
Dua item tersisa dari daftar langkah: **B** (27 baris `Not yet verified` di matriks kompetitif) dan **C** (pertanyaan gerbang TEXT.md §9 #1 yang belum terjawab: berapa modul Botasaurus yang kode sendiri vs dependensi pihak ketiga).

## Keputusan

### B — Shortlist 27 baris "Not yet verified"
Dibuat `docs/benchmark/not-yet-verified-shortlist.md` dengan pengelompokan berbasis dampak terukur, bukan kolom Priority Phase-0:

1. **Kelompok 1 (cost terukur, kerjakan dulu):** CPU monitoring (#1, melengkapi P3 — psutil sudah dideklarasikan tapi tidak dipakai), dynamic concurrency (#2, E11 sudah mengukur scaling sub-linear), regression gate (#3, checkpoint sudah adagal).
2. **Kelompok 2 (celah kapabilitas akuisisi):** pagination, canonical URL, connection pooling (satu-satunya dengan Botasaurus `Likely`), iframe/shadow DOM, AJAX interception, bandwidth throttling.
3. **Kelompok 3 (infra, sebagian sudah ada setelah P8):** `uwae serve`/`shutdown` sudah menutup sebagian "background service"; sisanya DLQ, circuit breaker, cache warming, dll.
4. **Kelompok 4 (sengaja tidak dibangun, per ADR-024):** automated challenge solving, MFA engine.
5. **Kelompok 5 (lingkungan/compliance, bukan kode engine).**

Fakta struktural yang diperbarui: dari 27 baris, **0 memiliki Botasaurus `Verified`** — tidak ada yang bisa menghasilkan baseline win.

### C — Pemisahan modul Botasaurus (menjawab §9 #1)
Dibuat `docs/audit/botasaurus-module-split.md`, diukur langsung dari `RECORD` tiap paket di venv:

| Kategori | Paket | File `.py` | Baris |
|---|---|---|---|
| Milik Botasaurus sendiri | **6** | **144** | **59.768** |
| Dependensi pihak ketiga | **39** | **2.310** | **857.328** |
| Total venv | 45 | 2.454 | 917.096 |

Hanya **5,9% file / 6,5% baris** kode yang berjalan adalah milik Botasaurus sendiri; paket terbesarnya justru `botasaurus_driver` (82 file, 83% kode milik Botasaurus), bukan paket inti.

**Koreksi:** klaim `environment-report.md:58` "357 paket (dist-info)" **tidak dapat direproduksi** — `ls *.dist-info` aktual = **45**, `pip list` = 47 baris, total file semua ekstensi = 6.106. Angka 357 tidak cocok dengan metrik apa pun. environment-report.md sengaja **tidak ditimpa** (audit historis tetap utuh); koreksi dicatat di dokumen audit baru dan ADR ini.

## Apa yang TIDAK diklaim
- Tidak ada klaim bahwa shortlist B akan menghasilkan kemenangan atas Botasaurus — 0 dari 27 baris punya Botasaurus `Verified`.
- Angka C diukur pada venv perbandingan (`/root/botasaurus-venv`), bukan pada instalasi produksi lain; tetap merupakan sumber yang sama dengan semua benchmark E14–E22.
- environment-report.md tidak diedit — koreksi mengikutinya, sesuai pola "jangan timpa evidence historis".

## Link
- `docs/benchmark/not-yet-verified-shortlist.md`
- `docs/audit/botasaurus-module-split.md`
- `docs/benchmark/text-9-gate-status.md` (baris #1 diperbarui menjadi Terjawab)
- `docs/benchmark/competitive-matrix.md` (27 baris `Not yet verified` tetap apa adanya — shortlist adalah dokumen terpisah, matriks tidak diubah)
