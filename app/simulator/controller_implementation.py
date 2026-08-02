"""
Plant Controller Integration - Full Experiment Modes and Termination Semantics

Integrates ThermalPlant + Controller state machine with support for:
- ISO1 fixed-temp mode with qualification cycles
- PLAT1 plateau mode with slope/range validation
- Calibration modes (CAL_BARE, CAL_TAPE, CAL_FULL)
- Proper termination semantics (STOP, ABORT, SUPERVISOR_ABORT)
- ExtendedTelemetry emission (17-field)
- Side-channel message handling
"""

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional, Dict, List, Any
import random
import json


class ControllerState(IntEnum):
    """Controller state machine matching firmware exactly (0-15)."""
    IDLE = 0
    STARTING = 1
    SENSOR_CHECK = 2
    CALIBRATING = 3
    WARMUP = 4
    STABILIZING = 5
    HEATING = 6
    HOLDING = 7
    COOLING = 8
    FINISHED = 9
    DONE = 10
    ABORTED = 11
    ERROR = 15
    
    # Custom extended states for different experiments
    QUALIFY_CYCLE = 12  # ISO1 qualification cycle
    PLATEAU_VALIDATE = 13  # PLAT1 plateau validation


class SupervisionFlag(IntEnum):
    """Supervision abort flags (separate from firmware ABORT)."""
    NONE = 0
    STOP_REQUESTED = 1
    ABORT_REQUESTED = 2
    SUPERVISOR_ABORT = 3
    INVALID_SENSOR = 4
    SAFE_OUTPUT = 5
    ERROR = 6


@dataclass
class PlantState:
    """Thermal plant state - matches interface spec."""
    surface_temp_c: float
    bulk_temp_c: float
    lamp_output_lux: float
    time_s: float
    
    @classmethod
    def default(cls) -> 'PlantState':
        return cls(surface_temp_c=25.0, bulk_temp_c=25.0, lamp_output_lux=0.0, time_s=0.0)


@dataclass
class ExtendedTelemetry:
    """Extended telemetry frame with 17 fields."""
    timestamp_s: float
    controller_state: int
    supervision_flag: int
    surface_temp_c: float
    bulk_temp_c: float
    lamp_output_lux: float
    target_temp_c: Optional[float] = None
    setpoint_temp_c: Optional[float] = None
    hold_temp_c: Optional[float] = None
    current_cycle: Optional[int] = None
    total_cycles: Optional[int] = None
    elapsed_hold_s: Optional[float] = None
    max_slope_c_per_min: Optional[float] = None
    min_slope_c_per_min: Optional[float] = None
    average_slope_c_per_min: Optional[float] = None
    cycle_elapsed_s: Optional[float] = None
    side_channel_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'timestamp_s': self.timestamp_s,
            'controller_state': self.controller_state,
            'supervision_flag': self.supervision_flag,
            'surface_temp_c': self.surface_temp_c,
            'bulk_temp_c': self.bulk_temp_c,
            'lamp_output_lux': self.lamp_output_lux,
            'target_temp_c': self.target_temp_c,
            'setpoint_temp_c': self.setpoint_temp_c,
            'hold_temp_c': self.hold_temp_c,
            'current_cycle': self.current_cycle,
            'total_cycles': self.total_cycles,
            'elapsed_hold_s': self.elapsed_hold_s,
            'max_slope_c_per_min': self.max_slope_c_per_min,
            'min_slope_c_per_min': self.min_slope_c_per_min,
            'average_slope_c_per_min': self.average_slope_c_per_min,
            'cycle_elapsed_s': self.cycle_elapsed_s,
            'side_channel_message': self.side_channel_message,
        }
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict())


