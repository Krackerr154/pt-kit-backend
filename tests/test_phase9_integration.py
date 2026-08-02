"""
Phase 9 Task 9.3 - Cross-Layer E2E Integration Suite.

Wires the complete digital-twin stack and verifies it behaves as ONE system:

    profile -> plant -> sensors -> arduino runner -> virtual UART
            -> ESP32 bridge -> SimulatorBackendAPILayer

Covered contracts (per app/simulator/INTERFACE_PHASE9.md):
  * Full pipeline delivers plausible telemetry with monotonic timestamps.
  * Determinism: seed 42 reproduces byte-identical traces; seed 43 diverges.
  * Isolation: /api/insert_data is never routed nor called; everything lives
    under /api/simulator, and a full run performs zero production calls.
  * Fault recovery: mid-run fault injection is survived and reported, and a
    STOP command terminates gracefully WITHOUT entering ABORTED state.

No network access. No database. No production endpoints.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from fastapi.testclient import TestClient

from app.simulator import profiles as sim_profiles
from app.simulator import virtual_uart as vuart
from app.simulator.arduino_binding import ArduinoHostController
from app.simulator.arduino_runner import ArduinoControllerRunner, RawSensorSample
from app.simulator.clock import VirtualClock
from app.simulator.esp32_bridge_simulator import (
    ESP32BridgeSimulator,
    SimulatorBackendAPIClient,
)
from app.simulator.fault_injector import FaultInjector, FaultType
from app.simulator.isolated_backend_api import RunState, SimulatorBackendAPILayer
from app.simulator.plant import ThermalPlant
from app.simulator.sensors import make_sensor

ROOT = Path(__file__).resolve().parents[1]

# Endpoints that belong to the PRODUCTION ingestion stack. The simulator must
# never route to, nor call, any of these.
PRODUCTION_ENDPOINTS = (
    "/api/insert_data",
    "/api/experiments",
    "/api/start_experiment",
    "/api/stop_experiment",
    "/api/calibration",
)

# FastAPI auto-generates these; they carry schema only, never simulation data.
SCHEMA_INFRA_ROUTES = {"/openapi.json", "/docs/oauth2-redirect"}

BASE_PATH = "/api/simulator"

# The API layer opens a run in STARTING and accepts telemetry throughout; it has
# no endpoint that promotes STARTING -> EXPERIMENT_RUNNING. Both are therefore
# legitimate "live, not terminated" states. (Implementation is authority per
# INTERFACE_PHASE9.md ground rule 1.)
ACTIVE_RUN_STATES = {
    RunState.STARTING.value,
    RunState.EXPERIMENT_RUNNING.value,
}


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(scope="module")
def controller_library(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Compile the shared Arduino controller core once for the whole module."""
    if shutil.which("g++") is None:
        pytest.fail("g++ is required to build the Arduino host binding")

    output = tmp_path_factory.mktemp("ptkit-phase9") / "libptkit_sim.so"
    subprocess.run(
        [
            "g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pedantic",
            "-fPIC", "-shared", "-IArduino", "-IArduino/sim",
            "Arduino/PTKitController.cpp",
            "Arduino/sim/PTKitSimulationCAPI.cpp",
            "-o", str(output),
        ],
        cwd=ROOT,
        check=True,
    )
    return output


# =============================================================================
# Pipeline harness - wires every layer together
# =============================================================================


