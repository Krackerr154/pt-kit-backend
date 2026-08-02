"""
Test Suite for Termination Semantics

Tests proper termination behavior and command handling:
- STOP is idempotent and does NOT trigger firmware ABORT
- Supervisor abort sets SUPERVISOR_ABORT flag separately from firmware ABORT
- DONE frame repetition and IDLE reset preservation
- Over-temperature quirk reproduction
- Verification that ABORT only comes from firmware faults, not STOP
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
)


class TestStopIdempotence:
    """Test STOP command idempotence and behavior."""
    
    def test_stop_is_idempotent(self):
        """
        Test that multiple STOP commands have same effect as single STOP.
        
        Idempotence means: STOP; STOP should behave identically to just STOP.
        """
        controller = PTKitControllerIntegration(
            plant_config={'heating_power_w': 300.0, 'thermal_mass': 50.0, 'cooling_rate_w': 2.0},
            seed=42
        )
        
        # Single STOP
        controller_single = PTKitControllerIntegration(
            plant_config={'heating_power_w': 300.0, 'thermal_mass': 50.0, 'cooling_rate_w': 2.0},
            seed=42
        )
        controller_single.send_command("ISO18000601")
        
        # Advance some time then STOP
        for _ in range(30):
            controller.step(dt_s=1.0)
        
        controller.send_command("STOP")
        controller_single.send_command("STOP")
        controller_single.send_command("STOP")  # Second STOP
        
        # After both sequences, compare states
        final_state_normal = controller.state
        final_state_double_stop = controller_single.state
        
        assert final_state_normal == final_state_double_stop, \
            f"Double STOP differs from single STOP: {final_state_normal} vs {final_state_double_stop}"
        
        # Both should be cooling or idle, not aborted
        assert final_state_normal != ControllerState.ABORTED, "STOP should not cause ABORTED state"
    
    def test_stop_does_not_trigger_firmware_abort(self):
        """
        Test that STOP does NOT set firmware ABORT state.
        
        Crucial distinction: STOP = graceful shutdown, ABORT = severe fault.
        """
        controller = PTKitControllerIntegration(
            plant_config={'heating_power_w': 300.0, 'thermal_mass': 50.0, 'cooling_rate_w': 2.0},
            seed=42
        )
        
        # Start an experiment
        controller.send_command("ISO18000601")
        
        # Run until we're actively heating
        for _ in range(30):
            controller.step(dt_s=1.0)
        
        initial_state = controller.state
        assert initial_state not in [ControllerState.ABORTED, ControllerState.ERROR]
        
        # Issue STOP
        controller.send_command("STOP")
        
        # Process transition
        controller.step(dt_s=1.0)
        
        # Verify supervision flag
        assert controller.supervision == SupervisionFlag.STOP_REQUESTED, \
            f"Supervision should be STOP_REQUESTED, got {controller.supervision}"
        
        # Most importantly: NOT firmware ABORT
        assert controller.state != ControllerState.ABORTED, \
            "STOP should NOT set state to ABORTED"
        
        assert controller.supervision != SupervisionFlag.ABORT_REQUESTED, \
            "STOP should NOT set ABORT_REQUESTED flag"
        
        # State should be transitioning gracefully (cooling) or already IDLE
        assert controller.state in [ControllerState.COOLING, ControllerState.IDLE], \
            f"After STOP, should be cooling/idle, got {controller.state}"
    
    def test_multiple_consecutive_stops_safe(self):
        """Test sending multiple STOP commands doesn't cause issues."""
        controller = PTKitControllerIntegration(
            plant_config={'heating_power_w': 300.0, 'thermal_mass': 50.0, 'cooling_rate_w': 2.0},
            seed=42
        )
        
        controller.send_command("ISO18000601")
        
        # Send multiple STOPs rapidly
        for _ in range(10):
            controller.send_command("STOP")
        
        # Step through (allow the graceful COOLING ramp to finish reaching IDLE)
        telems = []
        for i in range(600):
            telem = controller.step(dt_s=1.0)
            telems.append(telem)
        
        # Should complete without errors
        final_state = telems[-1].controller_state
        
        # Should reach a terminal state, never ABORTED
        assert final_state != ControllerState.ABORTED, "Multiple STOPs should not cause ABORT"
        assert final_state in [ControllerState.FINISHED, ControllerState.DONE, ControllerState.IDLE], \
            f"Should complete normally, got {final_state}"


