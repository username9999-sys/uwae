# ADR-017: Adaptive Scheduling — HTTP-first dengan eskalasi berbasis bukti

## Status
Accepted (2026-10-26, post-roadmap Tahap H — evidence: engine-results-e12.json)

## Context

TEXT.md Tahap H mandat lima eksperimen pembeda; E6 (concurrency) sudah
selesai di ADR-016. Eksperimen berikutnya adalah **E4 — adaptive scheduling**:
*"bandingkan biaya dan keberhasilan HTTP-first dengan strategi browser-first
pada fixture yang sama."*

Sebelum ini, pilihan transport di UWAE bersifat **struktural**, bukan
terukur: `build_default_registry()` menyusun `curl_cffi` → `browser`, dan
planner (ADR-013) memilih transport berdasarkan klasifikasi ACCESS. Belum
pernah ada bukti terukur tentang **berapa mahal** lengan browser dibanding
HTTP, dan **apa yang hilang** bila strategi adaptif tidak ada.

Dua pertanyaan yang harus dijawab dengan bukti, bukan penalaran:

1. **Biaya** — berapa mahal browser dibanding HTTP (waktu, memori, jumlah
   attempt)?
2. **Cakupan vs fidelity** — apakah selalu memakai browser memberi hasil
   *lebih baik*, atau justru **menyembunyikan sinyal** yang perlu terlihat?

Pertanyaan kedua penting secara arsitektural: UWAE adalah engine akuisisi
berbasis **klasifikasi bukti** (ACP §2 — `access_granted` vs
`challenge_present` vs `content_invalid`). Jika browser "menyembunyikan"
sinyal, maka lengan browser bisa terlihat lebih sukses **karena melihat
lebih sedikit** — hasil yang lebih buruk, bukan lebih baik.

## Decision

1. **Satu knob di worker: `JobWorker(initial_transport=...)`.** Transport
   untuk attempt PERTAMA dapat dipin oleh caller; `None` (default) =
   urutan prioritas registry (HTTP dulu). Keputusan **setelah** attempt
   pertama tetap milik planner — knob ini tidak memotong logika adaptif,
   hanya menggeser titik awal. Preseden: ADR-016 "policy stays at the
   caller".

2. **Benchmark membandingkan STRATEGI, bukan implementasi.** Ketiga lengan
   memakai `JobWorker` + registry + planner + artifact store yang **identik**;
   yang dibedakan hanya transport awal. Tanpa ini, benchmark akan mengukur
   dua implementasi berbeda dan kesimpulannya tidak berlaku.

3. **Ground truth dari semantika protokol fixture, bukan dari output
   classifier.** Kalau ground truth berasal dari classifier yang sama yang
   sedang diuji, benchmark bisa "memenuhi dirinya sendiri". Fixture
   menyiratkan jawaban (404 → gagal, JS-gate → butuh browser, challenge →
   perlu manusia); benchmark mengunci jawaban itu di `EXPECTED` dan
   mengukur **tingkat kesesuaian** tiap lengan.

4. **Biaya cold start diukur TERPISAH dari lengan berulang.** Lengan
   berulang memakai chromium persisten (ADR-014) agar statistik tidak
   didominasi biaya peluncuran proses; biaya one-shot chromium baru
   diukur sebagai metrik tersendiri karena inilah biaya yang dibayar user
   produksi pada jalur `--browser`.

5. **Perbaikan paritas diagnosis di sumber, bukan di benchmark.** Eksperimen
   menemukan celah nyata: jalur browser mengembalikan respons non-2xx
   sebagai **artifact** (bukan exception), sementara
   `observations_from_artifact` hanya mengurai sinyal body untuk status 2xx.
   Akibatnya marker challenge/login pada body 403 **hilang** di jalur
   browser. Perbaikan dilakukan di `access/observe.py` — body non-2xx tetap
   diurai untuk marker, tetapi **tidak pernah menjadi konten target**.
   Benchmark tidak pernah menambal klasifikasi; ia hanya mengukurnya.

## Measured Results (evidence: engine-results-e12.json)

369 run, 30 pengulangan per (lengan, skenario) untuk skenario berulang;
3 skenario fidelity dijalankan sekali per lengan (jeda Retry-After server).
**Tingkat kesesuaian ground truth: 100% di semua 21 kombinasi
(lengan × skenario).**

Cakupan:

| Skenario | http_only | browser_first | adaptive |
|---|---|---|---|
| `b01_small_get` (HTML biasa) | succeeded | succeeded | succeeded |
| `b07_js_render` (JS gate) | **failed** (javascript_required) | succeeded | succeeded (2 attempt) |
| `e02_not_found` (404) | failed | failed | failed |
| `a07_challenge` | needs_user | needs_user | needs_user |
| `a11_invalid_html` (byte rusak) | failed (content_invalid) | **succeeded** | failed (content_invalid) |
| `a06_rate_limited` (429) | failed (rate_limited) | failed (rate_limited) | failed (rate_limited) |
| `a04_login` | failed (auth_required) | failed (auth_required) | failed (auth_required) |

Biaya (median, chromium persisten):

- `b01_small_get`: http_only **255 ms** vs browser_first **534 ms** vs
  adaptive **213 ms** — adaptif ~2,5× lebih cepat dari browser-first pada
  HTML biasa, dan tidak menyentuh browser sama sekali.
