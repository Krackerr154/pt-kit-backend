"""
Comprehensive tests for the Batch Processing Manager.

Tests cover:
- Job lifecycle management
- Progress tracking
- Result aggregation
- Concurrent execution
- Error handling and retry logic
- Export functionality
"""

import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.simulator.batch_processor import (
    BatchProcessingConfig,
    ExperimentJob,
    JobStatus,
    ProgressTracker,
    ResultAggregator,
    BatchProcessorManager,
)


# ============================================================================
# Test Fixtures
# ============================================================================


def create_test_job(job_id: str = "test-job", name: str = "Test") -> ExperimentJob:
    """Create a test experiment job."""
    return ExperimentJob(
        job_id=job_id,
        experiment_name=name,
        input_profile=None,  # Using None for testing
        measured_data={"sensor1": [1.0, 2.0, 3.0], "sensor2": [4.0, 5.0]}
    )


async def async_process_job(job: ExperimentJob):
    """Simulated async processor function for testing."""
    await asyncio.sleep(0.1)  # Simulate processing time
    
    job.result = {
        "success": True,
        "metrics": {"rmse": 0.05, "mae": 0.03, "r_squared": 0.98},
        "progress": 100.0,
        "processed_at": datetime.now().isoformat()
    }
    
    return job.result


# ============================================================================
# BatchProcessingConfig Tests
# ============================================================================


class TestBatchProcessingConfig:
    """Tests for BatchProcessingConfig dataclass."""
    
    def test_default_config(self):
        """Test default configuration values."""
        config = BatchProcessingConfig()
        
        assert config.max_concurrent_jobs == 4
        assert config.timeout_per_experiment == 300
        assert config.retry_attempts == 2
        assert config.log_level == "INFO"
        assert config.progress_callback is None
        assert config.enable_retry is True
        assert config.retry_delay == 5
    
    def test_custom_config(self):
        """Test custom configuration values."""
        config = BatchProcessingConfig(
            max_concurrent_jobs=8,
            timeout_per_experiment=600,
            retry_attempts=3,
            log_level="DEBUG"
        )
        
        assert config.max_concurrent_jobs == 8
        assert config.timeout_per_experiment == 600
        assert config.retry_attempts == 3
        assert config.log_level == "DEBUG"
    
    def test_invalid_max_concurrent(self):
        """Test validation of max_concurrent_jobs."""
        try:
            BatchProcessingConfig(max_concurrent_jobs=0)
            assert False, "Should raise ValueError"
        except ValueError as e:
            assert "at least 1" in str(e)
    
    def test_invalid_timeout(self):
        """Test validation of timeout value."""
        try:
            BatchProcessingConfig(timeout_per_experiment=0)
            assert False, "Should raise ValueError"
        except ValueError as e:
            assert "positive" in str(e)
    
    def test_invalid_retries(self):
        """Test validation of retry attempts."""
        try:
            BatchProcessingConfig(retry_attempts=-1)
            assert False, "Should raise ValueError"
        except ValueError as e:
            assert "negative" in str(e)


# ============================================================================
# ExperimentJob Tests
# ============================================================================


class TestExperimentJob:
    """Tests for ExperimentJob dataclass."""
    
    def test_job_creation(self):
        """Test job creation with required fields."""
        job = create_test_job()
        
        assert job.job_id == "test-job"
        assert job.experiment_name == "Test"
        assert job.status == JobStatus.PENDING
        assert job.retry_count == 0
        assert job.created_at is not None
        assert job.updated_at is not None
    
    def test_status_update_to_running(self):
        """Test updating job status to running."""
        job = create_test_job()
        initial_time = job.start_time
        
        job.update_status(JobStatus.RUNNING)
        
        assert job.status == JobStatus.RUNNING
        assert job.start_time is not None
        assert job.end_time is None
    
    def test_status_update_to_completed(self):
        """Test updating job status to completed."""
        job = create_test_job()
        
        job.update_status(JobStatus.RUNNING)
        job.update_status(JobStatus.COMPLETED)
        
        assert job.status == JobStatus.COMPLETED
        assert job.start_time is not None
        assert job.end_time is not None
        assert job.end_time >= job.start_time
    
    def test_status_update_with_error(self):
        """Test updating job status with error message."""
        job = create_test_job()
        error_msg = "Connection timeout"
        
        job.update_status(JobStatus.FAILED, error_msg)
        
        assert job.status == JobStatus.FAILED
        assert job.error_message == error_msg
    
    def test_to_dict_serialization(self):
        """Test job serialization to dictionary."""
        job = create_test_job()
        job.update_status(JobStatus.COMPLETED)
        
        job_dict = job.to_dict()
        
        assert job_dict["job_id"] == "test-job"
        assert job_dict["status"] == "completed"
        assert job_dict["experiment_name"] == "Test"
        assert "created_at" in job_dict
        assert "updated_at" in job_dict


