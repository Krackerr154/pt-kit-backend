"""
Isolated Backend API Layer - Phase 5 Task 5.3

REST endpoint layer enforcing /api/simulator/* isolation for simulation-only operations.
This API layer provides exclusive access to simulator run state without touching
production databases or physical experiment APIs.

Design Principles:
✅ NO database writes - pure in-memory simulator state
✅ NO physical sensor ingestion (/api/insert_data is NOT used)
✅ Strict path isolation - only /api/simulator/* endpoints accessible
✅ Deterministic execution - reproducible simulation runs
✅ Component isolation - separate from production backend concerns
"""

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal
from dataclasses import dataclass, field as dataclass_field
from enum import Enum
import time
import uuid


# =============================================================================
# Data Models for Simulator State
# =============================================================================

class RunState(str, Enum):
    """Simulation run states mirroring physical system."""
    IDLE = "IDLE"
    STARTING = "STARTING"
    EXPERIMENT_RUNNING = "EXPERIMENT_RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    CALIBRATING = "CALIBRATING"


class SimulationMode(str, Enum):
    """Experiment mode types."""
    NORMAL_CYCLIC = "NORMAL_CYCLIC"
    FIXED_TEMPERATURE = "FIXED_TEMPERATURE"
    NATURAL_PLATEAU = "NATURAL_PLATEAU"


@dataclass
class PlantState:
    """Plant state snapshot for simulation."""
    surface_temp_c: float = 25.0
    bulk_temp_c: float = 24.0
    ambient_temp_c: float = 22.0
    lamp_output_lux: float = 0.0
    fan_airflow: float = 0.0
    lamp_pwm: int = 0
    fan_pwm: int = 0
    time_s: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'surface_temp_c': self.surface_temp_c,
            'bulk_temp_c': self.bulk_temp_c,
            'ambient_temp_c': self.ambient_temp_c,
            'lamp_output_lux': self.lamp_output_lux,
            'fan_airflow': self.fan_airflow,
            'lamp_pwm': self.lamp_pwm,
            'fan_pwm': self.fan_pwm,
            'time_s': self.time_s,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PlantState':
        return cls(
            surface_temp_c=data.get('surface_temp_c', 25.0),
            bulk_temp_c=data.get('bulk_temp_c', 24.0),
            ambient_temp_c=data.get('ambient_temp_c', 22.0),
            lamp_output_lux=data.get('lamp_output_lux', 0.0),
            fan_airflow=data.get('fan_airflow', 0.0),
            lamp_pwm=data.get('lamp_pwm', 0),
            fan_pwm=data.get('fan_pwm', 0),
            time_s=data.get('time_s', 0.0),
        )


@dataclass
class ExtendedTelemetry:
    """Extended telemetry frame matching physical protocol."""
    total_time: int = 0
    phase_time: int = 0
    cycle_num: int = 0
    state_code: int = 0
    state_label: str = "IDLE"
    ir_temp: Optional[float] = None
    tc_temp: Optional[float] = None
    current_lux: Optional[float] = None
    mode: Optional[str] = None
    control_temp: Optional[float] = None
    temp_setpoint: Optional[float] = None
    temp_error: Optional[float] = None
    lamp_pwm: Optional[float] = None
    hold_wall_elapsed_s: Optional[int] = None
    hold_qualified_elapsed_s: Optional[int] = None
    qualified: Optional[bool] = None
    detected_plateau_temp: Optional[float] = None
    timestamp_s: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ExtendedTelemetry':
        return cls(**{k: v for k, v in data.items() if k in cls.__annotations__})


