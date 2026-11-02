"""Job scheduler for the Universal Web Acquisition Engine."""

import asyncio
import logging
from typing import List, Optional
from datetime import datetime, timedelta

from universal_web_acquisition.core.job_model import Job, JobStatus
from universal_web_acquisition.core.job_repository import JobRepository

logger = logging.getLogger(__name__)


class JobScheduler:
    """Scheduler for job execution."""
    
    def __init__(self, job_repository: 'JobRepository'):
        """Initialize the job scheduler.
        
        Args:
            job_repository: The job repository
        """
        self.job_repository = job_repository
        self._running = False
        self._schedule_task: Optional[asyncio.Task] = None
        
    async def start(self) -> None:
        """Start the scheduler."""
        if self._running:
            logger.warning("Scheduler is already running")
            return
            
        logger.info("Starting job scheduler")
        self._running = True
        self._schedule_task = asyncio.create_task(self._schedule_loop())
        logger.info("Job scheduler started")
        
    async def stop(self) -> None:
        """Stop the scheduler."""
        if not self._running:
            logger.warning("Scheduler is not running")
            return
            
        logger.info("Stopping job scheduler")
        self._running = False
        if self._schedule_task:
            self._schedule_task.cancel()
            try:
                await self._schedule_task
            except asyncio.CancelledError:
                pass
            self._schedule_task = None
        logger.info("Job scheduler stopped")
        
    async def _schedule_loop(self) -> None:
        """Main scheduler loop."""
        while self._running:
            try:
                # Find queued jobs
                jobs = self.job_repository.list_jobs(limit=100)
                queued_jobs = [job for job in jobs if job.status == JobStatus.QUEUED]
                
                # Start workers for queued jobs (in a real implementation, this would
                # distribute jobs to worker pools based on capacity and priorities)
                for job in queued_jobs[:5]:  # Limit to 5 concurrent jobs for now
                    logger.debug(f"Scheduling job {job.job_id} for execution")
                    # In a real implementation, this would send the job to a worker pool
                    # For now, we'll just log that it would be scheduled
                    
                # Wait before next scheduling cycle
                await asyncio.sleep(1)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}")
                await asyncio.sleep(5)  # Wait longer on error
