"""CLI end-to-end tests: perintah ``acquire`` menjalankan siklus ACP penuh.

Yang diverifikasi:
- akuisisi sukses → exit 0, diagnosis access_granted, artifact dengan SHA-256;
- challenge → exit 2 (NEEDS_USER — intervensi pengguna);
- rate limit berbatas → exit 1 dengan diagnosis rate_limited;
- 404 → exit 1 dengan diagnosis content_invalid;
- flag --browser ter-wire tanpa mengubah hasil jalur sukses langsung;
- --session-login tanpa --session-cookie → UsageError;
- output human memuat diagnosis + jejak bukti (assessment/decision).
"""

import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from click.testing import CliRunner

from universal_web_acquisition.benchmark.fixture_server import FixtureServer
from universal_web_acquisition.cli.main import cli


@pytest.fixture()
def runner():
    return CliRunner()


def _paths():
    fd, db = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return db, tempfile.mkdtemp(prefix="uwae-cli-artifacts-")


def _run(runner, args):
    db, artifacts = _paths()
    try:
        return runner.invoke(cli, ["acquire", *args, "--db", db, "--artifacts-dir", artifacts])
    finally:
        os.unlink(db)


class TestAcquireSuccess:
    def test_html_fixture_succeeds_with_json_evidence(self, runner):
        with FixtureServer() as base:
            result = _run(runner, [base + "/html", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["job_status"] == "succeeded"
        assert payload["observed_state"] == "access_granted"
        assert payload["observed_reason"] == "ok"
        assert payload["artifact"]["sha256"]
        assert payload["artifact"]["size_bytes"] > 0
        # jejak bukti: minimal satu assessment + satu decision
        kinds = {item["kind"] for item in payload["lineage"]}
        assert "assessment" in kinds
        assert "decision" in kinds

    def test_human_output_shows_diagnosis_and_evidence(self, runner):
        with FixtureServer() as base:
            result = _run(runner, [base + "/html"])
        assert result.exit_code == 0, result.output
        assert "Status  : succeeded" in result.output
        assert "Diagnosis: access_granted (ok)" in result.output
        assert "assessment: state=access_granted" in result.output
        assert "decision  : action=accept" in result.output


class TestAcquireDiagnosis:
    def test_challenge_exits_2_needs_user(self, runner):
        with FixtureServer() as base:
            result = _run(runner, [base + "/challenge", "--json"])
        assert result.exit_code == 2, result.output
        payload = json.loads(result.output)
        assert payload["job_status"] == "needs_user"
        assert payload["observed_state"] == "challenge_present"

    def test_rate_limited_exits_1_with_diagnosis(self, runner):
        with FixtureServer() as base:
            result = _run(runner, [base + "/rate-limited", "--json", "--max-retries", "1"])
        assert result.exit_code == 1, result.output
        payload = json.loads(result.output)
        assert payload["job_status"] == "failed"
        assert payload["observed_state"] == "rate_limited"
        assert "budget_exhausted" in (payload["error"] or "")

    def test_missing_page_exits_1_content_invalid(self, runner):
        with FixtureServer() as base:
            result = _run(runner, [base + "/missing", "--json"])
        assert result.exit_code == 1, result.output
        payload = json.loads(result.output)
        assert payload["observed_state"] == "content_invalid"

    def test_denied_exits_2_never_retried(self, runner):
        # ACP §2.2: penolakan eksplisit → NEEDS_USER, tepat satu attempt
        with FixtureServer() as base:
            result = _run(runner, [base + "/denied", "--json"])
        assert result.exit_code == 2, result.output
        payload = json.loads(result.output)
        assert payload["observed_state"] == "access_denied"
        assert len(payload["attempts"]) == 1


class TestAcquireOptions:
    def test_browser_flag_wires_adapter_without_changing_direct_success(self, runner):
        with FixtureServer() as base:
            result = _run(runner, [base + "/html", "--json", "--browser"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["job_status"] == "succeeded"
        assert payload["observed_state"] == "access_granted"

    def test_session_flags_require_both(self, runner):
        with FixtureServer() as base:
            result = _run(runner, [base + "/html", "--session-login", base + "/session-login"])
        assert result.exit_code != 0
        assert "bersamaan" in result.output


class TestDiscoverCommand:
    def test_discover_fixture_sitemap(self, runner):
        # robots → sitemap index → child → /html; /private difilter robots,
        # external dibuang, .xml bukan konten
        with FixtureServer() as base:
            result = runner.invoke(cli, ["discover", base, "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["robots_compliant"] is True
        assert payload["count"] == 1
        assert payload["urls"][0].endswith("/html")

    def test_discover_respects_robots_in_human_output(self, runner):
        with FixtureServer() as base:
            result = runner.invoke(cli, ["discover", base])
        assert result.exit_code == 0, result.output
        assert "Ditemukan: 1 URL" in result.output
        assert "/private" not in result.output


class TestCalibrateCommand:
    def test_calibrate_shows_calibrated_granted_from_real_runs(self, runner):
        # Korpus gabungan: granted 22 sampel (2 sintetis + 10 kasus target
        # nyata + 7 komiku-capabilities + 3 E9) → source "calibrated" —
        # kalibrasi nyata aktif §3.2
        result = runner.invoke(cli, ["calibrate", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["min_samples"] == 10
        assert payload["real_cases"] >= 27
        states = {row["state"]: row for row in payload["states"]}
        assert len(states) == 9
        granted = states["access_granted"]
        assert granted["samples"] == 22
        assert granted["source"] == "calibrated"
        assert granted["confidence"] == 1.0

    def test_calibrate_human_output(self, runner):
        result = runner.invoke(cli, ["calibrate"])
        assert result.exit_code == 0, result.output
        assert "Kalibrasi confidence (min_samples=10):" in result.output
        assert "categorical-default" in result.output  # bucket < 10 sampel


def _run_crawl(runner, args):
    db, artifacts = _paths()
    try:
        return runner.invoke(
            cli, ["crawl", *args, "--db", db, "--artifacts-dir", artifacts]
        )
    finally:
        os.unlink(db)


class TestCrawlCommand:
    def test_crawl_fixture_end_to_end(self, runner):
        # robots → sitemap index → child → /html; dieksekusi penuh via ACP
        with FixtureServer() as base:
            result = _run_crawl(runner, [base, "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["discovered"] == 1
        assert payload["summary"]["succeeded"] == 1
        first = payload["results"][0]
        assert first["job_status"] == "succeeded"
        assert first["observed_state"] == "access_granted"
        assert first["artifact"]["sha256"]

    def test_crawl_respects_robots(self, runner):
        with FixtureServer() as base:
            result = _run_crawl(runner, [base])
        assert result.exit_code == 0, result.output
        assert "/private" not in result.output
        assert "1 sukses" in result.output

    def test_crawl_with_extract_records_extraction(self, runner):
        with FixtureServer() as base:
            result = _run_crawl(runner, [base, "--json", "--extract"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        kinds = {item["kind"] for item in payload["results"][0]["lineage"]}
        assert "extraction" in kinds

    def test_crawl_empty_discovery_exits_zero(self, runner):
        # origin tanpa sitemap (koneksi ditolak) → 0 URL, exit 0
        result = _run_crawl(runner, ["http://127.0.0.1:9", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["discovered"] == 0
        assert payload["results"] == []


class TestEvidenceInspection:
    """§5.1: evidence trail dapat diperiksa ulang dari terminal (list/show ACP)."""

    def _acquire_fixture(self, runner, db, artifacts):
        with FixtureServer() as base:
            acq = runner.invoke(
                cli,
                [
                    "acquire",
                    base + "/html",
                    "--db",
                    db,
                    "--artifacts-dir",
                    artifacts,
                    "--json",
                ],
            )
        assert acq.exit_code == 0, acq.output
        return json.loads(acq.output)

    def test_list_shows_acp_diagnosis(self, runner):
        db, artifacts = _paths()
        try:
            payload = self._acquire_fixture(runner, db, artifacts)
            result = runner.invoke(cli, ["list", "--db", db, "--json"])
            assert result.exit_code == 0, result.output
            listing = json.loads(result.output)
            assert listing["count"] == 1
            entry = listing["jobs"][0]
            assert entry["job_id"] == payload["job_id"]
            assert entry["job_status"] == "succeeded"
            assert entry["observed_state"] == "access_granted"
            assert entry["observed_reason"] == "ok"
        finally:
            os.unlink(db)

    def test_show_full_evidence(self, runner):
        db, artifacts = _paths()
        try:
            payload = self._acquire_fixture(runner, db, artifacts)
            result = runner.invoke(
                cli,
                [
                    "show",
                    payload["job_id"],
                    "--db",
                    db,
                    "--artifacts-dir",
                    artifacts,
                    "--json",
                ],
            )
            assert result.exit_code == 0, result.output
            evidence = json.loads(result.output)
            assert evidence["job_status"] == "succeeded"
            kinds = {item["kind"] for item in evidence["lineage"]}
            assert "assessment" in kinds
            assert "decision" in kinds
            assert len(evidence["attempts"]) == 1
            assert evidence["artifact"]["sha256"]
        finally:
            os.unlink(db)

    def test_show_missing_job_exits_1(self, runner):
        db, artifacts = _paths()
        try:
            result = runner.invoke(
                cli, ["show", "ghost-1", "--db", db, "--artifacts-dir", artifacts]
            )
            assert result.exit_code == 1
        finally:
            os.unlink(db)

    def test_show_survives_missing_artifact_file(self, runner):
        # artifact dihapus dari disk → show tetap bekerja (degradasi jujur):
        # artifact dilaporkan None, bukti diagnosis di lineage tidak hilang.
        import shutil

        db, artifacts = _paths()
        try:
            payload = self._acquire_fixture(runner, db, artifacts)
            shutil.rmtree(artifacts)
            result = runner.invoke(
                cli,
                [
                    "show",
                    payload["job_id"],
                    "--db",
                    db,
                    "--artifacts-dir",
                    artifacts,
                    "--json",
                ],
            )
            assert result.exit_code == 0, result.output
            evidence = json.loads(result.output)
            assert evidence["artifact"] is None
            assert evidence["job_status"] == "succeeded"
            kinds = {item["kind"] for item in evidence["lineage"]}
            assert "assessment" in kinds
            assert "decision" in kinds
        finally:
            os.unlink(db)


class TestStatsCommand:
    """``uwae stats`` (observability agregat) — satu sumber kebenaran: job_events."""

    def test_stats_empty_db(self, runner):
        # database kosong → nol; hit_rate None (jujur, bukan 0 palsu)
        db = tempfile.mktemp(suffix=".db")
        try:
            result = runner.invoke(cli, ["stats", "--db", db, "--json"])
            assert result.exit_code == 0, result.output
            payload = json.loads(result.output)
            assert payload["total_jobs"] == 0
            assert payload["by_status"] == {}
            assert payload["diagnoses"] == {}
            assert payload["cache"]["fetched_jobs"] == 0
            assert payload["cache"]["hit_rate"] is None
        finally:
            if os.path.exists(db):
                os.unlink(db)

    def test_stats_aggregates_recorded_evidence(self, runner):
        # bukti dibuat langsung via repo — agregasi persis apa yang tercatat
        from universal_web_acquisition.core.job_model import Job
        from universal_web_acquisition.core.job_repository import JobRepository

        db = tempfile.mktemp(suffix=".db")
        try:
            repo = JobRepository(db)
            repo.save_job(Job(job_id="s1", url="http://x/a"))
            repo.save_job(Job(job_id="s2", url="http://x/b"))
            repo.save_job(Job(job_id="s3", url="http://x/c"))
            repo.record_event(
                "s1",
                "assessment",
                json.dumps({"state": "access_granted", "signals": ["http.status=200"]}),
            )
            repo.record_event(
                "s1",
                "identification",
                json.dumps({"format": "html", "mime_conflict": False}),
            )
            repo.record_event("s1", "extraction", json.dumps({"extractor": "x"}))
            repo.record_event(
                "s2",
                "assessment",
                json.dumps(
                    {"state": "content_invalid", "signals": ["http.status=404"]}
                ),
            )
            repo.record_event("s2", "extraction_error", json.dumps({"extractor": "x"}))
            repo.record_event(
                "s3",
                "assessment",
                json.dumps(
                    {
                        "state": "access_granted",
                        "signals": ["http.status=200", "cache.hit=hit"],
                    }
                ),
            )
            repo.record_event(
                "s3",
                "discovered_via",
                json.dumps(
                    {
                        "url": "http://x/d",
                        "parent": "http://x/c",
                        "source": "follow_links",
                    }
                ),
            )
            result = runner.invoke(cli, ["stats", "--db", db, "--json"])
            assert result.exit_code == 0, result.output
            payload = json.loads(result.output)
            assert payload["total_jobs"] == 3
            assert payload["by_status"] == {"queued": 3}
            assert payload["diagnoses"] == {
                "access_granted": 2,
                "content_invalid": 1,
            }
            assert payload["cache"] == {
                "fetched_jobs": 3,
                "cache_hits": 1,
                "hit_rate": 0.333,
            }
            assert payload["identification"]["formats"] == {"html": 1}
            assert payload["identification"]["mime_conflicts"] == 0
            assert payload["extraction"] == {"success": 1, "errors": 1}
            assert payload["discovery"] == {"discovered_via": 1}
        finally:
            if os.path.exists(db):
                os.unlink(db)

    def test_stats_after_acquire_smoke(self, runner):
        db = tempfile.mktemp(suffix=".db")
        artifacts = tempfile.mkdtemp(prefix="uwae-stats-")
        try:
            with FixtureServer() as base:
                acquired = runner.invoke(
                    cli,
                    [
                        "acquire",
                        base + "/html",
                        "--db",
                        db,
                        "--artifacts-dir",
                        artifacts,
                    ],
                )
                assert acquired.exit_code == 0, acquired.output
                result = runner.invoke(cli, ["stats", "--db", db])
            assert result.exit_code == 0, result.output
            assert "Job total     : 1" in result.output
            assert "access_granted" in result.output
            assert "html=1" in result.output
        finally:
            if os.path.exists(db):
                os.unlink(db)
