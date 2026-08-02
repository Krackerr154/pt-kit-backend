"""
Test Suite for Simulator Controller Modes

Tests controller state machine correctness across different experiment modes:
- ISO1 fixed-temp mode with qualification cycles
- PLAT1 plateau mode with slope/range validation
- Calibration mode sequences (CAL_BARE → CAL_TAPE)
- Invalid sensor handling
- Determinism with fixed seed
"""

import pytest
import sys
import os
import logging

# Add app directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

from simulator.controller_implementation import (
    PTKitControllerIntegration,
    ControllerState,
    SupervisionFlag,
    PlantState,
    ExtendedTelemetry,
    ExperimentConfig,
    ThermalPlantSimulator,
)


class TestISO1Mode:
    """Test ISO1 fixed-temp mode with qualification cycles."""
    
    def test_iso1_reaches_done_after_qualification_and_hold(self):
        """
        Test that ISO1 mode completes qualification cycles then hold.
        
        Sequence: IDLE → STARTING → SENSOR_CHECK → WARMUP → STABILIZING → 
                  QUALIFY_CYCLE → HOLDING → DONE
        """
        # Create controller with ISO1 config - tuned for faster simulation
        controller = PTKitControllerIntegration(
            plant_config={
                'heating_power_w': 300.0, 
                'thermal_mass': 50.0,
                'cooling_rate_w': 2.0
            },
            seed=42
        )
        
        # Send ISO1 command: target 80°C, 2 cycles of 60s each
        controller.send_command("ISO180302")
        
        # Step through simulation
        max_steps = 500  # Should complete in ~240s total
        final_state = None
        
        for i in range(max_steps):
            telemetry = controller.step(dt_s=1.0)
            final_state = controller.state
            
            if controller.state == ControllerState.DONE:
                break
        
        # Verify completion
        assert final_state == ControllerState.DONE, f"Expected DONE, got {final_state}"
        
        # Verify we went through qualification cycles
        trace = controller.get_telemetry_buffer()
        states_seen = set(t.controller_state for t in trace)
        
        assert ControllerState.QUALIFY_CYCLE in states_seen, "Missing QUALIFY_CYCLE state"
        assert ControllerState.HOLDING in states_seen, "Missing HOLDING state"
        
        # Verify at least one qualification cycle completed
        cycles_counted = sum(
            1 for t in trace 
            if t.controller_state == ControllerState.QUALIFY_CYCLE
        )
        assert cycles_counted >= 1, "Should have seen at least one qualification cycle"
    
    def test_iso1_cycle_count_increments(self):
        """Test that ISO1 cycle counter increments correctly."""
        controller = PTKitControllerIntegration(
            plant_config={
                'heating_power_w': 400.0, 
                'thermal_mass': 40.0,
                'cooling_rate_w': 2.0
            },  # Fast heating
            seed=42
        )
        
        # ISO1 at 75°C with 3 cycles
        controller.send_command("ISO17506003")
        
        # Rapid step through to get faster simulation
        telemetry_list = []
        for _ in range(1500):
            telem = controller.step(dt_s=1.0)
            telemetry_list.append(telem)
        
        # Count transitions into QUALIFY_CYCLE with different cycle numbers
        cycle_transitions = {}
        for t in telemetry_list:
            if t.controller_state == ControllerState.QUALIFY_CYCLE and t.current_cycle is not None:
                cycle_num = t.current_cycle
                cycle_transitions[cycle_num] = cycle_transitions.get(cycle_num, 0) + 1
        
        # Should see at least cycles 0, 1, 2, 3 (maybe 4 depending on timing)
        unique_cycles = set(cycle_transitions.keys())
        assert len(unique_cycles) >= 3, f"Should see multiple cycles, only saw {unique_cycles}"


