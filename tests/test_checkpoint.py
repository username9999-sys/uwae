"""Modul checkpoint bersama untuk harness benchmark E14/E15/E16.

Yang diuji di sini adalah PROPERTI yang dijaga modul ini, karena tiga
harness bergantung padanya:

- append-only: satu baris JSON per run, ditulis dengan flush + fsync;
- tahan mati mendadak: baris terakhir yang terpotong diabaikan, sisanya
  tetap terpakai;
- disiplin sidik jari: record dengan fingerprint berbeda diabaikan dan
  DIHITUNG, tidak pernah dipakai diam-diam;
- menyimpan ROW KASAR: adjudication bisa berubah tanpa mengulang benchmark;
- backward compatibility: file checkpoint yang dibuat sebelum modul ini ada
  (skema ``scenario_id``/``arm_id``/``run_index``) tetap terbaca — kalau
  tidak, 480 run E16 yang sudah dibayar mahal akan hilang tanpa sebab.
"""

import json

import pytest

from universal_web_acquisition.benchmark._checkpoint import (
    Checkpoint,
    DEFAULT_INTERRUPTION_GAP_THRESHOLD_S,
    execution_sessions,
    timing_evidence,
)

FP_A = "a" * 64
FP_B = "b" * 64


def _write(path, records):
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )


def _record(scope, subject, index, row, fingerprint=FP_A):
    return {
        "fingerprint": fingerprint,
        "scope_id": scope,
        "subject_id": subject,
        "index": index,
        "row": row,
    }


# --------------------------------------------------------------------------
# Penyimpanan
# --------------------------------------------------------------------------


def test_a_fresh_checkpoint_is_empty(tmp_path):
    checkpoint = Checkpoint(tmp_path / "cp.jsonl", FP_A)
    assert checkpoint.rows == {}
    assert checkpoint.get("s", "a", 0) is None
    assert checkpoint.stats()["runs_in_checkpoint"] == 0


def test_an_appended_run_is_returned_by_get(tmp_path):
    checkpoint = Checkpoint(tmp_path / "cp.jsonl", FP_A)
    checkpoint.append("s", "a", 0, {"status_code": 200})
    assert checkpoint.get("s", "a", 0) == {"status_code": 200}


def test_get_marks_the_run_as_reused(tmp_path):
    checkpoint = Checkpoint(tmp_path / "cp.jsonl", FP_A)
    checkpoint.append("s", "a", 0, {"status_code": 200})
    assert checkpoint.stats()["runs_reused"] == 0
    checkpoint.get("s", "a", 0)
    assert checkpoint.stats()["runs_reused"] == 1


def test_different_scopes_do_not_collide(tmp_path):
    checkpoint = Checkpoint(tmp_path / "cp.jsonl", FP_A)
    checkpoint.append("s1", "a", 0, {"n": 1})
    checkpoint.append("s2", "a", 0, {"n": 2})
    checkpoint.append("s1", "b", 0, {"n": 3})
    assert checkpoint.get("s1", "a", 0) == {"n": 1}
    assert checkpoint.get("s2", "a", 0) == {"n": 2}
    assert checkpoint.get("s1", "b", 0) == {"n": 3}
    assert checkpoint.stats()["runs_in_checkpoint"] == 3


def test_rows_survive_a_reload(tmp_path):
    """Yang ditulis harus tetap ada setelah proses berikutnya membacanya."""
    path = tmp_path / "cp.jsonl"
    first = Checkpoint(path, FP_A)
    first.append("s", "a", 0, {"status_code": 200, "body_sha256": "abc"})
    first.append("s", "a", 1, {"status_code": 404})

    second = Checkpoint(path, FP_A)
    assert second.get("s", "a", 0)["body_sha256"] == "abc"
    assert second.get("s", "a", 1)["status_code"] == 404


def test_the_last_line_wins_for_a_repeated_key(tmp_path):
    """Append-only: baris yang sama boleh ditulis ulang, baris terakhir yang berlaku.

    Ini yang dipakai untuk melengkapi row dengan peak memory skenario yang
    baru diketahui setelah loop skenario selesai.
    """
    path = tmp_path / "cp.jsonl"
    first = Checkpoint(path, FP_A)
    first.append("s", "a", 0, {"elapsed_ms": 1.0})
    first.append("s", "a", 0, {"elapsed_ms": 1.0, "peak_memory_bytes": 999})

    reloaded = Checkpoint(path, FP_A)
    assert reloaded.get("s", "a", 0)["peak_memory_bytes"] == 999


