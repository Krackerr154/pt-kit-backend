import pytest
from pydantic import ValidationError

from app.protocol import (
    ExperimentMode, PostPlateauMode, STATE_LABELS, parse_telemetry,
    serialize_fixed_command, serialize_normal_command, serialize_plateau_command,
)


def test_state_codes_are_additive():
    assert STATE_LABELS[0] == "IDLE"
    assert STATE_LABELS[8] == "CAL_FULL"
    assert STATE_LABELS[9:16] == ["ISO_RAMP", "ISO_QUALIFY", "ISO_HOLD", "PLATEAU_HEATING", "PLATEAU_CONFIRM", "PLATEAU_HOLD", "ABORTED"]


def test_legacy_command_exact():
    assert serialize_normal_command(60, 5, 80.0, 1, 38000.0) == "SET:60:5:80.0:1:38000.0"


def test_fixed_command():
    assert serialize_fixed_command(45.0, 600, 0.5, 30, 80.0, 1, "IR", 5.0) == "ISO1:45.0:600:0.5:30:80.0:1:IR:5.0"


def test_plateau_command_defaults_passive():
    assert serialize_plateau_command(38000.0, 600, 120, 0.2, 0.5, 30, 1800, 80.0, 1, "IR", PostPlateauMode.PASSIVE) == "PLAT1:38000.0:600:120:0.2:0.5:30:1800:80.0:1:IR:PASSIVE"


def test_legacy_eight_field_telemetry():
    row = parse_telemetry("10,2,1,3,31.2,30.5,1234,ignored")
    assert row["current_lux"] == 1234.0
    assert row["mode"] is None


def test_extended_telemetry():
    row = parse_telemetry("10,2,1,11,31.2,30.5,1234,x,FIXED_TEMPERATURE,31.2,32,0.8,127,90,75,true,44.1")
    assert row["mode"] == "FIXED_TEMPERATURE"
    assert row["qualified"] is True
    assert row["detected_plateau_temp"] == 44.1


def test_bad_telemetry_rejected():
    with pytest.raises(ValueError):
        parse_telemetry("1,2")


def test_modes_values():
    assert ExperimentMode.NORMAL_CYCLIC.value == "NORMAL_CYCLIC"
    assert ExperimentMode.NATURAL_PLATEAU.value == "NATURAL_PLATEAU"