class PipelineHarness:
    """End-to-end harness binding all eight simulator layers.

    Every layer is the real implementation; nothing here is mocked. The harness
    only supplies the glue that a real deployment would provide (sensor
    provider callback, telemetry marshalling, transport pumping).
    """

    SET_COMMAND = "SET:1:1:80:1:5000"

    def __init__(
        self,
        library: Path,
        seed: int = 42,
        fault_injector: FaultInjector | None = None,
    ) -> None:
        self.seed = seed
        self.fault_injector = fault_injector

        # --- Layer 1: profile -> plant configuration -------------------------
        self.profile = sim_profiles.load_default_profile()
        self.plant = ThermalPlant(self.profile.to_plant_config())

        # --- Layer 2: sensors ------------------------------------------------
        self.sensor = make_sensor(seed=seed)

        # --- Layer 3: authoritative virtual clock ----------------------------
        self.clock = VirtualClock()

        # --- Layer 4: Arduino firmware core ----------------------------------
        self.controller = ArduinoHostController.load(library)
        self.runner = ArduinoControllerRunner(
            self.controller, self.clock, self._sensor_provider
        )

        # --- Layer 5: virtual UART transport ---------------------------------
        self.uart = vuart.VirtualUARTEngine(baud_rate=115200)

        # --- Layer 6: ESP32 bridge -------------------------------------------
        self.bridge = ESP32BridgeSimulator(seed=seed)
        self.bridge.initialize()

        # --- Layer 7: isolated backend API -----------------------------------
        self.api = SimulatorBackendAPILayer(base_path=BASE_PATH)
        self.client = TestClient(self.api.app)

        # --- Recorded artefacts ----------------------------------------------
        self.frames: list[dict[str, Any]] = []
        self.uart_streams: list[bytes] = []
        self.decoded_packets: list[Any] = []
        self.corrupted_frames = 0
        self.run_id: str | None = None
        self._closed = False

    # -- pipeline glue --------------------------------------------------------

    def _sensor_provider(self, now_ms: int) -> RawSensorSample:
        """Plant + sensor stack feeding the firmware, driven by the clock."""
        snapshot = self.controller.snapshot()
        lamp_pwm = int(snapshot.get("lamp_pwm") or 0)
        fan_pwm = int(snapshot.get("fan_pwm") or 0)
        plant_state = self.plant.step(lamp_pwm, fan_pwm, 1.0)
        reading = self.sensor.sample(plant_state, 1.0)
        return RawSensorSample(
            ir_c=reading.ir_temp_c, tc_c=reading.tc_temp_c, lux=reading.lux
        )

    def start_run(self, duration: int = 60, cycles: int = 2) -> str:
        """Open a run on the isolated backend and arm the firmware."""
        response = self.client.post(
            f"{BASE_PATH}/runs/start",
            json={
                "operator_name": "phase9-e2e",
                "sample_name": "cross-layer-sample",
                "description": "Phase 9 integration run",
                "duration": duration,
                "cycles": cycles,
                "max_temp": 80.0,
                "interval": 1,
                "target_lux": 5000.0,
                "illumination_mode": "TARGET_LUX",
                "mode": "NORMAL_CYCLIC",
                "control_sensor": "IR",
            },
        )
        assert response.status_code == 200, response.text
        self.run_id = response.json()["run_id"]

        assert self.runner.send_command(self.SET_COMMAND) is True
        self.runner.start()
        self._base_ms = self.clock.now_ms
        return self.run_id

    def step(self, index: int) -> dict[str, Any]:
        """Advance one virtual second and push telemetry through every layer."""
        self.runner.run_until(self._base_ms + index * 1000)
        snapshot = self.controller.snapshot()

        frame = {
            "total_time": int(snapshot["total_seconds"]),
            "phase_time": int(snapshot["state_seconds"]),
            "cycle_num": int(snapshot["cycle"]),
            "state_code": int(snapshot["state"]),
            "ir_temp": round(float(snapshot["temp_ir_c"]), 6),
            "tc_temp": round(float(snapshot["temp_tc_c"]), 6),
            "current_lux": round(float(snapshot["smoothed_lux"]), 6),
            "lamp_pwm": float(snapshot["lamp_pwm"]),
            "virtual_time_s": self.clock.now_ms / 1000.0,
        }

        # --- UART encode -> (optional fault) -> ESP32 decode ------------------
        packet = vuart.create_packet(
            vuart.FrameType.TELEMETRY,
            json.dumps(frame, sort_keys=True).encode("utf-8"),
            sequence=index,
        )
        stream = bytes(self.uart.encode_packet(packet))
        self.uart_streams.append(stream)

        wire = stream
        if self.fault_injector is not None:
            wire = self.fault_injector.inject_bit_flip(stream)

        self.uart.transmit_bytes(list(wire))
        decoded = self.uart.read_available()
        if decoded is None:
            # Checksum rejected the frame: the transport survived a corruption.
            self.corrupted_frames += 1
            self.uart.rx_queue.clear()
            self.bridge.state.add_fault(
                "UART_CHECKSUM_ERROR", f"Frame {index} failed CRC validation"
            )
        else:
            self.decoded_packets.append(decoded)
            self.bridge.forward_telemetry_to_backend(frame)
            payload = {k: v for k, v in frame.items() if k != "virtual_time_s"}
            posted = self.client.post(
                f"{BASE_PATH}/runs/{self.run_id}/telemetry", json=payload
            )
            assert posted.status_code == 200, posted.text
            self.frames.append(frame)

        return frame

    def run(self, steps: int = 10) -> list[dict[str, Any]]:
        for index in range(1, steps + 1):
            self.step(index)
        return self.frames

    # -- artefacts ------------------------------------------------------------

    def canonical_trace(self) -> str:
        """Deterministic, wall-clock-free serialization of the whole run."""
        return json.dumps(
            {
                "seed": self.seed,
                "frames": self.frames,
                "uart_streams": [s.hex() for s in self.uart_streams],
                "final_clock_ms": self.clock.now_ms,
            },
            sort_keys=True,
        )

    def exported_frames(self) -> list[dict[str, Any]]:
        """API-exported telemetry with server wall-clock stamps stripped."""
        export = self.api.export_run_data(self.run_id)
        return [
            {k: v for k, v in frame.items() if k != "timestamp_s"}
            for frame in export["telemetry_frames"]
        ]

    def state(self) -> str:
        response = self.client.get(f"{BASE_PATH}/runs/{self.run_id}")
        assert response.status_code == 200, response.text
        return response.json()["state"]

    def stop(self) -> dict[str, Any]:
        response = self.client.post(f"{BASE_PATH}/runs/{self.run_id}/stop")
        assert response.status_code == 200, response.text
        return response.json()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.runner.stop()
        self.controller.close()
        self.client.close()


