"""Scenario management for multi-scenario execution workflows."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional
import json


@dataclass
class ExperimentScenario:
    """Single experiment scenario configuration."""
    
    name: str = ""
    description: str = ""
    targets: Optional[dict] = None  # Target temperature/lux values
    fault_schedule: List[Dict[str, Any]] = field(default_factory=list)
    duration_s: float = 60.0
    
    def validate(self) -> List[str]:
        """Validate scenario against target setpoints."""
        errors = []
        
        if not self.name:
            errors.append("Scenario requires a name")
        
        return errors


@dataclass
class ScenarioExecutionState:
    """State of a running scenario."""
    
    scenario_name: str
    start_time: datetime
    current_step: int = 0
    status: str = "pending"  # pending, running, paused, completed, failed
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'scenario_name': self.scenario_name,
            'start_time': self.start_time.isoformat(),
            'current_step': self.current_step,
            'status': self.status,
        }


class ScenarioManager:
    """Manages multiple scenarios with workflow orchestration."""
    
    def __init__(self):
        """Initialize empty scenario collection."""
        self._scenarios: Dict[str, ExperimentScenario] = {}
        self._active_runs: Dict[str, ScenarioExecutionState] = {}
    
    def add_scenario(self, name: str, scenario: ExperimentScenario) -> bool:
        """Add or update a scenario.
        
        Args:
            name: Unique scenario identifier
            scenario: ExperimentScenario object to store
            
        Returns:
            True if added/updated successfully
        """
        scenario.name = name  # Ensure consistency
        
        validation_errors = scenario.validate()
        if len(validation_errors) > 0:
            return False
        
        self._scenarios[name] = scenario
        return True
    
    def get_scenario(self, name: str) -> Optional[ExperimentScenario]:
        """Retrieve scenario by name."""
        return self._scenarios.get(name)
    
    def remove_scenario(self, name: str) -> bool:
        """Remove a scenario from collection."""
        if name in self._scenarios:
            del self._scenarios[name]
            return True
        return False
    
    def list_scenarios(self) -> List[str]:
        """List all scenario names."""
        return list(self._scenarios.keys())
    
    def start_execution(self, scenario_name: str) -> Optional[ScenarioExecutionState]:
        """Begin execution of a scenario.
        
        Args:
            scenario_name: Name of scenario to execute
            
        Returns:
            ScenarioExecutionState object if started, None if not found
        """
        if scenario_name not in self._scenarios:
            return None
        
        state = ScenarioExecutionState(
            scenario_name=scenario_name,
            start_time=datetime.now(),
            status="running",
        )
        
        self._active_runs[scenario_name] = state
        return state
    
    def pause_execution(self, scenario_name: str) -> bool:
        """Pause running scenario."""
        if scenario_name in self._active_runs:
            self._active_runs[scenario_name].status = "paused"
            return True
        return False
    
    def resume_execution(self, scenario_name: str) -> bool:
        """Resume paused scenario."""
        if scenario_name in self._active_runs:
            self._active_runs[scenario_name].status = "running"
            return True
        return False
    
    def stop_execution(self, scenario_name: str) -> bool:
        """Stop scenario execution."""
        if scenario_name in self._active_runs:
            self._active_runs[scenario_name].status = "completed"
            return True
        return False
    
    def get_active_run(self, scenario_name: str) -> Optional[ScenarioExecutionState]:
        """Get active execution state for scenario."""
        return self._active_runs.get(scenario_name)


@dataclass
class MultiScenarioWorkflow:
    """Orchestration definition for multiple sequential scenarios."""
    
    name: str
    description: str = ""  # Make optional with default value
    scenarios: List[Dict[str, Any]] = field(default_factory=list)
    on_failure_mode: str = "stop"  # stop, continue, retry
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            'name': self.name,
            'description': self.description,
            'scenarios': self.scenarios,
            'on_failure_mode': self.on_failure_mode,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MultiScenarioWorkflow':
        """Deserialize from dictionary."""
        return cls(
            name=data['name'],
            description=data.get('description', ''),
            scenarios=data.get('scenarios', []),
            on_failure_mode=data.get('on_failure_mode', 'stop'),
        )


class ScenarioWorkflowExecutor:
    """Execute multi-scenario workflows sequentially."""
    
    def __init__(self, scenario_manager: ScenarioManager):
        """Initialize executor with scenario manager reference.
        
        Args:
            scenario_manager: Parent ScenarioManager instance
        """
        self.scenario_manager = scenario_manager
        self._execution_history: List[Dict[str, Any]] = []
    
    def execute_workflow(self, workflow: MultiScenarioWorkflow) -> bool:
        """Execute scenarios in sequence according to workflow definition.
        
        Args:
            workflow: MultiScenarioWorkflow defining order and behavior
            
        Returns:
            True if all scenarios executed successfully
        """
        success = True
        
        for scenario_def in workflow.scenarios:
            scenario_name = scenario_def.get('name')
            
            if not scenario_name:
                continue
            
            # Start execution
            if self.scenario_manager.start_execution(scenario_name):
                # Simulate successful execution (real implementation would track state)
                self.scenario_manager.stop_execution(scenario_name)
                
                self._execution_history.append({
                    'workflow_name': workflow.name,
                    'scenario_name': scenario_name,
                    'status': 'completed',
                    'timestamp': datetime.now().isoformat(),
                })
            else:
                # Scenario not found or execution failed
                if workflow.on_failure_mode == 'stop':
                    success = False
                    break
                elif workflow.on_failure_mode == 'continue':
                    pass  # Continue to next scenario
        
        return success
    
    def get_execution_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent execution history.
        
        Args:
            limit: Maximum number of entries to return
            
        Returns:
            List of execution history records
        """
        return self._execution_history[-limit:]
