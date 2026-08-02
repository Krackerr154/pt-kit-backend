# Phase 5 Interface Contract: Run Supervisor & Simulator Backend API Isolation

This document defines the interfaces for Phase 5 implementation so parallel subagents produce compatible code.

## Overview

Phase 5 implements the **Run Supervisor** - the orchestrator layer that manages simulator run state, coordinates between plant/controller/UART/ESP32 components, and exposes an isolated backend API.

The architecture adds a supervisor process that:
- Manages experiment lifecycle (START → RUNNING → PAUSED → COMPLETED)
- Receives remote commands from backend via isolated API
- Coordinates telemetry collection across all components
- Ensures simulator never writes to physical experiment database

```
Remote Backend Command → Run Supervisor → Simulator Components
                              ↓
                       /api/simulator/* (isolated API)
```

---

## Core Data Models

### Run State Enum

```python
from enum import IntEnum, auto

class RunState(IntEnum):
    """Experiment execution states."""
    
    IDLE = 0              # No experiment running, system ready
    STARTING = 1          # Initialization in progress
    RUNNING = 2           # Experiment actively executing
    PAUSED = 3            # Temporarily suspended (not DONE)
    COMPLETED = 4         # Normal completion
    ABORTED = 5           # Abnormal termination
    SUPERVISOR_ABORT = 6  # Supervisor initiated shutdown
    
    def is_active(self) -> bool:
        """True if experiment is actively running or paused."""
        return self in (self.RUNNING, self.PAUSED)
    
    def is_terminal(self) -> bool:
        """True if state cannot transition except to IDLE."""
        return self in (self.COMPLETED, self.ABORTED, self.SUPERVISOR_ABORT)
```

### ExperimentRecord Schema

```python
@dataclass
class ExperimentRecord:
    """Complete record of one experiment run."""
    
    # Identifiers
    run_id: str                    # UUID v4
    scenario: str                  # ISO1_default_target, PLAT1_default, etc.
    profile_uuid: Optional[str]    # PlantProfile UUID if loaded
    
    # Timing
    started_at: datetime
    completed_at: Optional[datetime]
    duration_s: float              # Total elapsed time
    
    # State machine
    state: RunState
    current_cycle: int             # Current qualification cycle (ISO1)
    
    # Telemetry summary
    frame_count: int               # Total frames collected
    last_temperature_c: Optional[float]
    last_lux: Optional[int]
    
    # Errors/faults
    error_message: Optional[str]
    fault_codes: list[str]         # FaultType codes if any faults occurred
    
    # Configuration snapshot
    plant_config_json: dict        # Serialized PlantConfig
    sensor_config_json: dict       # Serialized SensorConfig
    mode_params_json: dict         # Mode-specific parameters
    
    # Flags
    was_paused: bool = False       # If paused at least once during run
    forced_stop: bool = False      # If stopped externally before natural completion
    
    def to_dict(self) -> dict:
        return {
            'run_id': self.run_id,
            'scenario': self.scenario,
            'profile_uuid': self.profile_uuid,
            'started_at': self.started_at.isoformat(),
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'duration_s': self.duration_s,
            'state': int(self.state),
            'current_cycle': self.current_cycle,
            'frame_count': self.frame_count,
            'last_temperature_c': self.last_temperature_c,
            'last_lux': self.last_lux,
            'error_message': self.error_message,
            'fault_codes': self.fault_codes,
            'plant_config': self.plant_config_json,
            'sensor_config': self.sensor_config_json,
            'mode_params': self.mode_params_json,
            'was_paused': self.was_paused,
            'forced_stop': self.forced_stop,
        }
```

---

## API Interfaces

### ExperimentLifecycleController

