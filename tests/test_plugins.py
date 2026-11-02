"""Plugin system tests (ADR-006, Mandatory Phase 2 — INSTRUCTION.md).

Yang diverifikasi:
- kompatibilitas versi: plugin di luar rentang versi engine DITOLAK (bukan
  menebak-nebak kompatibilitas);
- registry: duplikat nama ditolak, lazy initialize SEKALI (idempoten),
  unregister memanggil shutdown, health_check_all tahan kegagalan satu
  plugin;
- extractor bawaan: HTML → {title, text}, hasil selalu membawa integrity
  sha256 konten SUMBER, content_type non-HTML ditolak dengan jelas;
- ExtractorInterface terpenuhi oleh extractor bawaan (runtime_checkable).
"""

import hashlib
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from universal_web_acquisition.artifact.model import Artifact
from universal_web_acquisition.extract.base import ExtractionResult
from universal_web_acquisition.extract.html_text import HTMLTextExtractor
from universal_web_acquisition.plugins.base import (
    ENGINE_VERSION,
    PluginError,
    PluginMetadata,
    is_compatible,
    parse_version,
)
from universal_web_acquisition.plugins.registry import PluginRegistry

HTML_BODY = (
    b"<html><head><title>Judul Halaman</title></head>"
    b"<body><h1>Heading</h1><p>Paragraf satu.</p><p>Paragraf dua.</p></body></html>"
)


def _html_artifact(content=HTML_BODY, content_type="text/html; charset=utf-8"):
    return Artifact(job_id="j1", url="http://fixture.test/x", content=content, content_type=content_type)


class _StubPlugin:
    """Plugin uji dengan perilaku yang dapat dikonfigurasi."""

    def __init__(self, name="stub", version="1.0.0", min_version="0.1.0", max_version=None, healthy=True):
        self._metadata = PluginMetadata(
            name=name,
            version=version,
            description="plugin uji",
            author="test",
            min_engine_version=min_version,
            max_engine_version=max_version,
        )
        self.healthy = healthy
        self.initialize_calls = 0
        self.shutdown_calls = 0
        self.last_config = None

    def get_metadata(self):
        return self._metadata

    def initialize(self, config):
        self.initialize_calls += 1
        self.last_config = config

    def shutdown(self):
        self.shutdown_calls += 1

    def health_check(self):
        if not self.healthy:
            raise RuntimeError("boom")
        return {"healthy": True}


class TestPluginMetadata:
    def test_frozen(self):
        metadata = PluginMetadata(name="x", version="1.0.0", description="d", author="a")
        with pytest.raises(Exception):
            metadata.name = "y"


class TestVersionCompatibility:
    def test_within_range_is_compatible(self):
        metadata = PluginMetadata(
            name="x", version="1.0.0", description="d", author="a",
            min_engine_version="0.2.0", max_engine_version="0.4.0",
        )
        assert is_compatible(metadata, "0.3.0") is True

    def test_engine_below_minimum_rejected(self):
        metadata = PluginMetadata(
            name="x", version="1.0.0", description="d", author="a",
            min_engine_version="0.4.0",
        )
        assert is_compatible(metadata, ENGINE_VERSION) is False

    def test_engine_above_maximum_rejected(self):
        metadata = PluginMetadata(
            name="x", version="1.0.0", description="d", author="a",
            min_engine_version="0.1.0", max_engine_version="0.2.0",
        )
        assert is_compatible(metadata, ENGINE_VERSION) is False

    def test_no_upper_bound_is_open(self):
        metadata = PluginMetadata(
            name="x", version="1.0.0", description="d", author="a",
            min_engine_version="0.1.0", max_engine_version=None,
        )
        assert is_compatible(metadata, "99.0.0") is True

    def test_unparseable_version_raises(self):
        with pytest.raises(PluginError):
            parse_version("not-a-version")


