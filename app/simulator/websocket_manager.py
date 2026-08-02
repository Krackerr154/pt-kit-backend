"""WebSocket Manager for real-time telemetry streaming to dashboard clients."""

import asyncio
import json
from typing import List, Optional, Dict, Any
from datetime import datetime

try:
    from fastapi import WebSocket
except ImportError:
    # Mock for testing without FastAPI dependency
    class WebSocket:
        def __init__(self):
            self._closed = False
        
        async def accept(self):
            pass
        
        async def send_json(self, data: Any):
            pass
        
        async def receive_json(self) -> Dict:
            return {}
        
        async def close(self):
            self._closed = True


class TelemetryCollector:
    """Placeholder for Phase 5 TelemetryCollector integration."""
    
    def __init__(self):
        self._connected = False
    
    @property
    def is_connected(self) -> bool:
        return self._connected


class WebSocketManager:
    """
    WebSocket connection manager for real-time telemetry streaming.
    
    Manages multiple dashboard client connections and streams telemetry frames
    at configurable intervals (default 2Hz).
    """
    
    DEFAULT_STREAM_INTERVAL: float = 0.5  # 2Hz streaming rate
    
    def __init__(self):
        """Initialize WebSocket manager with empty connections list."""
        self._connections: List[WebSocket] = []
        self._telemetry_collector: Optional[TelemetryCollector] = None
        self._stop_event = asyncio.Event()
        self._streaming_task: Optional[asyncio.Task] = None
    
    def set_telemetry_collector(self, collector: TelemetryCollector) -> None:
        """Set the telemetry collector for data source integration."""
        self._telemetry_collector = collector
    
    async def connect(self, websocket: WebSocket) -> None:
        """
        Accept WebSocket connection and add to connections list.
        
        Args:
            websocket: The WebSocket instance to accept
        """
        await websocket.accept()
        self._connections.append(websocket)
    
    async def disconnect(self, websocket: WebSocket) -> None:
        """
        Remove client from connections and close gracefully.
        
        Args:
            websocket: The WebSocket instance to disconnect
        """
        if websocket in self._connections:
            self._connections.remove(websocket)
        try:
            await websocket.close()
        except Exception:
            pass  # Ignore errors during close
    
    async def broadcast(self, data: Any) -> None:
        """
        Send JSON data to all connected clients simultaneously.
        
        Args:
            data: JSON-serializable data to broadcast
        """
        disconnected_clients = []
        
        for connection in self._connections:
            try:
                await connection.send_json(data)
            except Exception:
                # Mark failed connections for cleanup
                disconnected_clients.append(connection)
        
        # Clean up any failed connections
        for client in disconnected_clients:
            if client in self._connections:
                self._connections.remove(client)
    
    def _generate_sample_frame(self) -> Dict[str, Any]:
        """
        Generate a sample telemetry frame matching LiveTelemetryFrame schema.
        
        Returns:
            dict matching the exact schema of LiveTelemetryFrame
        """
        current_time = datetime.utcnow()
        
        return {
            "virtual_time_s": current_time.timestamp(),
            "sequence_number": len(self._connections),  # Placeholder
            "surface_temp_c": 45.7,
            "bulk_temp_c": 38.2,
            "lux": 850.5,
            "lamp_power_w": 125.0,
            "fan_rpm": 2400,
            "is_valid": True,
            "validation_errors": [],
            "timestamp_s": current_time.timestamp()
        }
    
    async def start_streaming(self, interval: float) -> None:
        """
        Start continuous telemetry streaming to all connected clients.
        
        Args:
            interval: Streaming interval in seconds (default 0.5 for 2Hz)
        """
        self._stop_event.clear()
        
        while not self._stop_event.is_set():
            # Generate and broadcast telemetry frame
            frame = self._generate_sample_frame()
            await self.broadcast(frame)
            
            # Wait for next interval using non-blocking async sleep
            await asyncio.sleep(interval)
    
    async def stop_streaming(self) -> None:
        """Stop telemetry streaming gracefully."""
        self._stop_event.set()
        
        if self._streaming_task and not self._streaming_task.done():
            self._streaming_task.cancel()
            try:
                await self._streaming_task
            except asyncio.CancelledError:
                pass
    
    def get_connection_count(self) -> int:
        """Return number of currently connected clients."""
        return len(self._connections)
    
    async def handle_client(self, websocket: WebSocket) -> None:
        """
        Handle individual client connection lifecycle.
        
        This method should be called per client and handles:
        - Connection acceptance
        - Client disconnection cleanup
        
        Args:
            websocket: The WebSocket instance for this client
        """
        await self.connect(websocket)
        
        try:
            # Keep connection alive but don't process messages in this demo
            while not self._stop_event.is_set():
                await asyncio.sleep(0.1)
        except Exception:
            pass
        finally:
            await self.disconnect(websocket)
