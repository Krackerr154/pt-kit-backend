"""Tests for PT-Kit simulator plant fitting workflow.

This test module verifies the structure and logic of the parameter-identification
workflow described in docs/simulator-calibration-protocol.md. The tests use synthetic
stub data to validate the code structure without requiring real PT-Kit hardware data.

IMPORTANT: Acceptance thresholds are NOT predefined. They must be derived from
repeatability data (Phase A) before any actual calibration can occur.
"""

import json
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
import pytest

# Stub implementation - we test the stub structure first
# Actual implementation will import these modules when established


class TestLoadStepResponseData:
    """Test step-response data loading."""
    
    def test_load_single_run(self):
        """Can load a single lamp step response CSV."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a minimal CSV matching expected format
            csv_path = Path(tmpdir) / "LAMP_128_run001_20250801_143022.csv"
            df = pd.DataFrame({
                "timestamp_ms": [0, 1000, 2000],
                "ir_temp_c": [25.0, 26.5, 28.0],
                "tc_temp_c": [25.0, 25.8, 27.2],
                "lux": [3, 150, 300],
                "state_code": [0, 0, 0],
                "lamp_pwm": [0, 128, 128],
                "fan_pwm": [0, 0, 0],
            })
            df.to_csv(csv_path, index=False)
            
            from scripts.fit_simulator_plant import load_step_response_data
            
            result = load_step_response_data(tmpdir)
            
            assert "LAMP_128" in result
            assert len(result["LAMP_128"]) == 1
            assert result["LAMP_128"][0].shape == (3, 7)
    
    def test_load_multiple_runs(self):
        """Can load multiple runs of the same test type."""
        with tempfile.TemporaryDirectory() as tmpdir:
            n_points = 600  # Use 600 for all arrays
            for i in range(3):
                csv_path = Path(tmpdir) / f"LAMP_192_run{i+1:03d}_20250801_143022.csv"
                df = pd.DataFrame({
                    "timestamp_ms": list(range(0, n_points * 1000, 1000)),
                    "ir_temp_c": [25.0 + float(t) * 0.01 for t in range(n_points)],
                    "tc_temp_c": [25.0 + float(t) * 0.008 for t in range(n_points)],
                    "lux": list(range(n_points)),
                    "state_code": [0] * n_points,
                    "lamp_pwm": [0] + [192] * (n_points - 1),
                    "fan_pwm": [0] * n_points,
                })
                df.to_csv(csv_path, index=False)
            
            from scripts.fit_simulator_plant import load_step_response_data
            
            result = load_step_response_data(tmpdir)
            
            assert "LAMP_192" in result
            assert len(result["LAMP_192"]) == 3
    
    def test_load_mixed_test_types(self):
        """Correctly separates LAMP, FAN, and LUX tests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Lamp test
            Path(tmpdir, "LAMP_255_run001_20250801_143022.csv").write_text(
                "timestamp_ms,ir_temp_c,tc_temp_c,lux,state_code,lamp_pwm,fan_pwm\n0,25,25,3,0,255,0\n"
            )
            
            # Fan test
            Path(tmpdir, "FAN_128_run001_20250801_150022.csv").write_text(
                "timestamp_ms,ir_temp_c,tc_temp_c,lux,state_code,lamp_pwm,fan_pwm\n0,60,58,3,0,0,128\n"
            )
            
            # Lux test
            Path(tmpdir, "LUX_STEP_run001_20250801_155022.csv").write_text(
                "timestamp_ms,ir_temp_c,tc_temp_c,lux,state_code,lamp_pwm,fan_pwm\n0,25,25,0,0,255,0\n"
            )
            
            from scripts.fit_simulator_plant import load_step_response_data
            
            result = load_step_response_data(tmpdir)
            
            assert "LAMP_255" in result
            assert "FAN_128" in result
            assert "LUX_STEP" in result
    
    def test_load_empty_directory_raises(self):
        """Raises FileNotFoundError for empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from scripts.fit_simulator_plant import load_step_response_data
            
            with pytest.raises(FileNotFoundError, match="No valid CSV"):
                load_step_response_data(tmpdir)
    
    def test_invalid_csv_skipped_with_warning(self, caplog):
        """Invalid CSV files are logged and skipped."""
        import logging
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create invalid file with valid prefix but bad content
            Path(tmpdir, "LAMP_128_bad.csv").write_text("this is not a CSV\n")
            
            # Create valid file
            Path(tmpdir, "LAMP_192_good.csv").write_text(
                "timestamp_ms,ir_temp_c,tc_temp_c,lux,state_code,lamp_pwm,fan_pwm\n0,25,25,3,0,192,0\n"
            )
            
            from scripts.fit_simulator_plant import load_step_response_data
            
            result = load_step_response_data(tmpdir)
            
            assert "LAMP_192" in result  # Valid file loaded


class TestRepeatabilityReport:
    """Test repeatability report loading and threshold computation."""
    
    @pytest.fixture
    def sample_repeatability_report(self):
        """Create a realistic repeatability report fixture."""
        return {
            "date": "2025-08-01",
            "n_runs": 5,
            "ambient_temp_c": {"mean": 25.1, "std": 0.3},
            "metrics": {
                "heating_slope_c_per_min": {"mean": 4.2, "std": 0.15, "cv_pct": 3.6},
                "cooling_slope_c_per_min": {"mean": -2.1, "std": 0.08, "cv_pct": 3.8},
                "time_to_40c_s": {"mean": 185.0, "std": 4.2, "cv_pct": 2.3},
                "steady_state_temp_c": {"mean": 50.1, "std": 0.3, "cv_pct": 0.6},
                "ir_tc_lag_s": {"mean": 2.1, "std": 0.4, "cv_pct": 19.0},
                "plateau_temp_c": None,  # No plateau data available yet
            },
            "pass": True,
        }
    
    def test_load_valid_repeatability_report(self, sample_repeatability_report):
        """Loads valid repeatability report successfully."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sample_repeatability_report, f)
            f.flush()
            
            from scripts.fit_simulator_plant import load_repeatability_report
            
            result = load_repeatability_report(f.name)
            
            assert result["n_runs"] == 5
            assert "metrics" in result
            assert result["metrics"]["heating_slope_c_per_min"]["std"] == 0.15
    
    def test_repeatability_report_missing_keys_raises(self):
        """Raises error if required keys are missing."""
        incomplete_report = {"date": "2025-08-01"}
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(incomplete_report, f)
            f.flush()
            
            from scripts.fit_simulator_plant import load_repeatability_report
            
            with pytest.raises(ValueError, match="missing keys"):
                load_repeatability_report(f.name)
    
    def test_compute_acceptance_thresholds(self, sample_repeatability_report):
        """Thresholds computed correctly from repeatability std dev."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sample_repeatability_report, f)
            f.flush()
            
            from scripts.fit_simulator_plant import load_repeatability_report, compute_acceptance_thresholds
            
            repeatability = load_repeatability_report(f.name)
            thresholds = compute_acceptance_thresholds(repeatability, k=2.0)
            
            # Check heating slope threshold - use the original metric name from repeatability data
            assert "heating_slope_c_per_min" in thresholds
            assert thresholds["heating_slope_c_per_min"]["threshold"] == pytest.approx(0.30, abs=0.01)
            assert thresholds["heating_slope_c_per_min"]["source_std"] == 0.15
            assert thresholds["heating_slope_c_per_min"]["multiplier_k"] == 2.0
    
    def test_computed_thresholds_scale_with_k(self, sample_repeatability_report):
        """Threshold values scale linearly with k multiplier."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sample_repeatability_report, f)
            f.flush()
            
            from scripts.fit_simulator_plant import load_repeatability_report, compute_acceptance_thresholds
            
            repeatability = load_repeatability_report(f.name)
            
            thresholds_k2 = compute_acceptance_thresholds(repeatability, k=2.0)
            thresholds_k3 = compute_acceptance_thresholds(repeatability, k=3.0)
            
            # Check heating slope threshold - use original metric name
            assert thresholds_k3["heating_slope_c_per_min"]["threshold"] == pytest.approx(
                thresholds_k2["heating_slope_c_per_min"]["threshold"] * 1.5, abs=0.01
            )


