# Phase 7 Interface Contract: Experiment Profile Management Layer

This document defines the interfaces for Phase 7 implementation so parallel subagents produce compatible code.

## Overview

Phase 7 implements the **Experiment Profile Management Layer** - a comprehensive system for defining, validating, loading, and switching between multiple experiment configurations. This layer enables users to manage complex experimental scenarios with predefined parameters, target values, duration constraints, and sensor calibration settings.

The architecture provides:
- Profile creation and persistence (JSON/YAML formats)
- Parameter validation against physical constraints
- Template-based profile generation
- Multi-scenario execution workflows
- Calibration state integration
- Version history and rollback capabilities

```
Dashboard/UI ←→ Profile Manager ←→ Plant/Controller Configs
                   ↓
            Validation Engine
                   ↓
            Load/Save Operations
```

---

## Core Data Models

### PlantProfile Schema (Extended from Phase 1)

```python
@dataclass
class PlantParameters:
    """Physical plant configuration parameters with units."""
    
    # Thermal properties
    ambient_temp_c: float = Field(default=25.0, ge=0, le=100)  # Ambient temperature °C
    surface_thermal_mass_j_k: float = Field(default=500, gt=0)  # Surface thermal mass J/K
    bulk_thermal_mass_j_k: float = Field(default=2000, gt=0)   # Bulk thermal mass J/K
    surface_to_bulk_thermal_conductance_w_k: float = Field(default=10, gt=0)  # W/K
    
    # Optical properties  
    lamp_efficiency_pct: float = Field(default=35, ge=0, le=100)  # Lamp power conversion %
    lux_to_power_conversion: float = Field(default=0.01, gt=0)    # Lux → Watts conversion
    
    # Dynamics parameters
    max_lamp_power_w: float = Field(default=100, gt=0)            # Maximum lamp output W
    max_fan_rpm: float = Field(default=5000, gt=0)                # Maximum fan speed RPM
    lamp_response_time_s: float = Field(default=0.1, gt=0)        # Lamp electrical response s
    fan_response_time_s: float = Field(default=0.5, gt=0)         # Fan mechanical response s


@dataclass
class SensorConfig:
    """Sensor calibration and noise parameters."""
    
    # Temperature sensors
    ir_temp_offset_c: float = Field(default=0.0)      # IR sensor offset °C
    tc_temp_offset_c: float = Field(default=0.0)      # Thermocouple offset °C
    temp_noise_sigma: float = Field(default=0.1, ge=0)  # Temp measurement noise σ °C
    
    # Lux sensor
    lux_offset: int = Field(default=0)                 # Lux sensor offset
    lux_gain: float = Field(default=1.0, gt=0)         # Lux gain multiplier
    
    # Sampling parameters
    update_interval_s: float = Field(default=0.5, gt=0)   # Sensor update interval s
    smoothing_window: int = Field(default=5, gt=0)        # Moving average window size


@dataclass
class PlantProfile:
    """Complete plant configuration with validation status."""
    
    name: str
    description: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    version: str = "1.0.0"
    
    plant_params: PlantParameters = field(default_factory=PlantParameters)
    sensor_config: SensorConfig = field(default_factory=SensorConfig)
    
    # Validation status
    is_validated: bool = False
    validation_errors: List[str] = field(default_factory=list)
    
    # Metadata
    author: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    
    def validate(self) -> Tuple[bool, List[str]]:
        """Validate all parameters are within physical constraints."""
        errors = []
        
        # Validate thermal masses are positive
        if self.plant_params.surface_thermal_mass_j_k <= 0:
            errors.append("Surface thermal mass must be > 0")
        
        if self.plant_params.bulk_thermal_mass_j_k <= 0:
            errors.append("Bulk thermal mass must be > 0")
        
        # Validate temperatures in reasonable range
        if not (0 <= self.plant_params.ambient_temp_c <= 100):
            errors.append("Ambient temperature must be 0-100°C")
        
        # Validate lamp efficiency
        if not (0 <= self.plant_params.lamp_efficiency_pct <= 100):
            errors.append("Lamp efficiency must be 0-100%")
        
        # Validate sensor offsets don't exceed physical limits
        if abs(self.sensor_config.ir_temp_offset_c) > 10:
            errors.append("IR sensor offset exceeds ±10°C limit")
        
        self.is_validated = len(errors) == 0
        self.validation_errors = errors
        
        return self.is_validated, errors
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary for JSON storage."""
        return {
            'name': self.name,
            'description': self.description,
            'created_at': self.created_at.isoformat(),
            'version': self.version,
            'plant_params': dataclasses.asdict(self.plant_params),
            'sensor_config': dataclasses.asdict(self.sensor_config),
            'is_validated': self.is_validated,
            'validation_errors': self.validation_errors,
            'author': self.author,
            'tags': self.tags,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PlantProfile':
        """Deserialize from dictionary."""
        return cls(
            name=data['name'],
            description=data.get('description', ''),
            created_at=datetime.fromisoformat(data['created_at']),
            version=data.get('version', '1.0.0'),
            plant_params=PlantParameters(**data['plant_params']),
            sensor_config=SensorConfig(**data['sensor_config']),
            is_validated=data.get('is_validated', False),
            validation_errors=data.get('validation_errors', []),
            author=data.get('author'),
            tags=data.get('tags', []),
        )
```

