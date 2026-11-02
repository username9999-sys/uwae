"""Confidence calibration (§3.2 INSTRUCTION.md).

Mandat: "confidence harus dikalibrasi terhadap corpus berlabel. Jika belum
ada dasar statistik untuk memberi probabilitas, gunakan kategori keyakinan
dan reason code terlebih dahulu."

Mekanisme ini membangun jalur kalibrasi TANPA memalsukan angka:

- bucket = state prediksi; akurasi bucket = precision dari korpus berlabel;
- bucket dengan sampel < ``min_samples`` → fallback ke konstanta kategorial
  (sampel kecil bukan dasar statistik — §3.2);
- tabel kosong / tidak disediakan → konstanta kategorial (perilaku saat ini,
  tetap sah menurut §3.2).

Korpus aktif (24 kasus sintetis + fixture) masih di bawah ``min_samples``
per bucket — sehingga konstanta kategorial tetap dipakai; tabel otomatis
terkalibrasi begitu korpus kegagalan nyata (E8+/real-target) bertumbuh.
"""

from typing import Dict, Iterable, Optional, Tuple


class CalibrationTable:
    """Peta bucket (state prediksi) → confidence terkalibrasi dari korpus.

    Sumber data: pasangan ``(bucket, benar)`` dari korpus berlabel, atau
    langsung confusion matrix harness evaluasi (``from_confusion_matrix``).
    """

    def __init__(self, min_samples: int = 10):
        if min_samples < 1:
            raise ValueError("min_samples harus >= 1")
        self.min_samples = min_samples
        self._correct: Dict[str, int] = {}
        self._total: Dict[str, int] = {}

    @classmethod
    def from_outcomes(
        cls,
        outcomes: Iterable[Tuple[str, bool]],
        min_samples: int = 10,
    ) -> "CalibrationTable":
        """Bangun tabel dari pasangan ``(bucket, benar)`` — satu entri per kasus."""
        table = cls(min_samples)
        for bucket, correct in outcomes:
            table._total[bucket] = table._total.get(bucket, 0) + 1
            if correct:
                table._correct[bucket] = table._correct.get(bucket, 0) + 1
        return table

    @classmethod
    def from_confusion_matrix(
        cls,
        confusion: Dict[str, Dict[str, int]],
        min_samples: int = 10,
    ) -> "CalibrationTable":
        """Bangun tabel dari confusion matrix harness evaluasi.

        Akurasi bucket "predicted X" = precision label X (kolom X pada
        matrix[expected][predicted]) — setiap sel di-expand per hitungan.
        """
        outcomes: list = []
        for expected, row in confusion.items():
            for predicted, count in row.items():
                outcomes.extend([(predicted, expected == predicted)] * count)
        return cls.from_outcomes(outcomes, min_samples)

    def confidence_for(self, bucket: str, default: float) -> float:
        """Confidence terkalibrasi untuk bucket — atau ``default`` (konstanta
        kategorial) bila sampel di bawah ``min_samples`` (§3.2: jangan
        memalsukan probabilitas tanpa dasar statistik)."""
        total = self._total.get(bucket, 0)
        if total < self.min_samples:
            return default
        return self._correct.get(bucket, 0) / total

    def sample_count(self, bucket: str) -> int:
        return self._total.get(bucket, 0)
