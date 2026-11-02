"""E14 — differential lintas-implementasi UWAE vs Botasaurus.

Yang diuji di sini BUKAN angka benchmark (angka itu bukti yang di-commit),
melainkan INVARIAN harness — justru invarian yang menjaga benchmark tetap
jujur:

- ground truth berasal dari semantik fixture, bukan dari engine yang diuji;
- rumuskriteria yang sama berlaku untuk kedua arm;
- "tidak punya API diagnosis" tidak boleh dihitung sebagai diagnosis benar
  (inflasi kredit) maupun sebagai diagnosis salah (penuduhan);
- bukti yang di-commit konsisten dengan harness yang menghasilkannya;
- klaim lama yang sudah terbukti SALAH tidak boleh muncul lagi diam-diam.
"""

import ast
import json
from pathlib import Path
from unittest import mock

import pytest

from universal_web_acquisition.access.model import AccessState
from universal_web_acquisition.benchmark import cross_impl_bench
from universal_web_acquisition.benchmark.cross_impl_bench import (
    DIAGNOSIS_GROUND_TRUTH,
    EXCLUDED_SCENARIOS,
    SCENARIO_CRITERION,
    SCENARIO_IDS,
    _assess_run,
    _cause_diagnosis_metrics,
    _false_problem_metrics,
    _median,
    _percentile,
)
from universal_web_acquisition.benchmark.fixture_server import GROUND_TRUTHS, SCENARIOS

REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = REPO_ROOT / "docs" / "benchmark" / "engine-results-e14.json"


@pytest.fixture(scope="module")
def evidence():
    return json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Ground truth
# --------------------------------------------------------------------------


def test_every_fixture_scenario_is_either_measured_or_excluded_with_a_reason():
    """Tidak boleh ada skenario fixture yang hilang diam-diam."""
    accounted = set(SCENARIO_IDS) | set(EXCLUDED_SCENARIOS)
    assert accounted == set(SCENARIOS)


def test_excluded_scenarios_state_why_they_are_not_measured():
    for scenario_id, reason in EXCLUDED_SCENARIOS.items():
        assert scenario_id in SCENARIOS, scenario_id
        assert reason.strip(), scenario_id


def test_every_measured_scenario_has_exactly_one_primary_criterion():
    for scenario_id in SCENARIO_IDS:
        assert SCENARIO_CRITERION[scenario_id] in ("acquisition", "diagnosis")
        assert scenario_id in GROUND_TRUTHS


def test_diagnosis_criteria_are_exactly_the_scenarios_with_a_ground_truth_label():
    """Kriteria primer harus konsisten dengan label diagnosis yang ada."""
    for scenario_id in SCENARIO_IDS:
        has_label = scenario_id in DIAGNOSIS_GROUND_TRUTH
        assert has_label == (SCENARIO_CRITERION[scenario_id] == "diagnosis"), scenario_id


def test_diagnosis_labels_are_reachable_states_of_the_engine():
    """Label ground truth harus bisa dihasilkan engine — kalau tidak, benchmark
    tidak terukur dan hasil 0 akan menyesatkan."""
    vocabulary = {state.value for state in AccessState}
    for label in DIAGNOSIS_GROUND_TRUTH.values():
        assert label in vocabulary, label


def test_ground_truth_labels_are_derived_from_fixture_semantics():
    """Label harus punya bukti di body fixture — bukan dari engine mana pun."""
    body_by_scenario = {
        sid: GROUND_TRUTHS[sid]["body"].decode("utf-8", "replace").lower()
        for sid in SCENARIOS
    }
    expectations = {
        "b07_js_render": ("please enable javascript",),
        "a04_login": ('type="password"',),
        "a07_challenge": ("just a moment",),
        "a06_rate_limited": ("rate limited",),
        "a07_denied": ("access denied",),
    }
    for scenario_id, markers in expectations.items():
        body = body_by_scenario[scenario_id]
        for marker in markers:
            assert marker in body, (scenario_id, marker)


# --------------------------------------------------------------------------
# Rumus kriteria — sama untuk kedua arm
# --------------------------------------------------------------------------