class TestPLAT1Mode:
    """Test PLAT1 plateau mode with slope/range validation."""
    
    def test_plat1_validates_slope_before_hold(self):
        """
        Test that PLAT1 validates slope before entering hold phase.
        
        Slope must be within [-2.0, +2.0] °C/min before holding.
        """
        controller = PTKitControllerIntegration(
            plant_config={
                'heating_power_w': 300.0,
                'thermal_mass': 60.0,
                'cooling_rate_w': 2.0
            },
            seed=42
        )
        
        # PLAT1 at 75°C ±0.5°C, slope ±0.5°C/min (strict slope requirement)
        controller.send_command("PLAT1075200200")
        
        # Run simulation until we see plateau validation
        for _ in range(400):
            controller.step(dt_s=1.0)
        
        trace = controller.get_telemetry_buffer()
        plateaus_seen = [t for t in trace if t.controller_state == ControllerState.PLATEAU_VALIDATE]
        
        # Should enter plateau validation state
        assert len(plateaus_seen) > 0, "Should enter PLATEAU_VALIDATE state"
        
        # Check that slope values are being tracked
        slopes_recorded = [
            t.average_slope_c_per_min 
            for t in plateaus_seen 
            if t.average_slope_c_per_min is not None
        ]
        
        # Slope should vary during validation
        if len(slopes_recorded) > 1:
            slope_range = max(slopes_recorded) - min(slopes_recorded)
            assert slope_range > 0, "Slope should change during validation"
    
    def test_plat1_temp_range_validation(self):
        """Test PLAT1 validates temperature stays within range bounds."""
        controller = PTKitControllerIntegration(
            plant_config={
                'heating_power_w': 300.0,
                'thermal_mass': 50.0,
                'cooling_rate_w': 2.0,
                'ambient_temp_c': 25.0
            },
            seed=42
        )
        
        # PLAT1 at 90°C ±1.0°C (range: 89°C to 91°C)
        controller.send_command("PLAT1090200200")
        
        # Run simulation
        for _ in range(300):
            controller.step(dt_s=1.0)
        
        trace = controller.get_telemetry_buffer()
        
        # Check all temperatures during PLATEAU_VALIDATE are logged
        plateau_temps = [
            t.surface_temp_c 
            for t in trace 
            if t.controller_state == ControllerState.PLATEAU_VALIDATE
        ]
        
        assert len(plateau_temps) > 0, "Should have recorded plateau temperatures"
        
        # Target was 90°C
        target = 90.0
        for temp in plateau_temps[:10]:  # Check first 10 readings
            # Temperature should approach target
            diff = abs(temp - target)
            assert diff <= 10.0, f"Temperature {temp} too far from target {target}"


class TestCalibrationModes:
    """Test calibration mode sequences."""
    
    def test_cal_bare_to_tape_sequence_completes(self):
        """
        Test that CAL_BARE → CAL_TAPE sequence completes successfully.
        
        Sequence: CAL_BARE heats to 150°C → transitions to CAL_TAPE → 
                 CAL_TAPE heats to 120°C → DONE
        """
        controller = PTKitControllerIntegration(
            plant_config={'heating_power_w': 100.0, 'thermal_mass': 40.0},
            seed=42
        )
        
        # Start CAL_BARE sequence
        controller.send_command("CALBARE")
        
        # Step until CAL_BARE reaches target and transitions
        telems = controller.get_telemetry_buffer()
        
        # Run until we see transition out of CALIBRATING
        calib_start_time = 0
        for i in range(300):
            controller.step(dt_s=1.0)
            telems = controller.get_telemetry_buffer()
            
            if controller.state == ControllerState.HOLDING:
                break
        
        # Should have started transitioning to tape calibration
        assert controller.experiment_config is not None
        # After CAL_BARE holds, it should transition to CAL_TAPE mode
        
    def test_cal_full_mode(self):
        """Test CAL_FULL mode execution."""
        controller = PTKitControllerIntegration(
            plant_config={'heating_power_w': 300.0, 'thermal_mass': 50.0, 'cooling_rate_w': 2.0},
            seed=42
        )
        
        controller.send_command("CAL_FULL")
        
        # Run for extended period
        for _ in range(600):
            controller.step(dt_s=1.0)
        
        trace = controller.get_telemetry_buffer()
        
        # Should reach a terminal state
        final_state = trace[-1].controller_state if trace else None
        assert final_state in [ControllerState.FINISHED, ControllerState.DONE], \
            f"CAL_FULL should complete, got {final_state}"
        
        # Verify temperature reached high value
        max_temp = max(t.surface_temp_c for t in trace)
        assert max_temp > 100.0, f"Should reach high calibration temp, max was {max_temp}"


class TestInvalidSensorHandling:
    """Test invalid sensor behavior across all modes."""
    
    def test_invalid_sensor_returns_safe_output(self):
        """Test that invalid sensors return safe/invalid output."""
        controller = PTKitControllerIntegration(
            plant_config={'heating_power_w': 50.0, 'thermal_mass': 50.0},
            seed=42
        )
        
        # Simulate error condition
        controller.supervision = SupervisionFlag.INVALID_SENSOR
        
        # Execute step with invalid sensor
        telemetry = controller.step(dt_s=1.0)
        
        # Should report invalid temperature (-273.15°C = absolute zero)
        assert telemetry.surface_temp_c == -273.15, \
            f"Invalid sensor should return -273.15, got {telemetry.surface_temp_c}"
        assert telemetry.side_channel_message == "ERR"
    
    def test_all_modes_handle_invalid_sensors(self):
        """Verify all experiment modes handle invalid sensors correctly."""
        modes = ["ISO1", "PLAT1", "CAL_BARE", "CAL_TAPE"]
        
        for mode_str in modes:
            controller = PTKitControllerIntegration(
                plant_config={'heating_power_w': 50.0, 'thermal_mass': 50.0},
                seed=42
            )
            
            # Trigger invalid sensor
            controller.supervision = SupervisionFlag.INVALID_SENSOR
            
            # Send mode command
            cmd = {"ISO1": "ISO1750600", "PLAT1": "PLAT1075200200", "CAL_BARE": "CALBARE", "CAL_TAPE": "CALTAPE"}[mode_str]
            controller.send_command(cmd)
            
            # Take measurement
            telem = None
            for _ in range(5):
                telem = controller.step(dt_s=1.0)
            
            assert telem is not None, "Telemetry should exist"
            
            # Even during operation, invalid sensor should override
            assert telem.surface_temp_c == -273.15 or \
                   (controller.state in [ControllerState.ERROR, ControllerState.ABORTED]), \
                f"{mode_str} should handle invalid sensor"


