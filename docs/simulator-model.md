# PT-Kit Simulator Plant Model Documentation

## Overview

This document describes the two-node thermal plant model and sensor models used in the PT-Kit digital-twin simulator. The model is designed to be deterministic, unit-aware, and extensible through profile configuration.

## Two-Node Thermal Plant Model

### Physical Rationale

The PT-Kit instrument has two distinct thermal masses:
1. **Surface node**: Rapidly responding metal block/lamp assembly
2. **Bulk node**: Slower sample chamber holding specimens

Heat flows between these nodes with different time constants.

### State Variables

| Variable | Units | Description |
|----------|-------|-------------|
| `surface_temp_c` | °C | Surface temperature |
| `bulk_temp_c` | °C | Bulk/sample temperature |
| `lamp_output_lux` | lux | Lamp optical output |
| `fan_airflow` | normalized 0–1 | Fan effective airflow |
| `time_s` | seconds | Elapsed virtual time |

### Governing Equations

Energy balance for each node:

```
C_s * dT_s/dt = P_optical + G_sb*(T_b - T_s) - G_sa*(T_s - T_ambient) - G_fa*PWM_fan*(T_s - T_ambient)
C_b * dT_b/dt = G_sb*(T_s - T_b) - G_ba*(T_b - T_ambient)
```

Where:
- `C_s`, `C_b`: thermal capacities (J/K)
- `G_sb`: surface–bulk conductance (W/K)
- `G_sa`: surface–ambient conductance (W/K)
- `G_ba`: bulk–ambient conductance (W/K)
- `G_fa`: fan-dependent conductance coefficient (W/K/PWM_max)
- `P_optical`: absorbed optical power (W)

### Actuator Models

#### Lamp Response

Lamp PWM → Optical Output follows first-order lag:

```
τ_lamp * d(P_opt)/dt + P_opt = (PWM / 255) * P_max
```

With:
- `τ_lamp`: lamp response time constant (s)
- `P_max`: maximum optical power (W)
- Lamp output saturates at `lux_saturation_high_lux`

#### Fan Response

Fan PWM → Additional convective cooling:

```
τ_fan * d(PWM_fan_eff)/dt + PWM_fan_eff = PWM / 255
G_fan_added = PWM_fan_eff * G_fan_max
```

### Analytic Time Integration

The plant uses analytic first-order solutions for numerical stability:

For a linear ODE `dy/dt = (y_target - y)/τ`:

```
y[t+dt] = y[t] + (1 - exp(-dt/τ)) * (y_target - y[t])
```

This guarantees:
- Stability for any `dt`
- No overshoot for step inputs
- Energy conservation (finite outputs)

## Sensor Models

Each sensor type includes realistic imperfections:

### IR Sensor (Surface Temperature)

Models an MLX90614 non-contact infrared thermometer:
- Fast thermal response (~50 ms time constant)
- Small bias and drift
- Quantization at 0.05°C steps
- Saturation limits: [-40°C, 150°C]
- Random invalidity probability ~0.1%

### TC Sensor (Bulk Temperature)

Models a MAX6675 thermocouple amplifier:
- Slower response (~100 ms time constant)
- Larger noise than IR
- Quantization at 0.1°C steps
- Saturation limits: [-50°C, 200°C]

### Lux Sensor (Optical Output)

Models BH1750 ambient light detection:
- Very fast response (~20 ms)
- Direct mapping to lamp output
- Quantization at 1 lux steps
- Saturation at 20,000 lux

### Noise Model

Bounded Gaussian noise:
```
measurement = true_value + bias + drift(t) + noise(σ) * clamp([-3σ, +3σ])
```

Drift accumulates linearly over elapsed virtual time.

## Profile System

Profiles package all parameters into versioned configurations:

### Validation Status Levels

| Status | Meaning | UI Label |
|--------|---------|----------|
| `UNCALIBRATED_SYNTHETIC` | Default synthetic values | Uncalibrated Synthetic Plant |
| `UNDER_REVIEW` | Fitted, pending validation | Under Review |
| `CALIBRATED` | Meets acceptance criteria | Calibrated Digital Twin |
| `DEPRECATED` | Avoid using | Deprecated |

### Profile Structure

```json
{
  "profile_id": "unique-id",
  "model_version": "2-node-thermal-v1.0",
  "validation_status": "UNCALIBRATED_SYNTHETIC",
  "validity_domain": { ... },
  "parameters": { ... },
  "source_dataset": null,
  "fit_metrics": null
}
```

All parameters include units via naming convention:
- `*_c`: degrees Celsius
- `*_lux`: lux
- `*_w`: watts
- `*_per_k`: per kelvin
- `*_s`: seconds
- `*_j_per_k`: joules per kelvin

## Determinism Guarantees

1. **No hidden randomness**: All stochastic behavior comes from explicitly seeded RNG streams.
2. **Reproducible runs**: Same seed produces identical sequences.
3. **Stream independence**: Fault injection does not affect physical-noise sequences.

## Calibration Acceptance Gates (Future)

When real data is available, acceptance thresholds will include:

| Metric | Target |
|--------|--------|
| IR RMSE | < 0.5°C |
| TC RMSE | < 0.8°C |
| Heating slope error | < 5% |
| Cooling slope error | < 5% |
| Time-to-threshold error | < 10 s |
| IR–TC lag error | < 2 s |
| Steady-state error | < 0.3°C |
| Plateau-temp error | < 0.5°C |

These thresholds are placeholders and must be determined from repeatability studies before calibration.

## API Reference

### PlantConfig

```python
@dataclass
class PlantConfig:
    # Thermal capacities (J/K)
    surface_capacity_j_per_k: float
    bulk_capacity_j_per_k: float
    
    # Conductances (W/K)
    surface_bulk_conductance_w_per_k: float
    surface_ambient_conductance_w_per_k: float
    bulk_ambient_conductance_w_per_k: float
    
    # Lamp model
    lamp_max_power_w: float          # W at PWM=255
    lamp_response_time_s: float      # seconds
    lamp_max_lux: float              # lux
    
    # Fan model
    fan_max_conductance_w_per_k: float
    fan_response_time_s: float
    
    # Ambient
    ambient_temp_c: float
    max_substep_s: float = 0.1
```

### SensorConfig

```python
@dataclass
class SensorConfig:
    # IR sensor
    ir_response_time_s: float        # seconds
    ir_bias_c: float                 # °C
    ir_drift_rate_per_s: float       # °C/s
    ir_noise_std: float              # °C
    ir_quantization_step: float      # °C
    ir_saturation_low_c: float
    ir_saturation_high_c: float
    
    # TC sensor (same fields with tc_* prefix)
    
    # Lux sensor (same fields with lux_* prefix)
    
    # Global
    random_invalid_probability: float  # 0.0–1.0
```

## Testing Guidance

Plant tests should verify:
- Zero-output equilibrium
- Monotonic heating under fixed lamp
- Stronger lamp increases rate
- Higher fan increases cooling
- Finite energy/temperatures
- Large-step stability
- Irregular-step determinism

Sensor tests should verify:
- Lag dynamics match first-order theory
- Quantization aligns to grid
- Bounded outputs
- Validity flags behave correctly
