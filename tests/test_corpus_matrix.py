"""E17 — matriks korpus vonis UWAE vs Botasaurus (Tahap G).

Yang diuji di sini BUKAN angka benchmark (angka itu bukti yang di-commit),
melainkan INVARIAN matriks korpus — invarian yang menjaga agregasi tetap
jujur:

- vonis korpus harus bisa DIREKONSTRUKSI dari evidence sumber: matriks
  ini merangkum, bukan inventing;
- aturan vonis harus SERAGAM untuk semua slot — jika dua slot memakai
  aturan berbeda, perbandingan antar-slot jadi tidak valid;
- run yang tidak bisa dinilai harus keluar dari penyebut kapabilitas dan
  muncul sebagai "belum teruji", tidak pernah dihitung sebagai gagal;
- slot yang bukan differential lintas-implementasi (mis. E9, E12) tidak boleh
  masuk korpus, karena vonisnya bukan UWAE-vs-baseline;
- closure celah harus menunjuk slot yang benar-benar ada dan terukur;
- jumlah korpus adalah jumlah INSTANSI perbandingan, bukan jumlah skenario
  unik, dan itu harus dinyatakan eksplisit.
"""

import json
from pathlib import Path

import pytest

from universal_web_acquisition.benchmark import corpus_matrix
from universal_web_acquisition.benchmark.corpus_matrix import (
    BENCHMARK_ID,
    DECLARED_GAP_CLOSURES,
    _detect_schema,
    _summarise_rows,
    build_corpus,
    comparison_outcome,
    discover_slots,
    row_is_untested,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = REPO_ROOT / "docs" / "benchmark"
EVIDENCE_PATH = BENCHMARK_DIR / "engine-results-e17.json"


@pytest.fixture(scope="module")
def corpus():
    return build_corpus()


@pytest.fixture(scope="module")
def evidence():
    return json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Aturan vonis
# --------------------------------------------------------------------------


def test_comparison_outcome_picks_the_winner_on_equal_denominators():
    uwae = {"runs": 30, "evaluated_runs": 30, "primary_success_runs": 30,
            "untested_runs": 0}
    baseline = {"runs": 30, "evaluated_runs": 30, "primary_success_runs": 0,
                "untested_runs": 0}
    assert comparison_outcome(uwae, baseline) == "uwae"
    assert comparison_outcome(baseline, uwae) == "baseline"


def test_comparison_outcome_reports_a_tie():
    cell = {"runs": 5, "evaluated_runs": 5, "primary_success_runs": 3,
            "untested_runs": 0}
    assert comparison_outcome(cell, dict(cell)) == "tie"


def test_comparison_outcome_refuses_to_choose_when_the_two_bounds_disagree():
    """Batas dievaluasi dan batas seluruh attempt boleh berbeda nisso.

    Skenario: UWAE 3/10 sukses atas seluruh attempt dan 3/10 atas run
    yang dievaluasi (0,30). Baseline punya 10 attempt tapi hanya 3 yang
    bisa dinilai, dan 1 di antaranya sukses: 1/3 = 0,33 atas run yang
    dievaluasi, tapi 1/10 = 0,10 atas seluruh attempt.

    Pada batas "dievaluasi" baseline menang (0,33 > 0,30), pada batas
    "seluruh attempt" UWAE menang (0,30 > 0,10). Bukti yang ada tidak cukup
    memilih, jadi vonisnya ``not_comparable`` dan TIDAK boleh diberikan ke
    lengan mana pun.
    """
    uwae = {"runs": 10, "evaluated_runs": 10, "primary_success_runs": 3,
            "untested_runs": 0}
    baseline = {"runs": 10, "evaluated_runs": 3, "primary_success_runs": 1,
                "untested_runs": 7}
    assert comparison_outcome(uwae, baseline) == "not_comparable"
    assert comparison_outcome(baseline, uwae) == "not_comparable"


def test_comparison_outcome_keeps_the_verdict_when_both_bounds_agree():
    """Run belum-teruji tidak otomatis membuat vonis jadi kabur.

    Di sini kedua batas memberi urutan yang sama (UWAE menang di keduanya),
    jadi vonisnya tetap pasti meski salah satu sisi punya run yang belum
    bisa dinilai.
    """
    uwae = {"runs": 10, "evaluated_runs": 3, "primary_success_runs": 3,
            "untested_runs": 7}
    baseline = {"runs": 3, "evaluated_runs": 3, "primary_success_runs": 0,
                "untested_runs": 0}
    assert comparison_outcome(uwae, baseline) == "uwae"


def test_comparison_outcome_reports_no_evaluable_runs():
    empty = {"runs": 0, "evaluated_runs": 0, "primary_success_runs": 0,
             "untested_runs": 0}
    good = {"runs": 3, "evaluated_runs": 3, "primary_success_runs": 3,
            "untested_runs": 0}
    assert comparison_outcome(empty, good) == "no_evaluable_runs"
    assert comparison_outcome(good, empty) == "no_evaluable_runs"


def test_a_side_with_only_untested_runs_cannot_win():
    """Lengan yang tidak punya run yang bisa dinilai tidak boleh menang."""
    untested = {"runs": 5, "evaluated_runs": 0, "primary_success_runs": 0,
                "untested_runs": 5}
    good = {"runs": 5, "evaluated_runs": 5, "primary_success_runs": 5,
            "untested_runs": 0}
    assert comparison_outcome(untested, good) == "no_evaluable_runs"


# --------------------------------------------------------------------------
# Run yang belum bisa dinilai
# --------------------------------------------------------------------------


def test_runtime_failure_counts_as_untested():
    assert row_is_untested({"runtime_failure": "timeout"})


def test_error_without_body_or_status_counts_as_untested():
    assert row_is_untested({"error": "chromium gagal start"})


def test_error_with_a_body_is_not_untested():
    """Lengan yang melaporkan error TAPI menghasilkan body tetap dievaluasi.

    Yang dinilai adalah capability engine-nya; error-nya sudah tercermin di
    row itu sendiri.
    """
    assert not row_is_untested({"error": "timeout", "body_sha256": "abc",
                                "status_code": 200})


def test_empty_outcome_counts_as_untested():
    assert row_is_untested({})


def test_summarise_rows_excludes_untested_from_the_capability_denominator():
    rows = [
        {"reached_protected": True, "status_code": 200},
        {"reached_protected": False, "status_code": 403},
        {"runtime_failure": "timeout"},
        {"error": "gagal", "body_sha256": None, "status_code": None},
    ]
    cell = _summarise_rows(rows)
    assert cell["runs"] == 4
    assert cell["evaluated_runs"] == 2
    assert cell["primary_success_runs"] == 1
    assert cell["untested_runs"] == 2


# --------------------------------------------------------------------------
# Pemilihan slot
# --------------------------------------------------------------------------


def test_only_cross_implementation_slots_enter_the_corpus():
    """Evidence yang bukan UWAE-vs-baseline tidak boleh masuk korpus.

    E9 punya key ``engines`` tapi tidak punya baseline Botasaurus; E12
    mengukur strategi UWAE terhadap dirinya sendiri. Keduanya tidak punya
    vonis yang bisa dibandingkan.

    E18/E19 adalah backfill §6.3 (n=30) dari E14/E15: skema DAN dimensi sama,
    hanya jumlah run lebih besar. Keduanya masuk korpus sebagai slot
    tersendiri lalu men-supersede slot lamanya.
    """
    slots = dict(discover_slots())
    assert set(slots) == {"E14", "E15", "E16", "E18", "E19", "E20", "E21", "E22"}


def test_non_differential_evidence_is_rejected_by_the_schema_detector():
    e9 = json.loads(
        (BENCHMARK_DIR / "engine-results-e9.json").read_text(encoding="utf-8")
    )
    e12 = json.loads(
        (BENCHMARK_DIR / "engine-results-e12.json").read_text(encoding="utf-8")
    )
    assert _detect_schema(e9) is None
    assert _detect_schema(e12) is None


def test_each_differential_evidence_is_recognised():
    for name, expected in (
        ("engine-results-e14.json", "e14_like"),
        ("engine-results-e15.json", "e15_like"),
        ("engine-results-e16.json", "e16_like"),
        # Backfill §6.3: skema identik dengan slot asal, hanya n lebih besar.
        ("engine-results-e18.json", "e14_like"),
        ("engine-results-e19.json", "e15_like"),
        # E20/E21: ekstensi POST HTTP (skema e14_like, dimensi http-post).
        ("engine-results-e20.json", "e14_like"),
        ("engine-results-e21.json", "e14_like"),
        # E22: POST via browser form (skema e16_like, summary.comparisons).
        ("engine-results-e22.json", "e16_like"),
    ):
        doc = json.loads((BENCHMARK_DIR / name).read_text(encoding="utf-8"))
        assert _detect_schema(doc) == expected, name


# --------------------------------------------------------------------------
# Matriks korpus
# --------------------------------------------------------------------------


def test_corpus_has_a_stable_benchmark_id(corpus):
    assert corpus["benchmark_id"] == BENCHMARK_ID


def test_corpus_publishes_all_four_verdict_classes_separately(corpus):
    """TEXT.md:1427 -- menang, seri, kalah, dan belum teruji terpisah."""
    totals = corpus["summary"]["corpus_totals"]
    for key in (
        "uwae_wins",
        "ties",
        "baseline_wins",
        "not_comparable",
        "no_evaluable_runs",
        "untested_runs_total",
    ):
        assert key in totals, key
        assert isinstance(totals[key], int), key


def _active_slots(corpus):
    """Slot yang dihitung korpus.

    Slot tersuspen tetap dipublikasikan sebagai rekaman historis, tapi
    vonisnya tidak boleh masuk hitungan — kalau ikut, dimensi yang sama
    terhitung dua kali (E14 dan E18 mengukur skenario yang identik).
    """
    return [slot for slot in corpus["slots"] if slot["status"] == "active"]


def test_corpus_totals_equal_the_sum_of_the_slots(corpus):
    totals = corpus["summary"]["corpus_totals"]
    for key in totals:
        expected = sum(slot["totals"][key] for slot in _active_slots(corpus))
        assert totals[key] == expected, key


def test_dimension_totals_equal_the_sum_of_the_slots(corpus):
    for dimension, bucket in corpus["dimensions"].items():
        expected = {"uwae_wins": 0, "ties": 0, "baseline_wins": 0,
                    "not_comparable": 0, "no_evaluable_runs": 0,
                    "untested_runs_total": 0}
        for slot in _active_slots(corpus):
            if slot["dimension"] != dimension:
                continue
            for key in expected:
                expected[key] += slot["totals"][key]
        assert bucket == expected, dimension


def test_superseded_slots_are_published_but_not_counted(corpus):
    """Slot lama tetap terlihat, tapi TIDAK boleh dihitung dua kali.

    Ini yang membedakan "backfill" dari "menulis ulang": bukti lamanya
    utuh dan tercetak, sementara hitungan korpus hanya berdiri di atas slot
    aktif.
    """
    active = _active_slots(corpus)
    superseded = [s for s in corpus["slots"] if s["status"] == "superseded"]
    assert superseded, "backfill harus menyisakan slot tersuspen yang terekam"

    totals = corpus["summary"]["corpus_totals"]
    counted = sum(slot["totals"]["uwae_wins"] for slot in active)
    assert totals["uwae_wins"] == counted
    # Kalau slot tersuspen ikut dihitung, angkanya jadi lebih besar.
    assert totals["uwae_wins"] < sum(
        slot["totals"]["uwae_wins"] for slot in corpus["slots"]
    )

    # Dimensi yang sama BOLEH punya beberapa slot aktif selama mengukur
    # skenario BERBEDA (E20/E21/E22 adalah ekstensi http-post: p01-p04,
    # p05-p06, p07). Yang tidak boleh: pasangan (skenario, arm) yang sama
    # dihitung dua kali (itu baru double counting, mis. kalau backfill tidak
    # men-supersede). Satu slot bisa mengandung beberapa comparisons untuk
    # satu skenario selama pasangan arm-nya berbeda (E16: 4 arm).
    seen: dict = {}
    for slot in active:
        for comp in slot.get("comparisons") or []:
            key = (
                slot["dimension"],
                comp.get("scenario_id"),
                comp.get("uwae_arm"),
                comp.get("baseline_arm"),
            )
            assert key not in seen, (
                f"comparison {key} dihitung dua kali oleh {seen.get(key)} dan {slot['slot']}"
            )
            seen[key] = slot["slot"]


def test_every_comparison_carries_the_numbers_it_was_derived_from(corpus):
    """Supaya matriks bisa diaudit ulang, bukan hanya dipercaya."""
    for slot in corpus["slots"]:
        for comparison in slot["comparisons"]:
            assert comparison["uwae"]["runs"] >= 0
            assert comparison["baseline"]["runs"] >= 0
            assert comparison["uwae"]["evaluated_runs"] <= comparison["uwae"]["runs"]
            assert (
                comparison["baseline"]["evaluated_runs"]
                <= comparison["baseline"]["runs"]
            )
            assert comparison["verdict"] in {
                "uwae",
                "baseline",
                "tie",
                "not_comparable",
                "no_evaluable_runs",
            }


def test_every_slot_states_where_its_verdicts_came_from(corpus):
    for slot in corpus["slots"]:
        for comparison in slot["comparisons"]:
            assert comparison["verdict_source"] in {"explicit", "derived"}
            assert comparison["evaluated_basis"] in {"raw_rows", "published_runs_only"}


def test_explicit_verdicts_are_not_re_derived(corpus):
    """Slot E16 sudah punya vonis -- matriks harus mengambilnya apa adanya."""
    e16 = next(slot for slot in corpus["slots"] if slot["slot"] == "E16")
    source = json.loads(
        (BENCHMARK_DIR / "engine-results-e16.json").read_text(encoding="utf-8")
    )
    expected = {
        (entry["scenario_id"], entry["uwae_arm"], entry["baseline_arm"]):
        entry["outcome"]
        for entry in source["summary"]["comparisons"]
    }
    actual = {
        (entry["scenario_id"], entry["uwae_arm"], entry["baseline_arm"]):
        entry["verdict"]
        for entry in e16["comparisons"]
    }
    assert actual == expected


def test_corpus_counts_are_instance_counts_not_unique_scenarios(corpus):
    """Jumlah korpus adalah instansi perbandingan, dan itu dinyatakan."""
    assert "INSTANSI perbandingan" in corpus["method"]["counts_are"]
    instances = sum(len(slot["comparisons"]) for slot in _active_slots(corpus))
    totals = corpus["summary"]["corpus_totals"]
    assert instances == (
        totals["uwae_wins"]
        + totals["ties"]
        + totals["baseline_wins"]
        + totals["not_comparable"]
        + totals["no_evaluable_runs"]
    )


def test_corpus_makes_no_overall_superiority_claim(corpus):
    """Tidak ada klaim UWAE unggul secara keseluruhan."""
    interpretation = corpus["summary"]["interpretation"]
    assert "Tidak ada klaim" in interpretation


# --------------------------------------------------------------------------
# Celah yang dideklarasikan
# --------------------------------------------------------------------------


def test_declared_gaps_are_collected_with_their_reason(corpus):
    gaps = corpus["declared_gaps"]
    assert gaps
    for gap in gaps:
        assert gap["scenario_id"]
        assert gap["reason"], gap["scenario_id"]
        assert gap["declared_in"]
        assert gap["status"] in {"open", "closed"}


def test_declared_gap_closure_points_at_a_slot_that_exists_and_is_measured(corpus):
    by_slot = {slot["slot"]: slot for slot in corpus["slots"]}
    for scenario_id, closure in DECLARED_GAP_CLOSURES.items():
        target = by_slot.get(closure["closed_by"])
        assert target is not None, scenario_id
        assert target["comparisons"], scenario_id


def test_a_closure_cannot_be_claimed_for_a_slot_that_was_not_measured():
    """Closure celah tidak boleh jadi klaim naratif tanpa bukti."""
    slots = [
        {"slot": "E16", "comparisons": [{"verdict": "tie"}], "declared_gaps": []},
    ]
    with pytest.raises(ValueError):
        corpus_matrix._validate_gap_closures(slots)


def test_declared_gaps_are_published_separately_from_verdicts(corpus):
    """Cakupan dan kemampuan adalah dua hal berbeda."""
    assert "declared_gaps_total" in corpus["summary"]
    assert "declared_gaps_closed" in corpus["summary"]
    assert corpus["summary"]["declared_gaps_closed"] <= corpus["summary"][
        "declared_gaps_total"
    ]


# --------------------------------------------------------------------------
# Evidence yang di-commit harus cocok dengan harness
# --------------------------------------------------------------------------


def test_committed_evidence_matches_the_harness_output(corpus, evidence):
    """Bukti yang di-commit harus bisa direproduksi dari evidence sumber."""
    assert evidence["benchmark_id"] == corpus["benchmark_id"]
    assert (
        evidence["summary"]["corpus_totals"] == corpus["summary"]["corpus_totals"]
    )
    assert len(evidence["slots"]) == len(corpus["slots"])
    for published, rebuilt in zip(evidence["slots"], corpus["slots"]):
        assert published["slot"] == rebuilt["slot"]
        assert published["totals"] == rebuilt["totals"]
        assert len(published["comparisons"]) == len(rebuilt["comparisons"])


def test_corpus_does_not_run_any_benchmark(corpus):
    """Matriks korpus merangkum; ia tidak mengukur."""
    assert "tidak menjalankan benchmark" in corpus["method"]["no_new_runs"]


# --------------------------------------------------------------------------
# Supersession -- backfill n>=30 tidak boleh menghitung ganda
# --------------------------------------------------------------------------


def test_a_superseding_slot_replaces_the_old_slot_in_the_counts():
    """Backfill menambah slot dengan dimensi sama; korpus tidak boleh menghitung
    skenario itu dua kali."""
    slot_entries = [
        {
            "slot": "E14",
            "source": "engine-results-e14.json",
            "dimension": "http-transport",
            "totals": {
                "uwae_wins": 7, "ties": 6, "baseline_wins": 0,
                "not_comparable": 0, "no_evaluable_runs": 0,
                "untested_runs_total": 0,
            },
            "comparisons": [{"verdict": "uwae"}],
            "supersedes": [],
        },
        {
            "slot": "E18",
            "source": "engine-results-e18.json",
            "dimension": "http-transport",
            "totals": {
                "uwae_wins": 7, "ties": 6, "baseline_wins": 0,
                "not_comparable": 0, "no_evaluable_runs": 0,
                "untested_runs_total": 0,
            },
            "comparisons": [{"verdict": "uwae"}],
            "supersedes": ["E14"],
        },
    ]
    active, supersessions = corpus_matrix._apply_supersessions(slot_entries)
    assert [entry["slot"] for entry in active] == ["E18"]
    assert len(supersessions) == 1
    assert supersessions[0]["slot"] == "E14"
    assert supersessions[0]["superseded_by"] == "E18"


def test_a_superseded_slot_is_still_published_with_its_status():
    """Bukti lama TIDAK hilang -- ia tetap tercatat, ditandai superseded."""
    slot_entries = [
        {"slot": "E14", "source": "engine-results-e14.json", "dimension": "d",
         "totals": corpus_matrix._empty_totals(),
         "comparisons": [], "supersedes": []},
        {"slot": "E18", "source": "engine-results-e18.json", "dimension": "d",
         "totals": corpus_matrix._empty_totals(),
         "comparisons": [], "supersedes": ["E14"]},
    ]
    corpus_matrix._apply_supersessions(slot_entries)
    by_slot = {entry["slot"]: entry for entry in slot_entries}
    assert by_slot["E14"]["status"] == "superseded"
    assert by_slot["E14"]["superseded_by"] == "E18"
    assert by_slot["E18"]["status"] == "active"


def test_a_supersession_pointing_at_an_unknown_slot_is_rejected():
    """Slot baru tidak boleh mengklaim menggantikan slot yang tidak ada."""
    slot_entries = [
        {"slot": "E18", "dimension": "d", "totals": corpus_matrix._empty_totals(),
         "comparisons": [], "supersedes": ["E99"]},
    ]
    with pytest.raises(ValueError):
        corpus_matrix._apply_supersessions(slot_entries)


def test_supersession_is_declared_in_the_evidence_not_in_the_aggregator():
    """Sumber kebenaran ikut travels bersama buktinya."""
    assert corpus_matrix._read_supersedes({"supersedes": "E14"}) == ["E14"]
    assert corpus_matrix._read_supersedes({"supersedes": ["E14", "E15"]}) == [
        "E14",
        "E15",
    ]
    assert corpus_matrix._read_supersedes({}) == []


def test_current_corpus_records_the_backfill_supersessions(corpus):
    """Backfill §6.3 (n=30) menggantikan slot n=5 -- dan itu TEREKAM.

    Slot lama tidak boleh hilang diam-diam: ia tetap dipublikasikan dengan
    status ``superseded`` dan penunjuk penggantinya, supaya pembaca bisa
    melihat bukti lamanya DAN alasan penggantinya.
    """
    supersessions = corpus["supersessions"]
    by_slot = {record["slot"]: record for record in supersessions}
    assert set(by_slot) == {"E14", "E15"}
    assert by_slot["E14"]["superseded_by"] == "E18"
    assert by_slot["E15"]["superseded_by"] == "E19"

    assert corpus["summary"]["superseded_slots"] == 2
    assert corpus["summary"]["active_slots"] == len(corpus["slots"]) - 2

    published = {entry["slot"]: entry for entry in corpus["slots"]}
    assert published["E14"]["status"] == "superseded"
    assert published["E14"]["superseded_by"] == "E18"
    assert published["E15"]["status"] == "superseded"
    assert published["E15"]["superseded_by"] == "E19"
    assert published["E18"]["status"] == "active"
    assert published["E19"]["status"] == "active"


def test_the_backfill_slots_carry_at_least_thirty_runs_per_cell(corpus):
    """§6.3 -- minimal 30 pengulangan per sel pada slot backfill.

    Slot yang sedang dihitung korpus harus benar-benar memenuhi ambang itu;
    kalau tidak, angka vonisnya berasal dari pengulangan yang terlalu sedikit.
    """
    published = {entry["slot"]: entry for entry in corpus["slots"]}
    for slot in ("E18", "E19"):
        entry = published[slot]
        assert entry["status"] == "active", slot
        for comparison in entry["comparisons"]:
            for side in ("uwae", "baseline"):
                runs = comparison[side]["runs"]
                assert runs >= 30, "%s/%s hanya %d run" % (slot, side, runs)
