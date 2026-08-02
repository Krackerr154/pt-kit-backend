from __future__ import annotations

from pathlib import Path

import pytest

from app.simulator.arduino_binding import ArduinoHostController
from app.simulator.arduino_runner import ArduinoControllerRunner, RawSensorSample
from app.simulator.clock import VirtualClock


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def controller_library(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("ptkit-runner") / "libptkit_sim.so"
    compiler = "g++"
    import shutil
    import subprocess

    if shutil.which(compiler) is None:
        pytest.fail("g++ is required for runner tests")
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            "-fPIC",
            "-shared",
            "-IArduino",
            "-IArduino/sim",
            "Arduino/PTKitController.cpp",
            "Arduino/sim/PTKitSimulationCAPI.cpp",
            "-o",
            str(output),
        ],
        cwd=ROOT,
        check=True,
    )
    return output


def make_runner(library: Path) -> tuple[VirtualClock, ArduinoControllerRunner]:
    clock = VirtualClock()
    controller = ArduinoHostController.load(library)
    runner = ArduinoControllerRunner(
        controller,
        clock,
        lambda _now: RawSensorSample(ir_c=31.0, tc_c=31.0, lux=5000.0),
    )
    return clock, runner


def test_runner_schedules_controller_ticks_on_virtual_clock(controller_library: Path) -> None:
    clock, runner = make_runner(controller_library)
    try:
        runner.start()
        runner.run_until(999)
        assert runner.trace == []
        assert clock.now_ms == 999

        runner.run_until(3000)
        ticks = [event for event in runner.trace if event["event"] == "arduino-control"]
        assert [event["at_ms"] for event in ticks] == [1000, 2000, 3000]
        assert all(event["stepped"] is True for event in ticks)
    finally:
        runner.stop()
        runner.controller.close()


def test_set_blocking_delay_advances_authoritative_clock(controller_library: Path) -> None:
    clock, runner = make_runner(controller_library)
    try:
        assert runner.send_command("SET:1:1:80:1:5000")
        assert clock.now_ms == 2000
        runner.start()
        runner.run_until(3000)
        ticks = [event for event in runner.trace if event["event"] == "arduino-control"]
        assert [event["at_ms"] for event in ticks] == [3000]
    finally:
        runner.stop()
        runner.controller.close()


def test_runner_replay_is_independent_of_clock_advance_chunking(controller_library: Path) -> None:
    def run(chunks: list[int]) -> list[dict[str, object]]:
        clock, runner = make_runner(controller_library)
        try:
            runner.send_command("SET2:1:1:80:1:MAX_OUTPUT")
            runner.start()
            for target in chunks:
                runner.run_until(target)
            return runner.trace
        finally:
            runner.stop()
            runner.controller.close()

    assert run([3000]) == run([2000, 2500, 3000])
