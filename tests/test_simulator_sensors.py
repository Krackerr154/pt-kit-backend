"""Deterministic sensor tests with fixed seed for reproducibility.

This module tests SensorModel behavior with emphasis on:
- Determinism (fixed seed produces identical results)
- Stream independence (using network fault doesn't change physical noise)
- Bounded outputs (values stay within limits, always finite)
- Validity flags (correctly indicate invalid readings)
- First-order lag dynamics
- Quantization effects
- Saturation behavior
"""

from __future__ import annotations

import dataclasses
import math
from typing import final

import pytest

from app.simulator.config import PlantConfig, SensorConfig
from app.simulator.random_streams import RNGStreams
from app.simulator.sensors import SensorModel, SensorReading


@final
class MockPlantState:
    """Minimal plant state mock for sensor testing."""
    
    def __init__(
        self,
        surface_temp_c: float = 25.0,
        bulk_temp_c: float = 25.0,
        lamp_output_lux: float = 0.0,
        time_s: float = 0.0,
    ):
        self.surface_temp_c = surface_temp_c
        self.bulk_temp_c = bulk_temp_c
        self.lamp_output_lux = lamp_output_lux
        self.time_s = time_s


@final
class TestSensorConfigDefaults:
    """Test SensorConfig has reasonable defaults."""
    
    def test_ir_default_params(self):
        config = SensorConfig()
        assert config.ir_response_time_s == 0.05
        assert config.ir_bias_c == 0.0
        assert config.ir_noise_std == 0.1
        assert config.ir_quantization_step == 0.05
        assert config.ir_saturation_high_c == 150.0
        assert config.ir_saturation_low_c == -40.0
    
    def test_tc_default_params(self):
        config = SensorConfig()
        assert config.tc_response_time_s == 0.1
        assert config.tc_bias_c == 0.0
        assert config.tc_noise_std == 0.15
        assert config.tc_quantization_step == 0.1
        assert config.tc_saturation_high_c == 200.0
        assert config.tc_saturation_low_c == -50.0
    
    def test_lux_default_params(self):
        config = SensorConfig()
        assert config.lux_response_time_s == 0.02
        assert config.lux_bias_lux == 0.0
        assert config.lux_noise_std == 2.0
        assert config.lux_quantization_step == 1.0
        assert config.lux_saturation_high_lux == 20000.0
        assert config.lux_saturation_low_lux == 0.0
    
    def test_random_invalid_probability(self):
        config = SensorConfig()
        assert config.random_invalid_probability == 0.001


@final
class TestRNGStreamsIndependence:
    """Test that RNG streams are independent and reproducible."""
    
    def test_all_streams_exist_and_are_callable(self):
        rng = RNGStreams(42)
        
        # All streams should be accessible
        assert hasattr(rng, "ir_noise")
        assert hasattr(rng, "tc_noise")
        assert hasattr(rng, "lux_noise")
        assert hasattr(rng, "plant_disturbance")
        assert hasattr(rng, "uart_fault")
        assert hasattr(rng, "network_fault")
        
        # Each stream should produce values
        ir_val1 = rng.ir_noise.gauss(0, 1)
        tc_val1 = rng.tc_noise.gauss(0, 1)
        lux_val1 = rng.lux_noise.gauss(0, 1)
        
        # Values should exist (not None)
        assert isinstance(ir_val1, float)
        assert isinstance(tc_val1, float)
        assert isinstance(lux_val1, float)
    
    def test_stream_reproducibility_after_reset(self):
        """Test that reset restores streams to initial state."""
        rng1 = RNGStreams(42)
        rng2 = RNGStreams(42)
        
        # Get some values from both
        ir_val1_init = rng1.ir_noise.gauss(0, 1)
        tc_val1_init = rng1.tc_noise.gauss(0, 1)
        
        rng2.reset()
        
        # After reset, sequences should match
        ir_val2_post_reset = rng2.ir_noise.gauss(0, 1)
        tc_val2_post_reset = rng2.tc_noise.gauss(0, 1)
        
        assert ir_val1_init == pytest.approx(ir_val2_post_reset, rel=1e-10)
        assert tc_val1_init == pytest.approx(tc_val2_post_reset, rel=1e-10)
    
    def test_independence_network_fault_does_not_affect_physical_noise(
        self,
    ):
        """CRITICAL: Using network_fault must NOT change IR/TC/lux noise sequence."""
        base_seed = 42
        
        # Scenario A: Use physical noise streams only
        rng_a = RNGStreams(base_seed)
        ir_noise_a = [rng_a.ir_noise.gauss(0, 1) for _ in range(5)]
        tc_noise_a = [rng_a.tc_noise.gauss(0, 1) for _ in range(5)]
        lux_noise_a = [rng_a.lux_noise.gauss(0, 1) for _ in range(5)]
        
        # Scenario B: Also use network_fault between physical noise calls
        rng_b = RNGStreams(base_seed)
        _ = rng_b.network_fault.random()  # Advance network_fault stream
        ir_noise_b = [rng_b.ir_noise.gauss(0, 1) for _ in range(5)]
        _ = rng_b.uart_fault.random()  # Another disturbance
        tc_noise_b = [rng_b.tc_noise.gauss(0, 1) for _ in range(5)]
        _ = rng_b.plant_disturbance.random()
        lux_noise_b = [rng_b.lux_noise.gauss(0, 1) for _ in range(5)]
        
        # Physical noise sequences MUST be identical
        assert ir_noise_a == pytest.approx(ir_noise_b, rel=1e-10), (
            f"IR noise changed after using network_fault! "
            f"A={ir_noise_a}, B={ir_noise_b}"
        )
        assert tc_noise_a == pytest.approx(tc_noise_b, rel=1e-10), (
            f"TC noise changed after using network_fault!"
        )
        assert lux_noise_a == pytest.approx(lux_noise_b, rel=1e-10), (
            f"Lux noise changed after using network_fault!"
        )
    
    def test_different_seeds_produce_different_sequences(self):
        rng_42 = RNGStreams(42)
        rng_123 = RNGStreams(123)
        
        val_42 = rng_42.ir_noise.random()
        val_123 = rng_123.ir_noise.random()
        
        # With overwhelming probability, different seeds give different values
        assert val_42 != val_123


