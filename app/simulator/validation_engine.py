"""Validation engine for plant simulation system.

This module provides validation checking for thermal feasibility,
scenario constraints, and calibration bounds.
"""

from typing import List, Tuple, Optional, Dict, Any
from dataclasses import dataclass


@dataclass
class TargetSetpoint:
    """Target temperature/lux setpoints for automated control."""
    
    target_surface_temp_c: Optional[float] = None
    target_bulk_temp_c: Optional[float] = None
    target_lux: Optional[int] = None
    ramp_rate_c_per_min: Optional[float] = None
    hold_duration_s: Optional[float] = None
    
    def validate(self) -> List[str]:
        """Validate setpoint combinations make physical sense."""
        errors = []
        
        # Check for conflicting targets
        if (self.target_surface_temp_c is not None and 
            self.target_bulk_temp_c is not None):
            diff = abs(self.target_surface_temp_c - self.target_bulk_temp_c)
            if diff < 2:
                errors.append(
                    f"Surface and bulk targets too close ({diff:.1f}°C difference), "
                    "minimum 2°C recommended"
                )
        
        # Validate ramp rates are achievable
        if self.ramp_rate_c_per_min is not None:
            if self.ramp_rate_c_per_min > 10:
                errors.append(
                    f"Ramp rate {self.ramp_rate_c_per_min}°C/min exceeds maximum "
                    "of 10°C/min"
                )
            
            if self.ramp_rate_c_per_min < 0:
                errors.append("Ramp rate cannot be negative")
        
        return errors


class ThermalFeasibilityChecker:
    """Check if thermal parameters allow stable operation."""
    
    @staticmethod
    def check_thermal_mass_ratios(plant_params) -> Tuple[bool, List[str]]:
        """Validate surface/bulk thermal mass ratio.
        
        Returns:
            Tuple of (is_feasible, list_of_warnings)
        """
        warnings = []
        
        if plant_params.bulk_thermal_mass_j_k > 0:
            ratio = (plant_params.surface_thermal_mass_j_k / 
                    plant_params.bulk_thermal_mass_j_k)
            
            if ratio > 5:
                warnings.append(
                    f"Surface thermal mass ratio too high ({ratio:.2f}), "
                    "may cause slow response"
                )
            elif ratio < 0.1:
                warnings.append(
                    f"Surface thermal mass ratio too low ({ratio:.2f}), "
                    "rapid fluctuations expected"
                )
        
        return len(warnings) == 0, warnings
    
    @staticmethod
    def check_lamp_efficiency(plant_params) -> Tuple[bool, List[str]]:
        """Check if lamp efficiency allows reaching targets.
        
        Returns:
            Tuple of (is_feasible, list_of_warnings)
        """
        warnings = []
        
        max_effective_power = (plant_params.max_lamp_power_w * 
                              plant_params.lamp_efficiency_pct / 100)
        
        if max_effective_power < 10:
            warnings.append(
                f"Effective lamp power below 10W ({max_effective_power:.1f}W), "
                "may struggle to reach heating targets"
            )
        
        return len(warnings) == 0, warnings
    
    @staticmethod
    def check_therrmal_feasibility(plant_params) -> Tuple[bool, List[str]]:
        """Run full thermal feasibility checks.
        
        Returns:
            Tuple of (is_feasible, list_of_warnings)
        """
        all_warnings = []
        
        # Run individual checks
        _, ratio_warnings = ThermalFeasibilityChecker.check_thermal_mass_ratios(
            plant_params
        )
        all_warnings.extend(ratio_warnings)
        
        _, efficiency_warnings = ThermalFeasibilityChecker.check_lamp_efficiency(
            plant_params
        )
        all_warnings.extend(efficiency_warnings)
        
        return len(all_warnings) == 0, all_warnings


