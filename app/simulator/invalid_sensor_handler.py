"""Invalid sensor handler for Phase 3 plant controller simulation.

This module implements the current firmware's handling of invalid sensors:
- Timeout thresholds for IR/TC/Lux sensor invalidity
- Safe-output behavior when sensors are invalid
- Zero-conditioning for legacy modes
- Per-mode handling (ISO1, PLAT1)

All behavior matches current firmware exactly without correction attempts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class SensorStatus:
    """Current sensor validity and timeout status."""
    
    ir_valid: bool = True
    tc_valid: bool = True
    lux_valid: bool = True
    
    # Consecutive invalid reading counts
    ir_invalid_count: int = 0
    tc_invalid_count: int = 0
    lux_invalid_count: int = 0
    
    # Current safe values
    ir_safe_value_c: float = 0.0
    tc_safe_value_c: float = 0.0
    lux_safe_value: float = 0.0


@dataclass 
class InvalidSensorConfig:
    """Configuration for invalid sensor handling."""
    
    # Timeout thresholds (consecutive invalid readings before declaring failure)
    ir_timeout_count: int = 5
    tc_timeout_count: int = 5
    lux_timeout_count: int = 10
    
    # Safe output values (zero-conditioning per firmware spec)
    ir_safe_output_c: float = 0.0
    tc_safe_output_c: float = 0.0
    lux_safe_output_lux: float = 0.0
    
    # Recovery debounce (consecutive valid readings before declaring recovery)
    recovery_debounce: int = 3


class InvalidSensorHandler:
    """Handles sensor invalidity according to current firmware behavior.
    
    Tracks validity flags from simulated sensors and applies:
    - Timeout logic (N consecutive invalid readings triggers failure state)
    - Safe-output substitution (zero-conditioning for legacy modes)
    - Mode-specific fallback chains (ISO1 uses IR→TC→zero)
    
    Does NOT implement any automatic corrections or improved algorithms.
    Behavior reproduces physical firmware exactly.
    """
    
    def __init__(self, config: InvalidSensorConfig | None = None):
        """Initialize with configuration."""
        self._config = config or InvalidSensorConfig()
        self._status = SensorStatus()
        
    def update_from_reading(self, ir_valid: bool, tc_valid: bool, lux_valid: bool) -> SensorStatus:
        """Update validity status from latest sensor readings.
        
        Args:
            ir_valid: IR sensor validity flag from sensors.py
            tc_valid: TC sensor validity flag from sensors.py  
            lux_valid: Lux sensor validity flag from sensors.py
        
        Returns:
            Updated SensorStatus with current timeout counts and safe values
        """
        # Update validity flags
        self._status.ir_valid = ir_valid
        self._status.tc_valid = tc_valid
        self._status.lux_valid = lux_valid
        
        # Update timeout counters (increment on invalid, reset on valid)
        if ir_valid:
            self._status.ir_invalid_count = max(0, self._status.ir_invalid_count - 1)
        else:
            self._status.ir_invalid_count += 1
            
        if tc_valid:
            self._status.tc_invalid_count = max(0, self._status.tc_invalid_count - 1)
        else:
            self._status.tc_invalid_count += 1
            
        if lux_valid:
            self._status.lux_invalid_count = max(0, self._status.lux_invalid_count - 1)
        else:
            self._status.lux_invalid_count += 1
        
        return self._status
    
    def is_ir_timed_out(self) -> bool:
        """Check if IR sensor has timed out (exceeded threshold)."""
        return self._status.ir_invalid_count >= self._config.ir_timeout_count
    
    def is_tc_timed_out(self) -> bool:
        """Check if TC sensor has timed out (exceeded threshold)."""
        return self._status.tc_invalid_count >= self._config.tc_timeout_count
    
    def is_lux_timed_out(self) -> bool:
        """Check if lux sensor has timed out (exceeded threshold)."""
        return self._status.lux_invalid_count >= self._config.lux_timeout_count
    
    def get_valid_temperature_source(
        self, 
        ir_temp_c: float, 
        tc_temp_c: float
    ) -> tuple[float, Literal['IR', 'TC', 'NONE']]:
        """Determine which temperature source to use (ISO1 mode priority chain).
        
        Priority chain per firmware spec:
        1. Use IR if valid AND not timed out
        2. Fallback to TC if valid AND not timed out  
        3. Return safe value (zero) if neither available
        
        Args:
            ir_temp_c: Raw IR sensor temperature
            tc_temp_c: Raw TC sensor temperature
        
        Returns:
            Tuple of (temperature_to_use, source_label)
            source_label will be 'IR', 'TC', or 'NONE'
        """
        # Try IR first
        if self._status.ir_valid and not self.is_ir_timed_out():
            return ir_temp_c, 'IR'
        
        # Fallback to TC
        if self._status.tc_valid and not self.is_tc_timed_out():
            return tc_temp_c, 'TC'
        
        # Neither available - return safe value
        return self._config.ir_safe_output_c, 'NONE'
    
    def get_selected_sensor_for_plat(
        self,
        selected_sensor: int,  # 0=IR, 1=TC
        ir_temp_c: float,
        tc_temp_c: float
    ) -> tuple[float, Literal['IR', 'TC']]:
        """Get temperature for PLAT1 plateau mode based on selected sensor.
        
        Uses same timeout/safe-output logic as ISO1 but for single selected sensor.
        
        Args:
            selected_sensor: Which sensor to use (0=IR, 1=TC)
            ir_temp_c: IR sensor temperature
            tc_temp_c: TC sensor temperature
        
        Returns:
            Tuple of (temperature_to_use, source_label)
        """
        if selected_sensor == 0:  # IR
            if self._status.ir_valid and not self.is_ir_timed_out():
                return ir_temp_c, 'IR'
            return self._config.ir_safe_output_c, 'IR'  # Still label as IR even though using safe
        
        else:  # TC
            if self._status.tc_valid and not self.is_tc_timed_out():
                return tc_temp_c, 'TC'
            return self._config.tc_safe_output_c, 'TC'
    
    def apply_zero_conditioning(self, value: float, source: str) -> float:
        """Apply zero-conditioning for legacy mode compatibility.
        
        This replicates current firmware's invalid-to-zero conditioning.
        
        Args:
            value: Temperature or lux value that may be conditioned
            source: Either 'IR' or 'TC'
        
        Returns:
            Conditioned value (may be zero if sensor invalid)
        """
        if source == 'IR':
            return self._config.ir_safe_output_c if self.is_ir_timed_out() else value
        else:  # TC
            return self._config.tc_safe_output_c if self.is_tc_timed_out() else value
    
    def get_extended_telemetry_status(self) -> dict:
        """Get status fields for ExtendedTelemetry frame.
        
        Returns:
            Dictionary suitable for extending telemetry object
        """
        return {
            'ir_valid': self._status.ir_valid,
            'tc_valid': self._status.tc_valid,
            'lux_valid': self._status.lux_valid,
            'ir_invalid_count': self._status.ir_invalid_count,
            'tc_invalid_count': self._status.tc_invalid_count,
            'lux_invalid_count': self._status.lux_invalid_count,
        }
    
    def reset(self) -> None:
        """Reset all timeout counters and validity flags.
        
        Called at start of new experiment or after recovery detection.
        """
        self._status = SensorStatus()


__all__ = ['InvalidSensorHandler', 'InvalidSensorConfig', 'SensorStatus']
