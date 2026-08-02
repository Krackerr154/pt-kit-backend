"""Profile management core for plant simulation system.

This module provides the core functionality for managing plant profiles,
including parameter validation, sensor configuration, and profile persistence.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Annotated
import json
import shutil


@dataclass
class PlantParameters:
    """Plant growth parameters with validated constraints."""
    
    # Thermal properties
    ambient_temp_c: float = field(default=25.0)
    surface_thermal_mass_j_k: float = field(default=500.0)
    bulk_thermal_mass_j_k: float = field(default=2000.0)
    surface_to_bulk_thermal_conductance_w_k: float = field(default=10.0)
    
    # Optical properties
    lamp_efficiency_pct: float = field(default=35.0)
    lux_to_power_conversion: float = field(default=0.01)
    
    # Dynamics parameters
    max_lamp_power_w: float = field(default=100.0)
    max_fan_rpm: float = field(default=5000.0)
    lamp_response_time_s: float = field(default=0.1)
    fan_response_time_s: float = field(default=0.5)
    
    def validate(self) -> Tuple[bool, List[str]]:
        """Validate parameter values against physical constraints.
        
        Returns:
            Tuple of (is_valid, list_of_error_messages)
        """
        errors = []
        
        # Validate temperatures
        if not (0 <= self.ambient_temp_c <= 100):
            errors.append(f"Ambient temperature must be 0-100°C, got {self.ambient_temp_c}")
        
        # Validate thermal masses are positive
        if self.surface_thermal_mass_j_k <= 0:
            errors.append("Surface thermal mass must be > 0")
        
        if self.bulk_thermal_mass_j_k <= 0:
            errors.append("Bulk thermal mass must be > 0")
        
        # Validate thermal conductance is positive
        if self.surface_to_bulk_thermal_conductance_w_k <= 0:
            errors.append("Thermal conductance must be > 0")
        
        # Validate lamp efficiency
        if not (0 <= self.lamp_efficiency_pct <= 100):
            errors.append(f"Lamp efficiency must be 0-100%, got {self.lamp_efficiency_pct}%")
        
        # Validate all dynamic parameters are positive
        if self.max_lamp_power_w <= 0:
            errors.append("Max lamp power must be > 0")
            
        if self.max_fan_rpm <= 0:
            errors.append("Max fan RPM must be > 0")
            
        if self.lamp_response_time_s <= 0:
            errors.append("Lamp response time must be > 0")
            
        if self.fan_response_time_s <= 0:
            errors.append("Fan response time must be > 0")
        
        return len(errors) == 0, errors


@dataclass
class SensorConfig:
    """Sensor calibration and noise parameters."""
    
    # Temperature sensors
    ir_temp_offset_c: float = field(default=0.0)
    tc_temp_offset_c: float = field(default=0.0)
    temp_noise_sigma: float = field(default=0.1)
    
    # Lux sensor
    lux_offset: int = field(default=0)
    lux_gain: float = field(default=1.0)
    
    # Sampling parameters
    update_interval_s: float = field(default=0.5)
    smoothing_window: int = field(default=5)
    
    def validate(self) -> Tuple[bool, List[str]]:
        """Validate sensor configuration values.
        
        Returns:
            Tuple of (is_valid, list_of_error_messages)
        """
        errors = []
        
        if self.lux_gain <= 0:
            errors.append("Lux gain must be > 0")
        
        if self.temp_noise_sigma < 0:
            errors.append("Temperature noise sigma cannot be negative")
        
        return len(errors) == 0, errors
    
    @staticmethod
    def _bump_version(version: str) -> str:
        """Increment semantic version string."""
        parts = version.split('.')
        if len(parts) != 3:
            raise ValueError(f"Invalid version format: {version}")
        
        major, minor, patch = map(int, parts)
        patch += 1
        
        if patch >= 1000:
            patch = 0
            minor += 1
            
        if minor >= 1000:
            minor = 0
            major += 1
            
        if major >= 1000:
            raise ValueError(f"Version bump would exceed maximum: {version}")
            
        return f"{major}.{minor}.{patch}"


@dataclass
class PlantProfile:
    """Complete plant configuration with validation status.

    Attributes:
        name: Profile name (required, unique identifier)
        description: Brief description of the profile
        created_at: Timestamp when profile was created
        updated_at: Timestamp of last modification
        version: Semantic version string (MAJOR.MINOR.PATCH)
        plant_params: Plant growth parameters
        sensor_config: Sensor calibration settings
        is_validated: Whether profile has passed all validations
        validation_errors: List of validation error messages
        author: Profile author name (optional)
        tags: List of tags for categorization (optional)
    """
    
    name: str
    description: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    version: str = "1.0.0"
    
    plant_params: PlantParameters = field(default_factory=PlantParameters)
    sensor_config: SensorConfig = field(default_factory=SensorConfig)
    
    is_validated: bool = False
    validation_errors: List[str] = field(default_factory=list)
    
    author: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    
    def validate(self) -> Tuple[bool, List[str]]:
        """Validate all parameters against physical constraints.
        
        Returns:
            Tuple of (is_valid, list_of_error_messages)
        """
        errors = []
        
        # Validate temperatures are within bounds
        if not (0 <= self.plant_params.ambient_temp_c <= 100):
            errors.append(f"Ambient temperature must be 0-100°C, got {self.plant_params.ambient_temp_c}")
        
        # Validate thermal masses are positive
        if self.plant_params.surface_thermal_mass_j_k <= 0:
            errors.append("Surface thermal mass must be > 0")
        
        if self.plant_params.bulk_thermal_mass_j_k <= 0:
            errors.append("Bulk thermal mass must be > 0")
        
        # Validate thermal conductance is positive
        if self.plant_params.surface_to_bulk_thermal_conductance_w_k <= 0:
            errors.append("Thermal conductance must be > 0")
        
        # Validate lamp efficiency is reasonable
        if not (0 <= self.plant_params.lamp_efficiency_pct <= 100):
            errors.append(f"Lamp efficiency must be 0-100%, got {self.plant_params.lamp_efficiency_pct}%")
        
        # Validate all dynamic parameters are positive
        if self.plant_params.max_lamp_power_w <= 0:
            errors.append("Max lamp power must be > 0")
            
        if self.plant_params.max_fan_rpm <= 0:
            errors.append("Max fan RPM must be > 0")
            
        if self.plant_params.lamp_response_time_s <= 0:
            errors.append("Lamp response time must be > 0")
            
        if self.plant_params.fan_response_time_s <= 0:
            errors.append("Fan response time must be > 0")
        
        # Validate sensor configurations
        if abs(self.sensor_config.ir_temp_offset_c) > 10:
            errors.append(f"IR sensor offset exceeds ±10°C limit: {self.sensor_config.ir_temp_offset_c}")
            
        if abs(self.sensor_config.tc_temp_offset_c) > 10:
            errors.append(f"TC sensor offset exceeds ±10°C limit: {self.sensor_config.tc_temp_offset_c}")
            
        if self.sensor_config.lux_gain <= 0:
            errors.append("Lux gain must be > 0")
        
        # Check thermal feasibility (not just validity)
        ratio = self.plant_params.surface_thermal_mass_j_k / self.plant_params.bulk_thermal_mass_j_k
        
        if ratio > 5:
            errors.append(f"Surface/bulk thermal mass ratio too high ({ratio:.2f}), may cause slow response")
        elif ratio < 0.1:
            errors.append(f"Surface/bulk thermal mass ratio too low ({ratio:.2f}), rapid fluctuations expected")
        
        # Set validation status
        self.is_validated = len(errors) == 0
        self.validation_errors = errors
        
        return self.is_validated, errors
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize profile to dictionary for JSON storage."""
        return {
            'name': self.name,
            'description': self.description,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'version': self.version,
            'plant_params': {
                'ambient_temp_c': self.plant_params.ambient_temp_c,
                'surface_thermal_mass_j_k': self.plant_params.surface_thermal_mass_j_k,
                'bulk_thermal_mass_j_k': self.plant_params.bulk_thermal_mass_j_k,
                'surface_to_bulk_thermal_conductance_w_k': self.plant_params.surface_to_bulk_thermal_conductance_w_k,
                'lamp_efficiency_pct': self.plant_params.lamp_efficiency_pct,
                'lux_to_power_conversion': self.plant_params.lux_to_power_conversion,
                'max_lamp_power_w': self.plant_params.max_lamp_power_w,
                'max_fan_rpm': self.plant_params.max_fan_rpm,
                'lamp_response_time_s': self.plant_params.lamp_response_time_s,
                'fan_response_time_s': self.plant_params.fan_response_time_s,
            },
            'sensor_config': {
                'ir_temp_offset_c': self.sensor_config.ir_temp_offset_c,
                'tc_temp_offset_c': self.sensor_config.tc_temp_offset_c,
                'temp_noise_sigma': self.sensor_config.temp_noise_sigma,
                'lux_offset': self.sensor_config.lux_offset,
                'lux_gain': self.sensor_config.lux_gain,
                'update_interval_s': self.sensor_config.update_interval_s,
                'smoothing_window': self.sensor_config.smoothing_window,
            },
            'is_validated': self.is_validated,
            'validation_errors': self.validation_errors,
            'author': self.author,
            'tags': self.tags,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PlantProfile':
        """Deserialize profile from dictionary."""
        return cls(
            name=data['name'],
            description=data.get('description', ''),
            created_at=datetime.fromisoformat(data['created_at']),
            updated_at=datetime.fromisoformat(data.get('updated_at', datetime.now().isoformat())),
            version=data.get('version', '1.0.0'),
            plant_params=PlantParameters(**data['plant_params']),
            sensor_config=SensorConfig(**data['sensor_config']),
            is_validated=data.get('is_validated', False),
            validation_errors=data.get('validation_errors', []),
            author=data.get('author'),
            tags=data.get('tags', []),
        )


@dataclass
class ProfileMetadata:
    """Minimal metadata for profile listing."""
    
    name: str
    version: str
    created_at: datetime
    updated_at: datetime
    author: Optional[str]
    tags: List[str]
    is_validated: bool
    description: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            'name': self.name,
            'version': self.version,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'author': self.author,
            'tags': self.tags,
            'is_validated': self.is_validated,
            'description': self.description,
        }


