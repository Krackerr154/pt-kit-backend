import pytest
from pydantic import ValidationError

from app.main import ExperimentConfig
from app.protocol import ExperimentMode, IlluminationMode, PostPlateauMode


def test_legacy_body_defaults_to_normal():
    model = ExperimentConfig(operator_name="op", sample_name="sample")
    assert model.mode == ExperimentMode.NORMAL_CYCLIC
    assert model.illumination_mode == IlluminationMode.TARGET_LUX
    assert model.duration == 60


def test_max_output_has_no_fake_target_lux():
    model = ExperimentConfig(
        operator_name="op", sample_name="sample",
        illumination_mode="MAX_OUTPUT", target_lux=999999,
    )
    assert model.illumination_mode == IlluminationMode.MAX_OUTPUT
    assert model.target_lux is None


def test_fixed_temperature_normalizes_legacy_illumination_fields():
    model = ExperimentConfig(
        operator_name="op", sample_name="sample", mode="FIXED_TEMPERATURE",
        target_temperature=45, hold_duration_s=60, temperature_tolerance=.5,
        qualification_dwell_s=10, ramp_rate=5,
    )
    assert model.illumination_mode == IlluminationMode.TEMPERATURE_CONTROLLED
    assert model.target_lux is None


def test_fixed_temperature_rejects_max_output():
    with pytest.raises(ValidationError):
        ExperimentConfig(
            operator_name="op", sample_name="sample", mode="FIXED_TEMPERATURE",
            illumination_mode="MAX_OUTPUT", target_temperature=45,
            hold_duration_s=60, temperature_tolerance=.5,
            qualification_dwell_s=10, ramp_rate=5,
        )


def test_natural_plateau_rejects_zero_target_lux():
    with pytest.raises(ValidationError):
        ExperimentConfig(
            operator_name="op", sample_name="sample", mode="NATURAL_PLATEAU",
            target_lux=0, hold_duration_s=60, plateau_window_s=30,
            plateau_max_slope=.2, plateau_max_range=.5,
            plateau_confirmation_s=10, plateau_max_discovery_s=300,
        )


@pytest.mark.parametrize("window", [2, 31])
def test_natural_plateau_rejects_window_outside_physical_capacity(window):
    with pytest.raises(ValidationError, match="between 3 and 30 seconds"):
        ExperimentConfig(operator_name="op", sample_name="sample", mode="NATURAL_PLATEAU",
                         target_lux=38000, hold_duration_s=60, plateau_window_s=window,
                         plateau_max_slope=.2, plateau_max_range=.5,
                         plateau_confirmation_s=10, plateau_max_discovery_s=300)


def test_protocol_integer_limits_are_validated_before_persistence():
    with pytest.raises(ValidationError):
        ExperimentConfig(operator_name="op", sample_name="sample", interval=32768)


def test_mode_fields_validate_additively():
    model = ExperimentConfig(operator_name="op", sample_name="sample", mode="NATURAL_PLATEAU",
                             hold_duration_s=60, plateau_window_s=30, plateau_max_slope=.2,
                             plateau_max_range=.5, plateau_confirmation_s=10,
                             plateau_max_discovery_s=600)
    assert model.post_plateau_mode == PostPlateauMode.PASSIVE


def test_plateau_discovery_firmware_limit():
    with pytest.raises(ValidationError):
        ExperimentConfig(operator_name="op", sample_name="sample", mode="NATURAL_PLATEAU",
                         hold_duration_s=60, plateau_window_s=30, plateau_max_slope=.2,
                         plateau_max_range=.5, plateau_confirmation_s=10,
                         plateau_max_discovery_s=6501)
