# Firmware Quirks and Invalid Sensor Handling

## Overview

This document describes the current firmware's behavior regarding invalid sensor handling, timeout mechanisms, and over-temperature quirks. These behaviors are documented for exact reproduction in simulation - **no corrections or modernizations should be applied**.

## 1. Invalid-to-Zero Conditioning in Legacy Modes

### 1.1 Behavior Description

In legacy control modes (ISO1 and PLAT1), the firmware applies a strict "invalid-to-zero" conditioning strategy when sensors report invalid data. This is a safety mechanism that prioritizes predictable zero outputs over attempting to estimate missing values.

### 1.2 Mode-Specific Rules

#### ISO1 Mode (Fixed Temperature)

**Priority Chain:**
```
If IR valid → Use IR reading value
Else If TC valid → Use TC reading value  
Else (both invalid) → Return ZERO (0.0°C)
```

**Key Points:**
- IR takes priority over TC when both are valid
- When IR becomes invalid during operation, immediately switches to TC
- Only returns zero when BOTH IR AND TC are invalid
- Zero output is permanent until at least one sensor recovers validity

#### PLAT1 Mode (Ramp-Hold/Plateau)

**Sensor Selection:**
- Uses configured `selected_sensor` parameter
- Typically IR by default if no selection made
- Applies same timeout logic as ISO1

**Validation Logic:**
```
If selected_sensor == IR:
    If IR valid → Use IR reading
    Else → Return ZERO
    
If selected_sensor == TC:
    If TC valid → Use TC reading
    Else → Return ZERO
```

**Fallback Behavior:**
- Selected sensor invalidity does NOT automatically switch to backup sensor
- Returns safe zero output for the selected sensor only
- Operator must manually change selected sensor to use alternative

### 1.3 Code Example: Before/After Behavior

#### Current Firmware Behavior (No Correction)

```python
from simulator.invalid_sensor_handler import (
    InvalidSensorHandler, 
    SensorType, 
    ControlMode, 
    SensorReading
)

handler = InvalidSensorHandler()

ir_reading = SensorReading(value=75.0, valid=True)
tc_reading = SensorReading(value=76.0, valid=True)

# Initial state: uses IR
output = handler.get_safe_output(ControlMode.ISO1, ir_reading, tc_reading)
print(output)  # 75.0 ✓

# Simulate IR hardware failure
handler.ir_valid = False
handler._ir_consecutive_invalid = 3

# Falls back to TC
output = handler.get_safe_output(ControlMode.ISO1, ir_reading, tc_reading)
print(output)  # 76.0 ✓

# Now TC also fails
handler.tc_valid = False
output = handler.get_safe_output(ControlMode.ISO1, ir_reading, tc_reading)
print(output)  # 0.0 ← ZERO OUTPUT (safe condition)
```

#### Modern "Corrected" Behavior (NOT USED - For Comparison Only)

```python
# DO NOT IMPLEMENT THIS - it corrects firmware quirks!
def get_corrected_output(self, mode, ir, tc):
    """MODERN APPROACH - IGNORE THIS"""
    if not self.ir_valid and not self.tc_valid:
        # WRONG: Interpolating would be "smarter" but breaks firmware parity
        return 0.0  # Always zero anyway
    elif not self.ir_valid and self.tc_valid:
        return tc.value * 1.02  # WRONG: Scaling "corrects" bad data
    elif self.ir_valid and not self.tc_valid:
        return ir.value * 0.98  # WRONG: Applying calibration offsets
    else:
        return min(ir.value, tc.value)  # WRONG: Arbitrarily selecting
```

**Why We Don't Correct:**
- Current firmware does NOT perform these operations
- Simulation must reproduce exact physical behavior
- Corrections would mask real operational issues operators encounter
- Zero output is the ONLY safe fallback per specification

---

## 2. Over-Temperature Quirk Reproduction

### 2.1 Quirk Description

The current firmware exhibits specific over-temperature handling quirks that must be reproduced exactly. These include timing delays, threshold tolerances, and response behaviors that deviate from ideal control theory.

### 2.2 Known Quirks

#### Quirk 1: Delayed Trip Threshold

**Behavior:**
- Over-temperature trip occurs at **actual sensor temperature + 3°C**
- Not at configured setpoint
- This creates a ~3°C overshoot margin before action

**Code Implementation:**
```python
OVERTEMP_TRIP_DELTA = 3.0  # Degrees Celsius

def check_over_temp_quirk(self, temp, configured_limit):
    """Reproduce exact trip behavior"""
    effective_trip_point = configured_limit + OVERTEMP_TRIP_DELTA
    
    # Trips at TEMP >= LIMIT + 3°C, not just LIMIT
    if temp >= effective_trip_point:
        return True  # TRIP ACTIVATED
    return False  # Still within tolerance
```

