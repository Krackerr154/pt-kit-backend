"""Sensor model for simulating raw sensor measurements.

This module implements realistic sensor behavior including:
- First-order response lag to true physical values
- Additive bias and drift over time
- Bounded Gaussian noise
- Quantization effects
- Saturation limits
- Random invalid readings
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import final

from .config import SensorConfig
from .random_streams import RNGStreams


@dataclass
class SensorReading:
    """Raw sensor measurement with validity flags.
    
    Attributes:
        ir_temp_c: IR sensor reading in degrees Celsius
        ir_valid: True if IR reading is valid (not saturated or faulted)
        tc_temp_c: Thermocouple reading in degrees Celsius
        tc_valid: True if TC reading is valid
        lux: Lux sensor reading in lux
        lux_valid: True if lux reading is valid
    """
    ir_temp_c: float
    ir_valid: bool
    tc_temp_c: float
    tc_valid: bool
    lux: float
    lux_valid: bool


@final
class SensorModel:
    """Physical sensor model with realistic imperfections.
    
    Models three sensor types:
    - IR sensor: measures surface temperature (fast thermal response)
    - TC sensor: measures bulk/sample temperature (slower response)
    - Lux sensor: measures optical output from lamp
    
    Each sensor exhibits:
    - First-order lag to true value
    - Constant bias
    - Linear drift over time
    - Bounded Gaussian noise
    - Quantization effects
    - Saturation at limits
    - Random invalidity
    
    Args:
        config: Sensor configuration with all model parameters
        rng_streams: Independent RNG streams for each sensor and fault type
    
    Example:
        >>> config = SensorConfig()
        >>> rng = RNGStreams(42)
        >>> sensor = SensorModel(config, rng)
        >>> state = plant_state  # PlantState from plant.py
        >>> reading = sensor.sample(state, dt_s=0.1)
        >>> print(f"IR: {reading.ir_temp_c:.2f}°C (valid={reading.ir_valid})")
    """
    
    def __init__(self, config: SensorConfig, rng_streams: RNGStreams):
        """Initialize sensor model with configuration and RNG streams.
        
        Args:
            config: Sensor model parameters with explicit units
            rng_streams: Independent RNG instances for reproducibility
        """
        self._config = config
        self._rng = rng_streams
        
        # State variables for first-order lag filtering (one per sensor type)
        self._ir_lagged_value: float = 25.0
        self._tc_lagged_value: float = 25.0
        self._lux_lagged_value: float = 0.0
        
        # Accumulated time for drift calculation
        self._elapsed_time_s: float = 0.0
        
        # Track last sample to ensure monotonic time progression
        self._last_sample_time_s: float = 0.0
    
    def _apply_lag(
        self, 
        current_value: float, 
        lag_buffer: float, 
        dt_s: float, 
        time_constant_s: float,
    ) -> tuple[float, float]:
        """Apply first-order lag filter (exponential moving average).
        
        This models the thermal/electronic response time of sensors.
        
        Args:
            current_value: Target value the sensor is trying to measure
            lag_buffer: Current buffer value (y[t-1])
            dt_s: Time since last sample (seconds)
            time_constant_s: Sensor response time constant (τ)
        
        Returns:
            Tuple of (new_lag_buffer, filtered_output)
        """
        if dt_s <= 0:
            return lag_buffer, lag_buffer
        
        alpha = dt_s / (time_constant_s + dt_s * 1e-12)  # Prevent div by zero
        alpha = min(alpha, 1.0)  # Clamp to [0, 1]
        
        # Exponential smoothing: y[t] = y[t-1] + α * (x[t] - y[t-1])
        new_buffer = lag_buffer + alpha * (current_value - lag_buffer)
        
        return new_buffer, new_buffer
    
    def _quantize(self, value: float, step: float) -> float:
        """Apply quantization to simulate ADC effects.
        
        Args:
            value: Continuous value to quantize
            step: Quantization step size
        
        Returns:
            Value rounded to nearest quantization level
        """
        return round(value / step) * step
    
    def _clamp(self, value: float, low: float, high: float) -> float:
        """Clamp value to specified range.
        
        Args:
            value: Value to clamp
            low: Lower bound (inclusive)
            high: Upper bound (inclusive)
        
        Returns:
            Clamped value within [low, high]
        """
        return max(low, min(high, value))
    
    def _apply_noise(
        self,
        base_value: float,
        std_dev: float,
        rng: random.Random,
        limit_factor: float = 3.0,
    ) -> float:
        """Add bounded Gaussian noise to a value.
        
        Args:
            base_value: Clean value to add noise to
            std_dev: Standard deviation of Gaussian noise
            rng: Python random.Random instance
            limit_factor: Maximum noise in sigma units (default ±3σ)
        
        Returns:
            Noisy value, bounded within ±limit_factor*std_dev from base
        """
        noise = rng.gauss(0, std_dev)
        # Clamp noise to prevent extreme outliers
        noise = max(-limit_factor * std_dev, min(limit_factor * std_dev, noise))
        return base_value + noise
    
    def _is_reading_invalid(self, rng: random.Random, prob: float) -> bool:
        """Determine if this reading should be marked invalid.
        
        Simulates random sensor faults, communication errors, etc.
        
        Args:
            rng: Random generator
            prob: Probability of invalidity (0.0 to 1.0)
        
        Returns:
            True if reading should be marked invalid
        """
        return rng.random() < prob
    
    @property
    def ir_lagged_value(self) -> float:
        """Get IR sensor's current filtered value."""
        return self._ir_lagged_value
    
    @property
    def tc_lagged_value(self) -> float:
        """Get TC sensor's current filtered value."""
        return self._tc_lagged_value
    
    @property
    def lux_lagged_value(self) -> float:
        """Get lux sensor's current filtered value."""
        return self._lux_lagged_value
    
    def reset(self, initial_time_s: float = 0.0) -> None:
        """Reset sensor model to initial state.
        
        Clears all accumulated state and returns sensors to initial conditions.
        Should be called before each simulation run.
        
        Args:
            initial_time_s: Initial timestamp for drift calculations
        """
        # Reset lag filters to neutral starting point
        self._ir_lagged_value = 25.0  # °C, room temp
        self._tc_lagged_value = 25.0  # °C, room temp
        self._lux_lagged_value = 0.0   # lux, lamp off
        
        # Reset time tracking
        self._elapsed_time_s = 0.0
        self._last_sample_time_s = initial_time_s
    
    def sample(self, plant_state, dt_s: float) -> SensorReading:
        """Sample all sensors given current plant state.
        
        This method performs the complete sensor measurement pipeline:
        1. Update elapsed time and advance lag filters
        2. Read true physical values from plant state
        3. Apply first-order lag dynamics
        4. Add bias, drift, and bounded noise
        5. Apply quantization
        6. Apply saturation/clamping
        7. Check for random invalidity
        8. Return reading with validity flags
        
        Args:
            plant_state: Current state from ThermalPlant.step()
                        Must have attributes:
                        - surface_temp_c: float
                        - bulk_temp_c: float
                        - lamp_output_lux: float
                        - time_s: float
            dt_s: Time since last sample (seconds)
        
        Returns:
            SensorReading with all six fields populated
        
        Raises:
            ValueError: If dt_s is negative
            AttributeError: If plant_state lacks required attributes
        """
        if dt_s < 0:
            raise ValueError(f"dt_s must be non-negative, got {dt_s}")
        
        # Update elapsed time for drift
        current_time_s = plant_state.time_s
        dt_since_last = current_time_s - self._last_sample_time_s
        self._elapsed_time_s += dt_since_last
        self._last_sample_time_s = current_time_s
        
        # === IR SENSOR (surface temperature) ===
        # 1. Apply lag to surface temperature
        ir_true = plant_state.surface_temp_c
        ir_lag_stream = self._rng.ir_noise
        self._ir_lagged_value, ir_lagged = self._apply_lag(
            ir_true,
            self._ir_lagged_value,
            dt_s,
            self._config.ir_response_time_s
        )
        
        # 2. Add bias and drift
        ir_bias_drifted = ir_lagged + self._config.ir_bias_c
        ir_drifted = ir_bias_drifted + self._config.ir_drift_rate_per_s * self._elapsed_time_s
        
        # 3. Add bounded noise
        ir_noisy = self._apply_noise(
            ir_drifted,
            self._config.ir_noise_std,
            ir_lag_stream,
        )
        
        # 4. Quantize
        ir_quantized = self._quantize(ir_noisy, self._config.ir_quantization_step)
        
        # 5. Clamp to saturation limits
        ir_final = self._clamp(ir_quantized, self._config.ir_saturation_low_c, self._config.ir_saturation_high_c)
        
        # 6. Determine validity (check for saturation-induced invalidity)
        # Treat readings near saturation limits as potentially unreliable
        ir_near_saturation = (
            abs(ir_final - self._config.ir_saturation_low_c) < self._config.ir_noise_std * 2 or
            abs(ir_final - self._config.ir_saturation_high_c) < self._config.ir_noise_std * 2
        )
        ir_random_invalid = self._is_reading_invalid(ir_lag_stream, self._config.random_invalid_probability)
        ir_valid = not (ir_near_saturation or ir_random_invalid)
        
        # === TC SENSOR (bulk temperature) ===
        # Repeat same pipeline for thermocouple
        tc_true = plant_state.bulk_temp_c
        tc_lag_stream = self._rng.tc_noise
        self._tc_lagged_value, tc_lagged = self._apply_lag(
            tc_true,
            self._tc_lagged_value,
            dt_s,
            self._config.tc_response_time_s,
        )
        
        tc_bias_drifted = tc_lagged + self._config.tc_bias_c
        tc_drifted = tc_bias_drifted + self._config.tc_drift_rate_per_s * self._elapsed_time_s
        tc_noisy = self._apply_noise(
            tc_drifted,
            self._config.tc_noise_std,
            tc_lag_stream,
        )
        tc_quantized = self._quantize(tc_noisy, self._config.tc_quantization_step)
        tc_final = self._clamp(tc_quantized, self._config.tc_saturation_low_c, self._config.tc_saturation_high_c)
        
        tc_near_saturation = (
            abs(tc_final - self._config.tc_saturation_low_c) < self._config.tc_noise_std * 2 or
            abs(tc_final - self._config.tc_saturation_high_c) < self._config.tc_noise_std * 2
        )
        tc_random_invalid = self._is_reading_invalid(tc_lag_stream, self._config.random_invalid_probability)
        tc_valid = not (tc_near_saturation or tc_random_invalid)
        
        # === LUX SENSOR (optical output) ===
        # Repeat same pipeline for lux sensor
        lux_true = plant_state.lamp_output_lux
        lux_lag_stream = self._rng.lux_noise
        self._lux_lagged_value, lux_lagged = self._apply_lag(
            lux_true,
            self._lux_lagged_value,
            dt_s,
            self._config.lux_response_time_s,
        )
        
        lux_bias_drifted = lux_lagged + self._config.lux_bias_lux
        lux_drifted = lux_bias_drifted + self._config.lux_drift_rate_per_s * self._elapsed_time_s
        lux_noisy = self._apply_noise(
            lux_drifted,
            self._config.lux_noise_std,
            lux_lag_stream,
        )
        lux_quantized = self._quantize(lux_noisy, self._config.lux_quantization_step)
        lux_final = self._clamp(lux_quantized, self._config.lux_saturation_low_lux, self._config.lux_saturation_high_lux)
        
        lux_near_saturation = (
            abs(lux_final - self._config.lux_saturation_low_lux) < self._config.lux_noise_std * 2 or
            abs(lux_final - self._config.lux_saturation_high_lux) < self._config.lux_noise_std * 2
        )
        lux_random_invalid = self._is_reading_invalid(lux_lag_stream, self._config.random_invalid_probability)
        lux_valid = not (lux_near_saturation or lux_random_invalid)
        
        return SensorReading(
            ir_temp_c=ir_final,
            ir_valid=ir_valid,
            tc_temp_c=tc_final,
            tc_valid=tc_valid,
            lux=lux_final,
            lux_valid=lux_valid,
        )


# Convenience function for quick sensor creation
def make_sensor(config: SensorConfig | None = None, seed: int = 42) -> SensorModel:
    """Create a SensorModel with given config and seed.
    
    Args:
        config: SensorConfig instance, or None for defaults
        seed: RNG seed for reproducibility
    
    Returns:
        Configured SensorModel ready for use
    
    Example:
        >>> sensor = make_sensor(seed=123)
        >>> reading = sensor.sample(plant.state, 0.1)
    """
    if config is None:
        config = SensorConfig()
    rng = RNGStreams(seed)
    return SensorModel(config, rng)


__all__ = ["SensorReading", "SensorModel", "make_sensor"]
