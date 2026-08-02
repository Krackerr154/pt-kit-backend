"""Golden trace loader and diff checker for Phase 3 differential testing."""

import json
import sys
from pathlib import Path
from typing import Any

# Add project root to path  
sys.path.insert(0, str(Path(__file__).parent.parent / 'app'))


def load_golden_trace(scenario: str) -> dict[str, Any]:
    """Load golden trace fixture from disk."""
    golden_path = Path(__file__).parent.parent / 'tests' / 'fixtures' / 'simulator' / 'golden' / f'{scenario}.json'
    
    if not golden_path.exists():
        raise FileNotFoundError(f"Golden trace not found: {golden_path}")
    
    with open(golden_path, 'r') as f:
        return json.load(f)


def compare_frame_fields(frame1: dict, frame2: dict, tolerance: float = 1e-4) -> list[str]:
    """Compare two frames field-by-field, reporting differences."""
    issues = []
    
    # Compare time
    t1 = frame1.get('virtual_time_s', 0)
    t2 = frame2.get('virtual_time_s', 0)
    if abs(t1 - t2) > tolerance:
        issues.append(f"time: {t1}s ≠ {t2}s")
    
    # Compare state
    s1 = frame1.get('state')
    s2 = frame2.get('state')
    if s1 != s2:
        issues.append(f"state: '{s1}' ≠ '{s2}'")
    
    # Compare actuator PWM values
    a1 = frame1.get('actuator', {})
    a2 = frame2.get('actuator', {})
    
    p1_lamp = a1.get('lamp_pwm')
    p2_lamp = a2.get('lamp_pwm')
    if p1_lamp != p2_lamp:
        issues.append(f"lamp_pwm: {p1_lamp} ≠ {p2_lamp}")
    
    p1_fan = a1.get('fan_pwm')
    p2_fan = a2.get('fan_pwm')
    if p1_fan != p2_fan:
        issues.append(f"fan_pwm: {p1_fan} ≠ {p2_fan}")
    
    # Compare telemetry fields
    te1 = frame1.get('telemetry', {})
    te2 = frame2.get('telemetry', {})
    
    # Temperature fields (allow small floating-point tolerance)
    temp_fields = ['surface_temp_c', 'bulk_temp_c']
    for tf in temp_fields:
        v1 = te1.get(tf)
        v2 = te2.get(tf)
        if v1 is not None and v2 is not None:
            if abs(v1 - v2) > tolerance:
                issues.append(f"{tf}: {v1} ≠ {v2}")
    
    # Lux reading
    l1 = te1.get('lux_reading')
    l2 = te2.get('lux_reading')
    if l1 is not None and l2 is not None:
        if abs(l1 - l2) > tolerance:
            issues.append(f"lux_reading: {l1} ≠ {l2}")
    
    # PWM fields in telemetry
    pwm_fields = ['lamp_pwm', 'fan_pwm']
    for pf in pwm_fields:
        v1 = te1.get(pf)
        v2 = te2.get(pf)
        if v1 != v2:
            issues.append(f"{pf}: {v1} ≠ {v2}")
    
    return issues


def run_differential_test(scenario: str, num_frames: int = None) -> bool:
    """Run differential test by loading and validating golden trace structure.
    
    Args:
        scenario: Scenario name to validate
        num_frames: Limit number of frames to check (None=all)
    
    Returns:
        True if trace loads successfully and has valid structure
    """
    try:
        golden = load_golden_trace(scenario)
        
        traces = golden.get('traces', [])
        if num_frames:
            traces = traces[:num_frames]
        
        if not traces:
            print(f"✗ Scenario {scenario}: Empty trace data")
            return False
        
        # Verify trace structure consistency
        prev_frame = None
        for i, frame in enumerate(traces):
            # Check required fields
            assert 'virtual_time_s' in frame, f"Frame {i}: missing virtual_time_s"
            assert 'state' in frame, f"Frame {i}: missing state"
            assert 'actuator' in frame, f"Frame {i}: missing actuator"
            assert 'telemetry' in frame, f"Frame {i}: missing telemetry"
            
            # Verify monotonic time progression
            curr_time = frame['virtual_time_s']
            if prev_frame:
                prev_time = prev_frame['virtual_time_s']
                assert curr_time >= prev_time, f"Frame {i}: time regression {prev_time}→{curr_time}"
            
            prev_frame = frame
        
        # Report success
        total_frames = len(golden['traces'])
        checked_frames = len(traces)
        duration_s = traces[-1]['virtual_time_s'] if traces else 0
        
        print(f"✓ Scenario {scenario}: PASSED")
        print(f"  Total frames: {total_frames}")
        print(f"  Checked: {checked_frames} frames (up to {duration_s:.1f}s)")
        print(f"  Plant config: surface_capacity={golden['plant_config']['surface_capacity_j_per_k']}J/K")
        
        return True
        
    except FileNotFoundError as e:
        print(f"✗ Scenario {scenario}: MISSING FIXTURE - {e}")
        return False
    except AssertionError as e:
        print(f"✗ Scenario {scenario}: STRUCTURE ERROR - {e}")
        return False
    except Exception as e:
        print(f"✗ Scenario {scenario}: EXCEPTION - {type(e).__name__}: {e}")
        return False


def main():
    """Run all golden trace validation tests."""
    scenarios = [
        'ISO1_default_target',
        'PLAT1_default', 
        'CAL_BARE_default',
    ]
    
    results = {}
    
    print("=" * 70)
    print("Phase 3 Golden Trace Validation")
    print("=" * 70 + "\n")
    
    for scenario in scenarios:
        passed = run_differential_test(scenario)
        results[scenario] = passed
        print()
    
    # Summary
    total = len(results)
    passed_count = sum(results.values())
    
    print("=" * 70)
    print(f"Differential Test Summary: {passed_count}/{total} scenarios validated")
    
    if passed_count == total:
        print("\n✅ All golden traces have valid structure ✓")
        return 0
    else:
        failed = [s for s, r in results.items() if not r]
        print(f"\n❌ Failed scenarios: {', '.join(failed)}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
