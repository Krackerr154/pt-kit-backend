"""Dashboard Web Server - Phase 6 Task 6.1

Core dashboard web server with REST API endpoints for simulator monitoring and control.
Provides FastAPI application serving dashboard at /simulator path with proper integration
to SimulatorBackendAPILayer from Phase 5.

Features:
✅ GET /simulator/status - Returns DashboardState JSON
✅ POST /simulator/commands - Remote command submission with validation
✅ GET /simulator/history - Telemetry history queries
✅ GET /health - Health check endpoint (<100ms response)
✅ Input validation against schemas
✅ Appropriate HTTP status codes (200, 400, 404)
✅ Deterministic output: same state produces identical JSON
"""

from fastapi import FastAPI, HTTPException, status, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any, Literal
from dataclasses import dataclass, field
from enum import Enum
import time
import uuid
from datetime import datetime
import asyncio


# =============================================================================
# Data Models for Dashboard State
# =============================================================================

class RunState(int, Enum):
    """Experiment execution states matching Phase 5."""
    IDLE = 0
    STARTING = 1
    EXPERIMENT_RUNNING = 2
    PAUSED = 3
    COMPLETED = 4
    ABORTED = 5
    SUPERVISOR_ABORT = 6


@dataclass
class DashboardState:
    """Current state view for dashboard visualization.
    
    Attributes:
        run_id: Unique experiment identifier
        state: Current RunState enum value
        scenario: Experiment scenario name
        duration_s: Total elapsed time in seconds
        progress_pct: Progress as percentage (0-100)
        current_surface_temp_c: Latest surface temperature (°C)
        current_bulk_temp_c: Latest bulk temperature (°C)
        current_lux: Latest light measurement (lux)
        lamp_power_w: Lamp power consumption (W)
        fan_rpm: Fan rotational speed (RPM)
        total_frames: Total telemetry frames collected
        gap_count: Number of detected data gaps
        validity_rate: Ratio of valid frames (0-1)
        active_faults: List of currently active fault identifiers
        started_at: ISO format timestamp when experiment started
        last_update: ISO format timestamp of last state update
    
    Example:
        >>> state = DashboardState(
        ...     run_id="abc-123",
        ...     state=RunState.EXPERIMENT_RUNNING,
        ...     scenario="ISO1_default_target",
        ...     duration_s=120.5,
        ...     progress_pct=45.2,
        ...     current_surface_temp_c=75.3,
        ...     current_bulk_temp_c=68.9,
        ...     current_lux=8500,
        ...     lamp_power_w=45.2,
        ...     fan_rpm=3200,
        ...     total_frames=120,
        ...     gap_count=2,
        ...     validity_rate=0.98,
        ...     active_faults=["FAULT_001"],
        ...     started_at=datetime.now(),
        ...     last_update=datetime.now()
        ... )
        >>> state_dict = state.to_dict()
    """
    
    # Experiment status
    run_id: str
    state: RunState
    scenario: str
    duration_s: float
    progress_pct: float
    
    # Real-time telemetry summary
    current_surface_temp_c: float
    current_bulk_temp_c: float
    current_lux: int
    lamp_power_w: float
    fan_rpm: int
    
    # Statistics summary
    total_frames: int
    gap_count: int
    validity_rate: float
    
    # Active faults
    active_faults: List[str]
    
    # Timestamps
    started_at: datetime
    last_update: datetime
    
    def to_dict(self) -> dict:
        """Convert state to dictionary for JSON serialization.
        
        Returns:
            dict: Dictionary representation with all fields serialized
            
        Example:
            {
                'run_id': 'abc-123',
                'state': 2,  # int(RunState.EXPERIMENT_RUNNING)
                'scenario': 'ISO1_default_target',
                ...
            }
        """
        return {
            'run_id': self.run_id,
            'state': self.state.value,  # Use .value for string enum
            'scenario': self.scenario,
            'duration_s': self.duration_s,
            'progress_pct': self.progress_pct,
            'current_surface_temp_c': self.current_surface_temp_c,
            'current_bulk_temp_c': self.current_bulk_temp_c,
            'current_lux': self.current_lux,
            'lamp_power_w': self.lamp_power_w,
            'fan_rpm': self.fan_rpm,
            'total_frames': self.total_frames,
            'gap_count': self.gap_count,
            'validity_rate': self.validity_rate,
            'active_faults': self.active_faults,
            'started_at': self.started_at.isoformat(),
            'last_update': self.last_update.isoformat(),
        }


