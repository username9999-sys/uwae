"""E16 — differential dimensi BROWSER UWAE vs Botasaurus.

Yang diuji di sini BUKAN angka benchmark (angka itu bukti yang di-commit),
melainkan INVARIAN harness — invarian yang menjaga benchmark tetap jujur:

- ground truth berasal dari semantika protokol fixture, bukan dari engine
  yang diuji;
- kriteria sukses berbasis MARKER, bukan byte-for-byte — output browser
  (``document.documentElement.outerHTML``) memang tidak pernah byte-identik
  dengan body sumber, jadi kriteria byte-for-byte akan otomatis menghukum
  browser di SEMUA skenario, termasuk yang seharusnya ia menang;
- kriteria yang sama diterapkan IDENTIK ke semua lengan;
- sumbu "sinyal gagal" menerima DUA kanal (body ATAU diagnosis) dan kanal
  yang dipakai ikut dicatat — perbedaan arsitektur tidak boleh disembunyikan
  di balik satu angka;
- "tidak ada body" berarti "tidak ada yang diukur", bukan "fidelitas gagal";
- bukti sisi server adalah sumber kebenaran, termasuk path breakdown;
- n=30 per sel (TEXT.md §6.3);
- matriks menang/seri/kalah dilaporkan apa adanya, tanpa klaim unggul.
"""

import ast
import hashlib
import json
from pathlib import Path

import pytest

