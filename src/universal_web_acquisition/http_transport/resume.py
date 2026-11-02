"""Resumable downloads (A09, §5.2 INSTRUCTION.md).

Aturan mandat yang diimplementasikan:

- "Validasi apakah server mendukung resume sebelum melanjutkan unduhan" —
  HEAD probe (``Accept-Ranges`` + ``Content-Length``) sebelum chunk pertama;
- "jangan menganggap ``Range`` selalu didukung… bukan menggabungkan byte
  secara spekulatif" — setiap chunk diverifikasi (206 + ``Content-Range``
  start == posisi yang diminta, total cocok); penyimpangan → kegagalan,
  bukan penggabungan;
- checkpoint tanpa validator (ETag) tidak dipakai — unduhan diulang dari
  awal, bukan dilanjutkan buta;
- server tanpa dukungan resume / konten kecil (<= ``RESUME_MIN_TOTAL``) →
  unduh penuh lewat jalur adapter normal (fallback tercatat sebagai event).

Checkpoint durabel: satu event ``download_checkpoint`` per chunk di
``job_events`` — bertahan lintas restart proses; kegagalan jaringan di
tengah unduhan meninggalkan checkpoint, attempt berikutnya (keputusan
planner RETRY_SAME_TRANSPORT) melanjutkan dari posisi tersimpan.
"""

import json
import os
from typing import Dict, Optional, Tuple

from universal_web_acquisition.access.model import ReasonCode
from universal_web_acquisition.artifact.model import Artifact
from universal_web_acquisition.http_transport.adapters import TransportFailure

# Di bawah ambang ini overhead probe + chunking tidak sepadan — unduh penuh.
RESUME_MIN_TOTAL = 256 * 1024
DEFAULT_CHUNK_SIZE = 64 * 1024


def _header(headers: Optional[Dict[str, str]], name: str) -> Optional[str]:
    """Lookup header case-insensitive (kapitalisasi antar-library berbeda)."""
    lowered = name.lower()
    for key, value in (headers or {}).items():
        if key.lower() == lowered:
            return value
    return None


def _parse_content_range(
    value: Optional[str],
) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    """``bytes 0-65535/524288`` → ``(0, 65535, 524288)``; None bila tak terurai."""
    if not value or not value.strip().startswith("bytes "):
        return (None, None, None)
    spec = value.strip().split(" ", 1)[1]
    range_part, _, total_part = spec.partition("/")
    start_s, _, end_s = range_part.partition("-")
    try:
        return (int(start_s), int(end_s), int(total_part))
    except ValueError:
        return (None, None, None)


