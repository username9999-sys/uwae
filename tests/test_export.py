"""Export adapters tests (lapisan Knowledge — hasil ekstraksi → file).

Yang diverifikasi:
- ``rows_from_events`` memetakan event ``extraction`` → baris export
  (extractor/format/fields/source_sha256/recorded_at) persis apa tercatat;
- ``JsonExporter`` lossless (fields tetap bersarang, round-trip);
- ``CsvExporter``: header kolom tetap + ``fields_json`` ter-parse balik;
- ``get_exporter`` menolak format tak dikenal (ValueError jujur);
- CLI ``uwae export``: JSON/CSV dari job ber-extraction; tanpa event
  ekstraksi / job tak dikenal → ditolak jujur (exit 1, tanpa file palsu).
"""

import csv
import json
import os
import sys
import tempfile

import pytest
from click.testing import CliRunner

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from universal_web_acquisition.benchmark.fixture_server import FixtureServer
from universal_web_acquisition.cli.main import cli
from universal_web_acquisition.export.adapters import (
    CsvExporter,
    JsonExporter,
    get_exporter,
    rows_from_events,
)


def _event(extractor="html-text-extractor", at="2026-10-25T10:00:00"):
    return {
        "event": "extraction",
        "detail": json.dumps(
            {
                "extractor": extractor,
                "format": "html_text",
                "fields": {"title": "Halaman", "text": "isi"},
                "source_sha256": "a" * 64,
                "source_size_bytes": 123,
            },
            ensure_ascii=False,
        ),
        "at": at,
    }


class TestRowsFromEvents:
    def test_maps_detail_and_carries_at(self):
        rows = rows_from_events([_event()])
        assert rows == [
            {
                "extractor": "html-text-extractor",
                "format": "html_text",
                "fields": {"title": "Halaman", "text": "isi"},
                "source_sha256": "a" * 64,
                "source_size_bytes": 123,
                "recorded_at": "2026-10-25T10:00:00",
            }
        ]


class TestJsonExporter:
    def test_round_trip_lossless(self, tmp_path):
        rows = rows_from_events([_event(), _event(extractor="marker")])
        out = tmp_path / "out.json"
        count = JsonExporter().export(rows, str(out))
        assert count == 2
        assert json.loads(out.read_text(encoding="utf-8")) == rows


class TestCsvExporter:
    def test_header_and_fields_json_round_trip(self, tmp_path):
        rows = rows_from_events([_event()])
        out = tmp_path / "out.csv"
        count = CsvExporter().export(rows, str(out))
        assert count == 1
        with out.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            assert tuple(reader.fieldnames) == CsvExporter.COLUMNS
            parsed = list(reader)
        assert parsed[0]["extractor"] == "html-text-extractor"
        assert json.loads(parsed[0]["fields_json"]) == {
            "title": "Halaman",
            "text": "isi",
        }


class TestGetExporter:
    def test_unknown_format_raises(self):
        with pytest.raises(ValueError, match="tidak dikenal"):
            get_exporter("xml")


def _paths():
    db = tempfile.mktemp(suffix=".db")
    artifacts = tempfile.mkdtemp(prefix="uwae-export-")
    return db, artifacts


class TestExportCommand:
    @pytest.fixture
    def runner(self):
        return CliRunner()

    def _acquire_with_extract(self, runner, base, db, artifacts):
        result = runner.invoke(
            cli,
            [
                "acquire",
                base + "/html",
                "--extract",
                "--db",
                db,
                "--artifacts-dir",
                artifacts,
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        return json.loads(result.output)

    def test_export_json_from_extracted_job(self, runner):
        db, artifacts = _paths()
        out = os.path.join(tempfile.mkdtemp(prefix="uwae-expout-"), "rows.json")
        try:
            with FixtureServer() as base:
                payload = self._acquire_with_extract(runner, base, db, artifacts)
                job_id = payload["job_id"]
                result = runner.invoke(
                    cli,
                    ["export", job_id, "--db", db, "--format", "json", "--output", out],
                )
            assert result.exit_code == 0, result.output
            rows = json.loads(open(out, encoding="utf-8").read())
            assert rows, "export harus memuat hasil ekstraksi"
            assert rows[0]["extractor"] == "html-text-extractor"
            # lineage integritas: sha256 sumber == artifact yang diakuisisi
            assert rows[0]["source_sha256"] == payload["artifact"]["sha256"]
        finally:
            os.unlink(db)

    def test_export_csv_round_trip(self, runner):
        db, artifacts = _paths()
        out = os.path.join(tempfile.mkdtemp(prefix="uwae-expout-"), "rows.csv")
        try:
            with FixtureServer() as base:
                payload = self._acquire_with_extract(runner, base, db, artifacts)
                job_id = payload["job_id"]
                result = runner.invoke(
                    cli,
                    ["export", job_id, "--db", db, "--format", "csv", "--output", out],
                )
            assert result.exit_code == 0, result.output
            with open(out, newline="", encoding="utf-8") as handle:
                parsed = list(csv.DictReader(handle))
            assert parsed[0]["extractor"] == "html-text-extractor"
            assert json.loads(parsed[0]["fields_json"])  # fields lossless
        finally:
            os.unlink(db)

    def test_export_without_extraction_rejected(self, runner):
        db, artifacts = _paths()
        out = os.path.join(tempfile.mkdtemp(prefix="uwae-expout-"), "rows.json")
        try:
            with FixtureServer() as base:
                result = runner.invoke(
                    cli,
                    ["acquire", base + "/html", "--db", db, "--artifacts-dir", artifacts, "--json"],
                )
                assert result.exit_code == 0, result.output
                job_id = json.loads(result.output)["job_id"]
                result = runner.invoke(
                    cli, ["export", job_id, "--db", db, "--output", out]
                )
            assert result.exit_code == 1
            assert "tidak punya hasil ekstraksi" in result.output
            assert not os.path.exists(out)  # tanpa file kosong palsu
        finally:
            os.unlink(db)

    def test_export_missing_job_rejected(self, runner):
        db, artifacts = _paths()
        out = os.path.join(tempfile.mkdtemp(prefix="uwae-expout-"), "rows.json")
        try:
            result = runner.invoke(
                cli, ["export", "no-such-job", "--db", db, "--output", out]
            )
            assert result.exit_code == 1
            assert "tidak ditemukan" in result.output
        finally:
            os.unlink(db)
