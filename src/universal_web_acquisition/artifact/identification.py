"""File Identification Registry (E2 — file-first, bukan extension-first).

Mandat TEXT.md/INSTRUCTION.md: penentuan format memakai gabungan signature,
MIME, metadata, dan struktur konten — nama file dan ekstensi HANYA petunjuk.
Registry ini extensible: detector baru terdaftar tanpa mengubah core, dan
daftar format bawaan BUKAN batas permanen (arsitektur #8).

Prinsip kejujuran (sejalan §3.2):
- ``format_id`` HANYA berasal dari detector berbasis konten (signature/
  parse); MIME dan ekstensi direkam sebagai bukti/petunjuk — tidak pernah
  menjadi dasar klaim format sendirian;
- ketidakcocokan MIME vs signature dicatat sebagai ``mime_conflict`` —
  tidak pernah disembunyikan;
- konten tanpa detector yang cocok → status ``unknown`` — artifact tetap
  tersimpan (pipeline tidak membuang bukti; ekstraksi menyusul bila ada
  plugin yang mampu).
"""

import base64
import json
from dataclasses import dataclass
from typing import Dict, List, Optional, Protocol, Tuple

# PNG 1x1 deterministik — fixture E2 (file tanpa ekstensi / MIME salah).
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAC"
    "hwGA60e6kgAAAABJRU5ErkJggg=="
)

# MIME → format (untuk rekonsiliasi; None = netral, tidak memicu konflik).
_MIME_FORMATS = {
    "text/html": "html",
    "application/json": "json",
    "application/xml": "xml",
    "text/xml": "xml",
    "application/zip": "zip",
    "application/gzip": "gzip",
    "application/x-gzip": "gzip",
    "image/png": "png",
    "image/jpeg": "jpeg",
    "application/pdf": "pdf",
    "text/plain": "text",
}

# Batas ukuran parse JSON (hindari parse berat atas body raksasa).
_JSON_PARSE_LIMIT = 1_048_576


@dataclass(frozen=True)
class IdentificationResult:
    """Hasil identifikasi satu konten — bukti penuh, tanpa klaim palsu.

    ``format_id`` "unknown" berarti tidak ada detector konten yang cocok;
    MIME/ekstensi tetap terekam sebagai petunjuk, konflik MIME ditandai.
    """

    format_id: str
    status: str  # "identified" | "unknown"
    confidence: str  # kategorial ("high" | "none") — tanpa probabilitas palsu
    evidence: Tuple[Tuple[str, str, str], ...] = ()  # (sumber, sinyal, nilai)
    filename_hint: Optional[str] = None
    mime_hint: Optional[str] = None
    mime_conflict: bool = False


class FormatDetector(Protocol):
    """Kontrak detector format — berbasis konten, deterministik."""

    name: str

    def detect(self, content: bytes) -> Optional[str]:
        """Kembalikan format_id bila konten cocok, selain itu None."""
        ...


class MagicByteDetector:
    """Signature magic bytes — bukti paling kuat (file-first)."""

    def __init__(self):
        self.name = "magic_bytes"
        self._table = (
            (b"PK\x03\x04", "zip"),
            (b"\x1f\x8b", "gzip"),
            (b"\x89PNG\r\n\x1a\n", "png"),
            (b"\xff\xd8\xff", "jpeg"),
            (b"%PDF-", "pdf"),
        )

    def detect(self, content: bytes) -> Optional[str]:
        for magic, format_id in self._table:
            if content.startswith(magic):
                return format_id
        return None