from universal_web_acquisition.benchmark import browser_diff_bench
from universal_web_acquisition.benchmark.browser_diff_bench import (
    ARM_CONFIGURATION,
    ARM_SCRIPTS,
    ARMS,
    BENCHMARK_ID,
    COMPARISONS,
    RUNS,
    SCENARIOS,
    SOURCE_BODIES,
    _assess_run,
    _comparison_outcome,
    _row_is_untested,
    _server_evidence,
    _summarise,
)
from universal_web_acquisition.benchmark.fixture_server import (
    CHALLENGE_BODY,
    HTML_BODY,
    INVALID_HTML_BODY,
    JS_BODY,
    GROUND_TRUTHS,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = REPO_ROOT / "docs" / "benchmark" / "engine-results-e16.json"
E14_EVIDENCE_PATH = REPO_ROOT / "docs" / "benchmark" / "engine-results-e14.json"
REPORT_PATH = REPO_ROOT / "docs" / "benchmark" / "browser-arm-differential.md"
ADR_PATH = (
    REPO_ROOT
    / "docs"
    / "architecture"
    / "decisions"
    / "ADR-021-browser-arm-differential.md"
)

EXPECTED_ARMS = (
    "uwae-adaptive",
    "uwae-browser-only",
    "botasaurus-http",
    "botasaurus-browser",
)


@pytest.fixture(scope="module")
def evidence():
    return json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Ground truth — dari semantik protokol fixture
# --------------------------------------------------------------------------


def test_source_bodies_come_from_the_fixture_ground_truths():
    """Body pembanding byte diambil dari body yang benar-benar dilayani
    fixture — bukan dari output engine mana pun."""
    assert SOURCE_BODIES["b01_small_get"] == HTML_BODY
    assert SOURCE_BODIES["b07_js_render"] == JS_BODY
    assert SOURCE_BODIES["a11_invalid_html"] == INVALID_HTML_BODY
    assert SOURCE_BODIES["a07_challenge"] == CHALLENGE_BODY
    for scenario_id, body in SOURCE_BODIES.items():
        assert body == GROUND_TRUTHS[scenario_id]["body"], scenario_id


def test_expected_status_matches_the_fixture_ground_truths():
    for entry in SCENARIOS:
        truth = GROUND_TRUTHS[entry["id"]]
        assert entry["expect_status"] == truth["expect_status"], entry["id"]


def test_marker_ground_truth_is_derived_from_the_fixture_bodies():
    """Marker wajib/terlarang harus BENAR-BENAR ada/tidak ada di body
    sumber. Kalau tidak, kriteria yang dipakai menilai sesuatu yang tidak
    ada di fixture."""
    for entry in SCENARIOS:
        body = SOURCE_BODIES[entry["id"]].decode("utf-8", "replace").lower()
        for marker in entry["required_markers"]:
            assert marker.lower() in body, (entry["id"], marker)
        for marker in entry["forbidden_markers"]:
            assert marker.lower() in body, (entry["id"], marker)


def test_scenarios_cover_cost_js_render_and_two_failure_signals():
    ids = [entry["id"] for entry in SCENARIOS]
    assert ids == ["b01_small_get", "b07_js_render", "a11_invalid_html", "a07_challenge"]
    by_id = {entry["id"]: entry for entry in SCENARIOS}
    assert by_id["b01_small_get"]["failure_signal"] is None
    assert by_id["b07_js_render"]["failure_signal"] is None
    assert by_id["a11_invalid_html"]["failure_signal"]["kind"] == "invalid_content"
    assert by_id["a07_challenge"]["failure_signal"]["kind"] == "challenge"


# --------------------------------------------------------------------------
# Integritas lengan
# --------------------------------------------------------------------------


def test_every_arm_has_metadata_and_a_script():
    assert set(ARMS) == set(ARM_SCRIPTS)
    assert set(ARMS) == set(EXPECTED_ARMS)
    assert set(ARM_CONFIGURATION) == set(EXPECTED_ARMS)


def test_every_arm_script_is_valid_python():
    for name, script in ARM_SCRIPTS.items():
        ast.parse(script)  # raises SyntaxError on failure
        assert script.strip(), name


def test_arm_configuration_records_the_conditions_that_make_arms_comparable():
    """Kondisi identik tidak boleh hanya DIKLAIM lewat boolean; konfigurasi
    yang mendasarinya harus tercatat supaya bisa diaudit."""
    for arm in EXPECTED_ARMS:
        config = ARM_CONFIGURATION[arm]
        for key in ("transport", "retry", "browser_lifecycle", "status_source"):
            assert config.get(key), (arm, key)
    assert ARM_CONFIGURATION["botasaurus-browser"]["diagnosis_layer"] == "tidak ada"
    assert ARM_CONFIGURATION["botasaurus-http"]["diagnosis_layer"] == "tidak ada"
    assert "ada" in ARM_CONFIGURATION["uwae-adaptive"]["diagnosis_layer"]
    assert "ada" in ARM_CONFIGURATION["uwae-browser-only"]["diagnosis_layer"]


def test_botasaurus_http_arm_never_calls_the_broken_entrypoint():
    """``botasaurus_requests.get(url)`` tanpa header SELALU gagal dengan
    KeyError('headers') — bug pemanggil, bukan batas platform (ADR-019).

    Pemeriksaan di AST, bukan di teks: entrypoint yang salah boleh DIBHASILKAN
    di komentar (itu justru menjelaskan bug-nya), tapi tidak boleh DIPANGGIL.
    """
    tree = ast.parse(ARM_SCRIPTS["botasaurus-http"])
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "get":
            continue
        owner = node.func.value
        assert not (
            isinstance(owner, ast.Name) and owner.id == "botasaurus_requests"
        ), "memanggil botasaurus_requests.get()"


def test_botasaurus_http_arm_supplies_explicit_headers():
    """Setiap pemanggilan HTTP pada lengan Botasaurus harus punya ``headers``
    eksplisit — tanpa itu lengan gagal sebelum ada I/O, dan baseline yang
    gagal karena bug pemanggil bukan pengukuran apa pun."""
    tree = ast.parse(ARM_SCRIPTS["botasaurus-http"])
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "get":
            continue
        owner = node.func.value
        if not (isinstance(owner, ast.Name) and owner.id in ("session", "reqs")):
            continue
        kwargs = {kw.arg for kw in node.keywords}
        assert "headers" in kwargs, "get() tanpa headers"


def test_botasaurus_browser_arm_uses_the_verified_public_browser_api():
    """Lengan browser Botasaurus harus memakai API PUBLIK yang sudah
    terverifikasi empiris: ``@browser`` + ``driver.get`` + ``tab.get_content``
    + ``tab.evaluate``."""
    script = ARM_SCRIPTS["botasaurus-browser"]
    assert "from botasaurus.browser_decorator import browser" in script
    assert "driver.get(" in script
    assert "tab.get_content()" in script
    assert "tab.evaluate(" in script
    # Layer diagnosis bukan kemampuan Botasaurus — tidak boleh dikarang.
    # Skrip menuliskannya sebagai assignment pada row, bukan sebagai literal
    # dict JSON, jadi yang diperiksa adalah bentuk penulisan yang sebenarnya.
    assert 'row["diagnosis_state"] = None' in script
    assert 'row["browser_used"] = True' in script


def test_botasaurus_browser_arm_evaluates_with_an_explicit_return():
    """``Tab.evaluate`` menyisipkan ekspresi ke body blok ``(() => { ... })()``.
    Ekspresi tanpa ``return`` dievaluasi menjadi ``undefined``, lalu
    ``json.loads("{}").get("x")`` mengembalikan None — termasuk untuk
    ``document.readyState``. Setiap ekspresi deshalb itu WAJIB diawali
    ``return``.

    Diperiksa di AST: string ``return`` boleh muncul di docstring (itu
    menjelaskantemuan), tapi ekspresi yang dikirim ke ``evaluate`` harus
    benar-benar diawali ``return``.
    """
    tree = ast.parse(ARM_SCRIPTS["botasaurus-browser"])
    evaluated = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "evaluate" or not node.args:
            continue
        arg = node.args[0]
        assert isinstance(arg, ast.Constant) and isinstance(arg.value, str)
        evaluated.append(arg.value)
    assert evaluated, "lengan browser harus membaca minimal satu nilai via evaluate"
    for expression in evaluated:
        assert expression.lstrip().startswith("return "), expression


def test_botasaurus_browser_arm_reads_status_through_the_same_mechanism_as_uwae():
    """``botasaurus_driver`` tidak mengekspos status HTTP. Lengan browser
    Botasaurus harus membacanya lewat ``performance.getEntriesByType`` —
    mekanisme yang PERSIS sama dengan UWAE, supaya adjudikasi tidak memberi
    privilege ke salah satu lengan.

    Untuk UWAE, mekanisme itu TIDAK berada di dalam teks skrip lengan: skrip
    lengan hanya menjalankan ``JobWorker``, dan pembacaan status terjadi di
    lapisan CDP (``browser/cdp.py``). Menguji skrip lengan untuk string itu
    salah lapis dan tidak dapat terpenuhi — assertion-nya harus menunjuk
    sumber sebenarnya.
    """
    script = ARM_SCRIPTS["botasaurus-browser"]
    assert "performance.getEntriesByType('navigation')" in script
    assert "responseStatus" in script

    cdp_source = (
        REPO_ROOT / "src" / "universal_web_acquisition" / "browser" / "cdp.py"
    ).read_text(encoding="utf-8")
    assert "performance.getEntriesByType('navigation')" in cdp_source
    assert "responseStatus" in cdp_source


# --------------------------------------------------------------------------
# Kriteria: marker, bukan byte-for-byte
# --------------------------------------------------------------------------


def _outcome(**kwargs):
    base = {
        "status_code": 200,
        "body_sha256": None,
        "body_bytes": None,
        "content": "",
        "browser_used": False,
        "diagnosis_state": None,
        "diagnosis_reason": None,
        "terminal_status": None,
        "error": None,
        "elapsed_ms": 10.0,
    }
    base.update(kwargs)
    return base


def _scenario(scenario_id):
    return next(entry for entry in SCENARIOS if entry["id"] == scenario_id)


def test_criteria_are_marker_based_and_never_require_byte_for_byte():
    """Tidak ada skenario yang memakai ``byte_faithful`` sebagai kriteria
    PRIMER. Kriteria byte-for-byte akan otomatis menghukum browser di semua
    skenario karena output browser bukan byte-identik dengan body sumber."""
    for entry in SCENARIOS:
        assert entry["criterion"] in ("body_acquired", "signal_preserved"), entry["id"]
        assert entry["criterion"] != "byte_faithful", entry["id"]


def test_invalid_html_primary_criterion_is_signal_preservation():
    """Body 200 yang rusak BUKAN keberhasilan. Kriteria primernya harus
    "sinyal kegagalan tertutup atau tidak", bukan "byte masih utuh" —
    UWAE yang MENOLAK menyimpan byte korup itu perilaku benar, bukan gagal
    menyimpan byte."""
    scenario = _scenario("a11_invalid_html")
    assert scenario["criterion"] == "signal_preserved"
    assert scenario["failure_signal"]["body_channel"] == "byte_faithful"
    assert scenario["failure_signal"]["diagnosis_states"] == ["content_invalid"]


def test_body_acquired_requires_status_and_markers():
    scenario = _scenario("b01_small_get")
    good = _outcome(
        status_code=200,
        content="fixture-ok",
        body_sha256=hashlib.sha256(HTML_BODY).hexdigest(),
    )
    row = _assess_run(scenario, good, [])
    assert row["axes"]["body_acquired"] is True

    wrong_status = _assess_run(scenario, dict(good, status_code=500), [])
    assert wrong_status["axes"]["body_acquired"] is False

    missing_marker = _assess_run(scenario, dict(good, content="something else"), [])
    assert missing_marker["axes"]["body_acquired"] is False


def test_forbidden_marker_blocks_body_acquired():
    scenario = _scenario("b07_js_render")
    raw = _outcome(status_code=200, content="please enable javascript to view this page")
    assert _assess_run(scenario, raw, [])["axes"]["body_acquired"] is False
    rendered = _outcome(status_code=200, content="rendered-by-js")
    assert _assess_run(scenario, rendered, [])["axes"]["body_acquired"] is True


def test_absent_body_means_not_measured_not_unfaithful():
    """Tidak ada body = "tidak ada yang diukur" (``None``), bukan "fidelitas
    gagal" (``False``). Mengambil ``False`` akan menyiratkan lengan
    mencoba menyimpan byte lalu gagal."""
    scenario = _scenario("b01_small_get")
    row = _assess_run(scenario, _outcome(status_code=None, content=""), [])
    assert row["axes"]["byte_faithful"] is None
    assert row["axes"]["body_acquired"] is False


def test_signal_preserved_accepts_body_or_diagnosis_channel():
    """Dua kanal, keduanya sah. Lengan tanpa lapisan diagnosis memenuhi
    sumbu lewat kanal BODY; lengan dengan lapisan diagnosis boleh
    memenuhi lewat kanal DIAGNOSIS. Kanal yang dipakai ikut dicatat."""
    scenario = _scenario("a07_challenge")

    body_channel = _assess_run(
        scenario,
        _outcome(status_code=403, content="Just a moment... Checking your browser"),
        [],
    )
    assert body_channel["axes"]["signal_preserved"] is True
    assert body_channel["signal_channel"] == "body"

    diagnosis_channel = _assess_run(
        scenario,
        _outcome(status_code=None, diagnosis_state="challenge_present"),
        [],
    )
    assert diagnosis_channel["axes"]["signal_preserved"] is True
    assert diagnosis_channel["signal_channel"] == "diagnosis"

    neither = _assess_run(
        scenario,
        _outcome(status_code=403, content="a perfectly ordinary body"),
        [],
    )
    assert neither["axes"]["signal_preserved"] is False
    assert neither["signal_channel"] is None


def test_false_success_is_flagged_when_a_failure_signal_is_masked():
    """Lengan yang melaporkan bodytarget padahal sinyal kegagalan tertutup
    harus ditandai — itu "melaporkan sukses palsu"."""
    scenario = _scenario("a11_invalid_html")
    masked = _assess_run(
        scenario,
        _outcome(
            status_code=200,
            content="<html><body>binary garbage</body></html>",
            body_sha256=hashlib.sha256(b"<html><body>binary garbage</body></html>").hexdigest(),
        ),
        [],
    )
    assert masked["axes"]["body_acquired"] is True
    assert masked["axes"]["signal_preserved"] is False
    assert masked["false_success_reported"] is True


def test_scenarios_without_failure_signal_have_no_signal_axis():
    for scenario_id in ("b01_small_get", "b07_js_render"):
        row = _assess_run(_scenario(scenario_id), _outcome(status_code=200, content="x"), [])
        assert row["axes"]["signal_preserved"] is None
        assert row["false_success_reported"] is False


# --------------------------------------------------------------------------
# Bukti sisi server
# --------------------------------------------------------------------------


def test_server_evidence_reports_a_path_breakdown_not_only_a_total():
    """Chromium melakukan request sampingan (``/favicon.ico``). Kalau hanya
    total yang dilaporkan, selisih "1 request" vs "2 request" terlihat
    seperti selisih biaya palsu."""
    log = [
        {"method": "GET", "path": "/html", "status": 200},
        {"method": "GET", "path": "/favicon.ico", "status": 404},
    ]
    evidence = _server_evidence(log, "/html")
    assert evidence["total_requests"] == 2
    assert evidence["scenario_requests"] == 1
    assert evidence["incidental_requests"] == 1
    assert evidence["path_breakdown"] == {"/html": 1, "/favicon.ico": 1}
    assert evidence["first_status"] == 200


def test_summary_counts_byte_faithfulness_against_its_own_denominator():
    """``byte_faithful_applicable_runs`` harus jadi penyebut — kalau tidak,
    lengan yang tidak punya body akan terlihat seolah-olah gagal
    fidelitas."""
    rows = [
        {
            "primary_success": True,
            "elapsed_ms": 10.0,
            "error": None,
            "status_code": 200,
            "body_sha256": "aaa",
            "browser_used": False,
            "axes": {
                "body_acquired": True,
                "byte_faithful": True,
                "signal_preserved": None,
            },
            "signal_channel": None,
            "false_success_reported": False,
            "server_observed": _server_evidence([], "/html"),
        },
        {
            # Lengan yang menjawab tapi tidak mengirim body: byte_faithful
            # bernilai None ("tidak ada yang diukur"), bukan False.
            "primary_success": False,
            "elapsed_ms": 20.0,
            "error": None,
            "status_code": 200,
            "body_sha256": None,
            "browser_used": True,
            "axes": {
                "body_acquired": False,
                "byte_faithful": None,
                "signal_preserved": None,
            },
            "signal_channel": None,
            "false_success_reported": False,
            "server_observed": _server_evidence([], "/html"),
        },
    ]
    summary = _summarise(rows)
    assert summary["byte_faithful_runs"] == 1
    assert summary["byte_faithful_applicable_runs"] == 1


# --------------------------------------------------------------------------
# Gerbang §6.3 — jumlah pengulangan
# --------------------------------------------------------------------------


def test_run_count_meets_the_text_md_6_3_gate():
    """TEXT.md §6.3: minimal 30 pengulangan untuk skenario benchmark utama
    sebelum membandingkan performa. E14/E15 jalan di n=5 dan harus menyatakan
    p95-nya belum bermakna; E16 sejak awal memenuhi gerbang ini."""
    assert RUNS >= 30


def test_comparisons_only_pair_arms_that_exist():
    for uwae_arm, baseline_arm in COMPARISONS:
        assert uwae_arm in ARMS, uwae_arm
        assert baseline_arm in ARMS, baseline_arm


# --------------------------------------------------------------------------
# Checkpoint dan adjudikasi "belum teruji"
# --------------------------------------------------------------------------


def _row(**overrides):
    """Row minimal untuk menguji adjudikasi tanpa menjalankan benchmark."""
    row = {
        "primary_success": True,
        "elapsed_ms": 10.0,
        "error": None,
        "runtime_failure": None,
        "status_code": 200,
        "body_sha256": "abc",
        "browser_used": False,
        "axes": {
            "body_acquired": True,
            "byte_faithful": True,
            "signal_preserved": None,
        },
        "signal_channel": None,
        "false_success_reported": False,
        "server_observed": _server_evidence([], "/html"),
    }
    row.update(overrides)
    return row


def _cell(successes, evaluated, runs):
    """Ringkasan sel minimal untuk menguji vonis perbandingan."""
    return {
        "primary_success_runs": successes,
        "evaluated_runs": evaluated,
        "runs": runs,
    }


def test_runtime_failures_leave_the_capability_denominator():
    """Timeout tidak boleh dihitung sebagai "gagal" -- tidak ada respons yang
    pernah diamati, jadi tidak ada bukti yang bisa dinilai (TEXT.md:1427)."""
    rows = [
        _row(),
        _row(
            primary_success=None,
            elapsed_ms=None,
            error='{"kind": "timeout"}',
            runtime_failure={"kind": "timeout"},
            status_code=None,
            body_sha256=None,
            axes={
                "body_acquired": None,
                "byte_faithful": None,
                "signal_preserved": None,
            },
        ),
    ]
    summary = _summarise(rows)
    assert summary["runs"] == 2
    assert summary["evaluated_runs"] == 1
    assert summary["untested_runs"] == 1
    assert summary["primary_success_runs"] == 1
    assert summary["primary_success_rate"] == 1.0
    assert summary["runtime_failures"] == 1


def test_arm_error_without_any_measurement_is_also_untested():
    """Lengan yang gagal start sehingga tidak ada body dan tidak ada status
    juga "belum teruji" -- yang gagal eksekusi, bukan kemampuan engine."""
    row = _row(
        primary_success=False,
        error="RuntimeError: Failed to connect to Chrome",
        status_code=None,
        body_sha256=None,
        axes={
            "body_acquired": False,
            "byte_faithful": None,
            "signal_preserved": None,
        },
    )
    assert _row_is_untested(row)
    assert not _row_is_untested(_row())


def test_diagnosed_failure_without_a_body_is_still_evaluated():
    """Run yang diagnosis-nya sengaja tidak punya body (challenge_present ->
    needs_user) ITULAH sinyal yang diukur, jadi tetap dievaluasi.

    Bentuknya persis seperti run UWAE yang nyata: tanpa body, tanpa status,
    tanpa error -- tapi diagnosis dan status terminalNYA ada, karena itu yang
    membuat sinyalnya terlihat.
    """
    row = _row(
        primary_success=True,
        status_code=None,
        body_sha256=None,
        error=None,
        diagnosis_state="challenge_present",
        terminal_status="needs_user",
        axes={
            "body_acquired": False,
            "byte_faithful": None,
            "signal_preserved": True,
        },
    )
    assert not _row_is_untested(row)


def test_comparison_judges_on_evaluated_runs_not_on_raw_counts():
    """Jumlah absolut TIDAK mengundi pemenang -- yang dihitung adalah tingkat
    sukses atas run yang dievaluasi.

    29 sukses dari 29 run versus 30 sukses dari 30 run: angka mentah berbeda,
    tingkat sukses sama -> seri.
    """
    assert _comparison_outcome(_cell(29, 29, 29), _cell(30, 30, 30)) == "tie"
    # Run yang belum teruji membuat kedua batas tidak sepakat -> vonisnya
    # "tidak sebanding", BUKAN "baseline menang" hanya karena 30 > 29.
    assert _comparison_outcome(_cell(29, 29, 30), _cell(30, 30, 30)) == "not_comparable"
    assert _comparison_outcome(_cell(30, 30, 30), _cell(29, 30, 30)) == "uwae"
    assert _comparison_outcome(_cell(29, 30, 30), _cell(30, 30, 30)) == "baseline"


def test_comparison_is_unknown_when_the_two_bounds_disagree():
    """Kalau batas "run dievaluasi" dan batas "seluruh attempt" memberi
    urutan berbeda, bukti yang ada tidak cukup untuk memilih salah satu.
    Timeout pada satu lengan bisa berarti lengan itu lebih lambat ATAU hanya
    masalah eksekusi — vonisnya harus 'not_comparable', bukan diberikan ke
    lengan mana pun (TEXT.md:1427)."""
    # UWAE 29/29 dievaluasi (1 run belum teruji) vs baseline 30/30.
    # Batas-1: 100% vs 100% -> seri. Batas-2: 29/30 vs 30/30 -> baseline.
    assert _comparison_outcome(_cell(29, 29, 30), _cell(30, 30, 30)) == "not_comparable"
    # Simetris: baseline yang punya run belum teruji.
    assert _comparison_outcome(_cell(30, 30, 30), _cell(29, 29, 30)) == "not_comparable"
    # Kedua batas sepakat -> vonis pasti.
    assert _comparison_outcome(_cell(29, 30, 30), _cell(28, 30, 30)) == "uwae"


def test_comparison_without_any_evaluable_run_is_reported_separately():
    """Satu sisi tanpa run yang bisa dinilai tidak boleh dipaksa menjadi
    kemenangan maupun kalah pada komparasi."""
    assert _comparison_outcome(_cell(0, 0, 30), _cell(30, 30, 30)) == "no_evaluable_runs"
    assert _comparison_outcome(_cell(30, 30, 30), _cell(0, 0, 30)) == "no_evaluable_runs"


def test_an_empty_outcome_is_untested_not_a_capability_loss():
    """Dekorator Botasaurus (``raise_exception=False``) menelan exception dan
    mengembalikan None, sehingga lengan mengembalikan outcome KOSONG tanpa
    error yang bisa diamati. Itu lengan yang TIDAK JALAN — bukan lengan yang
    gagal. Menghitungnya sebagai kegagalan akan menghukum lengan karena
    masalah eksekusi."""
    row = _row(
        primary_success=False,
        error=None,
        status_code=None,
        body_sha256=None,
        axes={
            "body_acquired": False,
            "byte_faithful": None,
            "signal_preserved": None,
        },
    )
    assert _row_is_untested(row)


def test_latency_censoring_is_published_next_to_the_percentiles():
    """Run yang tidak bisa dievaluasi tidak punya latensi terukur, jadi p95
    bisa menyensor ekor yang paling informatif. Jumlah run tersensor dan
    batas timeout harus dipublikasikan supaya p95 tidak understate tail
    secara senyap."""
    rows = [
        _row(elapsed_ms=10.0),
        _row(
            primary_success=None,
            elapsed_ms=None,
            error='{"kind": "timeout"}',
            runtime_failure={"kind": "timeout"},
            status_code=None,
            body_sha256=None,
            axes={
                "body_acquired": None,
                "byte_faithful": None,
                "signal_preserved": None,
            },
        ),
    ]
    summary = _summarise(rows)
    assert summary["latency_censored_runs"] == 1
    assert summary["timeout_cap_s"] == 180
    assert summary["elapsed_ms_p95_with_censored_at_cap"] >= 180000
    assert summary["elapsed_ms_p95"] < 180000


def test_checkpoint_resumes_completed_runs_instead_of_reexecuting(tmp_path):
    """Restart setelah device reboot tidak boleh mengulang run yang sudah
    selesai -- itulah yang membuat 393/480 run hilang sekali saja."""
    path = tmp_path / "checkpoint.jsonl"
    checkpoint = browser_diff_bench._Checkpoint(path)
    assert checkpoint.rows == {}

    row = _row()
    checkpoint.append("b01_small_get", "uwae-adaptive", 0, row)

    resumed = browser_diff_bench._Checkpoint(path)
    assert resumed.get("b01_small_get", "uwae-adaptive", 0) == row
    assert resumed.get("b01_small_get", "uwae-adaptive", 1) is None
    assert resumed.get("b01_small_get", "botasaurus-http", 0) is None


def test_checkpoint_ignores_rows_recorded_with_another_harness_configuration(tmp_path):
    """Kalau konfigurasi harness berubah, run lama tidak boleh dibandingkan
    dengan run baru. Fingerprint membuat mismatch terlihat, bukan diam-diam."""
    path = tmp_path / "checkpoint.jsonl"
    path.write_text(
        json.dumps(
            {
                "fingerprint": "fingerprint-dari-harness-lain",
                "scenario_id": "b01_small_get",
                "arm_id": "uwae-adaptive",
                "run_index": 0,
                "row": _row(),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    checkpoint = browser_diff_bench._Checkpoint(path)
    assert checkpoint.get("b01_small_get", "uwae-adaptive", 0) is None
    assert checkpoint.ignored_records == 1


def test_checkpoint_survives_a_truncated_last_line(tmp_path):
    """Kalau proses mati tepat saat menulis, baris terakhir bisa terpotong.
    Baris rusak diabaikan; sisanya tetap dipakai."""
    path = tmp_path / "checkpoint.jsonl"
    checkpoint = browser_diff_bench._Checkpoint(path)
    checkpoint.append("b01_small_get", "uwae-adaptive", 0, _row())
    with open(path, "a", encoding="utf-8") as handle:
        handle.write('{"fingerprint": "abc", "scenario_id": "b01_sm')

    resumed = browser_diff_bench._Checkpoint(path)
    assert resumed.get("b01_small_get", "uwae-adaptive", 0) is not None
    assert resumed.ignored_records == 1


# --------------------------------------------------------------------------
# Bukti yang di-commit
# --------------------------------------------------------------------------


def test_evidence_declares_identical_conditions(evidence):
    conditions = evidence["environment"]["identical_conditions"]
    for key in (
        "targets",
        "expected_outputs",
        "device_conditions",
        "run_counts",
        "success_criteria",
    ):
        assert conditions[key] is True, key


def test_evidence_covers_every_scenario_and_arm(evidence):
    assert evidence["benchmark_id"] == BENCHMARK_ID
    assert [entry["scenario_id"] for entry in evidence["scenarios"]] == [
        entry["id"] for entry in SCENARIOS
    ]
    for entry in evidence["scenarios"]:
        assert set(entry["arms"]) == set(EXPECTED_ARMS), entry["scenario_id"]


def test_evidence_run_counts_are_identical_across_arms(evidence):
    for entry in evidence["scenarios"]:
        runs = {arm: data["summary"]["runs"] for arm, data in entry["arms"].items()}
        assert len(set(runs.values())) == 1, entry["scenario_id"]
        assert list(runs.values())[0] == RUNS


def test_evidence_separates_untested_runs_from_the_capability_denominator(evidence):
    """Run yang tidak bisa dievaluasi harus DIHAPUS dari penyebut kapabilitas
    dan dipublikasikan terpisah sebagai belum-teruji (TEXT.md:1427).

    Menghitungnya sebagai "gagal" akan menghukum lengan karena masalah
    eksekusi (timeout, chromium gagal start), bukan karena kemampuan engine.
    Invarian ini dikunci di sini supaya adjudikasi yang tidak adil tidak bisa
    masuk ke evidence yang di-commit.
    """
    for entry in evidence["scenarios"]:
        for arm, data in entry["arms"].items():
            summary = data["summary"]
            assert (
                summary["evaluated_runs"] + summary["untested_runs"]
                == summary["runs"]
            ), (entry["scenario_id"], arm)
            assert summary["primary_success_runs"] <= summary["evaluated_runs"]
            assert summary["runtime_failures"] <= summary["untested_runs"]
            for row in data["runs"]:
                if _row_is_untested(row):
                    assert row["primary_success"] is None, (entry["scenario_id"], arm)
                    assert row["axes"]["body_acquired"] is None
                    assert row["axes"]["signal_preserved"] is None
                else:
                    assert row["primary_success"] is not None, (entry["scenario_id"], arm)


def test_evidence_summary_counts_match_the_scenario_data(evidence):
    for arm in EXPECTED_ARMS:
        recomputed = sum(
            entry["arms"][arm]["summary"]["primary_success_runs"]
            for entry in evidence["scenarios"]
        )
        assert evidence["summary"]["per_arm_totals"][arm]["primary_success_runs"] == recomputed
        evaluated = sum(
            entry["arms"][arm]["summary"]["evaluated_runs"]
            for entry in evidence["scenarios"]
        )
        assert evidence["summary"]["per_arm_totals"][arm]["evaluated_runs"] == evaluated
        untested = sum(
            entry["arms"][arm]["summary"]["untested_runs"]
            for entry in evidence["scenarios"]
        )
        assert evidence["summary"]["per_arm_totals"][arm]["untested_runs"] == untested


def test_evidence_win_tie_loss_accounts_for_every_comparison(evidence):
    comparisons = evidence["summary"]["comparisons"]
    expected = len(evidence["scenarios"]) * len(COMPARISONS)
    assert len(comparisons) == expected
    tally = {
        "uwae": 0,
        "tie": 0,
        "baseline": 0,
        "not_comparable": 0,
        "no_evaluable_runs": 0,
    }
    for comparison in comparisons:
        assert comparison["outcome"] in tally, comparison
        tally[comparison["outcome"]] += 1
    published = evidence["summary"]["win_tie_loss"]
    assert published["uwae_wins"] == tally["uwae"]
    assert published["ties"] == tally["tie"]
    assert published["baseline_wins"] == tally["baseline"]
    assert published["not_comparable"] == tally["not_comparable"]
    assert published["no_evaluable_runs"] == tally["no_evaluable_runs"]
    assert sum(tally.values()) == expected
    assert (
        published["uwae_wins"]
        + published["ties"]
        + published["baseline_wins"]
        + published["not_comparable"]
        + published["no_evaluable_runs"]
        == expected
    )


def test_evidence_unknown_outcomes_are_published_separately_from_wins(evidence):
    """Vonis yang tidak bisa diputuskan (bukti tidak cukup) harus muncul di
    kategori sendiri, tidak pernah ikut dihitung sebagai menang atau kalah."""
    published = evidence["summary"]["win_tie_loss"]
    unknown = published["not_comparable"] + published["no_evaluable_runs"]
    assert unknown >= 0
    for comparison in evidence["summary"]["comparisons"]:
        if comparison["outcome"] in ("not_comparable", "no_evaluable_runs"):
            assert (
                comparison["uwae_untested_runs"]
                or comparison["baseline_untested_runs"]
                or comparison["uwae_evaluated_runs"] == 0
                or comparison["baseline_evaluated_runs"] == 0
            ), comparison


def test_evidence_publishes_the_not_tested_count_separately(evidence):
    """TEXT.md:1427: 'Publikasikan hasil menang, seri, kalah, dan belum teruji
    secara terpisah.' Jumlah run yang belum teruji harus terlihat, bukan
    hilang di dalam angka sukses."""
    published = evidence["summary"]["win_tie_loss"]
    totals = evidence["summary"]["per_arm_totals"]
    assert published["untested_runs_total"] == sum(
        totals[arm]["untested_runs"] for arm in totals
    )
    with_untested = len(
        [
            comparison
            for comparison in evidence["summary"]["comparisons"]
            if comparison["uwae_untested_runs"] or comparison["baseline_untested_runs"]
        ]
    )
    assert published["comparisons_with_untested_runs"] == with_untested


def test_evidence_records_the_browser_arm_gap_closing_finding(evidence):
    """Celah ``js_rendering_browser_arm`` yang dideklarasikan E14 ditutup oleh
    E16: HTTP-only tidak bisa merender JS, sedangkan kedua lengan browser
    bisa. Ini temuan_platform yang harus TERKOMIT, bukan jadi catatan
    lisan."""
    by_scenario = {entry["scenario_id"]: entry for entry in evidence["scenarios"]}
    js = by_scenario["b07_js_render"]["arms"]
    assert js["botasaurus-http"]["summary"]["primary_success_runs"] == 0
    assert js["botasaurus-browser"]["summary"]["primary_success_runs"] == RUNS
    assert js["uwae-browser-only"]["summary"]["primary_success_runs"] == RUNS


def test_evidence_shows_the_browser_reconstruction_closes_the_invalid_content_signal(evidence):
    """Temuan E4: browser merekonstruksi byte korup jadi HTML valid sehingga
    sinyal ``content_invalid`` tertutup. Kedua lengan browser harus
    menunjukkan itu; lengan HTTP harus mempertahankan sinyalnya."""
    by_scenario = {entry["scenario_id"]: entry for entry in evidence["scenarios"]}
    arms = by_scenario["a11_invalid_html"]["arms"]
    for arm in ("uwae-browser-only", "botasaurus-browser"):
        assert arms[arm]["summary"]["signal_preserved_runs"] == 0, arm
        assert arms[arm]["summary"]["false_success_runs"] == RUNS, arm
    assert arms["botasaurus-http"]["summary"]["signal_preserved_runs"] == RUNS
    assert arms["uwae-adaptive"]["summary"]["signal_preserved_runs"] == RUNS


def test_evidence_never_claims_uwae_outperforms_botasaurus(evidence):
    """Mandat INSTRUCTION.md: hasil baseline, bukan klaim unggul."""
    interpretation = evidence["summary"]["interpretation"]
    assert "BUKAN" in interpretation
    assert "baseline" in interpretation.lower()


def test_evidence_records_the_signal_channel_difference(evidence):
    """Perbedaan kanal sinyal (body vs diagnosis) adalah perbedaan
    arsitektur dan harus TEREKSPOS di bukti, bukan tersembunyi di balik satu
    angka."""
    by_scenario = {entry["scenario_id"]: entry for entry in evidence["scenarios"]}
    challenge = by_scenario["a07_challenge"]["arms"]
    assert challenge["uwae-adaptive"]["summary"]["signal_channel_counts"].get(
        "diagnosis"
    ) == RUNS
    assert challenge["botasaurus-browser"]["summary"]["signal_channel_counts"].get(
        "body"
    ) == RUNS


def test_evidence_records_the_browser_request_overhead_from_the_server_side(evidence):
    """Biaya request sampingan browser (favicon) harus terlihat dari log
    server, bukan dari klaim arm."""
    by_scenario = {entry["scenario_id"]: entry for entry in evidence["scenarios"]}
    html = by_scenario["b01_small_get"]["arms"]
    assert html["botasaurus-http"]["summary"][
        "server_observed_scenario_requests_median"
    ] == 1
    assert html["botasaurus-browser"]["summary"][
        "server_observed_scenario_requests_median"
    ] == 1
    for run in html["botasaurus-browser"]["runs"]:
        assert run["server_observed"]["incidental_requests"] >= 1
        assert "/favicon.ico" in run["server_observed"]["path_breakdown"]


# --------------------------------------------------------------------------
# Durasi benchmark — tidak boleh bisa disalahbaca
# --------------------------------------------------------------------------


def test_evidence_does_not_publish_a_bare_elapsed_s_that_covers_only_the_last_invocation(
    evidence,
):
    """``elapsed_s`` tingkat dokumen dulu hanya mengukur SATU pemanggilan
    harness. Karena sebagian besar run diambil dari checkpoint, angka itu
    jauh lebih kecil daripada durasi kerja sebenarnya, dan pembaca akan
    menyimpulkan seluruh benchmark hanya memakan waktu itu.

    Jadi field itu harus hilang, dan penggantinya harus menamai cakupannya
    sendiri."""
    assert "elapsed_s" not in evidence


def test_evidence_publishes_the_measured_execution_total(evidence):
    """Durasi kerja yang sebenarnya harus dipublikasikan: jumlah waktu
    eksekusi lengan yang terukur pada seluruh run."""
    timing = evidence["timing"]
    measured = timing["measured_arm_execution_s_total"]
    assert measured > 0

    # Nilainya harus bisa direproduksi dari run yang ada di dokumen.
    total_ms = 0.0
    runs = 0
    for entry in evidence["scenarios"]:
        for arm in entry["arms"].values():
            for run in arm["runs"]:
                if run.get("elapsed_ms") is not None:
                    total_ms += float(run["elapsed_ms"])
                    runs += 1
    assert timing["measured_arm_execution_runs"] == runs
    assert abs(measured - total_ms / 1000.0) < 0.5


def test_evidence_publishes_the_measurement_window_and_its_sessions(evidence):
    """Rentang rekam dan segmen eksekusi harus dipublikasikan, supaya
    jeda restart perangkat terlihat sebagai fakta, bukan tersembunyi di
    balik satu angka."""
    timing = evidence["timing"]
    window = timing["measurement_window"]
    assert window["first_run_recorded_at"] < window["last_run_recorded_at"]
    assert window["wall_clock_span_s"] > 0

    sessions = timing["execution_sessions"]
    assert sessions
    assert sum(session["runs"] for session in sessions) == sum(
        len(arm["runs"])
        for entry in evidence["scenarios"]
        for arm in entry["arms"].values()
    )
    # Sesi harus berurutan dan tidak saling tumpang tindih.
    for earlier, later in zip(sessions, sessions[1:]):
        assert earlier["ended_at"] <= later["started_at"]
        assert later["gap_before_s"] > timing["interruption_gap_threshold_s"]


def test_evidence_separates_the_invocation_wall_clock_from_the_measurement(evidence):
    """Durasi pemanggilan harness yang menulis dokumen harus dipublikasikan
    TERPISAH dari durasi kerja terukur, dengan cakupan yang dinyatakan."""
    invocation = evidence["timing"]["harness_invocation"]
    checkpoint = evidence["checkpoint"]
    assert invocation["runs_reused_from_checkpoint"] == checkpoint["runs_reused"]
    assert (
        invocation["runs_executed_this_invocation"]
        + invocation["runs_reused_from_checkpoint"]
        == checkpoint["runs_in_checkpoint"]
    )
    assert invocation["wall_clock_s"] > 0
    assert "TIDAK mencakup" in invocation["note"]


def test_execution_sessions_split_on_a_long_gap_but_not_on_a_short_one():
    """Fungsi harus memisahkan segmen hanya pada jeda yang benar-benar
    jeda, dan tidak pada jeda antar-run normal."""
    rows = [
        {
            "recorded_at": "2026-10-27T23:12:01.000000+00:00",
            "elapsed_ms": 100,
            "fixture_base_url": "http://127.0.0.1:1",
        },
        {
            "recorded_at": "2026-10-27T23:12:06.000000+00:00",
            "elapsed_ms": 100,
            "fixture_base_url": "http://127.0.0.1:1",
        },
        {
            "recorded_at": "2026-10-27T23:45:00.000000+00:00",
            "elapsed_ms": 100,
            "fixture_base_url": "http://127.0.0.1:2",
        },
    ]
    sessions = browser_diff_bench._execution_sessions(rows)
    assert len(sessions) == 2
    assert sessions[0]["runs"] == 2
    assert sessions[1]["runs"] == 1
    assert sessions[1]["gap_before_s"] == 1974.0
    assert sessions[0]["fixture_base_urls"] == ["http://127.0.0.1:1"]
    assert sessions[1]["fixture_base_urls"] == ["http://127.0.0.1:2"]


# --------------------------------------------------------------------------
# Celah E14 — ditutup tanpa menimpa bukti historis
# --------------------------------------------------------------------------


def test_e14_evidence_records_that_the_browser_arm_gap_is_now_closed():
    """Bukti historis E14 tidak boleh ditimpa — celah
    ``js_rendering_browser_arm`` ditutup lewat blok correction TERPISAH yang
    menunjuk E16, sementara blok correction yang menunjuk E15 (dan yang
    ditutup a05) tetap utuh."""
    e14 = json.loads(E14_EVIDENCE_PATH.read_text(encoding="utf-8"))

    e15_correction = e14.get("correction")
    assert e15_correction, "E14 wajib punya blok correction yang menunjuk E15"
    assert e15_correction["adr"] == "ADR-020"
    assert e15_correction["superseded_by"] == "docs/benchmark/engine-results-e15.json"
    assert "unsupported_scenarios[a05_protected]" in e15_correction["closed_gaps"]

    e16_correction = e14.get("correction_e16")
    assert e16_correction, "E14 wajib punya blok correction_e16 yang menunjuk E16"
    assert e16_correction["adr"] == "ADR-021"
    assert e16_correction["superseded_by"] == "docs/benchmark/engine-results-e16.json"
    assert "unsupported_scenarios[js_rendering_browser_arm]" in e16_correction["closed_gaps"]

    # Data mentah E14 tetap utuh: entri skenario tak didukung masih ada
    # dengan alasan yang sama — yang berubah hanya CATATAN bahwa celahnya
    # sudah tertutup, bukan isi measurement-nya.
    unsupported = {entry["scenario_id"]: entry for entry in e14["unsupported_scenarios"]}
    assert "js_rendering_browser_arm" in unsupported
    assert unsupported["js_rendering_browser_arm"]["supported_by"] == []
    assert "belum diukur" in unsupported["js_rendering_browser_arm"]["reason"]


# --------------------------------------------------------------------------
# Laporan dan ADR
# --------------------------------------------------------------------------


def test_report_and_adr_exist_and_cite_the_evidence(evidence):
    report = REPORT_PATH.read_text(encoding="utf-8")
    adr = ADR_PATH.read_text(encoding="utf-8")
    for text in (report, adr):
        assert "engine-results-e16.json" in text
        assert evidence["benchmark_id"] in text


def test_report_numbers_match_the_committed_evidence(evidence):
    """Angka di laporan harus berasal dari bukti, bukan ditulis manual."""
    report = REPORT_PATH.read_text(encoding="utf-8")
    totals = evidence["summary"]["per_arm_totals"]
    for arm, data in totals.items():
        assert f"{data['primary_success_runs']}/{data['runs']}" in report, arm


def test_report_and_adr_contain_no_stray_foreign_characters():
    """Defek kelas yang pernah berulang di repo ini: karakter dari skrip
    lain yang menyelinap ke teks. CJK adalah contoh yang pernah terjadi;
    Cyrillic pernah menyusul (dua kata Indonesia disalin dari sumber
    Mandarin lalu diganti sebagian, jadi separuhnya huruf asing).
    Rentang ditulis sebagai ordinal supaya berkas tes ini sendiri tidak
    memuat karakter asing."""
    forbidden = (
        (0x0400, 0x04FF),  # Cyrillic
        (0x0370, 0x03FF),  # Greek
        (0x4E00, 0x9FFF),  # CJK unified ideographs
        (0x3040, 0x30FF),  # Hiragana + Katakana
        (0xAC00, 0xD7AF),  # Hangul syllables
        (0xFF00, 0xFFEF),  # Fullwidth forms
    )
    for path in (REPORT_PATH, ADR_PATH):
        text = path.read_text(encoding="utf-8")
        offenders = [
            ch
            for ch in text
            if any(low <= ord(ch) <= high for low, high in forbidden)
        ]
        assert not offenders, (path.name, offenders[:10])


def test_benchmark_module_is_importable_without_side_effects():
    """Impor modul harness tidak boleh menjalankan benchmark."""
    assert callable(browser_diff_bench.main)
    assert browser_diff_bench.RESULTS_PATH.name == "engine-results-e16.json"
