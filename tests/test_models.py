from app.main import ExperimentConfig
from app.protocol import ExperimentMode, PostPlateauMode


def test_legacy_body_defaults_to_normal():
    model = ExperimentConfig(operator_name="op", sample_name="sample")
    assert model.mode == ExperimentMode.NORMAL_CYCLIC
    assert model.duration == 60


def test_mode_fields_validate_additively():
    model = ExperimentConfig(operator_name="op", sample_name="sample", mode="NATURAL_PLATEAU",
                             hold_duration_s=60, plateau_window_s=30, plateau_max_slope=.2,
                             plateau_max_range=.5, plateau_confirmation_s=10,
                             plateau_max_discovery_s=600)
    assert model.post_plateau_mode == PostPlateauMode.PASSIVE
