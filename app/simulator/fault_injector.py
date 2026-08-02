"""Fault injection framework for UART communication layer.

This module provides deterministic fault injection for testing error handling
in the virtual UART and ESP32 bridge simulation. All faults are seeded with
a fixed random number generator for reproducible traces.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional, List


class FaultType(IntEnum):
    """Types of faults that can be injected."""
    
    BIT_FLIP_ERROR = 1        # Single-bit flips in payload
    LATENCY_SPIKE = 2         # Artificial delay simulation
    CONNECTION_DROP = 3       # Complete disconnection
    PACKET_LOSS = 4           # Discard packets randomly


@dataclass
class FaultEvent:
    """Record of an injected fault event."""
    
    timestamp_s: float
    fault_type: FaultType
    description: str
    affected_packet_sequence: Optional[int] = None
    
    def to_dict(self) -> dict:
        return {
            'timestamp_s': self.timestamp_s,
            'fault_type': int(self.fault_type),
            'description': self.description,
            'affected_packet_sequence': self.affected_packet_sequence,
        }


class FaultInjector:
    """Deterministic fault injection for UART/ESP32 simulation.
    
    Features:
    - Seeded random number generation for reproducibility
    - Configurable injection probability (0.0-1.0)
    - Multiple fault types: bit flip, latency spike, connection drop, packet loss
    - Comprehensive logging for golden trace comparison
    
    Usage:
        injector = FaultInjector(seed=42)
        injector.set_active(True)
        
        # Inject faults at 5% probability
        injector.set_injection_rate(0.05)
        
        # During simulation
        if injector.inject_bit_flip(payload):
            # Payload corrupted, will fail checksum
            pass
    """
    
    def __init__(self, seed: int = 42):
        """Initialize fault injector with fixed seed.
        
        Args:
            seed: Random seed for determinism (default 42)
        """
        self._seed = seed
        self._rng = random.Random(seed)
        self._active = False
        self._injection_probability = 0.0
        
        # Event logging
        self._events: List[FaultEvent] = []
        self._current_timestamp_s = 0.0
        
        # Statistics
        self._total_attempts = 0
        self._successful_injections = 0
        
    def set_active(self, active: bool) -> None:
        """Enable or disable fault injection.
        
        Args:
            active: True to enable injection, False to disable
        """
        self._active = active
        
    def set_injection_rate(self, rate: float) -> None:
        """Set probability of injection per operation.
        
        Args:
            rate: Probability between 0.0 (never) and 1.0 (always)
        """
        if not 0.0 <= rate <= 1.0:
            raise ValueError("Injection rate must be between 0.0 and 1.0")
        
        self._injection_probability = rate
        
    def advance_time(self, delta_s: float) -> None:
        """Advance simulation clock for event timestamps.
        
        Args:
            delta_s: Time increment in seconds
        """
        self._current_timestamp_s += delta_s
        
    def inject_bit_flip(self, payload: bytes) -> bytes:
        """Inject single-bit flip into payload bytes.
        
        Used to test checksum validation and error detection.
        
        Args:
            payload: Original payload bytes
            
        Returns:
            Modified payload with one bit flipped (or original if no injection)
        """
        self._total_attempts += 1
        
        if not self._active:
            return payload
        
        if self._rng.random() > self._injection_probability:
            return payload
        
        # Select random byte to corrupt
        byte_idx = self._rng.randint(0, len(payload) - 1)
        bit_idx = self._rng.randint(0, 7)
        
        original_byte = payload[byte_idx]
        flipped_byte = original_byte ^ (1 << bit_idx)
        
        corrupted = bytearray(payload)
        corrupted[byte_idx] = flipped_byte
        
        # Log event
        self._events.append(FaultEvent(
            timestamp_s=self._current_timestamp_s,
            fault_type=FaultType.BIT_FLIP_ERROR,
            description=f"Bit {bit_idx} flipped in byte {byte_idx}: {original_byte:02x} → {flipped_byte:02x}",
        ))
        
        self._successful_injections += 1
        
        return bytes(corrupted)
    
    def should_drop_connection(self) -> bool:
        """Check if connection should be dropped now.
        
        Returns:
            True if connection should be dropped (for testing reconnection logic)
        """
        self._total_attempts += 1
        
        if not self._active:
            return False
        
        if self._rng.random() > self._injection_probability:
            return False
        
        # Log event
        self._events.append(FaultEvent(
            timestamp_s=self._current_timestamp_s,
            fault_type=FaultType.CONNECTION_DROP,
            description="Connection dropped (testing reconnection)",
        ))
        
        self._successful_injections += 1
        
        return True
    
    def should_drop_packet(self) -> bool:
        """Check if current packet should be lost (not transmitted).
        
        Returns:
            True if packet should be silently discarded
        """
        self._total_attempts += 1
        
        if not self._active:
            return False
        
        if self._rng.random() > self._injection_probability:
            return False
        
        # Log event
        self._events.append(FaultEvent(
            timestamp_s=self._current_timestamp_s,
            fault_type=FaultType.PACKET_LOSS,
            description="Packet dropped (simulating network loss)",
        ))
        
        self._successful_injections += 1
        
        return True
    
    def should_delay_transmission(self, base_latency_us: float) -> float:
        """Calculate artificial latency spike.
        
        Returns:
            Additional latency in microseconds (0.0 if no spike)
        """
        self._total_attempts += 1
        
        if not self._active:
            return 0.0
        
        if self._rng.random() > self._injection_probability:
            return 0.0
        
        # Spike latency by 100x normal transmission time
        spike_latency = base_latency_us * 100.0
        
        # Log event
        self._events.append(FaultEvent(
            timestamp_s=self._current_timestamp_s,
            fault_type=FaultType.LATENCY_SPIKE,
            description=f"Latency spike: +{spike_latency:.0f} µs",
        ))
        
        self._successful_injections += 1
        
        return spike_latency
    
    def reset_statistics(self) -> None:
        """Clear all statistics and event logs."""
        self._events.clear()
        self._total_attempts = 0
        self._successful_injections = 0
        self._current_timestamp_s = 0.0
    
    def get_events(self) -> List[FaultEvent]:
        """Get list of all injected fault events.
        
        Returns:
            List of FaultEvent objects
        """
        return self._events.copy()
    
    def get_summary(self) -> dict:
        """Get summary statistics.
        
        Returns:
            Dictionary with injection statistics
        """
        return {
            'total_attempts': self._total_attempts,
            'successful_injections': self._successful_injections,
            'injection_rate': self._successful_injections / max(1, self._total_attempts),
            'events': [e.to_dict() for e in self._events],
        }


__all__ = ['FaultInjector', 'FaultType', 'FaultEvent']
