"""E3 reprocessing tests: proses ulang artifact tersimpan tanpa transfer ulang.

Mandat TEXT.md (E3): ubah plugin ekstraksi lalu proses ulang artifact yang
sudah tersimpan — TANPA transfer ulang. Yang diverifikasi:
- ``uwae reprocess <job_id>`` menjalankan extractor atas artifact lokal dan
  mencatat event audit ``extraction`` dengan integrity konten SUMBER
  (lineage yang sama dengan worker — satu sumber kebenaran);
- job tak dikenal / tanpa artifact → ditolak dengan jujur (exit 1);
- artifact hilang dari disk → degradasi jujur, tidak ada ekstraksi palsu.
"""

import json
import os
import shutil
import sys
import tempfile

import pytest
from click.testing import CliRunner

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from universal_web_acquisition.benchmark.fixture_server import FixtureServer
from universal_web_acquisition.cli.main import cli


def _paths():
    db = tempfile.mktemp(suffix=".db")
    artifacts = tempfile.mkdtemp(prefix="uwae-reproc-")
    return db, artifacts


class TestReprocessCommand:
    @pytest.fixture
    def runner(self):
        return CliRunner()

    def _acquire(self, runner, base, db, artifacts):
        result = runner.invoke(
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
        assert result.exit_code == 0, result.output
        return json.loads(result.output)

    def test_reprocess_records_extraction_event(self, runner):
        db, artifacts = _paths()
        try:
            with FixtureServer() as base:
                payload = self._acquire(runner, base, db, artifacts)
                job_id = payload["job_id"]
                result = runner.invoke(
                    cli,
                    [
                        "reprocess",
                        job_id,
                        "--db",
                        db,
                        "--artifacts-dir",
                        artifacts,
                        "--json",
                    ],
                )
            assert result.exit_code == 0, result.output
            out = json.loads(result.output)
            extractions = [t for t in out["lineage"] if t["kind"] == "extraction"]
            assert extractions, "reprocess harus mencatat event extraction"
            # integrity konten SUMBER wajib — lineage ke artifact terverifikasi
            assert extractions[-1]["source_sha256"] == out["artifact"]["sha256"]
            assert extractions[-1]["extractor"] == "html-text-extractor"
        finally:
            os.unlink(db)

    def test_reprocess_missing_job_exits_1(self, runner):
        db, artifacts = _paths()
        try:
            result = runner.invoke(
                cli, ["reprocess", "no-such-job", "--db", db, "--artifacts-dir", artifacts]
            )
            assert result.exit_code == 1
            assert "tidak ditemukan" in result.output
        finally:
            os.unlink(db)

    def test_reprocess_job_without_artifact_exits_1(self, runner):
        # job gagal (404 → content_invalid) → tidak ada artifact → ditolak jujur
        db, artifacts = _paths()
        try:
            with FixtureServer() as base:
                result = runner.invoke(
                    cli,
                    [
                        "acquire",
                        base + "/missing",
                        "--db",
                        db,
                        "--artifacts-dir",
                        artifacts,
                        "--json",
                    ],
                )
            assert result.exit_code == 1, result.output
            payload = json.loads(result.output)
            job_id = payload["job_id"]
            result = runner.invoke(
                cli, ["reprocess", job_id, "--db", db, "--artifacts-dir", artifacts]
            )
            assert result.exit_code == 1
            assert "tidak punya artifact" in result.output
        finally:
            os.unlink(db)

    def test_reprocess_missing_artifact_file_exits_1(self, runner):
        # artifact dihapus dari disk → degradasi jujur (tidak ada ekstraksi palsu)
        db, artifacts = _paths()
        try:
            with FixtureServer() as base:
                payload = self._acquire(runner, base, db, artifacts)
            job_id = payload["job_id"]
            shutil.rmtree(artifacts)  # artifact hilang dari disk
            result = runner.invoke(
                cli, ["reprocess", job_id, "--db", db, "--artifacts-dir", artifacts]
            )
            assert result.exit_code == 1
            assert "tidak dapat dimuat" in result.output
        finally:
            os.unlink(db)
