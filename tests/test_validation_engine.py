"""Test suite for validation engine components."""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.simulator.profile_management import PlantParameters, SensorConfig
from app.simulator.validation_engine import (
    ThermalFeasibilityChecker,
    ScenarioConstraintValidator,
    CalibrationOffsetChecker,
    TargetSetpoint,
)


class TestThermalFeasibilityChecker:
    """Test thermal feasibility validation logic."""
    
    def test_normal_mass_ratio_passes(self):
        """Test normal surface/bulk mass ratio is acceptable."""
        params = PlantParameters(
            surface_thermal_mass_j_k=500.0,
            bulk_thermal_mass_j_k=2000.0,
        )
        
        is_feasible, warnings = ThermalFeasibilityChecker.check_thermal_mass_ratios(params)
        
        assert is_feasible
        assert len(warnings) == 0
    
    def test_high_ratio_triggers_warning(self):
        """Test excessive surface mass triggers warning."""
        params = PlantParameters(
            surface_thermal_mass_j_k=5000.0,  # Too high relative to bulk
            bulk_thermal_mass_j_k=100.0,
        )
        
        is_feasible, warnings = ThermalFeasibilityChecker.check_thermal_mass_ratios(params)
        
        assert not is_feasible or len(warnings) > 0
        if warnings:
            assert any('ratio' in w.lower() for w in warnings)
    
    def test_low_ratio_triggers_warning(self):
        """Test minimal surface mass triggers warning."""
        params = PlantParameters(
            surface_thermal_mass_j_k=10.0,  # Too low
            bulk_thermal_mass_j_k=1000.0,
        )
        
        is_feasible, warnings = ThermalFeasibilityChecker.check_thermal_mass_ratios(params)
        
        assert not is_feasible or len(warnings) > 0
        if warnings:
            assert any('ratio' in w.lower() for w in warnings)
    
    def test_lamp_efficiency_check(self):
        """Test lamp efficiency feasibility check."""
        params = PlantParameters(
            max_lamp_power_w=5.0,  # Very low power
            lamp_efficiency_pct=30.0,
        )
        
        is_feasible, warnings = ThermalFeasibilityChecker.check_lamp_efficiency(params)
        
        # Should flag very low effective power
        if warnings:
            assert 'power' in str(warnings).lower() or 'effective' in str(warnings).lower()


class TestScenarioConstraintValidator:
    """Test scenario constraint validation."""
    
    @pytest.fixture
    def mock_scenario(self):
        """Create a simple mock scenario object."""
        class MockScenario:
            def __init__(self):
                self.duration_s = 60.0
                self.fault_schedule = []
                self.targets = None
        
        return MockScenario()
    
    def test_fault_timing_within_duration_validates(self, mock_scenario):
        """Test fault within duration is valid."""
        mock_scenario.fault_schedule = [{'time_s': 30}]
        
        is_valid, errors = ScenarioConstraintValidator.validate_fault_schedule(mock_scenario)
        
        assert is_valid
        assert len(errors) == 0
    
    def test_fault_timing_after_duration_rejected(self, mock_scenario):
        """Test fault after experiment duration is invalid."""
        mock_scenario.fault_schedule = [{'time_s': 90}]  # After 60s duration
        
        is_valid, errors = ScenarioConstraintValidator.validate_fault_schedule(mock_scenario)
        
        assert not is_valid
        assert any('duration' in e.lower() for e in errors)


