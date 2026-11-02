"""Export adapters (lapisan Knowledge — TEXT.md): hasil ekstraksi → file.

Kontrak jujur:

- sumber data = event audit ``extraction`` yang SUDAH tercatat (bukan
  re-ekstraksi) — apa yang diekspor persis apa yang tercatat;
- JSON = lossless (``fields`` tetap objek bersarang); CSV = kolom tetap +
  ``fields`` sebagai string JSON (lossless juga, hanya bentuknya yang pipih);
- tanpa event ekstraksi → error jujur di pemanggil, tanpa file kosong palsu.
"""
