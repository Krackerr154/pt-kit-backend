"""Golden trace generation and comparison for UART communication layer.

Simplified test module demonstrating:
- Golden trace JSON format specification
- Basic frame-level transaction recording  
- Comparison logic for replay testing
- Deterministic execution with fixed seed
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional

# Add project root to path  
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.simulator.virtual_uart import VirtualUARTEngine, CRC16CCITT, FrameType


@dataclass
class UARTTransaction:
    """Record of a single UART transaction."""
    
    time_s: float
    direction: str  # 'TX' or 'RX'
    packet_type: int
    sequence: int
    payload_size: int
    latency_us: float
    checksum_valid: bool
    
    def to_dict(self) -> dict:
        return {
            'time_s': self.time_s,
            'direction': self.direction,
            'packet_type': self.packet_type,
            'sequence': self.sequence,
            'payload_size': self.payload_size,
            'latency_us': round(self.latency_us, 2),
            'checksum_valid': self.checksum_valid,
        }


@dataclass
class GoldenTrace:
    """Complete golden trace record for replay comparison."""
    
    scenario: str
    seed: int
    uart_transactions: list[UARTTransaction] = field(default_factory=list)
    
    def add_transaction(self, tx: UARTTransaction) -> None:
        self.uart_transactions.append(tx)
    
    def to_json(self) -> str:
        return json.dumps({
            'scenario': self.scenario,
            'seed': self.seed,
            'uart_transactions': [t.to_dict() for t in self.uart_transactions],
        }, indent=2)


class UARTGoldenTraceGenerator:
    """Generate golden traces for UART simulation scenarios."""
    
    SCENARIOS = [
        'ISO1_default_target',
        'PLAT1_default', 
        'CAL_BARE_default',
    ]
    
    def __init__(self, seed: int = 42):
        """Initialize golden trace generator.
        
        Args:
            seed: Random seed for determinism (default 42)
        """
        self._seed = seed
    
    def generate_iso1_trace(self) -> GoldenTrace:
        """Generate golden trace simulating ISO1 mode telemetry flow.
        
        Returns:
            Complete golden trace with simulated UART transactions
        """
        trace = GoldenTrace(scenario='ISO1_default_target', seed=self._seed)
        
        last_sequence = 0
        current_time = 0.0
        
        # Simulate ISO1 telemetry stream (37 samples at 0.5s interval)
        for i in range(37):
            current_time += 0.5
            
            # Create mock telemetry payload (simulating ExtendedTelemetry)
            telemetry_payload = f'TELEM_ISO1_{i:03d}'.encode()
            
            # Calculate checksum for this "packet"
            checksum = CRC16CCITT.calculate(telemetry_payload)
            
            # Record transaction (simulating byte transmission)
            total_bytes = 9 + len(telemetry_payload) + 2  # header + payload + crc
            latency_us = total_bytes * 86.8  # µs at 115200 baud
            
            tx = UARTTransaction(
                time_s=current_time,
                direction='TX',
                packet_type=int(FrameType.TELEMETRY),
                sequence=last_sequence + 1,
                payload_size=len(telemetry_payload),
                latency_us=latency_us,
                checksum_valid=True,
            )
            trace.add_transaction(tx)
            
            last_sequence += 1
        
        # Final status packet
        current_time += 0.5
        status_payload = b'\x01'
        checksum = CRC16CCITT.calculate(status_payload)
        
        tx = UARTTransaction(
            time_s=current_time,
            direction='TX',
            packet_type=int(FrameType.STATUS),
            sequence=last_sequence + 1,
            payload_size=1,
            latency_us=12*86.8,
            checksum_valid=True,
        )
        trace.add_transaction(tx)
        
        return trace
    
    def generate_plat1_trace(self) -> GoldenTrace:
        """Generate golden trace simulating PLAT1 mode plateau detection."""
        trace = GoldenTrace(scenario='PLAT1_default', seed=self._seed)
        
        last_sequence = 0
        current_time = 0.0
        
        # Simulate PLAT1 telemetry (12 samples over 6 seconds)
        for i in range(12):
            current_time += 0.5
            
            telemetry_payload = f'TELEM_PLAT1_{i:03d}'.encode()
            total_bytes = 9 + len(telemetry_payload) + 2
            
            tx = UARTTransaction(
                time_s=current_time,
                direction='TX',
                packet_type=int(FrameType.TELEMETRY),
                sequence=last_sequence + 1,
                payload_size=len(telemetry_payload),
                latency_us=total_bytes * 86.8,
                checksum_valid=True,
            )
            trace.add_transaction(tx)
            last_sequence += 1
        
        return trace
    
    def generate_cal_bare_trace(self) -> GoldenTrace:
        """Generate golden trace simulating bare board calibration."""
        trace = GoldenTrace(scenario='CAL_BARE_default', seed=self._seed)
        
        last_sequence = 0
        current_time = 0.0
        
        # Simulate calibration sequence (16 samples)
        for i in range(16):
            current_time += 0.5
            
            cal_payload = f'CAL_BARE_{i:03d}'.encode()
            total_bytes = 9 + len(cal_payload) + 2
            
            tx = UARTTransaction(
                time_s=current_time,
                direction='TX',
                packet_type=int(FrameType.CALIBRATION),
                sequence=last_sequence + 1,
                payload_size=len(cal_payload),
                latency_us=total_bytes * 86.8,
                checksum_valid=True,
            )
            trace.add_transaction(tx)
            last_sequence += 1
        
        return trace
    
    def generate_all_traces(self) -> dict:
        """Generate golden traces for all supported scenarios.
        
        Returns:
            Dictionary mapping scenario names to golden traces
        """
        return {
            'ISO1_default_target': self.generate_iso1_trace(),
            'PLAT1_default': self.generate_plat1_trace(),
            'CAL_BARE_default': self.generate_cal_bare_trace(),
        }


class UARTGoldenTraceVerifier:
    """Compare new runs against golden reference traces."""
    
    FLOAT_TOLERANCE_S = 0.01  # ±10 ms timing tolerance
    FLOAT_TOLERANCE_US = 1.0  # ±1 µs microsecond tolerance
    
    def __init__(self, golden_trace: GoldenTrace):
        """Initialize verifier with golden reference.
        
        Args:
            golden_trace: Reference trace for comparison
        """
        self.golden = golden_trace
        self._deviations: list[dict[str, Any]] = []
    
    def verify(self, new_trace: GoldenTrace) -> bool:
        """Verify new trace matches golden reference.
        
        Args:
            new_trace: Trace from recent execution
            
        Returns:
            True if traces match within tolerances
        """
        if len(new_trace.uart_transactions) != len(self.golden.uart_transactions):
            self._deviations.append({
                'type': 'transaction_count_mismatch',
                'golden_count': len(self.golden.uart_transactions),
                'new_count': len(new_trace.uart_transactions),
            })
            return False
        
        for idx, (golden_tx, new_tx) in enumerate(zip(self.golden.uart_transactions, new_trace.uart_transactions)):
            deviation = self._compare_transaction(golden_tx, new_tx, idx)
            if deviation:
                self._deviations.append(deviation)
        
        return len(self._deviations) == 0
    
    def _compare_transaction(self, golden: UARTTransaction, new: UARTTransaction, index: int) -> Optional[dict]:
        """Compare single transaction and return deviation details."""
        deviations = {}
        
        # Check direction
        if golden.direction != new.direction:
            deviations['direction_mismatch'] = {'golden': golden.direction, 'new': new.direction}
        
        # Check packet type
        if golden.packet_type != new.packet_type:
            deviations['packet_type_mismatch'] = {'golden': golden.packet_type, 'new': new.packet_type}
        
        # Check sequence number
        if golden.sequence != new.sequence:
            deviations['sequence_gap'] = {'golden': golden.sequence, 'new': new.sequence}
        
        # Check timestamp within tolerance
        if abs(golden.time_s - new.time_s) > self.FLOAT_TOLERANCE_S:
            deviations['timing_deviation_s'] = {
                'golden': golden.time_s,
                'new': new.time_s,
                'tolerance_s': self.FLOAT_TOLERANCE_S,
            }
        
        # Check latency within tolerance
        if abs(golden.latency_us - new.latency_us) > self.FLOAT_TOLERANCE_US:
            deviations['latency_deviation_us'] = {
                'golden': golden.latency_us,
                'new': new.latency_us,
                'tolerance_us': self.FLOAT_TOLERANCE_US,
            }
        
        # Check payload size
        if golden.payload_size != new.payload_size:
            deviations['payload_size_mismatch'] = {'golden': golden.payload_size, 'new': new.payload_size}
        
        # Check checksum validity
        if golden.checksum_valid != new.checksum_valid:
            deviations['checksum_change'] = {'golden': golden.checksum_valid, 'new': new.checksum_valid}
        
        return deviations if deviations else None
    
    def get_summary(self) -> dict:
        """Get verification summary statistics.
        
        Returns:
            Summary dictionary with deviation counts and types
        """
        summary = {
            'total_comparisons': len(self.golden.uart_transactions),
            'total_deviations': len(self._deviations),
            'pass': len(self._deviations) == 0,
            'deviation_types': {},
        }
        
        for dev in self._deviations:
            for key, value in dev.items():
                summary['deviation_types'][key] = summary['deviation_types'].get(key, 0) + 1
        
        return summary


def save_golden_trace(trace: GoldenTrace, output_path: str) -> None:
    """Save golden trace to JSON file.
    
    Args:
        trace: Golden trace to save
        output_path: File path for JSON output
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        f.write(trace.to_json())


