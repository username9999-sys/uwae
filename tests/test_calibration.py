"""Calibration tests (§3.2 INSTRUCTION.md): bucket-accuracy dengan fallback jujur.

Yang diverifikasi:
- tabel kosong / sampel di bawah ``min_samples`` → fallback ke konstanta
  kategorial (jangan memalsukan probabilitas tanpa dasar statistik — §3.2);
- sampel cukup → confidence terkalibrasi (akurasi bucket);
- ``from_confusion_matrix`` meng-expand hitungan sel dengan benar;
- integrasi ``classify(calibration=...)``: override hanya untuk bucket yang
  memenuhi ambang; determinisme tetap terjaga;
- korpus aktif (24 kasus) di bawah ambang → fallback (status jujur saat
  ini); dengan ambang rendah → precision sempurna 1.0.
"""

import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from universal_web_acquisition.access.calibration import CalibrationTable
from universal_web_acquisition.access.classifier import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    Signal,
    classify,
)
from universal_web_acquisition.access.model import Observation
from universal_web_acquisition.benchmark.classifier_eval import build_calibration_table

DECIDED_AT = datetime(2026, 1, 1)


def _obs(signal, value):
    return Observation(
        observation_id=f"obs-{signal}-{value}",
        signal=signal,
        value=value,
        recorded_at=DECIDED_AT,
        source="test",
    )


def _granted_observations():
    return [_obs(Signal.HTTP_STATUS, "200"), _obs(Signal.TARGET_MARKER, "found")]


def _classify(observations, calibration=None):
    return classify(
        observations,
        assessment_id="cal-1",
        job_id="cal",
        attempt_id="cal",
        transport_id="test",
        decided_at=DECIDED_AT,
        calibration=calibration,
    )


class TestCalibrationTable:
    def test_empty_table_falls_back_to_defaults(self):
        table = CalibrationTable()
        assert table.confidence_for("access_granted", CONFIDENCE_HIGH) == CONFIDENCE_HIGH
        assert table.sample_count("access_granted") == 0

    def test_small_sample_falls_back_to_default(self):
        # 5 sampel < min_samples 10 → jangan memalsukan probabilitas (§3.2)
        outcomes = [("access_granted", True)] * 4 + [("access_granted", False)]
        table = CalibrationTable.from_outcomes(outcomes, min_samples=10)
        assert table.confidence_for("access_granted", CONFIDENCE_HIGH) == CONFIDENCE_HIGH

    def test_sufficient_sample_calibrates(self):
        outcomes = [("rate_limited", True)] * 18 + [("rate_limited", False)] * 2
        table = CalibrationTable.from_outcomes(outcomes, min_samples=10)
        assert table.confidence_for("rate_limited", CONFIDENCE_HIGH) == pytest.approx(0.9)

    def test_from_confusion_matrix_expands_counts(self):
        confusion = {"a": {"a": 3, "b": 1}, "b": {"b": 4}}
        table = CalibrationTable.from_confusion_matrix(confusion, min_samples=3)
        # bucket "a" (predicted): kolom a = 3 benar dari 3 → 1.0
        assert table.confidence_for("a", 0.0) == 1.0
        # bucket "b" (predicted): kolom b = 4 benar dari 5 — menerima 1 FP
        # dari expected "a" (semantik precision) → 0.8
        assert table.confidence_for("b", 0.0) == pytest.approx(0.8)

    def test_min_samples_must_be_positive(self):
        with pytest.raises(ValueError):
            CalibrationTable(min_samples=0)


class TestClassifyIntegration:
    def test_without_calibration_uses_constants(self):
        assessment = _classify(_granted_observations())
        assert assessment.confidence == CONFIDENCE_HIGH
        assert assessment.state.value == "access_granted"

    def test_with_calibration_overrides_confidence(self):
        # bucket access_granted: 1 benar dari 2 → 0.5 (min_samples=1)
        table = CalibrationTable.from_outcomes(
            [("access_granted", True), ("access_granted", False)], min_samples=1
        )
        assessment = _classify(_granted_observations(), calibration=table)
        assert assessment.confidence == pytest.approx(0.5)

    def test_calibration_fallback_for_unknown_bucket(self):
        # bucket lain yang terkalibrasi tidak memengaruhi state ini
        table = CalibrationTable.from_outcomes([("rate_limited", True)], min_samples=1)
        assessment = _classify(_granted_observations(), calibration=table)
        assert assessment.confidence == CONFIDENCE_HIGH

    def test_determinism_with_calibration(self):
        table = CalibrationTable.from_outcomes(
            [("access_granted", True)] * 12, min_samples=10
        )
        first = _classify(_granted_observations(), calibration=table)
        second = _classify(_granted_observations(), calibration=table)
        assert first == second
        assert first.confidence == pytest.approx(1.0)


class TestCorpusCalibration:
    def test_corpus_below_min_samples_falls_back(self):
        # Korpus gabungan (sintetis + nyata): granted 12 sampel → TERKALIBRASI
        # (kalibrasi dari run nyata aktif); bucket < 10 sampel tetap fallback
        table = build_calibration_table()
        assert table.confidence_for("access_granted", CONFIDENCE_HIGH) == 1.0
        assert table.confidence_for("unknown", CONFIDENCE_LOW) == CONFIDENCE_LOW

    def test_corpus_with_low_min_samples_is_perfect(self):
        # precision korpus 1.0 → semua bucket terkalibrasi ke 1.0
        table = build_calibration_table(min_samples=1)
        assert table.confidence_for("access_granted", 0.0) == 1.0
        assert table.confidence_for("unknown", 0.0) == 1.0
        assert table.confidence_for("network_failure", 0.0) == 1.0