class TestRegistry:
    def test_register_and_list(self):
        registry = PluginRegistry()
        registry.register(_StubPlugin(name="alpha"))
        registry.register(_StubPlugin(name="beta"))
        names = [m.name for m in registry.list()]
        assert names == ["alpha", "beta"]

    def test_duplicate_name_rejected(self):
        registry = PluginRegistry()
        registry.register(_StubPlugin(name="dup"))
        with pytest.raises(PluginError):
            registry.register(_StubPlugin(name="dup"))

    def test_incompatible_plugin_rejected(self):
        registry = PluginRegistry(engine_version="0.3.0")
        with pytest.raises(PluginError):
            registry.register(_StubPlugin(name="future", min_version="0.4.0"))

    def test_get_initializes_once(self):
        # lazy + idempoten: dua get → satu initialize
        registry = PluginRegistry()
        stub = _StubPlugin(name="lazy")
        registry.register(stub)
        assert stub.initialize_calls == 0  # register TIDAK meng-initialize

        first = registry.get("lazy", config={"key": "value"})
        second = registry.get("lazy")
        assert first is second
        assert stub.initialize_calls == 1
        assert stub.last_config == {"key": "value"}

    def test_get_unknown_raises(self):
        registry = PluginRegistry()
        with pytest.raises(PluginError):
            registry.get("ghost")

    def test_unregister_shuts_down_initialized_plugin(self):
        registry = PluginRegistry()
        stub = _StubPlugin(name="lifecycle")
        registry.register(stub)
        registry.get("lifecycle")
        registry.unregister("lifecycle")
        assert stub.shutdown_calls == 1
        with pytest.raises(PluginError):
            registry.get("lifecycle")

    def test_health_check_all_tolerates_failure(self):
        # kegagalan satu plugin tidak menghentikan pemeriksaan lainnya
        registry = PluginRegistry()
        registry.register(_StubPlugin(name="ok"))
        registry.register(_StubPlugin(name="broken", healthy=False))
        report = registry.health_check_all()
        assert report["ok"] == {"healthy": True}
        assert report["broken"]["healthy"] is False
        assert "RuntimeError" in report["broken"]["error"]


class TestHTMLTextExtractor:
    def test_metadata_is_compatible(self):
        extractor = HTMLTextExtractor()
        assert is_compatible(extractor.get_metadata(), ENGINE_VERSION) is True

    def test_extract_title_and_text(self):
        extractor = HTMLTextExtractor()
        result = extractor.extract(_html_artifact())
        assert isinstance(result, ExtractionResult)
        assert result.format == "html_text"
        assert result.fields["title"] == "Judul Halaman"
        assert "Heading" in result.fields["text"]
        assert "Paragraf satu." in result.fields["text"]
        assert "Paragraf dua." in result.fields["text"]

    def test_result_integrity_matches_source(self):
        # hasil ekstraksi selalu tertelusur ke konten SUMBER (sha256)
        artifact = _html_artifact()
        result = HTMLTextExtractor().extract(artifact)
        assert result.integrity.sha256 == hashlib.sha256(HTML_BODY).hexdigest()
        assert result.integrity.verify(HTML_BODY) is True

    def test_non_html_rejected_with_clear_error(self):
        with pytest.raises(PluginError):
            HTMLTextExtractor().extract(
                _html_artifact(content=b"plain", content_type="text/plain")
            )

    def test_initialize_config_respected(self):
        extractor = HTMLTextExtractor()
        extractor.initialize({"max_text_chars": "5"})
        result = extractor.extract(_html_artifact())
        assert len(result.fields["text"]) <= 5

    def test_satisfies_extractor_protocol(self):
        from universal_web_acquisition.extract.base import ExtractorInterface

        assert isinstance(HTMLTextExtractor(), ExtractorInterface)


class TestRegistryWithExtractor:
    def test_extractor_via_registry_end_to_end(self):
        registry = PluginRegistry()
        registry.register(HTMLTextExtractor())
        extractor = registry.get("html-text-extractor")
        result = extractor.extract(_html_artifact())
        assert result.fields["title"] == "Judul Halaman"
        assert registry.health_check_all()["html-text-extractor"] == {
            "healthy": True,
            "extractor": "html-text-extractor",
        }
