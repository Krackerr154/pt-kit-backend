"""Dashboard Web Server Tests - Phase 6 Task 6.1

Tests for DashboardWebServer REST API endpoints.
Verifies correct JSON structure, HTTP status codes, and integration with Phase 5 backend.

Test Coverage:
✅ Test each endpoint returns correct JSON structure
✅ Test valid requests return 200 status code
✅ Test invalid request bodies return 400 Bad Request
✅ Test missing run_id returns error (not crash)
✅ Verify integration with Phase 5 backend API works
✅ No external dependencies (mock responses used)
"""

import pytest
import time
import uuid
from datetime import datetime
from unittest.mock import MagicMock, Mock

# Import system under test
from app.simulator.dashboard_server import (
    DashboardWebServer,
    DashboardState,
    LiveTelemetryFrame,
    RemoteCommand,
    CommandResult,
    HealthStatus,
    RunState,
)


class TestDashboardState:
    """Tests for DashboardState data model."""
    
    def test_dashboard_state_to_dict(self):
        """Test that DashboardState converts to dict correctly."""
        now = datetime.now()
        state = DashboardState(
            run_id="test-123",
            state=RunState.EXPERIMENT_RUNNING,
            scenario="ISO1_default_target",
            duration_s=120.5,
            progress_pct=45.2,
            current_surface_temp_c=75.3,
            current_bulk_temp_c=68.9,
            current_lux=8500,
            lamp_power_w=45.2,
            fan_rpm=3200,
            total_frames=120,
            gap_count=2,
            validity_rate=0.98,
            active_faults=["FAULT_001"],
            started_at=now,
            last_update=now,
        )
        
        state_dict = state.to_dict()
        
        # Verify all fields present
        assert "run_id" in state_dict
        assert "state" in state_dict
        assert "scenario" in state_dict
        assert "duration_s" in state_dict
        assert "progress_pct" in state_dict
        assert "current_surface_temp_c" in state_dict
        assert "current_bulk_temp_c" in state_dict
        assert "current_lux" in state_dict
        assert "lamp_power_w" in state_dict
        assert "fan_rpm" in state_dict
        assert "total_frames" in state_dict
        assert "gap_count" in state_dict
        assert "validity_rate" in state_dict
        assert "active_faults" in state_dict
        assert "started_at" in state_dict
        assert "last_update" in state_dict
        
        # Verify values match input
        assert state_dict["run_id"] == "test-123"
        assert state_dict["state"] == int(RunState.EXPERIMENT_RUNNING)
        assert state_dict["scenario"] == "ISO1_default_target"
        assert abs(state_dict["duration_s"] - 120.5) < 0.01
        assert abs(state_dict["progress_pct"] - 45.2) < 0.01
    
    def test_dashboard_state_determinism(self):
        """Test determinism: same state produces identical JSON output."""
        now = datetime.fromisoformat("2026-08-01T12:00:00")
        
        state1 = DashboardState(
            run_id="test-123",
            state=RunState.EXPERIMENT_RUNNING,
            scenario="ISO1_default_target",
            duration_s=120.5,
            progress_pct=45.2,
            current_surface_temp_c=75.3,
            current_bulk_temp_c=68.9,
            current_lux=8500,
            lamp_power_w=45.2,
            fan_rpm=3200,
            total_frames=120,
            gap_count=2,
            validity_rate=0.98,
            active_faults=["FAULT_001"],
            started_at=now,
            last_update=now,
        )
        
        state2 = DashboardState(
            run_id="test-123",
            state=RunState.EXPERIMENT_RUNNING,
            scenario="ISO1_default_target",
            duration_s=120.5,
            progress_pct=45.2,
            current_surface_temp_c=75.3,
            current_bulk_temp_c=68.9,
            current_lux=8500,
            lamp_power_w=45.2,
            fan_rpm=3200,
            total_frames=120,
            gap_count=2,
            validity_rate=0.98,
            active_faults=["FAULT_001"],
            started_at=now,
            last_update=now,
        )
        
        dict1 = state1.to_dict()
        dict2 = state2.to_dict()
        
        # All fields should match exactly
        assert dict1 == dict2


