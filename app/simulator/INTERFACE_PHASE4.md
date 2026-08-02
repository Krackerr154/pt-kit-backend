# Phase 4 Interface Contract: Virtual UART & ESP32 Bridge

This document defines the interfaces for Phase 4 implementation so parallel subagents produce compatible code.

## Overview

Phase 4 implements the virtual communication layer between the plant/controller simulator (Phases 1-3) and a simulated ESP32 microcontroller. The architecture mirrors the physical PT-Kit setup:

```
Virtual Arduino Controller → Virtual UART → Virtual ESP32 Bridge → Simulator Run State
```

### Key Design Decisions

✅ **No physical serial ports** - Purely software simulation  
✅ **Isolated from production data** - Uses `/api/simulator/*` APIs only  
✅ **Deterministic execution** - Fixed seed enables reproducible trace replay  
✅ **Separate logical components** - Arduino firmware vs ESP32 bridge remain distinct  
✅ **Hardware protocol fidelity** - Follows actual UART packet format and timing  

---

## Interface Contracts

### 1. Virtual Arduino ↔ Virtual UART (Serial Port Simulation)

#### UART Packet Protocol

```python
@dataclass
class UARTPacket:
    """UART frame format matching ESP32 physical protocol."""
    
    # Header
    sync_word: int = 0xABCD        # Synchronization sequence
    version: int = 1               # Protocol version
    
    # Frame control
    type: int                      # Frame type (see below)
    sequence: int                  # Monotonic counter (wraps at 65535)
    payload_length: int            # 0-255 bytes
    
    # Payload (raw bytes)
    payload: bytes
    
    # Trailer
    checksum: int                  # CRC-16-CCITT over all fields except sync


class VirtualUARTEngine:
    """Simulates RS-232 serial communication with baud rate timing."""
    
    def __init__(self, baud_rate: int = 115200):
        """Initialize virtual serial port.
        
        Args:
            baud_rate: Baud rate (default 115200 matches physical PT-Kit)
        """
        self.baud_rate = baud_rate
        self._buffer: bytearray = bytearray()
        self._rx_buffer: bytearray = bytearray()
        self._tx_buffer: bytearray = bytearray()
        
    def write_packet(self, packet: UARTPacket) -> float:
        """Transmit packet, return time duration in seconds.
        
        Args:
            packet: Frame to transmit
            
        Returns:
            Time required to transmit this packet on current baud rate
        """
        ...
        
    def read_available(self) -> Optional[UARTPacket]:
        """Check if complete packet available in RX buffer.
        
        Returns:
            Complete packet if ready, None otherwise
        """
        ...
        
    def tick(self, dt_s: float) -> None:
        """Advance simulation by dt seconds.
        
        Moves bytes from TX to RX based on baud rate timing.
        """
        ...
```

#### Frame Types

| Type | Value | Direction | Description |
|------|-------|-----------|-------------|
| TELEMETRY | 0x01 | Arduino→ESP32 | ExtendedTelemetry from controller |
| COMMAND | 0x02 | ESP32→Arduino | Remote command (STOP, START, etc.) |
| ACK_NACK | 0x03 | Both | Acknowledgment or negative acknowledgment |
| CALIBRATION | 0x04 | Bidirectional | Calibration data exchange |
| STATUS | 0x05 | Bidirectional | Heartbeat/status query |

---

### 2. Virtual ESP32 ↔ Simulator Backend

#### ESP32 Internal State Model

```python
@dataclass
class ESP32State:
    """Simulated ESP32 microcontroller state."""
    
    # Connection status
    uart_connected: bool = False
    backend_connected: bool = False
    
    # Command queue (in-flight remote commands)
    pending_commands: list[Command] = field(default_factory=list)
    
    # Telemetry buffer (collected from Arduino via UART)
    telemetry_history: list[ExtendedTelemetry] = field(default_factory=list)
    
    # Local event logging
    internal_events: list[InternalEvent] = field(default_factory=list)
    
    # Error conditions
    faults: list[FaultCode] = field(default_factory=list)
    

class ESP32BridgeSimulator:
    """Simulates ESP32 receiving telemetry from Arduino, forwarding to backend."""
    
    def __init__(self):
        self.uart = VirtualUARTEngine(baud_rate=115200)
        self.state = ESP32State()
        
    def process_uart_byte(self) -> None:
        """Process one incoming byte from UART receiver.
        
        Builds complete packets from stream of bytes.
        Handles framing, sequencing, error detection.
        """
        ...
        
    def forward_telemetry_to_backend(self, telemetry: ExtendedTelemetry) -> None:
        """Forward telemetry to isolated backend API.
        
        This is where simulation data enters "run state" domain.
        Does NOT call /api/insert_data (physical ingestion).
        Uses /api/simulator/telemetry instead.
        """
        ...
        
    def receive_remote_command(self, cmd: Command) -> None:
        """Receive remote command from backend.
        
        Queues command to send back to Arduino via UART.
        Implements ack/nack handshake.
        """
        ...
        
    def apply_remote_command(self, cmd: str) -> None:
        """Apply command to local system state.
        
        Supported commands:
        - STOP: Graceful shutdown (not ABORT!)
        - START/RESUME: Resume interrupted experiment  
        - RESTART: Full restart from IDLE
        - CONFIGURE: Update runtime parameters
        
        Side effects:
        - Updates ESP32State.pending_commands
        - Triggers UART transmission back to Arduino
        """
        ...
```

