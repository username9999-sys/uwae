"""Typed contract tests (Mandatory Phase 2 — INSTRUCTION.md).

Covers the contract pairs mandated by Phase 2 that were not yet typed:
RequestSpec/ResponseMetadata, AcquisitionResult/ArtifactIntegrity,
BenchmarkRecord/FailureClassification — plus the mandate rule that
transport capabilities claim nothing without executable evidence.
"""

import dataclasses
import hashlib
import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from universal_web_acquisition.access.model import AccessState, ReasonCode
from universal_web_acquisition.artifact.model import (
    AcquisitionResult,
    ArtifactIntegrity,
)
from universal_web_acquisition.benchmark.model import (
    BenchmarkRecord,
    FailureClassification,
)
from universal_web_acquisition.core.job_model import JobStatus
from universal_web_acquisition.http_transport.contracts import (
    RequestSpec,
    ResponseMetadata,
)
from universal_web_acquisition.http_transport.registry import TransportCapability


class TestRequestSpec:
    def test_valid_defaults(self):
        spec = RequestSpec(url="https://example.com/x")
        assert spec.method == "GET"
        assert spec.timeout_seconds == 30.0
        assert spec.max_bytes is None
        assert spec.range is None

    def test_invalid_url_rejected(self):
        with pytest.raises(ValueError):
            RequestSpec(url="ftp://example.com/x")

    def test_nonpositive_timeout_rejected(self):
        with pytest.raises(ValueError):
            RequestSpec(url="https://example.com", timeout_seconds=0)

    def test_bad_max_bytes_rejected(self):
        with pytest.raises(ValueError):
            RequestSpec(url="https://example.com", max_bytes=0)

    def test_bad_range_rejected(self):
        with pytest.raises(ValueError):
            RequestSpec(url="https://example.com", range=(5, 2))

    def test_valid_range_accepted(self):
        spec = RequestSpec(url="https://example.com", range=(0, 1023))
        assert spec.range == (0, 1023)

    def test_frozen(self):
        spec = RequestSpec(url="https://example.com")
        with pytest.raises(dataclasses.FrozenInstanceError):
            spec.url = "https://other.com"


class TestResponseMetadata:
    def test_header_case_insensitive(self):
        meta = ResponseMetadata(status_code=200, headers={"Content-Type": "text/html"})
        assert meta.header("content-type") == "text/html"
        assert meta.header("CONTENT-TYPE") == "text/html"
        assert meta.header("Retry-After") is None

    def test_frozen(self):
        meta = ResponseMetadata(status_code=200)
        with pytest.raises(dataclasses.FrozenInstanceError):
            meta.status_code = 500


class TestArtifactIntegrity:
    def test_from_content_matches_hashlib(self):
        content = b"payload-for-integrity"
        integrity = ArtifactIntegrity.from_content(content, "text/plain")
        assert integrity.sha256 == hashlib.sha256(content).hexdigest()
        assert integrity.size_bytes == len(content)
        assert integrity.content_type == "text/plain"

    def test_verify_true_and_false(self):
        content = b"payload"
        integrity = ArtifactIntegrity.from_content(content)
        assert integrity.verify(content) is True
        assert integrity.verify(b"tampered") is False
        assert integrity.verify(content + b"x") is False

    def test_frozen(self):
        integrity = ArtifactIntegrity.from_content(b"x")
        with pytest.raises(dataclasses.FrozenInstanceError):
            integrity.sha256 = "fake"


class TestAcquisitionResult:
    def test_succeeded_requires_artifact_and_integrity(self):
        # tidak ada sukses tanpa bukti artifact (invarian kontrak)
        with pytest.raises(ValueError):
            AcquisitionResult(
                job_id="j1", url="http://x/", status=JobStatus.SUCCEEDED
            )
        with pytest.raises(ValueError):
            AcquisitionResult(
                job_id="j1",
                url="http://x/",
                status=JobStatus.SUCCEEDED,
                artifact_id="a1",
            )

    def test_succeeded_complete_is_valid(self):
        integrity = ArtifactIntegrity.from_content(b"data")
        result = AcquisitionResult(
            job_id="j1",
            url="http://x/",
            status=JobStatus.SUCCEEDED,
            artifact_id="a1",
            integrity=integrity,
        )
        assert result.succeeded is True

    def test_failed_without_artifact_is_valid(self):
        result = AcquisitionResult(
            job_id="j1",
            url="http://x/",
            status=JobStatus.FAILED,
            reason_code="budget_exhausted",
            error="anggaran habis",
        )
        assert result.succeeded is False

    def test_frozen(self):
        result = AcquisitionResult(job_id="j1", url="http://x/", status=JobStatus.FAILED)
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.status = JobStatus.SUCCEEDED


