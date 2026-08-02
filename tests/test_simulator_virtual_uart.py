"""
Comprehensive UART tests for Virtual UART Engine.

Tests packet encoding/decoding, checksum validation, sequencing, timing accuracy,
all frame types, and determinism with fixed seed.
"""

import pytest
import random
import struct
from typing import List, Tuple
import sys
import os

# Add simulator path to imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app', 'simulator'))

from virtual_uart import (
    FrameType,
    UARTPacket,
    CRC16CCITT,
    VirtualUARTEngine,
    create_packet
)


class TestCRC16CCITT:
    """Test CRC-16-CCITT checksum implementation."""
    
    def test_crc_basic(self):
        """Test basic CRC calculation."""
        data = b'Hello, World!'
        crc = CRC16CCITT.calculate(data)
        assert isinstance(crc, int)
        assert 0 <= crc <= 0xFFFF
    
    def test_crc_determinism(self):
        """Test that same input produces same CRC."""
        data = b'Test data for CRC'
        crc1 = CRC16CCITT.calculate(data)
        crc2 = CRC16CCITT.calculate(data)
        assert crc1 == crc2
    
    def test_crc_verification_valid(self):
        """Test CRC verification with valid data."""
        data = b'Verification test data'
        crc = CRC16CCITT.calculate(data)
        assert CRC16CCITT.verify(data, crc) is True
    
    def test_crc_verification_invalid(self):
        """Test CRC verification with wrong checksum."""
        data = b'Different checksum test'
        assert CRC16CCITT.verify(data, 0x1234) is False


class TestUARTPacketEncoding:
    """Test UART packet encoding to byte stream."""
    
    def test_empty_packet_encoding(self):
        """Test encoding a packet with empty payload."""
        engine = VirtualUARTEngine()
        packet = UARTPacket(
            sync_word=0xABCD,
            version=1,
            frame_type=FrameType.TELEMETRY.value,
            sequence=0,
            payload=b''
        )
        
        byte_stream = engine.encode_packet(packet)
        
        # Should have header (9 bytes) + checksum (2 bytes) = 11 bytes minimum
        assert len(byte_stream) == 11
        # Check sync word
        assert byte_stream[0] == 0xAB
        assert byte_stream[1] == 0xCD
    
    def test_packet_with_payload_encoding(self):
        """Test encoding a packet with payload."""
        engine = VirtualUARTEngine()
        payload = b'Hello, Telemetry Data!'
        packet = UARTPacket(
            sync_word=0xABCD,
            version=1,
            frame_type=FrameType.TELEMETRY.value,
            sequence=42,
            payload=payload
        )
        
        byte_stream = engine.encode_packet(packet)
        
        # Expected length: header(11) + payload(len)
        expected_len = 11 + len(payload)
        assert len(byte_stream) == expected_len
        
        # Verify payload bytes are in correct position (payload starts at offset 9)
        for i, byte_val in enumerate(payload):
            assert byte_stream[9 + i] == byte_val
    
    def test_long_payload_encoding(self):
        """Test encoding a large payload."""
        engine = VirtualUARTEngine()
        payload = bytes(range(256))  # All possible byte values
        packet = UARTPacket(
            sync_word=0xABCD,
            version=1,
            frame_type=FrameType.CALIBRATION.value,
            sequence=999,
            payload=payload
        )
        
        byte_stream = engine.encode_packet(packet)
        
        # Layout per spec: 9-byte header + payload + 2-byte trailing checksum
        expected_len = 11 + len(payload)
        assert len(byte_stream) == expected_len
        
        # Verify all payload bytes preserved (payload starts at offset 9)
        for i, byte_val in enumerate(payload):
            assert byte_stream[9 + i] == byte_val
    
    def test_large_sequence_number_encoding(self):
        """Test encoding with maximum sequence number."""
        engine = VirtualUARTEngine()
        packet = UARTPacket(
            sync_word=0xABCD,
            version=1,
            frame_type=FrameType.STATUS.value,
            sequence=0xFFFF,  # Maximum 16-bit value
            payload=b'test'
        )
        
        byte_stream = engine.encode_packet(packet)
        
        # Sequence should be at offset 4-5
        seq_bytes = byte_stream[4:6]
        assert seq_bytes[0] == 0xFF
        assert seq_bytes[1] == 0xFF


