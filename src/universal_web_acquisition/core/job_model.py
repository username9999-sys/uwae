"""Job model for the Universal Web Acquisition Engine."""

from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict
import json


class JobStatus(Enum):
    """Job status enumeration."""
    QUEUED = "queued"
    RUNNING = "running"
    VALIDATING = "validating"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"
    RETRY_WAIT = "retry_wait"
    NEEDS_USER = "needs_user"


@dataclass
class Job:
    """Job model representing an acquisition task."""
    
    job_id: str
    url: str
    status: JobStatus = JobStatus.QUEUED
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    artifact_id: Optional[str] = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    method: str = "GET"
    body: Optional[bytes] = None
    headers: Optional[Dict[str, str]] = None
    # Retry budget per ReasonCode (P2) — serialisasi JSON ke SQLite.
    # Key = ReasonCode.value (string), Value = remaining budget (int).
    # None = belum diinisialisasi (default max_retries per reason).
    retry_budget: Optional[Dict[str, int]] = None
    # Peak memory accounting per job (P3) — bytes, terukur via tracemalloc.
    peak_memory_bytes: Optional[int] = None

    def __post_init__(self) -> None:
        # Method dinormalisasi di satu tempat supaya jalur cache, resume, dan
        # wire konsisten: "post" dan "POST" adalah permintaan yang sama.
        self.method = (self.method or "GET").strip().upper()

    # Retry budget helpers (P2)
    def init_retry_budget(self, reason_codes: list, max_per_reason: int = 3) -> None:
        """Inisialisasi budget retry per ReasonCode."""
        self.retry_budget = {rc.value: max_per_reason for rc in reason_codes}

    def consume_retry_budget(self, reason_code) -> bool:
        """Kurangi budget untuk reason_code. Return True jika masih punya budget."""
        if self.retry_budget is None:
            return self.retry_count < self.max_retries
        key = reason_code.value if hasattr(reason_code, 'value') else str(reason_code)
        remaining = self.retry_budget.get(key, 0)
        if remaining <= 0:
            return False
        self.retry_budget[key] = remaining - 1
        return True

    def get_retry_budget(self, reason_code) -> int:
        """Sisa budget untuk reason_code."""
        if self.retry_budget is None:
            return self.max_retries - self.retry_count
        key = reason_code.value if hasattr(reason_code, 'value') else str(reason_code)
        return self.retry_budget.get(key, 0)

    def mark_started(self) -> None:
        """Mark the job as started."""
        self.started_at = datetime.now()
        self.updated_at = datetime.now()
        self.status = JobStatus.RUNNING
        
    def mark_completed(self, artifact_id: str) -> None:
        """Mark the job as completed successfully.
        
        Args:
            artifact_id: The ID of the resulting artifact
        """
        self.completed_at = datetime.now()
        self.updated_at = datetime.now()
        self.status = JobStatus.SUCCEEDED
        self.artifact_id = artifact_id
        
    def mark_failed(self, error: str) -> None:
        """Mark the job as failed.
        
        Args:
            error: The error message
        """
        self.completed_at = datetime.now()
        self.updated_at = datetime.now()
        self.status = JobStatus.FAILED
        self.error = error
        
    def mark_canceled(self) -> None:
        """Mark the job as canceled."""
        self.updated_at = datetime.now()
        self.status = JobStatus.CANCELED
        
    def mark_retry_wait(self, retry_count: int) -> None:
        """Mark the job as waiting for retry.
        
        Args:
            retry_count: The current retry count
        """
        self.updated_at = datetime.now()
        self.status = JobStatus.RETRY_WAIT
        self.retry_count = retry_count
        
    def mark_needs_user(self) -> None:
        """Mark the job as needing user intervention."""
        self.updated_at = datetime.now()
        self.status = JobStatus.NEEDS_USER
        
    def is_terminal(self) -> bool:
        """Check if the job is in a terminal state.
        
        Returns:
            True if the job is succeeded, failed, or canceled
        """
        return self.status in [JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELED]
