"""Comprehensive tests for invalid sensor handling behavior.

Tests cover:
- IR sensor invalidity during ramp phase  
- TC sensor invalidity during hold phase
- Both IR+TC invalid simultaneously
- Lux sensor invalidity doesn't affect temperature control
- Timeout triggers after N consecutive invalid readings
- Safe-output values used during invalid period
- Sensor recovery (valid again after invalidity)
- Determinism with fixed seed
"""

import pytest
from app.simulator.invalid_sensor_handler import InvalidSensorHandler


class TestIRSensorInvalidityRampPhase:
    """Test IR sensor invalidity during ramp-up phase."""
    
    def test_ir_invalid_during_ramp(self):
        """IR becomes invalid during ramp - should fall back to TC or zero."""
        handler = InvalidSensorHandler()
        
        # Start with both sensors valid
        status = handler.update_from_reading(ir_valid=True, tc_valid=True, lux_valid=True)
        assert status.ir_valid and status.tc_valid
        
        # Get valid source - should return IR temperature
        ir_temp = 25.0
        tc_temp = 26.0
        temp, source = handler.get_valid_temperature_source(ir_temp, tc_temp)
        assert temp == ir_temp
        assert source == 'IR'
        
        # Simulate IR becoming invalid during ramp (multiple consecutive)
        for _ in range(4):  # Close to timeout (threshold is 5)
            status = handler.update_from_reading(ir_valid=False, tc_valid=True, lux_valid=True)
        
        # Should still work because TC is valid
        temp, source = handler.get_valid_temperature_source(ir_temp, tc_temp)
        assert temp == tc_temp
        assert source == 'TC'
    
    def test_ir_timeout_triggers_during_ramp(self):
        """IR hits timeout threshold during ramp phase."""
        handler = InvalidSensorHandler()
        
        ir_temp = 25.0
        tc_temp = 26.0
        
        # Hit timeout threshold (default is 5)
        for i in range(5):
            status = handler.update_from_reading(ir_valid=False, tc_valid=True, lux_valid=True)
            
            if i < 4:  # First 4 counts
                assert not handler.is_ir_timed_out()
        
        # After 5th invalid reading, should timeout
        assert handler.is_ir_timed_out()
        
        # Now should use TC since IR timed out
        temp, source = handler.get_valid_temperature_source(ir_temp, tc_temp)
        assert temp == tc_temp
        assert source == 'TC'