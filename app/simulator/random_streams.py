"""Independent deterministic RNG streams for simulator components."""

from __future__ import annotations

import random


class RNGStreams:
    """Independent deterministic RNG streams for reproducibility.
    
    Each component gets its own seeded Random instance to ensure that
    faults in one subsystem do not affect the noise sequence of another.
    
    Key requirement: Adding a network fault must NOT change the physical-noise
    sequence (independent streams). This is guaranteed because each stream
    operates independently from its own internal state.
    
    Args:
        seed: Base seed for all streams. Each stream derives its seed from
              the base seed using a simple derivation scheme to ensure
              independence while maintaining reproducibility.
    
    Attributes:
        ir_noise: RNG for IR sensor noise (surface temperature)
        tc_noise: RNG for thermocouple noise (bulk temperature)
        lux_noise: RNG for lux sensor noise
        plant_disturbance: RNG for plant disturbances (thermal fluctuations)
        uart_fault: RNG for UART communication faults
        network_fault: RNG for network communication faults
    
    Example:
        >>> rng = RNGStreams(42)
        >>> ir_val = rng.ir_noise.gauss(0, 1)  # IR noise sample
        >>> tc_val = rng.tc_noise.gauss(0, 1)  # TC noise sample - independent!
        >>> # Even if we don't use network_fault, physical noise is unchanged
        >>> lux_val = rng.lux_noise.gauss(0, 1)
    """
    
    # Derivation multipliers to ensure stream independence
    _DERIVATION_MULTIPLIERS = {
        "ir_noise": 1009,
        "tc_noise": 1013,
        "lux_noise": 1019,
        "plant_disturbance": 1021,
        "uart_fault": 1031,
        "network_fault": 1033,
    }
    
    def __init__(self, seed: int = 42):
        """Initialize RNG streams with independent derived seeds.
        
        Args:
            seed: Base seed value. Default is 42 for reproducibility.
        """
        self._seed = seed
        
        # Create independent streams by deriving unique seeds
        self._ir_noise = random.Random()
        self._tc_noise = random.Random()
        self._lux_noise = random.Random()
        self._plant_disturbance = random.Random()
        self._uart_fault = random.Random()
        self._network_fault = random.Random()
        
        for name, stream in (
            ("ir_noise", self._ir_noise),
            ("tc_noise", self._tc_noise),
            ("lux_noise", self._lux_noise),
            ("plant_disturbance", self._plant_disturbance),
            ("uart_fault", self._uart_fault),
            ("network_fault", self._network_fault),
        ):
            derived_seed = (seed * self._DERIVATION_MULTIPLIERS[name]) % (2**32)
            stream.seed(derived_seed)
    
    @property
    def ir_noise(self) -> random.Random:
        """Get RNG stream for IR sensor noise.
        
        Used for simulating IR sensor measurement noise and drift.
        """
        return self._ir_noise
    
    @property
    def tc_noise(self) -> random.Random:
        """Get RNG stream for thermocouple sensor noise.
        
        Used for simulating TC sensor measurement noise and drift.
        """
        return self._tc_noise
    
    @property
    def lux_noise(self) -> random.Random:
        """Get RNG stream for lux sensor noise.
        
        Used for simulating lux sensor measurement noise.
        """
        return self._lux_noise
    
    @property
    def plant_disturbance(self) -> random.Random:
        """Get RNG stream for plant disturbances.
        
        Used for simulating thermal fluctuations, ambient variations,
        and other environmental disturbances affecting the plant.
        """
        return self._plant_disturbance
    
    @property
    def uart_fault(self) -> random.Random:
        """Get RNG stream for UART fault injection.
        
        Used for simulating serial communication errors, byte corruption,
        and protocol violations.
        """
        return self._uart_fault
    
    @property
    def network_fault(self) -> random.Random:
        """Get RNG stream for network fault injection.
        
        Used for simulating network timeouts, packet loss, connection drops,
        and latency spikes. Does NOT affect physical sensor noise.
        
        IMPORTANT: Using this stream has no impact on any other stream's
        sequence because all streams are completely independent.
        """
        return self._network_fault
    
    def reset(self) -> None:
        """Reset all streams to initial state.
        
        Returns all RNG instances to their initial seed state, allowing
        reproducible runs without creating new RNGStreams instances.
        """
        for name, stream in (
            ("ir_noise", self._ir_noise),
            ("tc_noise", self._tc_noise),
            ("lux_noise", self._lux_noise),
            ("plant_disturbance", self._plant_disturbance),
            ("uart_fault", self._uart_fault),
            ("network_fault", self._network_fault),
        ):
            derived_seed = (self._seed * self._DERIVATION_MULTIPLIERS[name]) % (2**32)
            stream.seed(derived_seed)
    
    def get_all_streams(self) -> dict[str, random.Random]:
        """Get all streams as a dictionary.
        
        Returns:
            Dictionary mapping stream names to Random instances.
        """
        return {
            "ir_noise": self.ir_noise,
            "tc_noise": self.tc_noise,
            "lux_noise": self.lux_noise,
            "plant_disturbance": self.plant_disturbance,
            "uart_fault": self.uart_fault,
            "network_fault": self.network_fault,
        }


# Convenience function for quick access
def make_rng_stream(seed: int = 42, stream_name: str = "ir_noise") -> random.Random:
    """Create an RNGStreams and return a specific stream.
    
    Args:
        seed: Base seed value.
        stream_name: Name of stream to retrieve.
    
    Returns:
        The requested Random instance.
    
    Raises:
        ValueError: If stream_name is not valid.
    
    Example:
        >>> ir_rng = make_rng_stream(42, "ir_noise")
        >>> value = ir_rng.gauss(0, 1)
    """
    streams = RNGStreams(seed)
    if stream_name not in streams.get_all_streams():
        raise ValueError(f"Unknown stream: {stream_name}. Valid: {list(streams.get_all_streams().keys())}")
    return streams.get_all_streams()[stream_name]


__all__ = ["RNGStreams", "make_rng_stream"]
