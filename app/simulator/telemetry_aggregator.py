"""Telemetry aggregator for collecting and managing simulation frames."""

import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, TypeVar

T = TypeVar('T')


@dataclass
class FrameMetadata:
    """Metadata for a single telemetry frame."""
    
    timestamp: float
    sequence_number: int
    source_id: str
    frame_type: str
    is_valid: bool
    validation_errors: List[str] = field(default_factory=list)
    collected_at: float = field(default_factory=time.time)
    
    @property
    def age(self) -> float:
        """Return the age of the frame in seconds."""
        return time.time() - self.timestamp


@dataclass
class TelemetryFrame:
    """A complete telemetry frame with metadata and data."""
    
    metadata: FrameMetadata
    data: Dict[str, Any]
    frame_type: str


@dataclass
class TelemetryStats:
    """Statistics about collected telemetry."""
    
    total_frames: int
    valid_frames: int
    invalid_frames: int
    dropped_frames: int
    oldest_timestamp: Optional[float]
    newest_timestamp: Optional[float]
    collection_start_time: float
    collection_end_time: Optional[float]
    
    @property
    def validity_rate(self) -> float:
        """Calculate the validity rate (0.0 to 1.0)."""
        if self.total_frames == 0:
            return 0.0
        return self.valid_frames / self.total_frames
    
    @property
    def drop_rate(self) -> float:
        """Calculate the drop rate (0.0 to 1.0)."""
        if self.total_frames == 0:
            return 0.0
        return self.dropped_frames / self.total_frames


