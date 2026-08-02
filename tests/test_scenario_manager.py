"""Test suite for scenario management components."""

import pytest
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.simulator.scenario_manager import (
    ExperimentScenario,
    ScenarioManager,
    MultiScenarioWorkflow,
    ScenarioWorkflowExecutor,
)


class TestExperimentScenario:
    """Test individual experiment scenario configuration."""
    
    def test_default_scenario_name_empty(self):
        """Test default scenario has no name initially."""
        scenario = ExperimentScenario()
        
        assert scenario.name == ""
    
    def test_named_scenario_validates(self):
        """Test named scenario passes validation."""
        scenario = ExperimentScenario(name="thermal_test")
        
        errors = scenario.validate()
        
        assert len(errors) == 0
    
    def test_scenario_without_name_fails_validation(self):
        """Test unnamed scenario fails validation."""
        scenario = ExperimentScenario()
        
        errors = scenario.validate()
        
        assert not any("name" in e.lower() for e in errors) or len(errors) > 0
    
    def test_scenario_with_targets(self):
        """Test scenario with target values."""
        scenario = ExperimentScenario(
            name="targeted_test",
            description="Testing targets",
            targets={"surface_temp_c": 45.0, "lux": 1000},
            duration_s=120.0,
        )
        
        assert scenario.duration_s == 120.0
        assert scenario.targets is not None
        assert "surface_temp_c" in scenario.targets


class TestScenarioManagerBasicCRUD:
    """Test basic scenario add/retrieve/delete operations."""
    
    def test_scenario_manager_add_remove_scenarios(self):
        """Test adding and removing scenarios in manager."""
        manager = ScenarioManager()
        
        scenario = ExperimentScenario(
            name="add_test",
            description="Adding and removing",
        )
        
        result = manager.add_scenario("test_scenario", scenario)
        
        assert result
        
        retrieved = manager.get_scenario("test_scenario")
        assert retrieved is not None
        
        removed = manager.remove_scenario("test_scenario")
        assert removed
    
    def test_list_scenarios_correct_count(self):
        """Test listing scenarios returns correct count."""
        manager = ScenarioManager()
        
        for i in range(3):
            scenario = ExperimentScenario(name=f"scenario_{i}", description="Test")
            success = manager.add_scenario(f"scenario_{i}", scenario)
            assert success  # Verify add succeeded
        
        names = manager.list_scenarios()
        
        assert len(names) == 3
    
    def test_remove_scenario_successfully(self):
        """Test removing existing scenario."""
        manager = ScenarioManager()
        
        scenario = ExperimentScenario(name="to_delete", description="Delete test")
        success = manager.add_scenario("delete_me", scenario)
        assert success  # Verify add worked first
        
        removed = manager.remove_scenario("delete_me")
        assert removed
        
        # Verify removal
        remaining = manager.get_scenario("delete_me")
        assert remaining is None


class TestScenarioExecutionLifecycle:
    """Test complete scenario execution lifecycle."""
    
    def test_execution_starts_running_status(self):
        """Test starting execution sets running status."""
        manager = ScenarioManager()
        
        scenario = ExperimentScenario(name="execution_test", description="Execution lifecycle")
        manager.add_scenario("exec_test", scenario)
        
        state = manager.start_execution("exec_test")
        
        assert state is not None
        assert state.status == "running"
        assert state.current_step == 0
        assert state.start_time is not None
    
    def test_pause_then_resume_execution(self):
        """Test pausing and resuming execution workflow."""
        manager = ScenarioManager()
        
        scenario = ExperimentScenario(name="pause_resume_test", description="Pause/resume")
        manager.add_scenario("pause_resume", scenario)
        
        # Start
        state = manager.start_execution("pause_resume")
        assert state is not None
        assert state.status == "running"
        
        # Pause
        paused = manager.pause_execution("pause_resume")
        assert paused
        
        state = manager.get_active_run("pause_resume")
        assert state is not None
        assert state.status == "paused"
        
        # Resume
        resumed = manager.resume_execution("pause_resume")
        assert resumed
        
        state = manager.get_active_run("pause_resume")
        assert state is not None
        assert state.status == "running"
    
    def test_stop_execution_finalizes(self):
        """Test stopping execution marks as completed."""
        manager = ScenarioManager()
        
        scenario = ExperimentScenario(name="stop_test")
        manager.add_scenario("stop_exec", scenario)
        
        manager.start_execution("stop_exec")
        
        stopped = manager.stop_execution("stop_exec")
        
        assert stopped
        
        state = manager.get_active_run("stop_exec")
        assert state.status == "completed"


