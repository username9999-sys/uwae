"""Extractor plugin contracts (ADR-006 plugin type 3, Mandatory Phase 2).

``ExtractorInterface`` memperluas kontrak dasar plugin dengan ``extract``;
``ExtractionResult`` membawa bukti integritas terhadap konten SUMBER
(sha256) sehingga hasil ekstraksi selalu tertelusur ke artifact yang
terverifikasi — bukan sekadar dict tanpa lineage.
"""

from dataclasses import dataclass, field
from typing import Dict, Protocol, runtime_checkable

from universal_web_acquisition.artifact.model import Artifact, ArtifactIntegrity
from universal_web_acquisition.plugins.base import PluginInterface


@dataclass(frozen=True)
class ExtractionResult:
    """Hasil ekstraksi satu artifact — dengan lineage integritas sumber."""

    extractor: str
    format: str  # kosakata berbatas: "html_text", dst.
    fields: Dict[str, str] = field(default_factory=dict)
    integrity: ArtifactIntegrity = None  # integritas konten SUMBER

    def __post_init__(self):
        if self.integrity is None:
            raise ValueError("ExtractionResult tanpa integrity tidak sah (bukti wajib)")


@runtime_checkable
class ExtractorInterface(PluginInterface, Protocol):
    """Kontrak plugin Extractor (ADR-006): extract(artifact) -> result."""

    def extract(self, artifact: Artifact) -> ExtractionResult: ...