class ProfileRegistry:
    """Central registry for plant profiles with CRUD operations.
    
    Provides persistent storage using JSON files in a user-specific directory.
    Thread-safe for concurrent read operations.
    """
    
    def __init__(self, storage_path: Optional[Path] = None):
        """Initialize profile registry.
        
        Args:
            storage_path: Directory path for storing profile files.
                         Defaults to ~/.pt-kit/profiles
        """
        if storage_path is None:
            self.storage_path = Path.home() / '.pt-kit' / 'profiles'
        else:
            self.storage_path = Path(storage_path).expanduser()
        
        self._profiles: Dict[str, PlantProfile] = {}
        self._history: Dict[str, List[Dict[str, Any]]] = {}
        
        # Ensure storage directory exists
        self.storage_path.mkdir(parents=True, exist_ok=True)
    
    def load_profile(self, name: str) -> Optional[PlantProfile]:
        """Load profile from JSON file.
        
        Args:
            name: Profile name (filename without .json extension)
            
        Returns:
            PlantProfile instance if found, None otherwise
        """
        file_path = self.storage_path / f"{name}.json"
        
        if not file_path.exists():
            return None
        
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            profile = PlantProfile.from_dict(data)
            self._profiles[name] = profile
            
            return profile
            
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            print(f"Error loading profile {name}: {e}")
            return None
    
    def save_profile(self, profile: PlantProfile) -> bool:
        """Save profile to JSON file after validation.
        
        Args:
            profile: PlantProfile instance to save
            
        Returns:
            True if saved successfully, raises ValidationError if invalid
        """
        # Auto-validate before saving
        is_valid, errors = profile.validate()
        
        if not is_valid:
            from dataclasses import fields
            valid_fields = [f.name for f in fields(profile)]
            raise ValueError(
                f"Cannot save invalid profile '{profile.name}':\n" +
                "\n".join(f"  - {error}" for error in errors)
            )
        
        # Update timestamp and version
        profile.updated_at = datetime.now()
        
        file_path = self.storage_path / f"{profile.name}.json"
        
        try:
            with open(file_path, 'w') as f:
                json.dump(profile.to_dict(), f, indent=2, default=str)
            
            # Record in history
            self._record_history(
                profile.name, 
                "SAVE", 
                f"Saved version {profile.version}"
            )
            
            # Cache in memory
            self._profiles[profile.name] = profile
            
            return True
            
        except IOError as e:
            print(f"Error saving profile {profile.name}: {e}")
            return False
    
    def delete_profile(self, name: str, force: bool = False) -> bool:
        """Delete profile from storage.
        
        Args:
            name: Profile name to delete
            force: If True, delete even if profile is in-memory cache only
            
        Returns:
            True if deleted successfully, False otherwise
        """
        file_path = self.storage_path / f"{name}.json"
        
        if not file_path.exists() and name not in self._profiles:
            return False
        
        try:
            if file_path.exists():
                file_path.unlink()
            
            if name in self._profiles:
                del self._profiles[name]
            
            self._record_history(name, "DELETE", "Profile removed")
            
            return True
            
        except IOError as e:
            print(f"Error deleting profile {name}: {e}")
            return False
    
    def list_profiles(self, tags: Optional[List[str]] = None) -> List[ProfileMetadata]:
        """List all stored profiles with optional tag filter.
        
        Args:
            tags: Optional list of tags to filter by (matches any tag)
            
        Returns:
            List of ProfileMetadata objects sorted by creation date (newest first)
        """
        metadatas = []
        
        for filename in self.storage_path.glob("*.json"):
            name = filename.stem
            
            try:
                profile = self.load_profile(name)
                if profile:
                    metadatas.append(ProfileMetadata(
                        name=name,
                        version=profile.version,
                        created_at=profile.created_at,
                        updated_at=profile.updated_at,
                        author=profile.author,
                        tags=profile.tags,
                        is_validated=profile.is_validated,
                        description=profile.description,
                    ))
                    
            except Exception as e:
                print(f"Error reading profile {name}: {e}")
                continue
        
        # Filter by tags if specified
        if tags:
            metadatas = [m for m in metadatas 
                        if any(tag in m.tags for tag in tags)]
        
        # Sort by creation date (newest first)
        return sorted(metadatas, key=lambda m: m.created_at, reverse=True)
    
    def get_version_history(self, name: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get version history for a profile.
        
        Args:
            name: Profile name
            limit: Maximum number of history entries to return
            
        Returns:
            List of history records with timestamp, action, and details
        """
        return self._history.get(name, [])[-limit:]
    
    def has_profile(self, name: str) -> bool:
        """Check if a profile exists in storage or cache.
        
        Args:
            name: Profile name to check
            
        Returns:
            True if profile exists, False otherwise
        """
        return name in self._profiles or (self.storage_path / f"{name}.json").exists()
    
    def clear_cache(self):
        """Clear in-memory profile cache.
        
        Note: This does NOT delete files from storage.
        """
        self._profiles.clear()
    
    def _record_history(self, name: str, action: str, details: str):
        """Record an action in the profile's history."""
        if name not in self._history:
            self._history[name] = []
        
        self._history[name].append({
            'timestamp': datetime.now().isoformat(),
            'action': action,
            'details': details,
        })