@dataclass 
class ExperimentConfig:
    """Experiment configuration for different modes."""
    mode: str  # ISO1, PLAT1, CAL_BARE, CAL_TAPE, CAL_FULL
    target_temp_c: float
    duration_s: float
    warmup_time_s: float = 30.0
    stabilization_tolerance_c: float = 0.5
    max_slope_c_per_min: float = 2.0
    min_slope_c_per_min: float = -2.0
    temp_range_lower_c: float = 0.0
    temp_range_upper_c: float = 0.0
    qualification_cycles: int = 1
    cycle_duration_s: float = 60.0
    hold_duration_s: float = 120.0


class ThermalPlantSimulator:
    """Simplified thermal plant simulator."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.state = PlantState.default()
        self.lamp_efficiency = config.get('lamp_efficiency', 0.7)
        self.thermal_mass = config.get('thermal_mass', 100.0)  # J/°C
        self.heating_power_w = config.get('heating_power_w', 50.0)
        self.cooling_rate_w = config.get('cooling_rate_w', 10.0)  # W per °C above ambient
        self.ambient_temp_c = config.get('ambient_temp_c', 25.0)
        self.time_elapsed_s = 0.0
        self.invalid_sensor = False
        
    def step(self, dt_s: float, lamp_on: bool) -> PlantState:
        """Advance plant simulation by dt seconds."""
        if self.invalid_sensor:
            # Return invalid/safe output when sensor is invalid
            return PlantState(
                surface_temp_c=-273.15,  # Absolute zero = clearly invalid
                bulk_temp_c=self.state.bulk_temp_c,
                lamp_output_lux=0.0,
                time_s=self.time_elapsed_s
            )
        
        # Lamp output calculation
        if lamp_on:
            lux_base = self.heating_power_w * self.lamp_efficiency * 10
            self.state.lamp_output_lux = lux_base
        else:
            self.state.lamp_output_lux *= 0.9  # Gradual decay
            
        # Thermal dynamics
        heat_loss_w = self.cooling_rate_w * (self.state.surface_temp_c - self.ambient_temp_c)
        net_heat_w = (self.heating_power_w if lamp_on else 0.0) - heat_loss_w
        
        # Temperature change: dT = P * dt / C
        dT = (net_heat_w * dt_s) / self.thermal_mass
        self.state.surface_temp_c += dT
        self.state.bulk_temp_c += dT * 0.8  # Bulk lags surface
        
        self.time_elapsed_s += dt_s
        self.state.time_s = self.time_elapsed_s
        
        return PlantState(
            surface_temp_c=self.state.surface_temp_c,
            bulk_temp_c=self.state.bulk_temp_c,
            lamp_output_lux=self.state.lamp_output_lux,
            time_s=self.time_elapsed_s
        )
    
    def set_invalid_sensor(self, invalid: bool):
        """Set sensor validity flag."""
        self.invalid_sensor = invalid


class PTKitControllerIntegration:
    """
    PTKit Controller Integration with full experiment modes.
    
    Integrates ThermalPlant + Controller state machine supporting:
    - ISO1 fixed-temp mode with qualification cycles
    - PLAT1 plateau mode with slope/range validation  
    - Calibration modes (CAL_BARE, CAL_TAPE, CAL_FULL)
    - Proper termination semantics (STOP, ABORT, SUPERVISOR_ABORT)
    - ExtendedTelemetry emission (17-field frames)
    - Side-channel message polling
    """
    
    def __init__(self, plant_config: Dict[str, Any], seed: Optional[int] = None):
        """Initialize controller with plant configuration."""
        self.plant = ThermalPlantSimulator(plant_config)
        self.state = ControllerState.IDLE
        self.old_state = ControllerState.IDLE
        self.supervision = SupervisionFlag.NONE
        self.telemetry_buffer: List[ExtendedTelemetry] = []
        
        # Experiment-specific tracking
        self.experiment_config: Optional[ExperimentConfig] = None
        self.cycle_count = 0
        self.start_time_s = 0.0
        self.last_temp_samples: List[float] = []
        self.slope_history: List[float] = []
        
        # Command queue
        self.command_queue: List[str] = []
        self.queue_index = 0
        
        # Random for deterministic behavior
        self.rng = random.Random(seed)
        
    def send_command(self, cmd: str):
        """Send command to controller (idempotent)."""
        self.command_queue.append(cmd)
        
    def _poll_commands(self) -> Optional[str]:
        """Poll next command from queue."""
        if self.queue_index < len(self.command_queue):
            cmd = self.command_queue[self.queue_index]
            self.queue_index += 1
            return cmd
        return None
    
    def _handle_command(self, cmd: str):
        """Process a single command."""
        cmd_upper = cmd.upper().strip()
        
        if cmd_upper == "STOP":
            # Idempotent STOP - sets supervision but does NOT trigger firmware ABORT
            if self.state not in [ControllerState.ABORTED, ControllerState.ERROR]:
                self.supervision = SupervisionFlag.STOP_REQUESTED
                # Transition to IDLE gracefully
                if self.state in [ControllerState.HEATING, ControllerState.HOLDING, 
                                 ControllerState.WARMUP, ControllerState.COOLING,
                                 ControllerState.QUALIFY_CYCLE, ControllerState.PLATEAU_VALIDATE]:
                    self.state = ControllerState.COOLING
                    # Emit one final telemetry before transition
                    telety = self._emit_telemetry(side_msg="STOP")
                    self.telemetry_buffer.append(telety)
                    
        elif cmd_upper == "ABORT":
            # Firmware ABORT - severe error, irreversible
            self.state = ControllerState.ABORTED
            self.supervision = SupervisionFlag.ABORT_REQUESTED
            
        elif cmd_upper == "SUPERVISOR_ABORT":
            # Supervisor-level abort (separate from firmware ABORT).
            # Always lands in ABORTED — including from IDLE — so the distinction
            # STOP != ABORT != SUPERVISOR_ABORT holds in every starting state.
            self.supervision = SupervisionFlag.SUPERVISOR_ABORT
            self.state = ControllerState.ABORTED
                
        elif cmd_upper.startswith("ISO1"):
            # Parse ISO1 command: ISO1<temp><duration>[<cycles>]
            # Format: ISO1 + 2-digit temp + 3-4 digit duration + optional cycles
            # Examples:
            #   ISO180300 = 80°C for 300s (default 1 cycle)
            #   ISO1803003 = 80°C for 300s, 3 cycles  
            #   ISO1856002 = 85°C for 600s, 2 cycles
            try:
                remaining = ""
                
                # Parse temperature (2 digits)
                remaining = cmd_upper[4:]  # Everything after "ISO1"
                
                if len(remaining) < 2:
                    raise ValueError("Insufficient data for temperature")
                    
                temp_str = remaining[:2]
                temp = float(temp_str)
                remaining = remaining[2:]
                
                # Parse duration (3-4 digits at start of remaining)
                import re
                match = re.match(r'(\d{3,4})', remaining)
                if match:
                    duration_str = match.group(1)
                    duration = int(duration_str)
                    remaining = remaining[len(duration_str):]
                else:
                    raise ValueError("No valid duration found")
                
                # Parse cycles if present (remaining should be digits)
                cycles = 1
                if remaining and remaining.isdigit() and len(remaining) > 0:
                    cycles = int(remaining)
                
                self.experiment_config = ExperimentConfig(
                    mode="ISO1",
                    target_temp_c=temp,
                    duration_s=duration,
                    qualification_cycles=cycles,
                    cycle_duration_s=60.0,
                    hold_duration_s=duration
                )
                self._start_experiment()
                
            except (ValueError, IndexError) as e:
                print(f"Iso1 parse error: {e}, remaining='{remaining}'")
                self.supervision = SupervisionFlag.ERROR
                
        elif cmd_upper.startswith("PLAT1"):
            # Parse PLAT1 command: PLAT1<temp><tolerance><slope>
            # Example: PLAT18520200 means plateaus around 85°C ±0.2°C, slope ±0.2°C/min
            try:
                temp = float(cmd_upper[5:8])
                tolerance = float(cmd_upper[8:11]) / 1000.0
                slope_max = float(cmd_upper[11:14]) / 1000.0
                slope_min = -slope_max
                
                self.experiment_config = ExperimentConfig(
                    mode="PLAT1",
                    target_temp_c=temp,
                    duration_s=self.experiment_config.duration_s if self.experiment_config else 300.0,
                    stabilization_tolerance_c=tolerance,
                    max_slope_c_per_min=slope_max,
                    min_slope_c_per_min=slope_min,
                    temp_range_lower_c=temp - tolerance,
                    temp_range_upper_c=temp + tolerance,
                    hold_duration_s=300.0
                )
                self._start_experiment()
                
            except (ValueError, IndexError):
                self.supervision = SupervisionFlag.ERROR
                
        elif cmd_upper == "CAL_BARE" or cmd_upper == "CALBARE":
            # Start calibration bare metal sequence
            self.experiment_config = ExperimentConfig(
                mode="CAL_BARE",
                target_temp_c=150.0,
                duration_s=120.0
            )
            self._start_calibration()
            
        elif cmd_upper == "CAL_TAPE" or cmd_upper == "CALTAPE":
            # Start calibration tape sequence
            self.experiment_config = ExperimentConfig(
                mode="CAL_TAPE",
                target_temp_c=120.0,
                duration_s=90.0
            )
            if self.experiment_config and self.experiment_config.mode == "CAL_BARE":
                # Complete CAL_BARE → CAL_TAPE sequence
                self._complete_calibration()
            self._start_calibration()
            
        elif cmd_upper == "CAL_FULL":
            # Full calibration sequence (bare + tape)
            self.experiment_config = ExperimentConfig(
                mode="CAL_FULL",
                target_temp_c=150.0,
                duration_s=210.0
            )
            self._start_full_calibration()
            
        elif cmd_upper == "STATUS" or cmd_upper == "READOUT":
            # Just emit current telemetry
            pass
            
        elif cmd_upper.startswith("ERR"):
            # Simulate error condition
            self.supervision = SupervisionFlag.INVALID_SENSOR
            
        elif cmd_upper == "MAXLUX":
            # Max lux warning side channel
            pass
            
    def _start_experiment(self):
        """Start experiment with initial transitions."""
        self.state = ControllerState.STARTING
        self.cycle_count = 0
        self.start_time_s = self.plant.time_elapsed_s
        self.last_temp_samples = []
        self.slope_history = []
        
    def _start_calibration(self):
        """Start calibration phase."""
        self.state = ControllerState.CALIBRATING
        
    def _complete_calibration(self):
        """Complete current calibration phase."""
        if self.experiment_config and self.experiment_config.mode == "CAL_BARE":
            self.experiment_config.mode = "CAL_TAPE"
            self.experiment_config.target_temp_c = 120.0
            
    def _start_full_calibration(self):
        """Start full calibration sequence."""
        self.state = ControllerState.CALIBRATING
        self.experiment_config.mode = "CAL_FULL"
        
    def _compute_slope(self) -> float:
        """Compute temperature slope over last 30 seconds."""
        current_time = self.plant.time_elapsed_s
        window_s = 30.0
        
        # Get temps within window
        if len(self.last_temp_samples) < 2:
            return 0.0
            
        time_diff_s = max(current_time - window_s, 1.0) / 60.0  # Convert to minutes
        temp_diff_c = self.last_temp_samples[-1] - self.last_temp_samples[0]
        
        return temp_diff_c / max(time_diff_s, 0.1)
    
    def _thermostat_lamp_on(self) -> bool:
        """
        Bang-bang thermostat: keep the lamp on only while below setpoint.

        Without this the lamp stays permanently on and the plant runs away to its
        thermal equilibrium, so _check_stabilization() (|T - target| <= tol) can
        never be satisfied and ISO1/PLAT1 runs stall in STABILIZING forever.
        Hysteresis is half the stabilization tolerance to avoid chatter.
        """
        if not self.experiment_config:
            return True

        target = self.experiment_config.target_temp_c
        hysteresis = max(self.experiment_config.stabilization_tolerance_c * 0.5, 0.05)
        return self.plant.state.surface_temp_c < (target - hysteresis)

    def _check_stabilization(self) -> bool:
        """Check if temperature is stabilized within tolerance."""
        if not self.experiment_config:
            return False
            
        tol = self.experiment_config.stabilization_tolerance_c
        current = self.plant.state.surface_temp_c
        target = self.experiment_config.target_temp_c
        
        return abs(current - target) <= tol
    
    def _check_plateau_validity(self) -> tuple:
        """Check plateau mode slope and range validation."""
        if not self.experiment_config:
            return False, 0.0, 0.0, 0.0
            
        current = self.plant.state.surface_temp_c
        lower = self.experiment_config.temp_range_lower_c
        upper = self.experiment_config.temp_range_upper_c
        
        in_range = lower <= current <= upper
        slope = self._compute_slope()
        
        slope_ok = self.experiment_config.min_slope_c_per_min <= slope <= self.experiment_config.max_slope_c_per_min
        
        return in_range and slope_ok, slope, lower, upper
    
    def _should_complete_iso1_cycle(self) -> bool:
        """Check if ISO1 qualification cycle should complete."""
        if not self.experiment_config:
            return False
            
        elapsed = self.plant.time_elapsed_s - self.start_time_s
        return elapsed >= self.experiment_config.cycle_duration_s
        
    def _should_complete_hold(self) -> bool:
        """Check if hold phase should complete."""
        if not self.experiment_config:
            return False
            
        # Track hold start separately
        if hasattr(self, '_hold_start_s'):
            elapsed = self.plant.time_elapsed_s - self._hold_start_s
            return elapsed >= self.experiment_config.hold_duration_s
        return False
        
    def _transition_to(self, new_state: ControllerState):
        """Transition to new state."""
        self.old_state = self.state
        self.state = new_state
        
    def _emit_telemetry(self, side_msg: Optional[str] = None) -> ExtendedTelemetry:
        """Emit ExtendedTelemetry frame (17 fields)."""
        msg = side_msg
        if not msg and self.supervision != SupervisionFlag.NONE:
            if self.supervision == SupervisionFlag.STOP_REQUESTED:
                msg = "STOP"
            elif self.supervision == SupervisionFlag.ABORT_REQUESTED:
                msg = "ABORT"
            elif self.supervision == SupervisionFlag.SUPERVISOR_ABORT:
                msg = "SUPERVISOR_ABORT"
            elif self.supervision == SupervisionFlag.INVALID_SENSOR:
                msg = "ERR"
                
        elapsed_hold = None
        if self.state == ControllerState.HOLDING and hasattr(self, '_hold_start_s'):
            elapsed_hold = self.plant.time_elapsed_s - self._hold_start_s
            
        return ExtendedTelemetry(
            timestamp_s=self.plant.time_elapsed_s,
            controller_state=int(self.state),
            supervision_flag=int(self.supervision),
            surface_temp_c=self.plant.state.surface_temp_c,
            bulk_temp_c=self.plant.state.bulk_temp_c,
            lamp_output_lux=self.plant.state.lamp_output_lux,
            target_temp_c=self.experiment_config.target_temp_c if self.experiment_config else None,
            setpoint_temp_c=self.experiment_config.target_temp_c if self.experiment_config else None,
            hold_temp_c=self.experiment_config.target_temp_c if self.experiment_config and self.state == ControllerState.HOLDING else None,
            current_cycle=self.cycle_count if self.state == ControllerState.QUALIFY_CYCLE else None,
            total_cycles=self.experiment_config.qualification_cycles if self.experiment_config else None,
            elapsed_hold_s=elapsed_hold,
            max_slope_c_per_min=self.experiment_config.max_slope_c_per_min if self.experiment_config and self.state == ControllerState.PLATEAU_VALIDATE else None,
            min_slope_c_per_min=self.experiment_config.min_slope_c_per_min if self.experiment_config and self.state == ControllerState.PLATEAU_VALIDATE else None,
            average_slope_c_per_min=self._compute_slope() if self.state == ControllerState.PLATEAU_VALIDATE else None,
            cycle_elapsed_s=(self.plant.time_elapsed_s - self.start_time_s)
                            if self.state == ControllerState.QUALIFY_CYCLE else None,
            side_channel_message=msg,
        )
    
    def step(self, dt_s: float = 1.0) -> Optional[ExtendedTelemetry]:
        """Execute one simulation step."""
        # Poll commands first
        cmd = self._poll_commands()
        if cmd:
            self._handle_command(cmd)
            
        # Check supervision conditions
        if self.supervision == SupervisionFlag.INVALID_SENSOR:
            self.plant.set_invalid_sensor(True)
            # Reflect the invalid reading in plant state immediately, even in states
            # (e.g. IDLE) that do not advance the plant, so telemetry reports the
            # safe sentinel value rather than a stale valid temperature.
            self.plant.state.surface_temp_c = -273.15
            self.plant.state.lamp_output_lux = 0.0
            
        # State machine logic
        if self.state == ControllerState.IDLE:
            pass  # Wait for command
            
        elif self.state == ControllerState.STARTING:
            self._transition_to(ControllerState.SENSOR_CHECK)
            
        elif self.state == ControllerState.SENSOR_CHECK:
            # Quick sensor validation
            self._transition_to(ControllerState.WARMUP)
            
        elif self.state == ControllerState.CALIBRATING:
            # Calibration heating
            plant_state = self.plant.step(dt_s, lamp_on=True)
            
            if plant_state.surface_temp_c >= self.experiment_config.target_temp_c * 0.9:
                self._transition_to(ControllerState.HOLDING)
                self._hold_start_s = self.plant.time_elapsed_s
                
        elif self.state == ControllerState.WARMUP:
            plant_state = self.plant.step(dt_s, lamp_on=True)
            
            # Track temp samples for slope calculation
            self.last_temp_samples.append(plant_state.surface_temp_c)
            if len(self.last_temp_samples) > 100:
                self.last_temp_samples = self.last_temp_samples[-100:]
                
            if plant_state.surface_temp_c >= self.experiment_config.target_temp_c * 0.5:
                self._transition_to(ControllerState.STABILIZING)
                
        elif self.state == ControllerState.STABILIZING:
            plant_state = self.plant.step(dt_s, lamp_on=self._thermostat_lamp_on())
            
            # Track temp samples for slope calculation
            self.last_temp_samples.append(plant_state.surface_temp_c)
            if len(self.last_temp_samples) > 100:
                self.last_temp_samples = self.last_temp_samples[-100:]
                
            if self._check_stabilization():
                if self.experiment_config.mode == "ISO1":
                    self._transition_to(ControllerState.QUALIFY_CYCLE)
                elif self.experiment_config.mode == "PLAT1":
                    self._transition_to(ControllerState.PLATEAU_VALIDATE)
                else:
                    self._transition_to(ControllerState.HOLDING)
                    self._hold_start_s = self.plant.time_elapsed_s
                    
        elif self.state == ControllerState.HEATING:
            plant_state = self.plant.step(dt_s, lamp_on=True)
            
            if plant_state.surface_temp_c >= self.experiment_config.target_temp_c:
                self._transition_to(ControllerState.HOLDING)
                self._hold_start_s = self.plant.time_elapsed_s
                
        elif self.state == ControllerState.HOLDING:
            plant_state = self.plant.step(dt_s, lamp_on=self._thermostat_lamp_on())
            
            if self._should_complete_hold():
                if self.experiment_config.mode == "ISO1" and self.cycle_count < self.experiment_config.qualification_cycles - 1:
                    # Complete cycle, start next
                    self.cycle_count += 1
                    self.start_time_s = self.plant.time_elapsed_s
                    self._transition_to(ControllerState.WARMUP)
                elif self.experiment_config.mode == "CAL_TAPE":
                    self._transition_to(ControllerState.DONE)
                elif self.experiment_config.mode in ("ISO1", "CAL_FULL"):
                    # Completed all qualification cycles / full calibration sequence
                    self._transition_to(ControllerState.DONE)
                else:
                    self._transition_to(ControllerState.FINISHED)
                    
        elif self.state == ControllerState.QUALIFY_CYCLE:
            plant_state = self.plant.step(dt_s, lamp_on=self._thermostat_lamp_on())
            
            # Track temp samples for slope calculation
            self.last_temp_samples.append(plant_state.surface_temp_c)
            if len(self.last_temp_samples) > 100:
                self.last_temp_samples = self.last_temp_samples[-100:]
                
            if self._should_complete_iso1_cycle():
                self.cycle_count += 1
                
                if self.cycle_count >= self.experiment_config.qualification_cycles:
                    self._transition_to(ControllerState.HOLDING)
                    self._hold_start_s = self.plant.time_elapsed_s
                else:
                    self.start_time_s = self.plant.time_elapsed_s
                    
        elif self.state == ControllerState.PLATEAU_VALIDATE:
            plant_state = self.plant.step(dt_s, lamp_on=self._thermostat_lamp_on())
            
            # Track temp samples for slope calculation
            self.last_temp_samples.append(plant_state.surface_temp_c)
            if len(self.last_temp_samples) > 100:
                self.last_temp_samples = self.last_temp_samples[-100:]
                
            valid, slope, _, _ = self._check_plateau_validity()
            
            if valid and self._should_complete_hold():
                self._transition_to(ControllerState.DONE)
                
        elif self.state == ControllerState.COOLING:
            plant_state = self.plant.step(dt_s, lamp_on=False)
            
            # Exit cooling once we are back near ambient. The threshold must be
            # ambient-aware: a fixed `target * 0.3` can sit BELOW ambient (e.g.
            # 80°C * 0.3 = 24°C vs 25°C ambient), which the plant can never reach,
            # leaving the controller stuck in COOLING forever.
            cooldown_threshold = max(
                self.experiment_config.target_temp_c * 0.3,
                self.plant.ambient_temp_c + 1.0,
            )
            if plant_state.surface_temp_c < cooldown_threshold:
                self._transition_to(ControllerState.IDLE)
                self.supervision = SupervisionFlag.NONE
                
        elif self.state in [ControllerState.FINISHED, ControllerState.DONE]:
            plant_state = self.plant.step(dt_s, lamp_on=False)
            
            # Repeat final state until reset
            self._transition_to(self.state)
            
        elif self.state in [ControllerState.ABORTED, ControllerState.ERROR]:
            # Stay aborted - requires explicit reset
            plant_state = self.plant.step(dt_s, lamp_on=False)
            
        # Emit telemetry
        telemetry = self._emit_telemetry()
        self.telemetry_buffer.append(telemetry)
        
        return telemetry
    
    def reset(self):
        """Reset controller to initial state."""
        self.state = ControllerState.IDLE
        self.old_state = ControllerState.IDLE
        self.supervision = SupervisionFlag.NONE
        self.experiment_config = None
        self.cycle_count = 0
        self.command_queue = []
        self.queue_index = 0
        self.telemetry_buffer = []
        self.plant = ThermalPlantSimulator({})
        
    def get_telemetry_buffer(self) -> List[ExtendedTelemetry]:
        """Get all emitted telemetry frames."""
        return self.telemetry_buffer.copy()
    
    def get_golden_trace_json(self, scenario: str) -> str:
        """Generate golden trace JSON format."""
        trace_data = {
            "scenario": scenario,
            "seed": self.rng.randint(0, 2**31-1),
            "plant_config": self.plant.config,
            "command": "; ".join(self.command_queue) if self.command_queue else "",
            "traces": [telem.to_dict() for telem in self.telemetry_buffer]
        }
        
        return json.dumps(trace_data, indent=2)
