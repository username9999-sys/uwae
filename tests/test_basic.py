"""Basic tests for the Universal Web Acquisition Engine."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

import pytest
from universal_web_acquisition.core.job_model import Job, JobStatus
from universal_web_acquisition.core.job_repository import JobRepository


def test_job_creation():
    """Test creating a job."""
    job = Job(job_id="test-job", url="https://example.com")
    assert job.job_id == "test-job"
    assert job.url == "https://example.com"
    assert job.status == JobStatus.QUEUED


def test_job_repository():
    """Test the job repository."""
    repo = JobRepository()
    
    # Create a job
    job = Job(job_id="test-job-repo", url="https://example.com")
    repo.save_job(job)
    
    # Retrieve the job
    retrieved = repo.get_job("test-job-repo")
    assert retrieved is not None
    assert retrieved.job_id == "test-job-repo"
    assert retrieved.url == "https://example.com"
    assert retrieved.status == JobStatus.QUEUED
    
    # List jobs
    jobs = repo.list_jobs(limit=10)
    assert len(jobs) >= 1
    assert any(j.job_id == "test-job-repo" for j in jobs)


if __name__ == "__main__":
    pytest.main([__file__])
