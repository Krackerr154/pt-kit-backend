"""Phase 5 discovery script - dispatch subagents for experiment modes & backend API."""

import json
from pathlib import Path
from hermes_tools import delegate_task


# Context you need for Phase 5 implementation
context_5_1 = """
Project: PT-Kit digital-twin simulator, working directory /home/Gerald154/Projects/pt-kit-backend.
Interface contract at app/simulator/INTERFACE_PHASE5.md (provided in this message).
Existing simulator structure includes: plant.py, controller_implementation.py (Task 3.1), 
virtual_uart.py (Task 4.1), esp32_bridge_simulator.py (Task 4.2), fault_injector.py (Task 4.3).
Use Python 3.11+, pytest, deterministic execution with fixed seed.

Focus: Implement Phase 5 Task 5.1 - Run supervisor orchestrator that manages experiment lifecycle,
handles remote commands (STOP, PAUSE, RESUME, RESTART, CONFIGURE), and coordinates component startup/shutdown.

Files to create:
- app/simulator/run_supervisor.py: ExperimentLifecycleController class
  • Manages RunState enum (IDLE → STARTING → RUNNING → PAUSED → COMPLETED/ABORTED)
  • Handles all remote commands from backend (see Task 5.3 interface)
  • Coordinates component startup/shutdown sequences
  • Maintains ExperimentRecord with full run history
  • Supports clean state transitions (no illegal state changes allowed)
  • Integrates with plant, controller, UART, ESP32 components
  • Records telemetry summaries and fault codes
  
- tests/test_run_supervisor.py: Comprehensive lifecycle tests
  • Test all valid state transitions (e.g., IDLE→STARTING→RUNNING→COMPLETED)
  • Test illegal transition rejection (e.g., IDLE→RUNNING without STARTING)
  • Test STOP command gracefully halts experiment (not ABORT!)
  • Test PAUSE/RESUME toggles correctly
  • Test RESTART resets to IDLE then STARTING
  • Test CONFIGURE updates runtime parameters mid-experiment
  • Verify no external dependencies (pure orchestration logic)

Contract from INTERFACE_PHASE5.md:
- RunState enum: IDLE(0), STARTING(1), RUNNING(2), PAUSED(3), COMPLETED(4), ABORTED(5), SUPERVISOR_ABORT(6)
- ExperimentRecord has: run_id, scenario, started_at, completed_at, duration_s, state, frame_count, error_message, etc.
- LifecycleController supports: start_experiments(), stop_experiment(), pause_experiment(), resume_experiment(), restart_experiment()
- All commands validated before applying (state machine invariant maintained)
- Determinism: fixed seed produces identical run histories

Exit criteria:
- All state transitions work correctly (valid transitions proceed, invalid rejected)
- STOP command handled gracefully without firmware ABORT
- PAUSE/RESUME toggling works reliably
- RESTART fully resets experiment to initial state
- CONFIGURE can update parameters during running experiment
- Full run history recorded in ExperimentRecord
- No external dependencies (orchestration logic isolated)
"""

context_5_2 = """
Project: PT-Kit digital-twin simulator, working directory /home/Gerald154/Projects/pt-kit-backend.
Interface contract at app/simulator/INTERFACE_PHASE5.md (provided in this message).
Existing structures: plant.py, controller_implementation.py, virtual_uart.py, esp32_bridge_simulator.py, fault_injector.py.
Use Python 3.11+, pytest, deterministic execution with fixed seed.

Focus: Implement Phase 5 Task 5.2 - Telemetry aggregator that collects frames from plant, sensors, controller,
validates ordering by timestamp, maintains circular buffer, supports export and history queries.

Files to create:
- app/simulator/telemetry_aggregator.py: TelemetryCollector class
  • Aggregates ExtendedTelemetry frames from plant, controller via VirtualUART
  • Validates timestamp ordering (monotonic within tolerance ±10ms)
  • Maintains circular buffer of last N seconds of frames (configurable default: 300s)
  • Detects and logs sequence gaps or out-of-order arrivals
  • Supports export as JSON, CSV, binary formats
  • Provides query interface: get_frames(start_time, end_time), get_summary(time_range)
  • Integrates with FaultInjector for error detection
  
- tests/test_telemetry_aggregator.py: Aggregator functionality tests
  • Test frame aggregation maintains monotonic timestamp order
  • Test circular buffer wraps correctly without data loss
  • Test gap detection when sequence numbers missing
  • Test export formats produce valid output files
  • Test query interface returns correct time-windowed data
  • Verify no external database dependencies
  • Determinism: same frames → identical aggregated results

Contract from INTERFACE_PHASE5.md:
- TelemetryCollector has methods: append_frame(frame), get_frames(start_time, end_time), export_json(path)
- Circular buffer size configurable (default 300s, ~720 frames at 2Hz)
- Timestamp validation tolerance ±10ms
- Export formats: JSON (full metadata), CSV (tabular), binary (compact)

Exit criteria:
- Frames aggregated in correct temporal order
- Circular buffer operates efficiently without memory leaks
- Gap detection works for missing frames
- Export formats validated (can parse output files)
- Query interface accurate for time-windowed retrievals
- No external dependencies (memory-only storage)
"""