def load_golden_trace(input_path: str) -> GoldenTrace:
    """Load golden trace from JSON file.
    
    Args:
        input_path: File path for JSON input
        
    Returns:
        GoldenTrace object reconstructed from JSON
    """
    with open(input_path, 'r') as f:
        data = json.load(f)
    
    trace = GoldenTrace(
        scenario=data['scenario'],
        seed=data['seed'],
    )
    
    for tx_data in data['uart_transactions']:
        tx = UARTTransaction(
            time_s=tx_data['time_s'],
            direction=tx_data['direction'],
            packet_type=tx_data['packet_type'],
            sequence=tx_data['sequence'],
            payload_size=tx_data['payload_size'],
            latency_us=tx_data['latency_us'],
            checksum_valid=tx_data['checksum_valid'],
        )
        trace.add_transaction(tx)
    
    return trace


if __name__ == '__main__':
    print("Generating Phase 4 UART golden traces...\n")
    
    generator = UARTGoldenTraceGenerator(seed=42)
    traces = generator.generate_all_traces()
    
    output_dir = Path('/home/Gerald154/Projects/pt-kit-backend/tests/fixtures/simulator/golden')
    output_dir.mkdir(parents=True, exist_ok=True)
    
    for scenario_name, trace in traces.items():
        output_path = output_dir / f'{scenario_name}_uart.json'
        save_golden_trace(trace, output_path)
        print(f"✓ Saved {output_path.name} ({len(trace.uart_transactions)} transactions)")
    
    print(f"\n✅ Generated {len(traces)} golden traces")
