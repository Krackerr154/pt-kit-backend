"""
Virtual UART Engine with byte-stream simulation and protocol framing.

Implements RS-232 serial communication simulation at configurable baud rate
with packet encoding/decoding, checksum validation, and precise timing.
"""

import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional, List
from collections import deque


class FrameType(IntEnum):
    """Frame type identifiers."""
    TELEMETRY = 0x01
    COMMAND = 0x02
    ACK_NACK = 0x03
    CALIBRATION = 0x04
    STATUS = 0x05


@dataclass
class UARTPacket:
    """UART packet structure with all protocol fields."""
    sync_word: int = 0xABCD
    version: int = 1
    frame_type: int = 0x01
    sequence: int = 0
    payload_length: int = 0
    payload: bytes = b''
    
    # Calculated fields
    checksum: int = 0
    
    def __post_init__(self):
        """Ensure payload is bytes."""
        if isinstance(self.payload, list):
            self.payload = bytes(self.payload)
        elif not isinstance(self.payload, bytes):
            self.payload = bytes(self.payload.encode() if isinstance(self.payload, str) else b'')


class CRC16CCITT:
    """CRC-16-CCITT checksum calculator (polynomial 0x1021)."""
    
    POLYNOMIAL = 0x1021
    INITIAL_VALUE = 0xFFFF
    
    @classmethod
    def calculate(cls, data: bytes) -> int:
        """Calculate CRC-16-CCITT checksum over data bytes."""
        crc = cls.INITIAL_VALUE
        
        for byte in data:
            crc ^= byte << 8
            for _ in range(8):
                if crc & 0x8000:
                    crc = (crc << 1) ^ cls.POLYNOMIAL
                else:
                    crc <<= 1
                crc &= 0xFFFF
        
        return crc
    
    @classmethod
    def verify(cls, data: bytes, expected_crc: int) -> bool:
        """Verify CRC-16-CCITT checksum against expected value."""
        return cls.calculate(data) == expected_crc