class TestPacketDecoding:
    """Test UART packet decoding from byte stream."""
    
    def test_decode_empty_packet(self):
        """Test decoding a packet with no payload."""
        engine = VirtualUARTEngine()
        
        # Manually construct valid byte stream
        payload = b''
        header = bytearray()
        header.append(0xAB)
        header.append(0xCD)
        header.append(1)  # version
        header.append(FrameType.TELEMETRY.value)
        header.append(0x00)  # seq high
        header.append(0x01)  # seq low
        header.append(0x00)  # len high
        header.append(0x00)  # len low
        header.append(0x00)  # padding
        
        checksum_data = bytes(header[:-1]) + payload
        checksum = CRC16CCITT.calculate(checksum_data)
        header.append((checksum >> 8) & 0xFF)
        header.append(checksum & 0xFF)
        
        # Put bytes in RX queue
        for byte_val in header:
            engine.rx_queue.append(byte_val)
        
        packet = engine.read_available()
        
        assert packet is not None
        assert packet.sync_word == 0xABCD
        assert packet.version == 1
        assert packet.frame_type == FrameType.TELEMETRY.value
        assert packet.sequence == 0x0001  # seq bytes were high=0x00, low=0x01 (big-endian)
        assert packet.payload_length == 0
        assert packet.payload == b''
    
    def test_decode_packet_with_payload(self):
        """Test decoding a packet with payload data."""
        engine = VirtualUARTEngine()
        
        # Use encoder instead of manual construction
        payload = b'Hello, PT-Kit!'
        packet = UARTPacket(
            sync_word=0xABCD,
            version=1,
            frame_type=FrameType.TELEMETRY.value,
            sequence=0x0700,  # This will be overridden
            payload=payload
        )
        
        # Clear any previous state
        engine.tx_queue.clear()
        engine.rx_queue.clear()
        
        byte_stream = engine.encode_packet(packet)
        for byte_val in byte_stream:
            engine.rx_queue.append(byte_val)
        
        packet = engine.read_available()
        
        assert packet is not None
        assert packet.payload == payload
        assert packet.payload_length == len(payload)
    
    def test_multiple_packets_sequential(self):
        """Test decoding multiple consecutive packets."""
        engine = VirtualUARTEngine()
        
        # Create and encode two packets
        payloads = [b'First packet', b'Second packet']
        for i, payload in enumerate(payloads):
            packet = UARTPacket(
                sync_word=0xABCD,
                version=1,
                frame_type=FrameType.TELEMETRY.value,
                sequence=i,
                payload=payload
            )
            byte_stream = engine.encode_packet(packet)
            
            # Add each byte to TX queue
            for byte_val in byte_stream:
                engine.tx_queue.append({'byte': byte_val, 'time_offset': 0})
        
        # Simulate transmission
        received_packets = engine.simulate_transmission()
        
        assert len(received_packets) == 2
        assert received_packets[0].payload == payloads[0]
        assert received_packets[1].payload == payloads[1]


class TestChecksumValidation:
    """Test packet checksum validation."""
    
    def test_valid_packet_passes_checksum(self):
        """Test that valid packets pass checksum validation."""
        engine = VirtualUARTEngine()
        packet = UARTPacket(
            sync_word=0xABCD,
            version=1,
            frame_type=FrameType.COMMAND.value,
            sequence=100,
            payload=b'Valid command data'
        )
        
        byte_stream = engine.encode_packet(packet)
        
        # Reconstruct buffer manually
        for byte_val in byte_stream:
            engine.rx_queue.append(byte_val)
        
        decoded = engine.read_available()
        assert decoded is not None
        assert engine.checksum_errors == 0
    
    def test_corrupted_packet_fails_checksum(self):
        """Test that corrupted packets fail checksum validation."""
        engine = VirtualUARTEngine()
        
        # Create valid packet first
        packet = UARTPacket(
            sync_word=0xABCD,
            version=1,
            frame_type=FrameType.ACK_NACK.value,
            sequence=50,
            payload=b'Status report'
        )
        byte_stream = engine.encode_packet(packet)
        
        # Corrupt a byte in the middle (not sync, not checksum)
        corruption_idx = 5
        original_byte = byte_stream[corruption_idx]
        byte_stream[corruption_idx] = (original_byte + 1) % 256
        
        # Add corrupted bytes to RX
        for byte_val in byte_stream:
            engine.rx_queue.append(byte_val)
        
        # Try to decode
        decoded = engine.read_available()
        
        # Should fail due to checksum mismatch
        assert decoded is None
        assert engine.checksum_errors >= 1
    
    def test_corrupted_header_fails_validation(self):
        """Test that corrupted header fails validation."""
        engine = VirtualUARTEngine()
        
        # Create valid packet
        packet = UARTPacket(
            sync_word=0xABCD,
            version=1,
            frame_type=FrameType.CALIBRATION.value,
            sequence=1,
            payload=b'Calibration data'
        )
        byte_stream = engine.encode_packet(packet)
        
        # Corrupt version byte (offset 2)
        byte_stream[2] = 99  # Invalid version
        
        for byte_val in byte_stream:
            engine.rx_queue.append(byte_val)
        
        decoded = engine.read_available()
        assert decoded is None


