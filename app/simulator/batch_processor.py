"""
Batch Processing Manager for PT-Kit Simulator

This module provides job scheduling, progress tracking, and result aggregation
for batch processing experiments in the digital-twin simulator.

Components:
- BatchProcessingConfig: Configuration dataclass
- ExperimentJob: Job representation dataclass
- JobScheduler: Manages job queue and execution
- ProgressTracker: Monitors job progress
- ResultAggregator: Collects and aggregates results
- BatchProcessorManager: Main orchestrator
"""

from __future__ import annotations
import asyncio
import inspect
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple, Union
import uuid

# Type checking imports to avoid circular dependencies
if TYPE_CHECKING:
    import numpy as np
    from .profile_management import PlantProfile
else:
    # Runtime imports - will be used in actual execution
    try:
        import numpy as np
    except ImportError:
        np = None
    
    PlantProfile = Any  # Forward reference for runtime


# ============================================================================
# Enums and Data Classes
# ============================================================================


class JobStatus(str, Enum):
    """Status of an experiment job."""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


@dataclass
class BatchProcessingConfig:
    """Configuration for batch processing operations.
    
    Attributes:
        max_concurrent_jobs: Maximum number of jobs to run concurrently (default: 4)
        timeout_per_experiment: Timeout in seconds for each experiment (default: 300)
        retry_attempts: Number of retry attempts on failure (default: 2)
        log_level: Logging level string (default: "INFO")
        progress_callback: Optional callback for progress updates
        enable_retry: Whether to automatically retry failed jobs (default: True)
        retry_delay: Delay in seconds between retries (default: 5)
        cleanup_on_complete: Whether to clean up completed jobs from memory (default: False)
    """
    max_concurrent_jobs: int = 4
    timeout_per_experiment: int = 300
    retry_attempts: int = 2
    log_level: str = "INFO"
    progress_callback: Optional[Callable[[str, str, float], None]] = None
    enable_retry: bool = True
    retry_delay: int = 5
    cleanup_on_complete: bool = False
    
    def __post_init__(self):
        """Validate configuration after initialization."""
        if self.max_concurrent_jobs < 1:
            raise ValueError("max_concurrent_jobs must be at least 1")
        if self.timeout_per_experiment < 1:
            raise ValueError("timeout_per_experiment must be positive")
        if self.retry_attempts < 0:
            raise ValueError("retry_attempts cannot be negative")
        
        # Configure logging
        logging.basicConfig(
            level=getattr(logging, self.log_level.upper()),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)