```python
class ExperimentLifecycleController:
    """Manages experiment lifecycle and remote command handling.
    
    Responsibilities:
    - Maintain state machine with validation
    - Queue and execute remote commands
    - Coordinate component startup/shutdown
    - Record metrics and events
    """
    
    def start_experiment(
        self,
        scenario: str,
        plant_config: PlantConfig,
        sensor_config: SensorConfig,
        mode_params: Dict[str, Any],
        profile_uuid: Optional[str] = None
    ) -> str:
        """Start a new experiment run.
        
        Transitions: IDLE → STARTING → RUNNING
        
        Returns: run_id (UUID string)
        """
    
    def stop_experiment(self, run_id: str, reason: str = "STOP") -> bool:
        """Gracefully stop experiment (without firmware ABORT).
        
        Transitions: RUNNING/PAUSED → COMPLETED (with graceful teardown)
        
        Does NOT trigger firmware ABORT sequence.
        """
    
    def pause_experiment(self, run_id: str) -> bool:
        """Pause running experiment.
        
        Transitions: RUNNING → PAUSED
        Freezes state but maintains context.
        """
    
    def resume_experiment(self, run_id: str) -> bool:
        """Resume paused experiment.
        
        Transitions: PAUSED → RUNNING
        Resumes from same timestamp.
        """
    
    def restart_experiment(self, run_id: str) -> bool:
        """Restart experiment from beginning.
        
        Resets state to IDLE, then transitions to STARTING.
        Clearing all accumulated telemetry and metrics.
        """
    
    def submit_command(
        self,
        run_id: str,
        command_type: str,
        payload: Dict[str, Any],
        scheduled_ms: Optional[int] = None
    ) -> str:
        """Submit remote command to experiment controller.
        
        Commands supported:
        - STOP: Graceful stop (idempotent, no ABORT)
        - RESTART: Restart from beginning
        - PAUSE/RESUME: Toggle paused state
        - CONFIGURE: Update runtime parameters
        - FAULT_INJECT: Trigger specific fault scenarios
        
        Returns: command_id (UUID string)
        """

```

### TelemetryCollector

```python
class TelemetryCollector:
    """Aggregates ExtendedTelemetry frames from all simulator components.
    
    Features:
    - Monotonic timestamp validation (±10ms tolerance)
    - Circular buffer (default 300s retention)
    - Gap detection and reporting
    - Export in JSON, CSV, binary formats
    - Time-windowed queries
    """
    
    def append_frame(self, frame: ExtendedTelemetry) -> bool:
        """Add telemetry frame to aggregator.
        
        Validates timestamp monotonicity within ±10ms tolerance.
        Stores in circular buffer if valid.
        
        Returns: True if accepted, False if invalid/timestamp gap > tolerance
        """
    
    def get_frames(self, start_time: float, end_time: float) -> List[ExtendedTelemetry]:
        """Retrieve frames within time window.
        
        Args:
            start_time: Start timestamp in seconds (relative to experiment start)
            end_time: End timestamp in seconds
            
        Returns: Ordered list of ExtendedTelemetry frames
        """
    
    def export_json(self, path: Path, include_metadata: bool = True) -> None:
        """Export telemetry to JSON file.
        
        Format includes:
        - Full metadata if include_metadata=True
        - Timestamp-ordered frames
        - Summary statistics (min/max/average values)
        """
    
    def export_csv(self, path: Path) -> None:
        """Export telemetry to CSV for spreadsheet analysis.
        
        Columns: virtual_time_s, surface_temp_c, bulk_temp_c, 
                 ir_temp_c, tc_temp_c, lux, lamp_power_w, fan_rpm, etc.
        """
    
    def get_summary(self, time_range: Optional[Tuple[float, float]] = None) -> Dict[str, Any]:
        """Generate summary statistics for time range.
        
        Returns: Dict with frame_count, min/max/avg values per field,
                 gap counts, validity percentages
        """

```

### SimulatorBackendAPILayer

