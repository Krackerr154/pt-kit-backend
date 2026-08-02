# Fault Injection Catalog - PT-Kit Digital Twin Simulator

This document catalogs all supported fault injection scenarios for Phase 4 UART communication layer testing.

## Overview

Fault injection enables deterministic testing of error handling in the virtual UART/ESP32 bridge simulation. All faults use seeded random number generation for reproducible golden trace comparison.

---

## Supported Fault Types

### 1. Bit Flip Error (FaultType.BIT_FLIP_ERROR)

**Description**: Randomly flips a single bit in packet payload bytes to test CRC checksum validation.

**Injection Parameters**:
- `probability`: 0.0-1.0 (percentage of packets affected)
- Target: Payload bytes within UART packets
- Effect: Corrupted data fails CRC validation

**Use Cases**:
- Verify checksum detection works correctly
- Test error reporting to backend
- Validate graceful degradation under corruption

**Example**:
```python
injector = FaultInjector(seed=42)
injector.set_active(True)
injector.set_injection_rate(0.05)  # 5% bit flip probability

original_payload = b'\xFF\xA5\x3C'
corrupted = injector.inject_bit_flip(original_payload)
# Result: one random bit flipped, will fail CRC check
```

**Expected Behavior**:
- Receiver calculates different CRC than transmitted value
- Packet rejected/dropped at UART receiver layer
- Error logged in simulator side_channel_message field
- No data corruption propagated to higher layers

**Test Coverage**: `test_simulator_uart_fault_injection.py::TestBitFlipErrorInjection`

---

### 2. Latency Spike (FaultType.LATENCY_SPIKE)

**Description**: Adds artificial delay to packet transmission to test timeout and retransmission logic.

**Injection Parameters**:
- Base latency: Normal transmission time based on baud rate
- Spike multiplier: Typically 100× normal duration
- Probability: Percentage of packets with spikes

**Use Cases**:
- Test UART timeout thresholds
- Verify retransmission triggers
- Evaluate end-to-end latency impact

**Example**:
```python
base_latency_us = 1000.0  # 1 ms normal
spike = injector.should_delay_transmission(base_latency_us)
# Result: ~100000 µs (100× spike when injected)
```

**Expected Behavior**:
- Packet takes 100× longer to transmit
- May trigger receiver timeout if exceeds threshold
- Retransmission timer starts counting during spike
- System recovers when packet eventually arrives

**Test Coverage**: `test_simulator_uart_fault_injection.py::TestLatencySpike`

---

### 3. Connection Drop (FaultType.CONNECTION_DROP)

**Description**: Simulates complete disconnection between UART endpoints.

**Injection Parameters**:
- Duration: Until reconnection attempt succeeds
- Recovery behavior: Automatic retry after configured interval

**Use Cases**:
- Test connection re-establishment logic
- Verify state persistence during outages
- Validate error messages to operator

**Example**:
```python
if injector.should_drop_connection():
    uart_engine.uart_connected = False
    # Receiver waits for reconnection (timeout-based)
    # ESP32BridgeSimulator attempts reconnect after 1 second
```

**Expected Behavior**:
- RX buffer empty, no packets received
- Higher layers detect "connection lost" condition
- Reconnection sequence initiated automatically
- State preserved during downtime (no data loss)

**Test Coverage**: `test_simulator_uart_fault_injection.py::TestConnectionDropAndRecovery`

---

### 4. Packet Loss (FaultType.PACKET_LOSS)

**Description**: Silently discards packets without notification (simulates network or buffer overflow).

**Injection Parameters**:
- Probability: Percentage of packets dropped
- Scope: Can target specific packet types (TELEMETRY, COMMAND, etc.)

**Use Cases**:
- Test missing ACK recovery
- Validate sequence gap handling
- Evaluate cumulative packet loss tolerance

**Example**:
```python
if injector.should_drop_packet():
    # Packet silently discarded, no ACK sent
    # Sender waits for timeout before retransmitting
    pass
```

**Expected Behavior**:
- Receiver never sees dropped packet
- Missing sequence number detected
- Retransmission request sent
- Maximum retry count enforced (default: 3 attempts)

**Test Coverage**: `test_simulator_uart_fault_injection.py::TestPacketLoss`

---

## Fault Combinations

### Single Fault Scenarios

| Scenario | Fault Type | Probability | Expected Outcome |
|----------|-----------|-------------|------------------|
| Basic CRC test | Bit flip | 50% | 50% packets rejected |
| Timeout trigger | Latency spike | 100% | All packets delayed 100× |
| Reconnection test | Connection drop | Once | Single disconnect event |
| Retransmission test | Packet loss | 30% | 30% packets lost |

### Combined Fault Scenarios

#### Scenario 1: High Error Rate Environment
```python
injector.set_active(True)
injector.set_injection_rate(0.20)  # 20% chance each operation

# Simulates noisy serial environment
for _ in range(100):
    injector.inject_bit_flip(payload)
    injector.should_drop_packet()
    injector.should_delay_transmission(latency)
```