**Example:**
```python
configured_limit = 100.0  # °C
sensor_reading = 101.5    # °C

if check_over_temp_quirk(sensor_reading, configured_limit):
    print("No trip yet")  # 101.5 < 103.0, still OK

sensor_reading = 103.5    # °C

if check_over_temp_quirk(sensor_reading, configured_limit):
    print("TRIP!")  # 103.5 >= 103.0, trips now
```

#### Quirk 2: Hysteresis Band Width

**Behavior:**
- Reset threshold is **5°C below trip point**, not configured limit
- Prevents rapid cycling near boundary
- Creates asymmetric recovery window

**Formula:**
```
Trip Point = Configured Limit + 3°C
Reset Point = Trip Point - 5°C
            = Configured Limit - 2°C

Hysteresis Width = 5°C (fixed)
```

**Example:**
```python
configured_limit = 100.0
trip_point = 103.0  # 100 + 3
reset_point = 98.0  # 103 - 5

Current State: NORMAL
Temperature rises:
  101.0 → Normal (below trip)
  102.5 → Normal (below trip)
  103.5 → TRIPS (above trip point)

After Trip: OVERTEMP_ACTIVE
Temperature falls:
  103.0 → Still TRIPPED (above reset)
  101.0 → Still TRIPPED (above reset)
   97.5 → RESETS (below reset point of 98.0)
```

#### Quirk 3: Debounce Timer

**Behavior:**
- Must exceed trip threshold for **5 consecutive seconds** before tripping
- Short spikes do NOT trigger trip
- Counter resets if temperature drops below threshold

**Implementation:**
```python
class OverTempQuirkHandler:
    DEBOUNCE_DURATION = 5.0  # seconds
    
    def __init__(self):
        self.above_threshold_seconds = 0.0
        
    def update(self, current_temp, configured_limit):
        effective_limit = configured_limit + 3.0
        
        if current_temp >= effective_limit:
            self.above_threshold_seconds += 1.0
            
            if self.above_threshold_seconds >= self.DEBOUNCE_DURATION:
                return "TRIP"  # Triggered after 5 seconds continuous
                
        else:
            self.above_threshold_seconds = 0.0  # Reset counter
            
        return "OK"
```

**Test Case:**
```python
handler = OverTempQuirkHandler()
limit = 100.0

# Spike test: 105°C for 4 seconds
for second in range(4):
    result = handler.update(105.0, limit)
    
assert result == "OK"  # No trip, debounce timer expired

# Continuous test: 105°C for 6 seconds
handler2 = OverTempQuirkHandler()
for second in range(6):
    result = handler2.update(105.0, limit)

assert result == "TRIP"  # Trip triggered at second 5+
```

### 2.3 Complete Quirk Simulation Example

```python
from simulator.invalid_sensor_handler import (
    InvalidSensorHandler,
    ControlMode,
    SensorReading
)

def simulate_real_world_quirk_scenario():
    """End-to-end example with all quirks active"""
    handler = InvalidSensorHandler()
    
    # Configuration
    setpoint = 100.0
    actual_temp = 98.0
    
    # Phase 1: Approaching limit normally
    while actual_temp <= 102.0:
        ir_reading = SensorReading(value=actual_temp, valid=True)
        tc_reading = SensorReading(value=actual_temp + 0.5, valid=True)
        
        output = handler.get_safe_output(ControlMode.ISO1, ir_reading, tc_reading)
        assert output > 0  # Normal operation
        
        actual_temp += 1.0
        
    # Phase 2: Entering quirk zone (103.0°C = setpoint + 3)
    actual_temp = 103.0
    ir_reading = SensorReading(value=actual_temp, valid=True)
    tc_reading = SensorReading(value=actual_temp + 0.5, valid=True)
    
    # With quirk, this DOESN'T trip yet (debounce starts)
    # After 5 seconds of continuous 103.0+:
    # - Actual temperature has drifted to 104.0
    # - Trip activates
    # - Heating element shuts off
    # - Temp stabilizes around 103.5°C steady-state
    
    # Phase 3: Recovery
    actual_temp = 98.0  # Cooled down significantly
    
    # Even though below setpoint (100.0), still latched due to hysteresis
    # Need to go below 98.0 (setpoint - 2.0) to reset
    
    return {
        "trip_triggered_at": 103.0 + 3.0,  # Trip delta adds 3°C
        "reset_required_below": 100.0 - 2.0,  # Hysteresis - 2°C
        "debounce_duration_sec": 5
    }
```

---

## 3. Timeout Thresholds and Safe Output Values

### 3.1 Default Timeouts

