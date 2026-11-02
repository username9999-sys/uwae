"""E15 — differential alur sesi UWAE vs Botasaurus.

Yang diuji di sini BUKAN angka benchmark (angka itu bukti yang di-commit),
melainkan INVARIAN harness — justru invarian yang menjaga benchmark tetap
jujur:

- ground truth berasal dari semantika protokol fixture, bukan dari engine
  yang diuji;
- keempat lengan memakai jalur Botasaurus yang benar (tidak pernah entrypoint
  yang selalu gagal dengan KeyError('headers'));
- baseline utama memakai BENTUK OBJEK SESI TERKUAT yang Botasaurus tawarkan,
  sehingga selisih tidak boleh berasal dari baseline yang dilemahkan;
- kriteria sukses menuntut body byte-for-byte, bukan status 200 saja;
- bukti sisi server adalah sumber kebenaran — bukan laporan arm;
- bukti yang di-commit konsisten dengan harness yang menghasilkannya.
"""

import ast
import hashlib
import json
import os
from pathlib import Path

import pytest

from universal_web_acquisition.benchmark import session_diff_bench
from universal_web_acquisition.benchmark.fixture_server import (
    PROTECTED_BODY,
    SESSION_COOKIE,
    SESSION_TOKEN,
    FixtureServer,
)
from universal_web_acquisition.benchmark.session_diff_bench import (
    ARM_SCRIPTS,
    ARMS,
    EXPECTED_BODY_BYTES,
    EXPECTED_BODY_SHA256,
    RUNS,
    SCENARIOS,
    _assess_run,
    _server_evidence,
    _summarise,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = REPO_ROOT / "docs" / "benchmark" / "engine-results-e15.json"
REPORT_PATH = REPO_ROOT / "docs" / "benchmark" / "session-flow-differential.md"
ADR_PATH = (
    REPO_ROOT
    / "docs"
    / "architecture"
    / "decisions"
    / "ADR-020-session-flow-differential.md"
)

EXPECTED_ARMS = (
    "uwae-engine",
    "botasaurus-auto",
    "botasaurus-explicit",
    "botasaurus-decorator-request",
)


@pytest.fixture(scope="module")
def evidence():
    return json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Ground truth — dari semantik protokol fixture
# --------------------------------------------------------------------------


def test_expected_body_is_derived_from_fixture_protocol_semantics():
    """Kriteria sukses diturunkan dari body yang benar-benar dilayani fixture,
    bukan dari output engine mana pun."""
    assert EXPECTED_BODY_SHA256 == hashlib.sha256(PROTECTED_BODY).hexdigest()
    assert EXPECTED_BODY_BYTES == len(PROTECTED_BODY)


def test_scenarios_cover_the_three_session_states():
    ids = [entry["id"] for entry in SCENARIOS]
    assert ids == ["session_valid", "session_required", "session_expired"]
    by_id = {entry["id"]: entry for entry in SCENARIOS}
    assert by_id["session_valid"]["expects_recovery"] is False
    assert by_id["session_required"]["expects_recovery"] is True
    assert by_id["session_expired"]["expects_recovery"] is True


def test_every_scenario_declares_its_cookie_mode():
    for entry in SCENARIOS:
        assert entry["cookie_mode"] in ("valid", "none", "stale"), entry["id"]


# --------------------------------------------------------------------------
# Integritas lengan
# --------------------------------------------------------------------------


def test_every_arm_has_metadata_and_a_script():
    assert set(ARMS) == set(ARM_SCRIPTS)
    assert set(ARMS) == set(EXPECTED_ARMS)


def test_every_arm_script_is_valid_python():
    for name, script in ARM_SCRIPTS.items():
        ast.parse(script)  # raises SyntaxError on failure
        assert script.strip(), name


def test_arm_scripts_never_call_the_broken_botasaurus_entrypoint():
    """``botasaurus_requests.get(url)`` tanpa header SELALU gagal dengan
    KeyError('headers') — bug pemanggil, bukan batas platform (ADR-019).

    Pemeriksaan di AST, bukan di teks: entrypoint yang salah boleh DIBHASILKAN
    di komentar (itu justru menjelaskan bug-nya), tapi tidak boleh DIPANGGIL.
    """
    for name, script in ARM_SCRIPTS.items():
        tree = ast.parse(script)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "get":
                continue
            owner = node.func.value
            assert not (
                isinstance(owner, ast.Name) and owner.id == "botasaurus_requests"
            ), (name, "memanggil botasaurus_requests.get()")


def test_every_botasaurus_call_supplies_headers_or_uses_request_api():
    """Setiap pemanggilan HTTP pada lengan Botasaurus harus punya ``headers``
    eksplisit, atau memakai ``Session.request(...)`` yang tidak butuh header.

    Tanpa ini lengan gagal dengan KeyError('headers') sebelum ada I/O — dan
    baseline yang gagal karena bug pemanggil bukan pengukuran apa pun.

    Hanya pemanggilan pada objek SESI yang diperiksa; ``dict.get`` adalah
    API lain dan tidak relevan.
    """
    for name in ("botasaurus-auto", "botasaurus-explicit", "botasaurus-decorator-request"):
        tree = ast.parse(ARM_SCRIPTS[name])
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "get":
                continue
            owner = node.func.value
            if not (isinstance(owner, ast.Name) and owner.id in ("session", "reqs")):
                continue
            kwargs = {kw.arg for kw in node.keywords}
            assert "headers" in kwargs, (name, "get() tanpa headers")


def test_explicit_arm_uses_the_strongest_botasaurus_session_object():
    """Baseline utama WAJIB memakai ``botasaurus_requests.Session()`` eksplisit.

    Objek ``reqs`` dari dekorator tidak menyimpan cookie — memakainya sebagai
    baseline akan membuat Botasaurus tampak "tidak punya sesi", artefak objek
    dan bukan batas platform.
    """
    for name in ("botasaurus-auto", "botasaurus-explicit"):
        script = ARM_SCRIPTS[name]
        assert "from botasaurus_requests import Session" in script, name
        assert "Session()" in script, name


def test_explicit_arm_relies_on_the_cookie_jar_not_manual_header_parsing():
    """Recovery lengan eksplisit harus mengandalkan cookie jar session.

    Parse manual header ``Set-Cookie`` akan mengukur jumlah baris kode yang
    ditulis pengguna, bukan perilaku platform — dan bisa benar sambil
    mengukur hal yang salah (bukti: lengan dekorator "berhasil" recovery tapi
    retry-nya tetap tanpa cookie).
    """
    script = ARM_SCRIPTS["botasaurus-explicit"]
    assert "set-cookie" not in script.lower()
    assert "_cookie_from_response" not in script


def test_decorator_arm_runs_the_same_recovery_logic_on_the_decorator_object():
    """Lengan dekorator menjalankan recovery IDENTIK pada objek bawaan
    dekorator — itu yang membuktikannya sebagai temuan platform, bukan
    sekadar menulis recovery yang lebih buruk."""
    script = ARM_SCRIPTS["botasaurus-decorator-request"]
    assert "reqs.get(" in script
    assert "login_url" in script

    # Dilarang memakai Session() —object ini harus benar-benar yang diberikan
    # dekorator. Pemeriksaan di AST: nama boleh DIBHASILKAN di docstring
    # (itu menjelaskan temuan), tapi tidak boleh DI-IMPORT atau DIPANGGIL.
    tree = ast.parse(script)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "botasaurus_requests":
            assert "Session" not in {alias.name for alias in node.names}
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "Session"


def test_decorator_arm_is_registered_as_its_own_arm_with_a_policy():
    assert ARMS["botasaurus-decorator-request"]["recovery_policy"] == "written_in_arm_code"
    assert ARMS["botasaurus-auto"]["recovery_policy"] == "none"
    assert ARMS["uwae-engine"]["recovery_policy"] == "engine_generic"


# --------------------------------------------------------------------------
# Kriteria sukses
# --------------------------------------------------------------------------


def _outcome(**kwargs):
    base = {
        "status_code": 200,
        "body_sha256": EXPECTED_BODY_SHA256,
        "body_bytes": EXPECTED_BODY_BYTES,
        "attempts": 1,
        "recovery_outcome": None,
        "elapsed_ms": 10.0,
        "error": None,
    }
    base.update(kwargs)
    return base


def test_success_requires_status_and_byte_for_byte_body():
    row = _assess_run(_outcome(), [])
    assert row["reached_protected"] is True
    assert row["content_ok"] is True


def test_status_200_with_wrong_body_is_not_a_success():
    row = _assess_run(_outcome(body_sha256="0" * 64), [])
    assert row["status_code"] == 200
    assert row["content_ok"] is False
    assert row["reached_protected"] is False


def test_status_401_is_not_a_success_even_with_the_right_body_hash():
    row = _assess_run(_outcome(status_code=401), [])
    assert row["reached_protected"] is False


def test_arm_reported_attempts_is_kept_separate_from_server_observed_requests():
    """``arm_reported_attempts`` menghitung attempt job di repository (UWAE)
    vs pemanggilan HTTP di dalam arm (Botasaurus) — satuan berbeda, jadi
    tidak boleh dibandingkan antar-lengan. Metrik comparable adalah
    ``server_observed.total_requests``."""
    row = _assess_run(_outcome(attempts=99), [])
    assert row["arm_reported_attempts"] == 99
    assert "attempts" not in row
    assert row["server_observed"]["total_requests"] == 0


def test_summarise_counts_successes_and_server_requests():
    rows = [
        _assess_run(_outcome(), [
            {"method": "GET", "path": "/protected", "status": 200, "cookie": "x=1"},
        ]),
        _assess_run(_outcome(status_code=401), []),
    ]
    summary = _summarise(rows)
    assert summary["runs"] == 2
    assert summary["reached_protected_runs"] == 1
    assert summary["primary_success_rate"] == 0.5
    assert summary["server_observed_total_requests"] == [1, 0]


# --------------------------------------------------------------------------
# Bukti sisi server
# --------------------------------------------------------------------------


def test_server_evidence_separates_protected_and_login_requests():
    log = [
        {"method": "GET", "path": "/protected", "status": 401, "cookie": ""},
        {"method": "GET", "path": "/session-login", "status": 200, "cookie": ""},
        {"method": "GET", "path": "/protected", "status": 200, "cookie": "uwae_session=t"},
    ]
    evidence = _server_evidence(log)
    assert evidence["total_requests"] == 3
    assert evidence["login_requests"] == 1
    assert evidence["protected_get_requests"] == 2
    assert evidence["first_protected_status"] == 401
    assert evidence["final_protected_status"] == 200
    assert evidence["cookies_seen_on_protected"] == ["", "uwae_session=t"]


def test_server_evidence_handles_an_empty_log():
    evidence = _server_evidence([])
    assert evidence["total_requests"] == 0
    assert evidence["first_protected_status"] is None
    assert evidence["final_protected_status"] is None


# --------------------------------------------------------------------------
# Fixture — semantik sesi
# --------------------------------------------------------------------------


def test_fixture_rejects_protected_without_a_session_cookie():
    with FixtureServer(port=0) as base:
        import urllib.error
        import urllib.request

        try:
            urllib.request.urlopen(base + "/protected", timeout=5)
            raise AssertionError("seharusnya 401")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401


def test_fixture_grants_protected_with_the_active_cookie():
    with FixtureServer(port=0) as base:
        import urllib.request

        req = urllib.request.Request(base + "/protected")
        req.add_header("Cookie", f"{SESSION_COOKIE}={SESSION_TOKEN}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
            assert resp.read() == PROTECTED_BODY


def test_expiring_the_session_invalidates_the_old_cookie_server_side():
    """Sesi dicabut di sisi server — cookie lama secara sintaksis valid
    tetap ditolak 401."""
    server = FixtureServer(port=0)
    with server as base:
        import urllib.error
        import urllib.request

        new_token = server.expire_session()
        assert new_token != SESSION_TOKEN

        req = urllib.request.Request(base + "/protected")
        req.add_header("Cookie", f"{SESSION_COOKIE}={SESSION_TOKEN}")
        try:
            urllib.request.urlopen(req, timeout=5)
            raise AssertionError("cookie lama harus ditolak setelah pencabutan")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401


def test_resetting_the_session_restores_the_identical_starting_condition():
    """Tanpa reset, lengan pertama yang me-recovery mewarisi token milik
    lengan sebelumnya — lengan yang menang bukan karena lebih baik."""
    server = FixtureServer(port=0)
    with server as base:
        import urllib.request

        server.expire_session()
        server.reset_session()
        assert server.active_session_token == SESSION_TOKEN

        req = urllib.request.Request(base + "/protected")
        req.add_header("Cookie", f"{SESSION_COOKIE}={SESSION_TOKEN}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200


def test_a_new_session_token_grants_access_after_expiry():
    """Token baru yang diterbitkan endpoint login harus bisa mengakses
    resource — inilah yang membuat recovery bisa berhasil sama sekali."""
    server = FixtureServer(port=0)
    with server as base:
        import urllib.request

        new_token = server.expire_session()
        req = urllib.request.Request(base + "/protected")
        req.add_header("Cookie", f"{SESSION_COOKIE}={new_token}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
            assert resp.read() == PROTECTED_BODY


def test_fixture_records_requests_when_asked():
    """Regresi: flag ``record_requests`` harus diteruskan ke objek HTTP server
    dan log harus berupa list yang SAMA dengan yang dibaca parent — tanpa itu
    handler gagal sebelum respons terkirim dan klien melihat EOF.
    """
    server = FixtureServer(port=0, record_requests=True)
    with server as base:
        import urllib.request

        req = urllib.request.Request(base + "/protected")
        req.add_header("Cookie", f"{SESSION_COOKIE}={SESSION_TOKEN}")
        with urllib.request.urlopen(req, timeout=5):
            pass
        assert len(server.request_log) == 1
        entry = server.request_log[0]
        assert entry["method"] == "GET"
        assert entry["path"] == "/protected"
        assert entry["status"] == 200
        assert SESSION_COOKIE in entry["cookie"]


def test_fixture_does_not_record_requests_by_default():
    server = FixtureServer(port=0)
    with server as base:
        import urllib.request

        with urllib.request.urlopen(base + "/html", timeout=5):
            pass
        assert server.request_log == []


def test_fixture_port_zero_yields_a_usable_port():
    """port=0 berarti OS memilih port bebas — base URL yang dikembalikan harus
    menunjuk port nyata, bukan 0."""
    with FixtureServer(port=0) as base:
        assert not base.endswith(":0/")
        import urllib.request

        with urllib.request.urlopen(base + "/html", timeout=5) as resp:
            assert resp.status == 200


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


def test_evidence_has_no_runtime_failures(evidence):
    for entry in evidence["scenarios"]:
        for arm, data in entry["arms"].items():
            assert data["summary"]["runtime_failures"] == 0, (entry["scenario_id"], arm)


def test_evidence_summary_counts_match_the_scenario_data(evidence):
    for arm in EXPECTED_ARMS:
        recomputed = sum(
            entry["arms"][arm]["summary"]["reached_protected_runs"]
            for entry in evidence["scenarios"]
        )
        assert evidence["summary"]["primary_success_runs"][arm] == recomputed


def test_evidence_automatic_recovery_axis_covers_only_recovery_scenarios(evidence):
    axis = evidence["summary"]["automatic_recovery_axis"]
    recovery_scenarios = [
        entry for entry in evidence["scenarios"] if entry["expects_recovery"]
    ]
    expected_runs = len(recovery_scenarios) * RUNS
    for arm, data in axis.items():
        assert data["of_runs"] == expected_runs, arm
        assert data["reached_protected_runs"] <= expected_runs, arm


def test_evidence_server_side_log_proves_uwae_recovery_reached_the_resource(evidence):
    """Bukti recovery UWAE bukan klaim arm — log server harus menunjukkan
    request login nyata lalu /protected 200 dengan cookie."""
    by_scenario = {entry["scenario_id"]: entry for entry in evidence["scenarios"]}
    for scenario_id in ("session_required", "session_expired"):
        data = by_scenario[scenario_id]["arms"]["uwae-engine"]
        assert data["summary"]["reached_protected_runs"] == RUNS, scenario_id
        for run in data["runs"]:
            observed = run["server_observed"]
            assert observed["login_requests"] >= 1, scenario_id
            assert observed["final_protected_status"] == 200, scenario_id
            assert any(SESSION_COOKIE in cookie for cookie in observed["cookies_seen_on_protected"])


def test_evidence_commits_the_botasaurus_decorator_cookie_finding(evidence):
    """Temuan platform Botasaurus — objek dekorator tidak menyimpan cookie —
    harus TERKOMIT sebagai bukti server-side, bukan jadi catatan lisan."""
    by_scenario = {entry["scenario_id"]: entry for entry in evidence["scenarios"]}
    for scenario_id in ("session_required", "session_expired"):
        data = by_scenario[scenario_id]["arms"]["botasaurus-decorator-request"]
        assert data["summary"]["reached_protected_runs"] == 0, scenario_id
        for run in data["runs"]:
            observed = run["server_observed"]
            assert observed["login_requests"] >= 1, scenario_id
            assert observed["final_protected_status"] == 401, scenario_id


def test_evidence_shows_the_explicit_baseline_is_not_weakened(evidence):
    """Baseline eksplisit harus mencapai hasil penuh — kalau tidak, perbandingan
    ini memang pembanding yang sengaja dibuat lemah."""
    by_scenario = {entry["scenario_id"]: entry for entry in evidence["scenarios"]}
    for scenario_id in ("session_valid", "session_required", "session_expired"):
        data = by_scenario[scenario_id]["arms"]["botasaurus-explicit"]
        assert data["summary"]["reached_protected_runs"] == RUNS, scenario_id


def test_evidence_does_not_claim_uwae_outperforms_botasaurus(evidence):
    """Mandat INSTRUCTION.md: hasil baseline, bukan klaim unggul. Lengan
    eksplisit mencapai hasil yang sama dengan UWAE."""
    interpretation = evidence["summary"]["interpretation"]
    assert "BUKAN" in interpretation
    assert "baseline" in interpretation.lower()
    by_scenario = {entry["scenario_id"]: entry for entry in evidence["scenarios"]}
    uwae = by_scenario["session_required"]["arms"]["uwae-engine"]["summary"]
    explicit = by_scenario["session_required"]["arms"]["botasaurus-explicit"]["summary"]
    assert uwae["reached_protected_runs"] == explicit["reached_protected_runs"]


def test_e14_evidence_records_that_the_a05_gap_is_now_closed():
    """Bukti historis E14 tidak boleh ditimpa — celah ``a05_protected`` yang
    dideklarasikannya ditutup lewat blok ``correction`` yang menunjuk E15
    (preseden ADR-018/ADR-019)."""
    e14 = json.loads(
        (REPO_ROOT / "docs" / "benchmark" / "engine-results-e14.json").read_text(
            encoding="utf-8"
        )
    )
    correction = e14.get("correction")
    assert correction, "E14 wajib punya blok correction yang menunjuk E15"
    assert correction["adr"] == "ADR-020"
    assert correction["superseded_by"] == "docs/benchmark/engine-results-e15.json"
    assert "unsupported_scenarios[a05_protected]" in correction["closed_gaps"]

    # Data mentah E14 tetap utuh: entri skenario tak didukung masih ada
    # dengan alasan yang sama — yang berubah hanya CATATAN bahwa celahnya
    # sudah tertutup, bukan isi measurement-nya.
    unsupported = {entry["scenario_id"]: entry for entry in e14["unsupported_scenarios"]}
    assert "a05_protected" in unsupported
    assert unsupported["a05_protected"]["supported_by"] == []
    assert "Perbandingan alur sesi belum diukur." in unsupported["a05_protected"]["reason"]


def test_report_and_adr_exist_and_cite_the_evidence(evidence):
    report = REPORT_PATH.read_text(encoding="utf-8")
    adr = ADR_PATH.read_text(encoding="utf-8")
    for text in (report, adr):
        assert "engine-results-e15.json" in text
        assert evidence["benchmark_id"] in text


def test_report_numbers_match_the_committed_evidence(evidence):
    """Angka di laporan harus berasal dari bukti, bukan ditulis manual."""
    report = REPORT_PATH.read_text(encoding="utf-8")
    totals = evidence["summary"]["primary_success_runs"]
    for arm, count in totals.items():
        assert f"{count}/{len(evidence['scenarios']) * RUNS}" in report, arm


def test_report_and_adr_contain_no_stray_cjk_characters():
    """Defek kelas yang pernah berulang di repo ini: karakter CJK yang
    menyelinap ke teks."""
    for path in (REPORT_PATH, ADR_PATH):
        text = path.read_text(encoding="utf-8")
        offenders = [ch for ch in text if "一" <= ch <= "鿿"]
        assert not offenders, (path.name, offenders[:10])


# --------------------------------------------------------------------------
# Checkpoint per-run — restart perangkat tidak boleh menghapus run
#
# E16 kehilangan 393 dari 480 run karena evidence hanya ditulis di akhir
# main() dan perangkat mati di tengah jalan. Harness E15 sekarang menulis
# checkpoint JSONL tiap run selesai, dan durasi dipublikasikan sebagai blok
# timing yang menamai cakupannya — bukan sebagai satu angka telanjang.
# --------------------------------------------------------------------------


TOTAL_RUNS = RUNS * len(SCENARIOS) * len(ARM_SCRIPTS)


def _checkpoint_row(**overrides):
    """Row kasar E15 — bentuk yang sama persis dengan row di dokumen."""
    base = {
        "status_code": 200,
        "body_sha256": EXPECTED_BODY_SHA256,
        "body_bytes": EXPECTED_BODY_BYTES,
        "content_ok": True,
        "reached_protected": True,
        "arm_reported_attempts": 1,
        "recovery_outcome": None,
        "recovery_generation": None,
        "diagnosis_state": "succeeded",
        "diagnosis_reason": None,
        "terminal_status": "succeeded",
        "elapsed_ms": 12.5,
        "error": None,
        "server_observed": {
            "total_requests": 1,
            "login_requests": 0,
            "protected_get_requests": 1,
            "protected_head_requests": 0,
            "first_protected_status": 200,
            "final_protected_status": 200,
            "cookies_seen_on_protected": [SESSION_COOKIE + "=token"],
        },
        "run_index": 0,
        "stdout_tail": "",
        "stderr_tail": "",
        "recorded_at": "2026-10-27T23:12:01.000000+00:00",
        "fixture_base_url": "http://127.0.0.1:8080",
    }
    base.update(overrides)
    return base


def _fake_run_arm(script, payload_path, out_path, timeout):
    """Arm tiruan: mengembalikan row sukses tanpa menjalankan subprocess."""
    return {
        "engine_id": "fake-arm",
        "outcome": {
            "status_code": 200,
            "body_sha256": EXPECTED_BODY_SHA256,
            "body_bytes": EXPECTED_BODY_BYTES,
            "attempts": 1,
            "recovery_outcome": None,
            "recovery_generation": None,
            "diagnosis_state": "succeeded",
            "diagnosis_reason": None,
            "terminal_status": "succeeded",
            "error": None,
            "elapsed_ms": 12.5,
        },
        "stdout_tail": "",
        "stderr_tail": "",
    }


def _run_harness(tmp_path, monkeypatch, checkpoint_path):
    """Jalankan ``main()`` E15 dengan arm tiruan.

    Mengembalikan (skrip arm yang dipanggil, dokumen yang ditulis). Loop
    per-run, checkpoint, dan blok timing bisa diuji tanpa membakar waktu
    device — dan tanpa menjalankan benchmark sungguhan.
    """
    calls = []

    def counting_run_arm(script, payload_path, out_path, timeout):
        calls.append(script)
        return _fake_run_arm(script, payload_path, out_path, timeout)

    monkeypatch.setattr(session_diff_bench, "_preflight", lambda: None)
    monkeypatch.setattr(session_diff_bench, "_interpreter_identity", lambda: {})
    monkeypatch.setattr(session_diff_bench, "_package_versions", lambda: {})
    monkeypatch.setattr(session_diff_bench, "_run_arm", counting_run_arm)
    monkeypatch.setattr(session_diff_bench, "RESULTS_PATH", tmp_path / "e15.json")
    monkeypatch.setattr(session_diff_bench, "CHECKPOINT_PATH", checkpoint_path)
    session_diff_bench.main()
    document = json.loads((tmp_path / "e15.json").read_text(encoding="utf-8"))
    return calls, document


def _flat_rows(document):
    return [
        row
        for entry in document["scenarios"]
        for arm in entry["arms"].values()
        for row in arm["runs"]
    ]


def test_checkpoint_path_lives_outside_the_repository():
    """Checkpoint default tidak boleh pernah ikut ter-commit."""
    default = Path(
        os.environ.get("UWAE_E15_CHECKPOINT", "/root/.qwen/tmp/e15_checkpoint.jsonl")
    )
    assert default == Path("/root/.qwen/tmp/e15_checkpoint.jsonl")
    assert REPO_ROOT not in default.parents


def test_harness_fingerprint_changes_when_the_measured_configuration_changes(monkeypatch):
    """Sidik jari harus memengaruhi run, timeout, skenario, skrip arm, dan
    kebijakan recovery — kalau tidak, checkpoint lama bisa tercampur diam-diam
    dengan run yang memakai kriteria berbeda."""
    before = session_diff_bench._harness_fingerprint()
    assert len(before) == 64

    monkeypatch.setattr(session_diff_bench, "RUNS", RUNS + 1)
    assert session_diff_bench._harness_fingerprint() != before


def test_checkpoint_resumes_completed_runs_instead_of_reexecuting(tmp_path):
    """Restart setelah perangkat reboot tidak boleh mengulang run yang sudah
    selesai — itulah yang membuat 393/480 run hilang sekali saja."""
    path = tmp_path / "checkpoint.jsonl"
    checkpoint = session_diff_bench._Checkpoint(path)
    assert checkpoint.rows == {}

    row = _checkpoint_row()
    checkpoint.append("session_valid", "uwae-engine", 0, row)

    resumed = session_diff_bench._Checkpoint(path)
    assert resumed.get("session_valid", "uwae-engine", 0) == row
    assert resumed.get("session_valid", "uwae-engine", 1) is None
    assert resumed.get("session_required", "uwae-engine", 0) is None


def test_checkpoint_ignores_rows_recorded_with_another_harness_configuration(tmp_path):
    """Kalau konfigurasi harness berubah, run lama tidak boleh dibandingkan
    dengan run baru. Fingerprint membuat mismatch terlihat, bukan diam-diam."""
    path = tmp_path / "checkpoint.jsonl"
    path.write_text(
        json.dumps(
            {
                "fingerprint": "fingerprint-dari-harness-lain",
                "scenario_id": "session_valid",
                "arm_id": "uwae-engine",
                "run_index": 0,
                "row": _checkpoint_row(),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    checkpoint = session_diff_bench._Checkpoint(path)
    assert checkpoint.get("session_valid", "uwae-engine", 0) is None
    assert checkpoint.ignored_records == 1


def test_checkpoint_survives_a_truncated_last_line(tmp_path):
    """Kalau proses mati tepat saat menulis, baris terakhir bisa terpotong.
    Baris rusak diabaikan; sisanya tetap dipakai."""
    path = tmp_path / "checkpoint.jsonl"
    checkpoint = session_diff_bench._Checkpoint(path)
    checkpoint.append("session_valid", "uwae-engine", 0, _checkpoint_row())
    with open(path, "a", encoding="utf-8") as handle:
        handle.write('{"fingerprint": "abc", "scope_id": "session_req')

    resumed = session_diff_bench._Checkpoint(path)
    assert resumed.get("session_valid", "uwae-engine", 0) is not None
    assert resumed.ignored_records == 1


def test_second_invocation_reuses_every_run_and_executes_no_new_arms(
    tmp_path, monkeypatch
):
    """Kriteria utama: pemanggilan kedua memakai ulang SEMUA run dan
    menjalankan nol arm baru."""
    checkpoint_path = tmp_path / "e15_checkpoint.jsonl"

    calls, first = _run_harness(tmp_path, monkeypatch, checkpoint_path)
    assert len(calls) == TOTAL_RUNS
    assert first["checkpoint"]["runs_in_checkpoint"] == TOTAL_RUNS
    assert first["checkpoint"]["runs_reused"] == 0

    calls_again, second = _run_harness(tmp_path, monkeypatch, checkpoint_path)
    assert calls_again == [], "invocation kedua tidak boleh menjalankan arm baru"
    assert second["checkpoint"]["runs_in_checkpoint"] == TOTAL_RUNS
    assert second["checkpoint"]["runs_reused"] == TOTAL_RUNS
    assert second["timing"]["harness_invocation"]["runs_executed_this_invocation"] == 0
    assert second["timing"]["harness_invocation"]["runs_reused_from_checkpoint"] == (
        TOTAL_RUNS
    )


def test_reused_rows_keep_every_field_a_live_row_has(tmp_path, monkeypatch):
    """Row yang dipakai ulang harus identik dengan row hidup — tidak boleh ada
    field yang hilang. Bukti sisi server (``server_observed``) hanya ada
    selama run hidup, jadi kalau hilang, run yang dipakai ulang diam-diam
    kehilangan bukti server."""
    checkpoint_path = tmp_path / "e15_checkpoint.jsonl"
    _run_harness(tmp_path, monkeypatch, checkpoint_path)
    _, second = _run_harness(tmp_path, monkeypatch, checkpoint_path)

    reused_rows = _flat_rows(second)
    assert len(reused_rows) == TOTAL_RUNS
    for row in reused_rows:
        for field in (
            "server_observed",
            "recorded_at",
            "elapsed_ms",
            "fixture_base_url",
        ):
            assert field in row, field
        assert row["server_observed"]["total_requests"] == 0
        assert row["elapsed_ms"] == 12.5
        assert row["fixture_base_url"].startswith("http://")
        assert row["recorded_at"]


def test_reused_rows_are_identical_to_the_live_rows_they_replace(tmp_path, monkeypatch):
    """Row checkpoint = row kasar yang sama persis dengan yang masuk dokumen
    pada run hidup. Kalau berbeda, ada field yang hilang diam-diam."""
    checkpoint_path = tmp_path / "e15_checkpoint.jsonl"
    _, first = _run_harness(tmp_path, monkeypatch, checkpoint_path)
    _, second = _run_harness(tmp_path, monkeypatch, checkpoint_path)
    assert _flat_rows(second) == _flat_rows(first)


def test_published_document_has_no_bare_elapsed_s_and_publishes_timing_and_checkpoint(
    tmp_path, monkeypatch
):
    """``elapsed_s`` tingkat dokumen dulu hanya mengukur SATU pemanggilan
    harness. Karena sebagian besar run diambil dari checkpoint, angka itu
    jauh lebih kecil daripada durasi kerja sebenarnya, dan pembaca akan
    salah menyimpulkan seluruh benchmark hanya memakan waktu itu.

    Jadi field itu harus hilang, dan penggantinya harus menamai cakupannya
    sendiri."""
    checkpoint_path = tmp_path / "e15_checkpoint.jsonl"
    _run_harness(tmp_path, monkeypatch, checkpoint_path)
    _, document = _run_harness(tmp_path, monkeypatch, checkpoint_path)

    assert "elapsed_s" not in document
    assert "timing" in document
    assert "checkpoint" in document

    timing = document["timing"]
    assert timing["measured_arm_execution_runs"] == TOTAL_RUNS
    assert timing["measured_arm_execution_s_total"] > 0
    assert timing["measurement_window"]["first_run_recorded_at"]
    assert timing["measurement_window"]["last_run_recorded_at"]
    assert timing["harness_invocation"]["wall_clock_s"] > 0
    assert "TIDAK mencakup" in timing["harness_invocation"]["note"]

    checkpoint = document["checkpoint"]
    assert checkpoint["runs_in_checkpoint"] == TOTAL_RUNS
    assert checkpoint["checkpoint_path"] == str(checkpoint_path)
    assert checkpoint["harness_fingerprint"] == session_diff_bench._harness_fingerprint()


def test_checkpoint_run_count_matches_the_number_of_runs_in_the_document(
    tmp_path, monkeypatch
):
    """Jumlah run di checkpoint harus sama dengan jumlah run di dokumen —
    kalau tidak, ada run yang hilang atau dobel."""
    checkpoint_path = tmp_path / "e15_checkpoint.jsonl"
    _run_harness(tmp_path, monkeypatch, checkpoint_path)
    _, document = _run_harness(tmp_path, monkeypatch, checkpoint_path)
    assert document["checkpoint"]["runs_in_checkpoint"] == len(_flat_rows(document))


def test_a_checkpoint_from_another_harness_is_never_mixed_into_the_results(
    tmp_path, monkeypatch
):
    """Record dengan fingerprint lain diabaikan dan DILAPORKAN — bukan
    dipakai diam-diam di samping run yang baru."""
    checkpoint_path = tmp_path / "e15_checkpoint.jsonl"
    foreign_row = _checkpoint_row(elapsed_ms=999.0, body_sha256="0" * 64)
    checkpoint_path.write_text(
        json.dumps(
            {
                "fingerprint": "fingerprint-dari-harness-lain",
                "scope_id": "session_valid",
                "subject_id": "uwae-engine",
                "index": 0,
                "row": foreign_row,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    calls, document = _run_harness(tmp_path, monkeypatch, checkpoint_path)
    assert len(calls) == TOTAL_RUNS
    assert document["checkpoint"]["records_ignored"] == 1
    assert document["checkpoint"]["runs_reused"] == 0

    first_row = document["scenarios"][0]["arms"]["uwae-engine"]["runs"][0]
    assert first_row["elapsed_ms"] != 999.0
    assert first_row["body_sha256"] == EXPECTED_BODY_SHA256


def test_a_corrupt_last_line_does_not_break_the_remaining_runs(tmp_path, monkeypatch):
    """Baris terakhir yang terpotong (perangkat mati tepat saat menulis)
    tidak boleh menggagalkan pemuatan checkpoint."""
    checkpoint_path = tmp_path / "e15_checkpoint.jsonl"
    _run_harness(tmp_path, monkeypatch, checkpoint_path)
    with open(checkpoint_path, "a", encoding="utf-8") as handle:
        handle.write('{"fingerprint": "abc", "scope_id": "session_req')

    calls, document = _run_harness(tmp_path, monkeypatch, checkpoint_path)
    assert calls == [], "run yang utuh tidak boleh dieksekusi ulang"
    assert document["checkpoint"]["records_ignored"] == 1
    assert document["checkpoint"]["runs_reused"] == TOTAL_RUNS
    assert len(_flat_rows(document)) == TOTAL_RUNS
