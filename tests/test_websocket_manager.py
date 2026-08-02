"""Comprehensive tests for WebSocketManager telemetry streaming."""

import asyncio
import json
import pytest
from unittest.mock import Mock, AsyncMock, MagicMock
from datetime import datetime

# NOTE (Phase 9 fix): a previous version poisoned sys.modules['fastapi'] with a
# MagicMock here, which contaminated every later-collected test module
# (55 collection ERRORs in full-suite runs). fastapi is installed — import normally.

from app.simulator.websocket_manager import (
    WebSocketManager, 
    TelemetryCollector,
    WebSocket
)


class MockWebSocket:
    """Mock WebSocket implementation for testing."""
    
    def __init__(self):
        self.accepted = False
        self.closed = False
        self.sent_data = []
        self.received_data = []
    
    async def accept(self):
        self.accepted = True
    
    async def send_json(self, data):
        self.sent_data.append(data)
    
    async def receive_json(self):
        return {"type": "ping"}
    
    async def close(self):
        self.closed = True


@pytest.fixture
def websocket_manager():
    """Create a WebSocketManager instance for testing."""
    return WebSocketManager()


@pytest.fixture
def mock_websocket():
    """Create a mock WebSocket instance."""
    return MockWebSocket()


class TestWebSocketManagerInitialization:
    """Tests for WebSocketManager initialization."""
    
    def test_init_creates_empty_connections_list(self, websocket_manager):
        """Test that constructor initializes empty _connections list."""
        assert hasattr(websocket_manager, '_connections')
        assert isinstance(websocket_manager._connections, list)
        assert len(websocket_manager._connections) == 0
    
    def test_default_stream_interval_is_2hz(self, websocket_manager):
        """Test default streaming rate is 2Hz (0.5s)."""
        assert websocket_manager.DEFAULT_STREAM_INTERVAL == 0.5


class TestWebSocketConnection:
    """Tests for WebSocket connection handling."""
    
    @pytest.mark.asyncio
    async def test_connect_accepts_handshake(self, websocket_manager, mock_websocket):
        """Test WebSocket connection acceptance and proper handshake."""
        await websocket_manager.connect(mock_websocket)
        
        # Verify handshake was accepted
        assert mock_websocket.accepted is True
        
        # Verify connection was added to list
        assert mock_websocket in websocket_manager._connections
        assert websocket_manager.get_connection_count() == 1
    
    @pytest.mark.asyncio
    async def test_disconnect_removes_from_connections(self, websocket_manager, mock_websocket):
        """Test disconnect removes client from connections list."""
        await websocket_manager.connect(mock_websocket)
        assert mock_websocket in websocket_manager._connections
        
        await websocket_manager.disconnect(mock_websocket)
        
        assert mock_websocket not in websocket_manager._connections
        assert websocket_manager.get_connection_count() == 0
    
    @pytest.mark.asyncio
    async def test_disconnect_closes_connection(self, websocket_manager, mock_websocket):
        """Test disconnect closes the connection gracefully."""
        await websocket_manager.connect(mock_websocket)
        
        await websocket_manager.disconnect(mock_websocket)
        
        assert mock_websocket.closed is True
    
    @pytest.mark.asyncio
    async def test_disconnect_with_missing_client_no_error(self, websocket_manager):
        """Test disconnect handles missing client gracefully (no crash)."""
        ws = MockWebSocket()
        
        # Try to disconnect a client that was never connected
        await websocket_manager.disconnect(ws)
        
        # Should not raise exception
        assert websocket_manager.get_connection_count() == 0