# ============================================================================
# ProgressTracker Tests
# ============================================================================


class TestProgressTracker:
    """Tests for ProgressTracker class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.config = BatchProcessingConfig(progress_callback=None)
        self.tracker = ProgressTracker(self.config)
    
    async def test_register_job(self):
        """Test job registration."""
        job = create_test_job()
        
        await self.tracker.register_job(job)
        
        retrieved_job = await self.tracker.get_job(job.job_id)
        assert retrieved_job is not None
        assert retrieved_job.job_id == job.job_id
    
    async def test_update_job_status(self):
        """Test updating job status through tracker."""
        job = create_test_job()
        await self.tracker.register_job(job)
        
        await self.tracker.mark_running(job.job_id, 10.0)
        
        updated_job = await self.tracker.get_job(job.job_id)
        assert updated_job is not None, "Job should exist after registering"
        assert updated_job.status == JobStatus.RUNNING
        
        await self.tracker.mark_completed(job.job_id, 100.0)
        
        updated_job = await self.tracker.get_job(job.job_id)
        assert updated_job is not None, "Job should still exist"
        assert updated_job.status == JobStatus.COMPLETED
    
    async def test_mark_failed(self):
        """Test marking job as failed."""
        job = create_test_job()
        await self.tracker.register_job(job)
        
        await self.tracker.mark_failed(job.job_id, "Test error", 50.0)
        
        updated_job = await self.tracker.get_job(job.job_id)
        assert updated_job is not None, "Job should exist"
        assert updated_job.status == JobStatus.FAILED
        assert updated_job.error_message == "Test error"
    
    async def test_cancel_job(self):
        """Test cancelling a job."""
        job = create_test_job()
        await self.tracker.register_job(job)
        
        await self.tracker.cancel_job(job.job_id)
        
        updated_job = await self.tracker.get_job(job.job_id)
        assert updated_job is not None, "Job should exist"
        assert updated_job.status == JobStatus.CANCELLED
    
    async def test_progress_summary(self):
        """Test progress summary generation."""
        # Create multiple jobs in different states
        job1 = create_test_job("job1", "Completed")
        job2 = create_test_job("job2", "Running")
        job3 = create_test_job("job3", "Failed")
        
        await self.tracker.register_job(job1)
        await self.tracker.register_job(job2)
        await self.tracker.register_job(job3)
        
        await self.tracker.mark_completed(job1.job_id, 100.0)
        await self.tracker.mark_running(job2.job_id, 50.0)
        await self.tracker.mark_failed(job3.job_id, "Error", 0.0)
        
        summary = self.tracker.get_progress_summary()
        
        assert summary["total_jobs"] == 3
        assert summary["completed"] == 1
        assert summary["running"] == 1
        assert summary["failed"] == 1
        assert summary["pending"] == 0
        assert abs(summary["progress_pct"] - 33.33) < 0.01
    
    async def test_get_all_jobs(self):
        """Test listing all registered jobs."""
        await self.tracker.register_job(create_test_job("j1"))
        await self.tracker.register_job(create_test_job("j2"))
        await self.tracker.register_job(create_test_job("j3"))
        
        all_jobs = await self.tracker.list_all_jobs()
        
        assert len(all_jobs) == 3
        job_ids = [j.job_id for j in all_jobs]
        assert "j1" in job_ids
        assert "j2" in job_ids
        assert "j3" in job_ids


# ============================================================================
# ResultAggregator Tests
# ============================================================================


class TestResultAggregator:
    """Tests for ResultAggregator class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.aggregator = ResultAggregator()
    
    def test_add_and_get_result(self):
        """Test adding and retrieving results."""
        result1 = {"metric1": 0.95, "processing_time": 1.2}
        result2 = {"metric1": 0.92, "processing_time": 1.5}
        
        self.aggregator.add_result("job1", result1)
        self.aggregator.add_result("job2", result2)
        
        assert self.aggregator.get_result("job1") == result1
        assert self.aggregator.get_result("job2") == result2
    
    def test_get_all_results(self):
        """Test retrieving all results at once."""
        results = {
            "job1": {"value": 10},
            "job2": {"value": 20},
            "job3": {"value": 30},
        }
        
        for job_id, result in results.items():
            self.aggregator.add_result(job_id, result)
        
        all_results = self.aggregator.get_all_results()
        
        assert len(all_results) == 3
        assert all(k in all_results for k in results.keys())
    
    def test_compute_statistics(self):
        """Test computation of aggregate statistics."""
        results = [
            {"rmse": 0.1, "score": 0.9},
            {"rmse": 0.2, "score": 0.8},
            {"rmse": 0.3, "score": 0.7},
        ]
        
        for i, result in enumerate(results):
            self.aggregator.add_result(f"job{i}", result)
        
        stats = self.aggregator.compute_summary_statistics()
        
        assert stats["count"] == 3
        assert "rmse" in stats["statistics"]
        assert "score" in stats["statistics"]
        
        rmse_stats = stats["statistics"]["rmse"]
        assert rmse_stats["mean"] == 0.2
        assert rmse_stats["min"] == 0.1
        assert rmse_stats["max"] == 0.3
        assert rmse_stats["sum"] == 0.6
    
    def test_empty_aggregation(self):
        """Test statistics calculation with no results."""
        stats = self.aggregator.compute_summary_statistics()
        
        assert stats["count"] == 0
        assert stats["statistics"] == {}
    
    def test_export_to_json(self):
        """Test exporting results to JSON file."""
        result = {"metric": 0.95, "time": 1.2}
        self.aggregator.add_result("test-job", result)
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            temp_path = f.name
        
        try:
            export_path = self.aggregator.export_to_json(temp_path)
            
            assert export_path.exists()
            
            with open(export_path) as f:
                exported_data = json.load(f)
            
            assert "exported_at" in exported_data
            assert exported_data["total_results"] == 1
            assert "test-job" in exported_data["results"]
            assert exported_data["results"]["test-job"] == result
            
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)