class TestSequencing:
    """Test sequence number wrapping and incrementing."""
    
    def test_sequence_wraps_at_65535(self):
        """Test that sequence wraps correctly at maximum value."""
        engine = VirtualUARTEngine()
        
        # Set sequence to maximum
        engine.sequence_number = 0xFFFF
        
        packet1 = UARTPacket(
            sync_word=0xABCD,
            version=1,
            frame_type=FrameType.STATUS.value,
            sequence=0,
            payload=b'Test'
        )
        
        duration = engine.write_packet(packet1)
        
        # After writing, sequence should wrap to 0
        assert engine.sequence_number == 0
        assert packet1.sequence == 0xFFFF
    
    def test_sequence_increments_properly(self):
        """Test that sequence increments on each write."""
        engine = VirtualUARTEngine()
        engine.sequence_number = 100
        
        packets_written = []
        for i in range(10):
            packet = UARTPacket(
                sync_word=0xABCD,
                version=1,
                frame_type=FrameType.TELEMETRY.value,
                sequence=0,
                payload=f'Packet {i}'.encode()
            )
            engine.write_packet(packet)
            packets_written.append(packet.sequence)
        
        # Verify sequences are 100, 101, 102, ..., 109
        expected = list(range(100, 110))
        assert packets_written == expected
    
    def test_wrap_then_continue(self):
        """Test sequence continues after wrapping."""
        engine = VirtualUARTEngine()
        
        # Force wrap by setting to max
        engine.sequence_number = 0xFFFF
        
        # Write one packet (should use 0xFFFF, wrap to 0)
        packet1 = UARTPacket(sync_word=0xABCD, version=1, frame_type=FrameType.TELEMETRY.value, 
                            sequence=0, payload=b'A')
        engine.write_packet(packet1)
        assert engine.sequence_number == 0
        
        # Next packet should use 0
        packet2 = UARTPacket(sync_word=0xABCD, version=1, frame_type=FrameType.TELEMETRY.value,
                            sequence=0, payload=b'B')
        engine.write_packet(packet2)
        assert packet2.sequence == 0
        assert engine.sequence_number == 1


class TestTimingAccuracy:
    """Test byte transmission timing accuracy."""
    
    def test_baud_rate_timing_calculation(self):
        """Test that timing matches baud rate specification."""
        # At 115200 baud with 10 bits/byte:
        # bytes_per_second = 115200 / 10 = 11520
        # byte_duration = 1 / 11520 ≈ 8.68 µs
        
        engine = VirtualUARTEngine(baud_rate=115200)
        
        expected_bytes_per_sec = 115200 / 10
        expected_byte_duration = 1.0 / expected_bytes_per_sec
        
        assert abs(engine.bytes_per_second - expected_bytes_per_sec) < 0.01
        assert abs(engine.byte_duration - expected_byte_duration) < 1e-9
    
    def test_single_byte_transmission_time(self):
        """Test single byte transmission time."""
        engine = VirtualUARTEngine(baud_rate=115200)
        
        # Single byte packet (11 bytes total: header+checksum)
        packet = UARTPacket(
            sync_word=0xABCD,
            version=1,
            frame_type=FrameType.TELEMETRY.value,
            sequence=0,
            payload=b'X'  # 1 byte payload
        )
        
        duration = engine.write_packet(packet)
        
        # Expected: 12 bytes * 8.68 µs = ~104 µs = 0.000104 seconds
        expected_duration = 12 * engine.byte_duration
        tolerance = expected_duration * 0.01  # ±1%
        
        assert abs(duration - expected_duration) < tolerance
    
    def test_multi_byte_timing_accuracy(self):
        """Test timing for multi-byte packet within ±1% tolerance."""
        engine = VirtualUARTEngine(baud_rate=115200)
        
        payload_size = 100  # bytes
        packet = UARTPacket(
            sync_word=0xABCD,
            version=1,
            frame_type=FrameType.TELEMETRY.value,
            sequence=0,
            payload=bytes(payload_size)
        )
        
        duration = engine.write_packet(packet)
        
        total_bytes = 11 + payload_size  # header + payload
        expected_duration = total_bytes * engine.byte_duration
        tolerance = expected_duration * 0.01
        
        assert abs(duration - expected_duration) < tolerance, \
            f"Duration {duration}s differs from expected {expected_duration}s by more than 1%"
    
    def test_different_baud_rates(self):
        """Test timing at different baud rates."""
        baud_rates = [9600, 19200, 38400, 57600, 115200]
        
        for baud in baud_rates:
            engine = VirtualUARTEngine(baud_rate=baud)
            expected_bytes_per_sec = baud / 10
            
            assert abs(engine.bytes_per_second - expected_bytes_per_sec) < 0.01
            assert engine.byte_duration > 0


