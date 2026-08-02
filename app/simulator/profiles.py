"""Plant profiles with validation status and parameter tracking.

This module defines:
- PlantProfile: structured profile data with validation status
- Default synthetic profile for uncalibrated simulation
- Profile loading/saving with JSON persistence
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .config import PlantConfig


class ValidationStatus(str, Enum):
    """Model validation status levels."""
    
    UNCALIBRATED_SYNTHETIC = "UNCALIBRATED_SYNTHETIC"
    """Uncalibrated synthetic model - not fitted to real data."""
    
    UNDER_REVIEW = "UNDER_REVIEW"
    """Fitted but pending additional validation."""
    
    CALIBRATED = "CALIBRATED"
    """Validated against acceptance criteria."""
    
    DEPRECATED = "DEPRECATED"
    """No longer recommended for use."""


@dataclass
class PlantProfile:
    """Complete plant sensor profile with validation metadata.
    
    Attributes:
        profile_id: Unique identifier for this profile version
        model_version: Model equation/version string
        validation_status: Current validation status
        validity_domain: Operating range specifications
        parameters: All model parameters with units
        source_dataset: Reference to dataset used for fitting (if any)
        fit_metrics: Statistical metrics from fitting (if any)
    """
    profile_id: str
    model_version: str
    validation_status: ValidationStatus
    validity_domain: dict[str, Any] = field(default_factory=dict)
    parameters: dict[str, float] = field(default_factory=dict)
    source_dataset: str | None = None
    fit_metrics: dict[str, float] | None = None
    
    def to_plant_config(self) -> PlantConfig:
        """Convert profile to PlantConfig instance."""
        p = self.parameters
        
        return PlantConfig(
            surface_capacity_j_per_k=p.get("surface_capacity_j_per_k", 100.0),
            bulk_capacity_j_per_k=p.get("bulk_capacity_j_per_k", 200.0),
            surface_bulk_conductance_w_per_k=p.get("surface_bulk_conductance_w_per_k", 5.0),
            surface_ambient_conductance_w_per_k=p.get("surface_ambient_conductance_w_per_k", 2.0),
            bulk_ambient_conductance_w_per_k=p.get("bulk_ambient_conductance_w_per_k", 1.0),
            lamp_max_power_w=p.get("lamp_max_power_w", 50.0),
            lamp_response_time_s=p.get("lamp_response_time_s", 0.5),
            lamp_max_lux=p.get("lamp_max_lux", 10000.0),
            fan_max_conductance_w_per_k=p.get("fan_max_conductance_w_per_k", 10.0),
            fan_response_time_s=p.get("fan_response_time_s", 0.2),
            ambient_temp_c=p.get("ambient_temp_c", 25.0),
            max_substep_s=p.get("max_substep_s", 0.1),
        )
    
    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON export."""
        d = asdict(self)
        # Convert enum to string
        d["validation_status"] = self.validation_status.value
        return d
    
    def save_to_json(self, path: Path) -> None:
        """Save profile to JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
    
    @classmethod
    def load_from_json(cls, path: Path) -> PlantProfile:
        """Load profile from JSON file."""
        with open(path, "r") as f:
            data = json.load(f)
        
        return cls(
            profile_id=data["profile_id"],
            model_version=data["model_version"],
            validation_status=ValidationStatus(data["validation_status"]),
            validity_domain=data.get("validity_domain", {}),
            parameters=data.get("parameters", {}),
            source_dataset=data.get("source_dataset"),
            fit_metrics=data.get("fit_metrics"),
        )


def load_default_profile() -> PlantProfile:
    """Load the default synthetic uncalibrated profile."""
    root = Path(__file__).parent
    profile_path = root / "profiles" / "synthetic-default.json"
    return PlantProfile.load_from_json(profile_path)


__all__ = [
    "PlantProfile",
    "ValidationStatus", 
    "load_default_profile",
]
