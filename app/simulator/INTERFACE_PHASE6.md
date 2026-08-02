# Phase 6 Interface Contract: Dashboard Integration Layer at /simulator

This document defines the interfaces for Phase 6 implementation so parallel subagents produce compatible code.

## Overview

Phase 6 implements the **Dashboard Integration Layer** - a web-based visualization and control interface accessible at `/simulator` path. This layer provides real-time monitoring of experiment state, telemetry display, remote command submission UI, and historical analysis tools.

The architecture adds a lightweight web server that:
- Serves static dashboard UI (HTML/JS/CSS)
- Provides WebSocket API for real-time telemetry streaming
- Handles HTTP REST endpoints for dashboard operations
- Integrates with simulator backend API (Phase 5) for data retrieval
- Never touches production databases or physical hardware

```
Browser → Web Server (/simulator) ←→ Simulator Backend API (Phase 5)
           ↓                              ↓
      Dashboard UI              Experiment Lifecycle Control
```

---

## Core Data Models

### DashboardState Schema

```python
@dataclass
class DashboardState:
    """Current state view for dashboard visualization."""
    
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
        return {
            'run_id': self.run_id,
            'state': int(self.state),
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
```

### LiveTelemetryFrame Schema

```python
@dataclass
class LiveTelemetryFrame:
    """Single frame for WebSocket streaming."""
    
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
        return {f.name: getattr(self, f.name) for f in self.__dataclass_fields__.values()}
```

---

## API Interfaces

### DashboardWebServer

```python
class DashboardWebServer:
    """Lightweight web server serving dashboard UI and real-time APIs.
    
    Features:
    - Static file serving at /simulator path
    - WebSocket endpoint for live telemetry streaming
    - REST endpoints for experiment control
    - Health check endpoint (/health)
    - Metrics endpoint (/metrics)
    """
    
    def __init__(self, host: str = "127.0.0.1", port: int = 8080):
        self.host = host
        self.port = port
        self._app = fastapi.FastAPI()
        self._ws_manager = WebSocketManager()
        self._backend_api: Optional[SimulatorBackendAPILayer] = None
        
        self._setup_routes()
    
    def _setup_routes(self):
        """Configure FastAPI routes for dashboard."""
        
        @self._app.get("/simulator")
        async def get_dashboard_index():
            """Serve main dashboard HTML page."""
            return FileResponse("dashboard/index.html")
        
        @self._app.get("/simulator/status")
        async def get_status(run_id: Optional[str] = None) -> Dict[str, Any]:
            """Get current dashboard state (with optional specific run)."""
            if not run_id:
                # Return latest running experiment
                run_id = self._get_active_run_id()
            
            state = self._generate_dashboard_state(run_id)
            return JSONResponse(content=state.to_dict())
        
        @self._app.websocket("/simulator/ws/telemetry")
        async def websocket_telemetry(websocket: WebSocket):
            """WebSocket endpoint for real-time telemetry streaming."""
            await self._ws_manager.connect(websocket)
            try:
                while True:
                    # Stream latest frames at configurable interval
                    data = await self._get_latest_telemetry_frame()
                    await websocket.send_json(data.to_dict())
                    await asyncio.sleep(0.5)  # 2Hz update rate
            except WebSocketDisconnect:
                self._ws_manager.disconnect(websocket)
        
        @self._app.post("/simulator/commands")
        async def submit_command(command: RemoteCommand) -> Dict[str, str]:
            """Submit remote command to experiment controller."""
            result = self._backend_api.submit_command(command)
            return {"command_id": result.command_id}
        
        @self._app.get("/simulator/history")
        async def get_history(
            run_id: str,
            start_time: Optional[float] = None,
            end_time: Optional[float] = None
        ) -> List[Dict[str, Any]]:
            """Retrieve telemetry history for visualization."""
            frames = self._backend_api.get_history(run_id, start_time, end_time)
            return [frame.to_dict() for frame in frames]
        
        @self._app.get("/simulator/metrics")
        async def get_metrics() -> Dict[str, Any]:
            """Return server metrics (request counts, uptime, etc.)."""
            return {
                "server_uptime_s": time.time() - self._start_time,
                "total_requests": self._request_counter,
                "active_websockets": len(self._ws_manager.connections),
                "buffer_usage_pct": self._get_buffer_usage(),
            }
        
        @self._app.get("/health")
        async def health_check():
            """Simple health check endpoint."""
            return {"status": "healthy", "version": "6.0.0"}
```

### WebSocketManager

```python
class WebSocketManager:
    """Manages multiple WebSocket connections for real-time streaming."""
    
    def __init__(self):
        self._connections: List[WebSocket] = []
        self._lock = asyncio.Lock()
    
    async def connect(self, websocket: WebSocket):
        """Accept new WebSocket connection."""
        await websocket.accept()
        async with self._lock:
            self._connections.append(websocket)
    
    async def disconnect(self, websocket: WebSocket):
        """Remove WebSocket connection."""
        async with self._lock:
            if websocket in self._connections:
                self._connections.remove(websocket)
        await websocket.close()
    
    async def broadcast(self, data: Dict[str, Any]):
        """Broadcast data to all connected clients."""
        async with self._lock:
            for conn in self._connections:
                try:
                    await conn.send_json(data)
                except Exception:
                    pass  # Skip disconnected clients
```

