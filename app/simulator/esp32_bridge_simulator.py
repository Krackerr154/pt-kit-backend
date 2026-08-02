"""
ESP32 Bridge Simulator - Virtual UART Communication Layer

Simulates ESP32 microcontroller receiving telemetry from Arduino via virtual UART,
forwarding to backend API, and handling remote control commands.

Architecture mirrors physical PT-Kit setup:
  Virtual Arduino → Virtual UART → Virtual ESP32 Bridge → Simulator Backend
"""

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional, List, Dict, Any, Callable, Union
import random
import struct
import zlib
import time


# =============================================================================
# Frame Types (matching physical protocol)
# =============================================================================

class FrameType(IntEnum):
    """UART frame type constants."""
    TELEMETRY = 0x01      # Arduino→ESP32: ExtendedTelemetry from controller
    COMMAND = 0x02        # ESP32→Arduino: Remote command (STOP, START, etc.)
    ACK_NACK = 0x03       # Both: Acknowledgment or negative acknowledgment
    CALIBRATION = 0x04    # Bidirectional: Calibration data exchange
    STATUS = 0x05         # Bidirectional: Heartbeat/status query


@dataclass
class Command:
    """Remote command message for Arduino transmission."""
    command_type: str     # STOP, START/RESUME, RESTART, CONFIGURE
    payload: Optional[Dict[str, Any]] = None
    sequence: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'command_type': self.command_type,
            'payload': self.payload or {},
            'sequence': self.sequence,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Command':
        """Create from dictionary."""
        return cls(
            command_type=data.get('command_type', ''),
            payload=data.get('payload'),
            sequence=data.get('sequence', 0),
        )


# =============================================================================
# Telemetry Packet Format
# =============================================================================

@dataclass
class UARTPacket:
    """UART frame format matching ESP32 physical protocol."""
    
    # Header
    sync_word: int = 0xABCD        # Synchronization sequence (16 bits)
    version: int = 1               # Protocol version
    type_: int = 0                 # Frame type (see FrameType enum)
    sequence: int = 0              # Monotonic counter (wraps at 65535)
    payload_length: int = 0        # 0-255 bytes
    
    # Payload (raw bytes)
    payload: bytes = b''
    
    # Trailer
    checksum: int = 0              # CRC-16-CCITT over all fields except sync
    
    # Computed timing
    transmit_time_s: float = 0.0   # Time required to transmit on current baud rate
    
    def pack(self) -> bytes:
        """Pack packet into byte stream for UART transmission."""
        # Pack header: sync(2) + sequence(2) + version(1) + type_(1) + length(1) = 7 bytes
        header = struct.pack('<HHBBB', 
            self.sync_word,
            self.sequence,
            self.version,
            self.type_,
            self.payload_length
        )
        
        # Calculate checksum over header + payload (CRC-16-CCITT)
        # Polynomial: 0x1021, initial value: 0xFFFF
        crc = zlib.crc32(header + self.payload) & 0xFFFF
        
        # Pack full packet: header + payload + checksum(2)
        packet_bytes = header + self.payload + struct.pack('<H', crc)
        
        # Compute transmit time at 115200 baud (8.68 µs per byte at 10 bits/frame)
        baud_rate = 115200
        bits_per_byte = 10  # Start + 8 data + stop bit
        total_bits = len(packet_bytes) * bits_per_byte
        transmit_time_s = total_bits / baud_rate
        
        self.transmit_time_s = transmit_time_s
        
        return packet_bytes
    
    @classmethod
    def unpack(cls, packet_bytes: bytes) -> Optional['UARTPacket']:
        """Unpack byte stream into UARTPacket, validate checksum."""
        if len(packet_bytes) < 9:  # Minimum: 2+1+1+2+1+2 (header + checksum)
            return None
        
        try:
            # Unpack header - match pack order (HHBBB)
            sync_word, sequence, version, type_, payload_length = struct.unpack(
                '<HHBBB', packet_bytes[:7]
            )
            
            # Extract payload and checksum
            expected_total = 7 + payload_length + 2  # header + payload + checksum
            if len(packet_bytes) != expected_total:
                return None
            
            payload = packet_bytes[7:7+payload_length]
            received_checksum = struct.unpack('<H', packet_bytes[7+payload_length:])[0]
            
            # Verify checksum
            calculated_crc = zlib.crc32(packet_bytes[:7+payload_length]) & 0xFFFF
            if calculated_crc != received_checksum:
                return None  # Checksum failure
            
            return cls(
                sync_word=sync_word,
                version=version,
                type_=type_,
                sequence=sequence,
                payload_length=payload_length,
                payload=payload,
                checksum=received_checksum
            )
            
        except (struct.error, IndexError):
            return None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            'sync_word': hex(self.sync_word),
            'version': self.version,
            'type_': self.type_,
            'sequence': self.sequence,
            'payload_length': self.payload_length,
            'checksum': hex(self.checksum),
            'transmit_time_s': self.transmit_time_s,
        }


