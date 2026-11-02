"""Pemuatan plugin eksternal dari path (E3 tindak lanjut — ADR-006).

Konvensi modul plugin eksternal: variabel ``PLUGIN`` (satu instance) atau
``PLUGINS`` (list instance); bila tidak ada, kandidat = kelas yang
memenuhi kontrak (``get_metadata`` + ``extract``) dan bisa di-instansiasi
tanpa argumen.

Pemuatan kode dari path MENJALANKAN kode itu — keputusan operator yang
eksplisit (setara menjalankan skrip sendiri). Loader hanya mengimpor modul
dan mengumpulkan kandidat; VALIDASI (metadata + kompatibilitas versi)
tetap tugas ``PluginRegistry.register`` — plugin di luar rentang DITOLAK
di sana dengan pesan yang jelas (ADR-006), bukan di sini.
"""

import importlib.util
from pathlib import Path
from typing import List

from universal_web_acquisition.plugins.base import PluginError


def _is_plugin_like(obj) -> bool:
    """Kandidat plugin: get_metadata() + extract() — kontrak Extractor."""
    return callable(getattr(obj, "get_metadata", None)) and callable(
        getattr(obj, "extract", None)
    )


def load_plugins_from_path(path: str) -> List:
    """Muat plugin dari file ``.py`` — kembalikan instance yang sah.

    ``PluginError`` bila file tidak ada, tidak dapat diimpor, atau tidak
    memuat satu pun kandidat yang sah.
    """
    file = Path(path)
    if not file.is_file():
        raise PluginError(f"file plugin tidak ditemukan: {path}")

    spec = importlib.util.spec_from_file_location(
        f"uwae_ext_plugin_{file.stem}", file
    )
    if spec is None or spec.loader is None:
        raise PluginError(f"file plugin tidak dapat diimpor: {path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise PluginError(
            f"eksekusi modul plugin gagal: {type(exc).__name__}: {exc}"
        ) from exc

    declared = getattr(module, "PLUGINS", None)
    if declared is not None:
        candidates = list(declared)
    elif getattr(module, "PLUGIN", None) is not None:
        candidates = [module.PLUGIN]
    else:
        # fallback: kelas plugin-like → instansiasi tanpa argumen
        candidates = []
        for name in dir(module):
            obj = getattr(module, name)
            if isinstance(obj, type) and _is_plugin_like(obj):
                try:
                    candidates.append(obj())
                except TypeError:
                    continue

    valid = [c for c in candidates if _is_plugin_like(c)]
    if not valid:
        raise PluginError(
            f"tidak ada plugin sah di {path} — butuh variabel PLUGIN/PLUGINS "
            "atau kelas dengan get_metadata() + extract()"
        )
    return valid