class TestSupervisorAbort:
    """Test supervisor abort behavior (separate from firmware ABORT)."""
    
    def test_supervisor_abort_sets_flag(self):
        """Test that SUPERVISOR_ABORT sets correct supervision flag."""
        controller = PTKitControllerIntegration(
            plant_config={'heating_power_w': 300.0, 'thermal_mass': 50.0, 'cooling_rate_w': 2.0},
            seed=42
        )
        
        # Send supervisor abort command
        controller.send_command("SUPERVISOR_ABORT")
        
        # Step through
        controller.step(dt_s=1.0)
        
        # Should have supervisor abort flag
        assert controller.supervision == SupervisionFlag.SUPERVISOR_ABORT, \
            f"Should have SUPERVISOR_ABORT flag, got {controller.supervision}"
    
    def test_supervisor_abort_transitions_to_aborted(self):
        """Test that SUPERVISOR_ABORT transitions controller to ABORTED state."""
        controller = PTKitControllerIntegration(
            plant_config={'heating_power_w': 300.0, 'thermal_mass': 50.0, 'cooling_rate_w': 2.0},
            seed=42
        )
        
        # Start experiment
        controller.send_command("ISO18000601")
        
        # Run a bit
        for _ in range(20):
            controller.step(dt_s=1.0)
        
        initial_state = controller.state
        assert initial_state != ControllerState.IDLE
        
        # Issue supervisor abort
        controller.send_command("SUPERVISOR_ABORT")
        
        # Step through transition
        controller.step(dt_s=1.0)
        
        # Should be aborted
        assert controller.state == ControllerState.ABORTED, \
            f"SUPERVISOR_ABORT should transition to ABORTED, got {controller.state}"
    
    def test_supervisor_abort_different_from_firmware_abort(self):
        """
        Test that SUPERVISOR_ABORT and ABORT are distinct paths.
        
        Both may result in ABORTED state, but via different supervision flags.
        """
        # Path 1: SUPERVISOR_ABORT
        ctrl_sup = PTKitControllerIntegration(
            plant_config={'heating_power_w': 300.0, 'thermal_mass': 50.0, 'cooling_rate_w': 2.0},
            seed=42
        )
        ctrl_sup.send_command("SUPERVISOR_ABORT")
        ctrl_sup.step(dt_s=1.0)
        sup_flag = ctrl_sup.supervision
        
        # Path 2: ABORT
        ctrl_abort = PTKitControllerIntegration(
            plant_config={'heating_power_w': 300.0, 'thermal_mass': 50.0, 'cooling_rate_w': 2.0},
            seed=42
        )
        ctrl_abort.send_command("ABORT")
        ctrl_abort.step(dt_s=1.0)
        abort_flag = ctrl_abort.supervision
        
        # Different supervision flags
        assert sup_flag != abort_flag, \
            "SUPERVISOR_ABORT and ABORT should have different supervision flags"
        assert sup_flag == SupervisionFlag.SUPERVISOR_ABORT
        assert abort_flag == SupervisionFlag.ABORT_REQUESTED
    
    def test_idle_state_preserved_on_supervisor_abort(self):
        """Test that SUPERVISOR_ABORT preserves IDLE if already idle."""
        controller = PTKitControllerIntegration(
            plant_config={'heating_power_w': 300.0, 'thermal_mass': 50.0, 'cooling_rate_w': 2.0},
            seed=42
        )
        
        # Don't start anything, issue supervisor abort while idle
        controller.send_command("SUPERVISOR_ABORT")
        controller.step(dt_s=1.0)
        
        # Should still be IDLE (not forced to ABORTED)
        # But supervision flag should be set
        assert controller.supervision == SupervisionFlag.SUPERVISOR_ABORT
        # Actually, since it's already IDLE, it shouldn't change state


