"""Plant configuration dataclass with explicit units."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PlantConfig:
    """Configuration for two-node thermal plant simulator.

    All parameters include explicit units in their names or docstrings.

    Attributes:
        surface_capacity_j_per_k: Thermal capacity of IR sensor surface (J/K).
        bulk_capacity_j_per_k: Thermal capacity of sample/bulk material (J/K).
        surface_bulk_conductance_w_per_k: Conductance between surface and bulk (W/K).
        surface_ambient_conductance_w_per_k: Surface heat loss to ambient (W/K).
        bulk_ambient_conductance_w_per_k: Bulk heat loss to ambient (W/K).
        lamp_max_power_w: Maximum lamp electrical power at PWM=255 (W).
        lamp_response_time_s: Lamp first-order lag time constant (s).
        lamp_max_lux: Maximum optical output at max electrical power (lux).
        fan_max_conductance_w_per_k: Additional conductance from fan at PWM=255 (W/K).
        fan_response_time_s: Fan first-order lag time constant (s).
        ambient_temp_c: Default ambient temperature (°C).
        max_substep_s: Maximum integration substep size (s), defaults to 0.1s.
    """

    # Thermal capacities (J/K = Joules per Kelvin)
    surface_capacity_j_per_k: float
    bulk_capacity_j_per_k: float

    # Thermal conductances (W/K = Watts per Kelvin)
    surface_bulk_conductance_w_per_k: float
    surface_ambient_conductance_w_per_k: float
    bulk_ambient_conductance_w_per_k: float

    # Lamp model
    lamp_max_power_w: float  # W at PWM=255
    lamp_response_time_s: float  # seconds, first-order lag
    lamp_max_lux: float  # lux at max optical output

    # Fan model
    fan_max_conductance_w_per_k: float  # W/K additional at PWM=255
    fan_response_time_s: float  # seconds, first-order lag

    # Ambient
    ambient_temp_c: float  # °C, can be overridden per-run

    # Integration
    max_substep_s: float = 0.1  # seconds, internal substep limit


@dataclass
class SensorConfig:
    """Sensor model configuration with all parameters having explicit units.
    
    IR sensor (surface temperature)
        ir_response_time_s: First-order response time constant (s)
        ir_scale_factor: Conversion from surface temp to raw reading (°C/°C)
        ir_bias_c: Zero-load offset (°C)
        ir_drift_rate_per_s: Temperature drift rate (°C/s)
        ir_noise_std: Gaussian noise standard deviation (°C)
        ir_quantization_step: ADC quantization step (°C)
        ir_saturation_high_c: Upper saturation limit (°C)
        ir_saturation_low_c: Lower saturation limit (°C)
    
    Thermocouple sensor (bulk temperature)
        tc_response_time_s: First-order response time constant (s)
        tc_scale_factor: Conversion from bulk temp to raw reading (°C/°C)
        tc_bias_c: Zero-load offset (°C)
        tc_drift_rate_per_s: Temperature drift rate (°C/s)
        tc_noise_std: Gaussian noise standard deviation (°C)
        tc_quantization_step: ADC quantization step (°C)
        tc_saturation_high_c: Upper saturation limit (°C)
        tc_saturation_low_c: Lower saturation limit (°C)
    
    Lux sensor (optical output)
        lux_response_time_s: First-order response time constant (s)
        lux_scale_factor: Conversion from lamp output to raw reading (lux/lux)
        lux_bias_lux: Zero-load offset (lux)
        lux_drift_rate_per_s: Lux drift rate (lux/s)
        lux_noise_std: Gaussian noise standard deviation (lux)
        lux_quantization_step: ADC quantization step (lux)
        lux_saturation_high_lux: Upper saturation limit (lux)
        lux_saturation_low_lux: Lower saturation limit (lux)
    """
    # IR sensor parameters
    ir_response_time_s: float = 0.05       # s, first-order lag
    ir_scale_factor: float = 1.0           # °C / °C (dimensionless)
    ir_bias_c: float = 0.0                 # °C
    ir_drift_rate_per_s: float = 1e-6      # °C/s
    ir_noise_std: float = 0.1              # °C
    ir_quantization_step: float = 0.05     # °C
    ir_saturation_high_c: float = 150.0    # °C
    ir_saturation_low_c: float = -40.0     # °C
    
    # TC sensor parameters
    tc_response_time_s: float = 0.1        # s, first-order lag
    tc_scale_factor: float = 1.0           # °C / °C (dimensionless)
    tc_bias_c: float = 0.0                 # °C
    tc_drift_rate_per_s: float = 1e-6      # °C/s
    tc_noise_std: float = 0.15             # °C
    tc_quantization_step: float = 0.1      # °C
    tc_saturation_high_c: float = 200.0    # °C
    tc_saturation_low_c: float = -50.0     # °C
    
    # Lux sensor parameters
    lux_response_time_s: float = 0.02      # s, first-order lag
    lux_scale_factor: float = 1.0          # lux / lux (dimensionless)
    lux_bias_lux: float = 0.0              # lux
    lux_drift_rate_per_s: float = 1e-4     # lux/s
    lux_noise_std: float = 2.0             # lux
    lux_quantization_step: float = 1.0     # lux
    lux_saturation_high_lux: float = 20000.0   # lux
    lux_saturation_low_lux: float = 0.0      # lux
    
    # Invalidity probability per sample
    random_invalid_probability: float = 0.001


__all__ = ["PlantConfig", "SensorConfig"]