### Scenario Configuration Schema

```python
@dataclass
class TargetSetpoint:
    """Target temperature/lux setpoints for automated control."""
    
    target_surface_temp_c: Optional[float] = None  # Surface target °C
    target_bulk_temp_c: Optional[float] = None     # Bulk target °C
    target_lux: Optional[int] = None               # Lux target
    ramp_rate_c_per_min: Optional[float] = None    # Ramp rate °C/min
    hold_duration_s: Optional[float] = None        # Hold time at target s
    
    def validate(self) -> List[str]:
        """Validate setpoint combinations make physical sense."""
        errors = []
        
        # Check for conflicting targets
        if self.target_surface_temp_c is not None and self.target_bulk_temp_c is not None:
            if abs(self.target_surface_temp_c - self.target_bulk_temp_c) < 2:
                errors.append("Surface and bulk targets too close (<2°C difference)")
        
        # Validate ramp rates are achievable
        if self.ramp_rate_c_per_min is not None:
            if self.ramp_rate_c_per_min > 10:  # Physical limitation
                errors.append("Ramp rate exceeds 10°C/min maximum")
        
        return errors


@dataclass
class ExperimentScenario:
    """Complete experiment scenario definition."""
    
    scenario_id: str
    name: str
    description: str = ""
    
    # Profile references
    base_profile_name: str
    calibration_offsets: Optional[Dict[str, float]] = None
    
    # Execution parameters
    duration_s: float = Field(default=3600, gt=0)  # Total duration seconds
    sample_rate_hz: float = Field(default=2.0, gt=0)  # Telemetry sample rate Hz
    
    # Control strategy
    control_mode: Literal["ISO1", "PLAT1", "CUSTOM"] = "ISO1"
    targets: Optional[TargetSetpoint] = None
    
    # Fault injection plan
    fault_schedule: List[Dict[str, Any]] = field(default_factory=list)
    # Example: [{"time_s": 60, "type": "sensor_drift", "magnitude": 0.5}]
    
    # Validation status
    is_validated: bool = False
    validation_warnings: List[str] = field(default_factory=list)
    
    def validate(self, profile_registry: 'ProfileRegistry') -> Tuple[bool, List[str]]:
        """Validate scenario against profile registry."""
        warnings = []
        
        # Check base profile exists
        if not profile_registry.has_profile(self.base_profile_name):
            warnings.append(f"Base profile '{self.base_profile_name}' not found in registry")
        
        # Validate fault schedule timing
        for fault in self.fault_schedule:
            if fault.get('time_s', 0) > self.duration_s:
                warnings.append(f"Fault scheduled at {fault['time_s']}s exceeds duration {self.duration_s}s")
        
        self.is_validated = len(warnings) == 0
        self.validation_warnings = warnings
        
        return self.is_validated, warnings
```