class ScenarioConstraintValidator:
    """Validate experiment scenario constraints."""
    
    @staticmethod
    def validate_fault_schedule(scenario) -> Tuple[bool, List[str]]:
        """Validate fault schedule timing.
        
        Args:
            scenario: ExperimentScenario object with duration_s and fault_schedule
            
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []
        
        if hasattr(scenario, 'fault_schedule') and scenario.fault_schedule:
            for fault in scenario.fault_schedule:
                fault_time = fault.get('time_s', 0)
                duration = getattr(scenario, 'duration_s', float('inf'))
                
                if fault_time > duration:
                    errors.append(
                        f"Fault scheduled at {fault_time}s exceeds "
                        f"experiment duration {duration}s"
                    )
        
        return len(errors) == 0, errors
    
    @staticmethod
    def validate_target_setpoints(target_setpoint: TargetSetpoint) -> Tuple[bool, List[str]]:
        """Validate target setpoint configurations.
        
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = target_setpoint.validate()
        return len(errors) == 0, errors
    
    @staticmethod
    def validate_ramp_rates(target_setpoint: TargetSetpoint) -> Tuple[bool, List[str]]:
        """Validate ramp rates are within physical limits.
        
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        if target_setpoint.ramp_rate_c_per_min is not None:
            if target_setpoint.ramp_rate_c_per_min > 10:
                return False, [
                    f"Ramp rate {target_setpoint.ramp_rate_c_per_min}°C/min "
                    "exceeds physical limit of 10°C/min"
                ]
        return True, []


class CalibrationOffsetChecker:
    """Validate sensor calibration offset ranges."""
    
    MAX_OFFSET_CELSIUS = 10.0
    
    @staticmethod
    def check_offset_bounds(sensor_config) -> Tuple[bool, List[str]]:
        """Validate all offsets within ±10°C limit.
        
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []
        
        ir_offset = getattr(sensor_config, 'ir_temp_offset_c', 0)
        tc_offset = getattr(sensor_config, 'tc_temp_offset_c', 0)
        
        if abs(ir_offset) > CalibrationOffsetChecker.MAX_OFFSET_CELSIUS:
            errors.append(
                f"IR sensor offset {ir_offset}°C exceeds "
                f"±{CalibrationOffsetChecker.MAX_OFFSET_CELSIUS}°C limit"
            )
        
        if abs(tc_offset) > CalibrationOffsetChecker.MAX_OFFSET_CELSIUS:
            errors.append(
                f"TC sensor offset {tc_offset}°C exceeds "
                f"±{CalibrationOffsetChecker.MAX_OFFSET_CELSIUS}°C limit"
            )
        
        return len(errors) == 0, errors
    
    @staticmethod
    def check_gain_ranges(sensor_config) -> Tuple[bool, List[str]]:
        """Validate gain values are positive and reasonable.
        
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []
        
        lux_gain = getattr(sensor_config, 'lux_gain', 1.0)
        
        if lux_gain <= 0:
            errors.append(f"Lux gain {lux_gain} must be > 0")
        elif lux_gain > 2.0:
            errors.append(
                f"Lux gain {lux_gain} exceeds reasonable range "
                "(recommended ≤ 2.0)"
            )
        
        noise_sigma = getattr(sensor_config, 'temp_noise_sigma', 0)
        
        if noise_sigma < 0:
            errors.append(f"Temperature noise sigma {noise_sigma} cannot be negative")
        
        return len(errors) == 0, errors


def run_comprehensive_validation(profile, scenario=None) -> Tuple[bool, List[str]]:
    """Run comprehensive validation suite on profile and optional scenario.
    
    This function orchestrates all validation checks across:
    - Profile parameter validity (PlantProfile.validate())
    - Thermal feasibility analysis
    - Sensor calibration bounds
    - Scenario-specific constraints (if provided)
    
    Args:
        profile: PlantProfile instance to validate
        scenario: Optional ExperimentScenario for additional checks
        
    Returns:
        Tuple of (is_valid, list_of_all_errors_and_warnings)
    """
    all_messages = []
    
    # 1. Basic profile validation
    is_valid, errors = profile.validate()
    all_messages.extend(errors)
    
    if is_valid:
        # 2. Thermal feasibility checks (warnings only)
        _, thermal_warnings = ThermalFeasibilityChecker.check_therrmal_feasibility(
            profile.plant_params
        )
        all_messages.extend(thermal_warnings)
        
        # 3. Sensor calibration bounds
        _, calibration_errors = CalibrationOffsetChecker.check_offset_bounds(
            profile.sensor_config
        )
        all_messages.extend(calibration_errors)
        
        _, gain_errors = CalibrationOffsetChecker.check_gain_ranges(
            profile.sensor_config
        )
        all_messages.extend(gain_errors)
    
    # 4. Scenario-specific checks (if provided)
    if scenario:
        # Fault schedule validation
        _, fault_errors = ScenarioConstraintValidator.validate_fault_schedule(scenario)
        all_messages.extend(fault_errors)
        
        # Target setpoint validation
        if hasattr(scenario, 'targets') and scenario.targets:
            _, target_errors = ScenarioConstraintValidator.validate_target_setpoints(
                scenario.targets
            )
            all_messages.extend(target_errors)
    
    final_is_valid = len([m for m in all_messages if 'error' in m.lower()]) == 0
    
    return final_is_valid, all_messages
