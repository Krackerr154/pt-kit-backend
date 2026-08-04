# Phase 3 Golden Trace Specification

## Overview

This document defines the golden trace format used for differential testing of Phase 3 controller implementations. Golden traces provide deterministic reference outputs against which new simulation runs can be compared to detect behavioral regressions.

## Trace Format

Golden traces are stored as JSON files in `tests/fixtures/simulator/golden/<scenario>.json`.

### Root Schema

```json
{
  "scenario": "<scenario_name>",
  "seed": <random_seed>,
  "plant_config": { /* PlantConfig serialized */ },
  "command": { /* Command parameters serialized */ },
  "traces": [ /* Array of frame objects */ ]
}
```

### Field Descriptions

#### Root Level Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `scenario` | string | Yes | Scenario identifier (e.g., `ISO1_default_target`) |
| `seed` | int | Yes | Random seed used for deterministic execution |
| `plant_config` | object | Yes | Plant configuration parameters |
| `command` | object | Yes | Command parameters passed to controller |
| `traces` | array | Yes | Sequence of telemetry frames |

#### PlantConfig Object

All parameters carry explicit units in their names.

```json
{
  "surface_capacity_j_per_k": 100.0,
  "bulk_capacity_j_per_k": 200.0,
  "surface_bulk_conductance_w_per_k": 5.0,
  "surface_ambient_conductance_w_per_k": 2.0,
  "bulk_ambient_conductance_w_per_k": 1.0,
  "lamp_max_power_w": 50.0,
  "lamp_response_time_s": 0.5,
  "lamp_max_lux": 10000.0,
  "fan_max_conductance_w_per_k": 10.0,
  "fan_response_time_s": 0.2,
  "ambient_temp_c": 25.0,
  "max_substep_s": 0.1
}
```

#### Command Object

Depends on experiment mode:

**ISO1 Command:**

> ⚠️ **CORRECTION (2026-08-03):** The earlier version of this section used a simulator-side JSON shape (`duration_s`, `qualification_cycles`, `temp_range_lower_c`, …) that does **not** match the parameters of `app/protocol.py::serialize_fixed_command`. The fields below match the production wire command `ISO1:{target_temp}:{hold_s}:{tolerance}:{qualify_s}:{max_temp}:{interval}:{sensor}:{ramp_rate}`.

```json
{
  "mode": "ISO1",
  "target_temperature": 37.0,
  "hold_duration_s": 60,
  "temperature_tolerance": 0.2,
  "qualification_dwell_s": 60,
  "max_temp": 80.0,
  "interval": 1,
  "control_sensor": "IR",
  "ramp_rate": 5.0
}
```

| JSON field | `serialize_fixed_command` arg | Wire position |
|---|---|---|
| `target_temperature` | `target_temp_c` | 1 |
| `hold_duration_s` | `hold_seconds` | 2 |
| `temperature_tolerance` | `tolerance_c` | 3 |
| `qualification_dwell_s` | `qualification_seconds` | 4 |
| `max_temp` | `max_temp_c` | 5 |
| `interval` | `log_interval_s` | 6 |
| `control_sensor` | `sensor` (`IR`\|`TC`) | 7 |
| `ramp_rate` | `ramp_rate_c_per_min` | 8 |

**PLAT1 Command:** field names follow `serialize_plateau_command` (`target_lux`, `hold_seconds`, `window_seconds`, `max_abs_slope_c_per_min`, `max_peak_to_peak_c`, `confirmation_seconds`, `max_discovery_seconds`, `max_temp_c`, `log_interval_s`, `sensor`, `post_plateau_mode`).

**CAL_BARE Command:** (calibration sequence parameters)

### Frame Schema

Each element in `traces` array represents a single time step.

```json
{
  "virtual_time_s": 1.0,
  "state": "STABILIZING",
  "actuator": {
    "lamp_pwm": 128,
    "fan_pwm": 64
  },
  "telemetry": {
    "timestamp_s": 1.0,
    "controller_state": 5,
    "supervision_flag": 0,
    "surface_temp_c": 26.5,
    "bulk_temp_c": 25.8,
    "lamp_output_lux": 4250.5,
    "target_temp_c": 37.0,
    "setpoint_temp_c": 37.0,
    "hold_temp_c": null,
    "current_cycle": 0,
    "total_cycles": 3,
    "elapsed_hold_s": null,
    "max_slope_c_per_min": null,
    "min_slope_c_per_min": null,
    "average_slope_c_per_min": null,
    "side_channel_message": null
  },
  "side_channel": null
}
```

#### Frame Field Details

**Required Top-Level Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `virtual_time_s` | float | Simulation time in seconds (monotonically increasing) |
| `state` | string | Controller state name (IDLE, WARMUP, STABILIZING, HOLDING, DONE, etc.) |
| `actuator` | object | Current actuator PWM values |
| `telemetry` | object | Extended telemetry data |

**Actuator Object:**

| Field | Type | Range | Description |
|-------|------|-------|-------------|
| `lamp_pwm` | int | 0-255 | Lamp PWM duty cycle |
| `fan_pwm` | int | 0-255 | Fan PWM duty cycle |