### StaticAssetsProvider

```python
class StaticAssetsProvider:
    """Serves dashboard static files (HTML, CSS, JS).
    
    Directory structure:
    /simulator/
      index.html          - Main dashboard application
      app.js              - React/Vue/Vanilla JS logic
      styles.css          - Styling and layout
      components/         - Reusable UI components
        chart.js          - Telemetry chart component
        controls.js       - Command submission controls
        status_panel.js   - Experiment status display
    """
    
    def __init__(self, base_path: Path = Path(__file__).parent / "dashboard"):
        self.base_path = base_path
    
    def get_asset(self, path: str) -> bytes:
        """Load static asset from filesystem."""
        full_path = self.base_path / path
        
        if not full_path.exists():
            raise FileNotFoundError(f"Asset not found: {path}")
        
        return full_path.read_bytes()
    
    def get_content_type(self, path: str) -> str:
        """Determine MIME type based on file extension."""
        ext = Path(path).suffix.lower()
        mime_types = {
            '.html': 'text/html',
            '.css': 'text/css',
            '.js': 'application/javascript',
            '.json': 'application/json',
            '.png': 'image/png',
            '.svg': 'image/svg+xml',
        }
        return mime_types.get(ext, 'application/octet-stream')
```

---

## Integration Points

### From Phase 5 Components

```python
# Dashboard server integrates with simulator backend API
dashboard_server = DashboardWebServer(
    host="127.0.0.1",
    port=8080,
    backend_api=isolated_backend_api_layer  # From Phase 5
)

# WebSocket manager streams from telemetry collector
websocket_manager = WebSocketManager()
telemetry_collector = TelemetryCollector()  # From Phase 5
```

### Dashboard UI Requirements

**Frontend Stack Options:**
- Vanilla JavaScript (preferred for simplicity/no dependencies)
- OR Vue.js/React if framework support needed

**Core UI Components:**
1. **Status Panel**: Display experiment state (IDLE/RUNNING/PAUSED), duration, progress bar
2. **Real-time Charts**: Line charts for temperature, lux, lamp power over virtual time
3. **Command Console**: Form to submit PAUSE/RESUME/STOP commands with payload validation
4. **History Viewer**: Time-slider to browse past telemetry frames, export to CSV
5. **Fault Log**: Scrollable log showing detected faults with timestamps
6. **Metrics Dashboard**: Request count, WebSocket connections, buffer utilization %

---

## Exit Criteria Checklist

✅ Dashboard serves at `/simulator` path without errors  
✅ Status endpoint returns valid DashboardState JSON  
✅ WebSocket /simulator/ws/telemetry streams at 2Hz without lag  
✅ Command submission validates payloads against schemas  
✅ History viewer queries backend API for time-windowed data  
✅ All requests logged with timestamps for audit trail  
✅ Health check responds within 100ms  
✅ No external npm packages required (vanilla JS preferred)  
✅ Deterministic: same input produces identical UI state  
✅ No database writes (only reads from simulator state)  

---

## Performance Targets

| Metric | Target | Measurement Method |
|--------|--------|-------------------|
| Dashboard load time | < 500ms | Time from request to DOM ready |
| WebSocket latency | < 100ms average | Time from frame generated to client receive |
| Command response time | < 50ms | POST to acknowledgment |
| History query performance | < 1s for 1 hour | Full hour of 2Hz data retrieval |
| Concurrent connections | ≥ 10 browsers | Load test with multiple clients |
| Memory usage | < 100 MB per instance | RSS monitoring under load |
| CPU usage | < 5% single core | Monitoring during steady-state streaming |

---

## Testing Requirements

### Unit Tests (Task 6.1: Web Server Core)
- Test all REST endpoints return correct status codes
- Test WebSocket connection acceptance/rejection
- Test broadcast to multiple connected clients
- Test health check returns healthy status
- Verify no database/external dependencies

### Unit Tests (Task 6.2: WebSocket Streaming)
- Test telemetry frames stream at configured interval (default 2Hz)
- Test frame structure matches LiveTelemetryFrame schema
- Test client disconnection handling (no crashes)
- Test reconnection after brief network issues
- Verify frame ordering maintained (monotonic timestamps)

### Unit Tests (Task 6.3: Static Assets & UI Components)
- Test static file serving (HTML/CSS/JS) returns correct MIME types
- Test dashboard loads without JavaScript errors
- Test command forms validate inputs before submission
- Test charts render data points correctly
- Test history viewer displays timeline accurately

---

## Security Considerations

- **Authentication**: Optional basic auth header for local deployment (configurable)
- **CORS**: Restrict origins to localhost by default
- **Rate Limiting**: Prevent WebSocket spamming (max 10 msgs/sec per client)
- **Input Validation**: Strictly validate all command payloads against schemas
- **XSS Prevention**: Escape all user inputs in HTML responses
- **Audit Logging**: Log all command submissions with client IP/user info

---

*Document Version: 1.0 | Created: 2026-08-01 | PT-Kit Phase 6 Deliverable*
