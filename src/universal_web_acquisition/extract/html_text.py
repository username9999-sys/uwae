"""Built-in HTML text extractor (ADR-006 plugin type 3 — bukti kontrak).

Extractor pertama yang membuktikan kontrak ExtractorInterface end-to-end:
judul + teks dari HTML via ``html.parser`` (stdlib — tanpa dependensi
baru). Hasil selalu membawa ``integrity`` terhadap konten SUMBER sehingga
tertelusur ke artifact terverifikasi.
"""

from html.parser import HTMLParser
from typing import Dict

from universal_web_acquisition.artifact.model import Artifact, ArtifactIntegrity
from universal_web_acquisition.extract.base import ExtractionResult
from universal_web_acquisition.plugins.base import PluginError, PluginMetadata

# Tag yang teksnya dianggap konten (kosakata berbatas v1).
_CONTENT_TAGS = frozenset({"p", "h1", "h2", "h3", "h4", "h5", "h6", "li"})

DEFAULT_MAX_TEXT_CHARS = 100_000


class _HTMLTextParser(HTMLParser):
    """Kumpulkan <title> + teks tag konten (p/h1-h6/li) — stdlib saja."""

    def __init__(self):
        super().__init__()
        self.title_parts = []
        self.text_parts = []
        self._in_title = False
        self._content_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        elif tag in _CONTENT_TAGS:
            self._content_depth += 1

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag in _CONTENT_TAGS and self._content_depth:
            self._content_depth -= 1

    def handle_data(self, data):
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
        elif self._content_depth:
            self.text_parts.append(text)


class HTMLTextExtractor:
    """Plugin Extractor bawaan: HTML → {title, text}."""

    def __init__(self, max_text_chars: int = DEFAULT_MAX_TEXT_CHARS):
        self._max_text_chars = max_text_chars
        self._metadata = PluginMetadata(
            name="html-text-extractor",
            version="1.0.0",
            description="Ekstrak judul dan teks dari artifact HTML (stdlib parser)",
            author="UWAE",
            min_engine_version="0.3.0",
        )

    def get_metadata(self) -> PluginMetadata:
        return self._metadata

    def initialize(self, config: Dict[str, str]) -> None:
        raw = config.get("max_text_chars")
        if raw is not None:
            self._max_text_chars = int(raw)

    def shutdown(self) -> None:
        return None

    def health_check(self) -> Dict[str, object]:
        return {"healthy": True, "extractor": self._metadata.name}

    def extract(self, artifact: Artifact) -> ExtractionResult:
        content_type = (artifact.content_type or "").lower()
        if "text/html" not in content_type:
            raise PluginError(
                f"html-text-extractor: content_type {artifact.content_type!r} "
                "bukan text/html"
            )
        parser = _HTMLTextParser()
        parser.feed(artifact.content.decode("utf-8", errors="replace"))
        parser.close()
        title = " ".join(parser.title_parts)
        text = "\n".join(parser.text_parts)[: self._max_text_chars]
        return ExtractionResult(
            extractor=self._metadata.name,
            format="html_text",
            fields={"title": title, "text": text},
            integrity=ArtifactIntegrity.from_content(
                artifact.content, artifact.content_type
            ),
        )