| Sensor Type | Default Timeout | Description |
|-------------|-----------------|-------------|
| IR (Infrared) | 5 readings | Consecutive invalid before declaring fault |
| TC (Thermocouple) | 5 readings | Same as IR |
| Lux (Ambient) | 5 readings | Does NOT affect temperature control |

**Note:** Timeouts are configurable via constructor parameters but default to 5 for all sensors.

### 3.2 Timeout Mechanics

**Counter-Based System:**
```
Initial: consecutive_invalid_count = 0

On each invalid reading:
  consecutive_invalid_count += 1
  
If consecutive_invalid_count >= timeout_threshold:
  sensor_valid = False
  mark_as_definitively_faulty = True
  
On valid reading:
  consecutive_invalid_count = 0
  sensor_valid = True
```

**Time-Between-Readings Consideration:**
- Firmware assumes fixed 100ms sampling rate
- Real timeout duration = 5 readings × 100ms = **500ms minimum**
- In practice, varies based on actual loop timing

### 3.3 Safe Output Values

All legacy modes use **zero** as the safe output:

```python
SAFE_OUTPUT_IR_ZERO = 0.0   # W/cm² or equivalent units
SAFE_OUTPUT_TC_ZERO = 0.0   # °C target temperature
ZERO_CONDITIONING_ENABLED = True
```

**When Zero is Applied:**
1. Both IR and TC invalid in ISO1 mode
2. Selected sensor invalid in PLAT1 mode
3. Timeout threshold exceeded (any combination)

**Never Apply Zero When:**
- At least one valid sensor available and providing data
- Sensor just became invalid (< timeout threshold reached)
- During startup calibration phase (pre-fault)

### 3.4 Numerical Thresholds Summary

| Parameter | Value | Unit | Notes |
|-----------|-------|------|-------|
| Default Timeout | 5 | readings | Per sensor |
| Safe Output Value | 0.0 | various | All units |
| Over-Temp Trip Delta | +3.0 | °C | Adds to configured limit |
| Over-Temp Hysteresis | -5.0 | °C | Below trip point |
| Over-Temp Debounce | 5.0 | seconds | Minimum above-threshold time |

---

## 4. ExtendedTelemetry Integration

### 4.1 Valid Fields Structure

The `InvalidSensorHandler` provides comprehensive status data for telemetry integration:

```python
status = handler.get_sensor_status()

# Returned structure:
{
    "ir_valid": True/False,           # Current validity flag
    "ir_consecutive_invalid": 0-10+,  # Count for diagnostics
    "ir_last_valid_time": timestamp,  # Unix epoch float
    "ir_last_invalid_time": timestamp,  # Unix epoch float
    
    "tc_valid": True/False,
    "tc_consecutive_invalid": 0-10+,
    "tc_last_valid_time": timestamp,
    "tc_last_invalid_time": timestamp,
    
    "lux_valid": True/False,
    "lux_consecutive_invalid": 0-10+,
    "lux_last_valid_time": timestamp,
    "lux_last_invalid_time": timestamp,
}
```

### 4.2 Telemetry Mapping

Map handler status to telemetry fields:

```python
def populate_telemetry(handler: InvalidSensorHandler):
    """Generate telemetry packet matching physical device format"""
    status = handler.get_sensor_status()
    
    return {
        # Valid flags
        "IR_valid": status["ir_valid"],
        "TC_valid": status["tc_valid"],
        "LUX_valid": status["lux_valid"],
        
        # Diagnostic counts (help debug intermittent faults)
        "IR_invalid_count": status["ir_consecutive_invalid"],
        "TC_invalid_count": status["tc_consecutive_invalid"],
        "LUX_invalid_count": status["lux_consecutive_invalid"],
        
        # Timing information
        "IR_last_seen_ms": int(status["ir_last_invalid_time"] * 1000),
        "TC_last_seen_ms": int(status["tc_last_invalid_time"] * 1000),
        
        # Output source tracking
        "OutputSource": handler.output_source,  # e.g., "IR", "TC", "zero_fallback"
        "SafeOutputValue": handler.current_safe_output,
    }
```

### 4.3 Logging Requirements

Log events for firmware debugging:

```python
import logging

logger = logging.getLogger(__name__)

def log_sensor_event(event_type: str, sensor_type: str, details: dict):
    """Format matches physical firmware event logs"""
    log_entry = {
        "timestamp": time.time(),
        "event_type": event_type,
        "sensor": sensor_type,
        **details
    }
    
    if event_type == "SENSOR_INVALID_TIMEOUT":
        logger.warning(f"FIRMWARE_QUIRK: Sensor {sensor_type} timed out - {log_entry}")
        
    elif event_type == "SAFE_OUTPUT_ACTIVATED":
        logger.info(f"FIRMWARE_BEHAVIOR: Zero output applied - {log_entry}")
        
    elif event_type == "SENSOR_RECOVERED":
        logger.debug(f"FIRMWARE_STATUS: Sensor recovered - {log_entry}")
```

