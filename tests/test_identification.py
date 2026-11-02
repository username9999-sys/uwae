"""File Identification Registry tests (E2 — file-first, bukan extension-first).

Yang diverifikasi:
- signature menang atas MIME/ekstensi yang salah (file-first);
- konflik MIME vs signature TERCATAT (tidak disembunyikan);
- konten tanpa detector → status unknown, tanpa klaim palsu;
- Content-Disposition (RFC 6266/5987) diparse dengan benar;
- registry extensible — detector baru tanpa mengubah core;
- wiring worker: event audit ``identification`` terekam setelah ACCEPT,
  termasuk filename dari Content-Disposition (fixture /file-no-ext) dan
  konflik MIME (fixture /file-wrong-mime).
"""

import asyncio
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from universal_web_acquisition.artifact.identification import (
    PNG_1X1,
    IdentificationRegistry,
    parse_content_disposition,
)
from universal_web_acquisition.artifact.storage import FilesystemArtifactStorage
from universal_web_acquisition.benchmark.fixture_server import FixtureServer
from universal_web_acquisition.core.job_model import Job, JobStatus
from universal_web_acquisition.core.job_repository import JobRepository
from universal_web_acquisition.core.job_worker import JobWorker
from universal_web_acquisition.http_transport.registry import RetryPolicy


def _make_repo():
    repo = JobRepository()
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo.db_path = path
    repo._init_db()
    return repo, path


class TestSignatureDetection:
    def _registry(self):
        return IdentificationRegistry.with_builtins()

    def test_png_identified_without_mime_or_name(self):
        # file tanpa ekstensi & MIME generik → tetap dikenali dari signature
        result = self._registry().identify(PNG_1X1)
        assert result.format_id == "png"
        assert result.status == "identified"
        assert result.confidence == "high"
        assert ("signature", "magic_bytes", "png") in result.evidence

    def test_magic_bytes_table(self):
        reg = self._registry()
        assert reg.identify(b"PK\x03\x04xxxx").format_id == "zip"
        assert reg.identify(b"\x1f\x8b\x08xxxx").format_id == "gzip"
        assert reg.identify(b"%PDF-1.7 rest").format_id == "pdf"
        assert reg.identify(b"\xff\xd8\xff\xe0rest").format_id == "jpeg"

    def test_structured_text_formats(self):
        reg = self._registry()
        assert (
            reg.identify(b"<!DOCTYPE html><html><body>x</body></html>").format_id
            == "html"
        )
        # toleran BOM + whitespace
        assert (
            reg.identify(b"\xef\xbb\xbf  <!doctype html><html></html>").format_id
            == "html"
        )
        assert reg.identify(b'{"a": 1}').format_id == "json"
        assert reg.identify(b"[1, 2]").format_id == "json"
        assert reg.identify(b'<?xml version="1.0"?><a/>').format_id == "xml"
        assert reg.identify(b"plain text hello").format_id == "text"

    def test_unknown_binary_gets_no_claim(self):
        # binary dengan null byte, tanpa magic → unknown (tanpa klaim palsu)
        result = self._registry().identify(bytes(range(0, 32)) * 4)
        assert result.status == "unknown"
        assert result.format_id == "unknown"
        assert result.confidence == "none"

    def test_invalid_json_not_json(self):
        # kurung kurawal tanpa JSON valid → bukan json (jujur)
        result = self._registry().identify(b"{not json at all")
        assert result.format_id != "json"


class TestMimeReconciliation:
    def test_signature_wins_over_wrong_mime(self):
        # E2: MIME salah (text/plain untuk PNG) → signature menang + konflik
        result = IdentificationRegistry.with_builtins().identify(
            PNG_1X1, content_type="text/plain"
        )
        assert result.format_id == "png"
        assert result.mime_hint == "text/plain"
        assert result.mime_conflict is True
        assert ("mime", "content_type", "text/plain") in result.evidence

    def test_agreeing_mime_no_conflict(self):
        result = IdentificationRegistry.with_builtins().identify(
            PNG_1X1, content_type="image/png"
        )
        assert result.mime_conflict is False

    def test_octet_stream_is_neutral(self):
        # application/octet-stream tidak mengklaim format → bukan konflik
        result = IdentificationRegistry.with_builtins().identify(
            PNG_1X1, content_type="application/octet-stream"
        )
        assert result.format_id == "png"
        assert result.mime_conflict is False

    def test_extension_and_mime_both_wrong(self):
        # HTML berpakaian .zip + application/zip → html menang, konflik
        result = IdentificationRegistry.with_builtins().identify(
            b"<!DOCTYPE html><html></html>",
            content_type="application/zip",
            filename="x.zip",
        )
        assert result.format_id == "html"
        assert result.mime_conflict is True
        assert result.filename_hint == "x.zip"
        assert ("filename", "extension", ".zip") in result.evidence