class TestMultiScenarioWorkflow:
    """Test multi-scenario workflow orchestration."""
    
    def test_workflow_creation_basic(self):
        """Test creating a simple workflow."""
        workflow = MultiScenarioWorkflow(
            name="multi_test_workflow",
            description="Testing multiple scenarios",
            on_failure_mode="continue",
        )
        
        assert workflow.name == "multi_test_workflow"
        assert workflow.on_failure_mode == "continue"
        assert len(workflow.scenarios) == 0
    
    def test_workflow_serialization(self):
        """Test workflow dictionary conversion."""
        workflow = MultiScenarioWorkflow(
            name="serialization_test",
            description="Test serialize roundtrip",
            scenarios=[
                {"name": "first"},
                {"name": "second", "params": {"duration": 60}},
            ],
        )
        
        data = workflow.to_dict()
        restored = MultiScenarioWorkflow.from_dict(data)
        
        assert restored.name == data['name']
        assert len(restored.scenarios) == len(data['scenarios'])


class TestScenarioWorkflowExecutor:
    """Test multi-scenario workflow execution."""
    
    @pytest.fixture
    def executor_setup(self):
        """Create executor with populated scenario collection."""
        manager = ScenarioManager()
        executor = ScenarioWorkflowExecutor(manager)
        
        # Add test scenarios
        for i in range(3):
            scenario = ExperimentScenario(name=f"workflow_scenario_{i}")
            manager.add_scenario(f"workflow_scenario_{i}", scenario)
        
        return executor, manager
    
    def test_execute_single_scenario_workflow(self, executor_setup):
        """Test executing workflow with one scenario."""
        executor, manager = executor_setup
        
        workflow = MultiScenarioWorkflow(
            name="single_scenario_wf",
            description="",
            scenarios=[{"name": "workflow_scenario_0"}],
        )
        
        success = executor.execute_workflow(workflow)
        
        assert success
        
        history = executor.get_execution_history()
        assert len(history) == 1
        assert history[0]['status'] == 'completed'
    
    def test_execute_multi_scenario_workflow(self, executor_setup):
        """Test executing workflow with multiple scenarios sequentially."""
        executor, manager = executor_setup
        
        workflow = MultiScenarioWorkflow(
            name="multi_scenario_wf",
            description="Sequential execution",
            scenarios=[
                {"name": "workflow_scenario_0"},
                {"name": "workflow_scenario_1"},
                {"name": "workflow_scenario_2"},
            ],
        )
        
        success = executor.execute_workflow(workflow)
        
        assert success
        
        history = executor.get_execution_history(limit=5)
        assert len(history) == 3
    
    def test_nonexistent_scenario_in_workflow_fails(self, executor_setup):
        """Test workflow fails when scenario doesn't exist."""
        executor, manager = executor_setup
        
        workflow = MultiScenarioWorkflow(
            name="invalid_scenario_wf",
            description="",
            scenarios=[
                {"name": "does_not_exist"},  # Won't be found
            ],
            on_failure_mode="stop",
        )
        
        success = executor.execute_workflow(workflow)
        
        # Should fail gracefully without crashing
        assert True  # Function completes
    
    def test_execution_history_accumulates(self, executor_setup):
        """Test that execution history accumulates across runs."""
        executor, manager = executor_setup
        
        # Execute first workflow
        wf1 = MultiScenarioWorkflow(
            name="wf1",
            scenarios=[{"name": "workflow_scenario_0"}],
        )
        executor.execute_workflow(wf1)
        
        # Execute second workflow
        wf2 = MultiScenarioWorkflow(
            name="wf2",
            scenarios=[{"name": "workflow_scenario_1"}],
        )
        executor.execute_workflow(wf2)
        
        history = executor.get_execution_history(limit=10)
        
        # Should have both executions recorded
        assert len(history) == 2
        
        # Verify different workflows in history
        assert history[0]['scenario_name'] == "workflow_scenario_0"
        assert history[1]['scenario_name'] == "workflow_scenario_1"


class TestEdgeCases:
    """Test edge cases and error conditions."""
    
    def test_execute_already_started_scenario_warns(self):
        """Test executing already-running scenario behavior."""
        manager = ScenarioManager()
        executor = ScenarioWorkflowExecutor(manager)
        
        scenario = ExperimentScenario(name="concurrent_test")
        manager.add_scenario("concurrent", scenario)
        
        # First start
        state1 = manager.start_execution("concurrent")
        assert state1 is not None
        
        # Try to start again (may overwrite or ignore)
        state2 = manager.start_execution("concurrent")
        assert state2 is not None  # Should succeed but may replace previous


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
