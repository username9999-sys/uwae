"""Core engine for the Universal Web Acquisition Engine."""

import asyncio
import logging
from typing import Optional, Dict, Any
from uuid import uuid4

from universal_web_acquisition.core.job_model import Job, JobStatus
from universal_web_acquisition.core.job_repository import JobRepository
from universal_web_acquisition.core.scheduler import JobScheduler
from universal_web_acquisition.core.job_worker import JobWorker

logger = logging.getLogger(__name__)


class AcquisitionEngine:
    """Main engine for the Universal Web Acquisition Engine."""
    
    def __init__(self, db_path: Optional[str] = None):
        """Initialize the acquisition engine.

        Args:
            db_path: Optional path to the SQLite database file
        """
        self.db_path = db_path
        self.job_repository = JobRepository(db_path)
        self.scheduler = JobScheduler(self.job_repository)
        self.worker = JobWorker(self.job_repository, self.scheduler)
        self._running = False
        
    async def start(self) -> None:
        """Start the acquisition engine."""
        if self._running:
            logger.warning("Engine is already running")
            return
            
        logger.info("Starting Universal Web Acquisition Engine")
        await self.scheduler.start()
        await self.worker.start()
        self._running = True
        logger.info("Universal Web Acquisition Engine started")
        
    async def stop(self) -> None:
        """Stop the acquisition engine."""
        if not self._running:
            logger.warning("Engine is not running")
            return
            
        logger.info("Stopping Universal Web Acquisition Engine")
        await self.worker.stop()
        await self.scheduler.stop()
        self._running = False
        logger.info("Universal Web Acquisition Engine stopped")
        
    def submit_job(self, url: str, job_id: Optional[str] = None) -> str:
        """Submit a URL for acquisition.
        
        Args:
            url: The URL to acquire
            job_id: Optional custom job ID
            
        Returns:
            The job ID
        """
        if job_id is None:
            job_id = str(uuid4())
            
        job = Job(
            job_id=job_id,
            url=url,
            status=JobStatus.QUEUED
        )
        
        self.job_repository.save_job(job)
        logger.info(f"Submitted job {job_id} for URL: {url}")
        return job_id
        
    def get_job(self, job_id: str) -> Optional[Job]:
        """Get a job by ID.
        
        Args:
            job_id: The job ID
            
        Returns:
            The job if found, None otherwise
        """
        return self.job_repository.get_job(job_id)
        
    def list_jobs(self, limit: int = 10) -> list:
        """List recent jobs.
        
        Args:
            limit: Maximum number of jobs to return
            
        Returns:
            List of jobs
        """
        return self.job_repository.list_jobs(limit=limit)
        
    def cancel_job(self, job_id: str) -> bool:
        """Cancel a job.
        
        Args:
            job_id: The job ID to cancel
            
        Returns:
            True if successful, False otherwise
        """
        job = self.job_repository.get_job(job_id)
        if not job:
            logger.warning(f"Job {job_id} not found for cancellation")
            return False
            
        if job.status in [JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELED]:
            logger.warning(f"Job {job_id} is already in terminal state: {job.status}")
            return False
            
        job.status = JobStatus.CANCELED
        self.job_repository.save_job(job)
        logger.info(f"Cancelled job {job_id}")
        return True
        
    def wait_for_job(self, job_id: str, timeout: Optional[float] = None) -> Job:
        """Wait for a job to complete.
        
        Args:
            job_id: The job ID to wait for
            timeout: Optional timeout in seconds
            
        Returns:
            The completed job
        """
        import time
        start_time = time.time()
        
        while True:
            job = self.get_job(job_id)
            if not job:
                raise ValueError(f"Job {job_id} not found")
                
            if job.status in [JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELED]:
                return job
                
            if timeout is not None and (time.time() - start_time) > timeout:
                raise TimeoutError(f"Timeout waiting for job {job_id}")
                
            # Wait a bit before checking again
            time.sleep(0.1)
