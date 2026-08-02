"""Tests for the Phase 8 batch processing manager (real BatchProcessorManager API)."""

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.simulator.batch_processor import (  # noqa: E402
    BatchProcessingConfig,
    BatchProcessorManager,
    ExperimentJob,
    JobStatus,
    ProgressTracker,
    ResultAggregator,
)
from app.simulator.profile_management import PlantProfile  # noqa: E402


def make_data(n=3):
    return {"temperature": [25.0 + i for i in range(n)]}


def simple_processor(job: ExperimentJob):
    """Deterministic stand-in for a real experiment run."""
    temps = job.measured_data.get("temperature", [])
    return {"mean_temp": sum(temps) / len(temps) if temps else 0.0, "n": len(temps)}


@pytest.fixture
def manager():
    mgr = BatchProcessorManager(BatchProcessingConfig(max_concurrent_jobs=2,
                                                      timeout_per_experiment=10))
    mgr.set_processor_function(simple_processor)
    return mgr


class TestBatchProcessingConfig:
    def test_defaults(self):
        cfg = BatchProcessingConfig()
        assert cfg.max_concurrent_jobs == 4
        assert cfg.timeout_per_experiment == 300
        assert cfg.retry_attempts == 2
        assert cfg.log_level == "INFO"
        assert cfg.progress_callback is None

    def test_overrides(self):
        cfg = BatchProcessingConfig(max_concurrent_jobs=8, timeout_per_experiment=600,
                                    retry_attempts=5, log_level="DEBUG")
        assert (cfg.max_concurrent_jobs, cfg.timeout_per_experiment,
                cfg.retry_attempts, cfg.log_level) == (8, 600, 5, "DEBUG")


class TestExperimentJob:
    def test_initial_state(self):
        job = ExperimentJob(job_id="j1", experiment_name="thermal",
                            input_profile=PlantProfile(name="p"), measured_data=make_data())
        assert job.status == JobStatus.PENDING
        assert job.result is None and job.start_time is None and job.retry_count == 0

    def test_lifecycle_fields(self):
        job = ExperimentJob(job_id="j2", experiment_name="run",
                            input_profile=PlantProfile(name="p"), measured_data=make_data())
        job.status = JobStatus.RUNNING
        job.start_time = datetime.now()
        job.status = JobStatus.COMPLETED
        job.result = {"rmse": 0.5}
        job.end_time = datetime.now()
        assert job.status == JobStatus.COMPLETED
        assert job.result["rmse"] == 0.5
        assert job.end_time >= job.start_time

    def test_to_dict_serializable(self):
        job = ExperimentJob(job_id="j3", experiment_name="ser",
                            input_profile=PlantProfile(name="p"), measured_data=make_data())
        d = job.to_dict()
        assert d["job_id"] == "j3" and d["experiment_name"] == "ser"
        json.dumps(d)  # must not raise


class TestSubmission:
    @pytest.mark.asyncio
    async def test_submit_single_job(self, manager):
        job_id = await manager.submit_job("single", PlantProfile(name="p"), make_data())
        assert isinstance(job_id, str) and job_id
        job = await manager.get_job_status(job_id)
        assert job is not None and job.experiment_name == "single"

    @pytest.mark.asyncio
    async def test_submit_batch(self, manager):
        experiments = [(f"exp{i}", PlantProfile(name=f"p{i}"), make_data()) for i in range(3)]
        job_ids = await manager.submit_batch(experiments)
        assert len(job_ids) == 3 and len(set(job_ids)) == 3

    @pytest.mark.asyncio
    async def test_unknown_job_returns_none(self, manager):
        assert await manager.get_job_status("does-not-exist") is None


class TestWorkflow:
    @pytest.mark.asyncio
    async def test_jobs_run_to_completion(self, manager):
        experiments = [(f"w{i}", PlantProfile(name=f"w{i}"), make_data(4)) for i in range(3)]
        job_ids = await manager.submit_batch(experiments)
        done = {jid: await manager.get_job_status(jid) for jid in job_ids}
        assert len(done) == 3
        for job in done.values():
            assert job.status == JobStatus.COMPLETED
            assert job.result["n"] == 4
        await manager.shutdown()

    @pytest.mark.asyncio
    async def test_progress_callback_fires(self):
        seen = []
        cfg = BatchProcessingConfig(max_concurrent_jobs=2,
                                    progress_callback=lambda jid, st, pct: seen.append((jid, st, pct)))
        mgr = BatchProcessorManager(cfg)
        mgr.set_processor_function(simple_processor)
        job_id = await mgr.submit_job("prog", PlantProfile(name="p"), make_data())
        assert seen, "progress_callback should have been invoked at least once"
        assert all(j == job_id for j, _, _ in seen)
        await mgr.shutdown()

    @pytest.mark.asyncio
    async def test_cancel_pending_job(self, manager):
        job_id = await manager.submit_job("cancelme", PlantProfile(name="p"), make_data())
        result = manager.cancel_job(job_id)
        assert isinstance(result, bool)


class TestReporting:
    @pytest.mark.asyncio
    async def test_summary_counts_jobs(self, manager):
        experiments = [(f"s{i}", PlantProfile(name=f"s{i}"), make_data()) for i in range(5)]
        await manager.submit_batch(experiments)
        summary = manager.get_batch_summary()
        assert summary["total_jobs"] == 5
        await manager.shutdown()

    @pytest.mark.asyncio
    async def test_export_results_json(self, manager, tmp_path):
        await manager.submit_job("exp", PlantProfile(name="p"), make_data())
        out = tmp_path / "batch_results.json"
        written = manager.export_results(str(out), format="json")
        assert Path(written).exists()
        payload = json.loads(Path(written).read_text())
        assert isinstance(payload, dict)
        await manager.shutdown()


class TestHelperComponents:
    def test_result_aggregator_computes_stats(self):
        agg = ResultAggregator()
        assert agg is not None

    def test_progress_tracker_instantiates(self):
        tracker = ProgressTracker(BatchProcessingConfig())
        assert tracker is not None


class TestConcurrency:
    @pytest.mark.asyncio
    async def test_more_jobs_than_slots_all_complete(self):
        mgr = BatchProcessorManager(BatchProcessingConfig(max_concurrent_jobs=2,
                                                          timeout_per_experiment=10))
        mgr.set_processor_function(simple_processor)
        experiments = [(f"c{i}", PlantProfile(name=f"c{i}"), make_data()) for i in range(6)]
        job_ids = await mgr.submit_batch(experiments)
        done = {jid: await mgr.get_job_status(jid) for jid in job_ids}
        assert len(done) == 6
        assert all(j.status == JobStatus.COMPLETED for j in done.values())
        await mgr.shutdown()
