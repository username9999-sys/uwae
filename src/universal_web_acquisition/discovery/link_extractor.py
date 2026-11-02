"""HTML link extractor (discovery graph — TEXT.md gap: link extraction,
deduplikasi, batas origin).

Mandat TEXT.md: discovery menghasilkan kandidat URL dan hubungan dengan
halaman induknya. Modul ini menyediakan lapisan ekstraksi tautannya:

- hanya ``<a href>`` (stdlib ``html.parser`` — tanpa dependensi baru);
- URL relatif di-resolve terhadap URL FINAL artifact (redirect mengubah base);
- fragmen (#...) dibuang; tautan ke halaman itu sendiri dilewati — tidak ada
  nilai discovery baru;
- skema non-HTTP(S) (mailto:, javascript:, tel:, data:) bukan kandidat
  akuisisi;
- ``same_origin_only=True`` (default) mengikat discovery pada origin sumber
  (batas domain — scope dan volume tetap terkendali).

Catatan batas: edge induk→anak (parent URL) belum direkam di job model —
tindak lanjut, bukan bagian milestone ini.
"""

from html.parser import HTMLParser
from typing import List
from urllib.parse import urljoin, urlsplit


class _LinkCollector(HTMLParser):
    """Kumpulkan nilai href dari semua <a> — toleran HTML rusak."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hrefs: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        for name, value in attrs:
            if name == "href" and value:
                self.hrefs.append(value)


def _origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def extract_links(
    html: bytes, base_url: str, same_origin_only: bool = True
) -> List[str]:
    """Ekstrak URL kandidat dari artifact HTML — absolut, dedup, terikat origin.

    Urutan hasil = urutan kemunculan pertama (dedup menjaga determinisme).
    Tautan yang setelah fragment-stripping sama dengan ``base_url`` (halaman
    itu sendiri) dilewati.
    """
    collector = _LinkCollector()
    collector.feed(html.decode("utf-8", errors="replace"))

    base_origin = _origin_of(base_url)
    seen = set()
    result: List[str] = []
    for href in collector.hrefs:
        absolute = urljoin(base_url, href.split("#", 1)[0])
        if not absolute or absolute == base_url:
            continue
        if urlsplit(absolute).scheme not in ("http", "https"):
            continue
        if same_origin_only and _origin_of(absolute) != base_origin:
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        result.append(absolute)
    return result
