"""Deterministic discrete-event virtual clock."""

from __future__ import annotations

import heapq
import itertools
from collections.abc import Callable
from typing import Any

from .events import VALID_PRIORITIES

_UINT32_MODULUS = 1 << 32


def _validate_milliseconds(value: int, *, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer number of milliseconds")
    if value < 0:
        raise ValueError(f"{name} must not be negative")


def firmware_millis(virtual_ms: int) -> int:
    """Convert monotonic virtual time to firmware ``uint32_t millis()``.

    Firmware sees only the low 32 bits, so ``0xffffffff`` is followed by zero.
    Scheduling itself always uses the unbounded monotonic virtual timestamp; this
    helper is only for values exposed to firmware logic.
    """

    _validate_milliseconds(virtual_ms, name="virtual_ms")
    return virtual_ms % _UINT32_MODULUS


class VirtualClock:
    """A pauseable deterministic discrete-event scheduler.

    ``advance_to`` returns ``None``.  While paused it is a no-op: neither virtual
    time nor callbacks progress.  Playback speed deliberately is not represented
    here; a caller may pace calls to ``advance_to`` using wall time.
    """

    def __init__(self) -> None:
        self._now_ms = 0
        self._paused = False
        self._sequence = itertools.count()
        self._events: list[tuple[int, int, int, int, Callable[[], Any], str]] = []
        self._pending_event_ids: set[int] = set()
        self._cancelled: set[int] = set()

    @property
    def now_ms(self) -> int:
        return self._now_ms

    @property
    def paused(self) -> bool:
        return self._paused

    def schedule(
        self,
        at_ms: int,
        priority: int,
        callback: Callable[[], Any],
        *,
        label: str,
    ) -> int:
        """Schedule a zero-argument callback and return its monotonic event ID."""

        _validate_milliseconds(at_ms, name="at_ms")
        if at_ms < self._now_ms:
            raise ValueError("cannot schedule an event in the past")
        if not isinstance(priority, int) or isinstance(priority, bool):
            raise TypeError("priority must be an integer event priority")
        if priority not in VALID_PRIORITIES:
            raise ValueError("priority must be a defined simulator event priority")
        if not callable(callback):
            raise TypeError("callback must be callable")
        if not isinstance(label, str):
            raise TypeError("label must be a string")
        if not label.strip():
            raise ValueError("label must not be empty")

        sequence = next(self._sequence)
        event_id = sequence
        self._pending_event_ids.add(event_id)
        heapq.heappush(
            self._events,
            (at_ms, int(priority), sequence, event_id, callback, label),
        )
        return event_id

    def advance_to(self, target_ms: int) -> None:
        """Run every event due through ``target_ms`` unless the clock is paused."""

        _validate_milliseconds(target_ms, name="target_ms")
        if target_ms < self._now_ms:
            raise ValueError("cannot advance virtual time backwards")
        if self._paused:
            return

        while self._events and self._events[0][0] <= target_ms:
            at_ms, _priority, _sequence, event_id, callback, _label = heapq.heappop(
                self._events
            )
            self._pending_event_ids.remove(event_id)
            if event_id in self._cancelled:
                self._cancelled.remove(event_id)
                continue
            self._now_ms = at_ms
            callback()
            if self._paused:
                return

        self._now_ms = target_ms

    def cancel(self, event_id: int) -> None:
        """Cancel an event if present; unknown or repeated IDs are harmless."""

        if not isinstance(event_id, int) or isinstance(event_id, bool):
            raise TypeError("event_id must be an integer")
        if event_id in self._pending_event_ids:
            self._cancelled.add(event_id)

    def pause(self) -> None:
        """Freeze virtual time and event execution until resumed."""

        self._paused = True

    def resume(self) -> None:
        """Permit subsequent calls to ``advance_to`` to progress again."""

        self._paused = False


__all__ = ["VirtualClock", "firmware_millis"]