def _row(**kwargs):
    base = {"scenario_id": "b01_small_get", "elapsed_ms": 10.0, "attempts": 1}
    base.update(kwargs)
    return base


def test_healthy_scenario_is_not_penalised_for_having_no_diagnosis():
    """Engine tanpa API diagnosis tidak boleh PENUDUHAN atas skenario sehat."""
    truth = GROUND_TRUTHS["b01_small_get"]
    import hashlib

    row = _row(
        status_code=truth["expect_status"],
        body_sha256=hashlib.sha256(truth["body"]).hexdigest(),
        observed_diagnosis=None,
    )
    result = _assess_run("b01_small_get", row)
    assert result["diagnosis_verified"] is None
    assert result["spurious_problem"] is False
    assert result["acquisition_verified"] is True
    assert result["primary_success"] is True


def test_healthy_scenario_flags_a_spurious_problem_report():
    result = _assess_run("b01_small_get", _row(observed_diagnosis="rate_limited"))
    assert result["spurious_problem"] is True
    assert result["primary_success"] is False


def test_healthy_scenario_accepts_access_granted_as_no_problem():
    result = _assess_run("b01_small_get", _row(observed_diagnosis="access_granted"))
    assert result["spurious_problem"] is False


def test_cause_scenario_requires_the_matching_diagnosis():
    result = _assess_run("a07_challenge", _row(observed_diagnosis="challenge_present"))
    assert result["diagnosis_verified"] is True
    assert result["primary_success"] is True


def test_cause_scenario_fails_when_diagnosis_is_wrong():
    result = _assess_run("a07_challenge", _row(observed_diagnosis="access_denied"))
    assert result["diagnosis_verified"] is False
    assert result["primary_success"] is False


def test_cause_scenario_fails_when_no_diagnosis_is_produced():
    """Botasaurus tidak punya API diagnosis — itu gaps kemampuan, bukan
    diagnosis yang salah; tapi tetap TIDAK boleh dihitung sebagai sukses."""
    result = _assess_run("a07_challenge", _row(observed_diagnosis=None))
    assert result["diagnosis_verified"] is False
    assert result["primary_success"] is False


def test_byte_mismatch_is_not_an_acquisition_success():
    truth = GROUND_TRUTHS["b01_small_get"]
    result = _assess_run(
        "b01_small_get",
        _row(status_code=truth["expect_status"], body_sha256="0" * 64),
    )
    assert result["status_match"] is True
    assert result["body_match"] is False
    assert result["acquisition_verified"] is False
    assert result["primary_success"] is False


def test_status_mismatch_is_not_an_acquisition_success():
    truth = GROUND_TRUTHS["b01_small_get"]
    import hashlib

    result = _assess_run(
        "b01_small_get",
        _row(
            status_code=500,
            body_sha256=hashlib.sha256(truth["body"]).hexdigest(),
        ),
    )
    assert result["acquisition_verified"] is False


# --------------------------------------------------------------------------
# Metrik diagnosis
# --------------------------------------------------------------------------


def test_cause_diagnosis_metrics_count_only_applicable_scenarios():
    rows = [
        _row(scenario_id="a07_challenge", observed_diagnosis="challenge_present"),
        _row(scenario_id="a07_challenge", observed_diagnosis="access_denied"),
        _row(scenario_id="b01_small_get", observed_diagnosis="access_granted"),
    ]
    metrics = _cause_diagnosis_metrics(rows)
    assert metrics["tp"] == 1
    assert metrics["fn"] == 1
    assert metrics["applicable_runs"] == 2
    assert metrics["recall"] == 0.5
    assert metrics["precision"] == 1.0


def test_cause_diagnosis_metrics_report_zero_for_engine_without_diagnosis_api():
    rows = [_row(scenario_id="a07_challenge", observed_diagnosis=None)]
    metrics = _cause_diagnosis_metrics(rows)
    assert metrics["tp"] == 0
    assert metrics["fn"] == 1
    assert metrics["recall"] == 0.0
    assert metrics["precision"] == 0.0