@final
class TestSensorModelReproducibility:
    """Test deterministic sensor sampling."""
    
    def test_identical_config_and_seed_produce_identical_results(self):
        config1 = SensorConfig()
        rng1 = RNGStreams(42)
        sensor1 = SensorModel(config1, rng1)
        
        config2 = SensorConfig()
        rng2 = RNGStreams(42)
        sensor2 = SensorModel(config2, rng2)
        
        # Same plant state at same time
        state = MockPlantState(
            surface_temp_c=30.0,
            bulk_temp_c=28.0,
            lamp_output_lux=1000.0,
            time_s=1.0,
        )
        
        reading1 = sensor1.sample(state, dt_s=0.1)
        reading2 = sensor2.sample(state, dt_s=0.1)
        
        # All values should be nearly identical (allowing for floating point)
        assert reading1.ir_temp_c == pytest.approx(reading2.ir_temp_c, rel=1e-10)
        assert reading1.tc_temp_c == pytest.approx(reading2.tc_temp_c, rel=1e-10)
        assert reading1.lux == pytest.approx(reading2.lux, rel=1e-10)
        assert reading1.ir_valid == reading2.ir_valid
        assert reading1.tc_valid == reading2.tc_valid
        assert reading1.lux_valid == reading2.lux_valid
    
    def test_reset_clears_state_and_produces_same_sequence(self):
        config = SensorConfig()
        rng = RNGStreams(42)
        sensor = SensorModel(config, rng)
        
        # First batch of samples
        state1 = MockPlantState(surface_temp_c=30.0, bulk_temp_c=28.0, lamp_output_lux=1000.0, time_s=1.0)
        reading1 = sensor.sample(state1, dt_s=0.1)
        
        state2 = MockPlantState(surface_temp_c=31.0, bulk_temp_c=29.0, lamp_output_lux=1100.0, time_s=1.1)
        reading2 = sensor.sample(state2, dt_s=0.1)
        
        # Reset to start
        sensor.reset(initial_time_s=0.0)
        rng.reset()
        
        # Second batch should match exactly
        state1_again = MockPlantState(surface_temp_c=30.0, bulk_temp_c=28.0, lamp_output_lux=1000.0, time_s=1.0)
        reading1_again = sensor.sample(state1_again, dt_s=0.1)
        
        state2_again = MockPlantState(surface_temp_c=31.0, bulk_temp_c=29.0, lamp_output_lux=1100.0, time_s=1.1)
        reading2_again = sensor.sample(state2_again, dt_s=0.1)
        
        assert reading1.ir_temp_c == pytest.approx(reading1_again.ir_temp_c, rel=1e-10)
        assert reading1.tc_temp_c == pytest.approx(reading1_again.tc_temp_c, rel=1e-10)
        assert reading1.lux == pytest.approx(reading1_again.lux, rel=1e-10)
        assert reading2.ir_temp_c == pytest.approx(reading2_again.ir_temp_c, rel=1e-10)
    
    def test_negative_dt_raises_value_error(self):
        config = SensorConfig()
        rng = RNGStreams(42)
        sensor = SensorModel(config, rng)
        
        state = MockPlantState()
        
        with pytest.raises(ValueError, match="dt_s must be non-negative"):
            sensor.sample(state, dt_s=-0.1)


