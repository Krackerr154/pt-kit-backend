"""Wire protocol definitions shared by the PT-Kit backend and controllers."""
from enum import Enum


class ExperimentMode(str, Enum):
    NORMAL_CYCLIC = "NORMAL_CYCLIC"
    FIXED_TEMPERATURE = "FIXED_TEMPERATURE"
    NATURAL_PLATEAU = "NATURAL_PLATEAU"


class PostPlateauMode(str, Enum):
    PASSIVE = "PASSIVE"
    REGULATED = "REGULATED"


STATE_LABELS = [
    "IDLE", "PRE_HEAT", "HEATING", "COOLING", "STABILIZING", "DONE",
    "CAL_BARE", "CAL_TAPE", "CAL_FULL", "ISO_RAMP", "ISO_QUALIFY",
    "ISO_HOLD", "PLATEAU_HEATING", "PLATEAU_CONFIRM", "PLATEAU_HOLD", "ABORTED",
]


def serialize_normal_command(duration, cycles, max_temp, interval, target_lux):
    return f"SET:{duration}:{cycles}:{max_temp}:{interval}:{target_lux}"


def serialize_fixed_command(target_temp_c, hold_seconds, tolerance_c, qualification_seconds,
                            max_temp_c, log_interval_s, sensor, ramp_rate_c_per_min):
    return f"ISO1:{target_temp_c}:{hold_seconds}:{tolerance_c}:{qualification_seconds}:{max_temp_c}:{log_interval_s}:{sensor}:{ramp_rate_c_per_min}"


def serialize_plateau_command(target_lux, hold_seconds, window_seconds, max_abs_slope_c_per_min,
                              max_peak_to_peak_c, confirmation_seconds, max_discovery_seconds,
                              max_temp_c, log_interval_s, sensor,
                              post_plateau_mode=PostPlateauMode.PASSIVE):
    post = post_plateau_mode.value if isinstance(post_plateau_mode, Enum) else post_plateau_mode
    return f"PLAT1:{target_lux}:{hold_seconds}:{window_seconds}:{max_abs_slope_c_per_min}:{max_peak_to_peak_c}:{confirmation_seconds}:{max_discovery_seconds}:{max_temp_c}:{log_interval_s}:{sensor}:{post}"


def parse_telemetry(csv_line):
    """Parse legacy telemetry (first seven values; optional eighth retained) or 17-field extension."""
    parts = [part.strip() for part in csv_line.split(",")]
    if len(parts) < 7:
        raise ValueError("telemetry requires at least seven fields")
    row = dict(total_time=int(parts[0]), phase_time=int(parts[1]), cycle_num=int(parts[2]),
               state_code=int(parts[3]), ir_temp=float(parts[4]), tc_temp=float(parts[5]),
               current_lux=float(parts[6]), mode=None, control_temp=None, temp_setpoint=None,
               temp_error=None, lamp_pwm=None, hold_wall_elapsed_s=None,
               hold_qualified_elapsed_s=None, qualified=None, detected_plateau_temp=None)
    # Field 8 is the unchanged legacy/reserved slot. Extension starts after it.
    if len(parts) >= 17:
        row.update(mode=parts[8] or None, control_temp=float(parts[9]), temp_setpoint=float(parts[10]),
                   temp_error=float(parts[11]), lamp_pwm=float(parts[12]),
                   hold_wall_elapsed_s=int(parts[13]), hold_qualified_elapsed_s=int(parts[14]),
                   qualified=parts[15].lower() in ("1", "true", "yes"),
                   detected_plateau_temp=float(parts[16]))
    return row