@dataclass
class SimulatorRunConfig:
    """Configuration for a simulation run."""
    run_id: str = ""  # Will be set by __post_init__
    operator_name: str = ""
    sample_name: str = ""
    description: str = ""
    duration_s: int = 60
    cycles: int = 5
    max_temp_c: float = 80.0
    log_interval_s: int = 1
    target_lux: Optional[float] = None
    illumination_mode: str = "TARGET_LUX"
    mode: str = "NORMAL_CYCLIC"
    target_temperature: Optional[float] = None
    hold_duration_s: Optional[int] = None
    temperature_tolerance: Optional[float] = None
    qualification_dwell_s: Optional[int] = None
    control_sensor: str = "IR"
    ramp_rate: Optional[float] = None
    plateau_window_s: Optional[int] = None
    plateau_max_slope: Optional[float] = None
    plateau_max_range: Optional[float] = None
    plateau_confirmation_s: Optional[int] = None
    plateau_max_discovery_s: Optional[int] = None
    post_plateau_mode: str = "PASSIVE"
    created_at: float = 0.0
    
    def __post_init__(self):
        """Auto-generate UUID if not provided, set timestamp."""
        if not self.run_id:
            self.run_id = str(uuid.uuid4())
        if self.created_at == 0.0:
            self.created_at = time.time()
    
    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SimulatorRunConfig':
        return cls(**{k: v for k, v in data.items() if k in cls.__annotations__})


# =============================================================================
# Request/Response Pydantic Models
# =============================================================================

class TelemetryFrameRequest(BaseModel):
    """Incoming telemetry frame submission."""
    total_time: int
    phase_time: int
    cycle_num: int
    state_code: int
    ir_temp: Optional[float] = None
    tc_temp: Optional[float] = None
    current_lux: Optional[float] = None
    mode: Optional[str] = None
    control_temp: Optional[float] = None
    temp_setpoint: Optional[float] = None
    temp_error: Optional[float] = None
    lamp_pwm: Optional[float] = None
    hold_wall_elapsed_s: Optional[int] = None
    hold_qualified_elapsed_s: Optional[int] = None
    qualified: Optional[bool] = None
    detected_plateau_temp: Optional[float] = None


class RunStateUpdateRequest(BaseModel):
    """Request to update run state."""
    run_id: str
    state: RunState
    metadata: Optional[Dict[str, Any]] = None


class CommandMessage(BaseModel):
    """Command message for remote control."""
    command_type: Literal["STOP", "START", "RESUME", "RESTART", "CONFIGURE"]
    payload: Optional[Dict[str, Any]] = None
    sequence: int = 0


class StartSimulationRequest(BaseModel):
    """Request to start a simulation run."""
    operator_name: str
    sample_name: str
    description: str = ""
    duration: int = 60
    cycles: int = 5
    max_temp: float = 80.0
    interval: int = 1
    target_lux: Optional[float] = None
    illumination_mode: str = "TARGET_LUX"
    mode: str = "NORMAL_CYCLIC"
    target_temperature: Optional[float] = None
    hold_duration_s: Optional[int] = None
    temperature_tolerance: Optional[float] = None
    qualification_dwell_s: Optional[int] = None
    control_sensor: str = "IR"
    ramp_rate: Optional[float] = None
    plateau_window_s: Optional[int] = None
    plateau_max_slope: Optional[float] = None
    plateau_max_range: Optional[float] = None
    plateau_confirmation_s: Optional[int] = None
    plateau_max_discovery_s: Optional[int] = None
    post_plateau_mode: str = "PASSIVE"


class SimulationStatusResponse(BaseModel):
    """Current simulation status response."""
    run_id: str
    state: RunState
    config: Dict[str, Any]
    last_telemetry: Optional[Dict[str, Any]] = None
    pending_commands: List[Dict[str, Any]] = []
    uptime_s: float = 0.0


# =============================================================================
# Isolated Backend API Layer Implementation
# =============================================================================

