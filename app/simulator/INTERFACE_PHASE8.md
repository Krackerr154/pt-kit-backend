# Phase 8 Interface Contract: Calibration & Parameter Optimization Layer

## Overview
This phase implements automated calibration and parameter optimization capabilities for the PT-Kit digital-twin simulator. The layer provides intelligent tuning algorithms that adjust plant parameters based on experimental data cross-validation, with support for batch processing, history tracking, and rollback capabilities.

---

## Scope

### Phase 8 Deliverables

**Task 8.1: Cross-validation Engine** (Primary)
- Cross-validation framework comparing simulated vs measured data
- Statistical metrics computation (RMSE, MAE, R²)
- Outlier detection with configurable thresholds
- Automatic parameter suggestion generation
- Validation of optimization results

**Task 8.2: Batch Processing Manager** (Parallel)
- Multi-experiment batch processing workflows
- Progress tracking and logging
- Parallel execution with resource management
- Result aggregation and reporting
- Error handling and recovery mechanisms

**Task 8.3: Historical Analysis & Rollback** (Parallel)  
- Historical parameter analysis tools
- Version comparison utilities
- Rollback to previous states
- Trend analysis and visualization data preparation
- Audit trail maintenance

---

## Component Contracts

### Task 8.1: Cross-validation Engine (`app/simulator/cross_validation_engine.py`)

#### Classes and Methods

**`CrossValidationMetrics` Dataclass:**
```python
@dataclass
class CrossValidationMetrics:
    rmse: float              # Root Mean Square Error
    mae: float               # Mean Absolute Error
    r_squared: float         # Coefficient of determination
    max_deviation: float     # Maximum deviation between curves
    mean_deviation: float    # Average deviation across all points
    num_points: int          # Number of comparison points
```

**`CurveFitter` Class:**
```python
class CurveFitter:
    def fit(self, x_data: np.ndarray, y_data: np.ndarray) -> Tuple[callable, dict]:
        """Fit polynomial/exponential curve to data."""
        
    def get_model_parameters(self) -> Dict[str, float]:
        """Extract fitted model parameters."""
    
    def predict(self, x_values: np.ndarray) -> np.ndarray:
        """Generate predictions from fitted model."""
```

**`OptimizationResult` Dataclass:**
```python
@dataclass 
class OptimizationResult:
    success: bool
    original_profile: PlantProfile
    optimized_profile: PlantProfile  
    metrics_before: CrossValidationMetrics
    metrics_after: CrossValidationMetrics
    delta_summary: str           # Human-readable summary
    improvement_pct: float       # Overall improvement percentage
```

**`CrossValidationEngine` Class:**
```python
class CrossValidationEngine:
    def __init__(self, tolerance=0.05):
        """Initialize with acceptable error tolerance."""
    
    def compute_metrics(measured: np.ndarray, simulated: np.ndarray) -> CrossValidationMetrics:
        """Compute all statistical metrics between two datasets."""
    
    def detect_outliers(data: np.ndarray, threshold_std=3.0) -> List[Tuple[int, float]]:
        """Detect outliers beyond threshold standard deviations."""
    
    def suggest_param_adjustments(
        profile: PlantProfile, 
        metrics: CrossValidationMetrics
    ) -> Dict[str, float]:
        """Generate parameter adjustment suggestions."""
    
    def optimize_parameters(
        profile: PlantProfile,
        measured_data: np.ndarray,
        target_temp_data: np.ndarray,
        max_iterations: int = 100
    ) -> OptimizationResult:
        """Run complete optimization workflow."""
    
    def validate_optimization(result: OptimizationResult, min_improvement=0.01) -> bool:
        """Validate that optimization provided meaningful improvement."""
```

---

### Task 8.2: Batch Processing Manager (`app/simulator/batch_processor.py`)

#### Classes and Methods

**`BatchProcessingConfig` Dataclass:**
```python
@dataclass
class BatchProcessingConfig:
    max_concurrent_jobs: int = 4
    timeout_per_experiment: int = 300  # seconds
    retry_attempts: int = 2
    log_level: str = "INFO"
    progress_callback: Optional[callable] = None
```

**`ExperimentJob` Dataclass:**
```python
@dataclass
class ExperimentJob:
    job_id: str
    experiment_name: str
    input_profile: PlantProfile
    measured_data: Dict[str, np.ndarray]
    status: str = "pending"      # pending/running/completed/failed
    result: Optional[dict] = None
    error_message: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
```