class JsonDetector:
    """JSON valid (mulai ``{``/``[`` dan parse berhasil) — bukti struktur."""

    def __init__(self):
        self.name = "json_parse"

    def detect(self, content: bytes) -> Optional[str]:
        stripped = content.lstrip()
        if stripped[:1] not in (b"{", b"["):
            return None
        if len(content) > _JSON_PARSE_LIMIT:
            return None
        try:
            json.loads(content.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        return "json"


class XmlDetector:
    """Deklarasi XML ``<?xml`` — bukti struktur."""

    def __init__(self):
        self.name = "xml_declaration"

    def detect(self, content: bytes) -> Optional[str]:
        if content.lstrip().startswith(b"<?xml"):
            return "xml"
        return None


class HtmlDetector:
    """DOCTYPE/html tag (toleran BOM + whitespace) — bukti struktur."""

    def __init__(self):
        self.name = "html_markup"

    def detect(self, content: bytes) -> Optional[str]:
        head = content.lstrip(b"\xef\xbb\xbf \t\r\n")[:200].lower()
        if head.startswith(b"<!doctype html") or head.startswith(b"<html"):
            return "html"
        return None


class TextDetector:
    """Teks UTF-8 polos tanpa null byte — fallback terakhir, bukti lemah."""

    def __init__(self):
        self.name = "utf8_text"

    def detect(self, content: bytes) -> Optional[str]:
        if not content or b"\x00" in content[:512]:
            return None
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            return None
        return "text"


class IdentificationRegistry:
    """Registry detector format — extensible tanpa mengubah core (ADR-006)."""

    def __init__(self):
        self._entries: List[Tuple[int, int, FormatDetector]] = []
        self._seq = 0

    def register(self, detector: FormatDetector, priority: int = 50) -> None:
        """Daftarkan detector — prioritas kecil dievaluasi lebih dulu.

        Detector fallback (teks generik) memakai prioritas besar agar detector
        plugin untuk format baru SELALU mendapat kesempatan sebelum fallback
        generik mengambil alih konten yang kebetulan teks valid; urutan
        registrasi menentukan urutan dalam prioritas yang sama.
        """
        self._entries.append((priority, self._seq, detector))
        self._seq += 1
        self._entries.sort(key=lambda entry: (entry[0], entry[1]))

    @classmethod
    def with_builtins(cls) -> "IdentificationRegistry":
        """Registry dengan detector bawaan (bukan batas permanen)."""
        registry = cls()
        registry.register(MagicByteDetector())
        registry.register(JsonDetector())
        registry.register(XmlDetector())
        registry.register(HtmlDetector())
        registry.register(TextDetector(), priority=100)
        return registry

    def identify(
        self,
        content: bytes,
        content_type: Optional[str] = None,
        filename: Optional[str] = None,
    ) -> IdentificationResult:
        """Identifikasi konten: signature menang; MIME/ekstensi = bukti.

        ``filename`` idealnya berasal dari header Content-Disposition
        (``parse_content_disposition``), bukan dari URL.
        """
        evidence: List[Tuple[str, str, str]] = []
        format_id: Optional[str] = None
        for _, _, detector in self._entries:
            detected = detector.detect(content)
            if detected:
                format_id = detected
                evidence.append(("signature", detector.name, detected))
                break

        mime_hint = (content_type or "").split(";")[0].strip().lower() or None
        if mime_hint:
            evidence.append(("mime", "content_type", mime_hint))

        ext = None
        if filename and "." in filename:
            ext = "." + filename.rsplit(".", 1)[1].lower()
            evidence.append(("filename", "extension", ext))

        # Rekonsiliasi: MIME diketahui dan berbeda dari hasil signature →
        # konflik TERCATAT (tidak disembunyikan); signature tetap menang.
        mime_conflict = bool(
            format_id
            and mime_hint
            and _MIME_FORMATS.get(mime_hint) is not None
            and _MIME_FORMATS[mime_hint] != format_id
        )

        return IdentificationResult(
            format_id=format_id or "unknown",
            status="identified" if format_id else "unknown",
            confidence="high" if format_id else "none",
            evidence=tuple(evidence),
            filename_hint=filename,
            mime_hint=mime_hint,
            mime_conflict=mime_conflict,
        )


def parse_content_disposition(value: Optional[str]) -> Optional[str]:
    """Ambil filename dari header Content-Disposition (RFC 6266 + 5987).

    ``filename*`` (RFC 5987, charset'lang'%encoded) diutamakan; tanpa
    direktif filename → None.
    """
    if not value:
        return None
    filename: Optional[str] = None
    for part in value.split(";"):
        part = part.strip()
        lowered = part.lower()
        if lowered.startswith("filename*="):
            from urllib.parse import unquote

            raw = part.split("=", 1)[1].strip().strip('"')
            pieces = raw.split("'", 2)
            if len(pieces) == 3:
                charset = pieces[0] or "utf-8"
                try:
                    filename = unquote(pieces[2], encoding=charset, errors="replace")
                except LookupError:
                    filename = unquote(pieces[2])
            else:
                filename = unquote(raw)
            return filename or None
        if lowered.startswith("filename=") and filename is None:
            raw = part.split("=", 1)[1].strip()
            if len(raw) >= 2 and raw.startswith('"') and raw.endswith('"'):
                raw = raw[1:-1]
            filename = raw or None
    return filename


def filename_from_headers(headers: Optional[Dict[str, str]]) -> Optional[str]:
    """Filename dari header Content-Disposition — lookup case-insensitive.

    Nama header bisa tiba dalam case apa pun tergantung transport (libcurl
    menormalkan ke huruf kecil), sehingga lookup wajib toleran case.
    """
    if not headers:
        return None
    for key, value in headers.items():
        if key.lower() == "content-disposition":
            return parse_content_disposition(value)
    return None