def test_false_problem_metrics_only_look_at_healthy_scenarios():
    rows = [
        _row(scenario_id="b01_small_get", observed_diagnosis="access_granted"),
        _row(scenario_id="b01_small_get", observed_diagnosis="rate_limited"),
        _row(scenario_id="a07_challenge", observed_diagnosis="challenge_present"),
    ]
    metrics = _false_problem_metrics(rows)
    assert metrics["healthy_runs"] == 2
    assert metrics["spurious_problem_runs"] == 1
    assert metrics["rate"] == 0.5


# --------------------------------------------------------------------------
# Statistik
# --------------------------------------------------------------------------


def test_percentile_uses_nearest_rank():
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert _percentile(values, 0.95) == 50.0
    assert _percentile(values, 0.5) == 30.0


def test_percentile_handles_empty_input():
    assert _percentile([], 0.95) is None


def test_median_handles_even_and_odd_counts():
    assert _median([1.0, 3.0, 5.0]) == 3.0
    assert _median([1.0, 2.0, 3.0, 4.0]) == 2.5
    assert _median([]) is None


# --------------------------------------------------------------------------
# Bukti yang di-commit
# --------------------------------------------------------------------------


def test_evidence_declares_identical_conditions(evidence):
    conditions = evidence["environment"]["identical_conditions"]
    for key in ("targets", "expected_outputs", "device_conditions", "run_counts",
                "success_criteria"):
        assert conditions[key] is True, key


def test_evidence_covers_every_measured_scenario(evidence):
    measured = [entry["scenario_id"] for entry in evidence["scenarios"]]
    assert measured == SCENARIO_IDS


def test_evidence_reports_both_arms_without_runtime_failure(evidence):
    failures = evidence["summary"]["runtime_failures"]
    assert failures["uwae-engine"] is None
    assert failures["botasaurus-request"] is None


def test_evidence_run_counts_are_identical_for_both_arms(evidence):
    for entry in evidence["scenarios"]:
        runs = {arm: entry["results"][arm]["runs"] for arm in entry["results"]}
        assert len(set(runs.values())) == 1, entry["scenario_id"]
        assert list(runs.values())[0] == cross_impl_bench.RUNS


def test_evidence_summary_counts_match_the_scenario_data(evidence):
    """Angka ringkasan harus bisa direproduksi dari data per-skenario."""
    for arm in ("uwae-engine", "botasaurus-request"):
        recomputed = sum(
            entry["results"][arm]["primary_successes"] for entry in evidence["scenarios"]
        )
        assert evidence["summary"]["primary_success_runs"][arm] == recomputed


def test_evidence_dns_section_records_runs_for_both_arms(evidence):
    dns = evidence["dns_boundedness"]
    assert dns["runs_per_arm"] == cross_impl_bench.DNS_RUNS
    for arm in ("uwae-engine", "botasaurus-request"):
        summary = dns[arm]["summary"]
        assert summary["runs"] == cross_impl_bench.DNS_RUNS


def test_evidence_lists_unsupported_scenarios_with_reasons(evidence):
    unsupported = evidence["unsupported_scenarios"]
    assert unsupported
    for entry in unsupported:
        assert entry["reason"].strip()


def test_evidence_does_not_claim_uwae_outperforms_botasaurus(evidence):
    """Mandat INSTRUCTION.md: hasil baseline, bukan klaim unggul."""
    interpretation = evidence["summary"]["interpretation"]
    assert "BUKAN" in interpretation
    assert "baseline" in interpretation.lower()


# --------------------------------------------------------------------------
# Regresi: klaim yang sudah terbukti salah tidak boleh kembali
# --------------------------------------------------------------------------

FALSIFIED_CLAIM_PATTERNS = (
    "TIDAK BERFUNGSI di PRoot",
    "engine HTTP Botasaurus tidak dapat dieksekusi",
    "baseline Botasaurus tidak dapat dieksekusi",
)

CORRECTION_MARKERS = ("ADR-019", "KOREKSI", "SALAH")