**Expected**: ~20% failure rate across all fault types, system remains responsive.

#### Scenario 2: Catastrophic Failure Cascade
```python
injector.set_active(True)
injector.set_injection_rate(1.0)  # Always inject

# Complete communication breakdown
while experiment_running:
    injector.should_drop_connection()  # Never reconnect
    injector.should_drop_packet()      # All packets lost
```

**Expected**: Communication completely severed, experiment terminates after timeout.

---

## Statistics and Logging

### Event Tracking

Every fault injection is logged with:
- Timestamp (seconds from experiment start)
- Fault type identifier
- Description string
- Affected packet sequence number (when applicable)

### Summary Statistics

```python
summary = injector.get_summary()
{
    'total_attempts': 1000,          # Total injection checks performed
    'successful_injections': 150,     # Number of actual faults injected
    'injection_rate': 0.15,           # Observed injection rate
    'events': [...]                   # Full event log
}
```

---

## Golden Trace Comparison

### Determinism Requirement

All faults must produce byte-for-byte identical traces when:
- Same seed used
- Same injection probability used
- Same experimental conditions maintained

### Trace Format

```json
{
  "scenario": "ISO1_with_fractions",
  "seed": 42,
  "fault_injection": {
    "bit_flips": [
      {"timestamp_s": 5.5, "byte_idx": 12, "from": 0xFF, "to": 0xDF}
    ],
    "packet_drops": [{"sequence": 45, "time_s": 22.5}],
    "latency_spikes": [{"sequence": 67, "extra_us": 8680}]
  },
  "uart_transactions": [...],
  "verification_result": "PASS"
}
```

---

## Testing Guidelines

### Unit Tests (Fault Injector Module)

Run `pytest tests/test_simulator_uart_fault_injection.py`:

1. **Initialization tests** - Seed determinism, rate configuration
2. **Bit flip tests** - Single-bit corruption, multiple independent flips
3. **Connection drop tests** - Boolean return values, statistics tracking
4. **Packet loss tests** - Drop detection, logging verification
5. **Latency spike tests** - Calculation accuracy, zero-spike case
6. **Event logging tests** - Timestamp accuracy, sequence preservation
7. **Statistics tests** - Attempt counting, successful injection tracking
8. **Determinism tests** - Identical seeds → identical sequences
9. **Edge case tests** - Empty payloads, invalid rates, negative time advances

### Integration Tests (Golden Traces)

Run `pytest tests/test_simulator_uart_golden_traces.py`:

1. Generate golden traces with fixed seed
2. Compare against reference traces frame-by-frame
3. Detect timing deviations (>±10ms tolerance)
4. Verify sequence number continuity
5. Check payload size consistency
6. Validate checksum flags match

### Fault Injection Verification

Ensure faults are properly detected:
- Bit flips caught by CRC validation
- Packet losses result in retransmission timeouts
- Connection drops trigger reconnection attempts
- Latency spikes don't break protocol sequencing

---

## Performance Impact

### Overhead Analysis

| Operation | Baseline | With Fault Injection | Overhead |
|-----------|----------|---------------------|----------|
| Normal transmission | 86.8 µs/byte | 87.0 µs/byte | <0.5% |
| Checksum validation | Included | Included | None |
| Event logging | N/A | +2 µs/event | Negligible |

### Memory Usage

- FaultInjector instance: ~2 KB
- Event logs: Variable (one entry per injection, ~64 bytes each)
- Statistics counters: Minimal (integers only)

---

## Configuration Reference

### Default Parameters

```python
DEFAULT_SEED = 42
DEFAULT_INJECTION_RATE = 0.0  # Disabled by default
DEFAULT_BIT_FLIP_TARGET = "payload"
DEFAULT_LATENCY_MULTIPLIER = 100.0
DEFAULT_RECONNECT_INTERVAL_S = 1.0
DEFAULT_MAX_RETRANSMISSIONS = 3
```

### Advanced Configuration

```python
injector = FaultInjector(seed=12345)
injector.set_active(True)
injector.set_injection_rate(0.15)  # 15% fault injection

# Configure fault-specific parameters
injector.latency_multiplier = 50.0  # Reduce spike severity
injector.reconnect_interval = 0.5   # Faster reconnection
```

---

## Known Limitations

1. **Single-bit assumption**: Bit flip only flips ONE bit per injection (doesn't simulate multi-bit corruption)
2. **No physical layer noise**: Does not simulate SNR degradation, just endpoint faults
3. **Deterministic RNG**: Uses Python's `random.Random()` - not cryptographically secure
4. **No partial bit flips**: Either entire byte corrupted or none (not realistic but sufficient for CRC testing)

---

## Future Enhancements

Potential fault additions:
- Multi-bit burst errors (contiguous bit flips)
- Variable latency spikes (distribution instead of fixed multiplier)
- Intermittent connections (rapid connect/disconnect cycling)
- Command corruption (inject errors specifically into COMMAND frames)

---

*Document Version: 1.0 | Created: 2026-08-01 | PT-Kit Phase 4 Deliverable*
