# UART Protocol Specification - PT-Kit Digital Twin Simulator

This document defines the complete UART communication protocol used in Phase 4 of the PT-Kit digital-twin simulator.

## Overview

The virtual UART layer simulates RS-232 serial communication between:
1. **Arduino Controller** (physical device or simulator) → ESP32 Bridge
2. **ESP32 Bridge** (virtual microcontroller) → Backend API

All packets follow a standardized binary frame format with CRC-16-CCITT checksum validation.

---

## Frame Format

### Binary Structure

```
+--------+-------+------+-------+----------+-----------+----------+
| Sync   | Vers  | Type | Seq   | Payload  | Checksum  | (Footer) |
| (2B)   | (1B)  | (1B) | (2B)  | (N bytes)| (2B CRC)  |          |
+--------+-------+------+-------+----------+-----------+----------+
|    0xABCD     |  0x01       |  Variable      | CRC-16-CCITT   |
+----------------+---------------+-----------------------------+
```

### Field Definitions

| Field | Size | Description |
|-------|------|-------------|
| `sync_word` | 2 bytes | Magic sequence `0xABCD` (high byte first) |
| `version` | 1 byte | Protocol version (currently 1) |
| `frame_type` | 1 byte | Type identifier (see below) |
| `sequence` | 2 bytes | Monotonic counter, little-endian, wraps at 65535 |
| `payload_length` | 1 byte | Payload size (0-255 bytes) |
| `payload` | N bytes | Variable-length data |
| `checksum` | 2 bytes | CRC-16-CCITT over all preceding fields |

---

## Frame Types

| Value | Name | Direction | Description |
|-------|------|-----------|-------------|
| `0x01` | TELEMETRY | Arduino→ESP32 | ExtendedTelemetry from controller |
| `0x02` | COMMAND | ESP32→Arduino | Remote command (STOP, START, etc.) |
| `0x03` | ACK_NACK | Bidirectional | Acknowledgment or rejection |
| `0x04` | CALIBRATION | Bidirectional | Calibration data exchange |
| `0x05` | STATUS | Bidirectional | Heartbeat/status query |

---

## Timing & Latency

### Baud Rate Calculations

At **115200 baud**:
- Bits per byte: 10 (1 start + 8 data + 1 stop)
- Time per byte: **~86.8 µs**
- Typical packet overhead: ~500 µs

### Transmission Time Formula

```
transmission_time_ms = ((header_size + payload_length + checksum_size) × 10) / baud_rate
```

Example for 128-byte telemetry packet:
- Total bytes: 9 (header) + 128 (payload) + 2 (checksum) = 139 bytes
- Transmission time: 139 × 86.8 µs ≈ **12.1 ms**

---

## CRC-16-CCITT Algorithm

### Polynomial & Parameters

```
polynomial = 0x1021
initial_value = 0xFFFF
```

### Python Implementation

```python
def calculate_crc16_ccitt(data: bytes) -> int:
    """Calculate CRC-16-CCITT checksum."""
    crc = 0xFFFF
    
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    
    return crc
```

### Verification

Receiver calculates CRC over received data (excluding checksum field itself). If calculated ≠ received, frame is corrupted and should be discarded or retransmitted.

---

## Error Handling Procedures

### Sequence Number Validation

- Packets must arrive in strictly monotonic order (except wraparound)
- Missing sequence numbers indicate packet loss
- Duplicate sequences indicate retransmission or corruption

**Action on Gap Detected:**
1. Log missing sequence number
2. Request retransmission (if reliable mode enabled)
3. Mark affected telemetry as "gap" for gap-fill interpolation

### Timeout Behavior

| Scenario | Default Timeout | Action |
|----------|-----------------|--------|
| ACK not received | 200 ms | Retransmit up to 3 times |
| Command not applied | 500 ms | Log warning, report to backend |
| Connection lost | 1 second | Attempt reconnection |

### Retry Strategy

```
Attempt 1: Immediate transmission
Attempt 2: After 100 ms delay
Attempt 3: After 200 ms delay
Final attempt after 500 ms delay (maximum retries exceeded)
```

---

## Packet Encoding/Decoding Examples

### Example 1: Simple Status Query