**`BatchProcessor` Class:**
```python
class BatchProcessor:
    def __init__(self, config: BatchProcessingConfig):
        """Initialize batch processor with configuration."""
    
    async def submit_job(self, experiment_name: str, profile: PlantProfile, 
                        measured_data: Dict[str, np.ndarray]) -> str:
        """Submit single experiment for batch processing."""
    
    async def submit_batch(
        self, 
        experiments: List[Tuple[str, PlantProfile, Dict[str, np.ndarray]]]
    ) -> List[str]:
        """Submit multiple experiments as a batch."""
    
    async def get_job_status(self, job_id: str) -> ExperimentJob:
        """Retrieve current status of a specific job."""
    
    async def wait_for_completion(
        self, 
        job_ids: List[str], 
        timeout: Optional[int] = None
    ) -> Dict[str, ExperimentJob]:
        """Wait for all jobs to complete or timeout."""
    
    def cancel_job(self, job_id: str) -> bool:
        """Cancel a running job."""
    
    def get_batch_summary(self) -> Dict[str, Any]:
        """Get overall batch processing statistics."""
    
    def export_results(self, output_path: str, format: str = "json") -> Path:
        """Export all results to file."""
```

**Progress Callback Signature:**
```python
def progress_callback(job_id: str, status: str, progress_pct: float):
    """Called periodically during processing."""
```

---

### Task 8.3: Historical Analysis & Rollback (`app/simulator/historical_analysis.py`)

#### Classes and Methods

**`ParameterHistoryEntry` Dataclass:**
```python
@dataclass
class ParameterHistoryEntry:
    timestamp: datetime
    action: str                 # create/update/optimize/rollback
    profile_name: str
    profile_version: str
    changed_fields: Dict[str, Any]
    reason: str                # Why this change was made
    operator: Optional[str] = None  # Who made it (if manual)
```

**`ParameterAnalyzer` Class:**
```python
class ParameterAnalyzer:
    def __init__(self, history_entries: List[ParameterHistoryEntry]):
        """Initialize analyzer with historical data."""
    
    def get_trend_analysis(
        field_name: str,
        window_days: int = 30
    ) -> Dict[str, Any]:
        """Analyze trend for a specific parameter over time."""
    
    def find_similar_configs(
        reference_profile: PlantProfile,
        similarity_threshold: float = 0.95
    ) -> List[tuple]:
        """Find similar configurations in history."""
    
    def calculate_variance_by_field(
        history: List[ParameterHistoryEntry]
    ) -> Dict[str, float]:
        """Calculate variance metrics per parameter field."""
```

**`RollbackManager` Class:**
```python
class RollbackManager:
    def __init__(self, registry: ProfileRegistry):
        """Initialize with profile registry."""
    
    async def create_checkpoint(
        self, 
        profile_name: str, 
        description: str
    ) -> str:
        """Create snapshot checkpoint of current state."""
    
    async def rollback_to_checkpoint(
        self,
        profile_name: str,
        checkpoint_id: str,
        force: bool = False
    ) -> bool:
        """Restore profile to saved checkpoint state."""
    
    async def list_checkpoints(
        self,
        profile_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List available checkpoints."""
    
    async def delete_checkpoint(
        self,
        checkpoint_id: str
    ) -> bool:
        """Remove a specific checkpoint."""
    
    async def compare_versions(
        self,
        profile_name: str,
        version_from: str,
        version_to: str
    ) -> Dict[str, Any]:
        """Compare two versions and return differences."""
```

**`AuditTrailLogger` Class:**
```python
class AuditTrailLogger:
    def __init__(self, storage_path: Path):
        """Initialize audit trail logger."""
    
    async def log_action(
        self,
        action: str,
        profile_name: str,
        details: Dict[str, Any],
        operator: Optional[str] = None
    ) -> None:
        """Log action to audit trail."""
    
    async def get_trail(
        self,
        profile_name: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Retrieve audit trail entries."""
```

---

