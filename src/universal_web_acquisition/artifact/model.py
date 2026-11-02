"""Artifact model for the Universal Web Acquisition Engine."""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any

from universal_web_acquisition.core.job_model import JobStatus


@dataclass
class Artifact:
    """Artifact representing acquired content."""
    
    job_id: str
    url: str
    content: bytes
    content_type: str = "application/octet-stream"
    status_code: int = 200
    headers: Dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    artifact_id: Optional[str] = None
    
    def __post_init__(self):
        """Generate an artifact ID if not provided."""
        if self.artifact_id is None:
            import uuid
            self.artifact_id = str(uuid.uuid4())
            
    @property
    def size(self) -> int:
        """Get the size of the content in bytes.
        
        Returns:
            Size of content in bytes
        """
        return len(self.content)
        
    def is_success(self) -> bool:
        """Check if the artifact represents a successful acquisition.

        Returns:
            True if status code indicates success
        """
        return 200 <= self.status_code < 300


@dataclass(frozen=True)
class ArtifactIntegrity:
    """Integritas artifact — sha256 + ukuran (Mandatory Phase 2, §5.3).

    Setiap artifact sukses wajib membawa ini; ``verify`` membandingkan
    konten terhadap sidik jari yang direkam.
    """

    sha256: str
    size_bytes: int
    content_type: str = "application/octet-stream"

    @classmethod
    def from_content(
        cls, content: bytes, content_type: str = "application/octet-stream"
    ) -> "ArtifactIntegrity":
        return cls(
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            content_type=content_type,
        )

    def verify(self, content: bytes) -> bool:
        return (
            len(content) == self.size_bytes
            and hashlib.sha256(content).hexdigest() == self.sha256
        )


@dataclass(frozen=True)
class AcquisitionResult:
    """Hasil terminal satu akuisisi (Mandatory Phase 2).

    Invarian: status SUCCEEDED wajib membawa ``artifact_id`` DAN
    ``integrity`` — keberhasilan tanpa bukti artifact tidak sah (tidak ada
    sukses palsu, kriteria lulus Milestone C).
    """

    job_id: str
    url: str
    status: JobStatus
    observed_state: Optional[str] = None
    reason_code: Optional[str] = None
    artifact_id: Optional[str] = None
    integrity: Optional[ArtifactIntegrity] = None
    attempts: int = 1
    duration_ms: float = 0.0
    error: Optional[str] = None

    def __post_init__(self):
        if self.status is JobStatus.SUCCEEDED and (
            self.artifact_id is None or self.integrity is None
        ):
            raise ValueError(
                "SUCCEEDED wajib membawa artifact_id dan integrity "
                "(tidak ada sukses tanpa bukti)"
            )

    @property
    def succeeded(self) -> bool:
        return self.status is JobStatus.SUCCEEDED
