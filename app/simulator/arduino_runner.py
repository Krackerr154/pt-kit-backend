"""VirtualClock integration for the shared Arduino controller binding."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .arduino_binding import ArduinoHostController
from .clock import VirtualClock
from .events import EventPriority


@dataclass(frozen=True)
class RawSensorSample:
    """Raw sensor values supplied to the controller at a virtual timestamp."""

    ir_c: float
    tc_c: float
    lux: float


SensorProvider = Callable[[int], RawSensorSample]


class ArduinoControllerRunner:
    """Drive the shared Arduino core from one authoritative virtual clock.

    This runner intentionally does not model plant or UART behavior yet. It
    schedules only Arduino control events; later phases attach plant sampling,
    byte-oriented UART delivery, and ESP32 actions at their defined priorities.
    """

    def __init__(
        self,
        controller: ArduinoHostController,
        clock: VirtualClock,
        sensor_provider: SensorProvider,
    ) -> None:
        self.controller = controller
        self.clock = clock
        self.sensor_provider = sensor_provider
        self.trace: list[dict[str, object]] = []
        self._next_event: int | None = None
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._schedule_next_tick()

    def stop(self) -> None:
        if self._next_event is not None:
            self.clock.cancel(self._next_event)
            self._next_event = None
        self._started = False

    def send_command(self, command: str | bytes) -> bool:
        """Deliver a command at the clock's current time and record its bytes."""

        self.controller.set_time(self.clock.now_ms)
        accepted = self.controller.send_command(command)
        output = self.controller.read_output().decode("ascii")
        snapshot = self.controller.snapshot()
        raw_controller_now = snapshot["now_ms"]
        if not isinstance(raw_controller_now, int):
            raise RuntimeError("controller snapshot returned a non-integer now_ms")
        controller_now = raw_controller_now
        # Blocking platform operations, such as SET's physical confirmation
        # pause, consume virtual time before the next scheduled tick.
        if controller_now > self.clock.now_ms:
            self.clock.advance_to(controller_now)
        self.trace.append(
            {
                "event": "command",
                "at_ms": self.clock.now_ms,
                "command": command.decode("ascii") if isinstance(command, bytes) else command,
                "accepted": accepted,
                "uart": output,
            }
        )
        return accepted

    def run_until(self, target_ms: int) -> None:
        self.clock.advance_to(target_ms)

    def _schedule_next_tick(self) -> None:
        if not self._started:
            return
        at_ms = self.clock.now_ms + 1000
        self._next_event = self.clock.schedule(
            at_ms,
            EventPriority.ARDUINO_CONTROL,
            self._tick,
            label="arduino-control-tick",
        )

    def _tick(self) -> None:
        self._next_event = None
        now_ms = self.clock.now_ms
        sample = self.sensor_provider(now_ms)
        self.controller.set_time(now_ms)
        self.controller.set_raw_sensors(sample.ir_c, sample.tc_c, sample.lux)
        stepped = self.controller.step()
        self.trace.append(
            {
                "event": "arduino-control",
                "at_ms": now_ms,
                "stepped": stepped,
                "sample": {
                    "ir_c": sample.ir_c,
                    "tc_c": sample.tc_c,
                    "lux": sample.lux,
                },
                "snapshot": self.controller.snapshot(),
                "uart": self.controller.read_output().decode("ascii"),
            }
        )
        self._schedule_next_tick()


__all__ = ["ArduinoControllerRunner", "RawSensorSample", "SensorProvider"]
