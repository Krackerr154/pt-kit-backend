# Phase 3 Interface Contract

This document defines the interfaces for Phase 3 implementation so parallel subagents produce compatible code.

## Plant Integration

### Inputs to Controller

```python
@dataclass
class PlantState:
    surface_temp_c: float  # Surface temperature, °C
    bulk_temp_c: float     # Bulk/sample temperature, °C
    lamp_output_lux: float # Lamp optical output, lux
    time_s: float          # Elapsed virtual time, s
```

Controller samples these via `plant.sample(state)`.

### Command Processing

```python
@dataclass  
class PlantConfig:
    # From Phase 2 - thermal capacities, conductances, lamp/fan models
    surface_capacity_j_per_k: float
    bulk_capacity_j_per_k: float
    surface_bulk_conductance_w_per_k: float
    surface_ambient_conductance_w_per_k: float
    bulk_ambient_conductance_w_per_k: float
    lamp_max_power_w: float
    lamp_response_time_s: float
    lamp_max_lux: float
    fan_max_conductance_w_per_k: float
    fan_response_time_s: float
    ambient_temp_c: float
    max_substep_s: float = 0.1

@dataclass
class SensorConfig:
    ir_response_time_s: float
    tc_response_time_s: float
    lux_response_time_s: float
    # + bias/noise/quantization/saturation params
```

## Controller Output Interface

### State Machine Status

```python
class ControllerState(IntEnum):
    IDLE = 0
    PRE_HEAT = 1
    HEATING = 2
    COOLING = 3
    STABILIZING = 4
    DONE = 5
    CAL_BARE = 6
    CAL_TAPE = 7
    CAL_FULL = 8
    ISO_RAMP = 9
    ISO_QUALIFY = 10
    ISO_HOLD = 11
    PLATEAU_HEATING = 12
    PLATEAU_CONFIRM = 13
    PLATEAU_HOLD = 14
    ABORTED = 15
```

### Telemetry Frame Structure

```python
@dataclass
class ExtendedTelemetry:
    """17-field extended telemetry frame."""
    # First 7 are legacy fields:
    frame_number: int        # Frame counter
    state_code: int          # ControllerState enum value
    surface_temp_c: float    # Surface node temperature
    bulk_temp_c: float       # Bulk node temperature
    lamp_pwm: int            # Lamp PWM (0-255)
    fan_pwm: int             # Fan PWM (0-255)
    lux_reading: float       # Lux sensor reading
    
    # Additional 10 fields (indices 7-16):
    target_temp_c: float | None   # Target temperature for ISO mode
    hold_time_s: float | None     # Hold duration
    cycle_count: int              # Current cycle number
    elapsed_s: float              # Elapsed time in current phase
    setpoint_error_c: float       # |target - measured|
    qualification_passed: bool    # ISO qualify status
    plateau_status: str | None    # heating/confirm/hold/null
    calibration_result: str | None # CALRESULT payload
    supervisor_abort: bool        # Supervisory abort flag
    run_id: str | None            # UUID from Phase 5 (optional in Phase 3)
```

### Side-Channel Messages

```python
@dataclass
class SideChannelMessage:
    message_type: Literal["STOP", "ABORT", "SUPERVISOR_ABORT", 
                         "ERR", "MAXLUX", "CALBARE", "CALTAPE"]
    payload: str | None  # Message-specific payload
```

## Actuator Commands

```python
@dataclass
class ActuatorCommand:
    lamp_pwm: int  # 0-255
    fan_pwm: int   # 0-255
    
    def validate(self) -> bool:
        return 0 <= self.lamp_pwm <= 255 and 0 <= self.fan_pwm <= 255
```

## Experiment Modes

### Fixed-Temperature Mode (ISO1)

```python
@dataclass
class ISO1Command:
    target_temp_c: float
    hold_duration_s: float
    tolerance_c: float
    qualification_cycles: int
    max_temp_c: float
    interval_s: float
    sensor_selection: int  # IR=0, TC=1
    ramp_rate_limit_c_per_s: float | None  # Optional
```