## Data Flow Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    EXPERIMENT DATA                          │
│              (Measured + Simulated)                         │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              CROSS_VALIDATION_ENGINE                         │
│  ┌─────────────────┐  ┌─────────────────┐                  │
│  │ CurveFitter     │  │ Optimizer       │                  │
│  │ (Polynomial fit)│  │ (Gradient desc) │                  │
│  └─────────────────┘  └─────────────────┘                  │
│                   ▼                                        │
│            OptimizationResult                             │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│               PARAMETER UPDATE PIPELINE                      │
│  ┌─────────────────┐  ┌─────────────────┐                  │
│  │ Validation      │  │ Audit Logging   │                  │
│  │ Check           │  │ + History Entry │                  │
│  └─────────────────┘  └─────────────────┘                  │
│                   ▼                                        │
│             Updated PlantProfile                          │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│               BATCH PROCESSING MANAGER                       │
│  ┌─────────────────┐  ┌─────────────────┐                  │
│  │ Job Scheduler   │  │ Progress Tracker│                  │
│  │ (Async pool)    │  │ + Logging       │                  │
│  └─────────────────┘  └─────────────────┘                  │
│                   ▼                                        │
│              Batch Results Aggregation                    │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│            HISTORICAL ANALYSIS + ROLLBACK                   │
│  ┌─────────────────┐  ┌─────────────────┐                  │
│  │ Trend Analysis  │  │ Rollback Manager│                  │
│  │ + Variance      │  │ + Checkpoints   │                  │
│  └─────────────────┘  └─────────────────┘                  │
│                   ▼                                        │
│            Audit Trail + Change Log                       │
└─────────────────────────────────────────────────────────────┘
```

---

## Integration Points

### With Phase 7 (Profile Management)
```python
from app.simulator.profile_management import ProfileRegistry
from app.simulator.cross_validation_engine import CrossValidationEngine

# Shared registry instance
registry = ProfileRegistry()
engine = CrossValidationEngine(tolerance=0.05)

# Optimization workflow uses same profiles
profile = registry.load_profile("ISO1_baseline")
result = engine.optimize_parameters(profile, measured_data, target_data)
```

### With Phase 5 (Backend API)
```python
from app.simulator.isolated_backend_api import SimulatorBackendAPILayer

backend_api = SimulatorBackendAPILayer()
batch_processor = BatchProcessor(config)

# Submit batch through API layer
job_ids = await backend_api.submit_optimization_batch(experiments)
```

### With Phase 6 (Dashboard)
```python
# Real-time progress updates to dashboard
progress_callback = lambda job_id, status, pct: websocket.send({
    "type": "optimization_progress",
    "job_id": job_id,
    "status": status,
    "progress": pct
})
```

---

## Testing Requirements

### Test Coverage Goals
- All statistical computations verified against known solutions
- Batch processing tests with mock async queues
- Rollback scenarios tested with checkpoint save/load cycles
- Edge cases: empty datasets, extreme values, missing fields
- Performance benchmarks: throughput for batch processing
- Concurrent access safety for shared resources

### Expected Test Patterns
```python
# Cross-validation metric computation
assert metrics.rmse < threshold
assert outlier_indices are within bounds

# Batch processing
await wait_for_completion(timeout=60)
assert all(completed_statuses)

# Rollback verification
rollback_success = await rollback_manager.rollback(...)
verified_restore = check_identical_state(old, new)
assert verified_restore

# Audit trail completeness
trail = await audit_logger.get_trail()
assert len(trail) == expected_count
```

---

## Acceptance Criteria

### Functional Requirements
✅ Automated parameter optimization with convergence detection  
✅ Statistical validation of optimization results (R² > 0.95 target)  
✅ Batch processing with configurable concurrency  
✅ Full rollback capability with checkpoint system  
✅ Complete audit trail for all changes  
✅ No external database dependencies  

### Performance Requirements
✅ Handle 50+ concurrent batch jobs efficiently  
✅ Optimization iterations complete within timeout limits  
✅ Rollback operations complete in < 5 seconds  
✅ Memory usage bounded for large datasets  

### Quality Requirements
✅ 100% test pass rate on core functionality  
✅ Code coverage > 85%  
✅ No warnings from type checking tools  
✅ Documentation complete for all public APIs  

---

## Implementation Notes

### Key Design Decisions
1. **Async-first design**: All I/O operations use `asyncio.to_thread()` for non-blocking performance
2. **Pure Python algorithms**: No numpy/scipy dependencies for simplicity and portability
3. **Callback-based progress**: External systems can subscribe to progress events
4. **Immutable snapshots**: Rollback uses deep copies to prevent corruption
5. **Separation of concerns**: Cross-validation, batch processing, and historical analysis are independent modules

### Dependencies
- `numpy` optional for advanced math (can fallback to pure Python)
- Standard library only for core functionality
- No database connections required
- JSON for persistence

---

## Success Metrics

- **Optimization quality**: Average R² improvement > 0.90 after tuning
- **Batch throughput**: Process 100 experiments/hour at default concurrency
- **Rollback reliability**: 100% successful restoration of saved checkpoints
- **Audit completeness**: Every state change logged with full context
- **Developer productivity**: API intuitive enough for rapid integration

---

*Interface contract version 1.0 | Created: 2026-08-01 | PT-Kit Simulator v1.0*