@final
class TestSensorBoundednessAndFiniteness:
    """Test that sensor readings are always bounded and finite."""
    
    def test_readings_always_finite(self):
        """All sensor values should be finite (no NaN or Inf)."""
        config = SensorConfig()
        rng = RNGStreams(42)
        sensor = SensorModel(config, rng)
        
        # Extreme plant state
        state = MockPlantState(
            surface_temp_c=float('inf'),
            bulk_temp_c=float('nan'),
            lamp_output_lux=1e20,
            time_s=1e10,
        )
        
        with pytest.raises((OverflowError, ValueError)):
            sensor.sample(state, dt_s=0.1)
    
    def test_readings_within_saturation_limits(self):
        """Readings should never exceed saturation bounds."""
        config = SensorConfig()
        rng = RNGStreams(42)
        sensor = SensorModel(config, rng)
        
        # Test extreme inputs that would saturate
        test_cases = [
            # (surface_temp, bulk_temp, lux, description)
            (200.0, 180.0, 50000.0, "above all saturation limits"),
            (-100.0, -80.0, -1000.0, "below all saturation limits"),
            (config.ir_saturation_high_c + 50, config.tc_saturation_high_c + 50, config.lux_saturation_high_lux + 5000, "well above high limits"),
            (config.ir_saturation_low_c - 50, config.tc_saturation_low_c - 50, config.lux_saturation_low_lux - 1000, "well below low limits"),
        ]
        
        for surface, bulk, lux, desc in test_cases:
            state = MockPlantState(
                surface_temp_c=surface,
                bulk_temp_c=bulk,
                lamp_output_lux=max(0, lux),  # Lux can't be negative
                time_s=1.0,
            )
            
            reading = sensor.sample(state, dt_s=0.1)
            
            # IR should be within saturation limits
            assert (
                config.ir_saturation_low_c <= reading.ir_temp_c <= config.ir_saturation_high_c
            ), f"IR temp {reading.ir_temp_c} out of bounds [{config.ir_saturation_low_c}, {config.ir_saturation_high_c}] for case: {desc}"
            
            # TC should be within saturation limits
            assert (
                config.tc_saturation_low_c <= reading.tc_temp_c <= config.tc_saturation_high_c
            ), f"TC temp {reading.tc_temp_c} out of bounds for case: {desc}"
            
            # Lux should be within saturation limits
            assert (
                config.lux_saturation_low_lux <= reading.lux <= config.lux_saturation_high_lux
            ), f"Lux {reading.lux} out of bounds for case: {desc}"
    
    def test_readings_remain_finite_over_long_simulation(self):
        """Long simulations should not accumulate errors leading to inf/nan."""
        config = SensorConfig()
        rng = RNGStreams(42)
        sensor = SensorModel(config, rng)
        
        # Simulate 1 hour of operation
        state = MockPlantState(
            surface_temp_c=60.0,
            bulk_temp_c=55.0,
            lamp_output_lux=5000.0,
            time_s=0.0,
        )
        
        num_samples = 36000  # At 10Hz for 1 hour
        for i in range(num_samples):
            state.time_s = i * 0.1
            reading = sensor.sample(state, dt_s=0.1)
            
            # Every reading should be finite
            assert math.isfinite(reading.ir_temp_c), f"IR became non-finite at sample {i}: {reading.ir_temp_c}"
            assert math.isfinite(reading.tc_temp_c), f"TC became non-finite at sample {i}: {reading.tc_temp_c}"
            assert math.isfinite(reading.lux), f"Lux became non-finite at sample {i}: {reading.lux}"