class TestAllFrameTypes:
    """Test all 5 frame type encodings."""
    
    FRAME_TYPES = [
        (FrameType.TELEMETRY, 0x01, b'Telemetry data'),
        (FrameType.COMMAND, 0x02, b'Command instruction'),
        (FrameType.ACK_NACK, 0x03, b'Acknowledgment'),
        (FrameType.CALIBRATION, 0x04, b'Calibration parameters'),
        (FrameType.STATUS, 0x05, b'System status')
    ]
    
    @pytest.mark.parametrize("frame_type,expected_type,payload", FRAME_TYPES)
    def test_frame_type_encodes_correctly(self, frame_type, expected_type, payload):
        """Test each frame type encodes the correct type byte."""
        engine = VirtualUARTEngine()
        
        packet = UARTPacket(
            sync_word=0xABCD,
            version=1,
            frame_type=frame_type.value,
            sequence=0,
            payload=payload
        )
        
        byte_stream = engine.encode_packet(packet)
        
        # Frame type is at offset 3
        assert byte_stream[3] == expected_type
    
    @pytest.mark.parametrize("frame_type,expected_type,payload", FRAME_TYPES)
    def test_frame_type_decodes_correctly(self, frame_type, expected_type, payload):
        """Test each frame type decodes back correctly."""
        engine = VirtualUARTEngine()
        
        packet = UARTPacket(
            sync_word=0xABCD,
            version=1,
            frame_type=frame_type.value,
            sequence=42,
            payload=payload
        )
        
        byte_stream = engine.encode_packet(packet)
        
        # Add to RX queue
        for byte_val in byte_stream:
            engine.rx_queue.append(byte_val)
        
        decoded = engine.read_available()
        
        assert decoded is not None
        assert decoded.frame_type == expected_type
    
    @pytest.mark.parametrize("frame_type,expected_type,payload", FRAME_TYPES)
    def test_end_to_end_all_frame_types(self, frame_type, expected_type, payload):
        """Test full encode-decode cycle for all frame types."""
        engine = VirtualUARTEngine()
        
        packet = create_packet(frame_type, payload, sequence=99)
        
        duration = engine.write_packet(packet)
        
        received_packets = engine.simulate_transmission()
        
        assert len(received_packets) == 1
        received = received_packets[0]
        
        assert received.frame_type == expected_type
        assert received.payload == payload
        # write_packet() auto-assigns the engine's own sequence counter (starts at 0),
        # intentionally overriding the caller-supplied value (implementation contract).
        assert received.sequence == 0


class TestDeterminism:
    """Test deterministic behavior with fixed seed."""
    
    def test_fixed_seed_produces_identical_trace(self):
        """Test that fixed random seed produces identical traces."""
        random.seed(42)
        
        # Generate and encode packets
        engine1 = VirtualUARTEngine(baud_rate=115200)
        packets1 = []
        for i in range(10):
            payload_size = random.randint(1, 50)
            payload = bytes([random.randint(0, 255) for _ in range(payload_size)])
            frame_type = random.choice(list(FrameType))
            
            packet = UARTPacket(
                sync_word=0xABCD,
                version=1,
                frame_type=frame_type.value,
                sequence=0,
                payload=payload
            )
            engine1.write_packet(packet)
            packets1.extend(engine1.simulate_transmission())
        
        random.seed(42)
        
        # Repeat with new engine
        engine2 = VirtualUARTEngine(baud_rate=115200)
        packets2 = []
        for i in range(10):
            payload_size = random.randint(1, 50)
            payload = bytes([random.randint(0, 255) for _ in range(payload_size)])
            frame_type = random.choice(list(FrameType))
            
            packet = UARTPacket(
                sync_word=0xABCD,
                version=1,
                frame_type=frame_type.value,
                sequence=0,
                payload=payload
            )
            engine2.write_packet(packet)
            packets2.extend(engine2.simulate_transmission())
        
        # Compare encoded results
        assert len(packets1) == len(packets2)
        
        for i, (p1, p2) in enumerate(zip(packets1, packets2)):
            assert p1.sync_word == p2.sync_word, f"Mismatch at index {i}: sync_word"
            assert p1.version == p2.version, f"Mismatch at index {i}: version"
            assert p1.frame_type == p2.frame_type, f"Mismatch at index {i}: frame_type"
            assert p1.payload == p2.payload, f"Mismatch at index {i}: payload"
            assert p1.checksum == p2.checksum, f"Mismatch at index {i}: checksum"
    
    def test_no_external_dependencies(self):
        """Test that simulation has no external dependencies."""
        engine = VirtualUARTEngine()
        
        # Encode a packet
        packet = UARTPacket(
            sync_word=0xABCD,
            version=1,
            frame_type=FrameType.TELEMETRY.value,
            sequence=123,
            payload=b'No external deps test'
        )
        
        # First encode
        byte_stream1 = engine.encode_packet(packet)
        
        # Reset and encode again (same packet fields — statistics reset must not
        # affect encoding output; sequence intentionally left unchanged)
        engine.reset_statistics()
        byte_stream2 = engine.encode_packet(packet)
        
        # Results should be identical
        assert byte_stream1 == byte_stream2