class VirtualUARTEngine:
    """
    Virtual UART engine simulating RS-232 serial communication.
    
    Features:
    - Configurable baud rate (default 115200)
    - Packet encoding/decoding with sync word, sequence numbers, CRC-16-CCITT
    - Byte-level transmission timing based on baud rate
    - Support for all 5 frame types
    - TX/RX byte queues with buffering
    """
    
    # Protocol constants
    SYNC_WORD_HIGH = 0xAB
    SYNC_WORD_LOW = 0xCD
    HEADER_SIZE = 9  # sync(2) + version(1) + type(1) + seq(2) + len(2) + pad(1)
    CHECKSUM_SIZE = 2
    
    # Byte transmission timing calculation
    BITS_PER_BYTE = 10  # Start(1) + Data(8) + Stop(1)
    
    def __init__(self, baud_rate: int = 115200):
        """
        Initialize virtual UART engine.
        
        Args:
            baud_rate: Serial baud rate (bits per second), default 115200
        """
        if baud_rate <= 0:
            raise ValueError("Baud rate must be positive")
        
        self.baud_rate = baud_rate
        self.bytes_per_second = baud_rate / self.BITS_PER_BYTE
        self.byte_duration = 1.0 / self.bytes_per_second  # seconds per byte
        
        # Byte queues for TX/RX buffering
        self.tx_queue: deque = deque()
        self.rx_queue: deque = deque()
        
        # Timing state
        self.last_tx_time = 0.0
        self.total_transmission_time = 0.0
        
        # Sequence counter
        self.sequence_number = 0
        
        # Statistics
        self.packets_sent = 0
        self.packets_received = 0
        self.bytes_transmitted = 0
        self.bytes_received = 0
        self.checksum_errors = 0
        self.sequence_errors = 0
    
    def encode_packet(self, packet: UARTPacket) -> List[int]:
        """
        Encode a UARTPacket into a byte stream.
        
        Args:
            packet: The packet to encode
            
        Returns:
            List of byte values representing the serialized packet
        """
        # Validate payload length
        if len(packet.payload) > 65535:
            raise ValueError("Payload too large (max 65535 bytes)")
        
        # Build header without sync word and checksum
        header = bytearray()
        header.append((packet.sync_word >> 8) & 0xFF)  # High byte of sync
        header.append(packet.sync_word & 0xFF)          # Low byte of sync
        header.append(packet.version)
        header.append(packet.frame_type)
        header.append((packet.sequence >> 8) & 0xFF)    # High byte of sequence
        header.append(packet.sequence & 0xFF)           # Low byte of sequence
        header.append((len(packet.payload) >> 8) & 0xFF)  # High byte of length
        header.append(len(packet.payload) & 0xFF)       # Low byte of length
        header.append(0x00)  # Padding/reserved
        
        # Calculate checksum over header (excluding last padding byte) and payload
        checksum_data = bytes(header[:-1]) + packet.payload
        packet.checksum = CRC16CCITT.calculate(checksum_data)
        
        # Frame layout per docs/phase4-uart-protocol-spec.md:
        # header + payload + checksum (checksum comes LAST, after payload)
        byte_stream = list(header) + list(packet.payload)
        byte_stream.append((packet.checksum >> 8) & 0xFF)
        byte_stream.append(packet.checksum & 0xFF)
        
        return byte_stream
    
    def transmit_bytes(self, byte_stream: List[int]) -> float:
        """
        Transmit a byte stream through the virtual UART.
        
        Args:
            byte_stream: List of byte values to transmit
            
        Returns:
            Time duration required to transmit all bytes (in seconds)
        """
        num_bytes = len(byte_stream)
        transmission_time = num_bytes * self.byte_duration
        
        # Add bytes to TX queue one at a time with timing
        for byte_val in byte_stream:
            self.tx_queue.append({
                'byte': byte_val & 0xFF,  # Ensure byte range
                'time_offset': self.total_transmission_time
            })
            self.total_transmission_time += self.byte_duration
        
        self.bytes_transmitted += num_bytes
        self.last_tx_time = self.total_transmission_time
        
        return transmission_time
    
    def write_packet(self, packet: UARTPacket) -> float:
        """
        Write and transmit a packet through the UART.
        
        Args:
            packet: The packet to send
            
        Returns:
            Time duration in seconds for packet transmission
        """
        # Auto-increment sequence number
        packet.sequence = self.sequence_number
        self.sequence_number = (self.sequence_number + 1) & 0xFFFF  # Wrap at 65535
        
        # Encode packet to bytes
        byte_stream = self.encode_packet(packet)
        
        # Transmit bytes
        duration = self.transmit_bytes(byte_stream)
        
        self.packets_sent += 1
        
        return duration
    
    def receive_byte(self) -> Optional[int]:
        """
        Receive a single byte from the RX queue.
        
        Returns:
            Byte value or None if no data available
        """
        if self.rx_queue:
            return self.rx_queue.popleft()
        return None
    
    def _flush_rx_buffer_to_queue(self):
        """Flush TX queue to RX queue (simulates actual transmission)."""
        while self.tx_queue:
            item = self.tx_queue.popleft()
            self.rx_queue.append(item['byte'])
            self.bytes_received += 1
    
    def read_available(self) -> Optional[UARTPacket]:
        """
        Attempt to read and decode a complete packet.
        
        Returns:
            Complete decoded UARTPacket or None if incomplete/corrupted
        """
        self._flush_rx_buffer_to_queue()
        
        # Need at least full header + checksum minimum
        min_required = self.HEADER_SIZE + self.CHECKSUM_SIZE
        
        if len(self.rx_queue) < min_required:
            return None
        
        # Get byte list for inspection
        byte_list = list(self.rx_queue)
        
        # Try to decode from start
        if byte_list[0] == self.SYNC_WORD_HIGH and byte_list[1] == self.SYNC_WORD_LOW:
            # Try decoding from position 0
            try:
                packet = self._decode_packet_from(byte_list)
                if packet is not None:
                    # Successfully decoded, now consume the bytes
                    payload_len = packet.payload_length
                    total_len = self.HEADER_SIZE + payload_len + self.CHECKSUM_SIZE
                    
                    # Consume exactly that many bytes
                    for _ in range(total_len):
                        self.rx_queue.popleft()
                    
                    self.packets_received += 1
                    return packet
            except (IndexError, ValueError):
                pass
        
        return None
    
    def _parse_simple_packet(self) -> Optional[UARTPacket]:
        """Simple packet parsing as fallback."""
        if len(self.rx_queue) < self.HEADER_SIZE + self.CHECKSUM_SIZE:
            return None
        
        # Extract sync word
        byte_list = list(self.rx_queue)
        
        # Try to decode from the very start first
        result = self._decode_packet_from_start(byte_list)
        if result is not None:
            return result
        
        # Look for sync word pattern
        for i in range(len(byte_list) - 3):
            if byte_list[i] == self.SYNC_WORD_HIGH and byte_list[i+1] == self.SYNC_WORD_LOW:
                return self._decode_packet_from(byte_list[i:])
        
        return None
    
    def _decode_packet_from_start(self, byte_list: List[int]) -> Optional[UARTPacket]:
        """Try to decode packet starting exactly at byte 0."""
        if len(byte_list) < self.HEADER_SIZE + self.CHECKSUM_SIZE:
            return None
        
        # Check if starts with valid sync
        if byte_list[0] != self.SYNC_WORD_HIGH or byte_list[1] != self.SYNC_WORD_LOW:
            return None
        
        return self._decode_packet_from(byte_list)
    
    def _decode_packet_from(self, byte_list: List[int]) -> Optional[UARTPacket]:
        """Decode packet starting from byte_list."""
        if len(byte_list) < self.HEADER_SIZE + self.CHECKSUM_SIZE:
            return None
        
        # Parse header to get field values
        sync_high = byte_list[0]
        sync_low = byte_list[1]
        version = byte_list[2]
        frame_type = byte_list[3]
        seq_high = byte_list[4]
        seq_low = byte_list[5]
        len_high = byte_list[6]
        len_low = byte_list[7]
        padding = byte_list[8]
        
        sync_word = (sync_high << 8) | sync_low
        sequence = (seq_high << 8) | seq_low
        payload_length = (len_high << 8) | len_low
        
        # Validate sync word
        if sync_word != 0xABCD:
            return None
        
        # Verify we have enough bytes for entire packet
        total_len = self.HEADER_SIZE + payload_length + self.CHECKSUM_SIZE
        if len(byte_list) < total_len:
            return None
        
        # Read payload: starts after padding (offset 9), length given by payload_length
        payload_start = 9
        payload_end = payload_start + payload_length
        payload = bytes(byte_list[payload_start:payload_end])
        
        # Checksum data calculation matches encode_packet:
        # bytes[0:8] (header excluding padding) + payload
        # which equals bytes[0:8] + bytes[9:9+payload_length]
        checksum_data = bytes(byte_list[0:8]) + payload
        calculated_checksum = CRC16CCITT.calculate(checksum_data)
        
        # Read stored checksum (at end of packet)
        cs_start = payload_end
        check_high = byte_list[cs_start]
        check_low = byte_list[cs_start + 1]
        checksum = (check_high << 8) | check_low
        
        if calculated_checksum != checksum:
            self.checksum_errors += 1
            return None
        
        # Build packet
        return UARTPacket(
            sync_word=sync_word,
            version=version,
            frame_type=frame_type,
            sequence=sequence,
            payload_length=payload_length,
            payload=payload,
            checksum=checksum
        )
    
    def simulate_transmission(self, timeout: float = None) -> List[UARTPacket]:
        """
        Simulate transmission by moving all TX bytes to RX and decoding packets.
        
        Args:
            timeout: Maximum time to wait (ignored in simulation)
            
        Returns:
            List of all packets received
        """
        self._flush_rx_buffer_to_queue()
        
        packets = []
        while True:
            packet = self.read_available()
            if packet is None:
                break
            packets.append(packet)
        
        return packets
    
    def get_statistics(self) -> dict:
        """Get UART engine statistics."""
        return {
            'baud_rate': self.baud_rate,
            'packets_sent': self.packets_sent,
            'packets_received': self.packets_received,
            'bytes_transmitted': self.bytes_transmitted,
            'bytes_received': self.bytes_received,
            'checksum_errors': self.checksum_errors,
            'sequence_errors': self.sequence_errors,
            'total_transmission_time': self.total_transmission_time
        }
    
    def reset_statistics(self):
        """Reset all statistics counters."""
        self.packets_sent = 0
        self.packets_received = 0
        self.bytes_transmitted = 0
        self.bytes_received = 0
        self.checksum_errors = 0
        self.sequence_errors = 0
        self.total_transmission_time = 0.0


def create_packet(frame_type: FrameType, payload: bytes = b'', sequence: int = None) -> UARTPacket:
    """
    Factory function to create a UART packet.
    
    Args:
        frame_type: Type of frame (TELEMETRY, COMMAND, etc.)
        payload: Payload data
        sequence: Sequence number (None for auto-increment)
        
    Returns:
        Configured UARTPacket instance
    """
    return UARTPacket(
        sync_word=0xABCD,
        version=1,
        frame_type=frame_type.value,
        sequence=sequence if sequence is not None else 0,
        payload=payload
    )