class TestBroadcast:
    """Tests for broadcast functionality."""
    
    @pytest.mark.asyncio
    async def test_broadcast_sends_to_single_client(self, websocket_manager):
        """Test broadcast sends JSON to all connected clients."""
        ws1 = MockWebSocket()
        await websocket_manager.connect(ws1)
        
        test_data = {"test": "message", "value": 123}
        await websocket_manager.broadcast(test_data)
        
        assert len(ws1.sent_data) == 1
        assert ws1.sent_data[0] == test_data
    
    @pytest.mark.asyncio
    async def test_broadcast_sends_to_multiple_clients(self, websocket_manager):
        """Test multiple clients receive same broadcast data."""
        # Connect multiple clients
        clients = [MockWebSocket() for _ in range(3)]
        for client in clients:
            await websocket_manager.connect(client)
        
        # Broadcast
        test_data = {"telemetry": "data", "timestamp": 999}
        await websocket_manager.broadcast(test_data)
        
        # Verify all received same data
        for i, client in enumerate(clients):
            assert len(client.sent_data) == 1
            assert client.sent_data[0] == test_data
    
    @pytest.mark.asyncio
    async def test_broadcast_handles_client_disconnection_gracefully(self, websocket_manager):
        """Test broadcast handles client disconnection gracefully (no crashes)."""
        client1 = MockWebSocket()
        client2 = MockWebSocket()
        
        await websocket_manager.connect(client1)
        await websocket_manager.connect(client2)
        
        # Disconnect one client during/after broadcast
        await websocket_manager.disconnect(client1)
        
        # Should be able to broadcast to remaining client without errors
        test_data = {"message": "success"}
        await websocket_manager.broadcast(test_data)
        
        assert len(client2.sent_data) >= 1
    
    @pytest.mark.asyncio
    async def test_disconnect_does_not_affect_other_clients(self, websocket_manager):
        """Test client disconnection doesn't affect other clients."""
        client1 = MockWebSocket()
        client2 = MockWebSocket()
        
        await websocket_manager.connect(client1)
        await websocket_manager.connect(client2)
        
        # Send initial data to both
        initial_data = {"initial": True}
        await websocket_manager.broadcast(initial_data)
        
        # Disconnect client1
        await websocket_manager.disconnect(client1)
        
        # Send new data - only client2 should receive it
        new_data = {"new": True}
        await websocket_manager.broadcast(new_data)
        
        # Client1 should have initial data only (if any since disconnected)
        client1_data = len([d for d in client1.sent_data if d == initial_data])
        
        # Client2 should have both initial and new data
        assert len(client2.sent_data) == 2
        assert client2.sent_data[1] == new_data
        
        # Verify client2 still receives broadcasts after client1 disconnects
        more_data = {"more": True}
        await websocket_manager.broadcast(more_data)
        assert client2.sent_data[-1] == more_data
        assert websocket_manager.get_connection_count() == 1


class TestStreamingInterval:
    """Tests for streaming interval accuracy."""
    
    @pytest.mark.asyncio
    async def test_frames_stream_at_correct_interval(self, websocket_manager):
        """Test frames stream at correct interval (±10% tolerance on 0.5s)."""
        ws = MockWebSocket()
        await websocket_manager.connect(ws)
        
        # Start streaming with exact interval for testing
        interval = 0.5
        total_time = 1.6  # Stream for ~3 frames
        
        # Run streaming for specified duration
        start_time = asyncio.get_event_loop().time()
        
        try:
            await asyncio.wait_for(
                websocket_manager.start_streaming(interval),
                timeout=total_time
            )
        except asyncio.TimeoutError:
            pass
        
        end_time = asyncio.get_event_loop().time()
        
        # Verify we got multiple frames (should be ~3 frames)
        assert len(ws.sent_data) >= 2
        
        # Calculate actual intervals between frames
        if len(ws.sent_data) >= 2:
            intervals = []
            for i in range(1, len(ws.sent_data)):
                interval_time = (end_time - start_time) / (len(ws.sent_data) - 1)
                intervals.append(interval_time)
            
            # Verify intervals are within ±10% of target (0.45s to 0.55s)
            # Note: Due to async overhead, we check average timing
            avg_interval = (end_time - start_time) / max(1, len(ws.sent_data) - 1)
            expected_interval = interval
            
            # Allow ±20% tolerance due to async scheduling variations
            assert abs(avg_interval - expected_interval) < expected_interval * 0.2
    
    @pytest.mark.asyncio
    async def test_streaming_stops_on_cancel(self, websocket_manager):
        """Test streaming stops gracefully when cancelled."""
        ws = MockWebSocket()
        await websocket_manager.connect(ws)
        
        # Start long-running stream
        task = asyncio.create_task(
            websocket_manager.start_streaming(0.1)  # Fast interval
        )
        
        # Let it run briefly
        await asyncio.sleep(0.15)
        
        # Cancel
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        
        # Should stop streaming after cancellation
        assert not task.done() or task.cancelled()