class ResumableDownloader:
    """Unduhan chunked Range dengan checkpoint durabel (A09, §5.2)."""

    def __init__(
        self,
        adapter,
        job_repository,
        storage,
        cookies: Optional[Dict[str, str]] = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ):
        self._adapter = adapter
        self._repo = job_repository
        self._storage = storage
        self._cookies = cookies
        self._chunk_size = chunk_size

    async def acquire(self, job) -> Artifact:
        if job.method.upper() != "GET":
            # Resume = probe HEAD + chunk Range: keduanya semantik GET.
            # Menjalankannya untuk POST akan mengirim payload berulang ke
            # server dan membandingkan respons antar-chunk yang tidak
            # terkait — jadi non-GET ditolak, bukan dipaksa lewat.
            raise TransportFailure(
                ReasonCode.CAPABILITY_MISSING,
                f"resume tidak berlaku untuk method {job.method}",
            )
        try:
            head = self._adapter.head(job.url, cookies=self._cookies)
        except TransportFailure:
            raise
        except Exception as exc:
            raise TransportFailure(
                self._adapter.classify_exception(exc), f"{type(exc).__name__}: {exc}"
            ) from exc
        accept = _header(head.headers, "accept-ranges")
        total: Optional[int] = None
        raw_total = _header(head.headers, "content-length")
        if raw_total is not None:
            try:
                total = int(raw_total)
            except ValueError:
                total = None
        if accept != "bytes" or total is None or total <= RESUME_MIN_TOTAL:
            self._repo.record_event(
                job.job_id,
                "download_full_fallback",
                json.dumps({"reason": "range_unsupported_or_small", "total": total}),
            )
            return await self._adapter.acquire(job, self._storage, cookies=self._cookies)

        etag = _header(head.headers, "etag")
        content_type = _header(head.headers, "content-type") or "application/octet-stream"
        part_path = os.path.join(self._storage.base_path, f"{job.job_id}.part")
        pos = self._resume_position(job, etag, total, part_path)

        while pos < total:
            end = min(pos + self._chunk_size - 1, total - 1)
            try:
                resp = self._adapter.fetch_range(job.url, pos, end, cookies=self._cookies)
            except TransportFailure:
                raise
            except Exception as exc:
                raise TransportFailure(
                    self._adapter.classify_exception(exc),
                    f"{type(exc).__name__}: {exc}",
                ) from exc
            if resp.status_code != 206:
                raise TransportFailure(
                    ReasonCode.CONNECTION_ERROR,
                    f"server membalas {resp.status_code} untuk Range — resume tidak "
                    "valid; jangan gabungkan byte spekulatif (§5.2)",
                    status_code=resp.status_code,
                )
            cstart, _cend, ctot = _parse_content_range(
                _header(resp.headers, "content-range")
            )
            if cstart != pos or ctot != total:
                raise TransportFailure(
                    ReasonCode.CONNECTION_ERROR,
                    f"Content-Range tidak cocok (start {cstart} != {pos}, total "
                    f"{ctot} != {total}) — byte spekulatif ditolak (§5.2)",
                )
            with open(part_path, "ab") as f:
                f.write(resp.content)
            pos += len(resp.content)
            self._repo.record_event(
                job.job_id,
                "download_checkpoint",
                json.dumps({"bytes": pos, "total": total, "etag": etag}),
            )

        if pos != total:
            raise TransportFailure(
                ReasonCode.CONNECTION_ERROR,
                f"unduhan tidak lengkap ({pos}/{total})",
            )
        with open(part_path, "rb") as f:
            content = f.read()
        os.remove(part_path)
        artifact = Artifact(
            job_id=job.job_id,
            url=job.url,
            content=content,
            content_type=content_type,
            status_code=200,
            headers=dict(head.headers),
        )
        self._repo.record_event(
            job.job_id,
            "download_completed",
            json.dumps({"bytes": total, "etag": etag}),
        )
        return await self._storage.store(artifact)

    def _resume_position(self, job, etag: Optional[str], total: int, part_path: str) -> int:
        """Posisi mulai dari checkpoint durabel — atau 0 bila tidak aman (§5.2)."""
        checkpoint = self._repo.latest_checkpoint(job.job_id)
        if checkpoint is None:
            return 0
        if not etag:
            # Tanpa validator, kelanjutan tidak dapat dibuktikan konsisten —
            # ulang dari awal, jangan gabungkan byte spekulatif.
            self._repo.record_event(
                job.job_id,
                "checkpoint_discarded",
                json.dumps({"reason": "no_validator"}),
            )
            return 0
        stale_reason = None
        if checkpoint.get("etag") != etag:
            stale_reason = "etag_changed"
        elif not isinstance(checkpoint.get("bytes"), int) or not (
            0 < checkpoint["bytes"] < total
        ):
            stale_reason = "bytes_out_of_range"
        elif not os.path.exists(part_path) or os.path.getsize(part_path) != checkpoint["bytes"]:
            stale_reason = "part_file_missing_or_size_mismatch"
        if stale_reason is not None:
            self._repo.record_event(
                job.job_id, "checkpoint_discarded", json.dumps({"reason": stale_reason})
            )
            if os.path.exists(part_path):
                os.remove(part_path)
            return 0
        return checkpoint["bytes"]