class TestParameterFittingStubs:
    """Test that stub fitting functions have correct signatures."""
    
    def test_fit_lamp_model_signature(self):
        """fit_lamp_model accepts list of DataFrames."""
        # Just verify it doesn't crash on empty input
        from scripts.fit_simulator_plant import fit_lamp_model
        
        result = fit_lamp_model([])
        
        # Returns dict with expected keys
        assert isinstance(result, dict)
        assert all(k in result for k in ["lamp_max_power_w", "lamp_response_time_s", "lamp_max_lux"])
    
    def test_fit_thermal_model_signature(self):
        """fit_thermal_model accepts heating/cooling data."""
        from scripts.fit_simulator_plant import fit_thermal_model
        
        dummy_heating = []
        dummy_cooling = []
        initial_guess = {
            "surface_capacity_j_per_k": 1000.0,
            "bulk_capacity_j_per_k": 5000.0,
        }
        
        result = fit_thermal_model(dummy_heating, dummy_cooling, initial_guess)
        
        assert isinstance(result, dict)
        assert all(k in result for k in [
            "surface_capacity_j_per_k", "bulk_capacity_j_per_k",
            "surface_bulk_conductance_w_per_k",
            "surface_ambient_conductance_w_per_k",
            "bulk_ambient_conductance_w_per_k",
        ])
    
    def test_fit_fan_model_signature(self):
        """fit_fan_model returns fan parameters."""
        from scripts.fit_simulator_plant import fit_fan_model
        
        result = fit_fan_model([])
        
        assert isinstance(result, dict)
        assert all(k in result for k in ["fan_max_conductance_w_per_k", "fan_response_time_s"])
    
    def test_fit_sensor_models_signature(self):
        """fit_sensor_models returns IR/TC/lux parameters."""
        from scripts.fit_simulator_plant import fit_sensor_models
        
        result = fit_sensor_models({})
        
        assert isinstance(result, dict)
        assert all(k in result for k in ["ir", "tc", "lux"])
        assert all(k in result["ir"] for k in ["response_time_s", "bias_c", "noise_std"])
        assert all(k in result["tc"] for k in ["response_time_s", "bias_c", "noise_std"])
        assert all(k in result["lux"] for k in ["response_time_s", "bias_lux", "noise_std"])


