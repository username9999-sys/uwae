# E5 — Failure Isolation

TEXT.md eksperimen E5: *"satu URL mengalami timeout atau error permanen
sementara pekerjaan lain harus tetap selesai."*

Angka di bawah DIHASILKAN dari `engine-results-e13.json` — jangan diedit manual.

## Hasil per skenario

| Skenario | Job sehat sukses | Job bermasalah | Batch meledak | Hasil lengkap | Batch ms | Sesuai ground truth |
|---|---|---|---|---|---|---|
| `healthy_only` | True | — | tidak | lengkap | 2582.6 | ya |
| `timeout_fault` | True | failed (`budget_exhausted: Timeout: Failed to perform, cu`) | tidak | lengkap | 8947.59 | ya |
| `permanent_error_fault` | True | failed (`http_4xx: HTTP 404 untuk http://127.0.0.1:8781/m`) | tidak | lengkap | 2909.75 | ya |
| `unexpected_exception_fault` | True | failed (`internal_error: RuntimeError: injected non-trans`) | tidak | lengkap | 2381.53 | ya |

## Kesimpulan

- Skenario terukur: **4**; seluruhnya sesuai ground truth: **True**.
- Batch yang meledak: **tidak ada**.
- Batch dengan hasil hilang: **tidak ada**.

## Metodologi

- tiap skenario = satu batch 12 job (11 sehat + 1 bermasalah) pada `ConcurrentJobRunner` dengan 4 thread — jalur produksi `uwae crawl --concurrency N`;
- fault timeout: endpoint `/hang` fixture (server tidak merespons) + timeout klien 2.0 s;
- fault error permanen: 404 (`/missing`);
- fault tak terduga: worker yang gagal DI LUAR try worker (simulasi kegagalan DB);
- ground truth berasal dari semantika skenario, bukan dari output engine.

## Batasan

- baseline internal UWAE; tidak ada perbandingan lintas-implementasi di sini.