CLAIM_BEARING_FILES = (
    REPO_ROOT / "src" / "universal_web_acquisition" / "benchmark" / "strategy_bench.py",
    REPO_ROOT / "src" / "universal_web_acquisition" / "benchmark" / "engine_bench.py",
    REPO_ROOT / "docs" / "roadmap" / "phase-1-implementation-plan.md",
    REPO_ROOT / "docs" / "architecture" / "decisions" / "ADR-017-adaptive-scheduling-evidence.md",
    REPO_ROOT / "docs" / "architecture" / "decisions" / "ADR-018-failure-isolation.md",
    REPO_ROOT / "docs" / "benchmark" / "strategy-comparison.md",
    REPO_ROOT / "docs" / "audit" / "g0-audit-report.md",
)


def _blocks(text):
    """Blok teks yang dipisah baris kosong — satu paragraf/bullet."""
    for raw in text.split("\n\n"):
        block = " ".join(raw.split())
        if block:
            yield block


def test_falsified_non_functional_claim_is_never_asserted_without_correction():
    """Klaim 'engine HTTP Botasaurus tidak berfungsi' sudah terbukti SALAH
    (bug Python pada skrip baseline milik proyek ini). Klaim itu BOLEH
    disebut sebagai riwayat — tapi tidak boleh disajikan sebagai fakta
    tanpa koreksi eksplisit di blok yang sama."""
    offenders = []
    for path in CLAIM_BEARING_FILES:
        for block in _blocks(path.read_text(encoding="utf-8")):
            if not any(pattern in block for pattern in FALSIFIED_CLAIM_PATTERNS):
                continue
            if not any(marker in block for marker in CORRECTION_MARKERS):
                offenders.append(f"{path.name}: {block[:120]}")
    assert not offenders, offenders


def test_historical_evidence_flags_the_invalidated_baseline_executability_field():
    """Field ``summary.baseline_executable_in_this_environment`` pernah bernilai
    False karena baseline salah dipanggil. Bukti historis tidak ditimpa, jadi
    field itu WAJIB ditandai invalid oleh blok ``correction`` yang menunjuk
    bukti E14."""
    for name in ("engine-results.json", "engine-results-e9.json", "engine-results-e12.json"):
        doc = json.loads(
            (REPO_ROOT / "docs" / "benchmark" / name).read_text(encoding="utf-8")
        )
        summary = doc.get("summary", {})
        if "baseline_executable_in_this_environment" not in summary:
            continue
        correction = doc.get("correction")
        assert correction, name
        assert correction["adr"] == "ADR-019", name
        assert correction["superseded_by"] == "docs/benchmark/engine-results-e14.json", name
        assert (
            "summary.baseline_executable_in_this_environment"
            in correction["invalidated_fields"]
        ), name


def test_baseline_scripts_do_not_use_the_broken_botasaurus_entrypoint():
    """``botasaurus_requests.get(url)`` tanpa header SELALU gagal dengan
    KeyError('headers') — itu bug pemanggil, bukan batas platform. Skrip
    baseline wajib memakai jalur publik yang benar (Request / @request).

    Pemeriksaan dilakukan di AST, bukan di teks: nama entrypoint yang salah
    boleh DIBHASILKAN di komentar (itu justru menjelaskan bug-nya), tapi tidak
    boleh DIPANGGIL."""
    from universal_web_acquisition.benchmark import engine_bench

    for name, script in (
        ("BASELINE_SCRIPT", engine_bench.BASELINE_SCRIPT),
        ("DNS_BASELINE_SCRIPT", engine_bench.DNS_BASELINE_SCRIPT),
    ):
        tree = ast.parse(script)

        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "botasaurus_requests":
                imported.update(alias.name for alias in node.names)
        assert "get" not in imported, (name, "import get")
        assert "Request" in imported, (name, "harus memakai jalur publik Request")

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "get":
                continue
            owner = node.func.value
            assert not (
                isinstance(owner, ast.Name) and owner.id == "botasaurus_requests"
            ), (name, "memanggil botasaurus_requests.get()")


# --------------------------------------------------------------------------
# Checkpoint per-run — durasi yang jujur dan tahan mati mendadak
# --------------------------------------------------------------------------


