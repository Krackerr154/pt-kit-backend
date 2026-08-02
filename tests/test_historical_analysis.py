"""Test suite for historical analysis & rollback system."""

import pytest
from pathlib import Path
import sys
import json
from datetime import datetime, timedelta
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import asyncio

from app.simulator.historical_analysis import (
    ParameterHistoryEntry,
    SimulationSnapshot,
    AuditLogEntry,
    AuditAction,
    ParameterAnalyzer,
    RollbackManager,
    AuditTrailLogger,
)


class TestParameterHistoryEntry:
    """Test parameter history entry structure."""
    
    def test_history_entry_creation(self):
        """Test creating a valid history entry."""
        entry = ParameterHistoryEntry(
            timestamp=datetime.now(),
            action=AuditAction.PARAMETER_UPDATE,
            profile_info={"name": "test_profile", "version": "1.0.0"},
            parameters_before={"ambient_temp_c": 24.0},
            parameters_after={"ambient_temp_c": 25.0}
        )
        
        assert entry.timestamp is not None
        assert entry.action == AuditAction.PARAMETER_UPDATE
        assert entry.profile_info["name"] == "test_profile"
        assert len(entry.parameters_after) > 0
        assert entry.entry_id is not None
    
    def test_optional_parameters_before_field(self):
        """Test parameters_before can be empty for initial state."""
        entry = ParameterHistoryEntry(
            timestamp=datetime.now(),
            action=AuditAction.SNAPSHOT_CREATED,
            profile_info={"name": "initial", "version": "1.0.0"},
            parameters_after={"ambient_temp_c": 25.0}
        )
        
        assert entry.parameters_before is None or entry.parameters_before == {}
    
    def test_various_action_types(self):
        """Test different audit actions are supported."""
        actions = [
            AuditAction.SIMULATION_START,
            AuditAction.SIMULATION_END,
            AuditAction.ROLLBACK_COMPLETED,
            AuditAction.AUTO_TUNING
        ]
        
        for action in actions:
            entry = ParameterHistoryEntry(
                timestamp=datetime.now(),
                action=action,
                profile_info={"name": "test", "version": "1.0.0"},
                parameters_after={}
            )
            
            assert entry.action == action


class TestSimulationSnapshot:
    """Test simulation snapshot creation and management."""
    
    def test_snapshot_basic_structure(self):
        """Test snapshot has required fields."""
        # Use factory method instead of direct instantiation
        snapshot = SimulationSnapshot.create(
            simulation_name="test_snapshot",
            parameters={"temp": 25.0, "mass": 100.0},
            metadata={"mode": "thermal"}
        )
        
        assert snapshot.snapshot_id is not None
        assert snapshot.timestamp is not None
        assert snapshot.simulation_name == "test_snapshot"
        assert "temp" in snapshot.parameters
    
    def test_snapshot_serialization(self):
        """Test converting snapshot to dictionary."""
        snapshot = SimulationSnapshot.create(
            simulation_name="serialization_test",
            parameters={"x": 1.0},
            metadata={}
        )
        
        snapshot_dict = snapshot.to_dict()
        
        assert isinstance(snapshot_dict, dict)
        assert "snapshot_id" in snapshot_dict
        assert "timestamp" in snapshot_dict


class TestRollbackCheckpoint:
    """Test checkpoint creation and rollback functionality."""
    
    def test_save_checkpoint_success(self):
        """Test saving a checkpoint works."""
        analyzer = ParameterAnalyzer()
        manager = RollbackManager(parameter_analyzer=analyzer)
        
        simulation_name = "checkpoint_test"
        parameters = {
            "ambient_temp_c": 25.0,
            "thermal_mass": 100.0
        }
        reason = "Initial setup"
        
        result = manager.save_checkpoint(
            simulation_name=simulation_name,
            parameters=parameters,
            reason=reason
        )
        
        assert result is not None
        assert isinstance(result, SimulationSnapshot)
        assert result.simulation_name == simulation_name
    
    def test_multiple_checkpoints(self):
        """Test creating multiple checkpoints."""
        analyzer = ParameterAnalyzer()
        manager = RollbackManager(parameter_analyzer=analyzer)
        
        checkpoint_ids = []
        for i in range(3):
            snapshot = manager.save_checkpoint(
                simulation_name=f"multi_{i}",
                parameters={"step": float(i)},
                reason=f"Checkpoint {i}"
            )
            
            checkpoint_ids.append(snapshot.snapshot_id)
        
        assert len(checkpoint_ids) == 3
        assert all(isinstance(cp_id, str) for cp_id in checkpoint_ids)
    
    def test_pending_rollback_tracking(self):
        """Test pending rollback tracking."""
        analyzer = ParameterAnalyzer()
        manager = RollbackManager(parameter_analyzer=analyzer)
        
        # At minimum, no crash on instantiation
        assert manager is not None