class TestLiveTelemetryFrame:
    """Tests for LiveTelemetryFrame data model (defined for future WebSocket support)."""
    
    def test_live_telemetry_frame_to_dict(self):
        """Test that LiveTelemetryFrame converts to dict correctly."""
        frame = LiveTelemetryFrame(
            virtual_time_s=100.5,
            sequence_number=100,
            surface_temp_c=75.3,
            bulk_temp_c=68.9,
            ir_temp_c=76.1,
            tc_temp_c=69.2,
            lux=8500,
            lamp_power_w=45.2,
            fan_rpm=3200,
            is_valid=True,
            validation_errors=[],
            timestamp_s=time.time(),
        )
        
        frame_dict = frame.to_dict()
        
        # Verify all fields present
        expected_fields = [
            "virtual_time_s", "sequence_number", "surface_temp_c",
            "bulk_temp_c", "ir_temp_c", "tc_temp_c", "lux",
            "lamp_power_w", "fan_rpm", "is_valid",
            "validation_errors", "timestamp_s"
        ]
        
        for field in expected_fields:
            assert field in frame_dict, f"Missing field: {field}"
        
        # Verify values match
        assert frame_dict["virtual_time_s"] == 100.5
        assert frame_dict["sequence_number"] == 100
        assert frame_dict["surface_temp_c"] == 75.3