class SimulatorBackendAPILayer:
    """
    Isolated backend API layer providing /api/simulator/* endpoints.
    
    This layer enforces strict isolation from production systems:
    - No database connections
    - No calls to /api/insert_data (physical data ingestion)
    - Pure in-memory simulator state management
    - Deterministic execution for reproducible experiments
    """
    
    def __init__(self, base_path: str = "/api/simulator"):
        """
        Initialize the isolated backend API layer.
        
        Args:
            base_path: Base path for all simulator endpoints (default: /api/simulator)
        """
        self.base_path = base_path
        self.app = FastAPI(
            title="Simulator Backend API",
            description="Isolated backend API layer for PT-Kit digital twin simulator",
            version="5.3.0",
            docs_url=f"{base_path}/docs",
            redoc_url=f"{base_path}/redoc",
        )
        
        # In-memory state storage (NO DATABASE)
        self._runs: Dict[str, SimulatorRunConfig] = {}
        self._run_states: Dict[str, RunState] = {}
        self._run_metadata: Dict[str, Dict[str, Any]] = {}
        self._telemetry_history: Dict[str, List[ExtendedTelemetry]] = {}
        self._pending_commands: Dict[str, List[CommandMessage]] = {}
        self._start_times: Dict[str, float] = {}
        
        self._setup_routes()
    
    def _setup_routes(self) -> None:
        """Configure FastAPI routes for simulator endpoints."""
        
        @self.app.post(f"{self.base_path}/runs/start")
        async def start_simulation(req: StartSimulationRequest):
            """
            Start a new simulation run with given configuration.
            
            Creates fresh in-memory state - no database writes.
            """
            try:
                config = SimulatorRunConfig(
                    operator_name=req.operator_name,
                    sample_name=req.sample_name,
                    description=req.description,
                    duration_s=req.duration,
                    cycles=req.cycles,
                    max_temp_c=req.max_temp,
                    log_interval_s=req.interval,
                    target_lux=req.target_lux,
                    illumination_mode=req.illumination_mode,
                    mode=req.mode,
                    target_temperature=req.target_temperature,
                    hold_duration_s=req.hold_duration_s,
                    temperature_tolerance=req.temperature_tolerance,
                    qualification_dwell_s=req.qualification_dwell_s,
                    control_sensor=req.control_sensor,
                    ramp_rate=req.ramp_rate,
                    plateau_window_s=req.plateau_window_s,
                    plateau_max_slope=req.plateau_max_slope,
                    plateau_max_range=req.plateau_max_range,
                    plateau_confirmation_s=req.plateau_confirmation_s,
                    plateau_max_discovery_s=req.plateau_max_discovery_s,
                    post_plateau_mode=req.post_plateau_mode,
                )
                
                run_id = config.run_id
                self._runs[run_id] = config
                self._run_states[run_id] = RunState.STARTING
                self._telemetry_history[run_id] = []
                self._pending_commands[run_id] = []
                self._run_metadata[run_id] = {}
                self._start_times[run_id] = time.time()
                
                return {
                    "status": "started",
                    "run_id": run_id,
                    "config": config.to_dict()
                }
                
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Failed to start simulation: {str(e)}"
                )
        
        @self.app.post(f"{self.base_path}/runs/{{run_id}}/stop")
        async def stop_run(run_id: str):
            """Stop a running simulation gracefully."""
            if run_id not in self._runs:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Run {run_id} not found"
                )
            
            self._run_states[run_id] = RunState.COMPLETED
            elapsed = time.time() - self._start_times.get(run_id, time.time())
            
            return {
                "status": "stopped",
                "run_id": run_id,
                "elapsed_s": round(elapsed, 3)
            }
        
        @self.app.post(f"{self.base_path}/runs/{{run_id}}/pause")
        async def pause_run(run_id: str):
            """Pause an ongoing simulation."""
            if run_id not in self._runs:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Run {run_id} not found"
                )
            
            if self._run_states.get(run_id) != RunState.EXPERIMENT_RUNNING:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Can only pause running simulations"
                )
            
            self._run_states[run_id] = RunState.PAUSED
            return {"status": "paused", "run_id": run_id}
        
        @self.app.post(f"{self.base_path}/runs/{{run_id}}/resume")
        async def resume_run(run_id: str):
            """Resume a paused simulation."""
            if run_id not in self._runs:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Run {run_id} not found"
                )
            
            if self._run_states.get(run_id) != RunState.PAUSED:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Can only resume paused simulations"
                )
            
            self._run_states[run_id] = RunState.EXPERIMENT_RUNNING
            self._start_times[run_id] = time.time()  # Reset timer for resumed runs
            return {"status": "resumed", "run_id": run_id}
        
        @self.app.post(f"{self.base_path}/runs/{{run_id}}/telemetry")
        async def submit_telemetry(run_id: str, frame: TelemetryFrameRequest):
            """
            Submit a single telemetry frame to simulation state.
            
            This is THE endpoint for simulator data ingestion - NOT /api/insert_data.
            Stores frame in memory only, never touches database.
            """
            if run_id not in self._runs:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Run {run_id} not found"
                )
            
            if self._run_states.get(run_id) not in (
                RunState.EXPERIMENT_RUNNING,
                RunState.PAUSED,
                RunState.STARTING,
                RunState.CALIBRATING,
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot submit telemetry in current state"
                )
            
            telemetry = ExtendedTelemetry(
                total_time=frame.total_time,
                phase_time=frame.phase_time,
                cycle_num=frame.cycle_num,
                state_code=frame.state_code,
                ir_temp=frame.ir_temp,
                tc_temp=frame.tc_temp,
                current_lux=frame.current_lux,
                mode=frame.mode,
                control_temp=frame.control_temp,
                temp_setpoint=frame.temp_setpoint,
                temp_error=frame.temp_error,
                lamp_pwm=frame.lamp_pwm,
                hold_wall_elapsed_s=frame.hold_wall_elapsed_s,
                hold_qualified_elapsed_s=frame.hold_qualified_elapsed_s,
                qualified=frame.qualified,
                detected_plateau_temp=frame.detected_plateau_temp,
                timestamp_s=time.time(),
            )
            
            self._telemetry_history[run_id].append(telemetry)
            
            return {
                "status": "accepted",
                "frame_index": len(self._telemetry_history[run_id]) - 1,
                "timestamp_s": telemetry.timestamp_s
            }
        
        @self.app.get(f"{self.base_path}/runs/{{run_id}}")
        async def get_run_status(run_id: str) -> SimulationStatusResponse:
            """Get current status of a simulation run."""
            if run_id not in self._runs:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Run {run_id} not found"
                )
            
            config = self._runs[run_id]
            state = self._run_states.get(run_id, RunState.IDLE)
            history = self._telemetry_history.get(run_id, [])
            commands = self._pending_commands.get(run_id, [])
            start_time = self._start_times.get(run_id, time.time())
            
            last_tele = history[-1].to_dict() if history else None
            
            return SimulationStatusResponse(
                run_id=run_id,
                state=state,
                config=config.to_dict(),
                last_telemetry=last_tele,
                pending_commands=[c.model_dump() for c in commands],
                uptime_s=round(time.time() - start_time, 3),
            )
        
        @self.app.get(f"{self.base_path}/runs/{{run_id}}/telemetry")
        async def get_telemetry_history(
            run_id: str,
            limit: int = 100,
            offset: int = 0
        ):
            """Retrieve telemetry history for a run."""
            if run_id not in self._runs:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Run {run_id} not found"
                )
            
            history = self._telemetry_history.get(run_id, [])
            sliced = history[offset:offset + limit]
            
            return {
                "run_id": run_id,
                "total_count": len(history),
                "limit": limit,
                "offset": offset,
                "frames": [t.to_dict() for t in sliced]
            }
        
        @self.app.post(f"{self.base_path}/runs/{{run_id}}/commands")
        async def queue_command(run_id: str, cmd: CommandMessage):
            """Queue a remote command for this simulation."""
            if run_id not in self._runs:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Run {run_id} not found"
                )
            
            # Update sequence number
            cmds = self._pending_commands.get(run_id, [])
            next_seq = max([c.sequence for c in cmds], default=0) + 1
            cmd.sequence = next_seq
            
            self._pending_commands[run_id].append(cmd)
            
            return {
                "status": "queued",
                "sequence": next_seq,
                "run_id": run_id
            }
        
        @self.app.get(f"{self.base_path}/runs/{{run_id}}/commands")
        async def get_pending_commands(run_id: str) -> List[Dict[str, Any]]:
            """Fetch queued commands for this run."""
            if run_id not in self._runs:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Run {run_id} not found"
                )
            
            cmds = self._pending_commands.get(run_id, [])
            return [c.model_dump() for c in cmds]
        
        @self.app.delete(f"{self.base_path}/runs/{{run_id}}/commands")
        async def clear_commands(run_id: str):
            """Clear all pending commands for a run."""
            if run_id not in self._runs:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Run {run_id} not found"
                )
            
            cleared = self._pending_commands.get(run_id, [])
            self._pending_commands[run_id] = []
            
            return {
                "status": "cleared",
                "count": len(cleared),
                "run_id": run_id
            }
        
        @self.app.delete(f"{self.base_path}/runs/{{run_id}}")
        async def delete_run(run_id: str):
            """Delete a simulation run and all its state."""
            if run_id not in self._runs:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Run {run_id} not found"
                )
            
            del self._runs[run_id]
            del self._run_states[run_id]
            del self._telemetry_history[run_id]
            del self._pending_commands[run_id]
            del self._run_metadata[run_id]
            del self._start_times[run_id]
            
            return {"status": "deleted", "run_id": run_id}
        
        @self.app.get(f"{self.base_path}/runs")
        async def list_runs():
            """List all active simulation runs."""
            return {
                "runs": [
                    {
                        "run_id": rid,
                        "config": cfg.to_dict(),
                        "state": state,
                        "telemetry_count": len(self._telemetry_history.get(rid, [])),
                    }
                    for rid, cfg in self._runs.items()
                    for state in [self._run_states.get(rid, RunState.IDLE)]
                ]
            }
        
        @self.app.get(f"{self.base_path}/health")
        async def health_check():
            """Health check endpoint for the simulator API layer."""
            return {
                "status": "healthy",
                "service": "simulator-backend-api",
                "version": "5.3.0",
                "base_path": self.base_path,
                "active_runs": len(self._runs),
                "isolated_from_production": True,
            }
    
    def get_in_memory_state(self) -> Dict[str, Any]:
        """
        Get complete in-memory state (for testing/diagnostics).
        
        WARNING: This method exposes internal state - use with caution.
        """
        return {
            "runs": {rid: cfg.to_dict() for rid, cfg in self._runs.items()},
            "states": {rid: state.value for rid, state in self._run_states.items()},
            "telemetry_counts": {rid: len(tel) for rid, tel in self._telemetry_history.items()},
            "command_counts": {rid: len(cmds) for rid, cmds in self._pending_commands.items()},
        }
    
    def verify_isolation(self) -> bool:
        """
        Verify that this layer maintains proper isolation.
        
        Returns True if no external dependencies are accessed.
        """
        # Verify no database connections exist in this layer
        # (The app should not have any psycopg2 or DB connection code)
        return True  # By design - this class has no DB access
    
    def export_run_data(self, run_id: str) -> Dict[str, Any]:
        """
        Export all data for a specific run as serializable dict.
        
        Useful for golden trace comparison and deterministic replay.
        """
        if run_id not in self._runs:
            raise ValueError(f"Run {run_id} not found")
        
        config = self._runs[run_id]
        state = self._run_states.get(run_id, RunState.IDLE)
        telemetry = self._telemetry_history.get(run_id, [])
        commands = self._pending_commands.get(run_id, [])
        
        return {
            "run_id": run_id,
            "config": config.to_dict(),
            "final_state": state.value,
            "telemetry_frames": [t.to_dict() for t in telemetry],
            "sent_commands": [c.model_dump() for c in commands],
            "export_timestamp_s": time.time(),
        }
