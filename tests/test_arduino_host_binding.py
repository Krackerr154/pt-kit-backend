"""Differential-contract tests for the shared host Arduino controller core."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.simulator.arduino_binding import ArduinoHostController


ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = ROOT / "tests" / "fixtures" / "simulator" / "arduino_golden"


def _build_host_library(output: Path) -> None:
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.fail("g++ is required for the host controller binding tests")
    command = [
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
    ]
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)


@pytest.fixture(scope="module")
def controller_library(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("ptkit-host") / "libptkit_sim.so"
    _build_host_library(output)
    return output


def _normal_trace(controller: ArduinoHostController, command: str) -> list[dict[str, object]]:
    trace = [{"event": "command", "command": command, "accepted": controller.send_command(command)}]
    time_offset = 2000 if command.startswith("SET:") else 0
    for now, ir, tc, lux in [
        (1000, 31, 31, 5000),
        (2000, 31, 31, 5000),
        (3000, 31, 31, 5000),
        (4000, 28, 28, 0),
        (5000, 28, 28, 0),
        (6000, 28, 28, 0),
        (7000, 28, 28, 0),
        (8000, 28, 28, 0),
        (9000, 28, 28, 0),
        (10000, 28, 28, 0),
    ]:
        now += time_offset
        controller.set_time(now)
        controller.set_raw_sensors(ir, tc, lux)
        stepped = controller.step()
        trace.append(
            {
                "event": "step",
                "now_ms": now,
                "stepped": stepped,
                "snapshot": controller.snapshot(),
                "uart": controller.read_output().decode("ascii"),
            }
        )
    return trace


def _short_trace(
    controller: ArduinoHostController,
    command: str,
    samples: list[tuple[int, float, float, float]],
) -> list[dict[str, object]]:
    trace = [{"event": "command", "command": command, "accepted": controller.send_command(command)}]
    time_offset = 2000 if command.startswith("SET:") else 0
    for now, ir, tc, lux in samples:
        now += time_offset
        controller.set_time(now)
        controller.set_raw_sensors(ir, tc, lux)
        trace.append(
            {
                "event": "step",
                "now_ms": now,
                "stepped": controller.step(),
                "snapshot": controller.snapshot(),
                "uart": controller.read_output().decode("ascii"),
            }
        )
    return trace


def _scenario(controller: ArduinoHostController, name: str) -> list[dict[str, object]]:
    if name == "boot_idle":
        return _short_trace(controller, "<boot>", [(1000, 25, 25, 0)])
    if name == "normal_target_lux":
        return _normal_trace(controller, "SET:2:1:80:1:5000")
    if name == "normal_max_output":
        return _short_trace(
            controller,
            "SET2:2:1:90:1:MAX_OUTPUT",
            [(1000, 31, 31, 0), (2000, 31, 31, 0), (3000, 31, 31, 0)],
        )
    if name == "fixed_temperature":
        return _short_trace(
            controller,
            "ISO1:45:5:0.5:2:80:1:TC:6",
            [(1000, 30, 30, 0), (2000, 30, 30, 0), (3000, 30, 30, 0)],
        )
    if name == "plateau_passive":
        return _short_trace(
            controller,
            "PLAT1:5000:5:3:0.2:0.8:2:30:90:1:IR:PASSIVE",
            [(1000, 30, 30, 5000), (2000, 30, 30, 5000), (3000, 30, 30, 5000), (4000, 30, 30, 5000), (5000, 30, 30, 5000)],
        )
    if name == "plateau_regulated":
        return _short_trace(
            controller,
            "PLAT1:5000:5:3:0.2:0.8:2:30:90:1:IR:REGULATED",
            [(1000, 30, 30, 5000), (2000, 30, 30, 5000), (3000, 30, 30, 5000), (4000, 30, 30, 5000), (5000, 30, 30, 5000)],
        )
    if name == "stop_normal_preheat":
        return _short_trace(controller, "SET:60:1:80:1:5000", [(1000, 25, 25, 5000)]) + [
            {"event": "stop", "accepted": controller.send_command("STOP"), "snapshot": controller.snapshot(), "uart": controller.read_output().decode("ascii")}
        ]
    if name == "stop_fixed_ramp":
        return _short_trace(controller, "ISO1:45:5:0.5:2:80:1:TC:6", [(1000, 30, 30, 0)]) + [
            {"event": "stop", "accepted": controller.send_command("STOP"), "snapshot": controller.snapshot(), "uart": controller.read_output().decode("ascii")}
        ]
    if name == "stop_plateau_heating":
        return _short_trace(controller, "PLAT1:5000:5:3:0.2:0.8:2:30:90:1:IR:PASSIVE", [(1000, 25, 25, 5000)]) + [
            {"event": "stop", "accepted": controller.send_command("STOP"), "snapshot": controller.snapshot(), "uart": controller.read_output().decode("ascii")}
        ]
    if name == "invalid_selected_sensor":
        return _short_trace(
            controller,
            "ISO1:45:5:0.5:2:80:1:TC:6",
            [(1000, 30, float("nan"), 0), (2000, 30, float("nan"), 0), (11000, 30, float("nan"), 0)],
        )
    if name == "maximum_temperature":
        return _short_trace(controller, "ISO1:30:5:0.5:2:35:1:TC:6", [(1000, 40, 40, 5000)])
    if name == "calibration_commands":
        return [
            {"event": "command", "command": command, "accepted": controller.send_command(command), "snapshot": controller.snapshot(), "uart": controller.read_output().decode("ascii")}
            for command in ("CAL_BARE", "CAL_TAPE", "CAL_FULL")
        ]
    raise AssertionError(f"unknown scenario {name}")


SCENARIOS = (
    "boot_idle",
    "normal_target_lux",
    "normal_max_output",
    "fixed_temperature",
    "plateau_passive",
    "plateau_regulated",
    "stop_normal_preheat",
    "stop_fixed_ramp",
    "stop_plateau_heating",
    "invalid_selected_sensor",
    "maximum_temperature",
    "calibration_commands",
)


def test_host_binding_loads_shared_c_abi(controller_library: Path) -> None:
    with ArduinoHostController.load(controller_library) as controller:
        assert controller.snapshot()["state"] == 0
        assert controller.send_command("\tSET:1:1:80:1:5000\r\n")
        controller.set_time(3000)
        controller.set_raw_sensors(31, 31, 5000)
        assert controller.step()
        assert controller.snapshot()["state"] == 2
        assert controller.read_output().count(b"\n") == 1
        with pytest.raises(ValueError):
            controller.set_time(0x1_0000_0000)


def test_target_sketch_delegates_to_shared_controller() -> None:
    sketch = (ROOT / "Arduino" / "Arduino.ino").read_text()
    assert '#include "PTKitController.h"' in sketch
    assert "PTKitController controller(controllerPlatform);" in sketch
    assert "controller.command(data.c_str(), data.length());" in sketch
    assert "controller.step(raw);" in sketch


STOP_CASES = (
    ("normal-heating", "SET:2:1:80:1:5000", [(1000, 31, 31, 5000)], 2),
    ("normal-cooling", "SET:2:1:80:1:5000", [(1000, 31, 31, 5000), (2000, 31, 31, 5000), (3000, 31, 31, 5000)], 3),
    ("normal-stabilizing", "SET:2:1:80:1:5000", [(1000, 31, 31, 5000), (2000, 31, 31, 5000), (3000, 31, 31, 5000), (4000, 28, 28, 0)], 4),
    ("iso-ramp", "ISO1:45:5:0.5:2:80:1:TC:6", [(1000, 30, 30, 0)], 9),
    ("iso-qualify", "ISO1:45:5:0.5:2:80:1:TC:6", [(1000, 45, 45, 0)], 10),
    ("iso-hold", "ISO1:45:5:0.5:2:80:1:TC:6", [(1000, 45, 45, 0), (2000, 45, 45, 0), (3000, 45, 45, 0)], 11),
    ("plateau-heating", "PLAT1:5000:5:3:0.2:0.8:2:30:90:1:IR:PASSIVE", [(1000, 30, 30, 5000)], 12),
    ("plateau-confirm", "PLAT1:5000:5:3:0.2:0.8:2:30:90:1:IR:PASSIVE", [(1000, 30, 30, 5000), (2000, 30, 30, 5000), (3000, 30, 30, 5000)], 13),
    ("plateau-hold", "PLAT1:5000:5:3:0.2:0.8:2:30:90:1:IR:PASSIVE", [(1000, 30, 30, 5000), (2000, 30, 30, 5000), (3000, 30, 30, 5000), (4000, 30, 30, 5000), (5000, 30, 30, 5000)], 14),
    ("cal-bare", "CAL_BARE", [], 6),
    ("cal-tape", "CAL_TAPE", [], 7),
    ("cal-full", "CAL_FULL", [], 8),
    ("aborted", "ISO1:45:5:0.5:2:80:1:TC:6", [(1000, 30, float("nan"), 0), (2000, 30, float("nan"), 0), (11000, 30, float("nan"), 0)], 15),
    ("done", "SET:2:1:80:1:5000", [(1000, 31, 31, 5000), (2000, 31, 31, 5000), (3000, 31, 31, 5000), (4000, 28, 28, 0), (5000, 28, 28, 0), (6000, 28, 28, 0), (7000, 28, 28, 0), (8000, 28, 28, 0), (9000, 28, 28, 0)], 5),
)


@pytest.mark.parametrize("_name,command,samples,expected_state", STOP_CASES)
def test_stop_returns_to_idle_from_every_controller_phase(
    controller_library: Path,
    _name: str,
    command: str,
    samples: list[tuple[int, float, float, float]],
    expected_state: int,
) -> None:
    with ArduinoHostController.load(controller_library) as controller:
        assert controller.send_command(command)
        offset = 2000 if command.startswith("SET:") else 0
        for now, ir, tc, lux in samples:
            controller.set_time(now + offset)
            controller.set_raw_sensors(ir, tc, lux)
            controller.step()
        assert controller.snapshot()["state"] == expected_state, _name
        assert controller.send_command("STOP")
        snapshot = controller.snapshot()
        assert snapshot["state"] == 0
        assert snapshot["lamp_pwm"] == 0
        assert snapshot["fan_pwm"] == 0


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_golden_controller_trace(controller_library: Path, scenario: str) -> None:
    fixture = GOLDEN_DIR / f"{scenario}.json"
    assert fixture.is_file(), f"missing golden fixture: {fixture}"
    expected = json.loads(fixture.read_text())
    with ArduinoHostController.load(controller_library) as controller:
        actual = _scenario(controller, scenario)
    assert actual == expected


def test_golden_fixtures_cover_all_phase_one_scenarios() -> None:
    names = {path.stem for path in GOLDEN_DIR.glob("*.json")}
    assert names == set(SCENARIOS)
