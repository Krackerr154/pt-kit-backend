"""Canonical event priorities for the deterministic simulator scheduler.

Lower numeric values run first when events share a virtual timestamp.  Components
must use these priorities rather than relying on their wall-clock execution order.
"""

from enum import IntEnum


class EventPriority(IntEnum):
    """Execution order for events scheduled at the same virtual millisecond."""

    FAULT = 0
    PLANT_INTEGRATION = 1
    SENSOR_SAMPLING = 2
    ARDUINO_CONTROL = 3
    UART_BYTE_DELIVERY = 4
    ESP32_ACTION = 5
    BACKEND_PUBLICATION = 6


PRIORITY_FAULT = EventPriority.FAULT
PRIORITY_PLANT_INTEGRATION = EventPriority.PLANT_INTEGRATION
PRIORITY_SENSOR_SAMPLING = EventPriority.SENSOR_SAMPLING
PRIORITY_ARDUINO_CONTROL = EventPriority.ARDUINO_CONTROL
PRIORITY_UART_BYTE_DELIVERY = EventPriority.UART_BYTE_DELIVERY
PRIORITY_ESP32_ACTION = EventPriority.ESP32_ACTION
PRIORITY_BACKEND_PUBLICATION = EventPriority.BACKEND_PUBLICATION

VALID_PRIORITIES = frozenset(EventPriority)

__all__ = [
    "EventPriority",
    "PRIORITY_FAULT",
    "PRIORITY_PLANT_INTEGRATION",
    "PRIORITY_SENSOR_SAMPLING",
    "PRIORITY_ARDUINO_CONTROL",
    "PRIORITY_UART_BYTE_DELIVERY",
    "PRIORITY_ESP32_ACTION",
    "PRIORITY_BACKEND_PUBLICATION",
]