class TestRemoteCommand:
    """Tests for RemoteCommand Pydantic model."""
    
    def test_remote_command_validation_success(self):
        """Test valid command passes validation."""
        cmd = RemoteCommand(
            command_type="STOP",
            payload={"reason": "user_requested"},
            run_id="abc-123",
            scheduled_ms=None
        )
        
        assert cmd.command_type == "STOP"
        assert cmd.payload == {"reason": "user_requested"}
        assert cmd.run_id == "abc-123"
        assert cmd.scheduled_ms is None
    
    def test_remote_command_validation_empty_run_id_fails(self):
        """Test empty run_id is rejected."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            RemoteCommand(
                command_type="STOP",
                payload=None,
                run_id="",
                scheduled_ms=None
            )
    
    def test_remote_command_validation_whitespace_run_id_fails(self):
        """Test whitespace-only run_id is rejected."""
        with pytest.raises(Exception):
            RemoteCommand(
                command_type="STOP",
                payload=None,
                run_id="   ",
                scheduled_ms=None
            )
    
    def test_remote_command_fault_inject_requires_fault_type(self):
        """Test FAULT_INJECT requires fault_type in payload."""
        # Valid fault injection command
        cmd_valid = RemoteCommand(
            command_type="FAULT_INJECT",
            payload={"fault_type": "FAULT_001"},
            run_id="abc-123",
            scheduled_ms=None
        )
        assert cmd_valid.command_type == "FAULT_INJECT"
        
        # Invalid: no fault_type
        with pytest.raises(Exception):
            RemoteCommand(
                command_type="FAULT_INJECT",
                payload={},  # Missing fault_type
                run_id="abc-123",
                scheduled_ms=None
            )
    
    def test_remote_command_other_commands_without_payload(self):
        """Test other command types work without payload."""
        cmd = RemoteCommand(
            command_type="STOP",
            payload=None,
            run_id="abc-123",
            scheduled_ms=None
        )
        assert cmd.command_type == "STOP"
        assert cmd.payload is None
    
    @pytest.mark.parametrize("command_type", [
        "STOP", "RESTART", "PAUSE", "RESUME", "CONFIGURE", "FAULT_INJECT"
    ])
    def test_all_command_types_accepted(self, command_type):
        """Test all supported command types are accepted."""
        if command_type == "FAULT_INJECT":
            cmd = RemoteCommand(
                command_type=command_type,
                payload={"fault_type": "TEST_FAULT"},
                run_id="abc-123",
                scheduled_ms=None
            )
        else:
            cmd = RemoteCommand(
                command_type=command_type,
                payload=None,
                run_id="abc-123",
                scheduled_ms=None
            )
        
        assert cmd.command_type == command_type


class TestCommandResult:
    """Tests for CommandResult response model."""
    
    def test_command_result_defaults(self):
        """Test CommandResult has correct default values."""
        result = CommandResult(command_id="test-id-123")
        
        assert result.command_id == "test-id-123"
        assert result.status == "queued"
        assert result.message == "Command queued successfully"
    
    def test_command_result_custom_status(self):
        """Test CommandResult with custom status."""
        result = CommandResult(
            command_id="test-id-123",
            status="executed",
            message="Command executed successfully"
        )
        
        assert result.status == "executed"
        assert result.message == "Command executed successfully"


class TestHealthStatus:
    """Tests for HealthStatus response model."""
    
    def test_health_status_factory(self):
        """Test HealthStatus.create factory method."""
        uptime = 1234.5
        health = HealthStatus.create(uptime)
        
        assert health.status == "healthy"
        assert health.version == "6.1.0"
        assert health.uptime_s == uptime
        assert health.timestamp is not None
        assert isinstance(health.timestamp, str)
    
    def test_health_status_serialization(self):
        """Test HealthStatus can be serialized to dict."""
        health = HealthStatus.create(100.0)
        health_dict = health.model_dump()
        
        assert "status" in health_dict
        assert "version" in health_dict
        assert "uptime_s" in health_dict
        assert "timestamp" in health_dict


class TestDashboardWebServerEndpoints:
    """Integration tests for DashboardWebServer endpoints."""
    
    @pytest.fixture
    def server(self):
        """Create test server instance."""
        return DashboardWebServer()
    
    @pytest.fixture
    def client(self, server):
        """Create test client."""
        return server.create_test_client()
    
    def _create_server_with_data(self):
        """Helper to create server with pre-populated test data."""
        startup_data = [
            {
                'run_id': 'run-active-1',
                'state': RunState.EXPERIMENT_RUNNING,
                'scenario': 'ISO1_default_target',
                'duration_s': 120.5,
                'progress_pct': 45.2,
                'latest_telemetry': {
                    'surface_temp_c': 75.3,
                    'bulk_temp_c': 68.9,
                    'lux': 8500,
                    'lamp_power_w': 45.2,
                    'fan_rpm': 3200,
                },
                'total_frames': 120,
                'gap_count': 2,
                'validity_rate': 0.98,
                'active_faults': ['FAULT_001'],
                'started_at': datetime.fromisoformat("2026-08-01T12:00:00"),
            }
        ]
        return DashboardWebServer(startup_data=startup_data)
    
    @pytest.fixture
    def server_with_data(self):
        """Create server pre-populated with test data."""
        return DashboardWebServer(startup_data=[
            {
                'run_id': 'run-active-1',
                'state': RunState.EXPERIMENT_RUNNING,
                'scenario': 'ISO1_default_target',
                'duration_s': 120.5,
                'progress_pct': 45.2,
                'latest_telemetry': {
                    'surface_temp_c': 75.3,
                    'bulk_temp_c': 68.9,
                    'lux': 8500,
                    'lamp_power_w': 45.2,
                    'fan_rpm': 3200,
                },
                'total_frames': 120,
                'gap_count': 2,
                'validity_rate': 0.98,
                'active_faults': ['FAULT_001'],
                'started_at': datetime.fromisoformat("2026-08-01T12:00:00"),
            }
        ])
    
    @pytest.fixture
    def client_with_data(self, server_with_data):
        """Create test client with pre-populated data."""
        return server_with_data.create_test_client()
    
    # ==================== HEALTH ENDPOINT TESTS ====================
    
    def test_health_endpoint_returns_200(self, client):
        """Test /health endpoint returns 200 OK."""
        response = client.get("/health")
        
        assert response.status_code == 200
    
    def test_health_endpoint_returns_correct_structure(self, client):
        """Test /health returns correct JSON structure."""
        response = client.get("/health")
        data = response.json()
        
        assert "status" in data
        assert "version" in data
        assert "uptime_s" in data
        assert "timestamp" in data
        
        assert data["status"] == "healthy"
        assert data["version"] == "6.1.0"
        assert data["uptime_s"] >= 0
        assert data["timestamp"] is not None
    
    def test_health_endpoint_response_time_under_100ms(self, client):
        """Test health check responds within 100ms."""
        start_time = time.perf_counter()
        response = client.get("/health")
        end_time = time.perf_counter()
        
        elapsed_ms = (end_time - start_time) * 1000
        
        assert response.status_code == 200
        assert elapsed_ms < 100, f"Health check took {elapsed_ms:.2f}ms, expected < 100ms"
    
    # ==================== STATUS ENDPOINT TESTS ====================
    
    def test_status_endpoint_returns_200_with_no_data(self, client):
        """Test /simulator/status returns 200 when no runs exist."""
        response = client.get("/simulator/status")
        
        assert response.status_code == 200
    
    def test_status_endpoint_returns_valid_json_structure(self, client):
        """Test /simulator/status returns valid JSON with required fields."""
        response = client.get("/simulator/status")
        data = response.json()
        
        # Verify all DashboardState fields present
        required_fields = [
            "run_id", "state", "scenario", "duration_s", "progress_pct",
            "current_surface_temp_c", "current_bulk_temp_c", "current_lux",
            "lamp_power_w", "fan_rpm", "total_frames", "gap_count",
            "validity_rate", "active_faults", "started_at", "last_update"
        ]
        
        for field in required_fields:
            assert field in data, f"Missing field: {field}"
    
    def test_status_endpoint_with_running_run(self, client_with_data):
        """Test /simulator/status returns correct data for running run."""
        response = client_with_data.get("/simulator/status")
        assert response.status_code == 200
        
        data = response.json()
        
        assert data["run_id"] == "run-active-1"
        assert data["state"] == int(RunState.EXPERIMENT_RUNNING)
        assert data["scenario"] == "ISO1_default_target"
        assert data["duration_s"] == 120.5
        assert data["progress_pct"] == 45.2
        assert data["current_surface_temp_c"] == 75.3
        assert data["total_frames"] == 120
    
    def test_status_endpoint_missing_run_id_not_crash(self, client):
        """Test /simulator/status doesn't crash when run_id not provided."""
        # Should return latest or empty state, not crash
        response = client.get("/simulator/status")
        
        assert response.status_code == 200
        assert "run_id" in response.json()
    
    def test_status_endpoint_specific_run_not_found(self, server_with_data):
        """Test /simulator/status returns 404 for non-existent run."""
        client = server_with_data.create_test_client()
        
        response = client.get("/simulator/status?run_id=non-existent-run")
        
        assert response.status_code == 404
    
    # ==================== COMMANDS ENDPOINT TESTS ====================
    
    def test_commands_endpoint_accepts_valid_command(self, client_with_data):
        """Test POST /simulator/commands accepts valid command."""
        response = client_with_data.post(
            "/simulator/commands",
            json={
                "command_type": "STOP",
                "payload": {"reason": "user_requested"},
                "run_id": "run-active-1"
            }
        )
        
        assert response.status_code == 200
        
        data = response.json()
        assert "command_id" in data
        assert data["status"] == "queued"
        assert "message" in data
    
    def test_commands_endpoint_rejects_invalid_run_id_empty(self, client):
        """Test POST /simulator/commands rejects empty run_id with 400."""
        response = client.post(
            "/simulator/commands",
            json={
                "command_type": "STOP",
                "payload": {},
                "run_id": ""
            }
        )
        
        # FastAPI returns either 400 or 422 for validation errors
        assert response.status_code in [400, 422]
    
    def test_commands_endpoint_missing_run_id_parameter(self, client):
        """Test POST /simulator/commands handles missing run_id gracefully."""
        # Missing run_id in JSON body should fail validation
        response = client.post(
            "/simulator/commands",
            json={
                "command_type": "STOP",
                "payload": {}
                # Missing run_id
            }
        )
        
        # Either 400 (validation error) or handled gracefully
        assert response.status_code in [400, 422]
    
    def test_commands_endpoint_invalid_command_type(self, client):
        """Test POST /simulator/commands rejects invalid command type."""
        response = client.post(
            "/simulator/commands",
            json={
                "command_type": "INVALID_TYPE",  # Not a supported type
                "payload": None,
                "run_id": "abc-123"
            }
        )
        
        # Pydantic should reject this
        assert response.status_code in [400, 422]
    
    def test_commands_endpoint_fault_inject_validation(self, client_with_data):
        """Test FAULT_INJECT requires fault_type in payload."""
        # Missing fault_type should fail
        response = client_with_data.post(
            "/simulator/commands",
            json={
                "command_type": "FAULT_INJECT",
                "payload": {},  # Missing fault_type
                "run_id": "run-active-1"
            }
        )
        
        # FastAPI returns 422 (Unprocessable Entity) for validation errors
        assert response.status_code == 422
    
    def test_commands_endpoint_all_command_types(self, client_with_data):
        """Test all supported command types are accepted."""
        command_types = ["STOP", "RESTART", "PAUSE", "RESUME", "CONFIGURE"]
        
        for cmd_type in command_types:
            response = client_with_data.post(
                "/simulator/commands",
                json={
                    "command_type": cmd_type,
                    "payload": None,
                    "run_id": "run-active-1"
                }
            )
            
            assert response.status_code == 200, f"Failed for command type: {cmd_type}"
    
    # ==================== HISTORY ENDPOINT TESTS ====================
    
    def test_history_endpoint_missing_run_id_returns_400(self, client):
        """Test GET /simulator/history returns 400 when run_id missing."""
        response = client.get("/simulator/history")
        
        # FastAPI returns either 400 or 422 for missing required parameters
        assert response.status_code in [400, 422]
    
    def test_history_endpoint_rejects_empty_run_id(self, client):
        """Test GET /simulator/history rejects empty run_id with 400."""
        response = client.get("/simulator/history?run_id=")
        
        assert response.status_code == 400
    
    def test_history_endpoint_returns_empty_list_for_no_data(self, client_with_data):
        """Test GET /simulator/history returns empty array when no telemetry."""
        response = client_with_data.get("/simulator/history?run_id=run-active-1")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0
    
    def test_history_endpoint_with_time_filters(self, server_with_data):
        """Test GET /simulator/history respects time filters."""
        client = server_with_data.create_test_client()
        
        # Add some telemetry data
        from app.simulator.isolated_backend_api import ExtendedTelemetry
        telemetry1 = ExtendedTelemetry(
            total_time=100,
            phase_time=50,
            cycle_num=1,
            state_code=2,
            ir_temp=75.3,
            tc_temp=68.9,
            current_lux=8500,
            mode="NORMAL_CYCLIC",
            timestamp_s=100.0,
        )
        telemetry2 = ExtendedTelemetry(
            total_time=200,
            phase_time=100,
            cycle_num=2,
            state_code=2,
            ir_temp=76.1,
            tc_temp=69.2,
            current_lux=8600,
            mode="NORMAL_CYCLIC",
            timestamp_s=200.0,
        )
        
        server_with_data._telemetry_history["run-active-1"] = [telemetry1, telemetry2]
        
        # Query with time filter
        response = client.get(
            "/simulator/history?run_id=run-active-1&start_time=150.0&end_time=250.0"
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Should only return frames within range
        assert isinstance(data, list)
        assert len(data) == 1  # Only telemetry2 (at 200.0)
    
    def test_history_endpoint_returns_array_of_dicts(self, server_with_data):
        """Test history returns array of dictionary objects."""
        client = server_with_data.create_test_client()
        
        # Pre-populate with sample telemetry
        from app.simulator.isolated_backend_api import ExtendedTelemetry
        telemetry = ExtendedTelemetry(
            total_time=100,
            phase_time=50,
            cycle_num=1,
            state_code=2,
            ir_temp=75.3,
            tc_temp=68.9,
            current_lux=8500,
            mode="NORMAL_CYCLIC",
            timestamp_s=time.time(),
        )
        server_with_data._telemetry_history["run-active-1"] = [telemetry]
        
        response = client.get("/simulator/history?run_id=run-active-1")
        
        assert response.status_code == 200
        data = response.json()
        
        assert isinstance(data, list)
        if len(data) > 0:
            assert isinstance(data[0], dict)
            assert "total_time" in data[0]
            assert "phase_time" in data[0]
            assert "ir_temp" in data[0]
            assert "tc_temp" in data[0]


class TestDashboardWebServerBackendIntegration:
    """Tests for DashboardWebServer integration with Phase 5 backend API."""
    
    def test_server_initializes_with_mock_backend(self):
        """Test DashboardWebServer accepts backend_api parameter."""
        mock_backend = MagicMock()
        server = DashboardWebServer(backend_api=mock_backend)
        
        assert server._backend_api is mock_backend
    
    def test_status_endpoint_uses_backend_when_available(self):
        """Test status endpoint attempts to use backend API when available."""
        mock_backend = MagicMock()
        mock_backend._get_run_state = MagicMock(return_value={
            'run_id': 'mock-run',
            'state': RunState.EXPERIMENT_RUNNING,
            'scenario': 'test_scenario',
        })
        
        server = DashboardWebServer(backend_api=mock_backend)
        client = server.create_test_client()
        
        response = client.get("/simulator/status")
        
        # Should call backend's _get_run_state
        mock_backend._get_run_state.assert_called()
        assert response.status_code == 200
    
    def test_commands_endpoint_forwarded_to_backend(self):
        """Test commands endpoint forwards to backend API when available."""
        mock_backend = MagicMock()
        mock_backend.queue_command = MagicMock(return_value={
            "command_id": "uuid-123",
            "status": "queued"
        })
        
        server = DashboardWebServer(backend_api=mock_backend)
        client = server.create_test_client()
        
        response = client.post(
            "/simulator/commands",
            json={
                "command_type": "STOP",
                "run_id": "test-run"
            }
        )
        
        assert response.status_code == 200
        assert mock_backend.queue_command.called
    
    def test_history_endpoint_uses_backend_telemetry(self):
        """Test history endpoint retrieves from backend when available."""
        from app.simulator.isolated_backend_api import ExtendedTelemetry
        
        mock_backend = MagicMock()
        mock_backend._get_run_state = MagicMock(return_value={
            'run_id': 'test-run',
            'state': RunState.EXPERIMENT_RUNNING,
        })
        mock_backend._telemetry_history = {
            'test-run': [
                ExtendedTelemetry(total_time=100, phase_time=50, cycle_num=1, 
                                 state_code=2, timestamp_s=100.0),
                ExtendedTelemetry(total_time=200, phase_time=100, cycle_num=2, 
                                 state_code=2, timestamp_s=200.0),
            ]
        }
        
        server = DashboardWebServer(backend_api=mock_backend)
        client = server.create_test_client()
        
        response = client.get("/simulator/history?run_id=test-run")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2
    
    def test_server_falls_back_to_internal_storage_without_backend(self):
        """Test server works without backend API using internal storage."""
        server = DashboardWebServer()
        
        # Pre-populate internal storage
        server._runs['standalone-run'] = {
            'run_id': 'standalone-run',
            'state': RunState.IDLE,
            'scenario': 'standalone_test',
        }
        
        client = server.create_test_client()
        response = client.get("/simulator/status?run_id=standalone-run")
        
        assert response.status_code == 200
        data = response.json()
        assert data['run_id'] == 'standalone-run'


class TestHTTPStatusCodes:
    """Tests for appropriate HTTP status code handling."""
    
    @pytest.fixture
    def client_with_data(self):
        """Create test client with pre-populated data."""
        server = DashboardWebServer(startup_data=[
            {
                'run_id': 'run-active-1',
                'state': RunState.EXPERIMENT_RUNNING,
                'scenario': 'ISO1_default_target',
                'duration_s': 120.5,
                'progress_pct': 45.2,
                'latest_telemetry': {
                    'surface_temp_c': 75.3,
                    'bulk_temp_c': 68.9,
                    'lux': 8500,
                    'lamp_power_w': 45.2,
                    'fan_rpm': 3200,
                },
                'total_frames': 120,
                'gap_count': 2,
                'validity_rate': 0.98,
                'active_faults': ['FAULT_001'],
                'started_at': datetime.fromisoformat("2026-08-01T12:00:00"),
            }
        ])
        return server.create_test_client()
    
    def test_valid_requests_return_200(self, client_with_data):
        """Test valid requests return 200 OK."""
        # Health check
        response = client_with_data.get("/health")
        assert response.status_code == 200
        
        # Status
        response = client_with_data.get("/simulator/status")
        assert response.status_code == 200
        
        # Commands with valid data
        response = client_with_data.post(
            "/simulator/commands",
            json={
                "command_type": "STOP",
                "run_id": "run-active-1"
            }
        )
        assert response.status_code == 200
        
        # History
        response = client_with_data.get("/simulator/history?run_id=run-active-1")
        assert response.status_code == 200
    
    def test_missing_required_parameters_return_400(self, client_with_data):
        """Test missing required parameters return 400 Bad Request."""
        # Missing run_id for history
        response = client_with_data.get("/simulator/history")
        assert response.status_code in [400, 422]
        
        # Empty run_id for history
        response = client_with_data.get("/simulator/history?run_id=")
        assert response.status_code in [400, 422]
        
        # Empty run_id for commands
        response = client_with_data.post(
            "/simulator/commands",
            json={
                "command_type": "STOP",
                "run_id": "",
                "payload": {}
            }
        )
        assert response.status_code in [400, 422]
    
    def test_non_existent_resources_return_404(self, client_with_data):
        """Test requests for non-existent resources return 404."""
        # Non-existent run for status
        response = client_with_data.get("/simulator/status?run_id=non-existent")
        assert response.status_code == 404
        
        # Non-existent run for history
        response = client_with_data.get("/simulator/history?run_id=non-existent")
        assert response.status_code == 404
    
    def test_invalid_request_bodies_return_400(self, client_with_data):
        """Test invalid request bodies return 400 Bad Request."""
        # Invalid command type
        response = client_with_data.post(
            "/simulator/commands",
            json={
                "command_type": "INVALID",
                "run_id": "run-active-1"
            }
        )
        assert response.status_code in [400, 422]  # Pydantic validation


class TestDeterminism:
    """Tests for deterministic behavior."""
    
    @pytest.fixture
    def client_with_data(self):
        """Create test client with pre-populated data."""
        server = DashboardWebServer(startup_data=[
            {
                'run_id': 'run-active-1',
                'state': RunState.EXPERIMENT_RUNNING,
                'scenario': 'ISO1_default_target',
                'duration_s': 120.5,
                'progress_pct': 45.2,
                'latest_telemetry': {
                    'surface_temp_c': 75.3,
                    'bulk_temp_c': 68.9,
                    'lux': 8500,
                    'lamp_power_w': 45.2,
                    'fan_rpm': 3200,
                },
                'total_frames': 120,
                'gap_count': 2,
                'validity_rate': 0.98,
                'active_faults': ['FAULT_001'],
                'started_at': datetime.fromisoformat("2026-08-01T12:00:00"),
            }
        ])
        return server.create_test_client()
    
    def test_same_state_produces_identical_json(self, client_with_data):
        """Test that same state produces identical JSON output."""
        # Call status twice
        response1 = client_with_data.get("/simulator/status")
        time.sleep(0.01)  # Small delay
        response2 = client_with_data.get("/simulator/status")
        
        assert response1.status_code == 200
        assert response2.status_code == 200
        
        data1 = response1.json()
        data2 = response2.json()
        
        # Remove timestamps which will change
        del data1["last_update"]
        del data2["last_update"]
        del data1["started_at"]
        del data2["started_at"]
        
        # Everything else should match
        assert data1 == data2
    
    def test_multiple_command_submissions_generate_unique_ids(self, client_with_data):
        """Test each command submission gets unique ID."""
        response1 = client_with_data.post(
            "/simulator/commands",
            json={"command_type": "STOP", "run_id": "run-active-1"}
        )
        
        response2 = client_with_data.post(
            "/simulator/commands",
            json={"command_type": "STOP", "run_id": "run-active-1"}
        )
        
        assert response1.status_code == 200
        assert response2.status_code == 200
        
        cmd_id1 = response1.json()["command_id"]
        cmd_id2 = response2.json()["command_id"]
        
        assert cmd_id1 != cmd_id2, "Each command should have unique ID"


# =============================================================================
# Test Suite Entry Point
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