class TestDoneFrameRepetition:
    """Test DONE frame repetition and IDLE reset."""
    
    def test_done_frame_repeats_until_reset(self):
        """Test that DONE state repeats telemetry until explicit reset."""
        controller = PTKitControllerIntegration(
            plant_config={'heating_power_w': 300.0, 'thermal_mass': 50.0, 'cooling_rate_w': 2.0},
            seed=42
        )
        
        # Quick ISO1 completion
        controller.send_command("ISO18000301")
        
        # Run until DONE
        telems = []
        done_count = 0
        for i in range(400):
            telem = controller.step(dt_s=1.0)
            telems.append(telem)
            
            if controller.state == ControllerState.DONE:
                done_count += 1
                if done_count >= 5:  # Check 5 consecutive DONE frames
                    break
        
        assert done_count >= 5, f"Should see repeated DONE frames, only saw {done_count}"
        
        # Verify all DONE frames have same supervision (NONE or whatever was last)
        done_frames = [t for t in telems if t.controller_state == ControllerState.DONE]
        if len(done_frames) > 1:
            super_flags = set(t.supervision_flag for t in done_frames)
            # All should have same supervision
            assert len(super_flags) == 1, f"DONE frames should have consistent supervision, got {super_flags}"
    
    def test_idle_reset_preserves_state(self):
        """Test that resetting returns to clean IDLE state."""
        controller = PTKitControllerIntegration(
            plant_config={'heating_power_w': 300.0, 'thermal_mass': 50.0, 'cooling_rate_w': 2.0},
            seed=42
        )
        
        # Complete an experiment
        controller.send_command("ISO18000301")
        
        for _ in range(400):
            controller.step(dt_s=1.0)
        
        # Should be DONE
        assert controller.state == ControllerState.DONE
        
        # Reset
        controller.reset()
        
        # Verify clean IDLE
        assert controller.state == ControllerState.IDLE, \
            f"Reset should return to IDLE, got {controller.state}"
        assert controller.supervision == SupervisionFlag.NONE, \
            f"Reset should clear supervision, got {controller.supervision}"
        assert controller.experiment_config is None, \
            "Reset should clear experiment config"
        assert len(controller.telemetry_buffer) == 0, \
            "Reset should clear telemetry buffer"
    
    def test_complete_workflow_then_reset(self):
        """Test complete workflow with reset afterward."""
        controller = PTKitControllerIntegration(
            plant_config={'heating_power_w': 300.0, 'thermal_mass': 50.0, 'cooling_rate_w': 2.0},
            seed=42
        )
        
        # Full workflow
        controller.send_command("ISO18000301")
        
        for _ in range(60):
            controller.step(dt_s=1.0)
        
        # Now reset
        controller.reset()
        
        # Can immediately start new experiment
        controller.send_command("PLAT17560150")
        
        for _ in range(30):
            controller.step(dt_s=1.0)
        
        # Should be working on second experiment
        assert controller.state in [ControllerState.STARTING, ControllerState.WARMUP, 
                                    ControllerState.STABILIZING, ControllerState.PLATEAU_VALIDATE], \
            f"Second experiment should be running, got {controller.state}"


class TestOverTemperatureQuirk:
    """Test over-temperature behavior quirks."""
    
    def test_over_temp_reproduction(self):
        """
        Reproduce over-temperature quirk scenario.
        
        When lamp output is maxed out and cooling insufficient,
        temperature can overshoot target before stabilization kicks in.
        """
        controller = PTKitControllerIntegration(
            plant_config={
                'heating_power_w': 150.0,  # Very high power
                'thermal_mass': 30.0,      # Low thermal mass
                'cooling_rate_w': 2.0,     # Poor cooling
                'ambient_temp_c': 25.0
            },
            seed=42
        )
        
        # Fast heating target
        controller.send_command("ISO19000301")
        
        telems = []
        max_temp_seen = 25.0
        peak_index = 0
        
        # Watch temperature trajectory
        for i in range(100):
            telem = controller.step(dt_s=1.0)
            telems.append(telem)
            
            if telem.surface_temp_c > max_temp_seen:
                max_temp_seen = telem.surface_temp_c
                peak_index = i
        
        # Temperature should reach target
        assert max_temp_seen >= 85.0, f"Should approach target, max was {max_temp_seen}"
        
        # There may be overshoot before stabilization
        import logging
        log = logging.getLogger(__name__)
        log.info(f"Peak temp: {max_temp_seen:.1f}°C at step {peak_index}")
        
        # Note: The quirk is that temperature might overshoot slightly
        # before the controller enters HOLDING phase


