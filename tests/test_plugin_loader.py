"""Plugin loader tests (E3 tindak lanjut — pemuatan plugin eksternal dari path).

Yang diverifikasi:
- konvensi modul: variabel ``PLUGIN`` / ``PLUGINS`` / fallback kelas
  plugin-like (get_metadata + extract) tanpa argumen;
- file hilang / tanpa plugin sah → PluginError dengan pesan jelas;
- VALIDASI versi tetap tugas registry (ADR-006): plugin di luar rentang
  engine DITOLAK di register, bukan di loader;
- ``uwae reprocess --plugin <path>``: extractor eksternal berjalan di samping
  bawaan, event extraction membawa integrity konten SUMBER;
- plugin tidak kompatibel → reprocess menolak dengan jujur (exit 1).
"""

import json
import os
import sys
import tempfile

import pytest
from click.testing import CliRunner

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from universal_web_acquisition.benchmark.fixture_server import FixtureServer
from universal_web_acquisition.cli.main import cli
from universal_web_acquisition.plugins.base import PluginError
from universal_web_acquisition.plugins.registry import PluginRegistry
from universal_web_acquisition.plugins.loader import load_plugins_from_path

PLUGIN_TEMPLATE = '''
from universal_web_acquisition.artifact.model import ArtifactIntegrity
from universal_web_acquisition.extract.base import ExtractionResult
from universal_web_acquisition.plugins.base import PluginMetadata


class MarkerExtractor:
    def __init__(self, name="marker-extractor"):
        self._meta = PluginMetadata(
            name=name,
            version="1.0.0",
            description="plugin uji pemuatan eksternal",
            author="test",
        )

    def get_metadata(self):
        return self._meta

    def initialize(self, config):
        pass

    def shutdown(self):
        pass

    def health_check(self):
        return {"healthy": True}

    def extract(self, artifact):
        return ExtractionResult(
            extractor=self._meta.name,
            format="marker",
            fields={"custom": "yes"},
            integrity=ArtifactIntegrity.from_content(artifact.content),
        )


PLUGIN = MarkerExtractor()
'''


def _write_plugin(tmpdir, body, filename="ext_plugin.py"):
    path = os.path.join(tmpdir, filename)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)
    return path


class TestLoadPluginsFromPath:
    def test_plugin_variable(self, tmp_path):
        path = _write_plugin(str(tmp_path), PLUGIN_TEMPLATE)
        plugins = load_plugins_from_path(path)
        assert len(plugins) == 1
        assert plugins[0].get_metadata().name == "marker-extractor"

    def test_plugins_list(self, tmp_path):
        body = PLUGIN_TEMPLATE.replace(
            "PLUGIN = MarkerExtractor()",
            "PLUGINS = [MarkerExtractor(name='a'), MarkerExtractor(name='b')]",
        )
        path = _write_plugin(str(tmp_path), body)
        plugins = load_plugins_from_path(path)
        assert [p.get_metadata().name for p in plugins] == ["a", "b"]

    def test_class_discovery_fallback(self, tmp_path):
        # tanpa variabel PLUGIN/PLUGINS → kelas plugin-like di-instansiasi
        body = PLUGIN_TEMPLATE.replace("PLUGIN = MarkerExtractor()\n", "")
        path = _write_plugin(str(tmp_path), body)
        plugins = load_plugins_from_path(path)
        assert len(plugins) == 1
        assert plugins[0].get_metadata().name == "marker-extractor"

    def test_missing_file_raises(self):
        with pytest.raises(PluginError, match="tidak ditemukan"):
            load_plugins_from_path("/nonexistent/plugin.py")

    def test_no_valid_plugin_raises(self, tmp_path):
        path = _write_plugin(str(tmp_path), "X = 1\n")
        with pytest.raises(PluginError, match="tidak ada plugin sah"):
            load_plugins_from_path(path)

    def test_incompatible_version_rejected_by_registry(self, tmp_path):
        # loader hanya mengumpulkan kandidat; VALIDASI versi = tugas registry
        body = PLUGIN_TEMPLATE.replace(
            'author="test",',
            'author="test",\n            min_engine_version="99.0.0",',
        )
        path = _write_plugin(str(tmp_path), body)
        plugins = load_plugins_from_path(path)
        registry = PluginRegistry()
        with pytest.raises(PluginError, match="tidak kompatibel"):
            registry.register(plugins[0])


def _paths():
    db = tempfile.mktemp(suffix=".db")
    artifacts = tempfile.mkdtemp(prefix="uwae-plug-")
    return db, artifacts


class TestReprocessWithExternalPlugin:
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

    def test_reprocess_records_custom_extractor_event(self, runner):
        db, artifacts = _paths()
        try:
            with FixtureServer() as base:
                payload = self._acquire(runner, base, db, artifacts)
                job_id = payload["job_id"]
                plugin_path = _write_plugin(
                    tempfile.mkdtemp(prefix="uwae-plugdef-"), PLUGIN_TEMPLATE
                )
                result = runner.invoke(
                    cli,
                    [
                        "reprocess",
                        job_id,
                        "--db",
                        db,
                        "--artifacts-dir",
                        artifacts,
                        "--plugin",
                        plugin_path,
                        "--json",
                    ],
                )
            assert result.exit_code == 0, result.output
            out = json.loads(result.output)
            extractions = [t for t in out["lineage"] if t["kind"] == "extraction"]
            names = {t["extractor"] for t in extractions}
            # bawaan + eksternal keduanya berjalan
            assert "html-text-extractor" in names
            assert "marker-extractor" in names
            marker = next(
                t for t in extractions if t["extractor"] == "marker-extractor"
            )
            assert marker["fields"] == {"custom": "yes"}
            # integrity sumber wajib — lineage ke artifact terverifikasi
            assert marker["source_sha256"] == out["artifact"]["sha256"]
        finally:
            os.unlink(db)

    def test_reprocess_rejects_incompatible_plugin(self, runner):
        db, artifacts = _paths()
        try:
            with FixtureServer() as base:
                payload = self._acquire(runner, base, db, artifacts)
                job_id = payload["job_id"]
                body = PLUGIN_TEMPLATE.replace(
                    'author="test",',
                    'author="test",\n            min_engine_version="99.0.0",',
                )
                plugin_path = _write_plugin(
                    tempfile.mkdtemp(prefix="uwae-plugdef-"), body
                )
                result = runner.invoke(
                    cli,
                    [
                        "reprocess",
                        job_id,
                        "--db",
                        db,
                        "--artifacts-dir",
                        artifacts,
                        "--plugin",
                        plugin_path,
                    ],
                )
            assert result.exit_code == 1
            assert "tidak kompatibel" in result.output
        finally:
            os.unlink(db)