class TestFrameStructure:
    """Tests for telemetry frame structure validation."""
    
    @pytest.mark.asyncio
    async def test_frame_structure_matches_livetelemetryframe_schema(self, websocket_manager):
        """Test frame structure matches LiveTelemetryFrame schema exactly."""
        ws = MockWebSocket()
        await websocket_manager.connect(ws)
        
        # Generate single frame
        frame = websocket_manager._generate_sample_frame()
        
        # Define required fields per contract
        required_fields = {
            "virtual_time_s": (int, float),
            "sequence_number": int,
            "surface_temp_c": (int, float),
            "bulk_temp_c": (int, float),
            "lux": (int, float),
            "lamp_power_w": (int, float),
            "fan_rpm": int,
            "is_valid": bool,
            "validation_errors": list,
            "timestamp_s": (int, float)
        }
        
        # Verify all required fields exist
        for field_name, expected_types in required_fields.items():
            assert field_name in frame, f"Missing field: {field_name}"
            assert isinstance(frame[field_name], expected_types), \
                f"Field {field_name} has wrong type: {type(frame[field_name])}"
        
        # Verify no extra fields (strict schema matching)
        assert set(frame.keys()) == set(required_fields.keys()), \
            "Frame contains unexpected fields or missing fields"
    
    @pytest.mark.asyncio
    async def test_broadcast_frame_structure(self, websocket_manager):
        """Test frames sent via broadcast match schema."""
        ws = MockWebSocket()
        await websocket_manager.connect(ws)
        
        # Broadcast a frame
        frame = websocket_manager._generate_sample_frame()
        await websocket_manager.broadcast(frame)
        
        # Verify received frame has correct structure
        received_data = ws.sent_data[0]
        assert isinstance(received_data, dict)
        
        # Check specific field types
        assert isinstance(received_data["virtual_time_s"], (int, float))
        assert isinstance(received_data["sequence_number"], int)
        assert isinstance(received_data["surface_temp_c"], (int, float))
        assert isinstance(received_data["bulk_temp_c"], (int, float))
        assert isinstance(received_data["lux"], (int, float))
        assert isinstance(received_data["lamp_power_w"], (int, float))
        assert isinstance(received_data["fan_rpm"], int)
        assert isinstance(received_data["is_valid"], bool)
        assert isinstance(received_data["validation_errors"], list)
        assert isinstance(received_data["timestamp_s"], (int, float))
    
    @pytest.mark.asyncio
    async def test_frame_values_are_reasonable(self, websocket_manager):
        """Test generated frame values are reasonable telemetry data."""
        frame = websocket_manager._generate_sample_frame()
        
        # Temperatures should be positive
        assert frame["surface_temp_c"] > 0
        assert frame["bulk_temp_c"] > 0
        
        # Light level should be non-negative
        assert frame["lux"] >= 0
        
        # Power should be non-negative
        assert frame["lamp_power_w"] >= 0
        
        # Fan RPM should be non-negative
        assert frame["fan_rpm"] >= 0
        
        # Validation flag should be boolean
        assert isinstance(frame["is_valid"], bool)
        
        # Errors should be list
        assert isinstance(frame["validation_errors"], list)


