"""Historical Analysis Module for ParameterAnalyzer, RollbackManager, and AuditTrailLogger."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, TypeVar
from enum import Enum
import json
import hashlib


class AuditAction(Enum):
    """Types of audit actions that can be logged."""
    PARAMETER_UPDATE = "parameter_update"
    SIMULATION_START = "simulation_start"
    SIMULATION_END = "simulation_end"
    SNAPSHOT_CREATED = "snapshot_created"
    ROLLBACK_INITIATED = "rollback_initiated"
    ROLLBACK_COMPLETED = "rollback_completed"
    CONFIG_CHANGED = "config_changed"
    MANUAL_OVERRIDE = "manual_override"
    AUTO_TUNING = "auto_tuning"
    
    def __str__(self) -> str:
        return self.value


T = TypeVar('T')


@dataclass
class ParameterHistoryEntry:
    """
    Represents a single entry in the parameter history tracking system.
    
    Each entry captures a snapshot of parameters at a specific point in time,
    including what action caused the change, the profile information, and
    metadata for auditing purposes.
    """
    timestamp: datetime
    action: AuditAction
    profile_info: Dict[str, Any]
    # Parameters before the change (can be empty for initial state)
    parameters_before: Optional[Dict[str, Any]] = None
    # Parameters after the change
    parameters_after: Dict[str, Any] = field(default_factory=dict)
    # Metadata about the change
    metadata: Dict[str, Any] = field(default_factory=dict)
    # Unique identifier for this entry
    entry_id: Optional[str] = None
    
    def __post_init__(self):
        """Generate unique ID if not provided."""
        if self.entry_id is None:
            self.entry_id = self._generate_entry_id()
    
    def _generate_entry_id(self) -> str:
        """
        Generate a unique entry ID based on timestamp, action, and content.
        
        Returns:
            A SHA-256 hash string representing the unique identifier.
        """
        content = f"{self.timestamp.isoformat()}{self.action.value}"
        if self.parameters_after:
            content += json.dumps(self.parameters_after, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the entry to a dictionary representation.
        
        Returns:
            Dictionary with all entry fields, with timestamp serialized.
        """
        return {
            'timestamp': self.timestamp.isoformat(),
            'action': self.action.value,
            'profile_info': self.profile_info,
            'parameters_before': self.parameters_before,
            'parameters_after': self.parameters_after,
            'metadata': self.metadata,
            'entry_id': self.entry_id
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ParameterHistoryEntry':
        """
        Create a ParameterHistoryEntry from a dictionary.
        
        Args:
            data: Dictionary containing entry data.
            
        Returns:
            New ParameterHistoryEntry instance.
        """
        # Convert ISO format timestamp back to datetime
        timestamp_str = data['timestamp']
        if isinstance(timestamp_str, str):
            timestamp = datetime.fromisoformat(timestamp_str)
        else:
            timestamp = timestamp_str
            
        return cls(
            timestamp=timestamp,
            action=AuditAction(data['action']),
            profile_info=data['profile_info'],
            parameters_before=data.get('parameters_before'),
            parameters_after=data.get('parameters_after', {}),
            metadata=data.get('metadata', {}),
            entry_id=data.get('entry_id')
        )
    
    def get_summary(self) -> str:
        """
        Get a human-readable summary of this entry.
        
        Returns:
            Summary string describing the change.
        """
        params_changed = set(self.parameters_after.keys())
        if self.parameters_before:
            params_before = set(self.parameters_before.keys())
            params_added = params_changed.difference(params_before)
        else:
            params_added = params_changed
        
        return (f"[{self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}] "
                f"{self.action.value}: {len(params_added)} parameter(s) updated")


@dataclass
class SimulationSnapshot:
    """
    Complete snapshot of simulation state at a point in time.
    
    Includes all parameters, settings, and contextual information needed
    to restore or analyze the simulation state.
    """
    snapshot_id: str
    timestamp: datetime
    simulation_name: str
    parameters: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def create(cls, simulation_name: str, parameters: Dict[str, Any], 
               metadata: Optional[Dict[str, Any]] = None) -> 'SimulationSnapshot':
        """
        Factory method to create a new snapshot.
        
        Args:
            simulation_name: Name/identifier of the simulation.
            parameters: Current parameters dict.
            metadata: Optional metadata to include.
            
        Returns:
            New Snapshot instance.
        """
        content = f"{simulation_name}{datetime.now().isoformat()}"
        return cls(
            snapshot_id=hashlib.md5(content.encode()).hexdigest()[:12],
            timestamp=datetime.now(),
            simulation_name=simulation_name,
            parameters=parameters.copy() if parameters else {},
            metadata=metadata.copy() if metadata else {}
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            'snapshot_id': self.snapshot_id,
            'timestamp': self.timestamp.isoformat(),
            'simulation_name': self.simulation_name,
            'parameters': self.parameters,
            'metadata': self.metadata
        }


class AuditLogEntry:
    """
    Low-level audit log entry for detailed system activity logging.
    
    Captures events like errors, warnings, and system-level activities
    separate from parameter changes.
    """
    def __init__(self, level: str, message: str, context: Optional[Dict[str, Any]] = None):
        """
        Initialize audit log entry.
        
        Args:
            level: Log level (INFO, WARNING, ERROR, DEBUG).
            message: Human-readable message.
            context: Optional additional context data.
        """
        self.timestamp = datetime.now()
        self.level = level.upper()
        self.message = message
        self.context = context or {}
        self.id = hashlib.md5(
            f"{self.timestamp.isoformat()}{message}".encode()
        ).hexdigest()[:8]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat(),
            'level': self.level,
            'message': self.message,
            'context': self.context
        }