```python
class SimulatorBackendAPILayer:
    """REST endpoint layer enforcing /api/simulator/* isolation only.
    
    Design Principles:
    ✅ NO /api/insert_data calls (never touch physical experiment DB)
    ✅ In-memory state management only
    ✅ Session pooling for performance
    ✅ Strict JSON schema validation
    ✅ Audit logging of all interactions
    """
    
    def __init__(self, base_url: str = "/api/simulator"):
        self.base_path = base_url
        self._session = requests.Session()
        self._session.headers.update({
            'Content-Type': 'application/json',
            'X-Simulator': 'true',
        })
        self._runs: Dict[str, SimulationStatus] = {}
    
    # === Endpoints ===
    
    @app.post(f"{base_path}/telemetry")
    async def post_telemetry(self, telemetry: ExtendedTelemetry) -> Dict[str, str]:
        """Post telemetry data to simulation run."""
        # Validate against simulation-only schemas
        # Forward to appropriate run or create new run
        pass
    
    @app.put(f"{base_path}/runs/{run_id}")
    async def put_run_status(
        self,
        run_id: str,
        status_update: SimulationStatusResponse
    ) -> Dict[str, str]:
        """Update simulation run status."""
        # Update internal state only (no DB write)
        pass
    
    @app.get(f"{base_path}/runs/{run_id}/commands")
    async def get_commands(self, run_id: str) -> List[Dict[str, Any]]:
        """Get pending commands for run."""
        # Return queued commands from in-memory store
        pass
    
    @app.get(f"{base_path}/runs/{run_id}/history")
    async def get_history(
        self,
        run_id: str,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None
    ) -> List[ExtendedTelemetry]:
        """Get telemetry history for run."""
        # Query in-memory circular buffer
        pass
    
    @app.delete(f"{base_path}/runs/{run_id}")
    async def delete_run(self, run_id: str) -> Dict[str, str]:
        """Delete simulation run and all associated data."""
        # Remove from in-memory store
        pass
    
    # === Isolation Enforcement ===
    
    def validate_isolation(self, path: str) -> bool:
        """Verify path starts with /api/simulator/.
        
        Raises HTTPException(404) if not isolated path.
        """
        if not path.startswith(self.base_path):
            raise HTTPException(404, f"Not found: {path}")
        return True
```

---

## Integration Points

### From Phase 4 Components

```python
# Run supervisor integrates with UART engine
controller = ExperimentLifecycleController(
    virtual_clock=VirtualClock(seed=42),
    uart_engine=VirtualUARTEngine(baud_rate=115200)
)

# Telemetry collector aggregates from plant, sensors, controller
collector = TelemetryCollector(
    circular_buffer_size_seconds=300,
    timestamp_tolerance_ms=10
)

# Backed by isolated API layer
api_layer = SimulatorBackendAPILayer(
    base_url="/api/simulator",
    telemetry_collector=collector
)
```

---

## Exit Criteria Checklist

✅ All 5 REST endpoints functional (POST telemetry, PUT run, GET commands/history, DELETE run)  
✅ Isolation enforced (paths validated, never allows /api/insert_data)  
✅ State machine transitions correct (IDLE→STARTING→RUNNING→COMPLETED/ABORTED)  
✅ Remote commands handled gracefully (STOP without ABORT, PAUSE/RESUME toggle, RESTART reset)  
✅ Telemetry aggregation maintains temporal order (±10ms tolerance)  
✅ Circular buffer operates without memory leaks (300s default retention)  
✅ All tests pass without external dependencies (mock responses used)  

---

## Testing Requirements

### Unit Tests (Task 5.1: Run Supervisor)
- Test all valid state transitions
- Test illegal transition rejection  
- Test STOP command graceful handling
- Test PAUSE/RESUME toggling
- Test RESTART full reset behavior
- Test CONFIGURE parameter updates mid-experiment
- Verify no external dependencies

### Unit Tests (Task 5.2: Telemetry Aggregator)
- Test frame ordering validation
- Test circular buffer wrap-around
- Test gap detection accuracy
- Test export format generation (JSON/CSV/binary)
- Test time-windowed query correctness
- Verify determinism with fixed seed

### Unit Tests (Task 5.3: Isolated Backend API)
- Test each endpoint response format
- Test isolation enforcement (block non-/api/simulator/ paths)
- Test JSON schema validation errors
- Test session pooling under load
- Verify mock responses only (no network calls)

---

## Performance Targets

| Metric | Target | Measurement Method |
|--------|--------|-------------------|
| Command latency | < 10ms average | Time from POST to response |
| Telemetry throughput | ≥ 100 frames/sec | Frames processed per second |
| Memory usage | < 50 MB for 1 hour run | RSS monitoring |
| Circular buffer retention | 99.9% no loss | Frame count verification |
| API isolation enforcement | 100% blocks bad paths | Malicious input testing |

---

*Document Version: 1.0 | Created: 2026-08-01 | PT-Kit Phase 5 Deliverable*