class TestContentDisposition:
    def test_basic_quoted(self):
        assert (
            parse_content_disposition('attachment; filename="data.zip"')
            == "data.zip"
        )

    def test_unquoted(self):
        assert parse_content_disposition("attachment; filename=data.zip") == "data.zip"

    def test_filename_star_rfc5987(self):
        assert (
            parse_content_disposition("attachment; filename*=UTF-8''na%C3%AFve.txt")
            == "naïve.txt"
        )

    def test_absent_or_without_filename(self):
        assert parse_content_disposition("") is None
        assert parse_content_disposition("inline") is None


class TestRegistryExtensibility:
    def test_custom_detector_without_core_change(self):
        class CustomDetector:
            name = "custom_magic"

            def detect(self, content):
                if content.startswith(b"UWAE1"):
                    return "uwae-format"
                return None

        reg = IdentificationRegistry.with_builtins()
        reg.register(CustomDetector())
        result = reg.identify(b"UWAE1payload")
        assert result.format_id == "uwae-format"
        assert ("signature", "custom_magic", "uwae-format") in result.evidence


class TestWorkerIdentification:
    """Wiring worker: event audit ``identification`` SETELAH ACCEPT (E2)."""

    def _worker(self, repo):
        return JobWorker(
            repo,
            scheduler=None,
            storage=FilesystemArtifactStorage(
                base_path=tempfile.mkdtemp(prefix="uwae-ident-")
            ),
            retry_policy=RetryPolicy(max_retries=1, base_backoff_seconds=0.01),
            identifier=IdentificationRegistry.with_builtins(),
        )

    def _identification_event(self, repo, job_id):
        events = repo.list_events(job_id)
        detail = next(e["detail"] for e in events if e["event"] == "identification")
        return json.loads(detail)

    def test_file_without_extension_identified_by_signature(self):
        repo, db_path = _make_repo()
        try:
            worker = self._worker(repo)
            with FixtureServer() as base:
                job = Job(job_id="id1", url=base + "/file-no-ext")
                repo.save_job(job)
                asyncio.run(worker._execute_job(job))
            assert repo.get_job("id1").status == JobStatus.SUCCEEDED
            ident = self._identification_event(repo, "id1")
            # signature PNG menang atas MIME generik + nama tanpa ekstensi
            assert ident["format"] == "png"
            assert ident["filename_hint"] == "download"
            assert ident["mime_conflict"] is False
        finally:
            os.unlink(db_path)

    def test_wrong_mime_flagged_as_conflict(self):
        repo, db_path = _make_repo()
        try:
            worker = self._worker(repo)
            with FixtureServer() as base:
                job = Job(job_id="id2", url=base + "/file-wrong-mime")
                repo.save_job(job)
                asyncio.run(worker._execute_job(job))
            assert repo.get_job("id2").status == JobStatus.SUCCEEDED
            ident = self._identification_event(repo, "id2")
            assert ident["format"] == "png"
            assert ident["mime"] == "text/plain"
            assert ident["mime_conflict"] is True
        finally:
            os.unlink(db_path)

    def test_no_identifier_no_event(self):
        # tanpa identifier → tidak ada event identification (wiring opsional)
        repo, db_path = _make_repo()
        try:
            worker = JobWorker(
                repo,
                scheduler=None,
                storage=FilesystemArtifactStorage(
                    base_path=tempfile.mkdtemp(prefix="uwae-ident-")
                ),
                retry_policy=RetryPolicy(max_retries=1, base_backoff_seconds=0.01),
            )
            with FixtureServer() as base:
                job = Job(job_id="id3", url=base + "/file-no-ext")
                repo.save_job(job)
                asyncio.run(worker._execute_job(job))
            assert repo.get_job("id3").status == JobStatus.SUCCEEDED
            events = repo.list_events("id3")
            assert not any(e["event"] == "identification" for e in events)
        finally:
            os.unlink(db_path)