### Profile Registry Schema

```python
@dataclass
class ProfileMetadata:
    """Minimal metadata for profile listing."""
    
    name: str
    version: str
    created_at: datetime
    author: Optional[str]
    tags: List[str]
    is_validated: bool
    description: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'version': self.version,
            'created_at': self.created_at.isoformat(),
            'author': self.author,
            'tags': self.tags,
            'is_validated': self.is_validated,
            'description': self.description,
        }


class ProfileRegistry:
    """Central registry for all profiles with CRUD operations."""
    
    def __init__(self, storage_path: Path = Path("~/.pt-kit/profiles")):
        self.storage_path = Path(storage_path).expanduser()
        self._profiles: Dict[str, PlantProfile] = {}
        self._scenarios: Dict[str, ExperimentScenario] = {}
        self._history: Dict[str, List[Tuple[datetime, str]]] = defaultdict(list)
        
        # Ensure storage directory exists
        self.storage_path.mkdir(parents=True, exist_ok=True)
    
    def load_profile(self, name: str) -> Optional[PlantProfile]:
        """Load profile from JSON file."""
        file_path = self.storage_path / f"{name}.json"
        
        if not file_path.exists():
            return None
        
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        profile = PlantProfile.from_dict(data)
        self._profiles[name] = profile
        
        return profile
    
    def save_profile(self, profile: PlantProfile) -> bool:
        """Save profile to JSON file after validation."""
        # Auto-validate before saving
        profile.validate()
        
        if not profile.is_validated:
            raise ValidationError(f"Profile '{profile.name}' has validation errors: {profile.validation_errors}")
        
        file_path = self.storage_path / f"{profile.name}.json"
        
        with open(file_path, 'w') as f:
            json.dump(profile.to_dict(), f, indent=2, default=str)
        
        # Record history
        self._record_history(profile.name, "SAVE", f"Saved version {profile.version}")
        
        return True
    
    def delete_profile(self, name: str, force: bool = False) -> bool:
        """Delete profile from storage."""
        if name not in self._profiles and not force:
            return False
        
        file_path = self.storage_path / f"{name}.json"
        if file_path.exists():
            file_path.unlink()
        
        self._record_history(name, "DELETE", "Profile removed")
        
        return True
    
    def list_profiles(self, tags: Optional[List[str]] = None) -> List[ProfileMetadata]:
        """List all stored profiles with optional tag filter."""
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
                        author=profile.author,
                        tags=profile.tags,
                        is_validated=profile.is_validated,
                        description=profile.description,
                    ))
            except Exception:
                continue  # Skip corrupted files
        
        # Filter by tags if specified
        if tags:
            metadatas = [m for m in metadatas if any(tag in m.tags for tag in tags)]
        
        return sorted(metadatas, key=lambda m: m.created_at, reverse=True)
    
    def get_version_history(self, name: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get version history for a profile."""
        return self._history.get(name, [])[-limit:]
    
    def _record_history(self, name: str, action: str, details: str):
        """Record action in profile history."""
        timestamp = datetime.now()
        self._history[name].append({
            'timestamp': timestamp,
            'action': action,
            'details': details,
        })
```

---

## API Interfaces

### ProfileManagementLayer

