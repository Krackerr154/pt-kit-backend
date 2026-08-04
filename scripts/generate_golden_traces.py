#!/usr/bin/env python3
"""Golden trace generator for Phase 3 controller modes.

Usage:
    python scripts/generate_golden_traces.py --scenario ISO1_default_target
    
Scenarios:
    ISO1_default_target     - Fixed-temperature mode with default parameters
    PLAT1_default           - Plateau mode with default parameters  
    CAL_BARE_default        - Bare board calibration sequence

Outputs traces to: tests/fixtures/simulator/golden/<scenario>.json
Uses fixed seed (42) for determinism.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def generate_iso1_trace(seed: int = 42) -> dict[str, Any]:
    """Generate golden trace for ISO1 fixed-temperature mode."""
    from app.simulator.plant import PlantConfig, ThermalPlant
    from app.simulator.controller_implementation import (
        PTKitControllerIntegration, 
        ControllerState,
        ExperimentConfig,
        PlantState,
        ExtendedTelemetry,
    )
    from app.simulator.clock import VirtualClock
    from app.simulator.config import SensorConfig
    
    # Setup deterministic simulation
    plant_config = PlantConfig(
        surface_capacity_j_per_k=100.0,
        bulk_capacity_j_per_k=200.0,
        surface_bulk_conductance_w_per_k=5.0,
        surface_ambient_conductance_w_per_k=2.0,
        bulk_ambient_conductance_w_per_k=1.0,
        lamp_max_power_w=50.0,
        lamp_response_time_s=0.5,
        lamp_max_lux=10000.0,
        fan_max_conductance_w_per_k=10.0,
        fan_response_time_s=0.2,
        ambient_temp_c=25.0,
        max_substep_s=0.1,
    )
    
    sensor_config = SensorConfig()
    
    plant = ThermalPlant(plant_config)
    controller = PTKitControllerIntegration(sensor_config)
    clock = VirtualClock(seed=seed)
    
    # Create ISO1 command
    iso1_cmd = ExperimentConfig(
        experiment_mode="ISO1",
        target_temp_c=37.0,
        hold_duration_s=60.0,
        tolerance_c=0.5,
        qualification_cycles=3,
        max_temp_c=45.0,
        interval_s=0.1,
        sensor_selection=0,  # IR
        ramp_rate_limit_c_per_s=None,
    )
    
    # Execute and record traces
    traces: list[dict] = []
    plant_state = plant.state
    
    # Initial IDLE state
    traces.append({
        "virtual_time_s": 0.0,
        "state": "IDLE",
        "actuator": {"lamp_pwm": 0, "fan_pwm": 0},
        "telemetry": {
            "frame_number": 0,
            "state_code": 0,
            "surface_temp_c": round(plant_state.surface_temp_c, 3),
            "bulk_temp_c": round(plant_state.bulk_temp_c, 3),
            "lamp_pwm": 0,
            "fan_pwm": 0,
            "lux_reading": round(plant_state.lamp_output_lux, 1),
            "target_temp_c": None,
            "hold_time_s": None,
            "cycle_count": 0,
            "elapsed_s": 0.0,
            "setpoint_error_c": 0.0,
            "qualification_passed": False,
            "plateau_status": None,
            "calibration_result": None,
            "supervisor_abort": False,
            "run_id": None,
        },
        "side_channel": None,
    })
    
    # Apply command and run simulation
    controller.apply_experiment_config(iso1_cmd)
    
    max_steps = 5000  # Safety limit
    step = 0
    
    while controller.state != ControllerState.DONE and step < max_steps:
        clock.tick()
        dt_s = clock.dt_s()
        
        # Get current actuator commands
        lamp_pwm = controller.lamp_pwm
        fan_pwm = controller.fan_pwm
        
        # Step plant
        plant.step(lamp_pwm, fan_pwm, dt_s)
        plant_state = plant.state
        
        # Tick controller
        controller.tick(dt_s)
        
        # Record frame if telemetry available
        if hasattr(controller, '_last_telemetry') and controller._last_telemetry:
            telemetry = controller._last_telemetry
            traces.append({
                "virtual_time_s": round(clock.virtual_time_s(), 3),
                "state": controller.state.name,
                "actuator": {"lamp_pwm": lamp_pwm, "fan_pwm": fan_pwm},
                "telemetry": {
                    "frame_number": telemetry.frame_number,
                    "state_code": telemetry.state_code,
                    "surface_temp_c": round(telemetry.surface_temp_c, 3),
                    "bulk_temp_c": round(telemetry.bulk_temp_c, 3),
                    "lamp_pwm": telemetry.lamp_pwm,
                    "fan_pwm": telemetry.fan_pwm,
                    "lux_reading": round(telemetry.lux_reading, 1),
                    "target_temp_c": telemetry.target_temp_c,
                    "hold_time_s": telemetry.hold_time_s,
                    "cycle_count": telemetry.cycle_count,
                    "elapsed_s": round(telemetry.elapsed_s, 3),
                    "setpoint_error_c": round(telemetry.setpoint_error_c, 3),
                    "qualification_passed": telemetry.qualification_passed,
                    "plateau_status": telemetry.plateau_status,
                    "calibration_result": telemetry.calibration_result,
                    "supervisor_abort": telemetry.supervisor_abort,
                    "run_id": telemetry.run_id,
                },
                "side_channel": None,
            })
        
        step += 1
    
    return {
        "scenario": "ISO1_default_target",
        "seed": seed,
        "plant_config": {
            "surface_capacity_j_per_k": plant_config.surface_capacity_j_per_k,
            "bulk_capacity_j_per_k": plant_config.bulk_capacity_j_per_k,
            "surface_bulk_conductance_w_per_k": plant_config.surface_bulk_conductance_w_per_k,
            "surface_ambient_conductance_w_per_k": plant_config.surface_ambient_conductance_w_per_k,
            "bulk_ambient_conductance_w_per_k": plant_config.bulk_ambient_conductance_w_per_k,
            "lamp_max_power_w": plant_config.lamp_max_power_w,
            "lamp_response_time_s": plant_config.lamp_response_time_s,
            "lamp_max_lux": plant_config.lamp_max_lux,
            "fan_max_conductance_w_per_k": plant_config.fan_max_conductance_w_per_k,
            "fan_response_time_s": plant_config.fan_response_time_s,
            "ambient_temp_c": plant_config.ambient_temp_c,
            "max_substep_s": plant_config.max_substep_s,
        },
        "command": {
            "mode": "ISO1",
            "target_temp_c": 37.0,
            "hold_duration_s": 60.0,
            "tolerance_c": 0.5,
            "qualification_cycles": 3,
            "max_temp_c": 45.0,
            "interval_s": 0.1,
            "sensor_selection": 0,
            "ramp_rate_limit_c_per_s": None,
        },
        "traces": traces,
    }


def main():
    parser = argparse.ArgumentParser(description='Generate golden traces for Phase 3 scenarios')
    parser.add_argument('--scenario', required=True, choices=['ISO1_default_target', 'PLAT1_default', 'CAL_BARE_default'],
                       help='Scenario name to generate')
    parser.add_argument('--seed', type=int, default=42, help='Random seed (default: 42)')
    parser.add_argument('--output', '-o', help='Output file path (default: tests/fixtures/simulator/golden/<scenario>.json)')
    
    args = parser.parse_args()
    
    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = Path(__file__).parent.parent / 'tests' / 'fixtures' / 'simulator' / 'golden' / f'{args.scenario}.json'
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    print(f"Generating {args.scenario} trace (seed={args.seed})...")
    
    if args.scenario == 'ISO1_default_target':
        trace_data = generate_iso1_trace(seed=args.seed)
    else:
        print(f"⚠️  Scenario '{args.scenario}' not yet implemented - using placeholder")
        trace_data = {
            "scenario": args.scenario,
            "seed": args.seed,
            "note": "Placeholder - requires implementation",
            "traces": [],
        }
    
    # Write to file
    with open(output_path, 'w') as f:
        json.dump(trace_data, f, indent=2)
    
    print(f"✓ Written: {output_path} ({output_path.stat().st_size // 1024} KB)")
    print(f"  Traces: {len(trace_data['traces'])} frames")


if __name__ == '__main__':
    main()
