import pytest

from app.simulator.clock import VirtualClock, firmware_millis
from app.simulator.events import (
    PRIORITY_ARDUINO_CONTROL,
    PRIORITY_BACKEND_PUBLICATION,
    PRIORITY_ESP32_ACTION,
    PRIORITY_FAULT,
    PRIORITY_PLANT_INTEGRATION,
    PRIORITY_SENSOR_SAMPLING,
    PRIORITY_UART_BYTE_DELIVERY,
)


PRIORITIES = (
    PRIORITY_FAULT,
    PRIORITY_PLANT_INTEGRATION,
    PRIORITY_SENSOR_SAMPLING,
    PRIORITY_ARDUINO_CONTROL,
    PRIORITY_UART_BYTE_DELIVERY,
    PRIORITY_ESP32_ACTION,
    PRIORITY_BACKEND_PUBLICATION,
)


def test_priority_constants_define_required_order():
    assert PRIORITIES == tuple(sorted(PRIORITIES))
    assert len(set(PRIORITIES)) == 7


def test_clock_starts_at_zero_and_advances_without_events():
    clock = VirtualClock()

    result = clock.advance_to(25)

    assert result is None
    assert clock.now_ms == 25


def test_events_are_ordered_by_time_then_priority():
    clock = VirtualClock()
    trace = []
    clock.schedule(20, PRIORITY_FAULT, lambda: trace.append("late"), label="late")
    clock.schedule(10, PRIORITY_SENSOR_SAMPLING, lambda: trace.append("sensor"), label="sensor")
    clock.schedule(10, PRIORITY_FAULT, lambda: trace.append("fault"), label="fault")

    clock.advance_to(20)

    assert trace == ["fault", "sensor", "late"]


def test_same_time_same_priority_events_run_in_scheduling_order():
    clock = VirtualClock()
    trace = []
    for item in ("first", "second", "third"):
        clock.schedule(
            10,
            PRIORITY_SENSOR_SAMPLING,
            lambda item=item: trace.append(item),
            label=item,
        )

    clock.advance_to(10)

    assert trace == ["first", "second", "third"]


def test_schedule_returns_distinct_monotonic_event_ids():
    clock = VirtualClock()

    event_ids = [
        clock.schedule(0, PRIORITY_FAULT, lambda: None, label=str(index))
        for index in range(3)
    ]

    assert event_ids[0] < event_ids[1] < event_ids[2]
    assert len(set(event_ids)) == 3


def test_scheduling_in_the_past_is_rejected():
    clock = VirtualClock()
    clock.advance_to(5)

    with pytest.raises(ValueError, match="past"):
        clock.schedule(4, PRIORITY_FAULT, lambda: None, label="past")


def test_backwards_advancement_is_rejected():
    clock = VirtualClock()
    clock.advance_to(5)

    with pytest.raises(ValueError, match="backwards"):
        clock.advance_to(4)


def test_cancellation_is_idempotent_and_prevents_execution():
    clock = VirtualClock()
    trace = []
    event_id = clock.schedule(5, PRIORITY_FAULT, lambda: trace.append("ran"), label="cancelled")

    clock.cancel(event_id)
    clock.cancel(event_id)
    clock.cancel(999_999)
    clock.advance_to(5)

    assert trace == []


def test_cancelling_unknown_id_does_not_pre_cancel_a_future_event():
    clock = VirtualClock()
    trace = []
    clock.cancel(1)
    clock.schedule(0, PRIORITY_FAULT, lambda: None, label="event zero")
    future_event_id = clock.schedule(
        0, PRIORITY_FAULT, lambda: trace.append("ran"), label="event one"
    )

    clock.advance_to(0)

    assert future_event_id == 1
    assert trace == ["ran"]


def test_pause_makes_advance_a_documented_no_op_until_resume():
    clock = VirtualClock()
    trace = []
    clock.schedule(10, PRIORITY_FAULT, lambda: trace.append("ran"), label="event")
    clock.pause()

    result = clock.advance_to(100)

    assert result is None
    assert clock.paused is True
    assert clock.now_ms == 0
    assert trace == []

    clock.resume()
    clock.advance_to(100)
    assert clock.paused is False
    assert clock.now_ms == 100
    assert trace == ["ran"]


def test_pause_and_resume_are_idempotent():
    clock = VirtualClock()

    clock.pause()
    clock.pause()
    clock.resume()
    clock.resume()

    assert clock.paused is False