**Sender (ESP32→Arduino):**
```python
packet = UARTPacket(
    sync_word=0xABCD,
    version=1,
    frame_type=FrameType.STATUS,
    sequence=42,
    payload=b'\x00\x01',  # Heartbeat query
)
encoded = packet.encode()  # Returns bytes
```

**Binary output (hex):**
```
AB CD 01 05 2A 00 01 F6 7C
↑    ↑   ↑   ↑    ↑      ↑
│    │   │   │    │      └─ CRC-16-CCITT
│    │   │   │    └──────── Payload (2 bytes)
│    │   │   └───────────── Sequence (42 = 0x2A)
│    │   └───────────────── Frame type (STATUS = 0x05)
│    └───────────────────── Version (1)
└────────────────────────── Sync word (0xABCD)
```

### Example 2: Telemetry Frame

**Full extended telemetry:**
```python
packet = UARTPacket(
    sync_word=0xABCD,
    version=1,
    frame_type=FrameType.TELEMETRY,
    sequence=1000,
    payload=extended_telemetry_binary_format,  # 128 bytes
)
```

Payload contains serialized `ExtendedTelemetry` structure:
```
SurfaceTemp°C (float32), BulkTemp°C (float32), LampLux (uint32),
Time_s (float64), CycleCount (uint16), QualifyRemaining (uint16),
... plus optional target/setpoint/hold fields
```

---

## Fault Injection Scenarios

### Bit Flip Errors

Inject random single-bit flips to test checksum validation:

```python
injector = FaultInjector(seed=42)
injector.set_active(True)
injector.set_injection_rate(0.05)  # 5% injection probability

corrupted_payload = injector.inject_bit_flip(original_payload)
# Will fail CRC validation at receiver
```

### Packet Loss

Simulate network or serial buffer overflow:

```python
if injector.should_drop_packet():
    # Silently discard packet (no ACK sent)
    pass
```

### Connection Drop

Test reconnection logic:

```python
if injector.should_drop_connection():
    uart_engine.uart_connected = False
    # Receiver will timeout waiting for next packet
    # Reconnection handled by higher layer
```

### Latency Spike

Artificially delay transmission:

```python
base_latency_us = packet_size_bytes * 86.8  # µs
extra_latency = injector.should_delay_transmission(base_latency_us)
actual_latency = base_latency_us + extra_latency
# Should trigger timeout if > expected threshold
```

---

## Golden Trace Format

For regression testing, generate golden traces with fixed seed:

```json
{
  "scenario": "ISO1_with_UART",
  "seed": 42,
  "uart_transactions": [
    {
      "time_s": 0.0121,
      "direction": "TX",
      "packet_type": "TELEMETRY",
      "sequence": 1,
      "payload_size": 128,
      "latency_us": 12100,
      "checksum_valid": true
    }
  ]
}
```

### Comparison Rules

Golden trace comparison uses strict equality for:
- Timing within ±1% tolerance
- Sequence numbers exactly matching
- Payload content byte-by-byte
- Checksum validity flags

Deviation triggers test failure unless intentional change documented.

---

## Testing Guidelines

### Unit Test Categories

1. **Encoding Tests** - Verify byte stream matches specification
2. **Decoding Tests** - Verify packets reconstructed correctly
3. **Checksum Tests** - Valid packets pass, corrupted packets fail
4. **Sequence Tests** - Wraparound behavior correct at 65535→0
5. **Timing Tests** - Transmission duration accurate to ±1%
6. **Fault Injection Tests** - Errors detected and logged correctly

### Integration Test Scenarios

1. **Normal Operation** - Long experiment without faults
2. **Transient Errors** - Isolated bit flips caught by CRC
3. **Persistent Failures** - Connection drops with recovery attempts
4. **Command Delivery** - STOP command reaches Arduino reliably
5. **Telemetry Ordering** - Frames arrive in monotonic sequence

---

## API Isolation Layer

> ⚠️ **CORRECTION (2026-08-03):** This section previously specified `SimulatorBackendAPIClient` calling `/api/simulator/telemetry` and `/api/simulator/runs/{run_id}/commands`. That was the **design intent**; the actual implementation differs and this section has been rewritten to match the code.

### Implemented simulator API surfaces

PT-Kit currently has **three distinct simulator API surfaces**, each in its own module. None of them matches the exact paths originally written in this section.