@pytest.fixture
def harness(controller_library: Path):
    """A fresh, fully-wired pipeline seeded at 42."""
    instance = PipelineHarness(controller_library, seed=42)
    try:
        yield instance
    finally:
        instance.close()


@pytest.fixture
def completed_run(harness: PipelineHarness) -> PipelineHarness:
    """A harness that has already executed a 10-step run."""
    harness.start_run()
    harness.run(steps=10)
    return harness


# =============================================================================
# 1. Full pipeline end-to-end
# =============================================================================


class TestFullPipelineE2E:
    """profile -> plant -> sensors -> arduino -> UART -> ESP32 -> backend."""

    def test_every_layer_is_wired(self, harness: PipelineHarness):
        """All eight layers instantiate and bind without adapters or stubs."""
        harness.start_run()

        assert harness.profile.profile_id
        assert harness.plant is not None
        assert harness.sensor is not None
        assert isinstance(harness.clock, VirtualClock)
        assert harness.runner.controller is harness.controller
        assert harness.uart.baud_rate == 115200
        assert harness.bridge.state.uart_connected is True
        assert harness.api.base_path == BASE_PATH

    def test_pipeline_delivers_telemetry_end_to_end(self, completed_run):
        """Ten clock steps produce ten frames at every downstream layer."""
        assert len(completed_run.frames) == 10
        assert len(completed_run.decoded_packets) == 10
        assert len(completed_run.bridge.get_telemetry_history()) == 10
        assert len(completed_run.exported_frames()) == 10

    def test_telemetry_values_are_physically_plausible(self, completed_run):
        """Sensor/actuator values stay inside real hardware envelopes."""
        for frame in completed_run.frames:
            assert -40.0 <= frame["ir_temp"] <= 200.0
            assert -50.0 <= frame["tc_temp"] <= 250.0
            assert 0.0 <= frame["current_lux"] <= 20000.0
            assert 0.0 <= frame["lamp_pwm"] <= 255.0
            assert frame["cycle_num"] >= 0
            assert frame["state_code"] >= 0

    def test_timestamps_are_strictly_monotonic(self, completed_run):
        """Virtual time never stalls or moves backwards across the run."""
        times = [f["virtual_time_s"] for f in completed_run.frames]
        assert times == sorted(times)
        assert all(b > a for a, b in zip(times, times[1:]))
        assert times[0] == pytest.approx(3.0)
        assert times[-1] == pytest.approx(12.0)

    def test_total_time_counter_advances_monotonically(self, completed_run):
        """Firmware's own elapsed-seconds counter is non-decreasing."""
        totals = [f["total_time"] for f in completed_run.frames]
        assert totals == sorted(totals)
        assert totals[-1] > totals[0]

    def test_plant_responds_to_lamp_actuation(self, completed_run):
        """Lamp drive raises surface temperature: the loop is genuinely closed."""
        assert any(f["lamp_pwm"] > 0 for f in completed_run.frames)
        assert completed_run.frames[-1]["ir_temp"] > completed_run.frames[0]["ir_temp"]

    def test_uart_frames_survive_the_transport(self, completed_run):
        """Encoded frames decode back with intact 9-byte header + CRC16 layout."""
        for stream in completed_run.uart_streams:
            assert stream[0] == 0xAB and stream[1] == 0xCD  # sync word
            payload_len = (stream[6] << 8) | stream[7]
            assert len(stream) == 9 + payload_len + 2  # header + payload + CRC

        stats = completed_run.uart.get_statistics()
        assert stats["checksum_errors"] == 0
        assert stats["packets_received"] == 10

    def test_bridge_reassembles_payloads_faithfully(self, completed_run):
        """What the ESP32 decodes equals what the firmware emitted."""
        for frame, packet in zip(completed_run.frames, completed_run.decoded_packets):
            decoded = json.loads(packet.payload.decode("utf-8"))
            assert decoded == frame
            assert packet.frame_type == vuart.FrameType.TELEMETRY.value

    def test_backend_status_reflects_live_run(self, completed_run):
        """The API layer reports RUNNING with the latest frame attached."""
        response = completed_run.client.get(f"{BASE_PATH}/runs/{completed_run.run_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["state"] in ACTIVE_RUN_STATES
        assert body["state"] != RunState.ABORTED.value
        assert body["last_telemetry"]["total_time"] == \
            completed_run.frames[-1]["total_time"]

    @pytest.mark.asyncio
    async def test_async_telemetry_history_endpoint(self, completed_run):
        """Telemetry is retrievable over an async ASGI transport."""
        import httpx

        transport = httpx.ASGITransport(app=completed_run.api.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://sim"
        ) as client:
            response = await client.get(
                f"{BASE_PATH}/runs/{completed_run.run_id}/telemetry"
            )
        assert response.status_code == 200
        assert len(response.json()["frames"]) == 10


# =============================================================================
# 2. Cross-layer determinism
# =============================================================================


class TestCrossLayerDeterminism:
    """Seed 42 must reproduce byte-identical traces; seed 43 must diverge."""

    @staticmethod
    def _run(library: Path, seed: int, steps: int = 8) -> tuple[str, list, list]:
        harness = PipelineHarness(library, seed=seed)
        try:
            harness.start_run()
            harness.run(steps=steps)
            return (
                harness.canonical_trace(),
                harness.exported_frames(),
                list(harness.uart_streams),
            )
        finally:
            harness.close()

    def test_seed_42_reproduces_identical_trace(self, controller_library):
        """Two independent seed-42 runs are byte-identical."""
        first, _, _ = self._run(controller_library, 42)
        second, _, _ = self._run(controller_library, 42)
        assert first == second

    def test_seed_42_differs_from_seed_43(self, controller_library):
        """Changing the seed changes the trace: the RNG really is wired in."""
        seeded_42, _, _ = self._run(controller_library, 42)
        seeded_43, _, _ = self._run(controller_library, 43)
        assert seeded_42 != seeded_43

    def test_uart_byte_streams_are_reproducible(self, controller_library):
        """Determinism holds all the way down to the wire format."""
        _, _, streams_a = self._run(controller_library, 42)
        _, _, streams_b = self._run(controller_library, 42)
        assert [s.hex() for s in streams_a] == [s.hex() for s in streams_b]

    def test_uart_byte_streams_diverge_across_seeds(self, controller_library):
        """Different seeds produce different bytes on the wire."""
        _, _, streams_42 = self._run(controller_library, 42)
        _, _, streams_43 = self._run(controller_library, 43)
        assert [s.hex() for s in streams_42] != [s.hex() for s in streams_43]

    def test_api_exports_match_after_normalization(self, controller_library):
        """Backend exports agree once server wall-clock stamps are removed."""
        _, export_a, _ = self._run(controller_library, 42)
        _, export_b, _ = self._run(controller_library, 42)
        assert export_a == export_b
        assert len(export_a) == 8

    def test_plant_and_sensor_layers_are_deterministic(self, controller_library):
        """Determinism originates in the physics/sensor layers themselves."""
        def sample(seed: int) -> list[tuple[float, float, float]]:
            profile = sim_profiles.load_default_profile()
            plant = ThermalPlant(profile.to_plant_config())
            sensor = make_sensor(seed=seed)
            out = []
            for _ in range(20):
                state = plant.step(180, 40, 0.5)
                reading = sensor.sample(state, 0.5)
                out.append((reading.ir_temp_c, reading.tc_temp_c, reading.lux))
            return out

        assert sample(42) == sample(42)
        assert sample(42) != sample(43)

    def test_fault_injector_is_seed_deterministic(self):
        """Fault scheduling replays exactly, so faults are reproducible."""
        def events(seed: int) -> list[str]:
            injector = FaultInjector(seed=seed)
            injector.set_active(True)
            injector.set_injection_rate(0.5)
            for step in range(15):
                injector.advance_time(0.1)
                injector.inject_bit_flip(bytes([step] * 8))
                injector.should_drop_packet()
            return [e.description for e in injector.get_events()]

        assert events(42) == events(42)
        assert events(42) != events(43)


# =============================================================================
# 3. Isolation guarantee
# =============================================================================


class TestIsolationGuarantee:
    """The simulator must be provably incapable of touching production."""

    def test_no_route_touches_production_endpoints(self, harness: PipelineHarness):
        """No registered route starts with /api/insert_data or friends."""
        paths = [getattr(r, "path", "") for r in harness.api.app.routes]
        for path in paths:
            for forbidden in PRODUCTION_ENDPOINTS:
                assert not path.startswith(forbidden), f"leaked route: {path}"

    def test_all_functional_routes_live_under_base_path(self, harness):
        """Every data-bearing route is namespaced under /api/simulator."""
        paths = {getattr(r, "path", "") for r in harness.api.app.routes}
        functional = paths - SCHEMA_INFRA_ROUTES
        assert functional, "expected at least one functional route"
        for path in functional:
            assert path.startswith(BASE_PATH), f"route outside namespace: {path}"

    def test_production_paths_are_not_served(self, harness: PipelineHarness):
        """Requesting a production endpoint on the simulator app 404s."""
        for endpoint in PRODUCTION_ENDPOINTS:
            for response in (
                harness.client.get(endpoint),
                harness.client.post(endpoint, json={}),
            ):
                assert response.status_code in (404, 405), endpoint

    def test_full_run_makes_zero_production_calls(self, controller_library, monkeypatch):
        """Spy on the bridge's backend client: only /api/simulator is ever hit."""
        seen: list[str] = []
        original = SimulatorBackendAPIClient.post_telemetry_frame

        def spy(self, frame):
            seen.append(f"{self.base_url}/telemetry")
            return original(self, frame)

        monkeypatch.setattr(
            SimulatorBackendAPIClient, "post_telemetry_frame", spy
        )

        harness = PipelineHarness(controller_library, seed=42)
        try:
            harness.start_run()
            harness.run(steps=6)
        finally:
            harness.close()

        assert len(seen) == 6
        for endpoint in seen:
            assert endpoint.startswith(BASE_PATH)
            assert not any(p in endpoint for p in PRODUCTION_ENDPOINTS)

    def test_bridge_self_reports_isolation(self, completed_run):
        """The ESP32 bridge's own audit of its request log passes."""
        assert completed_run.bridge.verify_backend_isolation() is True
        requests = completed_run.bridge.get_backend_requests()
        assert len(requests) == 10
        for request in requests:
            assert request["endpoint"].startswith(BASE_PATH)

    def test_run_opens_no_network_sockets(self, controller_library, monkeypatch):
        """Patch socket.connect to prove the pipeline is fully in-process."""
        connections: list[Any] = []
        original_connect = socket.socket.connect

        def guarded_connect(self, address):  # pragma: no cover - must not run
            connections.append(address)
            raise AssertionError(f"simulator attempted a network call: {address}")

        monkeypatch.setattr(socket.socket, "connect", guarded_connect)

        harness = PipelineHarness(controller_library, seed=42)
        try:
            harness.start_run()
            harness.run(steps=5)
            harness.stop()
        finally:
            harness.close()
            monkeypatch.setattr(socket.socket, "connect", original_connect)

        assert connections == []

    def test_api_layer_holds_state_in_memory_only(self, completed_run):
        """State lives in RAM; the layer declares itself isolated."""
        assert completed_run.api.verify_isolation() is True
        state = completed_run.api.get_in_memory_state()
        assert state["telemetry_counts"][completed_run.run_id] == 10
        assert completed_run.run_id in state["runs"]

    @pytest.mark.asyncio
    async def test_async_health_confirms_isolation_flag(self, harness):
        """Health endpoint advertises isolation over async transport too."""
        import httpx

        transport = httpx.ASGITransport(app=harness.api.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://sim"
        ) as client:
            response = await client.get(f"{BASE_PATH}/health")
        assert response.status_code == 200
        assert response.json()["isolated_from_production"] is True


# =============================================================================
# 4. Fault recovery and termination semantics
# =============================================================================


class TestFaultRecovery:
    """Mid-run faults are survivable; STOP must never mean ABORT."""

    def test_injected_bit_flip_is_detected_not_silently_accepted(self, controller_library):
        """A corrupted frame fails CRC instead of poisoning the dataset."""
        injector = FaultInjector(seed=42)
        injector.set_active(True)
        injector.set_injection_rate(1.0)

        harness = PipelineHarness(controller_library, seed=42, fault_injector=injector)
        try:
            harness.start_run()
            harness.run(steps=5)
            assert harness.corrupted_frames > 0
            assert harness.uart.get_statistics()["checksum_errors"] > 0
            assert len(harness.frames) < 5
        finally:
            harness.close()

    def test_pipeline_survives_fault_injected_midrun(self, controller_library):
        """Faults for a window; the pipeline resumes delivering afterwards."""
        injector = FaultInjector(seed=42)
        injector.set_active(False)

        harness = PipelineHarness(controller_library, seed=42, fault_injector=injector)
        try:
            harness.start_run()
            harness.run(steps=3)          # clean
            healthy_before = len(harness.frames)
            assert healthy_before == 3

            injector.set_active(True)     # fault window opens mid-run
            injector.set_injection_rate(1.0)
            for index in range(4, 7):
                harness.step(index)
            assert harness.corrupted_frames > 0

            injector.set_active(False)    # fault clears
            for index in range(7, 11):
                harness.step(index)

            # The run continued and recovered rather than dying.
            assert len(harness.frames) > healthy_before
            assert harness.state() in ACTIVE_RUN_STATES
            assert harness.state() != RunState.ABORTED.value
        finally:
            harness.close()

    def test_status_reflects_the_injected_fault(self, controller_library):
        """Faults are recorded on the bridge and in the injector's summary."""
        injector = FaultInjector(seed=42)
        injector.set_active(True)
        injector.set_injection_rate(1.0)

        harness = PipelineHarness(controller_library, seed=42, fault_injector=injector)
        try:
            harness.start_run()
            harness.run(steps=5)

            assert harness.bridge.get_state()["fault_count"] > 0
            faults = [f.to_dict() for f in harness.bridge.state.faults]
            assert any(f["code"] == "UART_CHECKSUM_ERROR" for f in faults)

            summary = injector.get_summary()
            assert summary["successful_injections"] > 0
            assert any(
                e.fault_type == FaultType.BIT_FLIP_ERROR for e in injector.get_events()
            )
        finally:
            harness.close()

    def test_telemetry_after_fault_is_still_plausible(self, controller_library):
        """Recovered frames carry sane physics, not corrupted garbage."""
        injector = FaultInjector(seed=42)
        injector.set_active(True)
        injector.set_injection_rate(1.0)

        harness = PipelineHarness(controller_library, seed=42, fault_injector=injector)
        try:
            harness.start_run()
            harness.run(steps=4)
            injector.set_active(False)
            for index in range(5, 9):
                harness.step(index)

            recovered = harness.frames[-1]
            assert -40.0 <= recovered["ir_temp"] <= 200.0
            assert 0.0 <= recovered["current_lux"] <= 20000.0
            times = [f["virtual_time_s"] for f in harness.frames]
            assert all(b > a for a, b in zip(times, times[1:]))
        finally:
            harness.close()

    def test_stop_terminates_gracefully_without_aborting(self, completed_run):
        """STOP -> COMPLETED. It must never be reported as ABORTED."""
        assert completed_run.state() in ACTIVE_RUN_STATES

        result = completed_run.stop()
        assert result["status"] == "stopped"

        final = completed_run.state()
        assert final == RunState.COMPLETED.value
        assert final != RunState.ABORTED.value

    def test_stop_after_fault_still_completes_not_aborts(self, controller_library):
        """Even a fault-scarred run stops cleanly rather than aborting."""
        injector = FaultInjector(seed=42)
        injector.set_active(True)
        injector.set_injection_rate(1.0)

        harness = PipelineHarness(controller_library, seed=42, fault_injector=injector)
        try:
            harness.start_run()
            harness.run(steps=5)
            assert harness.corrupted_frames > 0

            harness.stop()
            assert harness.state() == RunState.COMPLETED.value
            assert harness.state() != RunState.ABORTED.value

            export = harness.api.export_run_data(harness.run_id)
            assert export["final_state"] == RunState.COMPLETED.value
        finally:
            harness.close()

    def test_stop_preserves_collected_telemetry(self, completed_run):
        """Graceful termination keeps the dataset intact for analysis."""
        before = len(completed_run.exported_frames())
        completed_run.stop()
        after = completed_run.exported_frames()
        assert len(after) == before == 10
        assert after[-1]["total_time"] == completed_run.frames[-1]["total_time"]

    def test_aborted_state_never_observed_during_normal_lifecycle(self, controller_library):
        """Track every state transition; ABORTED must never appear."""
        harness = PipelineHarness(controller_library, seed=42)
        observed: list[str] = []
        try:
            harness.start_run()
            observed.append(harness.state())
            for index in range(1, 6):
                harness.step(index)
                observed.append(harness.state())
            harness.stop()
            observed.append(harness.state())
        finally:
            harness.close()

        assert RunState.ABORTED.value not in observed
        assert observed[-1] == RunState.COMPLETED.value
        assert set(observed) <= ACTIVE_RUN_STATES | {RunState.COMPLETED.value}
        assert set(observed[:-1]) <= ACTIVE_RUN_STATES