# --------------------------------------------------------------------------
# Disiplin sidik jari
# --------------------------------------------------------------------------


def test_records_with_another_fingerprint_are_ignored_and_counted(tmp_path):
    """Run lama tidak boleh dicampur diam-diam dengan run baru."""
    path = tmp_path / "cp.jsonl"
    _write(
        path,
        [
            _record("s", "a", 0, {"n": 1}, fingerprint=FP_A),
            _record("s", "a", 1, {"n": 2}, fingerprint=FP_B),
        ],
    )
    checkpoint = Checkpoint(path, FP_A)
    assert checkpoint.get("s", "a", 0) == {"n": 1}
    assert checkpoint.get("s", "a", 1) is None
    assert checkpoint.stats()["records_ignored"] == 1


def test_the_fingerprint_is_published_in_the_stats(tmp_path):
    checkpoint = Checkpoint(tmp_path / "cp.jsonl", FP_A)
    assert checkpoint.stats()["harness_fingerprint"] == FP_A


# --------------------------------------------------------------------------
# Ketahanan terhadap mati mendadak
# --------------------------------------------------------------------------


def test_a_truncated_last_line_does_not_break_loading(tmp_path):
    """Proses bisa mati tepat saat menulis; baris rusak tidak boleh
    menggagalkan seluruh checkpoint."""
    path = tmp_path / "cp.jsonl"
    path.write_text(
        json.dumps(_record("s", "a", 0, {"n": 1})) + "\n"
        + json.dumps(_record("s", "a", 1, {"n": 2}))[:20],
        encoding="utf-8",
    )
    checkpoint = Checkpoint(path, FP_A)
    assert checkpoint.get("s", "a", 0) == {"n": 1}
    assert checkpoint.get("s", "a", 1) is None
    assert checkpoint.stats()["records_ignored"] == 1


def test_a_record_missing_its_key_fields_is_ignored(tmp_path):
    path = tmp_path / "cp.jsonl"
    _write(path, [{"fingerprint": FP_A, "row": {"n": 1}}])
    checkpoint = Checkpoint(path, FP_A)
    assert checkpoint.stats()["runs_in_checkpoint"] == 0
    assert checkpoint.stats()["records_ignored"] == 1


def test_a_corrupt_line_in_the_middle_does_not_lose_the_other_rows(tmp_path):
    path = tmp_path / "cp.jsonl"
    path.write_text(
        json.dumps(_record("s", "a", 0, {"n": 1})) + "\n"
        + "{bukan json\n"
        + json.dumps(_record("s", "a", 2, {"n": 3})) + "\n",
        encoding="utf-8",
    )
    checkpoint = Checkpoint(path, FP_A)
    assert checkpoint.get("s", "a", 0) == {"n": 1}
    assert checkpoint.get("s", "a", 2) == {"n": 3}
    assert checkpoint.stats()["records_ignored"] == 1


# --------------------------------------------------------------------------
# Backward compatibility
# --------------------------------------------------------------------------


def test_the_legacy_schema_is_still_readable(tmp_path):
    """File checkpoint sebelum modul ini ada memakai kunci lain.

    Kalau tidak dibaca, 480 run E16 yang sudah dibayar mahal dengan waktu
    device akan hilang tanpa sebab.
    """
    path = tmp_path / "cp.jsonl"
    _write(
        path,
        [
            {
                "fingerprint": FP_A,
                "scenario_id": "b01_small_get",
                "arm_id": "uwae-adaptive",
                "run_index": 7,
                "row": {"elapsed_ms": 12.5},
            }
        ],
    )
    checkpoint = Checkpoint(path, FP_A)
    assert checkpoint.get("b01_small_get", "uwae-adaptive", 7) == {
        "elapsed_ms": 12.5
    }


# --------------------------------------------------------------------------
# Sesi eksekusi
# --------------------------------------------------------------------------


def _row(stamp, elapsed_ms=100.0):
    return {"recorded_at": stamp, "elapsed_ms": elapsed_ms}


def test_execution_sessions_split_on_a_long_gap():
    rows = [
        _row("2026-10-27T10:00:00+00:00"),
        _row("2026-10-27T10:00:10+00:00"),
        _row("2026-10-27T10:30:00+00:00"),
    ]
    sessions = execution_sessions(rows, 60.0)
    assert len(sessions) == 2
    assert sessions[0]["runs"] == 2
    assert sessions[1]["runs"] == 1
    assert sessions[1]["gap_before_s"] == pytest.approx(1790.0)


