# Phase 2 Interface Contract

This document defines the interfaces between Phase 2 components so they can be implemented in parallel.

## Plant State (from `plant.py`)

```python
@dataclass
class PlantState:
    """Two-node thermal plant state."""
    surface_temp_c: float      # Surface temperature, °C
    bulk_temp_c: float         # Bulk/sample temperature, °C
    ambient_temp_c: float      # Ambient temperature, °C
    lamp_output_lux: float     # Lamp optical output, lux
    fan_airflow: float         # Effective fan airflow, 0.0-1.0 normalized
    lamp_pwm: int              # Current lamp PWM, 0-255
    fan_pwm: int               # Current fan PWM, 0-255
    time_s: float              # Elapsed virtual time, seconds
```

## Plant Interface (from `plant.py`)

```python
class ThermalPlant:
    def __init__(self, config: PlantConfig, initial_state: PlantState | None = None): ...
    
    def step(self, lamp_pwm: int, fan_pwm: int, dt_s: float) -> PlantState:
        """Advance plant by dt_s seconds with given actuator commands."""
        ...
    
    @property
    def state(self) -> PlantState: ...
    
    def reset(self, initial_state: PlantState | None = None) -> None: ...
```

## Plant Config (from `config.py`)

```python
@dataclass
class PlantConfig:
    """All parameters with explicit units."""
    # Thermal capacities
    surface_capacity_j_per_k: float      # J/K
    bulk_capacity_j_per_k: float         # J/K
    
    # Thermal conductances
    surface_bulk_conductance_w_per_k: float   # W/K
    surface_ambient_conductance_w_per_k: float # W/K
    bulk_ambient_conductance_w_per_k: float    # W/K
    
    # Lamp model
    lamp_max_power_w: float              # W at PWM=255
    lamp_response_time_s: float          # seconds, first-order lag
    lamp_max_lux: float                  # lux at max optical output
    
    # Fan model
    fan_max_conductance_w_per_k: float   # W/K additional at PWM=255
    fan_response_time_s: float           # seconds, first-order lag
    
    # Ambient
    ambient_temp_c: float                # °C, can be overridden per-run
    
    # Integration
    max_substep_s: float = 0.1           # seconds, internal substep limit
```

## Sensor Reading (from `sensors.py`)

```python
@dataclass
class SensorReading:
    """Raw sensor measurement."""
    ir_temp_c: float          # IR sensor reading, °C
    ir_valid: bool            # IR sensor validity
    tc_temp_c: float          # Thermocouple reading, °C
    tc_valid: bool            # TC validity
    lux: float                # Lux sensor reading, lux
    lux_valid: bool           # Lux validity
```

## Sensor Interface (from `sensors.py`)

```python
class SensorModel:
    def __init__(self, config: SensorConfig, rng_streams: RNGStreams): ...
    
    def sample(self, plant_state: PlantState, dt_s: float) -> SensorReading:
        """Sample sensors given current plant state."""
        ...
    
    def reset(self) -> None: ...
```

## RNG Streams (from `random_streams.py`)

```python
class RNGStreams:
    """Independent deterministic RNG streams."""
    def __init__(self, seed: int = 42): ...
    
    @property
    def ir_noise(self) -> random.Random: ...
    @property
    def tc_noise(self) -> random.Random: ...
    @property
    def lux_noise(self) -> random.Random: ...
    @property
    def plant_disturbance(self) -> random.Random: ...
    @property
    def uart_fault(self) -> random.Random: ...
    @property
    def network_fault(self) -> random.Random: ...
```

## Profile (from `profiles.py`)

```python
@dataclass
class PlantProfile:
    profile_id: str
    model_version: str
    validation_status: str  # UNCALIBRATED_SYNTHETIC, CALIBRATED, etc.
    validity_domain: dict
    parameters: dict        # All parameters with units
    source_dataset: str | None
    fit_metrics: dict | None
    
    def to_plant_config(self) -> PlantConfig: ...
    def to_sensor_config(self) -> SensorConfig: ...
```

## File Ownership

| File | Owner Task |
|------|------------|
| `app/simulator/config.py` | Task 2.1 |
| `app/simulator/plant.py` | Task 2.1 |
| `tests/test_simulator_plant.py` | Task 2.1 |
| `app/simulator/sensors.py` | Task 2.2 |
| `app/simulator/random_streams.py` | Task 2.2 |
| `tests/test_simulator_sensors.py` | Task 2.2 |
| `app/simulator/profiles.py` | Task 2.3 |
| `app/simulator/profiles/synthetic-default.json` | Task 2.3 |
| `docs/simulator-model.md` | Task 2.3 |
| `tests/test_simulator_profiles.py` | Task 2.3 |
| `scripts/fit_simulator_plant.py` | Task 2.4 |
| `tests/test_simulator_fitting.py` | Task 2.4 |
| `docs/simulator-calibration-protocol.md` | Task 2.4 |