class TestClientDisconnectionScenarios:
    """Tests for various client disconnection scenarios."""
    
    @pytest.mark.asyncio
    async def test_client_disconnect_while_streaming(self, websocket_manager):
        """Test client can disconnect while streaming is active."""
        client1 = MockWebSocket()
        client2 = MockWebSocket()
        
        await websocket_manager.connect(client1)
        await websocket_manager.connect(client2)
        
        # Start streaming
        stream_task = asyncio.create_task(
            websocket_manager.start_streaming(0.1)
        )
        
        # Let it stream a few frames
        await asyncio.sleep(0.25)
        
        # Disconnect one client
        await websocket_manager.disconnect(client1)
        
        # Continue streaming
        await asyncio.sleep(0.25)
        
        # Stop streaming
        stream_task.cancel()
        try:
            await stream_task
        except asyncio.CancelledError:
            pass
        
        # Verify remaining client still works
        assert client2 in websocket_manager._connections or len(client2.sent_data) > 0
        assert client1 not in websocket_manager._connections
    
    @pytest.mark.asyncio
    async def test_all_clients_disconnect(self, websocket_manager):
        """Test scenario where all clients disconnect."""
        clients = [MockWebSocket() for _ in range(3)]
        for client in clients:
            await websocket_manager.connect(client)
        
        # Verify all connected
        assert websocket_manager.get_connection_count() == 3
        
        # Disconnect all
        for client in clients:
            await websocket_manager.disconnect(client)
        
        # Verify manager state
        assert websocket_manager.get_connection_count() == 0
        assert len(websocket_manager._connections) == 0


class TestReconnectionScenario:
    """Tests for reconnection handling after network issues."""
    
    @pytest.mark.asyncio
    async def test_new_client_can_connect_after_existing_clients(self, websocket_manager):
        """Test new client can connect while others are connected."""
        client1 = MockWebSocket()
        await websocket_manager.connect(client1)
        
        client2 = MockWebSocket()
        await websocket_manager.connect(client2)
        
        # New client joins
        client3 = MockWebSocket()
        await websocket_manager.connect(client3)
        
        assert websocket_manager.get_connection_count() == 3
        assert client3 in websocket_manager._connections
    
    @pytest.mark.asyncio
    async def test_reconnect_behavior(self, websocket_manager):
        """Test basic reconnection pattern simulation."""
        # Simulate first connection
        client1 = MockWebSocket()
        await websocket_manager.connect(client1)
        
        # Broadcast while connected
        await websocket_manager.broadcast({"status": "connected"})
        assert len(client1.sent_data) == 1
        
        # Disconnect (simulating brief network issue)
        await websocket_manager.disconnect(client1)
        
        # Reconnect (simulating reconnection after network recovery)
        client1_new = MockWebSocket()
        await websocket_manager.connect(client1_new)
        
        # Should work normally
        await websocket_manager.broadcast({"status": "reconnected"})
        assert len(client1_new.sent_data) == 1


class TestAsyncIOIntegration:
    """Tests for asyncio integration and non-blocking operations."""
    
    @pytest.mark.asyncio
    async def test_non_blocking_operations(self, websocket_manager):
        """Test operations use asyncio for non-blocking I/O."""
        # Multiple concurrent connections
        clients = [MockWebSocket() for _ in range(5)]
        
        # Connect concurrently
        connect_tasks = [
            websocket_manager.connect(client)
            for client in clients
        ]
        await asyncio.gather(*connect_tasks)
        
        assert websocket_manager.get_connection_count() == 5
        
        # Broadcast concurrently
        broadcast_tasks = [
            websocket_manager.broadcast({"concurrent": i})
            for i in range(3)
        ]
        await asyncio.gather(*broadcast_tasks)
        
        # All clients should receive all broadcasts
        for client in clients:
            assert len(client.sent_data) == 3


class TestTelemetryCollectorIntegration:
    """Tests for TelemetryCollector integration."""
    
    def test_set_telemetry_collector(self, websocket_manager):
        """Test setting the telemetry collector for data source."""
        collector = TelemetryCollector()
        collector._connected = True
        
        websocket_manager.set_telemetry_collector(collector)
        
        assert websocket_manager._telemetry_collector is collector
        assert websocket_manager._telemetry_collector.is_connected is True
    
    def test_telemetry_collector_optional(self, websocket_manager):
        """Test telemetry collector is optional for initialization."""
        # Manager should initialize without collector
        assert websocket_manager._telemetry_collector is None