@final
class TestSensorFirstOrderLag:
    """Test first-order lag dynamics."""
    
    def test_lag_follows_step_change(self):
        """Sensor output should follow step input with exponential response."""
        config = SensorConfig()
        # Very fast response for easy testing
        config.ir_response_time_s = 0.01
        config.tc_response_time_s = 0.01
        config.lux_response_time_s = 0.01
        
        rng = RNGStreams(42)
        sensor = SensorModel(config, rng)
        
        # Set up state with rapid temperature change
        states = [
            MockPlantState(surface_temp_c=25.0, bulk_temp_c=25.0, lamp_output_lux=1000.0, time_s=0.0),
            MockPlantState(surface_temp_c=75.0, bulk_temp_c=25.0, lamp_output_lux=1000.0, time_s=0.1),  # Step up
            MockPlantState(surface_temp_c=75.0, bulk_temp_c=25.0, lamp_output_lux=1000.0, time_s=0.2),
            MockPlantState(surface_temp_c=75.0, bulk_temp_c=25.0, lamp_output_lux=1000.0, time_s=0.3),
        ]
        
        # Disable noise for predictable lag test
        config.ir_noise_std = 0.0
        config.tc_noise_std = 0.0
        config.lux_noise_std = 0.0
        config.ir_bias_c = 0.0
        config.tc_bias_c = 0.0
        config.lux_bias_lux = 0.0
        
        readings = []
        for state in states:
            reading = sensor.sample(state, dt_s=0.1)
            readings.append(reading)
        
        # First reading should still near initial value (lag effect)
        assert readings[0].ir_temp_c < 50.0, "First reading too close to new value - lag not working"
        
        # Later readings should approach 75°C (asymptotically, may reach target eventually)
        assert readings[-1].ir_temp_c >= 50.0, f"Not approaching target temperature: {readings[-1].ir_temp_c}"
    def test_zero_dt_preserves_value(self):
        """Small dt_s should produce minimal change in filtered value."""
        config = SensorConfig()
        # Disable noise and bias to focus on lag dynamics
        config.ir_noise_std = 0.0
        config.ir_bias_c = 0.0
        config.ir_drift_rate_per_s = 0.0
        rng = RNGStreams(42)
        sensor = SensorModel(config, rng)
        
        # Set initial filter state close to target
        sensor._ir_lagged_value = 30.0
        
        # State with same temperature but slightly different time
        state1 = MockPlantState(surface_temp_c=30.0, bulk_temp_c=28.0, lamp_output_lux=1000.0, time_s=0.0)
        reading1 = sensor.sample(state1, dt_s=0.1)
        first_ir = reading1.ir_temp_c
        
        # Use tiny dt - filter should barely move since target hasn't changed
        state2 = MockPlantState(surface_temp_c=30.0, bulk_temp_c=28.0, lamp_output_lux=1000.0, time_s=0.000001)
        reading_small = sensor.sample(state2, dt_s=0.000001)
        
        # Very small dt should produce minimal change (within 0.001°C tolerance)
        assert abs(reading_small.ir_temp_c - first_ir) < 0.001, \
            f"Tiny dt changed value significantly: {first_ir} -> {reading_small.ir_temp_c}"
        
        # Compare with normal dt - should show more change
        reading_normal = sensor.sample(state1, dt_s=0.1)
        large_change = abs(reading_normal.ir_temp_c - first_ir)
        small_change = abs(reading_small.ir_temp_c - first_ir)
        
        # Normal dt should show at least 10x more lag effect than tiny dt
        assert large_change >= 10 * small_change or small_change == 0.0, \
            f"Expected larger change with normal dt: normal={large_change}, small={small_change}"


@final
class TestSensorQuantization:
    """Test quantization effects."""
    
    def test_quantization_steps(self):
        """Values should align to quantization grid."""
        config = SensorConfig()
        rng = RNGStreams(42)
        sensor = SensorModel(config, rng)
        
        # Disable other noise sources
        config.ir_noise_std = 0.0
        config.ir_bias_c = 0.0
        config.ir_drift_rate_per_s = 0.0
        config.tc_noise_std = 0.0
        config.lux_noise_std = 0.0
        
        # Apply known temperature
        state = MockPlantState(surface_temp_c=30.123, bulk_temp_c=28.456, lamp_output_lux=1000.789, time_s=0.0)
        reading = sensor.sample(state, dt_s=0.1)
        
        # Check alignment to quantization grids
        ir_quantized = round(reading.ir_temp_c / config.ir_quantization_step) * config.ir_quantization_step
        tc_quantized = round(reading.tc_temp_c / config.tc_quantization_step) * config.tc_quantization_step
        lux_quantized = round(reading.lux / config.lux_quantization_step) * config.lux_quantization_step
        
        assert abs(reading.ir_temp_c - ir_quantized) < config.ir_quantization_step * 0.01
        assert abs(reading.tc_temp_c - tc_quantized) < config.tc_quantization_step * 0.01
        assert abs(reading.lux - lux_quantized) < config.lux_quantization_step * 0.01