```python
class ProfileManagementLayer:
    """High-level profile management orchestration layer."""
    
    def __init__(self, registry: ProfileRegistry):
        self.registry = registry
        self._active_profile: Optional[PlantProfile] = None
        self._active_scenario: Optional[ExperimentScenario] = None
        self._load_callbacks: List[Callable[[PlantProfile], None]] = []
    
    async def load_profile(self, name: str, apply: bool = True) -> PlantProfile:
        """Load profile from storage and optionally activate it."""
        profile = await asyncio.to_thread(self.registry.load_profile, name)
        
        if not profile:
            raise ValueError(f"Profile '{name}' not found")
        
        if apply:
            await self._activate_profile(profile)
        
        return profile
    
    async def create_profile(
        self, 
        name: str,
        base_profile_name: Optional[str] = None,
        custom_params: Optional[Dict[str, Any]] = None
    ) -> PlantProfile:
        """Create new profile from template or with custom parameters."""
        if base_profile_name:
            # Clone existing profile
            base = await self.load_profile(base_profile_name, apply=False)
            profile = copy.deepcopy(base)
            profile.name = name
            profile.version = self._generate_version(base.version)
        else:
            # Create blank profile with defaults
            profile = PlantProfile(
                name=name,
                description="New profile",
                plant_params=PlantParameters(),
                sensor_config=SensorConfig(),
            )
        
        # Apply custom parameter overrides
        if custom_params:
            self._apply_custom_params(profile, custom_params)
        
        # Validate before saving
        is_valid, errors = profile.validate()
        if not is_valid:
            raise ValidationError(f"Cannot create invalid profile: {errors}")
        
        # Save to registry
        self.registry.save_profile(profile)
        
        return profile
    
    async def update_profile_parameters(
        self, 
        name: str, 
        updates: Dict[str, Any],
        create_snapshot: bool = True
    ) -> PlantProfile:
        """Update specific parameters of existing profile."""
        profile = await self.load_profile(name, apply=False)
        
        # Parse updates into nested structure
        self._parse_nested_updates(profile, updates)
        
        # Re-validate
        is_valid, errors = profile.validate()
        if not is_valid:
            raise ValidationError(f"Update would create invalid profile: {errors}")
        
        # Bump version and save
        profile.version = self._bump_version(profile.version)
        self.registry.save_profile(profile)
        
        return profile
    
    def validate_profile(self, profile: PlantProfile) -> Tuple[bool, List[str]]:
        """Run full validation suite on profile."""
        # Plant parameter validation
        is_valid, errors = profile.validate()
        
        if is_valid:
            # Check thermal equilibrium feasibility
            is_feasible, warnings = self._check_thermal_feasibility(profile)
            errors.extend(warnings)
        
        return len(errors) == 0, errors
    
    async def switch_to_profile(self, name: str) -> bool:
        """Switch active profile for running experiments."""
        profile = await self.load_profile(name, apply=True)
        self._active_profile = profile
        
        # Notify subscribers
        for callback in self._load_callbacks:
            await callback(profile)
        
        return True
    
    def register_load_callback(self, callback: Callable[[PlantProfile], None]):
        """Register callback to be invoked when profile loads."""
        self._load_callbacks.append(callback)
    
    async def export_profile(self, name: str, format: str = "json") -> bytes:
        """Export profile in various formats (JSON, YAML, CSV summary)."""
        profile = await self.load_profile(name, apply=False)
        
        if format == "json":
            return json.dumps(profile.to_dict(), indent=2).encode()
        elif format == "yaml":
            import yaml
            return yaml.dump(profile.to_dict()).encode()
        elif format == "csv":
            return self._export_to_csv(profile)
        else:
            raise ValueError(f"Unsupported export format: {format}")
    
    def _check_thermal_feasibility(self, profile: PlantProfile) -> Tuple[bool, List[str]]:
        """Check if thermal parameters allow stable operation."""
        warnings = []
        
        # Check thermal mass ratio
        ratio = profile.plant_params.surface_thermal_mass_j_k / \
                profile.plant_params.bulk_thermal_mass_j_k
        
        if ratio > 5:
            warnings.append("Surface thermal mass much larger than bulk - may cause slow response")
        
        if ratio < 0.1:
            warnings.append("Surface thermal mass very small relative to bulk - rapid fluctuations expected")
        
        # Check lamp efficiency vs max power
        max_effective_power = profile.plant_params.max_lamp_power_w * \
                             profile.plant_params.lamp_efficiency_pct / 100
        
        if max_effective_power < 10:
            warnings.append("Effective lamp power below 10W - may struggle to reach targets")
        
        return len(warnings) == 0, warnings
```