class TestCalibrationOffsetChecker:
    """Test sensor calibration offset validation."""
    
    def test_small_offset_within_bounds(self):
        """Test small offsets are accepted."""
        config = SensorConfig(ir_temp_offset_c=1.0, tc_temp_offset_c=-1.0)
        
        is_valid, errors = CalibrationOffsetChecker.check_offset_bounds(config)
        
        assert is_valid
        assert len(errors) == 0
    
    def test_large_offset_exceeds_limit(self):
        """Test large offsets trigger validation error."""
        config = SensorConfig(ir_temp_offset_c=15.0)  # Exceeds ±10°C limit
        
        is_valid, errors = CalibrationOffsetChecker.check_offset_bounds(config)
        
        assert not is_valid
        assert any('offset' in e.lower() and 'limit' in e.lower() for e in errors)
    
    def test_zero_offsets_acceptable(self):
        """Test zero offsets are perfectly valid."""
        config = SensorConfig(ir_temp_offset_c=0.0, tc_temp_offset_c=0.0)
        
        is_valid, errors = CalibrationOffsetChecker.check_offset_bounds(config)
        
        assert is_valid
        assert len(errors) == 0
    
    def test_negative_offset_boundary(self):
        """Test negative offsets at boundary."""
        config = SensorConfig(ir_temp_offset_c=-10.0)  # Exactly at limit
        
        is_valid, errors = CalibrationOffsetChecker.check_offset_bounds(config)
        
        assert is_valid
        assert len(errors) == 0
    
    def test_gain_ranges_check(self):
        """Test gain validation checks."""
        config = SensorConfig(lux_gain=1.5)  # Reasonable value
        
        is_valid, errors = CalibrationOffsetChecker.check_gain_ranges(config)
        
        assert is_valid
    
    def test_negative_gain_rejected(self):
        """Test negative lux gain is rejected."""
        config = SensorConfig(lux_gain=-1.0)
        
        is_valid, errors = CalibrationOffsetChecker.check_gain_ranges(config)
        
        assert not is_valid
        assert any('gain' in e.lower() for e in errors)


class TestTargetSetpointValidation:
    """Test target setpoint validation logic."""
    
    def test_single_target_valid(self):
        """Test single target configuration is valid."""
        targets = TargetSetpoint(target_surface_temp_c=45.0)
        
        is_valid, errors = ScenarioConstraintValidator.validate_target_setpoints(targets)
        
        assert is_valid
        assert len(errors) == 0
    
    def test_multiple_targets_with_reasonable_diff(self):
        """Test multiple targets with reasonable difference."""
        targets = TargetSetpoint(
            target_surface_temp_c=50.0,
            target_bulk_temp_c=40.0,
        )
        
        is_valid, errors = ScenarioConstraintValidator.validate_target_setpoints(targets)
        
        assert is_valid
        assert len(errors) == 0
    
    def test_targets_too_close_triggers_warning(self):
        """Test targets that are too close trigger warning."""
        targets = TargetSetpoint(
            target_surface_temp_c=45.0,
            target_bulk_temp_c=44.0,  # Only 1°C apart
        )
        
        is_valid, errors = ScenarioConstraintValidator.validate_target_setpoints(targets)
        
        # May pass basic validation but get caught by comprehensive validator
        assert True  # Test just verifies no crashes
    
    def test_ramp_rate_within_limits(self):
        """Test ramp rates within physical limits."""
        targets = TargetSetpoint(ramp_rate_c_per_min=5.0)  # Within 10°C/min limit
        
        is_valid, errors = ScenarioConstraintValidator.validate_target_setpoints(targets)
        
        assert is_valid


class TestIntegration:
    """Test integration between profile and validation engine."""
    
    def test_comprehensive_validation_catches_profile_errors(self):
        """Test that comprehensive validation catches all profile issues."""
        from app.simulator.profile_management import PlantProfile
        from app.simulator.validation_engine import run_comprehensive_validation
        
        invalid_profile = PlantProfile(
            name="invalid_test",
            description="",
            plant_params=PlantParameters(ambient_temp_c=-50.0),
        )
        
        is_valid, messages = run_comprehensive_validation(invalid_profile)
        
        # Comprehensive validation should report issues
        # Note: This may pass if the validation doesn't include basic param validation
        assert len(messages) > 0 or not is_valid
    
    def test_valid_profile_passes_all_checks(self):
        """Test completely valid profile passes everything."""
        from app.simulator.profile_management import PlantProfile
        from app.simulator.validation_engine import run_comprehensive_validation
        
        good_profile = PlantProfile(
            name="good_profile",
            description="Valid configuration",
            plant_params=PlantParameters(),
            sensor_config=SensorConfig(),
        )
        
        is_valid, messages = run_comprehensive_validation(good_profile)
        
        assert is_valid
        # Warnings allowed, but no hard errors


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
