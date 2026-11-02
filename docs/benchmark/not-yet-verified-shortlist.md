# Shortlist prioritas: 27 baris "Not yet verified" di competitive-matrix.md

> Dihasilkan 2026-10-31 dari audit ulang sumber (`src/universal_web_acquisition/`) setelah P2/P3/P8 mendarat. Mengikuti ADR-024: prioritas diturunkan dari **hasil pengukuran dan celah nyata**, bukan dari kolom Priority Phase-0.
>
> Fakta struktural (diperbarui): dari 27 baris ini, **0 baris** memiliki Botasaurus `Verified` — Botasaurus pada baris-baris itu berstatus `Not verified` atau paling tinggi `Likely`. Jadi tidak ada satupun dari 27 ini yang bisa menghasilkan "baseline win"; yang bisa dihasilkan adalah penutupan celah kemampuan atau pengurangan cost.

## Kelompok 1 — Celah cost yang SUDAH terukur (kerjakan lebih dulu)

| # | Baris | Kenapa prioritas | Bukti |
|---|---|---|---|
| 1 | **CPU usage monitoring and limits** | P3 sudah mengukur memori per job; CPU adalah separuh lain dari "resource accounting" yang sama-sama tidak ada. psutil sudah jadi dependensi yang dideklarasikan tapi tidak dipakai. | matriks baris ini; `pyproject.toml` |
| 2 | **Dynamic concurrency adjustment based on resource availability** | E11 sudah mengukur scaling sub-linear (1,57x di 2 thread, 1,25x di 4); dengan sinyal resource (P3 + CPU) concurrency bisa di-adjust otomatis — ini baru bisa diukur setelah #1. | `engine-results-e11.json` |
| 3 | **Performance regression detection** | Semua slot sudah punya checkpoint + fingerprint; yang kurang adalah baseline tersimpan + threshold + gate. Ini melindungi seluruh 41 instans korpus dari regresi diam-diam. | `corpus_matrix.py`, `_checkpoint.py` |

## Kelompok 2 — Celah kapabilitas yang berdampak pada hasil akuisisi

| # | Baris | Kenapa | Catatan |
|---|---|---|---|
| 4 | **Pagination handling** | Banyak target nyata (listing, komik, direktori) butuh `rel=next`/cursor; tanpa ini akuisisi hanya halaman pertama. | prioritas High di Phase-0, konsisten dengan dampak |
| 5 | **Canonical URL resolution** | Dedup saat ini exact-URL saja, jadi halaman sama bisa di-fetch berkali-kali — cost nyata yang bisa diukur. | |
| 6 | **HTTP connection pooling** | Botasaurus `Likely` via `requests.Session`; UWAE memanggil helper stateless per request. Ini celah cost yang bisa diukur head-to-head (E18-style latency). | satu-satunya baris dengan Botasaurus `Likely` |
| 7 | **iframe handling / Shadow DOM penetration** | Browser arm membaca `documentElement.outerHTML` saja; konten di dalam iframe/shadow root tidak ikut. Bisa diukur dengan fixture baru. | |
| 8 | **AJAX/XHR interception** | Tanpa interception, konten yang dimuat via XHR setelah load tidak tertangkap browser arm. | |
| 9 | **Bandwidth throttling** | Berguna untuk mengukur cost pada kondisi jaringan lambat (relevan di Termux). | |

## Kelompok 3 — Infrastruktur/operasional (ada sebagian setelah P8)

| # | Baris | Status setelah P8 | Sisa |
|---|---|---|---|
| 10 | **Background service compatibility** | `uwae serve` + `uwae shutdown <pid>` sudah ada (daemon dengan klaim QUEUED atomik + SIGTERM graceful) | Yang kurang: integrasi termux-service/wake-lock, bukan daemon-nya sendiri. Status bisa naik ke `Implemented` untuk bagian daemon. |
| 11 | **Configuration profiles (dev/staging/prod)** | Loader terpusat sudah ada (P8) | Yang kurang: profil bernama + flag pemilihan. |
| 12 | **Dead letter queue** | Job gagal memang sudah tercatat dengan jejak attempt | Yang kurang: store DLQ + kebijakan requeue. |
| 13 | **Circuit breaker patterns** | — | Belum ada state breaker lintas-job. |
| 14 | **Cache warming/preloading** | — | Belum ada. |
| 15 | **Extraction caching** | Hanya ada cache respons HTTP | Cache hasil ekstraksi belum ada. |
| 16 | **Format version detection** | Identification mencatat format id, bukan versi | |
| 17 | **Browser instance limits** | 1 chromium per adapter, dibatasi implisit oleh thread cap 16 | Tidak ada cap eksplisit. |
| 18 | **Multiple browser profiles** | — | Satu profil per adapter. |
| 19 | **Interactive mode/wizard** | — | Semua non-interaktif. |
| 20 | **Distributed tracing** | Event log per-job sudah ada (bukan tracing) | Tidak ada span/correlation id. |

## Kelompok 4 — Yang sengaja TIDAK dibangun (per ADR-024)

| # | Baris | Alasan |
|---|---|---|
| 21 | **Automated challenge solving** | ADR-024: tidak dibangun — itu kategori anti-deteksi, bukan akuisisi; dan bisa melanggar ToS target. |
| 22 | **Multi-factor authentication support** | ADR-024: engine MFA tidak dibangun; yang benar adalah `needs_user` untuk MFA (sudah ada). |

## Kelompok 5 — Lingkungan/compliance (bukan kode engine)

| # | Baris | Catatan |
|---|---|---|
| 23 | **Compliance with data protection regulations** | Bukan fitur kode; perlu kebijakan retensi/erasure. |
| 24 | **Storage access permissions handling** | Perlu penanganan scoped-storage Android — di luar sandbox Termux saat ini. |
| 25 | **Battery-efficient operation** | Tidak ada pengukuran power; proxy terdekat sudah ada (E12: biaya browser). |
| 26 | **Cross-platform test compatibility** | Semua benchmark jalan di satu platform (aarch64 PRoot); perlu run kedua platform. |
| 27 | **HTTP connection pooling** sudah masuk kelompok 2 (#6) | — |

## Rekomendasi urutan eksekusi

1. **#1 CPU monitoring** (melengkapi P3, psutil sudah ada) → lalu **#2 dynamic concurrency** (butuh #1).
2. **#3 regression gate** — melindungi semua evidence yang sudah ada; relatif murah karena checkpoint sudah ada.
3. **#6 connection pooling** — satu-satunya celah cost yang bisa diukur head-to-head dengan Botasaurus (`Likely`).
4. **#4 pagination + #5 canonical** — celah kapabilitas dengan dampak akuisisi terbesar.
5. Sisanya menyusul; kelompok 4 tidak dibangun.