@dataclass
class ExperimentJob:
    """Represents a single experiment job in the batch processing pipeline.
    
    Attributes:
        job_id: Unique identifier for the job
        experiment_name: Human-readable name for the experiment
        input_profile: Plant profile to use for the experiment
        measured_data: Dictionary mapping sensor names to measured data arrays
        status: Current job status (default: pending)
        result: Computed result when completed
        error_message: Error message if job failed
        start_time: When job started execution
        end_time: When job finished
        retry_count: Number of retry attempts made
        created_at: When job was created
        updated_at: Last update timestamp
    """
    job_id: str
    experiment_name: str
    input_profile: Any  # PlantProfile - from profile_management
    measured_data: Dict[str, Any]  # Dict[str, np.ndarray] - imported numpy
    status: JobStatus = JobStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    retry_count: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    def update_status(self, status: JobStatus, error_msg: Optional[str] = None):
        """Update job status and timestamps.
        
        Args:
            status: New status to set
            error_msg: Optional error message if status is FAILED or CANCELLED
        """
        self.status = status
        self.updated_at = datetime.now()
        if error_msg:
            self.error_message = error_msg
        
        if status == JobStatus.RUNNING and self.start_time is None:
            self.start_time = datetime.now()
        elif status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            self.end_time = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert job to dictionary for serialization.
        
        Returns:
            Dictionary representation of the job
        """
        return {
            'job_id': self.job_id,
            'experiment_name': self.experiment_name,
            'status': self.status.value,
            'result': self.result,
            'error_message': self.error_message,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'retry_count': self.retry_count,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }


# ============================================================================
# Progress Tracking
# ============================================================================


class ProgressTracker:
    """Tracks progress of batch processing operations.
    
    Provides real-time progress monitoring with callbacks to external systems.
    """
    
    def __init__(self, config: BatchProcessingConfig):
        """Initialize progress tracker.
        
        Args:
            config: Batch processing configuration
        """
        self.config = config
        self._jobs: Dict[str, ExperimentJob] = {}
        self._lock = asyncio.Lock()
        self._total_jobs = 0
        self._completed_jobs = 0
        self._failed_jobs = 0
        
    async def register_job(self, job: ExperimentJob):
        """Register a new job for tracking.
        
        Args:
            job: Job to register
        """
        async with self._lock:
            self._jobs[job.job_id] = job
            self._total_jobs += 1
            
            # Notify callback if configured
            if self.config.progress_callback:
                self.config.progress_callback(job.job_id, "registered", 0.0)
    
    async def update_job_status(self, job_id: str, status: JobStatus, 
                               progress_pct: float = 0.0, error_msg: Optional[str] = None):
        """Update job status and notify progress callback.
        
        Args:
            job_id: ID of job to update
            status: New status
            progress_pct: Progress percentage (0-100)
            error_msg: Optional error message
        """
        async with self._lock:
            if job_id not in self._jobs:
                self.config.logger.warning(f"Job {job_id} not found for status update")
                return
                
            job = self._jobs[job_id]
            
            # Handle completion counting
            if status == JobStatus.COMPLETED:
                self._completed_jobs += 1
            elif status in (JobStatus.FAILED, JobStatus.CANCELLED):
                self._failed_jobs += 1
            
            job.update_status(status, error_msg)
            
            # Call progress callback
            if self.config.progress_callback:
                self.config.progress_callback(job_id, status.value, progress_pct)
            
            # Log status change
            self.config.logger.info(
                f"Job {job_id}: {status.value} "
                f"(progress: {progress_pct:.1f}%, "
                f"completed: {self._completed_jobs}/{self._total_jobs})"
            )
    
    async def mark_running(self, job_id: str, progress_pct: float = 0.0):
        """Mark job as running.
        
        Args:
            job_id: ID of job
            progress_pct: Initial progress percentage
        """
        await self.update_job_status(job_id, JobStatus.RUNNING, progress_pct)
    
    async def mark_completed(self, job_id: str, progress_pct: float = 100.0):
        """Mark job as completed.
        
        Args:
            job_id: ID of job
            progress_pct: Final progress percentage (typically 100)
        """
        await self.update_job_status(job_id, JobStatus.COMPLETED, progress_pct)
    
    async def mark_failed(self, job_id: str, error_msg: str, progress_pct: float = 0.0):
        """Mark job as failed.
        
        Args:
            job_id: ID of job
            error_msg: Failure reason
            progress_pct: Progress at time of failure
        """
        await self.update_job_status(job_id, JobStatus.FAILED, progress_pct, error_msg)
    
    async def cancel_job(self, job_id: str):
        """Cancel a running job.
        
        Args:
            job_id: ID of job to cancel
        """
        await self.update_job_status(job_id, JobStatus.CANCELLED, 0.0)
        self.config.logger.info(f"Job {job_id} cancelled by user request")
    
    def get_progress_summary(self) -> Dict[str, Any]:
        """Get overall progress summary.
        
        Returns:
            Summary dictionary with progress statistics
        """
        total = len(self._jobs)
        if total == 0:
            return {
                'total_jobs': 0,
                'completed': 0,
                'failed': 0,
                'pending': 0,
                'running': 0,
                'progress_pct': 0.0,
                'jobs': []
            }
        
        completed = sum(1 for j in self._jobs.values() if j.status == JobStatus.COMPLETED)
        failed = sum(1 for j in self._jobs.values() if j.status in 
                    (JobStatus.FAILED, JobStatus.CANCELLED))
        running = sum(1 for j in self._jobs.values() if j.status == JobStatus.RUNNING)
        pending = sum(1 for j in self._jobs.values() if j.status in 
                     (JobStatus.PENDING, JobStatus.QUEUED))
        
        avg_progress = sum(j.to_dict()['result'].get('progress', 0) 
                         for j in self._jobs.values() 
                         if j.result) / total if total > 0 else 0.0
        
        return {
            'total_jobs': total,
            'completed': completed,
            'failed': failed,
            'pending': pending,
            'running': running,
            'progress_pct': (completed / total * 100) if total > 0 else 0.0,
            'avg_progress': avg_progress,
            'jobs': [j.to_dict() for j in self._jobs.values()]
        }
    
    async def get_job(self, job_id: str) -> Optional[ExperimentJob]:
        """Get specific job by ID.
        
        Args:
            job_id: Job ID to retrieve
            
        Returns:
            Job object or None if not found
        """
        return self._jobs.get(job_id)
    
    async def list_all_jobs(self) -> List[ExperimentJob]:
        """List all registered jobs.
        
        Returns:
            List of all jobs
        """
        return list(self._jobs.values())


# ============================================================================
# Result Aggregation
# ============================================================================


class ResultAggregator:
    """Collects and aggregates results from multiple batch jobs.
    
    Provides statistical analysis and reporting capabilities.
    """
    
    def __init__(self):
        """Initialize result aggregator."""
        self._results: Dict[str, Dict[str, Any]] = {}
        self._summaries: Dict[str, Any] = {}
    
    def add_result(self, job_id: str, result: Dict[str, Any]):
        """Add result from a job.
        
        Args:
            job_id: ID of job that produced result
            result: Result dictionary from job
        """
        self._results[job_id] = result
        self._invalidate_summaries()
    
    def get_result(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get result for specific job.
        
        Args:
            job_id: Job ID to retrieve
            
        Returns:
            Result dictionary or None
        """
        return self._results.get(job_id)
    
    def get_all_results(self) -> Dict[str, Dict[str, Any]]:
        """Get all collected results.
        
        Returns:
            Dictionary of all results keyed by job_id
        """
        return self._results.copy()
    
    def _invalidate_summaries(self):
        """Invalidate cached summaries."""
        self._summaries.clear()
    
    def compute_summary_statistics(self) -> Dict[str, Any]:
        """Compute aggregate statistics across all results.
        
        Returns:
            Dictionary of aggregated statistics
        """
        if not self._results:
            return {'count': 0, 'statistics': {}}
        
        # Extract numeric fields from results
        numeric_fields = {}
        for result in self._results.values():
            for key, value in result.items():
                if isinstance(value, (int, float)):
                    if key not in numeric_fields:
                        numeric_fields[key] = []
                    numeric_fields[key].append(value)
        
        # Calculate statistics
        statistics = {}
        for field_name, values in numeric_fields.items():
            if values:
                stats = self._compute_field_stats(field_name, values)
                statistics[field_name] = stats
        
        summary = {
            'count': len(self._results),
            'fields_analyzed': list(numeric_fields.keys()),
            'statistics': statistics,
            'generated_at': datetime.now().isoformat()
        }
        
        self._summaries['all'] = summary
        return summary
    
    def _compute_field_stats(self, field_name: str, values: List[float]) -> Dict[str, float]:
        """Compute statistics for a numeric field.
        
        Args:
            field_name: Name of the field
            values: List of numeric values
            
        Returns:
            Dictionary with statistical measures
        """
        n = len(values)
        if n == 0:
            return {}
        
        # Compute mean
        mean_val = sum(values) / n
        
        # Compute standard deviation
        variance = sum((x - mean_val) ** 2 for x in values) / n if n > 1 else 0
        std_dev = variance ** 0.5
        
        # Min and max
        min_val = min(values)
        max_val = max(values)
        
        return {
            'count': n,
            'mean': mean_val,
            'std_dev': std_dev,
            'min': min_val,
            'max': max_val,
            'sum': sum(values)
        }
    
    def export_to_json(self, output_path: str) -> Path:
        """Export all results to JSON file.
        
        Args:
            output_path: Path where to save JSON file
            
        Returns:
            Path to saved file
        """
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        export_data = {
            'exported_at': datetime.now().isoformat(),
            'total_results': len(self._results),
            'results': self._results,
            'summary_statistics': self.compute_summary_statistics()
        }
        
        with open(path, 'w') as f:
            json.dump(export_data, f, indent=2)
        
        return path