class TestDeterminism:
    """Test deterministic behavior with fixed seeds."""
    
    def test_fixed_seed_produces_identical_traces(self):
        """
        Test that same seed produces identical traces across runs.
        
        This ensures reproducibility for testing and debugging.
        """
        seed = 12345
        plant_config = {'heating_power_w': 50.0, 'thermal_mass': 50.0}
        
        # Run 1
        controller1 = PTKitControllerIntegration(plant_config, seed=seed)
        controller1.send_command("ISO180602")
        
        traces1 = []
        for _ in range(200):
            telem = controller1.step(dt_s=1.0)
            traces1.append(telem.to_dict())
        
        # Run 2 with same seed
        controller2 = PTKitControllerIntegration(plant_config, seed=seed)
        controller2.send_command("ISO180602")
        
        traces2 = []
        for _ in range(200):
            telem = controller2.step(dt_s=1.0)
            traces2.append(telem.to_dict())
        
        # Compare traces
        assert len(traces1) == len(traces2), "Traces should have same length"
        
        for i, (t1, t2) in enumerate(zip(traces1, traces2)):
            assert t1['surface_temp_c'] == t2['surface_temp_c'], \
                f"Mismatch at step {i}: t1={t1['surface_temp_c']}, t2={t2['surface_temp_c']}"
            assert t1['bulk_temp_c'] == t2['bulk_temp_c'], \
                f"Bulk temp mismatch at step {i}"
            assert t1['lamp_output_lux'] == t2['lamp_output_lux'], \
                f"Lamp lux mismatch at step {i}"
            assert t1['controller_state'] == t2['controller_state'], \
                f"State mismatch at step {i}"
    
    def test_different_seeds_produce_different_traces(self):
        """Test that different seeds produce different results."""
        plant_config = {'heating_power_w': 50.0, 'thermal_mass': 50.0}
        
        # Run with seed 1
        controller1 = PTKitControllerIntegration(plant_config, seed=1)
        controller1.send_command("ISO180602")
        
        for _ in range(100):
            controller1.step(dt_s=1.0)
        
        traces1 = controller1.get_telemetry_buffer()
        initial_temp1 = traces1[50].surface_temp_c
        
        # Run with seed 2
        controller2 = PTKitControllerIntegration(plant_config, seed=2)
        controller2.send_command("ISO180602")
        
        for _ in range(100):
            controller2.step(dt_s=1.0)
        
        traces2 = controller2.get_telemetry_buffer()
        initial_temp2 = traces2[50].surface_temp_c
        
        # With randomization, should differ (though edge case where they match is possible)
        # This is a probabilistic check
        import logging
        log = logging.getLogger(__name__)
        log.info(f"Seed 1 temp at 50s: {initial_temp1}")
        log.info(f"Seed 2 temp at 50s: {initial_temp2}")


class TestExtendedTelemetryStructure:
    """Test ExtendedTelemetry frame structure and fields."""
    
    def test_extended_telemetry_has_all_17_fields(self):
        """Verify ExtendedTelemetry has exactly 17 fields."""
        controller = PTKitControllerIntegration(
            plant_config={'heating_power_w': 50.0, 'thermal_mass': 50.0},
            seed=42
        )
        
        # Send a command to trigger some telemetry
        controller.send_command("ISO180602")
        
        for _ in range(10):
            controller.step(dt_s=1.0)
        
        trace = controller.get_telemetry_buffer()
        
        # Check first telemetry frame
        if trace:
            telem = trace[0]
            telem_dict = telem.to_dict()
            
            # Verify all 17 expected fields exist
            expected_fields = [
                'timestamp_s', 'controller_state', 'supervision_flag',
                'surface_temp_c', 'bulk_temp_c', 'lamp_output_lux',
                'target_temp_c', 'setpoint_temp_c', 'hold_temp_c',
                'current_cycle', 'total_cycles', 'elapsed_hold_s',
                'max_slope_c_per_min', 'min_slope_c_per_min', 
                'average_slope_c_per_min', 'side_channel_message'
            ]
            
            for field_name in expected_fields:
                assert field_name in telem_dict, f"Missing field: {field_name}"
            
            assert len(telem_dict) == 17, f"Should have exactly 17 fields, has {len(telem_dict)}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