class ParameterAnalyzer:
    """
    Analyzes parameter history to detect patterns, anomalies, and optimization opportunities.
    
    Provides tools for understanding how parameters have changed over time
    and identifying trends or problematic configurations.
    """
    
    def __init__(self):
        """Initialize the analyzer."""
        self._history: List[ParameterHistoryEntry] = []
        self._snapshots: Dict[str, SimulationSnapshot] = {}
        self._analysis_cache: Dict[str, Any] = {}
    
    def add_history_entry(self, entry: ParameterHistoryEntry) -> None:
        """
        Add an entry to the history.
        
        Args:
            entry: The history entry to add.
        """
        self._history.append(entry)
        self._analysis_cache.clear()  # Invalidate cache on new data
    
    def get_history(self, action: Optional[AuditAction] = None) -> List[ParameterHistoryEntry]:
        """
        Get history entries, optionally filtered by action type.
        
        Args:
            action: Optional filter for specific action types.
            
        Returns:
            List of matching history entries.
        """
        if action is None:
            return self._history.copy()
        return [e for e in self._history if e.action == action]
    
    def create_snapshot(self, simulation_name: str, parameters: Dict[str, Any],
                       metadata: Optional[Dict[str, Any]] = None) -> SimulationSnapshot:
        """
        Create a new simulation snapshot.
        
        Args:
            simulation_name: Identifier for the simulation.
            parameters: Current parameter values.
            metadata: Additional metadata.
            
        Returns:
            Created snapshot.
        """
        snapshot = SimulationSnapshot.create(simulation_name, parameters, metadata)
        self._snapshots[snapshot.snapshot_id] = snapshot
        self.add_history_entry(ParameterHistoryEntry(
            timestamp=snapshot.timestamp,
            action=AuditAction.SNAPSHOT_CREATED,
            profile_info={'simulation_name': simulation_name},
            parameters_after={'snapshot_id': snapshot.snapshot_id}
        ))
        return snapshot
    
    def get_snapshots(self, simulation_name: Optional[str] = None) -> List[SimulationSnapshot]:
        """
        Get snapshots, optionally filtered by simulation name.
        
        Args:
            simulation_name: Optional simulation name filter.
            
        Returns:
            List of matching snapshots.
        """
        if simulation_name is None:
            return list(self._snapshots.values())
        return [s for s in self._snapshots.values() 
                if s.simulation_name == simulation_name]
    
    def detect_parameter_drift(self, threshold: float = 0.5) -> Dict[str, float]:
        """
        Detect significant drift in parameters over time.
        
        Args:
            threshold: Drift detection threshold (0.0 to 1.0).
            
        Returns:
            Dictionary mapping parameter names to drift scores.
        """
        if len(self._history) < 2:
            return {}
        
        # Extract parameter values across all entries
        param_values: Dict[str, List[float]] = {}
        
        for entry in self._history:
            if entry.parameters_after:
                for param, value in entry.parameters_after.items():
                    if isinstance(value, (int, float)):
                        if param not in param_values:
                            param_values[param] = []
                        param_values[param].append(float(value))
        
        # Calculate drift for each parameter
        drift_scores: Dict[str, float] = {}
        
        for param, values in param_values.items():
            if len(values) < 2:
                continue
            
            min_val = min(values)
            max_val = max(values)
            range_val = max_val - min_val if max_val != min_val else 1.0
            
            # Relative change as fraction of range
            drift = range_val / (abs(min_val) + abs(max_val) + 1e-10)
            drift_scores[param] = min(drift, 1.0)
        
        return drift_scores
    
    def find_optimal_parameters(self, metric_history: Dict[str, float]) -> Optional[Dict[str, Any]]:
        """
        Find the best performing parameter set based on historical metrics.
        
        Args:
            metric_history: Mapping of entry IDs to performance metrics.
            
        Returns:
            Best parameter set or None if no data available.
        """
        if not metric_history:
            return None
        
        # Sort by metric value (assuming higher is better)
        sorted_entries = sorted(metric_history.items(), key=lambda x: x[1] if x[1] else 0, reverse=True)
        
        if not sorted_entries:
            return None
        
        best_entry_id = sorted_entries[0][0]
        
        if best_entry_id is None:
            return None
        
        # Find the entry with this ID
        for entry in self._history:
            if entry.entry_id == best_entry_id:
                return entry.parameters_after
        
        return None
    
    def generate_analysis_report(self) -> Dict[str, Any]:
        """
        Generate a comprehensive analysis report.
        
        Returns:
            Analysis report dictionary.
        """
        drift_scores = self.detect_parameter_drift()
        recent_entries = self.get_history()[-10:] if self._history else []
        
        # Count actions by type
        action_counts: Dict[str, int] = {}
        for entry in self._history:
            action_str = str(entry.action)
            action_counts[action_str] = action_counts.get(action_str, 0) + 1
        
        return {
            'total_entries': len(self._history),
            'snapshots_count': len(self._snapshots),
            'drift_scores': drift_scores,
            'action_distribution': action_counts,
            'recent_changes': [e.get_summary() for e in recent_entries],
            'analysis_timestamp': datetime.now().isoformat()
        }
    
    def reset(self) -> None:
        """Clear all history and snapshots."""
        self._history.clear()
        self._snapshots.clear()
        self._analysis_cache.clear()