**Behavior:**
- Ramp to `target_temp_c` at specified rate if given
- Wait until within `tolerance_c` of target
- Perform `qualification_cycles` valid passes through range [target±tol]
- Enter `hold_duration_s` after qualification completes
- On completion: state=DONE, emit DONE frame

### Plateau Mode (PLAT1)

```python
@dataclass
class PLAT1Command:
    target_lux: float
    hold_duration_s: float
    window_lux: float
    max_slope_lux_per_s: float
    max_range_lux: float
    confirmation_samples: int
    max_discovery_time_s: float
    max_temp_c: float
    interval_s: float
    sensor_selection: int  # IR=0, TC=1
    post_mode: str         # continuation mode after plateau
```

**Behavior:**
- Maintain lamp output near `target_lux`
- Validate temperature stability within `max_range_lux`
- Check slope < `max_slope` during confirm period
- After `confirmation_samples` consecutive stable readings: enter hold
- Hold for `hold_duration_s`
- On completion: state=DONE

### Calibration Modes

#### CAL_BARE
```python
@dataclass
class CalBareCommand:
    pass  # No parameters

# Behavior: bare board calibration sequence
# States: CAL_BARE → CALTAPE:... → DONE
```

#### CAL_TAPE
```python
@dataclass
class CalTapeCommand:
    pass  # Tape calibration sequence
```

#### CAL_FULL
```python
@dataclass
class CalFullCommand:
    pass  # Full calibration combines CAL_BARE + CAL_TAPE
```

## Termination Semantics

### STOP vs ABORT

```text
STOP:
- Graceful stop, maintains current state
- Emits telemetry with final measurements
- Returns to IDLE without firmware ABORT
- Idempotent: repeated STOP has no additional effect

ABORT:
- Firmware-generated by over-temperature or fault
- Sets state=ABORTED
- Emits MAXLUX or ERR message as appropriate
- Requires power-cycle or manual reset to recover

SUPERVISOR_ABORT:
- Simulator-generated (Phase 5+)
- Emergency termination
- Sets state=ABORTED internally
- Does NOT produce firmware ABORT sequence
```

## Golden Trace Requirements

For each test scenario, capture:
- Timestamped state transitions
- Actuator commands emitted
- Telemetry frames generated
- Side-channel messages produced

Format:
```json
{
  "scenario": "ISO1_default_target",
  "seed": 42,
  "plant_config": {...},
  "command": {"mode": "ISO1", "target_temp_c": 37.0, ...},
  "traces": [
    {
      "virtual_time_s": 0.0,
      "state": "PRE_HEAT",
      "actuator": {"lamp_pwm": 200, "fan_pwm": 0},
      "telemetry": { /* 17-field frame */ },
      "side_channel": null
    },
    // ... more entries
  ]
}
```

## Testing Guidelines

All tests must verify:
1. **Determinism**: Same seed produces identical traces
2. **Mode correctness**: Fixed-temp, plateau, and calibration modes reach expected states
3. **Stop behavior**: STOP command is idempotent and does not trigger firmware ABORT
4. **Termination semantics**: SUPERVISOR_ABORT ≠ firmware ABORT ≠ DONE
5. **Invalid sensor handling**: Follows current firmware behavior (timeout/safe-output)
6. **Over-temperature quirk**: Reproduces existing behavior exactly

## API Usage Examples

```python
from app.simulator.controller import PTKitController
from app.simulator.plant import ThermalPlant
from app.simulator.config import PlantConfig, SensorConfig
from app.simulator.clock import VirtualClock

# Setup
config = PlantConfig(...)
sensor_config = SensorConfig(...)
plant = ThermalPlant(config)
controller = PTKitController(sensor_config)
clock = VirtualClock(seed=42)

# Execute ISO1 mode
clock.tick()
plant.step(lamp_pwm=0, fan_pwm=0, dt_s=0.1)

controller.apply_command(ISO1Command(target_temp_c=37.0, hold_duration_s=60.0, ...))

while controller.state != ControllerState.DONE:
    controller.tick(clock.dt_s())
    plant.step(controller.lamp_pwm, controller.fan_pwm, clock.dt_s())
    clock.tick()
    
    if (frame := controller.poll_telemetry()):
        print(f"Frame {frame.frame_number}: {frame.target_temp_c:.1f}°C")
```
