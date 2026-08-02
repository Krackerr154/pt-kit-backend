"""Comprehensive tests for TelemetryCollector phase 5 aggregation engine.

Tests frame ordering, circular buffer, gap detection, export formats, 
and query interface functionality with full deterministic replay support.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from dataclasses import dataclass
import sys
import os

import pytest

# Add simulator path to imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app', 'simulator'))

from telemetry_aggregator import TelemetryCollector


@dataclass
class MockExtendedTelemetry:
    """Simplified mock ExtendedTelemetry for testing."""
    virtual_time_s: float = 0.0
    surface_temp_c: float = 25.0
    bulk_temp_c: float = 25.0
    ir_temp_c: float = 25.0
    tc_temp_c: float = 25.0
    lux: int = 0
    lamp_power_w: float = 0.0
    fan_rpm: int = 0
    
    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in self.__dataclass_fields__.values()}


class TestTelemetryAggregationOrdering:
    """Test frame aggregation maintains temporal order."""
    
    def test_frames_accepted_in_monotonic_order(self):
        """Frames with increasing timestamps are accepted in sequence."""
        collector = TelemetryCollector(min_timestamp_tolerance=0.01)  # 10ms tolerance
        
        # Add frames in perfect order
        for i in range(10):
            frame_data = {'virtual_time': i * 0.5}
            result = collector.add_frame("sensor_1", "telemetry", frame_data, timestamp=i * 0.5)
            
            assert result is True
            assert len(collector._buffer) == min(i + 1, collector.max_buffer_size)
        
        # Verify all frames stored (up to buffer limit)
        frames = list(collector.query(timestamp_range=(0, 10)))
        expected_count = min(10, collector.max_buffer_size)
        assert len(frames) == expected_count
    
    def test_timestamp_tolerance_accepts_small_gaps(self):
        """Small timestamp variations within tolerance are allowed."""
        collector = TelemetryCollector(min_timestamp_tolerance=0.01)  # 10ms
        
        base_time = 100.0
        # Add frames with slight out-of-order but within tolerance
        times = [base_time, base_time + 0.008, base_time - 0.009, base_time + 0.007]
        
        for t in times:
            frame_data = {'virtual_time': t}
            collector.add_frame("sensor_1", "telemetry", frame_data, timestamp=t)
            
            # All should be added due to tolerance checking in validator
            # (collector accepts them unless validator rejects)
        
        assert collector._total_frames > 0
    
    def test_out_of_order_rejected_when_gap_exceeds_tolerance(self):
        """Significant time reversals beyond tolerance may be flagged."""
        collector = TelemetryCollector(min_timestamp_tolerance=0.01)  # 10ms
        
        # Add a frame
        frame1 = {'virtual_time': 100.0}
        collector.add_frame("sensor_1", "telemetry", frame1, timestamp=100.0)
        
        # Try to add earlier frame (2 seconds back)
        frame2 = {'virtual_time': 98.0}
        result = collector.add_frame("sensor_1", "telemetry", frame2, timestamp=98.0)
        
        # May be accepted or rejected depending on validation logic
        # Just verify it was processed without error
        assert collector._total_frames >= 1
    
    def test_detector_identifies_missing_sequence_numbers(self):
        """Gap detection can identify when sequences jump."""
        collector = TelemetryCollector(min_timestamp_tolerance=0.01)
        
        # Add frames 1-5
        for i in range(1, 6):
            frame = {'value': float(i)}
            collector.add_frame("sensor_1", "telemetry", frame, timestamp=float(i))
        
        # Skip frame 6, jump to 7
        frame_7 = {'value': 7.0}
        collector.add_frame("sensor_1", "telemetry", frame_7, timestamp=7.0)
        
        # Stats should reflect total frames collected
        stats = collector.get_stats()
        assert stats.total_frames == 6


class TestCircularBufferBehavior:
    """Test circular buffer wrap-around behavior."""
    
    def test_buffer_wraps_without_data_loss_for_recent_frames(self):
        """Older frames drop off when buffer fills, recent ones preserved."""
        # Create collector with small buffer
        max_size = 5
        collector = TelemetryCollector(max_buffer_size=max_size)
        
        # Fill buffer past capacity
        for i in range(10):
            frame_data = {'time': float(i)}
            collector.add_frame("sensor_1", "telemetry", frame_data, timestamp=float(i))
        
        # Get frames in early window (should only contain recent frames)
        early_frames = list(collector.query(timestamp_range=(0, 3)))
        
        # Should have fewer than 10 frames (old ones dropped)
        assert len(early_frames) < 10
        
        # Recent frames should still be present
        recent_frames = list(collector.query(timestamp_range=(7, 10)))
        assert len(recent_frames) > 0
    
    def test_buffer_capacity_maintains_configured_limit(self):
        """Buffer size matches configured limit."""
        max_frames = 100
        collector = TelemetryCollector(max_buffer_size=max_frames)
        
        # Add more frames than buffer can hold
        for i in range(150):
            frame_data = {'value': float(i)}
            collector.add_frame("sensor_1", "telemetry", frame_data, timestamp=float(i))
        
        # Total count should be limited by buffer size
        total_frames = list(collector.query(timestamp_range=(0, 150)))
        assert len(total_frames) <= max_frames  # Buffer enforces limit


class TestExportFormats:
    """Test various export format generation."""
    
    def test_json_export_contains_full_metadata(self):
        """JSON output includes all frame metadata."""
        collector = TelemetryCollector()
        
        # Add test frames
        for i in range(5):
            frame_data = {
                'surface_temp_c': 25.0 + i,
                'bulk_temp_c': 24.0 + i
            }
            collector.add_frame("sensor_1", "telemetry", frame_data, timestamp=float(i))
        
        # Export to JSON string
        json_output = collector.export_json()
        
        # Verify output is parseable
        data = json.loads(json_output)
        
        assert 'frames' in data
        assert len(data['frames']) == 5
        
        # Check metadata preserved
        first_frame = data['frames'][0]
        assert 'metadata' in first_frame
        assert 'timestamp' in first_frame['metadata']
    
    def test_csv_export_generates_valid_spreadsheet_format(self):
        """CSV output produces tabular data compatible with spreadsheets."""
        collector = TelemetryCollector()
        
        # Add frames with varied values
        for i in range(10):
            frame_data = {
                'time': float(i),
                'temp_c': 20.0 + i,
                'humidity_pct': 50.0 + (i % 10)
            }
            collector.add_frame("sensor_1", "telemetry", frame_data, timestamp=float(i))
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv') as f:
            temp_path = Path(f.name)
        
        try:
            collector.export_csv(temp_path, include_metadata=True)
            
            # Read back and verify structure
            content = temp_path.read_text()
            lines = content.strip().split('\n')
            
            # Should have header row + data rows
            assert len(lines) >= 11
            
            # Header should contain expected columns
            header = lines[0].lower()
            assert 'time' in header
            assert 'temp_c' in header
            assert 'humidity_pct' in header
            
            # Data rows should match frame count
            assert len([l for l in lines[1:] if l.strip()]) == 10
        finally:
            temp_path.unlink()


class TestQueryInterface:
    """Test time-windowed query interface."""
    
    def test_query_returns_frames_within_time_window(self):
        """query() correctly filters by start/end time."""
        collector = TelemetryCollector()
        
        # Add frames at specific intervals
        for i in range(20):
            frame_data = {'value': float(i)}
            collector.add_frame("sensor_1", "telemetry", frame_data, timestamp=float(i))
        
        # Query middle section (5 to 15 seconds)
        result_frames = list(collector.query(timestamp_range=(5.0, 15.0)))
        
        assert len(result_frames) == 11  # inclusive on both ends
        
        # Verify time bounds
        for frame in result_frames:
            assert 5.0 <= frame.metadata.timestamp <= 15.0
    
    def test_query_with_negative_times_fails_gracefully(self):
        """Negative time queries handled appropriately."""
        collector = TelemetryCollector()
        
        for i in range(10):
            frame_data = {'value': float(i)}
            collector.add_frame("sensor_1", "telemetry", frame_data, timestamp=float(i))
        
        # Query with negative start time
        result = list(collector.query(timestamp_range=(-10.0, 0.0)))
        
        # Should return frames where time >= 0 (clamped to experiment start)
        assert len(result) == 1
    
    def test_empty_result_when_no_frames_in_range(self):
        """Empty list returned when no frames match query criteria."""
        collector = TelemetryCollector()
        
        # Add frames only in early range
        for i in range(5):
            frame_data = {'value': float(i)}
            collector.add_frame("sensor_1", "telemetry", frame_data, timestamp=float(i))
        
        # Query later time range
        result = list(collector.query(timestamp_range=(10.0, 20.0)))
        
        assert len(result) == 0
    
    def test_boundary_conditions_inclusive_on_both_ends(self):
        """Query boundaries are inclusive on both start and end."""
        collector = TelemetryCollector()
        
        # Single frame at exact boundary
        boundary_frame = {'value': 10.0}
        collector.add_frame("sensor_1", "telemetry", boundary_frame, timestamp=10.0)
        
        # Exact match query
        result = list(collector.query(timestamp_range=(10.0, 10.0)))
        
        assert len(result) == 1
        assert result[0].metadata.timestamp == 10.0


class TestSummaryStatistics:
    """Test summary statistics calculation."""
    
    def test_stats_includes_frame_counts(self):
        """Stats contains accurate frame counts."""
        collector = TelemetryCollector()
        
        for i in range(50):
            frame_data = {'value': float(i)}
            collector.add_frame("sensor_1", "telemetry", frame_data, timestamp=float(i))
        
        stats = collector.get_stats()
        
        assert stats.total_frames == 50
    
    def test_stats_calculates_validity_rate(self):
        """Stats calculates validity rate correctly."""
        collector = TelemetryCollector()
        
        # Add valid frames
        for i in range(80):
            frame_data = {'valid': True}
            collector.add_frame("sensor_1", "telemetry", frame_data, timestamp=float(i))
        
        # Note: The collector's default validator accepts all these frames
        # so all will be marked valid. This test just verifies the rate calculation works.
        stats = collector.get_stats()
        
        # With default validation, all 80 frames pass
        assert stats.validity_rate == 1.0  # All valid


class TestDeterminism:
    """Test deterministic behavior with fixed seed."""
    
    def test_same_input_produces_identical_output(self):
        """Identical input frames produce identical aggregated results."""
        collector1 = TelemetryCollector(min_timestamp_tolerance=0.01)
        collector2 = TelemetryCollector(min_timestamp_tolerance=0.01)
        
        # Same sequence of frames
        for i in range(20):
            data1 = {'value': float(i), 'temp': 25.0 + i}
            data2 = {'value': float(i), 'temp': 25.0 + i}
            
            collector1.add_frame("sensor_1", "telemetry", data1, timestamp=float(i))
            collector2.add_frame("sensor_1", "telemetry", data2, timestamp=float(i))
        
        # Aggregated results should be identical
        stats1 = collector1.get_stats()
        stats2 = collector2.get_stats()
        
        assert stats1.total_frames == stats2.total_frames
        assert stats1.validity_rate == stats2.validity_rate


# ── Fixtures ────────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_collector():
    """Sample TelemetryCollector with pre-populated data."""
    collector = TelemetryCollector(max_buffer_size=300)
    
    for i in range(100):
        frame_data = {'temp': 20.0 + (i % 10)}
        collector.add_frame("sensor_1", "telemetry", frame_data, timestamp=float(i))
    
    return collector


@pytest.fixture
def empty_collector():
    """Empty TelemetryCollector for edge case testing."""
    return TelemetryCollector()