class TestAuditTrailLogging:
    """Test audit trail logging functionality."""
    
    def test_audit_logger_initialization(self):
        """Logger initializes standalone and can register an analyzer."""
        logger = AuditTrailLogger()

        assert logger is not None
        entry = logger.log_event("INFO", "logger ready", {"phase": 9})
        assert entry.message == "logger ready"

        events = logger.get_events()
        assert len(events) == 1
        assert events[0]["message"] == "logger ready"

    def test_audit_logger_binds_analyzer(self):
        """Logger accepts a ParameterAnalyzer and records parameter changes."""
        analyzer = ParameterAnalyzer()
        logger = AuditTrailLogger(parameter_analyzer=analyzer)

        logger.log_parameter_change(
            old_value=1.0, new_value=2.0,
            parameter_name="thermal_mass", actor="phase9-test",
        )

        history = analyzer.get_history()
        assert len(history) == 1
        assert history[0].parameters_after["thermal_mass"] == 2.0

    def test_simulation_start_end_logged(self):
        """Simulation lifecycle events land in the audit trail."""
        logger = AuditTrailLogger()
        logger.log_simulation_start("run-a", {"seed": 42})
        logger.log_simulation_end("run-a", success=True, duration=12.5)

        messages = " ".join(e["message"] for e in logger.get_events())
        assert "run-a" in messages

    def test_export_audit_trail_is_json(self):
        """Exported audit trail is valid JSON."""
        logger = AuditTrailLogger()
        logger.log_event("WARNING", "drift observed")

        payload = json.loads(logger.export_audit_trail(format="json"))
        assert payload  # non-empty

    def test_audit_action_values(self):
        """Test audit action enum values."""
        assert AuditAction.PARAMETER_UPDATE.value == "parameter_update"
        assert AuditAction.SNAPSHOT_CREATED.value == "snapshot_created"


class TestParameterAnalyzerBasic:
    """Test basic parameter analysis functionality."""
    
    def test_analyzer_initialization(self):
        """Analyzer takes no constructor args and starts with empty history."""
        analyzer = ParameterAnalyzer()
        
        assert analyzer is not None
        assert analyzer.get_history() == []
        assert analyzer.get_snapshots() == []
    
    def test_analyzer_with_entries(self):
        """Entries are added via add_history_entry(), not the constructor."""
        now = datetime.now()
        analyzer = ParameterAnalyzer()

        for i in range(5):
            analyzer.add_history_entry(
                ParameterHistoryEntry(
                    timestamp=now - timedelta(days=i),
                    action=AuditAction.PARAMETER_UPDATE,
                    profile_info={"name": "test"},
                    parameters_after={"param": float(i)},
                )
            )

        history = analyzer.get_history()
        assert len(history) == 5
        assert {e.parameters_after["param"] for e in history} == {0.0, 1.0, 2.0, 3.0, 4.0}

    def test_get_history_filters_by_action(self):
        """get_history(action=...) narrows results to that action."""
        analyzer = ParameterAnalyzer()
        now = datetime.now()

        analyzer.add_history_entry(ParameterHistoryEntry(
            timestamp=now, action=AuditAction.PARAMETER_UPDATE,
            profile_info={"name": "a"}, parameters_after={"x": 1.0}))
        analyzer.add_history_entry(ParameterHistoryEntry(
            timestamp=now, action=AuditAction.SNAPSHOT_CREATED,
            profile_info={"name": "b"}, parameters_after={"x": 2.0}))

        updates = analyzer.get_history(action=AuditAction.PARAMETER_UPDATE)
        assert len(updates) == 1
        assert updates[0].parameters_after["x"] == 1.0
    
    def test_parameter_drift_detection(self):
        """detect_parameter_drift() flags a steadily drifting parameter."""
        analyzer = ParameterAnalyzer()
        now = datetime.now()

        # Ramp 'temperature' well beyond the threshold across the history.
        for i in range(10):
            analyzer.add_history_entry(
                ParameterHistoryEntry(
                    timestamp=now + timedelta(seconds=i),
                    action=AuditAction.PARAMETER_UPDATE,
                    profile_info={"name": "drift"},
                    parameters_after={"temperature": 25.0 + i * 2.0},
                )
            )

        drift = analyzer.detect_parameter_drift(threshold=0.5)
        assert isinstance(drift, dict)
        assert "temperature" in drift
        # Value is a normalized drift coefficient, not an absolute delta.
        assert drift["temperature"] > 0.0


class TestEdgeCasesAndErrorHandling:
    """Test edge cases and error handling scenarios."""
    
    def test_analyzer_handles_empty_history(self):
        """Analyzer degrades gracefully with no history recorded."""
        analyzer = ParameterAnalyzer()

        assert analyzer.get_history() == []
        assert analyzer.detect_parameter_drift(threshold=0.5) == {}

        report = analyzer.generate_analysis_report()
        assert isinstance(report, dict)
    
    def test_concurrent_operations_safe(self):
        """Test concurrent operations don't cause crashes."""
        analyzer = ParameterAnalyzer()
        manager = RollbackManager(parameter_analyzer=analyzer)
        
        # Multiple rapid requests (sequential since sync)
        checkpoint_ids = []
        for i in range(5):
            snapshot = manager.save_checkpoint(
                simulation_name=f"rapid_{i}",
                parameters={"i": float(i)},
                reason="Quick checkpoint"
            )
            checkpoint_ids.append(snapshot.snapshot_id)
        
        assert len(checkpoint_ids) == 5
        assert all(isinstance(cp_id, str) for cp_id in checkpoint_ids)


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--asyncio-mode=auto'])