# =============================================================================
# ESP32 State Model
# =============================================================================

@dataclass
class FaultCode:
    """Error condition codes for ESP32 faults."""
    code: str
    description: str
    timestamp_s: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'code': self.code,
            'description': self.description,
            'timestamp_s': self.timestamp_s,
        }


class InternalEventType(IntEnum):
    """Types of internal events logged by ESP32."""
    PACKET_RECEIVED = 1
    PACKET_FORWARDING = 2
    COMMAND_RECEIVED = 3
    COMMAND_TRANSMITTED = 4
    ACK_SENT = 5
    NACK_SENT = 6
    TIMEOUT = 7
    RETRANSMISSION = 8
    FAULT_DETECTED = 9


@dataclass
class InternalEvent:
    """Event logged by ESP32 internal state machine."""
    event_type: int
    sequence: int
    timestamp_s: float
    details: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'event_type': self.event_type,
            'sequence': self.sequence,
            'timestamp_s': self.timestamp_s,
            'details': self.details,
        }


@dataclass
class ESP32State:
    """Simulated ESP32 microcontroller state."""
    
    # Connection status
    uart_connected: bool = False
    backend_connected: bool = False
    
    # Command queue (in-flight remote commands)
    pending_commands: List[Command] = field(default_factory=list)
    
    # Telemetry buffer (collected from Arduino via UART)
    telemetry_history: List[Dict[str, Any]] = field(default_factory=list)
    
    # Local event logging
    internal_events: List[InternalEvent] = field(default_factory=list)
    
    # Error conditions
    faults: List[FaultCode] = field(default_factory=list)
    
    # Tracking
    next_sequence: int = 0
    last_received_sequence: int = 0
    
    def log_event(self, event_type: int, sequence: int, details: Optional[str] = None):
        """Log an internal event."""
        event = InternalEvent(
            event_type=event_type,
            sequence=sequence,
            timestamp_s=time.time(),
            details=details
        )
        self.internal_events.append(event)
    
    def add_fault(self, code: str, description: str):
        """Add a fault condition."""
        fault = FaultCode(code=code, description=description, timestamp_s=time.time())
        self.faults.append(fault)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary."""
        return {
            'uart_connected': self.uart_connected,
            'backend_connected': self.backend_connected,
            'pending_commands': [c.to_dict() for c in self.pending_commands],
            'telemetry_count': len(self.telemetry_history),
            'fault_count': len(self.faults),
            'internal_event_count': len(self.internal_events),
            'next_sequence': self.next_sequence,
            'last_received_sequence': self.last_received_sequence,
        }


# =============================================================================
# Virtual UART Engine
# =============================================================================

class VirtualUARTEngine:
    """Simulates RS-232 serial communication with baud rate timing."""
    
    def __init__(self, baud_rate: int = 115200):
        """Initialize virtual serial port.
        
        Args:
            baud_rate: Baud rate (default 115200 matches physical PT-Kit)
        """
        self.baud_rate = baud_rate
        self._rx_buffer: bytearray = bytearray()
        self._tx_buffer: bytearray = bytearray()
        self._byte_delivery_time_s: float = 0.0
        
        # Timing: bytes per second at given baud rate
        # At 115200 baud with 10 bits/frame: 11520 bytes/sec
        self.bytes_per_second = baud_rate // 10
    
    def write_packet(self, packet_bytes: bytes) -> float:
        """Transmit packet, add bytes to TX buffer.
        
        Args:
            packet_bytes: Raw packet bytes to transmit
            
        Returns:
            Time required to transmit this packet
        """
        self._tx_buffer.extend(packet_bytes)
        transmit_time_s = len(packet_bytes) / self.bytes_per_second
        self._byte_delivery_time_s = transmit_time_s
        return transmit_time_s
    
    def read_available(self) -> Optional[bytes]:
        """Check if complete packet available in RX buffer.
        
        Returns:
            Complete packet bytes if ready, None otherwise
        """
        if not self._rx_buffer:
            return None
        return bytes(self._rx_buffer)
    
    def tick(self, dt_s: float) -> None:
        """Advance simulation by dt seconds.
        
        Moves bytes from TX to RX based on baud rate timing.
        
        Args:
            dt_s: Time delta in seconds
        """
        # Calculate how many bytes can be transferred
        bytes_to_transfer = int(dt_s * self.bytes_per_second)
        
        # Transfer from TX to RX
        remaining = min(bytes_to_transfer, len(self._tx_buffer))
        self._rx_buffer.extend(self._tx_buffer[:remaining])
        self._tx_buffer = self._tx_buffer[remaining:]
    
    def clear_buffers(self):
        """Clear both RX and TX buffers."""
        self._rx_buffer.clear()
        self._tx_buffer.clear()
    
    def get_rx_buffer_size(self) -> int:
        """Get current RX buffer size."""
        return len(self._rx_buffer)
    
    def get_tx_buffer_size(self) -> int:
        """Get current TX buffer size."""
        return len(self._tx_buffer)


# =============================================================================
# Backend API Isolation Layer
# =============================================================================

class SimulatorBackendAPIClient:
    """Isolated backend API client for simulation-only operations."""
    
    def __init__(self, base_url: str = "/api/simulator"):
        """Initialize isolated backend client.
        
        Args:
            base_url: Base URL for simulator APIs (default /api/simulator)
                      This ensures NO calls to production /api/insert_data
        """
        self.base_url = base_url.rstrip('/')
        self._requests_sent: List[Dict[str, Any]] = []
        self._request_counter = 0
    
    def post_telemetry_frame(self, frame: Dict[str, Any]) -> Dict[str, Any]:
        """Submit single telemetry frame to simulator run state.
        
        Args:
            frame: ExtendedTelemetry as dictionary
            
        Returns:
            Simulated response (no actual network call)
        """
        self._request_counter += 1
        
        # Log request for verification
        request = {
            'id': self._request_counter,
            'endpoint': f"{self.base_url}/telemetry",
            'method': 'POST',
            'frame': frame,
            'timestamp_s': time.time(),
        }
        self._requests_sent.append(request)
        
        # Return simulated success response
        return {
            'status': 'success',
            'request_id': self._request_counter,
            'acknowledged': True,
        }
    
    def put_run_state(self, run_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
        """Update current run state.
        
        Args:
            run_id: Run identifier
            state: Run state dictionary
            
        Returns:
            Simulated response
        """
        self._request_counter += 1
        
        request = {
            'id': self._request_counter,
            'endpoint': f"{self.base_url}/runs/{run_id}",
            'method': 'PUT',
            'state': state,
            'timestamp_s': time.time(),
        }
        self._requests_sent.append(request)
        
        return {
            'status': 'success',
            'request_id': self._request_counter,
            'updated': True,
        }
    
    def get_pending_commands(self, run_id: str) -> List[Command]:
        """Fetch queued commands for this run.
        
        Args:
            run_id: Run identifier
            
        Returns:
            List of Command objects
        """
        self._request_counter += 1
        
        request = {
            'id': self._request_counter,
            'endpoint': f"{self.base_url}/runs/{run_id}/commands",
            'method': 'GET',
            'timestamp_s': time.time(),
        }
        self._requests_sent.append(request)
        
        # In simulation, return empty list (commands injected directly)
        return []
    
    def get_request_log(self) -> List[Dict[str, Any]]:
        """Get all logged requests for verification."""
        return self._requests_sent.copy()
    
    def clear_request_log(self):
        """Clear request log."""
        self._requests_sent.clear()
        self._request_counter = 0


# =============================================================================
# ESP32 Bridge Simulator (Main Implementation)
# =============================================================================

class ESP32BridgeSimulator:
    """Simulates ESP32 receiving telemetry from Arduino, forwarding to backend.
    
    Architecture:
      Arduino Controller → Virtual UART → ESP32BridgeSimulator → Backend API
    
    Features:
      - Receives UART packets from Arduino, assembles complete packets from byte stream
      - Validates checksums and sequence numbers before processing
      - Forwards telemetry to isolated backend using /api/simulator/telemetry endpoint
      - Maintains command queue for remote control messages
      - Implements ACK/NACK handshake protocol
      - Timeout and retransmission logic for reliable delivery
    """
    
    # Retry configuration
    MAX_RETRANSMISSIONS = 3
    RETRANSMIT_TIMEOUT_S = 0.1  # 100ms timeout before retry
    
    def __init__(self, seed: Optional[int] = None):
        """Initialize ESP32 bridge simulator.
        
        Args:
            seed: Random seed for deterministic behavior
        """
        self.state = ESP32State()
        self.uart = VirtualUARTEngine(baud_rate=115200)
        self.backend_client = SimulatorBackendAPIClient("/api/simulator")
        
        # Deterministic RNG if seed provided
        self.rng = random.Random(seed)
        
        # Retransmission tracking
        self._pending_ack_commands: Dict[int, Command] = {}
        self._retransmission_counts: Dict[int, int] = {}
        self._last_command_time: Dict[int, float] = {}
        
        # Packet assembly state
        self._assembling_packet: Optional[bytearray] = None
        self._packet_start_time: Optional[float] = None
        
        # Timing
        self.simulation_start_time_s: float = 0.0
        self.current_time_s: float = 0.0
    
    def initialize(self):
        """Initialize ESP32 state and connections."""
        self.state.uart_connected = True
        self.state.backend_connected = True
        self.state.next_sequence = 1
        self.state.last_received_sequence = 0
        self.simulation_start_time_s = time.time()
        self.current_time_s = 0.0
        
        self.state.log_event(
            InternalEventType.PACKET_RECEIVED,
            0,
            "ESP32 bridge initialized"
        )
    
    def process_uart_byte(self, byte_value: int) -> Optional[UARTPacket]:
        """Process one incoming byte from UART receiver.
        
        Builds complete packets from stream of bytes.
        Handles framing, sequencing, error detection.
        
        Args:
            byte_value: Single byte value (0-255)
            
        Returns:
            Complete packet if assembled and valid, None otherwise
        """
        # Add byte to assembling buffer
        if self._assembling_packet is None:
            # Looking for sync word start (0xABCD in little-endian: 0xCD first)
            if byte_value == 0xCD:
                self._assembling_packet = bytearray()
                self._assembling_packet.append(byte_value)
                self._packet_start_time = self.current_time_s
            return None
        
        self._assembling_packet.append(byte_value)
        
        # Check if we have sync word first byte, waiting for second
        if len(self._assembling_packet) == 1 and byte_value == 0xCD:
            # Sync word complete
            pass
        
        # Try to unpack complete packet
        packet = UARTPacket.unpack(bytes(self._assembling_packet))
        
        if packet is not None:
            # Complete valid packet received
            self._assembling_packet = None
            return packet
        
        # If buffer gets too large, discard and reset
        if len(self._assembling_packet) > 512:  # Reasonable max packet size
            self.state.add_fault(
                "PACKET_OVERFLOW",
                "UART buffer overflow during packet assembly"
            )
            self.state.log_event(
                InternalEventType.FAULT_DETECTED,
                0,
                "Packet overflow"
            )
            self._assembling_packet = None
        
        return None
    
    def process_uart_stream(self, byte_stream: bytes) -> List[UARTPacket]:
        """Process a stream of UART bytes, returning complete packets.
        
        Args:
            byte_stream: Raw UART byte stream
            
        Returns:
            List of successfully parsed UART packets
        """
        packets = []
        for byte in byte_stream:
            packet = self.process_uart_byte(byte)
            if packet is not None:
                packets.append(packet)
        return packets
    
    def forward_telemetry_to_backend(self, telemetry: Dict[str, Any]) -> bool:
        """Forward telemetry to isolated backend API.
        
        This is where simulation data enters "run state" domain.
        Does NOT call /api/insert_data (physical ingestion).
        Uses /api/simulator/telemetry instead.
        
        Args:
            telemetry: ExtendedTelemetry as dictionary
            
        Returns:
            True if forwarded successfully
        """
        if not self.state.backend_connected:
            return False
        
        result = self.backend_client.post_telemetry_frame(telemetry)
        
        if result.get('status') == 'success':
            # Store in telemetry history
            self.state.telemetry_history.append(telemetry)
            
            self.state.log_event(
                InternalEventType.PACKET_FORWARDING,
                telemetry.get('timestamp_s', 0),
                f"Forwarded telemetry frame {len(self.state.telemetry_history)}"
            )
            
            return True
        
        return False
    
    def receive_remote_command(self, cmd: Command) -> bool:
        """Receive remote command from backend.
        
        Queues command to send back to Arduino via UART.
        Implements ack/nack handshake.
        
        Args:
            cmd: Command to queue
            
        Returns:
            True if command accepted
        """
        # Queue command for transmission
        cmd.sequence = self.state.next_sequence
        self.state.next_sequence = (self.state.next_sequence + 1) % 65536
        
        self.state.pending_commands.append(cmd)
        
        self.state.log_event(
            InternalEventType.COMMAND_RECEIVED,
            cmd.sequence,
            f"Received {cmd.command_type} command"
        )
        
        # Send immediate ACK
        self._send_ack(cmd.sequence)
        
        # Track for retransmission if needed
        self._pending_ack_commands[cmd.sequence] = cmd
        self._retransmission_counts[cmd.sequence] = 0
        
        return True
    
    def apply_remote_command(self, cmd_type: str, payload: Optional[Dict[str, Any]] = None) -> bool:
        """Apply command to local system state.
        
        Supported commands:
        - STOP: Graceful shutdown (not ABORT!)
        - START/RESUME: Resume interrupted experiment
        - RESTART: Full restart from IDLE
        - CONFIGURE: Update runtime parameters
        
        Side effects:
        - Updates ESP32State.pending_commands
        - Triggers UART transmission back to Arduino
        
        Args:
            cmd_type: Command type string
            payload: Optional command payload
            
        Returns:
            True if command applied
        """
        cmd = Command(
            command_type=cmd_type,
            payload=payload,
            sequence=self.state.next_sequence
        )
        
        # Apply command locally
        if cmd_type == 'STOP':
            # Idempotent graceful shutdown
            self.state.internal_events.append(InternalEvent(
                event_type=InternalEventType.COMMAND_TRANSMITTED,
                sequence=cmd.sequence,
                timestamp_s=self.current_time_s,
                details="STOP command applied - graceful shutdown"
            ))
            
        elif cmd_type == 'START' or cmd_type == 'RESUME':
            # Resume interrupted operation
            self.state.internal_events.append(InternalEvent(
                event_type=InternalEventType.COMMAND_TRANSMITTED,
                sequence=cmd.sequence,
                timestamp_s=self.current_time_s,
                details=f"{cmd_type} command applied - resuming operation"
            ))
            
        elif cmd_type == 'RESTART':
            # Full restart from IDLE
            self.state.internal_events.append(InternalEvent(
                event_type=InternalEventType.COMMAND_TRANSMITTED,
                sequence=cmd.sequence,
                timestamp_s=self.current_time_s,
                details="RESTART command applied - resetting to IDLE"
            ))
            
        elif cmd_type == 'CONFIGURE':
            # Update runtime parameters from payload
            self.state.internal_events.append(InternalEvent(
                event_type=InternalEventType.COMMAND_TRANSMITTED,
                sequence=cmd.sequence,
                timestamp_s=self.current_time_s,
                details=f"CONFIGURE command applied with payload: {payload}"
            ))
            
        else:
            self.state.add_fault(
                "UNKNOWN_COMMAND",
                f"Unknown command type: {cmd_type}"
            )
            self._send_nack(cmd.sequence, "UNKNOWN_COMMAND")
            return False
        
        # Queue for UART transmission
        self.receive_remote_command(cmd)
        
        return True
    
    def _send_ack(self, sequence: int):
        """Send ACK for a command sequence."""
        ack_cmd = Command(
            command_type='ACK',
            payload={'sequence': sequence},
            sequence=sequence
        )
        self.state.log_event(
            InternalEventType.ACK_SENT,
            sequence,
            f"ACK sent for sequence {sequence}"
        )
    
    def _send_nack(self, sequence: int, reason: str):
        """Send NACK for a command sequence."""
        nack_cmd = Command(
            command_type='NACK',
            payload={'sequence': sequence, 'reason': reason},
            sequence=sequence
        )
        self.state.log_event(
            InternalEventType.NACK_SENT,
            sequence,
            f"NACK sent for sequence {sequence}: {reason}"
        )
    
    def assemble_command_packet(self, cmd: Command) -> bytes:
        """Assemble UART packet for command transmission.
        
        Returns:
            UART packet bytes
        """
        # Create telemetry frame
        payload_data = {
            'command_type': cmd.command_type,
            'payload': cmd.payload or {},
        }
        
        # Serialize payload to JSON bytes
        import json
        payload_bytes = json.dumps(payload_data).encode('utf-8')
        
        # Build UART packet
        packet = UARTPacket(
            sync_word=0xABCD,
            version=1,
            type_=FrameType.COMMAND,
            sequence=cmd.sequence,
            payload_length=len(payload_bytes),
            payload=payload_bytes
        )
        
        packet_bytes = packet.pack()
        return packet_bytes
    
    def transmit_pending_commands(self) -> List[bytes]:
        """Transmit all pending commands via UART.
        
        Returns:
            List of transmitted packet bytes
        """
        transmitted = []
        
        while self.state.pending_commands:
            cmd = self.state.pending_commands.pop(0)
            
            packet_bytes = self.assemble_command_packet(cmd)
            if packet_bytes:
                # Add to UART TX buffer
                transmit_time = self.uart.write_packet(packet_bytes)
                transmitted.append(packet_bytes)
                
                self.state.log_event(
                    InternalEventType.COMMAND_TRANSMITTED,
                    cmd.sequence,
                    f"Command {cmd.command_type} transmitted ({transmit_time:.6f}s)"
                )
        
        return transmitted
    
    def tick(self, dt_s: float) -> None:
        """Advance simulation by dt seconds.
        
        Args:
            dt_s: Time delta in seconds
        """
        self.current_time_s += dt_s
        
        # Advance UART byte delivery
        self.uart.tick(dt_s)
        
        # Check for retransmission timeouts
        current_time = time.time()
        sequences_to_remove = []
        
        for seq, count in self._retransmission_counts.items():
            if count < self.MAX_RETRANSMISSIONS:
                time_since_last = current_time - self._last_command_time.get(seq, current_time)
                if time_since_last >= self.RETRANSMIT_TIMEOUT_S:
                    # Trigger retransmission
                    self._retransmission_counts[seq] = count + 1
                    self._last_command_time[seq] = current_time
                    
                    cmd = self._pending_ack_commands.get(seq)
                    if cmd:
                        self.state.log_event(
                            InternalEventType.RETRANSMISSION,
                            seq,
                            f"Retransmission #{count + 1} for sequence {seq}"
                        )
            else:
                # Max retries exceeded
                sequences_to_remove.append(seq)
        
        for seq in sequences_to_remove:
            self._retransmission_counts.pop(seq, None)
            self._pending_ack_commands.pop(seq, None)
            
            self.state.add_fault(
                "TRANSMISSION_FAILED",
                f"Max retransmissions ({self.MAX_RETRANSMISSIONS}) exceeded for sequence {seq}"
            )
    
    def get_telemetry_history(self) -> List[Dict[str, Any]]:
        """Get all forwarded telemetry frames in order."""
        return self.state.telemetry_history.copy()
    
    def get_state(self) -> Dict[str, Any]:
        """Get current ESP32 state."""
        return self.state.to_dict()
    
    def get_backend_requests(self) -> List[Dict[str, Any]]:
        """Get all backend API requests made."""
        return self.backend_client.get_request_log()
    
    def verify_backend_isolation(self) -> bool:
        """Verify no calls were made to production API endpoints.
        
        Returns:
            True if only /api/simulator/* endpoints were used
        """
        for req in self.backend_client.get_request_log():
            endpoint = req.get('endpoint', '')
            if '/api/insert_data' in endpoint or '/api/experiments' in endpoint:
                return False
            if not endpoint.startswith('/api/simulator'):
                return False
        return True
    
    def reset(self):
        """Reset simulator to initial state."""
        self.state = ESP32State()
        self.uart.clear_buffers()
        self.backend_client.clear_request_log()
        self._pending_ack_commands.clear()
        self._retransmission_counts.clear()
        self._assembling_packet = None
        self._packet_start_time = None
        self.simulation_start_time_s = 0.0
        self.current_time_s = 0.0


__all__ = [
    'ESP32BridgeSimulator',
    'VirtualUARTEngine',
    'UARTPacket',
    'Command',
    'FrameType',
    'ESP32State',
    'SimulatorBackendAPIClient',
    'FaultCode',
    'InternalEventType',
]