class TelemetryCollector:
    """
    Aggregator that collects telemetry frames with circular buffer support.
    
    Features:
    - Collects frames from multiple sources
    - Validates timestamps against configurable thresholds
    - Maintains a circular buffer with configurable max size
    - Dropped old frames when buffer is full
    - Supports export in multiple formats
    - Provides filtering and query capabilities
    
    Example:
        >>> collector = TelemetryCollector(max_buffer_size=1000)
        >>> collector.add_frame("sensor_1", "temperature", {"value": 25.5})
        >>> frames = collector.query(timestamp_range=(1000.0, 2000.0))
        >>> stats = collector.get_stats()
    """
    
    DEFAULT_MAX_AGE_SECONDS = 3600.0  # 1 hour
    DEFAULT_MIN_TIMESTAMP_TOLERANCE = 0.1  # 100ms tolerance
    
    def __init__(
        self,
        max_buffer_size: int = 10000,
        max_age_seconds: Optional[float] = None,
        min_timestamp_tolerance: Optional[float] = None,
        auto_cleanup: bool = True,
    ):
        """
        Initialize the telemetry collector.
        
        Args:
            max_buffer_size: Maximum number of frames to keep in buffer.
                When exceeded, oldest frames are dropped.
            max_age_seconds: Maximum age of frames before considered stale.
                If None, uses DEFAULT_MAX_AGE_SECONDS.
            min_timestamp_tolerance: Minimum acceptable timestamp difference.
                Frames within this tolerance of current time may be rejected.
                If None, uses DEFAULT_MIN_TIMESTAMP_TOLERANCE.
            auto_cleanup: Whether to automatically remove stale frames.
        """
        self.max_buffer_size = max_buffer_size
        self.max_age_seconds = max_age_seconds or self.DEFAULT_MAX_AGE_SECONDS
        self.min_timestamp_tolerance = min_timestamp_tolerance or self.DEFAULT_MIN_TIMESTAMP_TOLERANCE
        
        self.auto_cleanup = auto_cleanup
        
        # Circular buffer using deque for efficient rotation
        self._buffer: deque[TelemetryFrame] = deque(maxlen=max_buffer_size)
        
        # Sequence counter per source
        self._source_sequences: Dict[str, int] = {}
        
        # Global sequence number
        self._global_sequence = 0
        
        # Collection tracking
        self._collection_start_time = time.time()
        self._collection_end_time: Optional[float] = None
        self._is_active = True
        
        # Stats counters
        self._total_frames = 0
        self._valid_frames = 0
        self._invalid_frames = 0
        self._dropped_frames = 0
        
        # Registered callbacks
        self._validators: List[Callable[[Dict[str, Any]], List[str]]] = []
        self._frame_handlers: List[Callable[[Dict[str, Any], FrameMetadata], None]] = []
        
        # Add default validator
        self.register_validator(self._default_timestamp_validator)
    
    def add_frame(
        self,
        source_id: str,
        frame_type: str,
        data: Dict[str, Any],
        timestamp: Optional[float] = None,
        force_valid: bool = False,
    ) -> bool:
        """
        Add a new telemetry frame to the collector.
        
        Args:
            source_id: Identifier for the source of this frame.
            frame_type: Type/category of the frame.
            data: Frame payload/data.
            timestamp: Timestamp of the frame. If None, uses current time.
            force_valid: If True, skip validation. Use with caution.
            
        Returns:
            True if frame was added successfully, False otherwise.
        """
        if not self._is_active:
            return False
        
        # Generate timestamp if not provided
        if timestamp is None:
            timestamp = time.time()
        
        # Increment source-specific sequence
        self._source_sequences[source_id] = self._source_sequences.get(source_id, 0) + 1
        source_seq = self._source_sequences[source_id]
        
        # Increment global sequence
        self._global_sequence += 1
        global_seq = self._global_sequence
        
        # Validate frame
        validation_errors = []
        is_valid = True
        
        if not force_valid:
            for validator in self._validators:
                errors = validator(data)
                validation_errors.extend(errors)
            
            is_valid = len(validation_errors) == 0
            
            if not is_valid:
                self._invalid_frames += 1
            else:
                self._valid_frames += 1
        
        # Create frame metadata
        metadata = FrameMetadata(
            timestamp=timestamp,
            sequence_number=source_seq,
            source_id=source_id,
            frame_type=frame_type,
            is_valid=is_valid,
            validation_errors=validation_errors,
            collected_at=time.time(),
        )
        
        # Store frame in buffer
        metadata = FrameMetadata(
            timestamp=timestamp,
            sequence_number=source_seq,
            source_id=source_id,
            frame_type=frame_type,
            is_valid=is_valid,
            validation_errors=validation_errors,
            collected_at=time.time(),
        )
        
        frame_record = TelemetryFrame(
            metadata=metadata,
            data=data,
            frame_type=frame_type,
        )
        
        self._buffer.append(frame_record)
        self._total_frames += 1
        
        # Trigger frame handlers for valid frames
        if is_valid and self._frame_handlers:
            for handler in self._frame_handlers:
                try:
                    handler(data, metadata)
                except Exception as e:
                    # Don't let handler errors break frame collection
                    pass
        
        return is_valid
    
    def _default_timestamp_validator(self, data: Dict[str, Any]) -> List[str]:
        """Default validator for timestamp consistency."""
        errors = []
        
        # Check for explicit timestamp field in data
        if "timestamp" in data:
            data_ts = data["timestamp"]
            current_ts = time.time()
            
            # Check if timestamp is too far in the future
            if data_ts > current_ts + self.min_timestamp_tolerance:
                errors.append(f"Future timestamp detected: {data_ts}")
            
            # Check if timestamp is way too far in the past
            age = current_ts - data_ts
            if age > self.max_age_seconds * 2:
                errors.append(f"Timestamp too old: {age:.2f}s")
        
        return errors
    
    def _handle_buffer_overflow(self):
        """Handle buffer overflow by dropping oldest frames."""
        excess = len(self._buffer) - self.max_buffer_size
        for _ in range(excess):
            if self._buffer:
                self._buffer.popleft()
                self._dropped_frames += 1
    
    def cleanup_stale_frames(self) -> int:
        """
        Remove frames older than max_age_seconds.
        
        Returns:
            Number of frames removed.
        """
        if not self.auto_cleanup:
            return 0
        
        cutoff_time = time.time() - self.max_age_seconds
        frames_to_keep = []
        removed_count = 0
        
        for frame in self._buffer:
            if frame.metadata.timestamp < cutoff_time:
                removed_count += 1
            else:
                frames_to_keep.append(frame)
        
        if removed_count > 0:
            self._buffer = deque(frames_to_keep, maxlen=self.max_buffer_size)
        
        return removed_count
    
    def get_frame_count(self) -> int:
        """Return the total number of frames currently in the buffer."""
        return len(self._buffer)
    
    def get_stats(self) -> TelemetryStats:
        """Get comprehensive statistics about collected telemetry."""
        timestamps = [f.metadata.timestamp for f in self._buffer] if self._buffer else []
        
        return TelemetryStats(
            total_frames=self._total_frames,
            valid_frames=self._valid_frames,
            invalid_frames=self._invalid_frames,
            dropped_frames=self._dropped_frames,
            oldest_timestamp=min(timestamps) if timestamps else None,
            newest_timestamp=max(timestamps) if timestamps else None,
            collection_start_time=self._collection_start_time,
            collection_end_time=self._collection_end_time,
        )
    
    def query(
        self,
        source_id: Optional[str] = None,
        frame_type: Optional[str] = None,
        timestamp_range: Optional[tuple] = None,
        is_valid: Optional[bool] = None,
        limit: Optional[int] = None,
        reverse: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Query frames with various filters.
        
        Args:
            source_id: Filter by source ID.
            frame_type: Filter by frame type.
            timestamp_range: Tuple of (start, end) timestamps.
            is_valid: Filter by validity status.
            limit: Maximum number of results to return.
            reverse: Return results in reverse chronological order.
            
        Returns:
            List of matching frames.
        """
        results = []
        
        for frame in self._buffer:
            metadata = frame.metadata
            
            # Apply filters
            if source_id is not None and metadata.source_id != source_id:
                continue
            
            if frame_type is not None and metadata.frame_type != frame_type:
                continue
            
            if timestamp_range is not None:
                ts_start, ts_end = timestamp_range
                if not (ts_start <= metadata.timestamp <= ts_end):
                    continue
            
            if is_valid is not None and metadata.is_valid != is_valid:
                continue
            
            results.append(TelemetryFrame(
                metadata=metadata,
                data=frame.data,
                frame_type=frame.frame_type,
            ))
        
        # Apply ordering
        if reverse:
            results.reverse()
        
        # Apply limit
        if limit is not None:
            results = results[:limit]
        
        return results
    
    def query_latest(
        self,
        n: int = 1,
        source_id: Optional[str] = None,
        frame_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get the N most recent frames.
        
        Args:
            n: Number of frames to retrieve.
            source_id: Optional filter by source.
            frame_type: Optional filter by type.
            
        Returns:
            List of latest frames.
        """
        all_frames = self.query(
            source_id=source_id,
            frame_type=frame_type,
            reverse=True,
        )
        return all_frames[:n]
    
    def query_by_source(self, source_id: str) -> List[Dict[str, Any]]:
        """Get all frames from a specific source."""
        return self.query(source_id=source_id)
    
    def query_by_frame_type(self, frame_type: str) -> List[Dict[str, Any]]:
        """Get all frames of a specific type."""
        return self.query(frame_type=frame_type)
    
    def query_invalid_frames(self) -> List[Dict[str, Any]]:
        """Get all frames that failed validation."""
        return self.query(is_valid=False)
    
    def export_json(self) -> str:
        """
        Export all frames as JSON string.
        
        Returns:
            JSON string representation of all frames.
        """
        import json
        
        frames_data = []
        for frame in self._buffer:
            frames_data.append({
                "metadata": {
                    "timestamp": frame.metadata.timestamp,
                    "sequence_number": frame.metadata.sequence_number,
                    "source_id": frame.metadata.source_id,
                    "frame_type": frame.metadata.frame_type,
                    "is_valid": frame.metadata.is_valid,
                    "validation_errors": frame.metadata.validation_errors,
                    "collected_at": frame.metadata.collected_at,
                    "age": frame.metadata.age,
                },
                "frame_type": frame.frame_type,
                "data": frame.data,
            })
        
        stats_dict = {
            "total_frames": self._total_frames,
            "valid_frames": self._valid_frames,
            "invalid_frames": self._invalid_frames,
            "dropped_frames": self._dropped_frames,
            "current_buffer_size": len(self._buffer),
        }
        
        export_data = {
            "stats": stats_dict,
            "frames": frames_data,
        }
        
        return json.dumps(export_data, indent=2)
    
    def export_csv(self, filepath: str, include_metadata: bool = True):
        """
        Export frames to CSV file.
        
        Args:
            filepath: Path to output CSV file.
            include_metadata: Whether to include metadata columns.
        """
        import csv
        
        frames = list(self._buffer)
        if not frames:
            with open(filepath, 'w', newline='') as f:
                f.write("# No data to export\n")
            return
        
        # Determine headers
        if include_metadata:
            headers = [
                "timestamp",
                "sequence_number", 
                "source_id",
                "frame_type",
                "is_valid",
                "collected_at",
                "age",
            ]
        else:
            headers = []
        
        # Add data columns from first frame
        sample_frame = frames[0]
        for key in sorted(sample_frame.data.keys()):
            headers.append(key)
        
        # Write CSV
        with open(filepath, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            
            for frame in frames:
                row = {}
                
                if include_metadata:
                    meta = frame.metadata
                    row.update({
                        "timestamp": meta.timestamp,
                        "sequence_number": meta.sequence_number,
                        "source_id": meta.source_id,
                        "frame_type": meta.frame_type,
                        "is_valid": meta.is_valid,
                        "collected_at": meta.collected_at,
                        "age": meta.age,
                    })
                
                # Add data fields from THIS frame
                for key, value in frame.data.items():
                    row[key] = value
                
                writer.writerow(row)
    
    def register_validator(self, validator: Callable[[Dict[str, Any]], List[str]]):
        """
        Register a custom validation function.
        
        Args:
            validator: Function that takes frame data and returns list of error strings.
        """
        self._validators.append(validator)
    
    def unregister_validator(self, validator: Callable[[Dict[str, Any]], List[str]]):
        """Unregister a validation function."""
        if validator in self._validators:
            self._validators.remove(validator)
    
    def add_frame_handler(self, handler: Callable[[Dict[str, Any], FrameMetadata], None]):
        """
        Register a callback to handle each new valid frame.
        
        Args:
            handler: Function called with (data, metadata) for each valid frame.
        """
        self._frame_handlers.append(handler)
    
    def remove_frame_handler(self, handler: Callable[[Dict[str, Any], FrameMetadata], None]):
        """Remove a registered frame handler."""
        if handler in self._frame_handlers:
            self._frame_handlers.remove(handler)
    
    def clear(self):
        """Clear all frames from the buffer."""
        self._buffer.clear()
        self._collection_end_time = time.time()
    
    def reset_stats(self):
        """Reset statistics counters but keep the buffer."""
        self._collection_end_time = time.time()
        self._total_frames = 0
        self._valid_frames = 0
        self._invalid_frames = 0
        self._dropped_frames = 0
    
    def start(self):
        """Start the collector."""
        if not self._is_active:
            self._is_active = True
            self._collection_start_time = time.time()
    
    def stop(self):
        """Stop the collector."""
        self._is_active = False
        self._collection_end_time = time.time()
    
    def is_running(self) -> bool:
        """Check if the collector is active."""
        return self._is_active
    
    def get_summary(self) -> Dict[str, Any]:
        """
        Get a summary of the collector state.
        
        Returns:
            Dictionary with summary information.
        """
        stats = self.get_stats()
        
        duration = 0.0
        if stats.collection_end_time:
            duration = stats.collection_end_time - stats.collection_start_time
        else:
            duration = time.time() - stats.collection_start_time
        
        sources = []
        frame_types = []
        for frame in self._buffer:
            sources.append(frame.metadata.source_id)
            frame_types.append(frame.frame_type)
        
        return {
            "is_active": self._is_active,
            "buffer_size": len(self._buffer),
            "max_buffer_size": self.max_buffer_size,
            "duration_seconds": duration,
            "total_frames": stats.total_frames,
            "valid_frames": stats.valid_frames,
            "invalid_frames": stats.invalid_frames,
            "dropped_frames": stats.dropped_frames,
            "validity_rate": stats.validity_rate,
            "drop_rate": stats.drop_rate,
            "sources": list(set(sources)),
            "frame_types": list(set(frame_types)),
        }


# Convenience functions for common use cases

def create_simulator_collector() -> TelemetryCollector:
    """Create a telemetry collector optimized for simulation use cases."""
    return TelemetryCollector(
        max_buffer_size=10000,
        max_age_seconds=3600.0,
        auto_cleanup=True,
    )


def create_streaming_collector(buffer_size: int = 1000) -> TelemetryCollector:
    """
    Create a telemetry collector optimized for streaming scenarios.
    
    Args:
        buffer_size: Size of circular buffer for streaming data.
    """
    return TelemetryCollector(
        max_buffer_size=buffer_size,
        max_age_seconds=300.0,  # 5 minutes for streaming
        auto_cleanup=True,
    )