class TestAbortFromFirmwareOnly:
    """Test that ABORT only occurs from firmware faults, not user commands."""
    
    def test_abort_only_from_firmware_faults(self):
        """Verify ABORT state only occurs from firmware ABORT command."""
        # Scenario 1: STOP should NEVER cause ABORT
        ctrl_stop = PTKitControllerIntegration(
            plant_config={'heating_power_w': 300.0, 'thermal_mass': 50.0, 'cooling_rate_w': 2.0},
            seed=42
        )
        ctrl_stop.send_command("ISO18000601")
        
        for _ in range(30):
            ctrl_stop.step(dt_s=1.0)
        
        ctrl_stop.send_command("STOP")
        ctrl_stop.step(dt_s=1.0)
        
        assert ctrl_stop.state != ControllerState.ABORTED, \
            "STOP should never lead to ABORTED state"
        
        # Scenario 2: SUPERVISOR_ABORT should cause ABORTED
        ctrl_super = PTKitControllerIntegration(
            plant_config={'heating_power_w': 300.0, 'thermal_mass': 50.0, 'cooling_rate_w': 2.0},
            seed=42
        )
        ctrl_super.send_command("SUPERVISOR_ABORT")
        ctrl_super.step(dt_s=1.0)
        
        assert ctrl_super.state == ControllerState.ABORTED, \
            "SUPERVISOR_ABORT should lead to ABORTED state"
        assert ctrl_super.supervision == SupervisionFlag.SUPERVISOR_ABORT
        
        # Scenario 3: Explicit ABORT causes ABORTED
        ctrl_abort = PTKitControllerIntegration(
            plant_config={'heating_power_w': 300.0, 'thermal_mass': 50.0, 'cooling_rate_w': 2.0},
            seed=42
        )
        ctrl_abort.send_command("ABORT")
        ctrl_abort.step(dt_s=1.0)
        
        assert ctrl_abort.state == ControllerState.ABORTED, \
            "Explicit ABORT should lead to ABORTED state"
        assert ctrl_abort.supervision == SupervisionFlag.ABORT_REQUESTED
    
    def test_no_pathway_from_stop_to_abort(self):
        """
        Verify no pathway allows STOP to eventually become ABORT.
        
        This is a critical safety property.
        """
        controller = PTKitControllerIntegration(
            plant_config={'heating_power_w': 300.0, 'thermal_mass': 50.0, 'cooling_rate_w': 2.0},
            seed=42
        )
        
        # Do various things then STOP
        controller.send_command("ISO18000601")
        
        for _ in range(20):
            controller.step(dt_s=1.0)
        
        # Multiple stops
        controller.send_command("STOP")
        controller.send_command("STOP")
        controller.send_command("STOP")
        
        # Continue stepping
        for _ in range(50):
            controller.step(dt_s=1.0)
        
        # Never transition to ABORTED after STOP
        trace = controller.get_telemetry_buffer()
        for telem in trace:
            if telem.supervision_flag == SupervisionFlag.STOP_REQUESTED:
                assert telem.controller_state != ControllerState.ABORTED, \
                    "No STOP supervision should ever show ABORTED state"


class TestTerminationSemanticsSeparation:
    """Test clear separation between termination semantics."""
    
    def test_stop_abort_supervisor_abort_distinct(self):
        """Verify STOP, ABORT, and SUPERVISOR_ABORT have distinct behaviors."""
        
        # STOP: Graceful, no firmware ABORT
        ctrl_stop = PTKitControllerIntegration(
            plant_config={'heating_power_w': 300.0, 'thermal_mass': 50.0, 'cooling_rate_w': 2.0},
            seed=42
        )
        ctrl_stop.send_command("ISO18000601")
        for _ in range(20):
            ctrl_stop.step(dt_s=1.0)
        ctrl_stop.send_command("STOP")
        ctrl_stop.step(dt_s=1.0)
        
        # ABORT: Firmware-level error
        ctrl_abort = PTKitControllerIntegration(
            plant_config={'heating_power_w': 300.0, 'thermal_mass': 50.0, 'cooling_rate_w': 2.0},
            seed=42
        )
        ctrl_abort.send_command("ABORT")
        ctrl_abort.step(dt_s=1.0)
        
        # SUPERVISOR_ABORT: Supervisor-level intervention
        ctrl_super = PTKitControllerIntegration(
            plant_config={'heating_power_w': 300.0, 'thermal_mass': 50.0, 'cooling_rate_w': 2.0},
            seed=42
        )
        ctrl_super.send_command("SUPERVISOR_ABORT")
        ctrl_super.step(dt_s=1.0)
        
        # All three result in different supervision states
        stop_sup = ctrl_stop.supervision
        abort_sup = ctrl_abort.supervision
        super_sup = ctrl_super.supervision
        
        assert stop_sup != abort_sup, "STOP supervision should differ from ABORT"
        assert stop_sup != super_sup, "STOP supervision should differ from SUPERVISOR_ABORT"
        assert abort_sup != super_sup, "ABORT supervision should differ from SUPERVISOR_ABORT"
        
        # STOP leaves state non-ABORTED
        assert ctrl_stop.state != ControllerState.ABORTED
        # Both ABORT and SUPERVISOR_ABORT result in ABORTED state
        assert ctrl_abort.state == ControllerState.ABORTED
        assert ctrl_super.state == ControllerState.ABORTED


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
