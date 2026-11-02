"""Base plugin contracts (ADR-006, Mandatory Phase 2 — INSTRUCTION.md).

Implementasi inti dari keputusan ADR-006 (*Proposed* → inti terimplementasi):
``PluginMetadata`` + ``PluginInterface`` (get_metadata/initialize/shutdown/
health_check) dan kompatibilitas versi engine.

Aturan mandat terkait: kemampuan tidak diklaim tanpa bukti — plugin
menyatakan rentang versi engine yang didukung; registry menolak plugin di
luar rentang itu (bukan menebak-nebak kompatibilitas).
"""

from dataclasses import dataclass
from typing import Dict, Optional, Protocol, runtime_checkable

# Sinkron manual dengan ENGINE_VERSION di benchmark/engine_bench.py ("uwae-0.3.0").
ENGINE_VERSION = "0.3.0"


@dataclass(frozen=True)
class PluginMetadata:
    """Identitas + kompatibilitas versi satu plugin (ADR-006)."""

    name: str
    version: str
    description: str
    author: str
    homepage: Optional[str] = None
    min_engine_version: str = "0.1.0"
    max_engine_version: Optional[str] = None  # None = tanpa batas atas


class PluginError(Exception):
    """Kegagalan plugin dengan penyebab yang jelas — bukan exception generik."""


def parse_version(version: str) -> tuple:
    """``"1.2.3"`` → ``(1, 2, 3)`` — perbandingan semver sederhana."""
    try:
        return tuple(int(part) for part in version.strip().split("."))
    except ValueError as exc:
        raise PluginError(f"versi tidak terurai: {version!r}") from exc


def is_compatible(metadata: PluginMetadata, engine_version: str = ENGINE_VERSION) -> bool:
    """Plugin kompatibel bila versi engine dalam rentang yang dinyatakan."""
    engine = parse_version(engine_version)
    minimum = parse_version(metadata.min_engine_version)
    if engine < minimum:
        return False
    if metadata.max_engine_version is not None:
        maximum = parse_version(metadata.max_engine_version)
        if engine > maximum:
            return False
    return True


@runtime_checkable
class PluginInterface(Protocol):
    """Kontrak dasar seluruh tipe plugin (ADR-006)."""

    def get_metadata(self) -> PluginMetadata: ...

    def initialize(self, config: Dict[str, str]) -> None: ...

    def shutdown(self) -> None: ...

    def health_check(self) -> Dict[str, object]: ...
