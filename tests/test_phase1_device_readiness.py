import pytest

from app import main
from app.main import ExperimentConfig


def test_start_is_rejected_without_fresh_device_telemetry(monkeypatch):
    monkeypatch.setattr(main, "last_device_telemetry_at", None)
    config = ExperimentConfig(operator_name="op", sample_name="sample")

    with pytest.raises(main.HTTPException) as exc:
        main.start_experiment(config)

    assert exc.value.status_code == 409
    assert "ESP32" in exc.value.detail


def test_start_is_rejected_when_device_telemetry_is_stale(monkeypatch):
    monkeypatch.setattr(main, "last_device_telemetry_at", main.time.time() - 11)
    config = ExperimentConfig(operator_name="op", sample_name="sample")

    with pytest.raises(main.HTTPException) as exc:
        main.start_experiment(config)

    assert exc.value.status_code == 409


def test_calibration_is_rejected_without_fresh_device_telemetry(monkeypatch):
    monkeypatch.setattr(main, "last_device_telemetry_at", None)

    with pytest.raises(main.HTTPException) as exc:
        main.trigger_calibrate_tape("bare")

    assert exc.value.status_code == 409


def test_device_readiness_window(monkeypatch):
    monkeypatch.setattr(main, "last_device_telemetry_at", main.time.time() - 5)
    assert main.device_is_ready() is True
    monkeypatch.setattr(main, "last_device_telemetry_at", main.time.time() - 10.1)
    assert main.device_is_ready() is False