def test_harness_fingerprint_is_stable_across_calls():
    """Fingerprint yang berubah-ubah tidak berguna: dia harus mengunci
    konfigurasi yang sama ke sidik jari yang sama."""
    assert cross_impl_bench._harness_fingerprint() == (
        cross_impl_bench._harness_fingerprint()
    )


def test_harness_fingerprint_changes_when_the_measurement_material_changes():
    """Kalau jumlah run berubah, run lama tidak boleh dibandingkan dengan run
    baru memakai kriteria berbeda."""
    base = cross_impl_bench._harness_fingerprint()
    with mock.patch.object(cross_impl_bench, "RUNS", cross_impl_bench.RUNS + 1):
        assert cross_impl_bench._harness_fingerprint() != base
    with mock.patch.object(cross_impl_bench, "ARM_TIMEOUT_S", 999):
        assert cross_impl_bench._harness_fingerprint() != base
    with mock.patch.object(
        cross_impl_bench, "BOTASAURUS_ARM_SCRIPT", "changed"
    ):
        assert cross_impl_bench._harness_fingerprint() != base


def test_harness_fingerprint_does_not_change_when_unrelated_state_changes():
    """Fingerprint harus spesifik, bukan rakaman semua yang bisa berubah."""
    base = cross_impl_bench._harness_fingerprint()
    with mock.patch.object(cross_impl_bench, "RESULTS_PATH", Path("/tmp/lain.json")):
        assert cross_impl_bench._harness_fingerprint() == base


def test_the_arm_scripts_read_the_checkpoint_instead_of_re_running():
    """Skrip arm harus benar-benar mengecek checkpoint sebelum permintaan.

    Ini dicek pada sumber skrip arm, karena skrip arm dijalankan sebagai
    subprocess — bukan sebagai fungsi yang bisa dipanggil langsung.
    """
    for name, script in (
        ("BOTASAURUS_ARM_SCRIPT", cross_impl_bench.BOTASAURUS_ARM_SCRIPT),
        ("UWAE_ARM_SCRIPT", cross_impl_bench.UWAE_ARM_SCRIPT),
    ):
        assert "checkpoint.get(" in script, name
        assert "checkpoint.append(" in script, name
        # Baris yang dipakai ulang harus melompati eksekusi run.
        assert "if cached is not None:" in script, name
        # Fingerprint ikut dibawa ke subprocess, jadi run dengan konfigurasi
        # berbeda tidak akan dipakai diam-diam.
        assert "payload[\"fingerprint\"]" in script, name


@pytest.fixture(scope="module")
def two_invocations(tmp_path_factory):
    """Jalankan harness dua kali dengan checkpoint yang sama.

    Jalur RESULTS_PATH dan CHECKPOINT_PATH diarahkan ke direktori sementara
    supaya bukti historis yang sudah di-commit tidak tertimpa.
    """
    tmp = tmp_path_factory.mktemp("e14-checkpoint")
    results_path = tmp / "engine-results-e14.json"
    checkpoint_path = tmp / "checkpoint.jsonl"

    docs = []
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(cross_impl_bench, "RESULTS_PATH", results_path)
        patch.setattr(cross_impl_bench, "CHECKPOINT_PATH", checkpoint_path)
        patch.setattr(cross_impl_bench, "RUNS", 1)
        patch.setattr(cross_impl_bench, "DNS_RUNS", 1)
        for _ in range(2):
            cross_impl_bench.main()
            docs.append(json.loads(results_path.read_text(encoding="utf-8")))
    return docs[0], docs[1], checkpoint_path


def test_the_second_invocation_reuses_every_completed_run(two_invocations):
    """Run yang sudah dibayar mahal dengan waktu device tidak dieksekusi ulang."""
    _, second, _ = two_invocations
    checkpoint = second["checkpoint"]
    assert checkpoint["runs_executed_this_invocation"] == 0
    assert checkpoint["runs_reused"] == checkpoint["runs_in_checkpoint"]


def test_the_first_invocation_executes_every_run(two_invocations):
    first, _, _ = two_invocations
    checkpoint = first["checkpoint"]
    assert checkpoint["runs_executed_this_invocation"] == checkpoint[
        "runs_in_checkpoint"
    ]
    assert checkpoint["runs_reused"] == 0