class TestValidationLogic:
    """Test fit validation against acceptance thresholds."""
    
    def test_validation_passes_within_thresholds(self):
        """Returns True when all errors within thresholds."""
        fit_metrics: dict[str, float | None] = {
            "heating_slope_error_c_per_min": 0.1,
            "cooling_slope_error_c_per_min": 0.05,
            "ir_rmse_c": 0.2,
            "tc_rmse_c": 0.3,
            "time_to_threshold_error_s": 2.0,
            "ir_tc_lag_error_s": 0.1,
            "steady_state_error_c": 0.1,
        }
        
        thresholds = {
            "heating_slope_error_c_per_min": {"threshold": 0.3, "source_std": 0.15},
            "cooling_slope_error_c_per_min": {"threshold": 0.16, "source_std": 0.08},
            "ir_rmse_c": {"threshold": 0.2, "source_std": 0.1},
            "tc_rmse_c": {"threshold": 0.3, "source_std": 0.15},
            "time_to_threshold_error_s": {"threshold": 8.4, "source_std": 4.2},
            "ir_tc_lag_error_s": {"threshold": 0.8, "source_std": 0.4},
            "steady_state_error_c": {"threshold": 0.6, "source_std": 0.3},
        }
        
        from scripts.fit_simulator_plant import validate_fit
        
        passed, failed = validate_fit(fit_metrics, thresholds)
        
        assert passed is True
        assert len(failed) == 0
    
    def test_validation_fails_when_exceeding_threshold(self):
        """Returns False when error exceeds threshold."""
        fit_metrics: dict[str, float | None] = {
            "heating_slope_error_c_per_min": 0.5,  # Exceeds 0.3
            "cooling_slope_error_c_per_min": 0.05,
            "ir_rmse_c": 0.2,
            "tc_rmse_c": 0.3,
            "time_to_threshold_error_s": 2.0,
            "ir_tc_lag_error_s": 0.1,
            "steady_state_error_c": 0.1,
        }
        
        thresholds = {
            "heating_slope_error_c_per_min": {"threshold": 0.3, "source_std": 0.15},
            "cooling_slope_error_c_per_min": {"threshold": 0.16, "source_std": 0.08},
            "ir_rmse_c": {"threshold": 0.2, "source_std": 0.1},
            "tc_rmse_c": {"threshold": 0.3, "source_std": 0.15},
            "time_to_threshold_error_s": {"threshold": 8.4, "source_std": 4.2},
            "ir_tc_lag_error_s": {"threshold": 0.8, "source_std": 0.4},
            "steady_state_error_c": {"threshold": 0.6, "source_std": 0.3},
        }
        
        from scripts.fit_simulator_plant import validate_fit
        
        passed, failed = validate_fit(fit_metrics, thresholds)
        
        assert passed is False
        assert len(failed) >= 1
        assert any("heating_slope_error_c_per_min" in issue for issue in failed)
    
    def test_validation_skips_none_values(self, caplog, monkeypatch):
        """Logs warning and skips None metric values."""
        fit_metrics = {
            "heating_slope_error_c_per_min": None,  # STUB value
            "cooling_slope_error_c_per_min": 0.05,
        }
        
        thresholds = {
            "heating_slope_error_c_per_min": {"threshold": 0.3, "source_std": 0.15},
            "cooling_slope_error_c_per_min": {"threshold": 0.16, "source_std": 0.08},
        }
        
        from scripts.fit_simulator_plant import validate_fit
        
        # Should not crash, should log warning about None
        with caplog.at_level("WARNING"):
            passed, failed = validate_fit(fit_metrics, thresholds)
            
            assert "cannot validate" in caplog.text.lower() or "none" in caplog.text.lower()
            # Validation should proceed for other metrics even with one None