- `b07_js_render`: adaptive **720 ms** (2 attempt: HTTP → browser) vs
  browser_first **550 ms** (1 attempt) — adaptif membayar biaya eskalasi
  hanya pada kasus yang membutuhkannya.
- Biaya cold start chromium (satu akuisisi, proses baru): **5432 ms**,
  RSS **191368 kB** (~187 MB).

Tiga temuan yang mengubah cara engine harus berperilaku:

1. **Browser-first bukan "lebih baik" — ia lebih mahal dan kurang jujur.**
   Pada `a11_invalid_html`, lengan browser **berhasil** sementara HTTP
   gagal. Itu bukan keunggulan: DOM browser merekonstruksi byte rusak
   menjadi HTML valid, sehingga sinyal "konten rusak" **hilang**. Lengan
   HTTP melaporkan `content_invalid` — diagnosis yang benar. Memilih
   browser-first berarti **membayar ~187 MB dan ~5,4 s untuk melihat lebih
   sedikit**.

2. **Browser tidak melihat header respons, sehingga tidak bisa menghormati
   `Retry-After`.** Pada `a06_rate_limited`, lengan HTTP menghormati jeda
   server (`wait_retry_after` tercatat di event decision); lengan browser
   tidak dapat — header respons tidak terekspos oleh CDP. Klasifikasi tetap
   benar (`rate_limited`), tapi **perilaku menghormati server hilang**.

3. **Challenge tidak terpecahkan oleh browser.** Ketiga lengan berakhir
   `needs_user` — hasil yang benar menurut ACP §2.2 (verifikasi manusia),
   bukan sukses palsu. Browser yang merender halaman challenge tidak
   membuat challenge terpecahkan.

Kesimpulan terukur: **strategi adaptif (default engine) adalah pilihan
terbaik di antara ketiganya** — ia mencapai cakupan browser-first pada
kasus yang butuh browser, dengan biaya HTTP-first pada kasus yang tidak,
dan **tanpa kehilangan sinyal diagnosis** yang justru dihapus oleh
browser-first.

## Alternatives Considered

- **Selalu browser-first** — ditolak oleh bukti: 2,5× lebih lambat pada
  HTML biasa, ~187 MB RSS per chromium, kehilangan sinyal `content_invalid`,
  dan kehilangan kemampuan menghormati `Retry-After`. Keunggulannya
  (satu attempt untuk JS gate) tidak sebanding dengan harga yang dibayar
  pada setiap URL lain.
- **Selalu HTTP-only** — ditolak oleh bukti: kehilangan `b07_js_render`
  sepenuhnya (30/30 gagal). Tanpa jalur eskalasi, engine tidak dapat
  menjangkau konten yang butuh JS.
- **Menambah transport baru (mis. HTTP/2, QUIC)** — ditolak untuk sekarang:
  E4 mengukur **strategi**, bukan varian transport; menambah transport
  baru akan mengaburkan perbandingan dan tidak menjawab pertanyaan E4.
- **Benchmark lintas-implementasi (vs Botasaurus)** — tidak dilakukan
  di ADR ini: ADR ini mengukur **strategi**, bukan implementasi lain.
  Catatan koreksi (ADR-019): alasan lama "engine HTTP Botasaurus tidak
  dapat dieksekusi di environment ini" ternyata SALAH — itu bug pemanggilan
  pada skrip baseline proyek ini, bukan batas platform. Benchmark
  lintas-implementasi yang sah ada di `docs/benchmark/engine-results-e14.json`
  (E14); tidak ada klaim lintas-implementasi di ADR ini.

## Consequences

- `JobWorker` gaining satu parameter opsional — default `None` menjaga
  perilaku byte-for-byte; jalur produksi tidak berubah.
- `access/observe.py` kini mengurai body non-2xx untuk marker (tanpa
  menjadikannya konten target) — **mengubah klasifikasi jalur browser**
  pada respons non-2xx: challenge/login kini terdeteksi di kedua jalur.
  Ini perubahan perilaku yang disengaja dan terukur;
  `tests/test_strategy_bench.py::TestObservationParity` mengunci perilakunya.
- `CDPBrowserAdapter.last_rss_kb` kini diisi setelah render — biaya memori
  browser dapat diukur, bukan diklaim.
- Bukti ter-commit memuat **dua cacat yang ditemukan saat review** dan
  sudah diperbaiki: (1) RSS yang selalu `None`; (2) cold start yang
  diam-diam mengukur HTTP (205 ms) karena `initial_transport` tidak
  disetel pada worker cold-start. `tests/test_strategy_bench.py::TestEvidenceIntegrity`
  mengunci kedua cacat itu agar tidak bisa kembali.
- Baseline internal: **bukan** klaim mengungguli Botasaurus (mandat
  INSTRUCTION.md). Perbandingan lintas-implementasi **bukan** bagian ADR ini;
 ia diukur terpisah di `docs/benchmark/engine-results-e14.json` (E14) dan
  dicatat di ADR-019. KOREKSI (ADR-019): alasan lama "engine HTTP Botasaurus
  tidak dapat dieksekusi di environment ini" ternyata SALAH — itu bug
  pemanggilan pada skrip baseline proyek ini, bukan batas platform.
- Biaya cold start ~5,4 s per eskalasi one-shot adalah batas nyata untuk
  jalur `uwae acquire --browser` pada environment phone — chromium
  persisten (ADR-014) adalah cara yang sudah diukur untuk menguranginya.