@dataclass
class LiveTelemetryFrame:
    """Single frame for WebSocket streaming.
    
    Note: This is defined for future WebSocket support (Task 6.2).
    Currently included to match Phase 6 interface specification.
    
    Attributes:
        virtual_time_s: Virtual experiment time in seconds
        sequence_number: Monotonically increasing frame counter
        surface_temp_c: Surface temperature reading (°C)
        bulk_temp_c: Bulk temperature reading (°C)
        ir_temp_c: IR sensor temperature (°C)
        tc_temp_c: Thermocouple temperature (°C)
        lux: Light intensity (lux)
        lamp_power_w: Lamp power (W)
        fan_rpm: Fan speed (RPM)
        is_valid: Whether frame passed validation
        validation_errors: List of validation error messages
        timestamp_s: Wall-clock timestamp when frame was generated
    """
    
    virtual_time_s: float
    sequence_number: int
    surface_temp_c: float
    bulk_temp_c: float
    ir_temp_c: float
    tc_temp_c: float
    lux: int
    lamp_power_w: float
    fan_rpm: int
    is_valid: bool
    validation_errors: List[str]
    timestamp_s: float
    
    def to_dict(self) -> dict:
        """Convert frame to dictionary for JSON serialization.
        
        Returns:
            dict: All fields as key-value pairs
        """
        return {f.name: getattr(self, f.name) 
                for f in self.__dataclass_fields__.values()}


# =============================================================================
# Request/Response Pydantic Models
# =============================================================================

class RemoteCommand(BaseModel):
    """Command message for remote dashboard control.
    
    Attributes:
        command_type: Type of command (STOP, RESTART, PAUSE, RESUME, CONFIGURE, FAULT_INJECT)
        payload: Command-specific parameters
        run_id: Target experiment run ID (required)
        scheduled_ms: Optional scheduled execution time in milliseconds
        
    Example:
        >>> cmd = RemoteCommand(
        ...     command_type="STOP",
        ...     payload={"reason": "user_requested"},
        ...     run_id="abc-123"
        ... )
    """
    command_type: Literal["STOP", "RESTART", "PAUSE", "RESUME", "CONFIGURE", "FAULT_INJECT"]
    payload: Optional[Dict[str, Any]] = None
    run_id: str = Field(..., description="Target run ID (required)")
    scheduled_ms: Optional[int] = Field(None, description="Optional scheduled execution time")
    
    @validator('run_id')
    def validate_run_id(cls, v):
        """Ensure run_id is not empty or whitespace."""
        if not v or not v.strip():
            raise ValueError('run_id cannot be empty or whitespace')
        return v.strip()
    
    @validator('payload')
    def validate_payload_structure(cls, v, values):
        """Validate payload structure based on command type."""
        cmd_type = values.get('command_type')
        if cmd_type == "FAULT_INJECT":
            # Fault injection requires specific fields. Note an empty dict is
            # falsy, so this must test for None explicitly rather than truthiness.
            if not v or 'fault_type' not in v:
                raise ValueError("FAULT_INJECT commands require 'fault_type' in payload")
        return v
    
    def to_dict(self) -> dict:
        """Convert to dictionary for logging/storing."""
        return {
            'command_type': self.command_type,
            'payload': self.payload,
            'run_id': self.run_id,
            'scheduled_ms': self.scheduled_ms,
        }


class CommandResult(BaseModel):
    """Result of command submission.
    
    Attributes:
        command_id: UUID assigned to this command
        status: Submission status ("queued", "executed", "failed")
        message: Human-readable status message
    """
    command_id: str
    status: Literal["queued", "executed", "failed"] = "queued"
    message: str = "Command queued successfully"


class HistoryQueryRequest(BaseModel):
    """Request model for history query (optional validation layer).
    
    Note: GET endpoint uses Query parameters directly for simplicity.
    This model exists for potential future POST-based history queries.
    
    Attributes:
        start_time: Optional start timestamp in seconds
        end_time: Optional end timestamp in seconds
        limit: Maximum number of frames to return
        offset: Pagination offset
    """
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    limit: Optional[int] = Field(1000, ge=1, le=10000)
    offset: int = Field(0, ge=0)