# ============================================================================
# Job Scheduler
# ============================================================================


class JobScheduler:
    """Manages job queue and concurrent execution.
    
    Handles job submission, scheduling, and resource management.
    """
    
    def __init__(self, config: BatchProcessingConfig):
        """Initialize job scheduler.
        
        Args:
            config: Batch processing configuration
        """
        self.config = config
        self._queue: asyncio.Queue = asyncio.Queue()
        self._active_tasks: Dict[str, asyncio.Task] = {}
        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(config.max_concurrent_jobs)
        self._shutdown_event = asyncio.Event()
        
        self.config.logger.info(
            f"JobScheduler initialized with max_concurrent_jobs={config.max_concurrent_jobs}"
        )
    
    async def submit(self, job: ExperimentJob):
        """Submit job to queue for processing.
        
        Args:
            job: Job to submit
        """
        await self._queue.put(job)
        self.config.logger.info(f"Job {job.job_id} submitted to queue")
    
    async def process_batch(self, jobs: List[ExperimentJob], 
                           processor_func: Callable[[ExperimentJob], asyncio.Coroutine]):
        """Process a batch of jobs concurrently.
        
        Args:
            jobs: List of jobs to process
            processor_func: Async function to execute for each job
        """
        self.config.logger.info(f"Starting batch processing of {len(jobs)} jobs")
        
        # Create tasks for all jobs
        tasks = [
            self._process_single_job(job, processor_func) 
            for job in jobs
        ]
        
        # Execute all tasks concurrently with limited concurrency
        await asyncio.gather(*tasks, return_exceptions=True)
        
        self.config.logger.info("Batch processing completed")
    
    async def _process_single_job(self, job: ExperimentJob, 
                                  processor_func: Callable[[ExperimentJob], Any]):
        """Process single job with semaphore control.
        
        Args:
            job: Job to process
            processor_func: Async function to execute
        """
        async with self._semaphore:
            try:
                # Mark as running
                job.status = JobStatus.RUNNING
                job.start_time = datetime.now()
                await self._notify(job.job_id, "running", 0.0)

                # Execute with timeout. Support both sync and async processors.
                try:
                    outcome = processor_func(job)
                    if inspect.isawaitable(outcome):
                        result = await asyncio.wait_for(
                            outcome,
                            timeout=self.config.timeout_per_experiment
                        )
                    else:
                        result = outcome

                    # Update result
                    job.result = result
                    job.status = JobStatus.COMPLETED
                    job.end_time = datetime.now()
                    await self._notify(job.job_id, "completed", 100.0)

                except asyncio.TimeoutError:
                    await self._handle_timeout(job)

            except Exception as e:
                await self._handle_error(job, str(e))

    async def _notify(self, job_id: str, status: str, pct: float):
        """Invoke the optional progress callback, tolerating sync or async callables."""
        cb = self.config.progress_callback
        if cb is None:
            return
        outcome = cb(job_id, status, pct)
        if inspect.isawaitable(outcome):
            await outcome
    
    async def _handle_timeout(self, job: ExperimentJob):
        """Handle job timeout.
        
        Args:
            job: Timing out job
        """
        error_msg = f"Job timed out after {self.config.timeout_per_experiment}s"
        
        if self.config.enable_retry and job.retry_count < self.config.retry_attempts:
            job.retry_count += 1
            if self.config.progress_callback:
                # Run callback in executor to avoid blocking event loop
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self.config.progress_callback, 
                                          job.job_id, "retrying", 0.0)
            self.config.logger.info(
                f"Job {job.job_id} timed out, retrying (attempt {job.retry_count})"
            )
            await asyncio.sleep(self.config.retry_delay)
            # Retry logic would go here
        else:
            await self.config.progress_callback(
                job.job_id, "failed", 0.0, error_msg
            )
    
    async def _handle_error(self, job: ExperimentJob, error_msg: str):
        """Handle job execution error.
        
        Args:
            job: Failed job
            error_msg: Error message
        """
        if self.config.enable_retry and job.retry_count < self.config.retry_attempts:
            job.retry_count += 1
            self.config.logger.warning(
                f"Job {job.job_id} failed with '{error_msg}', "
                f"retrying (attempt {job.retry_count})"
            )
            await asyncio.sleep(self.config.retry_delay)
        else:
            # Schedule callback on event loop (progress_callback doesn't take error_msg)
            loop = asyncio.get_event_loop()
            if self.config.progress_callback:
                await loop.run_in_executor(None, 
                    lambda: self.config.progress_callback(job.job_id, "failed", 0.0))  # type: ignore
    
    async def shutdown(self):
        """Shutdown scheduler and cancel active tasks."""
        self._shutdown_event.set()
        
        # Cancel all active tasks
        for task_id, task in self._active_tasks.items():
            if not task.done():
                task.cancel()
                self.config.logger.info(f"Cancelling task {task_id}")
        
        # Wait for cancellation
        await asyncio.gather(*self._active_tasks.values(), return_exceptions=True)
        self._active_tasks.clear()