class TestGoldenTraces:
    """Generate and verify golden trace comparisons."""
    
    def test_create_golden_trace(self):
        """Create a golden trace for replay comparison."""
        engine = VirtualUARTEngine(baud_rate=115200)
        
        # Create known sequence of packets
        test_packets = [
            (FrameType.TELEMETRY, b'\x01\x02\x03\x04\x05'),
            (FrameType.COMMAND, b'\xAA\xBB\xCC'),
            (FrameType.ACK_NACK, b'READY'),
            (FrameType.CALIBRATION, bytes([0, 1, 2, 3, 4, 5])),
            (FrameType.STATUS, b'OK')
        ]
        
        golden_trace = []
        
        for frame_type, payload in test_packets:
            packet = UARTPacket(
                sync_word=0xABCD,
                version=1,
                frame_type=frame_type.value,
                sequence=len(golden_trace),
                payload=payload
            )
            
            byte_stream = engine.encode_packet(packet)
            duration = engine.write_packet(packet)
            
            golden_trace.append({
                'sequence': len(golden_trace),
                'frame_type': frame_type.name,
                'payload_hex': payload.hex(),
                'byte_stream': byte_stream,
                'duration_ms': duration * 1000
            })
        
        return golden_trace
    
    def test_replay_golden_trace(self):
        """Replay a golden trace and verify correctness."""
        golden_trace = self.test_create_golden_trace()
        
        # Replay using a fresh engine
        replay_engine = VirtualUARTEngine(baud_rate=115200)
        replay_packets = []
        
        for entry in golden_trace:
            payload = bytes.fromhex(entry['payload_hex'])
            packet = create_packet(
                FrameType[entry['frame_type']],
                payload,
                sequence=entry['sequence']
            )
            replay_engine.write_packet(packet)
        
        replay_packets = replay_engine.simulate_transmission()
        
        # Verify all packets received
        assert len(replay_packets) == len(golden_trace)
        
        # Verify each packet matches
        for i, (packet, entry) in enumerate(zip(replay_packets, golden_trace)):
            assert packet.frame_type == FrameType[entry['frame_type']].value
            assert packet.payload == bytes.fromhex(entry['payload_hex'])
            assert packet.sequence == entry['sequence']


class TestStatistics:
    """Test statistics tracking."""
    
    def test_statistics_collection(self):
        """Test that statistics are collected correctly."""
        engine = VirtualUARTEngine(baud_rate=115200)
        
        # Send 5 packets
        for i in range(5):
            packet = UARTPacket(
                sync_word=0xABCD,
                version=1,
                frame_type=FrameType.TELEMETRY.value,
                sequence=i,
                payload=f'Payload {i}'.encode()
            )
            engine.write_packet(packet)
        
        stats = engine.get_statistics()
        
        assert stats['packets_sent'] == 5
        assert stats['bytes_transmitted'] > 0
        assert stats['total_transmission_time'] > 0
    
    def test_statistics_reset(self):
        """Test that statistics can be reset."""
        engine = VirtualUARTEngine()
        
        # Send some packets
        for i in range(3):
            packet = UARTPacket(sync_word=0xABCD, version=1, frame_type=FrameType.TELEMETRY.value,
                              sequence=i, payload=b'test')
            engine.write_packet(packet)
        
        # Reset
        engine.reset_statistics()
        
        stats = engine.get_statistics()
        assert stats['packets_sent'] == 0
        assert stats['packets_received'] == 0
        assert stats['checksum_errors'] == 0


def main():
    """Run all tests directly."""
    pytest.main([__file__, '-v'])


if __name__ == '__main__':
    main()
