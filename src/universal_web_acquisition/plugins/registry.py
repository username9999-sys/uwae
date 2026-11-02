"""Plugin registry (ADR-006, Mandatory Phase 2 — INSTRUCTION.md).

Registrasi eksplisit + lazy initialization + lifecycle:

- ``register``  : validasi metadata + kompatibilitas versi; duplikat nama
  ditolak; TIDAK meng-initialize (lazy — plugin dimuat saat dibutuhkan);
- ``get``       : mengambil plugin, meng-initialize SEKALI dengan config
  (idempoten — initialize ulang tidak terjadi);
- ``unregister``: memanggil ``shutdown`` bila plugin ter-inisialisasi;
- ``health_check_all``: kesehatan seluruh plugin terdaftar (diagnostik).

Entry-point discovery (setuptools) ditunda sampai ada plugin eksternal
nyata — registrasi eksplisit sudah memenuhi kontrak ADR-006 dan menghindari
mekanisme tanpa pengguna.
"""

from typing import Dict, List, Optional

from universal_web_acquisition.plugins.base import (
    ENGINE_VERSION,
    PluginError,
    PluginInterface,
    PluginMetadata,
    is_compatible,
)


class PluginRegistry:
    """Registry plugin dengan lazy lifecycle (ADR-006)."""

    def __init__(self, engine_version: str = ENGINE_VERSION):
        self.engine_version = engine_version
        self._plugins: Dict[str, PluginInterface] = {}
        self._initialized: set = set()

    def register(self, plugin: PluginInterface) -> PluginMetadata:
        """Daftarkan plugin — validasi metadata + kompatibilitas versi."""
        metadata = plugin.get_metadata()
        if not metadata.name:
            raise PluginError("metadata plugin tanpa nama tidak sah")
        if metadata.name in self._plugins:
            raise PluginError(f"plugin {metadata.name!r} sudah terdaftar")
        if not is_compatible(metadata, self.engine_version):
            raise PluginError(
                f"plugin {metadata.name!r} {metadata.version} tidak kompatibel "
                f"dengan engine {self.engine_version} "
                f"(mendukung {metadata.min_engine_version}..{metadata.max_engine_version or '∞'})"
            )
        self._plugins[metadata.name] = plugin
        return metadata

    def unregister(self, name: str) -> None:
        """Lepaskan plugin — shutdown bila ter-inisialisasi (lifecycle ADR-006)."""
        plugin = self._plugins.pop(name, None)
        if plugin is None:
            raise PluginError(f"plugin {name!r} tidak terdaftar")
        if name in self._initialized:
            plugin.shutdown()
            self._initialized.discard(name)

    def get(self, name: str, config: Optional[Dict[str, str]] = None) -> PluginInterface:
        """Ambil plugin; initialize SEKALI (lazy, idempoten)."""
        plugin = self._plugins.get(name)
        if plugin is None:
            raise PluginError(f"plugin {name!r} tidak terdaftar")
        if name not in self._initialized:
            plugin.initialize(config or {})
            self._initialized.add(name)
        return plugin

    def list(self) -> List[PluginMetadata]:
        """Metadata seluruh plugin terdaftar, urut nama."""
        return [p.get_metadata() for p in self._plugins.values()]

    def health_check_all(self) -> Dict[str, Dict[str, object]]:
        """Kesehatan seluruh plugin — kegagalan satu plugin tidak menghentikan lainnya."""
        report: Dict[str, Dict[str, object]] = {}
        for name, plugin in self._plugins.items():
            try:
                report[name] = plugin.health_check()
            except Exception as exc:
                report[name] = {"healthy": False, "error": f"{type(exc).__name__}: {exc}"}
        return report