def test_execution_sessions_do_not_split_on_a_short_gap():
    rows = [
        _row("2026-10-27T10:00:00+00:00"),
        _row("2026-10-27T10:00:37+00:00"),
    ]
    sessions = execution_sessions(rows, 60.0)
    assert len(sessions) == 1
    assert sessions[0]["runs"] == 2


def test_execution_sessions_report_the_fixture_base_urls_per_session():
    rows = [
        {**_row("2026-10-27T10:00:00+00:00"), "fixture_base_url": "http://a"},
        {**_row("2026-10-27T10:30:00+00:00"), "fixture_base_url": "http://b"},
    ]
    sessions = execution_sessions(rows, 60.0)
    assert sessions[0]["fixture_base_urls"] == ["http://a"]
    assert sessions[1]["fixture_base_urls"] == ["http://b"]


def test_execution_sessions_ignore_rows_without_a_timestamp():
    rows = [{"elapsed_ms": 5.0}, _row("2026-10-27T10:00:00+00:00")]
    sessions = execution_sessions(rows, 60.0)
    assert sessions[0]["runs"] == 1


def test_the_default_interruption_threshold_is_sixty_seconds():
    assert DEFAULT_INTERRUPTION_GAP_THRESHOLD_S == 60.0


# --------------------------------------------------------------------------
# Blok durasi
# --------------------------------------------------------------------------


def test_timing_evidence_sums_the_measured_execution_time():
    rows = [
        {"elapsed_ms": 1000.0, "recorded_at": "2026-10-27T10:00:00+00:00"},
        {"elapsed_ms": 2500.0, "recorded_at": "2026-10-27T10:00:05+00:00"},
    ]
    timing = timing_evidence(rows, {"runs_reused": 0}, 12.3)
    assert timing["measured_arm_execution_s_total"] == pytest.approx(3.5)
    assert timing["measured_arm_execution_runs"] == 2


def test_timing_evidence_rounds_the_total_to_two_decimals():
    """Pembulatan dua desimal — format yang sama dipakai evidence E16."""
    rows = [
        {"elapsed_ms": 3500.5, "recorded_at": "2026-10-27T10:00:00+00:00"},
    ]
    timing = timing_evidence(rows, {"runs_reused": 0}, 1.0)
    assert timing["measured_arm_execution_s_total"] == 3.5


def test_timing_evidence_separates_the_measurement_window_from_the_invocation():
    rows = [
        {"elapsed_ms": 1000.0, "recorded_at": "2026-10-27T10:00:00+00:00"},
        {"elapsed_ms": 1000.0, "recorded_at": "2026-10-27T10:00:10+00:00"},
    ]
    timing = timing_evidence(rows, {"runs_reused": 0}, 0.5)
    assert timing["measurement_window"]["wall_clock_span_s"] == pytest.approx(10.0)
    assert timing["harness_invocation"]["wall_clock_s"] == pytest.approx(0.5)


def test_timing_evidence_reports_how_many_runs_were_reused():
    """Jumlah run yang dieksekusi pada pemanggilan ini harus bisa dihitung."""
    rows = [{"elapsed_ms": 1.0, "recorded_at": "2026-10-27T10:00:00+00:00"}] * 10
    timing = timing_evidence(rows, {"runs_reused": 10}, 0.2)
    assert timing["harness_invocation"]["runs_executed_this_invocation"] == 0
    assert timing["harness_invocation"]["runs_reused_from_checkpoint"] == 10


def test_timing_evidence_states_that_the_invocation_excludes_checkpointed_runs():
    rows = [{"elapsed_ms": 1.0, "recorded_at": "2026-10-27T10:00:00+00:00"}]
    timing = timing_evidence(rows, {"runs_reused": 1}, 0.2)
    assert "TIDAK mencakup" in timing["harness_invocation"]["note"]


def test_timing_evidence_publishes_no_bare_elapsed_s():
    """Nama yang sama dengan makna berbeda akan terus menyesatkan."""
    rows = [{"elapsed_ms": 1.0, "recorded_at": "2026-10-27T10:00:00+00:00"}]
    timing = timing_evidence(rows, {"runs_reused": 0}, 0.2)
    assert "elapsed_s" not in timing
    assert "measured_arm_execution_s_total" in timing