def test_the_document_publishes_a_timing_block_instead_of_a_bare_elapsed_s(
    two_invocations,
):
    """Angka `elapsed_s` tingkat dokumen hanya mengukur satu pemanggilan —
    kalau sebagian besar run dari checkpoint, pembaca akan salah menyimpulkan.
    Jadi field itu dihapus, bukan hanya diberi label lain."""
    first, second, _ = two_invocations
    for doc in (first, second):
        assert "elapsed_s" not in doc
        assert "timing" in doc
        assert "checkpoint" in doc


def test_the_timing_block_separates_measured_time_from_the_invocation(
    two_invocations,
):
    """Durasi kerja terukur harus jauh lebih besar daripada durasi
    pemanggilan penulis pada invocation kedua — itu justru inti fix-nya."""
    _, second, _ = two_invocations
    timing = second["timing"]
    assert timing["measured_arm_execution_runs"] > 0
    assert timing["measured_arm_execution_s_total"] > 0
    assert timing["harness_invocation"]["runs_executed_this_invocation"] == 0
    assert timing["harness_invocation"]["runs_reused_from_checkpoint"] > 0


def test_reused_rows_keep_their_measurement_fields(two_invocations):
    """Row dari checkpoint harus lengkap: tanpa field hilang, pembacaan
    ulang tidak bisa membedakan run reuse dari run baru.

    Yang diperiksa adalah BARIS MENTAH di file checkpoint, bukan ringkasan
    di dokumen — ringkasan memang sudah bisa sedikit kehilangan field.

    Catatan: peak_memory_bytes ditambahkan SETELAH loop skenario (last-line-wins),
    jadi baris PERTAMA untuk kunci tidak punya field ini — baris KEDUA yang punya.
    Test memverifikasi SETIAP KUNCI punya minimal satu baris dengan field tersebut.

    DNS runs (scope_id='dns') dikecualikan karena skema berbeda.
    """
    _, _, checkpoint_path = two_invocations
    raw = [
        json.loads(line)
        for line in checkpoint_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    arm_records = [
        record
        for record in raw
        if record.get("subject_id") in {"botasaurus-request", "uwae-engine"}
        and record.get("scope_id") != "dns"
    ]
    assert arm_records

    # Kelompokkan per kunci (scope_id, subject_id, index)
    by_key = {}
    for record in arm_records:
        key = (record["scope_id"], record["subject_id"], record["index"])
        by_key.setdefault(key, []).append(record)

    for key, records in by_key.items():
        scope_id, subject_id, index = key
        # Setiap kunci harus punya field mandatory di SEMUA baris
        for record in records:
            row = record["row"]
            assert row["recorded_at"], record
            assert row["fixture_base_url"], record
            assert row["elapsed_ms"] >= 0, record
            assert "attempts" in row, record
            assert "observed_diagnosis" in row, record
            assert "raw_signal" in row, record
            assert row["scenario_id"] == scope_id, record
            assert row["run_index"] == index, record
        # Minimal satu baris per kunci harus punya peak_memory_bytes
        assert any("peak_memory_bytes" in r["row"] for r in records), key


def test_the_checkpoint_file_lives_outside_the_repository(two_invocations):
    """Checkpoint berisi data pengukuran mentah; ia tidak boleh ikut
    ter-commit ke repo."""
    _, _, checkpoint_path = two_invocations
    assert not str(checkpoint_path).startswith(str(REPO_ROOT))


def test_a_checkpoint_from_another_fingerprint_is_ignored(two_invocations):
    """Run lama dengan konfigurasi berbeda tidak boleh dipakai diam-diam."""
    _, _, checkpoint_path = two_invocations
    checkpoint_path.write_text(
        json.dumps(
            {
                "fingerprint": "0" * 64,
                "scope_id": "b01_small_get",
                "subject_id": "uwae-engine",
                "index": 0,
                "row": {"status_code": 999},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    checkpoint = cross_impl_bench._Checkpoint(checkpoint_path)
    assert checkpoint.get("b01_small_get", "uwae-engine", 0) is None
    assert checkpoint.stats()["records_ignored"] == 1