# ============================================================================
# Main Batch Processor Manager
# ============================================================================


class BatchProcessorManager:
    """Main orchestrator for batch processing operations.
    
    Coordinates job scheduling, progress tracking, and result aggregation.
    """
    
    def __init__(self, config: BatchProcessingConfig):
        """Initialize batch processor manager.
        
        Args:
            config: Batch processing configuration
        """
        self.config = config
        self.progress_tracker = ProgressTracker(config)
        self.result_aggregator = ResultAggregator()
        self.scheduler = JobScheduler(config)
        self._processor_func: Optional[Callable] = None
        
        self.config.logger.info("BatchProcessorManager initialized")
    
    def set_processor_function(self, processor_func: Callable[[ExperimentJob], Any]):
        """Set the processor function for jobs.
        
        This function will be called for each job in the batch.
        
        Args:
            processor_func: Async function to process jobs (callable that takes ExperimentJob)
        """
        self._processor_func = processor_func  # type: ignore
        self.config.logger.info("Processor function set")
    
    async def submit_job(self, experiment_name: str, input_profile: Any,
                        measured_data: Dict[str, Any]) -> str:
        """Submit single experiment for batch processing.
        
        Args:
            experiment_name: Name for the experiment
            input_profile: Plant profile to use
            measured_data: Measured data dictionary
            
        Returns:
            Job ID for the submitted job
        """
        if not self._processor_func:
            raise RuntimeError("No processor function set")
        
        job_id = str(uuid.uuid4())
        job = ExperimentJob(
            job_id=job_id,
            experiment_name=experiment_name,
            input_profile=input_profile,
            measured_data=measured_data
        )
        
        # Register job for tracking
        await self.progress_tracker.register_job(job)
        
        # Submit to scheduler
        await self.scheduler.submit(job)
        
        self.config.logger.info(f"Job {job_id} submitted for experiment: {experiment_name}")
        return job_id
    
    async def submit_batch(
        self,
        experiments: List[Tuple[str, Any, Dict[str, Any]]]
    ) -> List[str]:
        """Submit multiple experiments as a batch.
        
        Args:
            experiments: List of (experiment_name, profile, measured_data) tuples
            
        Returns:
            List of job IDs
        """
        if not self._processor_func:
            raise RuntimeError("No processor function set")
        
        job_ids = []
        jobs = []
        
        for experiment_name, profile, measured_data in experiments:
            job_id = str(uuid.uuid4())
            job = ExperimentJob(
                job_id=job_id,
                experiment_name=experiment_name,
                input_profile=profile,
                measured_data=measured_data
            )
            
            await self.progress_tracker.register_job(job)
            jobs.append(job)
            job_ids.append(job_id)
        
        # Process batch
        await self.scheduler.process_batch(jobs, self._processor_func)
        
        # Aggregate results
        for job in jobs:
            if job.result:
                self.result_aggregator.add_result(job.job_id, job.result)
        
        self.config.logger.info(f"Batch of {len(experiments)} jobs completed")
        return job_ids
    
    async def get_job_status(self, job_id: str) -> Optional[ExperimentJob]:
        """Retrieve current status of a specific job.
        
        Args:
            job_id: Job ID to check
            
        Returns:
            Job object or None if not found
        """
        return await self.progress_tracker.get_job(job_id)
    
    async def wait_for_completion(self, job_ids: List[str], 
                                 timeout: Optional[int] = None) -> Dict[str, ExperimentJob]:
        """Wait for all jobs to complete or timeout.
        
        Args:
            job_ids: List of job IDs to wait for
            timeout: Maximum wait time in seconds (optional)
            
        Returns:
            Dictionary mapping job_id to job objects
        """
        deadline = None
        if timeout:
            deadline = asyncio.get_event_loop().time() + timeout
        
        while True:
            all_done = True
            pending_ids = []
            
            for job_id in job_ids:
                job = await self.progress_tracker.get_job(job_id)
                if job is None:
                    all_done = False
                    continue
                    
                if job.status not in (
                    JobStatus.COMPLETED, 
                    JobStatus.FAILED, 
                    JobStatus.CANCELLED
                ):
                    all_done = False
                    pending_ids.append(job_id)
            
            if all_done:
                break
            
            # Check timeout
            if deadline and asyncio.get_event_loop().time() >= deadline:
                self.config.logger.warning(
                    f"Timeout waiting for jobs: {pending_ids}"
                )
                break
            
            await asyncio.sleep(0.1)
        
        # Collect results
        results: Dict[str, ExperimentJob] = {}
        for job_id in job_ids:
            job = await self.progress_tracker.get_job(job_id)
            if job is not None:
                results[job_id] = job
        
        return results
    
    def cancel_job(self, job_id: str) -> bool:
        """Cancel a running job.
        
        Args:
            job_id: Job ID to cancel
            
        Returns:
            True if job was found and cancelled, False otherwise
        """
        try:
            asyncio.run(self.progress_tracker.cancel_job(job_id))
            self.config.logger.info(f"Job {job_id} cancelled")
            return True
        except Exception as e:
            self.config.logger.error(f"Failed to cancel job {job_id}: {e}")
            return False
    
    def get_batch_summary(self) -> Dict[str, Any]:
        """Get overall batch processing statistics.
        
        Returns:
            Summary dictionary with batch statistics
        """
        progress_summary = self.progress_tracker.get_progress_summary()
        
        # Add result aggregation info
        if self.result_aggregator._results:
            stats = self.result_aggregator.compute_summary_statistics()
            progress_summary['result_statistics'] = stats
        
        return progress_summary
    
    def export_results(self, output_path: str, format: str = "json") -> Path:
        """Export all results to file.
        
        Args:
            output_path: Output file path
            format: Export format ('json' currently supported)
            
        Returns:
            Path to exported file
        """
        if format == "json":
            return self.result_aggregator.export_to_json(output_path)
        else:
            raise ValueError(f"Unsupported export format: {format}")
    
    async def shutdown(self):
        """Shutdown the batch processor."""
        await self.scheduler.shutdown()
        self.config.logger.info("BatchProcessorManager shutdown complete")


# ============================================================================
# Helper Functions
# ============================================================================


def create_default_config(
    max_concurrent_jobs: int = 4,
    timeout_seconds: int = 300,
    retry_attempts: int = 2
) -> BatchProcessingConfig:
    """Create a default batch processing configuration.
    
    Args:
        max_concurrent_jobs: Maximum concurrent jobs
        timeout_seconds: Timeout per experiment
        retry_attempts: Number of retry attempts
        
    Returns:
        Configured BatchProcessingConfig instance
    """
    return BatchProcessingConfig(
        max_concurrent_jobs=max_concurrent_jobs,
        timeout_per_experiment=timeout_seconds,
        retry_attempts=retry_attempts
    )