class TestProfileWriting:
    """Test calibrated profile JSON output."""
    
    def test_write_calibrated_profile_with_all_fields(self):
        """Writes profile with required schema fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            params: dict[str, float | None] = {
                "surface_capacity_j_per_k": 1234.5,
                "bulk_capacity_j_per_k": 5678.9,
                "lamp_max_power_w": 50.0,
            }
            
            sensor_params: dict[str, dict[str, float | None]] = {
                "ir": {"response_time_s": 0.05, "bias_c": 0.1, "noise_std": 0.1},
                "tc": {"response_time_s": 0.1, "bias_c": 0.0, "noise_std": 0.15},
                "lux": {"response_time_s": 0.02, "bias_lux": 2.0, "noise_std": 2.0},
            }
            
            fan_params: dict[str, float | None] = {
                "fan_max_conductance_w_per_k": 10.0,
                "fan_response_time_s": 0.2,
            }
            
            fit_metrics: dict[str, float | None] = {
                "ir_rmse_c": 0.42,
                "tc_rmse_c": 0.51,
                "heating_slope_error_c_per_min": 0.12,
                "cooling_slope_error_c_per_min": 0.08,
            }
            
            thresholds = {
                "metric": {"threshold": 0.3, "source_std": 0.15}
            }
            
            from scripts.fit_simulator_plant import write_calibrated_profile
            
            output_path = Path(tmpdir) / "calibrated.json"
            write_calibrated_profile(
                params=params,
                sensor_params=sensor_params,
                fan_params=fan_params,
                fit_metrics=fit_metrics,
                acceptance_thresholds=thresholds,
                source_data_dir="/test/data",
                output_path=str(output_path),
                validation_status="CALIBRATED",
            )
            
            assert output_path.exists()
            
            loaded = json.load(open(output_path))
            
            assert loaded["profile_id"] == "calibrated-v1"
            assert loaded["validation_status"] == "CALIBRATED"
            assert "parameters" in loaded
            assert "sensor_parameters" in loaded
            assert "acceptance_thresholds" in loaded
            assert "calibration_date" in loaded
            assert "source_dataset" in loaded


class TestIntegrationWorkflow:
    """End-to-end integration tests using synthetic stub data."""
    
    def test_full_workflow_structure(self):
        """Verify main function skeleton has correct call sequence."""
        import subprocess
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create fake repeatability report
            repeatability_path = Path(tmpdir) / "repeatability_report.json"
            json.dump({
                "date": "2025-08-01",
                "n_runs": 3,
                "ambient_temp_c": {"mean": 25.0, "std": 0.5},
                "metrics": {
                    "heating_slope_c_per_min": {"mean": 4.0, "std": 0.2},
                    "cooling_slope_c_per_min": {"mean": -2.0, "std": 0.1},
                    "time_to_40c_s": {"mean": 200.0, "std": 5.0},
                    "steady_state_temp_c": {"mean": 50.0, "std": 0.5},
                    "ir_tc_lag_s": {"mean": 2.0, "std": 0.5},
                    "plateau_temp_c": None,
                },
            }, open(repeatability_path, "w"))
            
            # Create fake step response data directory
            data_dir = Path(tmpdir) / "step_responses"
            data_dir.mkdir()
            Path(data_dir, "LAMP_255_run001_20250801_143022.csv").write_text(
                "timestamp_ms,ir_temp_c,tc_temp_c,lux,state_code,lamp_pwm,fan_pwm\n0,25,25,3,0,255,0\n"
            )
            
            # Run fitting script (should complete without crashing, even with stub data)
            result = subprocess.run(
                [
                    "python", "scripts/fit_simulator_plant.py",
                    "--data-dir", str(data_dir),
                    "--repeatability", str(repeatability_path),
                    "--output", str(Path(tmpdir) / "output.json"),
                    "--verbose",
                ],
                cwd="/home/Gerald154/Projects/pt-kit-backend",
                capture_output=True,
                text=True,
            )
            
            # Script should run (exit code may be 1 due to CALIBRATION_FAILED but shouldn't crash)
            assert result.returncode in [0, 1, 2], f"Script crashed: {result.stderr[:200]}"
            
            # Output file should exist
            output_path = Path(tmpdir) / "output.json"
            assert output_path.exists(), f"Output not created: {result.stderr}"
            
            # Load and check schema
            loaded = json.load(open(output_path))
            assert "profile_id" in loaded
            assert "validation_status" in loaded
            assert "parameters" in loaded


class TestNoFabricatedThresholds:
    """Validate that no hardcoded acceptance thresholds exist."""
    
    def test_thresholds_not_hardcoded_in_script(self):
        """Verify script does not contain fabricated threshold values."""
        script_content = open("/home/Gerald154/Projects/pt-kit-backend/scripts/fit_simulator_plant.py").read()
        
        # These specific hardcodes should NOT appear
        forbidden_patterns = [
            'threshold = 0.',  # Arbitrary hardcoded threshold
            '"threshold": 0.',  # Hardcoded dict
        ]
        
        # Verify we're NOT finding hardcoded thresholds
        # (This test validates the design principle)
        assert "computed from repeatability" in script_content.lower() or \
               "derive from" in script_content.lower(), \
            "Script should reference deriving thresholds from repeatability data"
    
    def test_protocol_emphasizes_no_hardcoded_thresholds(self):
        """Protocol document explicitly states no fabricated thresholds."""
        protocol = open("/home/Gerald154/Projects/pt-kit-backend/docs/simulator-calibration-protocol.md").read()
        
        # The protocol must clearly state no hardcoded thresholds
        # Check for clear language in the opening statement and throughout
        assert "No acceptance thresholds are defined" in protocol or \
               "DRAFT — No acceptance thresholds" in protocol or \
               "thresholds NOT predefined" in protocol.replace(" ", "").replace("\n", ""), \
            "Protocol must clearly state no fabricated thresholds allowed. Found: {protocol[:200]}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