def test_external_pacing_does_not_change_trace_or_live_on_clock():
    def run_with_pacing(advance_points):
        clock = VirtualClock()
        trace = []
        for at_ms, priority, name in (
            (100, PRIORITY_BACKEND_PUBLICATION, "publish"),
            (50, PRIORITY_SENSOR_SAMPLING, "sample"),
            (50, PRIORITY_FAULT, "fault"),
        ):
            clock.schedule(at_ms, priority, lambda name=name: trace.append(name), label=name)
        for target_ms in advance_points:
            clock.advance_to(target_ms)
        assert not hasattr(clock, "playback_speed")
        return trace

    assert run_with_pacing([100]) == run_with_pacing([10, 25, 50, 75, 100])


def test_large_jump_executes_every_due_event_at_its_virtual_time():
    clock = VirtualClock()
    trace = []
    for at_ms in (1_000_000, 2, 50_000, 0, 999_999):
        clock.schedule(
            at_ms,
            PRIORITY_PLANT_INTEGRATION,
            lambda at_ms=at_ms: trace.append((clock.now_ms, at_ms)),
            label=str(at_ms),
        )

    clock.advance_to(2_000_000)

    assert trace == [(value, value) for value in (0, 2, 50_000, 999_999, 1_000_000)]
    assert clock.now_ms == 2_000_000


def test_callback_can_schedule_due_events_that_rejoin_heap_order():
    clock = VirtualClock()
    trace = []

    def plant_callback():
        trace.append("plant")
        clock.schedule(10, PRIORITY_BACKEND_PUBLICATION, lambda: trace.append("publish"), label="publish")
        clock.schedule(10, PRIORITY_FAULT, lambda: trace.append("new fault"), label="new fault")

    clock.schedule(10, PRIORITY_PLANT_INTEGRATION, plant_callback, label="plant")
    clock.schedule(10, PRIORITY_SENSOR_SAMPLING, lambda: trace.append("sensor"), label="sensor")

    clock.advance_to(10)

    assert trace == ["plant", "new fault", "sensor", "publish"]


@pytest.mark.parametrize("at_ms", [-1, 1.5, "1", True, None])
def test_invalid_schedule_times_are_rejected(at_ms):
    clock = VirtualClock()

    expected = ValueError if at_ms == -1 else TypeError
    with pytest.raises(expected):
        clock.schedule(at_ms, PRIORITY_FAULT, lambda: None, label="invalid time")


@pytest.mark.parametrize("priority", [-1, 1.5, "1", True, None])
def test_invalid_priorities_are_rejected(priority):
    clock = VirtualClock()

    expected = ValueError if priority == -1 else TypeError
    with pytest.raises(expected):
        clock.schedule(0, priority, lambda: None, label="invalid priority")


@pytest.mark.parametrize("callback", [None, 7, "call me"])
def test_non_callable_callbacks_are_rejected(callback):
    clock = VirtualClock()

    with pytest.raises(TypeError, match="callback"):
        clock.schedule(0, PRIORITY_FAULT, callback, label="invalid callback")


@pytest.mark.parametrize("label", [None, 7, "", "   "])
def test_invalid_labels_are_rejected(label):
    clock = VirtualClock()

    expected = ValueError if isinstance(label, str) else TypeError
    with pytest.raises(expected):
        clock.schedule(0, PRIORITY_FAULT, lambda: None, label=label)


@pytest.mark.parametrize("target_ms", [-1, 1.5, "1", True, None])
def test_invalid_advance_targets_are_rejected(target_ms):
    clock = VirtualClock()

    expected = ValueError if target_ms == -1 else TypeError
    with pytest.raises(expected):
        clock.advance_to(target_ms)


def test_firmware_millis_converts_virtual_time_with_uint32_rollover():
    assert firmware_millis(0) == 0
    assert firmware_millis(0xFFFFFFFF) == 0xFFFFFFFF
    assert firmware_millis(0x1_0000_0000) == 0
    assert firmware_millis(0x1_0000_0001) == 1


@pytest.mark.parametrize("virtual_ms", [-1, 1.5, "1", True, None])
def test_firmware_millis_rejects_invalid_virtual_times(virtual_ms):
    expected = ValueError if virtual_ms == -1 else TypeError
    with pytest.raises(expected):
        firmware_millis(virtual_ms)