---

## Exit Criteria Checklist

✅ Profile creation workflow completes successfully  
✅ Validation rejects physically impossible parameter combinations  
✅ Templates enable quick profile generation from common configurations  
✅ Loading/saving operations complete within 100ms  
✅ Version history tracks all modifications  
✅ Tag-based filtering works for profile listings  
✅ Export to JSON/YAML/CSV formats produces valid files  
✅ No external database dependencies (local JSON files only)  
✅ Deterministic: same input produces identical output  
✅ Thread-safe concurrent access to registry  

---

## Performance Targets

| Metric | Target | Measurement Method |
|--------|--------|-------------------|
| Profile load time | < 100ms | Time from request to validated object |
| Profile save time | < 200ms | Time from validation to disk write |
| List profiles | < 50ms for 100 profiles | Iteration + metadata extraction |
| Validation time | < 50ms per profile | Full parameter constraint checking |
| Concurrent access | ≥ 10 simultaneous reads | Thread safety verification |
| Memory usage | < 5 MB per 100 profiles | RSS monitoring |
| Disk space | ~10 KB per profile | Average JSON file size |

---

## Testing Requirements

### Unit Tests (Task 7.1: Profile Core)
- Test PlantProfile serialization/deserialization round-trip
- Test PlantParameters validation catches out-of-range values
- Test SensorConfig bounds checking (offsets, gains, noise)
- Test ProfileRegistry CRUD operations (create, read, update, delete)
- Test version bumping logic (1.0.0 → 1.0.1, 1.9.0 → 1.10.0)
- Verify no external database/HTTP dependencies

### Unit Tests (Task 7.2: Validation Engine)
- Test thermal feasibility checks detect unrealistic configurations
- Test fault schedule validation rejects future-time faults beyond duration
- Test target setpoint conflicts (surface/bulk too close)
- Test ramp rate limits (max 10°C/min)
- Test calibration offset boundaries (±10°C)
- Mock file system interactions for reproducibility

### Integration Tests (Task 7.3: Scenario Management)
- Test scenario creation from profile templates
- Test multi-step workflow (create → validate → save → load)
- Test profile switching during active experiment
- Test version history accumulation across saves
- Test export formats (JSON/YAML/CSV) produce correct output
- Mock callbacks for load event notifications

---

## Security Considerations

- **Input Sanitization**: Strip dangerous characters from profile names (no path traversal)
- **File Permissions**: Store profiles in user-specific directory (~/.pt-kit/profiles/) with 600 permissions
- **Path Traversal Prevention**: Reject profile names containing "..", "/", "\", ":"
- **Validation Before Parse**: Validate string length before JSON/YAML parsing (DoS prevention)
- **Resource Limits**: Enforce maximum file sizes (1MB per profile file)
- **Audit Logging**: Log all profile modifications with timestamps and actions

---

## Error Handling

| Scenario | Response | Recovery Action |
|----------|----------|-----------------|
| Profile not found | `ProfileNotFoundError` | List available profiles, suggest alternatives |
| Validation error | `ValidationError` with details | Show user which parameters violated constraints |
| File corruption | `CorruptedProfileError` | Attempt restore from version history |
| Permission denied | `PermissionError` | Suggest re-run with elevated privileges |
| Disk full | `IOError` | Cleanup old versions, alert user |

---

*Document Version: 1.0 | Created: 2026-08-01 | PT-Kit Phase 7 Deliverable*