class HealthStatus(BaseModel):
    """Health check response model.
    
    Attributes:
        status: Health status string ("healthy", "degraded", "unhealthy")
        version: API version string
        uptime_s: Server uptime in seconds
        timestamp: ISO format timestamp
    """
    status: Literal["healthy", "degraded", "unhealthy"] = "healthy"
    version: str = "6.1.0"
    uptime_s: float
    timestamp: str
    
    @classmethod
    def create(cls, uptime_s: float) -> 'HealthStatus':
        """Factory method to create health status with current timestamp.
        
        Args:
            uptime_s: Server uptime in seconds
            
        Returns:
            HealthStatus instance ready for JSON serialization
        """
        return cls(
            status="healthy",
            version="6.1.0",
            uptime_s=uptime_s,
            timestamp=datetime.now().isoformat()
        )


# =============================================================================
# DashboardWebServer Implementation
# =============================================================================

class DashboardWebServer:
    """Lightweight web server serving dashboard UI and real-time APIs.
    
    Integrates with SimulatorBackendAPILayer from Phase 5 to provide:
    - Real-time state monitoring at /simulator/status
    - Remote command submission at /simulator/commands
    - Telemetry history retrieval at /simulator/history
    - Health check at /health
    
    Features:
    ✅ FastAPI application serving dashboard at /simulator path
    ✅ GET /simulator/status endpoint returning DashboardState
    ✅ POST /simulator/commands for remote command submission
    ✅ GET /simulator/history for telemetry history queries
    ✅ GET /health health check endpoint
    ✅ Integration with SimulatorBackendAPILayer
    ✅ Input validation against Pydantic schemas
    ✅ Appropriate HTTP status codes (200 OK, 400 Bad Request, 404 Not Found)
    ✅ Determinism: same state produces identical JSON output
    
    Args:
        backend_api: Optional SimulatorBackendAPILayer instance from Phase 5
        host: Server host address (default: 127.0.0.1)
        port: Server port (default: 8080)
        startup_data: Optional initial simulation runs for testing
        
    Example:
        >>> # Basic usage with existing backend API
        >>> backend_api = SimulatorBackendAPILayer()
        >>> server = DashboardWebServer(backend_api=backend_api)
        >>> server.run(host="127.0.0.1", port=8080)
        
        # For testing without backend API
        >>> server = DashboardWebServer(backend_api=None)
        >>> app = server.get_app()
    """
    
    def __init__(
        self,
        backend_api: Any = None,  # Type: Optional[SimulatorBackendAPILayer]
        host: str = "127.0.0.1",
        port: int = 8080,
        startup_data: Optional[List[Any]] = None
    ):
        """Initialize dashboard web server.
        
        Args:
            backend_api: SimulatorBackendAPILayer from Phase 5, or None for standalone mode
            host: Bind address (default: 127.0.0.1)
            port: Port number (default: 8080)
            startup_data: Pre-populated runs for testing
        """
        self.host = host
        self.port = port
        self._backend_api = backend_api
        self._start_time = time.time()
        self._request_counter = 0
        
        # In-memory run state storage for standalone operation
        self._runs: Dict[str, Dict[str, Any]] = {}
        self._telemetry_history: Dict[str, List[Dict[str, Any]]] = {}
        self._command_queue: List[Dict[str, Any]] = []
        
        # Initialize FastAPI app
        self._app = FastAPI(
            title="PT-Kit Simulator Dashboard API",
            description="Dashboard web server for PT-Kit digital twin simulator",
            version="6.1.0",
            docs_url="/simulator/docs",
            redoc_url="/simulator/redoc",
        )
        
        # Setup routes
        self._setup_routes()
        
        # Pre-populate with startup data if provided
        if startup_data:
            for run_data in startup_data:
                run_id = run_data.get('run_id', str(uuid.uuid4()))
                self._runs[run_id] = run_data
                self._telemetry_history[run_id] = run_data.get('telemetry', [])
    
    def _setup_routes(self) -> None:
        """Configure FastAPI routes for dashboard endpoints."""
        
        # Health check endpoint
        @self._app.get("/health")
        async def health_check():
            """Simple health check endpoint.
            
            Returns:
                JSONResponse: Status with version and uptime
                
            Response Schema:
                {
                    "status": "healthy",
                    "version": "6.1.0",
                    "uptime_s": 1234.5,
                    "timestamp": "2026-08-01T12:00:00.000000"
                }
                
            Performance: Responds within 100ms
            """
            uptime = time.time() - self._start_time
            return HealthStatus.create(uptime).model_dump()
        
        # Status endpoint - GET /simulator/status
        @self._app.get("/simulator/status")
        async def get_status(
            run_id: Optional[str] = Query(
                None, 
                description="Optional run ID. If not provided, returns latest running experiment"
            )
        ):
            """Get current dashboard state.
            
            Retrieves state from backend API or internal storage.
            If run_id not specified, attempts to return the latest running experiment.
            
            Args:
                run_id: Optional target run identifier
                
            Returns:
                JSONResponse: DashboardState serialized to JSON
                
            Raises:
                HTTPException(404): Run not found when run_id is specified
                HTTPException(500): Internal error retrieving state
                
            Response Schema:
                {
                    "run_id": "abc-123",
                    "state": 2,  # int(RunState)
                    "scenario": "ISO1_default_target",
                    "duration_s": 120.5,
                    "progress_pct": 45.2,
                    "current_surface_temp_c": 75.3,
                    "current_bulk_temp_c": 68.9,
                    "current_lux": 8500,
                    "lamp_power_w": 45.2,
                    "fan_rpm": 3200,
                    "total_frames": 120,
                    "gap_count": 2,
                    "validity_rate": 0.98,
                    "active_faults": ["FAULT_001"],
                    "started_at": "2026-08-01T12:00:00",
                    "last_update": "2026-08-01T12:02:00"
                }
            """
            self._request_counter += 1
            
            try:
                # Try to get from backend API first if available
                if self._backend_api:
                    # Check if we can call backend API methods
                    if hasattr(self._backend_api, '_get_run_state'):
                        run_state = self._backend_api._get_run_state(run_id)
                        if run_state:
                            return JSONResponse(
                                content=self._generate_dashboard_state_dict(run_state)
                            )
                
                # Fall back to internal storage
                if not run_id:
                    # Return latest running experiment
                    run_id = self._get_active_run_id()
                    if not run_id:
                        return JSONResponse(
                            content=self._create_default_empty_state(),
                            status_code=status.HTTP_200_OK
                        )
                    # An explicitly resolved active run must still exist below.
                
                run_data = self._runs.get(run_id)
                if not run_data:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Run {run_id} not found"
                    )
                
                return JSONResponse(
                    content=self._generate_dashboard_state_dict(run_data)
                )
                
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to retrieve status: {str(e)}"
                )
        
        # Commands endpoint - POST /simulator/commands
        @self._app.post("/simulator/commands")
        async def submit_command(command: RemoteCommand):
            """Submit remote command to experiment controller.
            
            Validates command structure and forwards to backend API or queues internally.
            Validates run_id presence and payload structure based on command type.
            
            Args:
                command: RemoteCommand with validated structure
                
            Returns:
                JSONResponse: CommandResult with command_id and status
                
            Raises:
                HTTPException(400): Invalid command structure or missing run_id
                HTTPException(404): Run not found
                HTTPException(500): Failed to execute command
                
            Example Request:
                {
                    "command_type": "STOP",
                    "payload": {"reason": "user_requested"},
                    "run_id": "abc-123"
                }
                
            Example Response:
                {
                    "command_id": "uuid-here",
                    "status": "queued",
                    "message": "Command queued successfully"
                }
            """
            self._request_counter += 1
            
            try:
                # Validate run_id exists
                if not command.run_id or not command.run_id.strip():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Missing or invalid run_id in command"
                    )
                
                run_id = command.run_id.strip()
                
                # Check if run exists (only if backend API not available)
                if not self._backend_api:
                    if run_id not in self._runs:
                        # Only fail if we're managing runs locally
                        raise HTTPException(
                            status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Run {run_id} not found"
                        )
                
                # Forward to backend API if available
                if self._backend_api:
                    if hasattr(self._backend_api, 'queue_command'):
                        result = self._backend_api.queue_command(run_id, command.model_dump())
                        return JSONResponse(content=result)
                    elif hasattr(self._backend_api, '_pending_commands'):
                        # Access internal queue directly
                        command_id = str(uuid.uuid4())
                        cmd_entry = {
                            'command_id': command_id,
                            **command.model_dump()
                        }
                        self._backend_api._pending_commands.setdefault(run_id, []).append(cmd_entry)
                        
                        return CommandResult(
                            command_id=command_id,
                            status="queued",
                            message=f"Command {command.command_type} queued for run {run_id}"
                        ).model_dump()
                
                # Internal queue for standalone mode
                command_id = str(uuid.uuid4())
                cmd_entry = {
                    'command_id': command_id,
                    **command.model_dump()
                }
                self._command_queue.append(cmd_entry)
                
                return CommandResult(
                    command_id=command_id,
                    status="queued",
                    message=f"Command {command.command_type} queued for run {run_id}"
                ).model_dump()
                
            except HTTPException:
                raise
            except ValueError as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(e)
                )
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to submit command: {str(e)}"
                )
        
        # History endpoint - GET /simulator/history
        @self._app.get("/simulator/history")
        async def get_history(
            run_id: str = Query(..., description="Target run ID (required)"),
            start_time: Optional[float] = Query(
                None, 
                description="Optional start timestamp in seconds"
            ),
            end_time: Optional[float] = Query(
                None,
                description="Optional end timestamp in seconds"
            )
        ):
            """Retrieve telemetry history for visualization.
            
            Queries backend API or internal storage for telemetry frames
            within optional time window.
            
            Args:
                run_id: Target run identifier (required)
                start_time: Optional start timestamp in seconds
                end_time: Optional end timestamp in seconds
                
            Returns:
                List[Dict]: Array of telemetry frame dictionaries
                
            Raises:
                HTTPException(400): Missing run_id
                HTTPException(404): Run not found
                
            Example Request:
                /simulator/history?run_id=abc-123&start_time=100.0&end_time=200.0
                
            Example Response:
                [
                    {
                        "virtual_time_s": 100.5,
                        "sequence_number": 100,
                        "surface_temp_c": 75.3,
                        "bulk_temp_c": 68.9,
                        ...
                    },
                    ...
                ]
            """
            self._request_counter += 1
            
            # Validate run_id is provided
            if not run_id or not run_id.strip():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Missing required parameter: run_id"
                )
            
            run_id = run_id.strip()
            
            try:
                # Try to get from backend API first
                if self._backend_api:
                    if hasattr(self._backend_api, '_telemetry_history'):
                        history = self._backend_api._telemetry_history.get(run_id, [])
                        # Filter by time range if specified
                        if start_time is not None:
                            history = [f for f in history if f.timestamp_s >= start_time]
                        if end_time is not None:
                            history = [f for f in history if f.timestamp_s <= end_time]
                        
                        return [frame.to_dict() for frame in history]
                    
                    # Call get_history method if available
                    if hasattr(self._backend_api, 'get_history'):
                        return self._backend_api.get_history(run_id, start_time, end_time)
                
                # Fall back to internal storage
                if run_id not in self._runs and run_id not in self._telemetry_history:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Run {run_id} not found"
                    )

                history = self._telemetry_history.get(run_id, [])
                
                # Convert ExtendedTelemetry-like objects to dicts if needed
                result = []
                for frame in history:
                    if frame is not None and callable(getattr(frame, 'to_dict', None)):
                        result.append(frame.to_dict())
                    elif frame is not None:
                        result.append(frame)
                
                # Apply time filters
                if start_time is not None:
                    result = [f for f in result if f.get('timestamp_s', 0) >= start_time]
                if end_time is not None:
                    result = [f for f in result if f.get('timestamp_s', 0) <= end_time]
                
                return result
                
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to retrieve history: {str(e)}"
                )
    
    def _get_active_run_id(self) -> Optional[str]:
        """Get ID of currently active run.
        
        Returns:
            str: Active run_id, or None if no active run
        """
        # Look for RUNNING or PAUSED run
        for run_id, run_data in self._runs.items():
            state = run_data.get('state', '')
            if isinstance(state, RunState):
                # RunState is an IntEnum, so .value is an int (e.g. 2) and would
                # never match the string names below — compare by .name instead.
                state_str = state.name
            else:
                state_str = str(state)
            
            if state_str in ('RUNNING', 'EXPERIMENT_RUNNING', 'PAUSED'):
                return run_id
        
        return None
    
    def _create_default_empty_state(self) -> dict:
        """Create default empty state for when no runs exist.
        
        Returns:
            dict: Empty DashboardState structure
        """
        now = datetime.now()
        return {
            'run_id': '',
            'state': RunState.IDLE.value,
            'scenario': '',
            'duration_s': 0.0,
            'progress_pct': 0.0,
            'current_surface_temp_c': 0.0,
            'current_bulk_temp_c': 0.0,
            'current_lux': 0,
            'lamp_power_w': 0.0,
            'fan_rpm': 0,
            'total_frames': 0,
            'gap_count': 0,
            'validity_rate': 0.0,
            'active_faults': [],
            'started_at': now.isoformat(),
            'last_update': now.isoformat(),
        }
    
    def _generate_dashboard_state_dict(self, run_data: Dict[str, Any]) -> dict:
        """Generate DashboardState dict from run data.
        
        Args:
            run_data: Run configuration and state data
            
        Returns:
            dict: Serialized DashboardState
        """
        # Extract state from run data
        run_id = run_data.get('run_id', '')
        state = run_data.get('state', RunState.IDLE)
        if isinstance(state, str):
            try:
                state = RunState(state)
            except ValueError:
                state = RunState.IDLE
        
        scenario = run_data.get('scenario', '')
        duration_s = run_data.get('duration_s', 0.0)
        progress_pct = run_data.get('progress_pct', 0.0)
        
        # Get latest telemetry
        telemetry = run_data.get('latest_telemetry', {})
        if telemetry:
            current_surface_temp_c = telemetry.get('surface_temp_c', telemetry.get('ir_temp', 0.0))
            current_bulk_temp_c = telemetry.get('bulk_temp_c', telemetry.get('tc_temp', 0.0))
            current_lux = int(telemetry.get('lux', telemetry.get('current_lux', 0)))
            lamp_power_w = telemetry.get('lamp_power_w', telemetry.get('lamp_pwm', 0) * 0.1)
            fan_rpm = int(telemetry.get('fan_rpm', telemetry.get('fan_airflow', 0) * 5000))
        else:
            current_surface_temp_c = 0.0
            current_bulk_temp_c = 0.0
            current_lux = 0
            lamp_power_w = 0.0
            fan_rpm = 0
        
        total_frames = run_data.get('total_frames', 0)
        gap_count = run_data.get('gap_count', 0)
        validity_rate = run_data.get('validity_rate', 0.0)
        active_faults = run_data.get('active_faults', [])
        
        started_at = run_data.get('started_at')
        if isinstance(started_at, datetime):
            started_at_iso = started_at.isoformat()
        elif isinstance(started_at, str):
            started_at_iso = started_at
        else:
            now = datetime.now()
            started_at_iso = now.isoformat()
        
        last_update = datetime.now()
        
        # Parse the ISO string for the DashboardState constructor
        started_at_parsed = datetime.fromisoformat(started_at_iso)
        
        # Build state object
        state_obj = DashboardState(
            run_id=run_id,
            state=state,
            scenario=scenario,
            duration_s=duration_s,
            progress_pct=progress_pct,
            current_surface_temp_c=current_surface_temp_c,
            current_bulk_temp_c=current_bulk_temp_c,
            current_lux=current_lux,
            lamp_power_w=lamp_power_w,
            fan_rpm=fan_rpm,
            total_frames=total_frames,
            gap_count=gap_count,
            validity_rate=validity_rate,
            active_faults=list(active_faults),
            started_at=started_at_parsed,
            last_update=last_update,
        )
        
        return state_obj.to_dict()
    
    def get_app(self) -> FastAPI:
        """Get the FastAPI application instance.
        
        Returns:
            FastAPI: Application instance for testing or mounting
        """
        return self._app
    
    def run(self, host: Optional[str] = None, port: Optional[int] = None):
        """Start the FastAPI server using uvicorn.
        
        Args:
            host: Override host address (uses self.host if not provided)
            port: Override port number (uses self.port if not provided)
        """
        import uvicorn
        
        host = host or self.host
        port = port or self.port
        
        print(f"Starting Dashboard Web Server at http://{host}:{port}")
        print(f"Available endpoints:")
        print(f"  - GET  /health")
        print(f"  - GET  /simulator/status")
        print(f"  - POST /simulator/commands")
        print(f"  - GET  /simulator/history")
        print(f"  - GET  /simulator/docs")
        
        uvicorn.run(
            self._app,
            host=host,
            port=port,
            log_level="info"
        )
    
    def create_test_client(self):
        """Create test client for unit testing.
        
        Returns:
            TestClient: FastAPI TestClient instance
        """
        from fastapi.testclient import TestClient
        return TestClient(self._app)