# ============================================================================
# BatchProcessorManager Integration Tests
# ============================================================================


class TestBatchProcessorManager:
    """Integration tests for BatchProcessorManager."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.config = BatchProcessingConfig(
            max_concurrent_jobs=2,
            timeout_per_experiment=10,
            retry_attempts=1,
            log_level="WARNING"
        )
        self.manager = BatchProcessorManager(self.config)
        self.manager.set_processor_function(async_process_job)
    
    def test_single_job_submission(self):
        """Test submitting a single job."""
        async def run_test():
            job_id = await self.manager.submit_job(
                experiment_name="Single Job Test",
                input_profile=None,
                measured_data={"data": [1, 2, 3]}
            )
            
            assert job_id is not None
            assert isinstance(job_id, str)
            assert len(job_id) > 0
            
            status = await self.manager.get_job_status(job_id)
            assert status is not None
            assert status.experiment_name == "Single Job Test"
            
        asyncio.run(run_test())
    
    def test_batch_submission(self):
        """Test submitting multiple jobs as a batch."""
        async def run_test():
            experiments = [
                ("Exp1", None, {"data": [1]}),
                ("Exp2", None, {"data": [2]}),
                ("Exp3", None, {"data": [3]}),
            ]
            
            job_ids = await self.manager.submit_batch(experiments)
            
            assert len(job_ids) == 3
            assert all(isinstance(jid, str) for jid in job_ids)
            
            # Wait for completion
            results = await self.manager.wait_for_completion(job_ids, timeout=30)
            
            assert len(results) == 3
            for job_id, job in results.items():
                assert job.status == JobStatus.COMPLETED
                assert job.result is not None
                
        asyncio.run(run_test())
    
    def test_wait_for_completion(self):
        """Test waiting for batch completion with timeout."""
        async def run_test():
            experiments = [
                ("Exp1", None, {"data": [1]}),
            ]
            
            job_ids = await self.manager.submit_batch(experiments)
            
            # Wait with reasonable timeout
            results = await self.manager.wait_for_completion(job_ids, timeout=10)
            
            assert len(results) == 1
            job = results[job_ids[0]]
            assert job.status == JobStatus.COMPLETED
            
        asyncio.run(run_test())
    
    def test_batch_summary(self):
        """Test getting batch summary statistics."""
        async def run_test():
            experiments = [
                ("Exp1", None, {"data": [1]}),
                ("Exp2", None, {"data": [2]}),
            ]
            
            job_ids = await self.manager.submit_batch(experiments)
            
            summary = self.manager.get_batch_summary()
            
            assert summary["total_jobs"] == 2
            assert "completed" in summary
            assert "failed" in summary
            assert "progress_pct" in summary
            
        asyncio.run(run_test())
    
    def test_shutdown(self):
        """Test graceful shutdown."""
        async def run_test():
            await self.manager.shutdown()
            
        asyncio.run(run_test())


# ============================================================================
# Concurrent Execution Tests
# ============================================================================


class TestConcurrentExecution:
    """Tests for concurrent job execution."""
    
    async def test_sequential_processing_order(self):
        """Test that jobs are processed in submission order."""
        config = BatchProcessingConfig(max_concurrent_jobs=1, log_level="WARNING")
        manager = BatchProcessorManager(config)
        manager.set_processor_function(async_process_job)
        
        job_ids = []
        completion_order = []
        
        def track_completion(job_id, status, progress):
            if status == "completed":
                completion_order.append(job_id)
        
        config.progress_callback = track_completion
        
        async def run_test():
            # Submit jobs sequentially
            for i in range(3):
                job_id = await manager.submit_job(
                    experiment_name=f"Job{i}",
                    input_profile=None,
                    measured_data={"seq": i}
                )
                job_ids.append(job_id)
            
            # Wait for completion
            await manager.wait_for_completion(job_ids, timeout=30)
            
            # Verify order
            assert completion_order == job_ids, f"Expected {job_ids}, got {completion_order}"
            
            await manager.shutdown()
        
        asyncio.run(run_test())
    
    async def test_parallel_processing_limited_by_semaphore(self):
        """Test that concurrent jobs respect semaphore limit."""
        config = BatchProcessingConfig(max_concurrent_jobs=2, log_level="WARNING")
        
        active_count = 0
        max_active = 0
        
        async def counting_processor(job):
            nonlocal active_count, max_active
            active_count += 1
            max_active = max(max_active, active_count)
            await asyncio.sleep(0.05)
            active_count -= 1
            return {"status": "done"}
        
        manager = BatchProcessorManager(config)
        manager.set_processor_function(counting_processor)
        
        async def run_test():
            experiments = [
                (f"Exp{i}", None, {"i": i})
                for i in range(4)
            ]
            
            await manager.submit_batch(experiments)
            
            # Max concurrent should never exceed 2
            assert max_active <= 2, f"Max active was {max_active}, exceeded limit of 2"
            
            await manager.shutdown()
        
        asyncio.run(run_test())


# ============================================================================
# Retry Logic Tests
# ============================================================================


class TestRetryLogic:
    """Tests for automatic retry functionality."""
    
    async def test_successful_retry_on_failure(self):
        """Test that retries occur on temporary failures."""
        config = BatchProcessingConfig(
            max_concurrent_jobs=1,
            retry_attempts=2,
            retry_delay=0,
            log_level="WARNING"
        )
        
        failure_count = 0
        success_after_retries = False
        
        async def flaky_processor(job):
            nonlocal failure_count, success_after_retries
            failure_count += 1
            
            if failure_count < 2:
                raise Exception("Transient error")
            
            job.result = {"success": True}
            success_after_retries = True
            return job.result
        
        manager = BatchProcessorManager(config)
        manager.set_processor_function(flaky_processor)
        
        async def run_test():
            job_id = await manager.submit_job(
                experiment_name="Flaky Job",
                input_profile=None,
                measured_data={}
            )
            
            await manager.wait_for_completion([job_id], timeout=10)
            
            job = await manager.get_job_status(job_id)
            
            # Should have succeeded after retry
            assert success_after_retries is True
            assert failure_count == 2
            
            await manager.shutdown()
        
        asyncio.run(run_test())


# ============================================================================
# Main Test Runner
# ============================================================================


def run_all_tests():
    """Run all test classes."""
    print("=" * 60)
    print("Running Batch Processor Tests")
    print("=" * 60)
    
    test_classes = [
        TestBatchProcessingConfig,
        TestExperimentJob,
        TestProgressTracker,
        TestResultAggregator,
        TestBatchProcessorManager,
        TestConcurrentExecution,
        TestRetryLogic,
    ]
    
    passed = 0
    failed = 0
    errors = []
    
    for test_class in test_classes:
        print(f"\n{test_class.__name__}:")
        instance = test_class()
        
        # Setup
        if hasattr(instance, 'setup_method'):
            instance.setup_method()
        
        # Run tests
        for method_name in dir(instance):
            if method_name.startswith('test_'):
                try:
                    method = getattr(instance, method_name)
                    
                    if asyncio.iscoroutinefunction(method):
                        asyncio.run(method())
                    else:
                        method()
                    
                    print(f"  ✓ {method_name}")
                    passed += 1
                    
                except Exception as e:
                    print(f"  ✗ {method_name}: {str(e)}")
                    errors.append((test_class.__name__, method_name, e))
                    failed += 1
    
    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    if errors:
        print("\nErrors:")
        for class_name, method_name, error in errors:
            print(f"  {class_name}.{method_name}: {error}")
        sys.exit(1)
    else:
        print("\n✅ All tests passed successfully!")
        sys.exit(0)


if __name__ == "__main__":
    run_all_tests()