**Telemetry Object (17 fields):**

| Field | Type | Description |
|-------|------|-------------|
| `timestamp_s` | float | Same as virtual_time_s |
| `controller_state` | int | ControllerState enum value (0-15) |
| `supervision_flag` | int | SupervisionFlag enum value |
| `surface_temp_c` | float | Surface temperature in °C |
| `bulk_temp_c` | float | Bulk temperature in °C |
| `lamp_output_lux` | float | Lamp output intensity in lux |
| `target_temp_c` | float? | Experiment target temperature (nullable) |
| `setpoint_temp_c` | float? | Current setpoint (nullable) |
| `hold_temp_c` | float? | Hold temperature threshold (nullable) |
| `current_cycle` | int? | Current qualification cycle number (nullable) |
| `total_cycles` | int? | Total qualification cycles (nullable) |
| `elapsed_hold_s` | float? | Time spent in hold phase (nullable) |
| `max_slope_c_per_min` | float? | Maximum measured slope (nullable) |
| `min_slope_c_per_min` | float? | Minimum measured slope (nullable) |
| `average_slope_c_per_min` | float? | Average slope over window (nullable) |
| `side_channel_message` | string? | Side-channel message if any (nullable) |

**Simulator ↔ production wire field-name mapping:**

> The simulator telemetry names above are plant/controller-side names. They do **not** match the production wire/backend field names in `app/protocol.py::parse_telemetry` / `app/main.py`. Use this table to map a golden-trace frame onto a production telemetry row (and vice versa):

| Golden-trace (sim) | Production wire/backend | Notes |
|---|---|---|
| `timestamp_s` | `total_time` (+ `phase_time`) | wire carries both total and phase time |
| `controller_state` | `state_code` (→ `state_label` via STATE_LABELS) | same 0–15 enum |
| `surface_temp_c` | `ir_temp` | surface ≈ IR sensor |
| `bulk_temp_c` | `tc_temp` | bulk ≈ thermocouple |
| `lamp_output_lux` | `current_lux` | |
| `target_temp_c` | `temp_setpoint` | experiment target |
| `setpoint_temp_c` | `control_temp` | active control value |
| `lamp_pwm` (actuator) | `lamp_pwm` (field 13) | same name |
| `elapsed_hold_s` | `hold_wall_elapsed_s` / `hold_qualified_elapsed_s` | wire splits wall vs qualified |
| `supervision_flag`, `hold_temp_c`, `current_cycle`, `total_cycles`, `max/min/average_slope_c_per_min`, `side_channel_message` | *(no direct wire field)* | sim-only; `cycle_num` on wire ≈ `current_cycle`; `detected_plateau_temp` (wire) has no sim counterpart in this schema |

Full production layout: see `docs/BACKEND_API.md` §10 (Telemetry Wire Format) and §11 (State Code Map).

**Floating-Point Tolerance:**

When comparing traces, numeric comparisons use:
- **Temperature fields**: ±0.001°C tolerance
- **Time fields**: ±0.001s tolerance  
- **PWM fields**: exact integer match required
- **Lux fields**: ±0.1 lux tolerance

## Comparison Rules

### Determinism Guarantee

Golden traces are generated with fixed random seeds and must be bit-for-bit reproducible when:
1. Same scenario parameters
2. Same plant configuration
3. Same command sequence
4. No external randomness (browser, network, database)

### Deviation Detection

Any deviation from golden trace indicates potential regression:

**Critical deviations (must fail test):**
- State machine jumps or skips states
- PWM values differ by more than 1 LSB
- Temperature readings drift beyond floating-point tolerance
- Timing regressions (time not monotonically increasing)

**Warning deviations (flag but may pass):**
- Floating-point rounding differences > tolerance
- Minor timing variations due to system load

### Update Procedure

To intentionally update golden traces after valid changes:

1. Modify simulation logic intentionally
2. Regenerate traces with same seed
3. Review diffs manually using `git diff tests/fixtures/simulator/golden/`
4. Commit both code and golden trace updates together
5. Document the change rationale in commit message

## Scenario Naming Convention

Scenarios follow the pattern: `<Mode>_<Variant>_<Parameters>`

Examples:
- `ISO1_default_target` - ISO1 mode with default 37°C target
- `PLAT1_default` - PLAT1 mode with default 85°C plateau
- `CAL_BARE_default` - Bare board calibration sequence

## Test Execution

Run golden trace validation:

```bash
python tests/test_simulator_golden_diff_validated.py
```

Or run all Phase 3 tests including plant/sensor/profile tests:

```bash
pytest -q tests/test_simulator_plant.py tests/test_simulator_sensors.py \
       tests/test_simulator_profiles.py tests/test_simulator_golden_diff_validated.py
```

## Future Enhancements

Planned improvements:
- Add parameterized scenarios with varied targets
- Support replay of physical experiment logs as golden references
- Integrate with CI pipeline for automated regression detection
- Visual diff tools for trace comparison

---

*Last updated: 2026-08-03 | PT-Kit Digital Twin Simulator v3.0 — ISO1 command JSON + telemetry field names reconciled with app/protocol.py wire format*
