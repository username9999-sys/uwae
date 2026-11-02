# Evaluasi Classifier Akses — Milestone B (G3)

Tanggal: 2026-10-21 · Classifier: `access/classifier.py` (`classifier-1.0.0`)
Harness: `benchmark/classifier_eval.py` · Test: `tests/test_classifier_eval.py` (13 test)
Suite penuh: **167 passed** (`python run_tests.py`, 61 s)

## Metodologi

Mandat Milestone B: "Classifier diuji menggunakan fixture yang label sebenarnya
sudah diketahui" — dengan precision/recall per kelas, confusion matrix, FP/FN,
dan persentase UNKNOWN yang dilaporkan. Harness ini mengeksekusi tiga lapis
bukti:

1. **Korpus berlabel sintetis** (`LABELED_CASES`, 24 kasus) — sinyal → state
   yang diharapkan, mencakup seluruh 9 kelas `AccessState`, kasus preseden
   urutan evaluasi §3.1, dan robustness (status tak terurai). Korpus adalah
   **spesifikasi eksekutabel**: akurasi < 1.0 berarti inkonsistensi nyata
   antara classifier dan spesifikasi, bukan angka untuk dipoles.
2. **Probe marker konten** (`MARKER_PROBES`, 5 probe) — mengukur TP/FP
   deteksi gerbang JS/interstitial challenge di `access/observe` — kode yang
   sama persis dengan jalur produksi worker (satu sumber kebenaran).
3. **Kasus turunan fixture nyata** — respons HTTP sungguhan dari fixture
   server E5 (bukan observasi buatan) diklasifikasikan end-to-end.

## Hasil terukur (run 2026-10-21)

### Korpus berlabel — 24/24 benar

| Metrik | Nilai |
|---|---|
| Total kasus | 24 |
| Benar | 24 |
| Akurasi | **1.00** |
| Mismatch | 0 |
| Proporsi UNKNOWN | 2/24 ≈ **0.083** (by design — UNKNOWN adalah hasil yang sah, §5) |
| Confusion matrix | **hanya diagonal** — tidak ada off-diagonal |
| Precision per kelas | **1.00** untuk seluruh 9 label |
| Recall per kelas | **1.00** untuk seluruh 9 label |

Distribusi korpus: ACCESS_GRANTED 2 · AUTH_REQUIRED 3 · RATE_LIMITED 3 ·
CHALLENGE_PRESENT 2 · JAVASCRIPT_REQUIRED 2 · CONTENT_INVALID 4 ·
NETWORK_FAILURE 5 · ACCESS_DENIED 1 · UNKNOWN 2.

### Probe marker — 6/6 lulus

| Probe | Hasil diharapkan | Hasil aktual | Status |
|---|---|---|---|
| `normal-article-captcha-word` | hanya `target=found` | persis | ✅ FP terhindar |
| `normal-js-mention` | hanya `target=found` | persis | ✅ FP terhindar |
| `js-gate` | `target=missing` + `js.required=true` | persis | ✅ TP |
| `challenge-checking-browser` | `challenge` + `target=missing` | persis | ✅ TP |
| `challenge-just-a-moment` | `challenge` + `target=missing` | persis | ✅ TP |
| `cloudflare-normal-page-with-challenge-script` | hanya `target=found` | persis | ✅ FP terhindar (temuan target nyata) |

Catatan FP: kata generik ("captcha", "javascript") sengaja **tidak** ada di
daftar marker — artikel yang membahas captcha tidak boleh diklasifikasikan
sebagai challenge.

**Temuan target nyata (komiku.asia, run `real-target-komiku-001`)**: marker
`challenge-platform` DIHAPUS dari daftar setelah pengujian nyata menunjukkan
Cloudflare menginjeksikan path `/cdn-cgi/challenge-platform/` ke halaman
NORMAL yang disajikan sukses (200 + konten penuh 291 KB) — kehadirannya
sempat memicu false positive `CHALLENGE_PRESENT` pada homepage (tertangkap
oleh evidence lineage per-attempt, bukan tersembunyi). Probe regresi
ditambahkan; run ulang: seluruh 6 skenario `ACCESS_GRANTED`.

### Kasus turunan fixture nyata (E5)

| Fixture | Respons | Diagnosis | Reason code |
|---|---|---|---|
| `/html` | 200 + konten | `ACCESS_GRANTED` | `ok` |
| `/missing` | 404 (TransportFailure) | `CONTENT_INVALID` | `http_4xx` |
| `/js` (fetch HTTP) | 200 + teks gerbang | `JAVASCRIPT_REQUIRED` | `content_invalid` |

## Keputusan yang tidak dapat diputuskan (daftar Milestone B)

1. **403 tanpa bukti body** — benar-benar ambigu (penolakan izin vs aturan
   aplikasi vs challenge). Aturan preseden §3.1 memutuskannya ke
   `ACCESS_DENIED`, tetapi tanpa sinyal body pembedaan sesungguhnya tidak
   mungkin — keputusan terbatas-bukti, dicatat sebagai such.
2. **200 + body kosong** — selector salah vs gerbang JS vs halaman kosong;
   classifier melaporkan `CONTENT_INVALID` (bukan sukses). Pembedaan
   membutuhkan aturan target per-situs atau bukti JS tambahan.
3. **503 + Retry-After** — diklasifikasikan `RATE_LIMITED` karena sinyal
   eksplisit menang (aturan 2); secara semantik bisa juga pemeliharaan
   server. Diputuskan oleh aturan, bukan oleh bukti.
4. **Kasus UNKNOWN** (status tak terurai, sinyal tak dikenal saja) —
   dibiarkan UNKNOWN sesuai desain; persentase dilaporkan, tidak disembunyikan.
5. **Konstanta confidence** (0.95/0.75/0.35) — placeholder kategorial yang
   belum dikalibrasi (§3.2); kalibrasi menunggu corpus kegagalan nyata.

## Batasan & langkah berikutnya

- Korpus saat ini sintetis + turunan fixture lokal; kasus dari target nyata
  (E8+) membutuhkan otorisasi dan akan menambah korpus.
- FP-rate marker terukur pada 5 probe; pengukuran pada halaman nyata
  mengikuti pertumbuhan korpus berlabel.
- Precision/recall 1.0 pada korpus adalah **verifikasi spesifikasi**, bukan
  klaim unggul atas baseline (mandat: bukti dulu, klaim kemudian).