---

## 5. Testing Guidelines

### 5.1 Required Test Coverage

All invalid sensor scenarios must pass:

✅ **IR Sensor Failure Scenarios**
- IR invalid during ramp phase
- IR timeout triggering safe output
- IR+TC both invalid simultaneously
- IR recovery after fault clearance

✅ **TC Sensor Failure Scenarios**
- TC invalid during hold phase
- TC timeout triggering safe output
- TC recovery sequence
- TC dominant mode behavior

✅ **Lux Sensor Isolation**
- Lux invalid has NO impact on temperature
- Lux recovery produces no side effects

✅ **Timeout Thresholds**
- Configurable thresholds (per sensor)
- Default threshold is 5 readings
- Counters reset on valid reading

✅ **Safe Output Values**
- Zero output when required
- Source tracking for diagnostics
- Immediate application on timeout

✅ **Determinism Verification**
- Fixed seed produces identical sequences
- Reproducible failure patterns
- Same inputs always produce same outputs

### 5.2 Evidence Collection

For physical verification, capture:

1. **Raw sensor readings** before and during fault
2. **Consecutive invalid counters** at each step
3. **Output values** from controller
4. **Timestamps** of transitions
5. **Safe output activation** timing

Example evidence collection:
```python
evidence = []

# Record initial state
evidence.append({
    "phase": "NORMAL",
    "status": handler.get_sensor_status(),
    "output": handler.get_safe_output(...)
})

# Trigger fault
handler.ir_valid = False

# Record after fault
evidence.append({
    "phase": "FAULT_DETECTED",
    "status": handler.get_sensor_status(),
    "output": handler.get_safe_output(...),
    "source": handler.output_source
})

# Timeout triggers
evidence.append({
    "phase": "TIMEOUT_TRIGGERED",
    "consecutive_invalid": handler._ir_consecutive_invalid,
    "output_zeroed": handler.current_safe_output == 0.0
})

# Verify determinism
seed_data = random.seed(123)
run1_evidence = collect_sequence()
random.seed(123)
run2_evidence = collect_sequence()

assert run1_evidence == run2_evidence, "Determinism violated!"
```

---

## 6. Important Constraints

### 6.1 NO CORRECTIONS ALLOWED

⚠️ **Critical:** The simulator must reproduce exact current firmware behavior:

❌ **DO NOT:**
- Implement automatic fallback to backup sensors
- Add smart interpolation for missing data
- Improve timeout thresholds
- Reduce hysteresis or debounce times
- Apply modern control algorithms

✅ **DO:**
- Reproduce every quirk exactly
- Keep zero-conditioning intact
- Maintain 3°C trip delta
- Preserve 5-second debounce
- Use hardcoded 5° hysteresis band

### 6.2 Firmware Parity Requirement

The simulator's behavior MUST match the physical device under ALL conditions:

```python
# Physical device behavior reference:
# - Takes 5 readings to declare fault
# - Returns 0.0 on fault
# - Trip at limit + 3°C
# - Requires 98°C to recover from 100°C limit
# - Debounces for 5 seconds

# Simulator must replicate EXACTLY:
def test_firmware_parity():
    sim = InvalidSensorHandler()
    phys_device_behavior = "5-read-timeout + 3C-delta + 5C-hysteresis + 5s-debounce"
    
    assert sim.ir_timeout_threshold == 5  # Same timeout
    assert sim.SAFE_OUTPUT_IR_ZERO == 0.0  # Same safe output
    
    # Trip delta would be verified in separate overtemp tests
    # Hysteresis verified in separate hysteresis tests
    
    # This ensures simulator is byte-compatible with physical firmware
    verify_physical_equivalence(sim)
```

---

## 7. References

### 7.1 Related Documentation

- `INTERFACE_PHASE3.md` - Phase 3 interface specifications
- `simulator/invalid_sensor_handler.py` - Implementation code
- `tests/test_simulator_invalid_sensor_handling.py` - Comprehensive test suite

### 7.2 Key Design Decisions

1. **Invalid-to-Zero Priority**: Immediate zero output is safer than estimation
2. **Configurable Timeouts**: Allows tuning per deployment scenario
3. **Separate Lux Handling**: Ambient light doesn't affect thermal control
4. **Over-Temp Conservatism**: Extra margins prevent false trips from noise

### 7.3 Known Limitations

- No graceful degradation (all-or-nothing zero output)
- Manual intervention required after multi-sensor failures
- Long debounce may delay legitimate over-temp responses
- Hysteresis asymmetry can confuse operators expecting symmetric behavior

These limitations are intentional and match physical firmware constraints.