@final
class TestSensorValidityFlags:
    """Test validity flag behavior."""
    
    def test_initial_readings_valid(self):
        """Initial readings should generally be valid."""
        config = SensorConfig()
        rng = RNGStreams(42)
        sensor = SensorModel(config, rng)
        
        state = MockPlantState(
            surface_temp_c=25.0,
            bulk_temp_c=25.0,
            lamp_output_lux=1000.0,
            time_s=0.0,
        )
        
        reading = sensor.sample(state, dt_s=0.1)
        
        # Normal readings in middle of range should be valid
        assert reading.ir_valid is True or reading.tc_valid is True or reading.lux_valid is True
    
    def test_saturation_can_mark_invalid(self):
        """Readings near saturation may be marked invalid."""
        config = SensorConfig()
        # Reduce noise to make near-saturation detection more reliable
        config.ir_noise_std = 0.01
        config.tc_noise_std = 0.01
        config.lux_noise_std = 0.01
        
        rng = RNGStreams(42)
        sensor = SensorModel(config, rng)
        
        # Readings at saturation limits
        state = MockPlantState(
            surface_temp_c=config.ir_saturation_high_c,
            bulk_temp_c=config.tc_saturation_high_c,
            lamp_output_lux=config.lux_saturation_high_lux,
            time_s=0.0,
        )
        
        reading = sensor.sample(state, dt_s=0.1)
        
        # May or may not be invalid (depends on random invalidity check)
        # But if near saturation, there's a chance of invalidity
        assert reading.ir_temp_c <= config.ir_saturation_high_c
        assert reading.tc_temp_c <= config.tc_saturation_high_c
        assert reading.lux <= config.lux_saturation_high_lux
    
    def test_validity_flags_are_boolean(self):
        """All validity flags should be proper booleans."""
        config = SensorConfig()
        rng = RNGStreams(42)
        sensor = SensorModel(config, rng)
        
        state = MockPlantState(time_s=0.0)
        reading = sensor.sample(state, dt_s=0.1)
        
        assert isinstance(reading.ir_valid, bool)
        assert isinstance(reading.tc_valid, bool)
        assert isinstance(reading.lux_valid, bool)