class TestFailureClassification:
    def test_from_state_all_nine(self):
        assert FailureClassification.from_state(AccessState.ACCESS_GRANTED) is None
        assert (
            FailureClassification.from_state(AccessState.NETWORK_FAILURE)
            is FailureClassification.NETWORK
        )
        assert (
            FailureClassification.from_state(AccessState.RATE_LIMITED)
            is FailureClassification.RATE_LIMITED
        )
        assert (
            FailureClassification.from_state(AccessState.CHALLENGE_PRESENT)
            is FailureClassification.CHALLENGE
        )
        assert (
            FailureClassification.from_state(AccessState.AUTH_REQUIRED)
            is FailureClassification.AUTH_REQUIRED
        )
        assert (
            FailureClassification.from_state(AccessState.ACCESS_DENIED)
            is FailureClassification.ACCESS_DENIED
        )
        assert (
            FailureClassification.from_state(AccessState.CONTENT_INVALID)
            is FailureClassification.CONTENT_MISMATCH
        )
        assert (
            FailureClassification.from_state(AccessState.JAVASCRIPT_REQUIRED)
            is FailureClassification.CONTENT_MISMATCH
        )
        assert (
            FailureClassification.from_state(AccessState.UNKNOWN)
            is FailureClassification.UNKNOWN
        )

    def test_from_reason_code_spot_checks(self):
        assert (
            FailureClassification.from_reason_code(ReasonCode.DNS_FAILURE)
            is FailureClassification.NETWORK
        )
        assert (
            FailureClassification.from_reason_code(ReasonCode.TIMEOUT)
            is FailureClassification.TIMEOUT
        )
        assert (
            FailureClassification.from_reason_code(ReasonCode.HTTP_429)
            is FailureClassification.RATE_LIMITED
        )
        assert (
            FailureClassification.from_reason_code(ReasonCode.CHALLENGE_DETECTED)
            is FailureClassification.CHALLENGE
        )
        assert (
            FailureClassification.from_reason_code(ReasonCode.AUTH_EXPIRED)
            is FailureClassification.AUTH_REQUIRED
        )
        assert (
            FailureClassification.from_reason_code(ReasonCode.HTTP_5XX)
            is FailureClassification.CONTENT_MISMATCH
        )
        assert (
            FailureClassification.from_reason_code(ReasonCode.CAPABILITY_MISSING)
            is FailureClassification.CAPABILITY_MISSING
        )
        assert (
            FailureClassification.from_reason_code(ReasonCode.BUDGET_EXHAUSTED)
            is FailureClassification.BUDGET_EXHAUSTED
        )
        # HTTP_4XX ambigu (403 denial vs 404 missing) → jujur UNKNOWN
        assert (
            FailureClassification.from_reason_code(ReasonCode.HTTP_4XX)
            is FailureClassification.UNKNOWN
        )

    def test_total_over_all_reason_codes(self):
        # total: setiap ReasonCode terpetakan tanpa exception
        for reason in ReasonCode:
            assert isinstance(
                FailureClassification.from_reason_code(reason), FailureClassification
            )


class TestBenchmarkRecord:
    def test_success_must_not_carry_failure_classification(self):
        with pytest.raises(ValueError):
            BenchmarkRecord(
                record_id="r1",
                benchmark_id="e9",
                scenario_id="s1",
                engine="uwae",
                engine_version="0.3.0",
                success=True,
                duration_ms=10.0,
                peak_memory_bytes=1000,
                classification=FailureClassification.NETWORK,
            )

    def test_failed_record_with_classification(self):
        record = BenchmarkRecord(
            record_id="r2",
            benchmark_id="e9",
            scenario_id="s1",
            engine="uwae",
            engine_version="0.3.0",
            success=False,
            duration_ms=10.0,
            peak_memory_bytes=1000,
            classification=FailureClassification.RATE_LIMITED,
            observed_state="rate_limited",
        )
        assert record.classification is FailureClassification.RATE_LIMITED

    def test_timestamp_caller_supplied_for_reproducibility(self):
        ts = datetime(2026, 10, 23)
        record = BenchmarkRecord(
            record_id="r3",
            benchmark_id="e9",
            scenario_id="s1",
            engine="uwae",
            engine_version="0.3.0",
            success=True,
            duration_ms=1.0,
            peak_memory_bytes=1,
            timestamp=ts,
        )
        assert record.timestamp == ts

    def test_frozen(self):
        record = BenchmarkRecord(
            record_id="r4",
            benchmark_id="e9",
            scenario_id="s1",
            engine="uwae",
            engine_version="0.3.0",
            success=True,
            duration_ms=1.0,
            peak_memory_bytes=1,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            record.success = False


class TestCapabilityDefaults:
    def test_default_capability_claims_nothing(self):
        # mandat: "Do not claim HTTP/2, HTTP/3, browser execution, streaming,
        # or session support without an executable test" — default kosong.
        cap = TransportCapability()
        assert cap.tls_fingerprint is False
        assert cap.http2 is False
        assert cap.http3 is False
        assert cap.brotli is False
        assert cap.supports_async is False
