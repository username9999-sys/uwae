"""Per-origin target rules (aturan target per-situs, Spec v2 §3.1).

Lapisan konfigurasi yang MENYEMPURNAKAN diagnosis bila bukti lintas-path
tersedia — tanpa aturan universal:

- ``soft404_as_invalid(origin)``: bila operator menyatakan bahwa untuk origin
  ini konten identik lintas path (soft-404, bukti event
  ``soft404_suspected``) BUKAN konten target, worker mengubah keputusan
  ACCEPT menjadi FAILED ``content_invalid`` — bukti tetap tercatat penuh.

Tanpa aturan terdaftar, perilaku tetap jujur secara teknis (konten valid =
ACCESS_GRANTED) — sesuai §3.1: jangan membuat aturan universal; keputusan
berubah hanya atas konfigurasi eksplisit per-situs.
"""

from typing import Dict, Set


class TargetRules:
    """Aturan target per-origin (v1: satu aturan — soft-404 = bukan target)."""

    def __init__(self):
        self._soft404_invalid: Set[str] = set()

    def register_soft404_invalid(self, origin: str) -> None:
        """Nyatakan bahwa untuk ``origin``, konten soft-404 bukan konten target."""
        self._soft404_invalid.add(origin)

    def soft404_as_invalid(self, origin: str) -> bool:
        return origin in self._soft404_invalid