context_5_3 = """
Project: PT-Kit digital-twin simulator, working directory /home/Gerald154/Projects/pt-kit-backend.
Interface contract at app/simulator/INTERFACE_PHASE5.md (provided in this message).
Existing structures: plant.py, controller_implementation.py, virtual_uart.py, esp32_bridge_simulator.py.
Use Python 3.11+, pytest, deterministic execution with fixed seed.

Focus: Implement Phase 5 Task 5.3 - Isolated backend API layer with REST endpoints that handle simulation-specific operations.
MUST enforce isolation (no /api/insert_data calls), support session pooling, validate incoming command payloads.

Files to create:
- app/simulator/isolated_backend_api.py: SimulatorBackendAPILayer class
  • Implements REST endpoints: POST /telemetry, PUT /runs/{id}, GET /runs/{id}/commands
    GET /runs/{id}/history, DELETE /runs/{id}
  • Enforces isolation: ALWAYS validates path starts with /api/simulator/*
  • Session pooling for performance (reuses requests.Session across calls)
  • Validates all incoming JSON payloads against schemas
  • Returns appropriate HTTP status codes (200 OK, 400 Bad Request, 404 Not Found, 500 Error)
  • Logs all API interactions for audit trail
  
- tests/test_isolated_backend_api.py: API endpoint tests
  • Test each endpoint handles valid requests correctly
  • Test invalid paths return 404 NOT found
  • Test /api/insert_data attempts are blocked (isolation enforced)
  • Test JSON payload validation rejects malformed requests
  • Test session pooling improves performance under load
  • Verify no actual network calls made (mock responses used)

Contract from INTERFACE_PHASE5.md:
- Endpoint paths: /api/simulator/telemetry (POST), /api/simulator/runs/{id} (PUT/DELETE)
           : /api/simulator/runs/{id}/commands (GET)
           : /api/simulator/runs/{id}/history (GET)
- MUST reject any path not starting with /api/simulator/
- Validation: strict schema checking for all request bodies
- Session pooling: maintain persistent connection for repeated calls
- Status codes: 200 success, 201 created, 400 bad request, 404 not found, 500 server error

Exit criteria:
- All endpoints functional and return correct status codes
- Isolation enforced (never allows /api/insert_data)
- Payload validation catches malformed requests
- Session pooling implemented and tested
- No network calls made (mocking verified)
"""

# Dispatch subagents
print("=" * 70)
print("DISPATCHING PHASE 5 SUBAGENTS")
print("=" * 70 + "\n")

task_5_1_result = delegate_task(context=context_5_1, goal="Implement Phase 5 Task 5.1: Run supervisor orchestrator", role="leaf")
print(f"✅ Task 5.1 dispatched: {task_5_1_result.get('delegation_id', 'N/A')}")

task_5_2_result = delegate_task(context=context_5_2, goal="Implement Phase 5 Task 5.2: Telemetry aggregator", role="leaf")
print(f"✅ Task 5.2 dispatched: {task_5_2_result.get('delegation_id', 'N/A')}")

task_5_3_result = delegate_task(context=context_5_3, goal="Implement Phase 5 Task 5.3: Isolated backend API layer", role="leaf")
print(f"✅ Task 5.3 dispatched: {task_5_3_result.get('delegation_id', 'N/A')}")

print("\n🚀 Waiting for subagent completion...")