#### Backend API Isolation Layer

```python
class SimulatorBackendAPIClient:
    """Isolated backend API client for simulation-only operations."""
    
    def __init__(self, base_url: str = "/api/simulator"):
        self.base_url = base_url
        self._session = requests.Session()
        
    def post_telemetry_frame(self, frame: ExtendedTelemetry) -> Response:
        """Submit single telemetry frame to simulator run state."""
        endpoint = f"{self.base_url}/telemetry"
        return self._session.post(endpoint, json=frame.to_dict())
        
    def put_run_state(self, state: RunState) -> Response:
        """Update current run state (EXPERIMENT_RUNNING, PAUSED, COMPLETED)."""
        endpoint = f"{self.base_url}/runs/{state.run_id}"
        return self._session.put(endpoint, json=state.to_dict())
        
    def get_pending_commands(self, run_id: str) -> List[Command]:
        """Fetch queued commands for this run."""
        endpoint = f"{self.base_url}/runs/{run_id}/commands"
        response = self._session.get(endpoint)
        return [Command.from_dict(c) for c in response.json()]


__all__ = [
    'UARTEngine', 'UARTPacket', 'VirtualESP32Bridge',
    'SimulatorBackendAPIClient', 'Command', 'ExtendedTelemetry'
]
```

---

## Test Requirements

### Golden Trace Comparison Tests

Each scenario must generate identical UART transaction logs when run with same seed:

```json
{
  "scenario": "ISO1_with_UART",
  "seed": 42,
  "uart_transactions": [
    {
      "time_s": 0.017,
      "direction": "TX",  // TX or RX
      "packet_type": "TELEMETRY",
      "sequence": 1,
      "payload_size": 128,
      "latency_us": 14580  // ~115200 baud × 10 bits per byte
    }
  ]
}
```

Tests verify:
- Byte-level exact timing match
- Packet boundaries align correctly
- Sequences monotonic and wrap at 65535
- Checksum validation catches corruption
- Endianness consistent (little-endian for multi-byte fields)

### Functional Tests

- STOP command sent via backend → received by Arduino within N milliseconds
- Telemetry frames arrive in correct order despite network jitter simulation
- Timeout handling: missing ACK triggers retransmission up to 3 times
- Fault injection: bit-flip errors during UART transmission detected and logged

---

## Documentation Deliverables

1. **UART Protocol Specification** - Complete packet format, error handling, timing budgets
2. **ESP32 Firmware Emulation Guide** - How virtual ESP32 mimics real firmware behavior
3. **Backend API Isolation Document** - Why `/api/simulator/*` used instead of `/api/insert_data`
4. **Fault Injection Catalog** - All supported fault scenarios (bit errors, latency spikes, disconnects)

---

## Implementation Guidelines

⚠️ **Critical Constraints:**

1. **NO browser/backend/database access** - Simulate as pure Python objects
2. **Fixed seed determinism** - All randomness from seeded RNG streams
3. **Baud rate accuracy** - Actual byte timing (115200 baud ≈ 8.68 µs per byte at 10 bits/frame)
4. **Protocol fidelity** - Match real PT-Kit UART format exactly
5. **Component isolation** - Arduino simulator ≠ ESP32 simulator ≠ Backend API

⚠️ **DO NOT:**

- Use actual serial port libraries (`pyserial`)
- Write to physical database tables
- Call production experiment APIs (`/api/insert_data`)
- Modify calibration state or physical sensor readings
- Introduce non-deterministic delays (system load, GC pauses)

✅ **DO:**

- Implement byte-stream simulation with explicit timing
- Maintain separate clock/timing domains for UART ↔ Backend
- Log transactions for golden trace comparison
- Validate checksums and sequence numbers
- Inject faults deterministically for regression testing

---

## Exit Criteria

- ✅ UART protocol fully implemented with correct timing
- ✅ ESP32 bridge forwards telemetry without corruption
- ✅ Remote commands reach Arduino controller reliably
- ✅ STOP command idempotent (verified across all test modes)
- ✅ Deterministic golden traces generated for all experiment modes
- ✅ Fault injection tests pass (error detection working)
- ✅ All tests run without external dependencies

---

*Draft v1.0 | 2026-08-01 | PT-Kit Digital Twin Simulator Phase 4*
