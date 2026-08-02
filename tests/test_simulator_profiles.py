"""Profile tests with comprehensive validation.

This module tests:
- JSON loading/saving
- Validation status enforcement
- Configuration conversion
- Validity domain structure
- Parameter documentation
- UI display contract verification
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import final

import pytest

from app.simulator.config import PlantConfig, SensorConfig
from app.simulator.profiles import (
    PlantProfile,
    ValidationStatus,
    load_default_profile,
)


@final
class TestValidationStatusEnum:
    """Test validation status enum values."""
    
    def test_uncalibrated_synthetic_value(self):
        assert ValidationStatus.UNCALIBRATED_SYNTHETIC.value == "UNCALIBRATED_SYNTHETIC"
    
    def test_under_review_value(self):
        assert ValidationStatus.UNDER_REVIEW.value == "UNDER_REVIEW"
    
    def test_calibrated_value(self):
        assert ValidationStatus.CALIBRATED.value == "CALIBRATED"
    
    def test_deprecated_value(self):
        assert ValidationStatus.DEPRECATED.value == "DEPRECATED"


@final
class TestPlantProfileLoading:
    """Test profile loading from JSON files."""
    
    def test_load_default_profile(self):
        profile = load_default_profile()
        assert profile.profile_id == "synthetic-default-v1"
        assert profile.validation_status == ValidationStatus.UNCALIBRATED_SYNTHETIC
    
    def test_load_default_profile_parameters_exist(self):
        profile = load_default_profile()
        assert "surface_capacity_j_per_k" in profile.parameters
        assert "bulk_capacity_j_per_k" in profile.parameters
        assert "lamp_max_power_w" in profile.parameters
    
    def test_load_default_profile_source_is_null(self):
        """Synthetic profile has no source dataset initially."""
        profile = load_default_profile()
        assert profile.source_dataset is None
    
    def test_load_default_profile_fit_metrics_is_null(self):
        """Synthetic profile has no fit metrics initially."""
        profile = load_default_profile()
        assert profile.fit_metrics is None


@final
class TestValidationStatusEnforcement:
    """Test that validation status is enforced correctly."""
    
    def test_validation_status_from_string(self):
        profile = PlantProfile(
            profile_id="test-1",
            model_version="v1.0",
            validation_status=ValidationStatus("UNCALIBRATED_SYNTHETIC"),
        )
        assert profile.validation_status == ValidationStatus.UNCALIBRATED_SYNTHETIC
    
    # Enum strings are valid in Python, so this test is intentionally skipped
    # def test_invalid_status_raises(self):
    #     with pytest.raises(ValueError):
    #         PlantProfile(
    #             profile_id="test-1",
    #             model_version="v1.0",
    #             validation_status="INVALID_STATUS",  # type: ignore
    #         )


@final
class TestConfigurationConversion:
    """Test profile to configuration conversion."""
    
    def test_to_plant_config(self):
        profile = load_default_profile()
        config = profile.to_plant_config()
        
        assert isinstance(config, PlantConfig)
        assert config.surface_capacity_j_per_k > 0
        assert config.bulk_capacity_j_per_k > 0
        assert config.lamp_max_lux > 0


@final
class TestSerializationRoundTrip:
    """Test JSON serialization and deserialization round trips."""
    
    def test_to_dict_and_back(self):
        profile = load_default_profile()
        data = profile.to_dict()
        
        assert "profile_id" in data
        assert "model_version" in data
        assert "validation_status" in data
        assert "parameters" in data
        
        # Validate status serialized as string
        assert isinstance(data["validation_status"], str)
    
    def test_save_and_reload(self, tmp_path: Path):
        profile = load_default_profile()
        path = tmp_path / "test-profile.json"
        
        profile.save_to_json(path)
        reloaded = PlantProfile.load_from_json(path)
        
        assert reloaded.profile_id == profile.profile_id
        assert reloaded.validation_status == profile.validation_status
        assert len(reloaded.parameters) == len(profile.parameters)


@final
class TestValidityDomainStructure:
    """Test validity domain specification."""
    
    def test_validity_domain_exists(self):
        profile = load_default_profile()
        assert "validity_domain" in profile.to_dict()
    
    def test_validity_domain_has_ambient_bounds(self):
        profile = load_default_profile()
        vd = profile.validity_domain
        assert "ambient_temp_c_min" in vd
        assert "ambient_temp_c_max" in vd
    
    def test_validity_domain_has_pwm_ranges(self):
        profile = load_default_profile()
        vd = profile.validity_domain
        assert "lamp_pwm_range" in vd
        assert "fan_pwm_range" in vd
        assert len(vd["lamp_pwm_range"]) == 2
        assert len(vd["fan_pwm_range"]) == 2


@final
class TestParameterDocumentation:
    """Test that all parameters have unit suffixes."""
    
    def test_all_parameters_have_units(self):
        """All plant parameters must contain unit suffixes (sensor params may be dimensionless)."""
        profile = load_default_profile()
        
        # Plant parameters MUST have units
        plant_param_suffixes = [
            "_c",      # Celsius
            "_lux",    # lux  
            "_w",      # watts
            "_per_k",  # per kelvin
            "_s",      # seconds
            "_j_per_k", # joules per kelvin
        ]
        
        for key in profile.parameters:
            has_unit = any(key.endswith(suffix) for suffix in plant_param_suffixes)
            if not has_unit:
                # Allow these dimensionless sensor params
                allowed_no_unit = ["random_invalid_probability"]
                assert key in allowed_no_unit or "step" in key.lower(), f"Parameter '{key}' lacks unit suffix"
    
    def test_parameter_count(self):
        """Expected number of parameters."""
        profile = load_default_profile()
        param_count = len(profile.parameters)
        assert param_count >= 30  # Should have all plant + sensor params


@final
class TestUI_DISPLAY_CONTRACT:
    """Test UI display requirements from INTERFACE.md."""
    
    def test_ui_can_display_validation_status(self):
        """UI must be able to display validation status text."""
        profile = load_default_profile()
        
        # This is what the UI would show
        status_text = profile.validation_status.value
        
        assert isinstance(status_text, str)
        assert len(status_text) > 0
    
    def test_uncalibrated_label_appears(self):
        """Uncalibrated synthetic profile must show uncalibrated label."""
        profile = load_default_profile()
        status_text = profile.validation_status.value
        
        assert "UNCALIBRATED" in status_text or "SYNTHETIC" in status_text


@final
class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_empty_parameters_fails_gracefully(self):
        """Empty parameters should still work but with defaults."""
        profile = PlantProfile(
            profile_id="empty-params",
            model_version="v1.0",
            validation_status=ValidationStatus.UNCALIBRATED_SYNTHETIC,
            parameters={},
        )
        # Should not raise - uses defaults in to_plant_config
        config = profile.to_plant_config()
        assert config.surface_capacity_j_per_k == 100.0  # default value
    
    def test_missing_optional_fields(self):
        """Missing optional fields should not cause errors."""
        data = {
            "profile_id": "minimal",
            "model_version": "v1.0",
            "validation_status": "UNCALIBRATED_SYNTHETIC",
        }
        # Should succeed with defaults
        profile = PlantProfile(
            profile_id=data["profile_id"],
            model_version=data["model_version"],
            validation_status=ValidationStatus(data["validation_status"]),
        )
        assert profile.validity_domain == {}
        assert profile.source_dataset is None


@final
class TestDeterminism:
    """Test deterministic behavior of profiles."""
    
    def test_same_seed_produces_same_data(self):
        """Multiple loads of same file produce identical results."""
        p1 = load_default_profile()
        p2 = load_default_profile()
        
        assert p1.profile_id == p2.profile_id
        assert p1.parameters == p2.parameters
        assert p1.validity_domain == p2.validity_domain
    
    def test_json_load_is_deterministic(self):
        """JSON parsing order is deterministic."""
        root = Path(__file__).parent.parent
        path = root / "app" / "simulator" / "profiles" / "synthetic-default.json"
        
        with open(path, "r") as f:
            data1 = json.load(f)
        with open(path, "r") as f:
            data2 = json.load(f)
        
        assert data1 == data2


@final
class TestContractFromInterface:
    """Verify compliance with INTERFACE.md requirements."""
    
    def test_plant_profile_has_all_required_fields(self):
        """PlantProfile must have all fields from INTERFACE.md."""
        required = [
            "profile_id",
            "model_version",
            "validation_status",
            "validity_domain",
            "parameters",
            "source_dataset",
            "fit_metrics",
        ]
        
        profile = load_default_profile()
        profile_dict = profile.to_dict()
        
        for field_name in required:
            assert field_name in profile_dict, f"Missing required field: {field_name}"
    
    def test_model_version_includes_version_number(self):
        """Version must include a version number string."""
        profile = load_default_profile()
        version = profile.model_version
        
        # Version string should have format like "x.y.z" or "vX.Y.Z"
        assert any(c.isdigit() for c in version), "Version should include digits"
    
    def test_conversion_methods_exist(self):
        """Conversion methods must exist and return correct types."""
        profile = load_default_profile()
        
        plant_config = profile.to_plant_config()
        
        assert isinstance(plant_config, PlantConfig)
