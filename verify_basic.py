#!/usr/bin/env python3
"""Basic verification script for Universal Web Acquisition Engine."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from universal_web_acquisition.core.engine import AcquisitionEngine
from universal_web_acquisition.core.job_model import Job, JobStatus
from universal_web_acquisition.core.job_repository import JobRepository
from universal_web_acquisition.core.scheduler import JobScheduler
from universal_web_acquisition.core.job_worker import JobWorker
from universal_web_acquisition.config import Config


def test_imports():
    """Test that we can import the core modules."""
    try:
        assert AcquisitionEngine is not None
        assert Job is not None
        assert JobRepository is not None
        print("✓ All imports successful")
        return True
    except Exception as e:
        print(f"✗ Import failed: {e}")
        return False

def test_job_creation():
    """Test job creation and basic properties."""
    try:
        job = Job(job_id="test-job", url="https://example.com")
        assert job.job_id == "test-job"
        assert job.url == "https://example.com"
        assert job.status.name == "QUEUED"
        print("✓ Job creation successful")
        return True
    except Exception as e:
        print(f"✗ Job creation failed: {e}")
        return False

def test_job_repository():
    """Test job repository basic operations."""
    try:
        repo = JobRepository()
        job = Job(job_id="repo-test", url="https://test.com")
        repo.save_job(job)
        retrieved = repo.get_job("repo-test")
        assert retrieved is not None
        assert retrieved.job_id == "repo-test"
        assert retrieved.url == "https://test.com"
        print("✓ Job repository operations successful")
        return True
    except Exception as e:
        print(f"✗ Job repository failed: {e}")
        return False

def test_config_loading():
    """Test configuration loading."""
    try:
        config = Config()
        # Test getting a value with default
        db_path = config.get("database.path", "default.db")
        assert isinstance(db_path, str)
        print("✓ Configuration loading successful")
        return True
    except Exception as e:
        print(f"✗ Configuration loading failed: {e}")
        return False

def main():
    """Run all verification tests."""
    print("Running basic verification tests...\n")
    
    tests = [
        test_imports,
        test_job_creation,
        test_job_repository,
        test_config_loading
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        if test():
            passed += 1
        print()  # Add spacing between tests
    
    print(f"Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("✓ All verification tests passed!")
        return 0
    else:
        print("✗ Some verification tests failed!")
        return 1

if __name__ == "__main__":
    sys.exit(main())