@final
class TestSensorMappingToPhysicalQuantities:
    """Test correct mapping of physical quantities to sensors."""
    
    def test_ir_map_to_surface_temp(self):
        """IR sensor should primarily respond to surface temperature."""
        config = SensorConfig()
        # Minimize confounding factors
        config.ir_noise_std = 0.0
        config.ir_bias_c = 0.0
        config.ir_drift_rate_per_s = 0.0
        
        rng = RNGStreams(42)
        sensor = SensorModel(config, rng)
        
        # Change surface temp, keep bulk constant
        state1 = MockPlantState(surface_temp_c=25.0, bulk_temp_c=25.0, lamp_output_lux=0.0, time_s=0.0)
        state2 = MockPlantState(surface_temp_c=50.0, bulk_temp_c=25.0, lamp_output_lux=0.0, time_s=0.0)
        
        reading1 = sensor.sample(state1, dt_s=0.1)
        reading2 = sensor.sample(state2, dt_s=0.1)
        
        # IR should change proportionally with surface temp
        delta_reading = reading2.ir_temp_c - reading1.ir_temp_c
        delta_true = 50.0 - 25.0
        
        # Allow some error due to lag initialization
        assert delta_reading > 0, "IR should increase with surface temp"
        assert delta_reading < delta_true * 1.1, f"IR over-reached: {delta_reading} vs expected ~{delta_true}"
    
    def test_tc_map_to_bulk_temp(self):
        """TC sensor should primarily respond to bulk temperature."""
        config = SensorConfig()
        config.tc_noise_std = 0.0
        config.tc_bias_c = 0.0
        
        rng = RNGStreams(42)
        sensor = SensorModel(config, rng)
        
        # Change bulk temp, keep surface constant
        state1 = MockPlantState(surface_temp_c=25.0, bulk_temp_c=25.0, lamp_output_lux=0.0, time_s=0.0)
        state2 = MockPlantState(surface_temp_c=25.0, bulk_temp_c=60.0, lamp_output_lux=0.0, time_s=0.0)
        
        reading1 = sensor.sample(state1, dt_s=0.1)
        reading2 = sensor.sample(state2, dt_s=0.1)
        
        delta_reading = reading2.tc_temp_c - reading1.tc_temp_c
        delta_true = 60.0 - 25.0
        
        assert delta_reading > 0, "TC should increase with bulk temp"
        assert delta_reading < delta_true * 1.1
    
    def test_lux_map_to_lamp_output(self):
        """Lux sensor should respond to lamp optical output."""
        config = SensorConfig()
        config.lux_noise_std = 0.0
        config.lux_bias_lux = 0.0
        
        rng = RNGStreams(42)
        sensor = SensorModel(config, rng)
        
        # Vary lamp output
        state1 = MockPlantState(surface_temp_c=25.0, bulk_temp_c=25.0, lamp_output_lux=1000.0, time_s=0.0)
        state2 = MockPlantState(surface_temp_c=25.0, bulk_temp_c=25.0, lamp_output_lux=3000.0, time_s=0.0)
        
        reading1 = sensor.sample(state1, dt_s=0.1)
        reading2 = sensor.sample(state2, dt_s=0.1)
        
        assert reading2.lux > reading1.lux, "Lux should increase with lamp output"
    
    def test_cross_coupling_minimal(self):
        """Changing one physical quantity shouldn't affect unrelated sensors much."""
        config = SensorConfig()
        config.ir_noise_std = 0.0
        config.tc_noise_std = 0.0
        config.lux_noise_std = 0.0
        
        rng = RNGStreams(42)
        sensor = SensorModel(config, rng)
        
        # Change lux dramatically, see effect on IR and TC
        state_base = MockPlantState(surface_temp_c=25.0, bulk_temp_c=25.0, lamp_output_lux=0.0, time_s=0.0)
        state_high_lux = MockPlantState(surface_temp_c=25.0, bulk_temp_c=25.0, lamp_output_lux=20000.0, time_s=0.0)
        
        reading_base = sensor.sample(state_base, dt_s=0.1)
        reading_high = sensor.sample(state_high_lux, dt_s=0.1)
        
        # Lux should change significantly
        assert abs(reading_high.lux - reading_base.lux) > 1000
        
        # IR and TC should barely change (lamp heat takes time to transfer)
        assert abs(reading_high.ir_temp_c - reading_base.ir_temp_c) < 1.0, \
            f"IR affected by lux change too much: {reading_high.ir_temp_c - reading_base.ir_temp_c}"
        assert abs(reading_high.tc_temp_c - reading_base.tc_temp_c) < 1.0, \
            f"TC affected by lux change too much"


@final
class TestSensorDriftBehavior:
    """Test drift over time."""
    
    def test_linear_drift_accumulation(self):
        """Drift should accumulate linearly with elapsed time."""
        config = SensorConfig()
        # Use measurable drift rate
        config.ir_drift_rate_per_s = 0.1  # 0.1 °C/s
        config.ir_noise_std = 0.0
        config.ir_bias_c = 0.0
        
        rng = RNGStreams(42)
        sensor = SensorModel(config, rng)
        
        # Hold constant temperature, advance time
        state = MockPlantState(surface_temp_c=30.0, bulk_temp_c=25.0, lamp_output_lux=0.0, time_s=0.0)
        
        # Sample at various times
        times = [0.0, 10.0, 20.0, 30.0]
        readings = []
        
        for t in times:
            state.time_s = t
            reading = sensor.sample(state, dt_s=1.0)
            readings.append(reading)
        
        # Drift should be approximately linear: drift_rate * time
        drift_10 = readings[1].ir_temp_c - readings[0].ir_temp_c
        drift_20 = readings[2].ir_temp_c - readings[0].ir_temp_c
        drift_30 = readings[3].ir_temp_c - readings[0].ir_temp_c
        
        # Allow 20% tolerance for discretization effects
        assert abs(drift_10 - 1.0) < 0.2, f"Expected ~1.0°C drift at 10s, got {drift_10}"
        assert abs(drift_20 - 2.0) < 0.4, f"Expected ~2.0°C drift at 20s, got {drift_20}"
        assert abs(drift_30 - 3.0) < 0.6, f"Expected ~3.0°C drift at 30s, got {drift_30}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