class RollbackManager:
    """
    Manages rollback operations using saved snapshots and history.
    
    Provides controlled rollback capabilities to revert parameter changes
    to previous states with proper auditing and verification.
    """
    
    def __init__(self, parameter_analyzer: Optional[ParameterAnalyzer] = None):
        """
        Initialize the rollback manager.
        
        Args:
            parameter_analyzer: Optional shared analyzer instance.
        """
        self._analyzer = parameter_analyzer or ParameterAnalyzer()
        self._rollback_log: List[Dict[str, Any]] = []
        self._pending_rollback: Optional[Dict[str, Any]] = None
    
    def register_analyzer(self, analyzer: ParameterAnalyzer) -> None:
        """Register an external analyzer instance."""
        self._analyzer = analyzer
    
    def save_checkpoint(self, simulation_name: str, parameters: Dict[str, Any],
                       reason: str) -> SimulationSnapshot:
        """
        Save a checkpoint for potential rollback.
        
        Args:
            simulation_name: Simulation identifier.
            parameters: Current parameters.
            reason: Reason for saving checkpoint.
            
        Returns:
            Created checkpoint snapshot.
        """
        snapshot = self._analyzer.create_snapshot(
            simulation_name=simulation_name,
            parameters=parameters,
            metadata={'checkpoint_reason': reason}
        )
        
        # Log the checkpoint creation
        self._rollback_log.append({
            'type': 'checkpoint_saved',
            'snapshot_id': snapshot.snapshot_id,
            'timestamp': snapshot.timestamp.isoformat(),
            'reason': reason
        })
        
        return snapshot
    
    def rollback_to_snapshot(self, snapshot_id: str, validate: bool = True) -> Dict[str, Any]:
        """
        Rollback to a previously saved snapshot.
        
        Args:
            snapshot_id: ID of snapshot to rollback to.
            validate: Whether to perform validation before rollback.
            
        Returns:
            Rollback result dictionary.
        """
        # Find the snapshot
        snapshot = None
        for snap in self._analyzer.get_snapshots():
            if snap.snapshot_id == snapshot_id:
                snapshot = snap
                break
        
        if snapshot is None:
            return {
                'success': False,
                'error': f"Snapshot {snapshot_id} not found",
                'timestamp': datetime.now().isoformat()
            }
        
        if validate:
            # Validate we can proceed
            if not self._validate_rollback(snapshot):
                return {
                    'success': False,
                    'error': "Validation failed",
                    'timestamp': datetime.now().isoformat()
                }
        
        # Perform rollback
        try:
            parameters_before = dict(snapshot.parameters)
            
            # Simulate the rollback (in real implementation, this would update actual parameters)
            result = {
                'success': True,
                'snapshot_id': snapshot_id,
                'simulation_name': snapshot.simulation_name,
                'parameters_restored': snapshot.parameters,
                'timestamp': datetime.now().isoformat()
            }
            
            # Log the rollback
            self._rollback_log.append({
                'type': 'rollback_completed',
                'snapshot_id': snapshot_id,
                'result': result,
                'timestamp': datetime.now().isoformat()
            })
            
            # Add history entry
            self._analyzer.add_history_entry(ParameterHistoryEntry(
                timestamp=datetime.now(),
                action=AuditAction.ROLLBACK_COMPLETED,
                profile_info={'simulation_name': snapshot.simulation_name},
                parameters_before=parameters_before,
                parameters_after=result['parameters_restored'],
                metadata={'rollback_target': snapshot_id}
            ))
            
            return result
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }
    
    def _validate_rollback(self, snapshot: SimulationSnapshot) -> bool:
        """
        Validate that a rollback operation can proceed safely.
        
        Args:
            snapshot: Target snapshot for validation.
            
        Returns:
            True if rollback is safe to proceed.
        """
        # Check snapshot exists
        if not snapshot:
            return False
        
        # Check parameters is valid (can be empty dict)
        if snapshot.parameters is None:
            return False
        
        # Check parameters are valid types
        for key, value in snapshot.parameters.items():
            if value is None:
                return False
        
        return True
    
    def get_rollback_history(self) -> List[Dict[str, Any]]:
        """Get rollback operation history."""
        return self._rollback_log.copy()
    
    def undo_last_action(self) -> Dict[str, Any]:
        """
        Undo the last recorded action.
        
        Returns:
            Undo result.
        """
        if not self._analyzer._history:
            return {
                'success': False,
                'error': 'No history available',
                'timestamp': datetime.now().isoformat()
            }
        
        # Get the last parameter update
        for entry in reversed(self._analyzer._history):
            if entry.action in [AuditAction.PARAMETER_UPDATE, AuditAction.CONFIG_CHANGED]:
                if entry.parameters_before and entry.entry_id:
                    # Find previous state
                    prev_entry = None
                    for other in reversed(self._analyzer._history):
                        if other.entry_id == entry.entry_id:
                            continue
                        if other.parameters_after == entry.parameters_before:
                            prev_entry = other
                            break
                    
                    if prev_entry:
                        return self.rollback_to_snapshot(prev_entry.entry_id)
        
        return {
            'success': False,
            'error': 'Could not determine previous state',
            'timestamp': datetime.now().isoformat()
        }
    
    def clear_rollbacks(self) -> None:
        """Clear rollback history."""
        self._rollback_log.clear()
    
    @property
    def analyzer(self) -> ParameterAnalyzer:
        """Get associated analyzer."""
        return self._analyzer