**1. Isolated backend API** — `app/simulator/isolated_backend_api.py` (`IsolatedBackendAPI`, base path `/api/simulator`, in-memory only, no database):

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/simulator/runs/start` | Start a run (`StartSimulationRequest` mirrors the production `ExperimentConfig` fields) |
| POST | `/api/simulator/runs/{run_id}/stop` | Stop a run gracefully |
| POST | `/api/simulator/runs/{run_id}/pause` | Pause (RUNNING only) |
| POST | `/api/simulator/runs/{run_id}/resume` | Resume (PAUSED only) |
| POST | `/api/simulator/runs/{run_id}/telemetry` | **Telemetry ingestion — NOT `/api/insert_data`** |
| GET | `/api/simulator/runs/{run_id}` | Run detail/state |
| GET | `/api/simulator/runs/{run_id}/telemetry` | Telemetry history |
| POST | `/api/simulator/runs/{run_id}/commands` | Queue a command for the run |
| GET | `/api/simulator/runs/{run_id}/commands` | List pending commands |
| DELETE | `/api/simulator/runs/{run_id}/commands` | Clear pending commands |
| DELETE | `/api/simulator/runs/{run_id}` | Delete run state |
| GET | `/api/simulator/runs` | List all runs |
| GET | `/api/simulator/health` | Health check |

Note the telemetry endpoint is **per-run** (`/runs/{run_id}/telemetry`), not the flat `/api/simulator/telemetry` originally specified here.

**2. Live dashboard (plant-driven sim)** — `app/simulator/live_dashboard.py`:

`POST /api/sim/start`, `POST /api/sim/{run_id}/pause`, `POST /api/sim/{run_id}/resume`, `POST /api/sim/{run_id}/stop`, `GET /api/sim/{run_id}/status`, `GET /api/sim/{run_id}/history`, `GET /api/sim/runs`, `WS /ws/sim/{run_id}`, plus `/health`.

**3. Dashboard server** — `app/simulator/dashboard_server.py` (mounted under `/simulator`, docs at `/simulator/docs`):

`GET /simulator/status`, `POST /simulator/commands`, `GET /simulator/history`.

### Isolation rule (unchanged)

❌ **DO NOT** call: `/api/insert_data` (physical experiment ingestion)
✅ **USE** the `/api/simulator/*` (isolated layer), `/api/sim/*` (live dashboard), or `/simulator/*` (dashboard server) families instead.

Simulated telemetry is in-memory only and never contaminates the production PostgreSQL database.

### ⚠️ Known unresolved divergence: ESP32-bridge wire format

Per `PHASE9_IMPL_BUGS.md` (OPEN item A), the two ends of the simulated serial link **do not interoperate**:

| Aspect | `virtual_uart.py` (Arduino side) | `esp32_bridge_simulator.py` (ESP32 side) |
|---|---|---|
| Byte order | big-endian (`abcd0101…`) | little-endian (`cdab0100…`) |
| Header size | 9 bytes | 7 bytes |
| Field order | sync, ver, type, seq, len | sync, **seq**, ver, type, len |
| Checksum | true CRC-16-CCITT (poly 0x1021) | `zlib.crc32() & 0xFFFF` — **not** CCITT |

This document (frame layout §"Frame Format" and §"CRC-16-CCITT") describes the **`virtual_uart.py` side**, which is the spec-conformant side. The ESP32 bridge diverges on all four axes. Aligning the bridge is a real protocol change affecting the ESP32 firmware contract and is deliberately left open pending a decision on whether the simulator mirrors this spec or the deployed ESP32 firmware.

> Phase 9 also fixed a separate CRC **placement** bug (`PHASE9_IMPL_BUGS.md` item 2): the checksum must trail the payload (header → payload → checksum), matching this spec. That fix is conformant; the remaining divergence is item A above.

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-08-01 | PT-Kit Team | Initial spec for Phase 4 |
| 1.1 | 2026-08-03 | PT-Kit Team | Rewrote API Isolation Layer to match implemented `/api/simulator/*`, `/api/sim/*`, `/simulator/*` surfaces; documented open ESP32-bridge wire-format divergence (PHASE9 item A) |

---

*End of UART Protocol Specification v1.1*