class AuditTrailLogger:
    """
    Comprehensive audit trail logging for all simulation activities.
    
    Tracks all relevant operations with timestamps, actors, and context
    for compliance, debugging, and forensic analysis.
    """
    
    def __init__(self, parameter_analyzer: Optional[ParameterAnalyzer] = None):
        """
        Initialize the audit logger.
        
        Args:
            parameter_analyzer: Optional shared analyzer instance.
        """
        self._analyzer = parameter_analyzer or ParameterAnalyzer()
        self._audit_log: List[AuditLogEntry] = []
        self._max_log_size: int = 10000  # Maximum entries to keep
        self._event_handlers: List[callable] = []
    
    def register_analyzer(self, analyzer: ParameterAnalyzer) -> None:
        """Register an external analyzer instance."""
        self._analyzer = analyzer
    
    def log_event(self, level: str, message: str, context: Optional[Dict[str, Any]] = None) -> AuditLogEntry:
        """
        Log an audit event.
        
        Args:
            level: Log level (INFO, WARNING, ERROR, DEBUG).
            message: Event message.
            context: Optional context dictionary.
            
        Returns:
            Created audit log entry.
        """
        entry = AuditLogEntry(level, message, context)
        self._audit_log.append(entry)
        
        # Enforce max log size
        if len(self._audit_log) > self._max_log_size:
            self._audit_log = self._audit_log[-self._max_log_size:]
        
        # Notify handlers
        for handler in self._event_handlers:
            try:
                handler(entry)
            except Exception:
                pass  # Don't let handler errors affect logging
        
        return entry
    
    def log_parameter_change(self, old_value: Any, new_value: Any, parameter_name: str,
                            actor: str, context: Optional[Dict[str, Any]] = None) -> None:
        """
        Log a parameter change event.
        
        Args:
            old_value: Previous value.
            new_value: New value.
            parameter_name: Name of the parameter.
            actor: Who made the change.
            context: Additional context.
        """
        message = f"Parameter '{parameter_name}' changed from {old_value} to {new_value}"
        log_context = {
            'change_type': 'parameter',
            'parameter': parameter_name,
            'actor': actor,
            'old_value': old_value,
            'new_value': new_value,
            **(context or {})
        }
        
        entry = self.log_event('INFO', message, log_context)
        
        # Also create history entry
        self._analyzer.add_history_entry(ParameterHistoryEntry(
            timestamp=entry.timestamp,
            action=AuditAction.MANUAL_OVERRIDE if actor == 'user' else AuditAction.PARAMETER_UPDATE,
            profile_info={'actor': actor},
            parameters_before={parameter_name: old_value} if old_value is not None else None,
            parameters_after={parameter_name: new_value},
            metadata={'entry_id': entry.id}
        ))
    
    def log_simulation_start(self, simulation_name: str, config: Dict[str, Any]) -> None:
        """Log simulation start."""
        self.log_event('INFO', f"Simulation '{simulation_name}' started", {
            'event_type': 'simulation_start',
            'simulation': simulation_name,
            'config_summary': {k: '<hidden>' if 'password' in k.lower() else v 
                             for k, v in config.items()}
        })
    
    def log_simulation_end(self, simulation_name: str, success: bool, duration: float) -> None:
        """Log simulation end."""
        status = "completed" if success else "failed"
        self.log_event('INFO', f"Simulation '{simulation_name}' {status}", {
            'event_type': 'simulation_end',
            'simulation': simulation_name,
            'success': success,
            'duration': duration
        })
    
    def add_event_handler(self, handler: callable) -> None:
        """
        Register an event handler for audit events.
        
        Args:
            handler: Function to call on each event (receives AuditLogEntry).
        """
        self._event_handlers.append(handler)  # type: ignore
    
    def get_events(self, level: Optional[str] = None, 
                   since: Optional[datetime] = None,
                   limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get audit events.
        
        Args:
            level: Filter by log level.
            since: Only events after this datetime.
            limit: Maximum number of events.
            
        Returns:
            List of event dictionaries.
        """
        filtered = list(self._audit_log)
        
        if level:
            filtered = [e for e in filtered if e.level == level.upper()]
        
        if since:
            filtered = [e for e in filtered if e.timestamp >= since]
        
        # Reverse and slice to get newest first with limit
        filtered.reverse()
        return [e.to_dict() for e in filtered[:limit]]
    
    def export_audit_trail(self, format: str = 'json') -> str:
        """
        Export the complete audit trail.
        
        Args:
            format: Output format ('json' or 'text').
            
        Returns:
            Formatted audit trail string.
        """
        if format == 'json':
            return json.dumps([e.to_dict() for e in self._audit_log], indent=2)
        else:
            lines = ["AUDIT TRAIL EXPORT", "=" * 50]
            for entry in self._audit_log:
                lines.append(f"[{entry.timestamp}] [{entry.level}] {entry.message}")
                if entry.context:
                    for k, v in entry.context.items():
                        lines.append(f"    {k}: {v}")
            return "\n".join(lines)
    
    def clear_log(self) -> None:
        """Clear the audit log."""
        self._audit_log.clear()
    
    @property
    def analyzer(self) -> ParameterAnalyzer:
        """Get associated analyzer."""
        return self._analyzer
    
    @property
    def log_count(self) -> int:
        """Get number of logged events."""
        return len(self._audit_log)
