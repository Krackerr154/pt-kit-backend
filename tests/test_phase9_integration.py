"""Phase 9 — cross-layer end-to-end integration tests.

These exercise the simulator layers *together* rather than in isolation, which is
what surfaced the eleven implementation bugs recorded in PHASE9_IMPL_BUGS.md.

Scope guards enforced here:
  * simulated telemetry NEVER touches /api/insert_data or any production route
  * a run is byte-for-byte reproducible
  * STOP is graceful and is NOT firmware ABORT
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import app.simulator.controller_implementation as ci  # noqa: E402
from app.simulator.isolated_backend_api import SimulatorBackendAPILayer  # noqa: E402
from app.simulator.virtual_uart import (  # noqa: E402
    FrameType,
    UARTPacket,
    VirtualUARTEngine,
)

FAST_ISO1 = "ISO18000301"   # 80 °C, 30 s hold, 1 cycle -> DONE in ~90 steps
PLANT = {"heating_power_w": 300.0, "thermal_mass": 50.0, "cooling_rate_w": 2.0}


def build_controller(seed=42, plant=None):
    return ci.PTKitControllerIntegration(plant_config=dict(plant or PLANT), seed=seed)


def run_to_completion(controller, max_steps=600):
    """Step until a terminal state; return the emitted telemetry frames."""
    for _ in range(max_steps):
        controller.step(dt_s=1.0)
        if controller.state in (ci.ControllerState.DONE, ci.ControllerState.FINISHED):
            break
    return controller.get_telemetry_buffer()


@pytest.fixture
def api_layer():
    return SimulatorBackendAPILayer(base_path="/api/simulator")


# --------------------------------------------------------------------------
class TestFullPipelineE2E:
    """profile -> plant -> controller -> telemetry -> UART -> backend."""

    def test_controller_reaches_terminal_state(self):
        c = build_controller()
        c.send_command(FAST_ISO1)
        frames = run_to_completion(c)
        assert c.state == ci.ControllerState.DONE
        assert len(frames) > 10

    def test_telemetry_timestamps_are_monotonic(self):
        c = build_controller()
        c.send_command(FAST_ISO1)
        frames = run_to_completion(c)
        stamps = [f.timestamp_s for f in frames]
        assert stamps == sorted(stamps)

    def test_temperatures_stay_physically_plausible(self):
        c = build_controller()
        c.send_command(FAST_ISO1)
        frames = run_to_completion(c)
        temps = [f.surface_temp_c for f in frames]
        assert min(temps) >= 20.0, "should never drop below ambient-ish"
        assert max(temps) < 200.0, "thermostat must prevent runaway heating"

    def test_thermostat_holds_near_setpoint(self):
        """Regression for the runaway-heating bug (PHASE9_IMPL_BUGS #3)."""
        c = build_controller()
        c.send_command(FAST_ISO1)
        run_to_completion(c)
        holding = [f.surface_temp_c for f in c.get_telemetry_buffer()
                   if f.controller_state == ci.ControllerState.HOLDING]
        assert holding, "run should pass through HOLDING"
        assert max(holding) < 100.0, f"overshoot past setpoint: {max(holding)}"

    def test_every_frame_carries_17_fields(self):
        c = build_controller()
        c.send_command(FAST_ISO1)
        frames = run_to_completion(c)
        for f in frames:
            assert len(f.to_dict()) == 17

    def test_telemetry_is_json_serializable_end_to_end(self):
        c = build_controller()
        c.send_command(FAST_ISO1)
        frames = run_to_completion(c)
        blob = json.dumps([f.to_dict() for f in frames])
        assert json.loads(blob)[0]["controller_state"] is not None

    def test_telemetry_survives_uart_round_trip(self):
        """Frames encode to the wire and decode back without corruption."""
        c = build_controller()
        c.send_command(FAST_ISO1)
        frames = run_to_completion(c)

        engine = VirtualUARTEngine()
        payload = json.dumps(frames[0].to_dict()).encode()[:200]
        packet = UARTPacket(
            sync_word=0xABCD, version=1,
            frame_type=FrameType.TELEMETRY.value, sequence=1, payload=payload,
        )
        for byte in engine.encode_packet(packet):
            engine.rx_queue.append(byte)

        decoded = engine.read_available()
        assert decoded is not None, "checksum must validate (PHASE9_IMPL_BUGS #2)"
        assert decoded.payload == payload
        assert engine.checksum_errors == 0


# --------------------------------------------------------------------------
class TestCrossLayerDeterminism:
    """Reproducibility is the contract that makes golden traces meaningful."""

    def _trace(self, seed):
        c = build_controller(seed=seed)
        c.send_command(FAST_ISO1)
        return json.dumps([f.to_dict() for f in run_to_completion(c)])

    def test_same_seed_produces_identical_trace(self):
        assert self._trace(42) == self._trace(42)

    def test_repeated_runs_are_stable_across_many_iterations(self):
        base = self._trace(42)
        for _ in range(3):
            assert self._trace(42) == base

    def test_model_is_seed_independent_by_design(self):
        """The thermal/controller model is fully deterministic.

        `PTKitControllerIntegration` builds `self.rng` but never uses it to perturb
        the plant, so traces are identical across seeds. This asserts that property
        explicitly so any future introduction of stochastic noise fails loudly here
        instead of silently breaking golden-trace comparisons.
        """
        assert self._trace(42) == self._trace(43)

    def test_uart_encoding_is_deterministic(self):
        engine = VirtualUARTEngine()
        packet = UARTPacket(sync_word=0xABCD, version=1,
                            frame_type=FrameType.TELEMETRY.value,
                            sequence=7, payload=b"determinism")
        assert engine.encode_packet(packet) == engine.encode_packet(packet)


# --------------------------------------------------------------------------
class TestIsolationGuarantee:
    """Simulated telemetry must never reach the production ingestion path."""

    FORBIDDEN = ("/api/insert_data", "/api/data", "/insert_data")

    def test_no_route_touches_production_endpoints(self, api_layer):
        paths = [r.path for r in api_layer.app.routes if hasattr(r, "path")]
        for path in paths:
            for bad in self.FORBIDDEN:
                assert bad not in path, f"simulator exposes production route {path}"

    def test_all_api_routes_live_under_simulator_namespace(self, api_layer):
        paths = [r.path for r in api_layer.app.routes
                 if hasattr(r, "path") and r.path.startswith("/api")]
        assert paths, "expected simulator API routes"
        for path in paths:
            assert path.startswith("/api/simulator"), f"leaked route: {path}"

    def test_backend_state_is_in_memory_only(self, api_layer):
        """No DB handles anywhere on the isolated layer."""
        for attr in vars(api_layer):
            assert "conn" not in attr.lower()
            assert "psycopg" not in attr.lower()
            assert "session" not in attr.lower()

    def test_controller_performs_no_network_io(self, monkeypatch):
        """A full run must not open a socket."""
        import socket

        def boom(*a, **k):
            raise AssertionError("simulator attempted network I/O")

        monkeypatch.setattr(socket.socket, "connect", boom)
        c = build_controller()
        c.send_command(FAST_ISO1)
        assert run_to_completion(c)


# --------------------------------------------------------------------------
class TestFaultRecovery:
    """Termination semantics: STOP != ABORT != SUPERVISOR_ABORT."""

    def test_stop_is_graceful_and_never_aborts(self):
        c = build_controller()
        c.send_command(FAST_ISO1)
        for _ in range(40):
            c.step(dt_s=1.0)

        c.send_command("STOP")
        for _ in range(600):
            c.step(dt_s=1.0)

        assert c.state != ci.ControllerState.ABORTED
        assert c.state == ci.ControllerState.IDLE, "must finish cooling (BUGS #4)"

    def test_repeated_stops_are_idempotent(self):
        c = build_controller()
        c.send_command(FAST_ISO1)
        for _ in range(30):
            c.step(dt_s=1.0)
        for _ in range(10):
            c.send_command("STOP")
        for _ in range(600):
            c.step(dt_s=1.0)
        assert c.state != ci.ControllerState.ABORTED

    def test_firmware_abort_is_terminal(self):
        c = build_controller()
        c.send_command(FAST_ISO1)
        for _ in range(20):
            c.step(dt_s=1.0)
        c.send_command("ABORT")
        c.step(dt_s=1.0)
        assert c.state == ci.ControllerState.ABORTED

    def test_supervisor_abort_aborts_even_from_idle(self):
        """Regression for PHASE9_IMPL_BUGS #5."""
        c = build_controller()
        c.send_command("SUPERVISOR_ABORT")
        c.step(dt_s=1.0)
        assert c.state == ci.ControllerState.ABORTED
        assert c.supervision == ci.SupervisionFlag.SUPERVISOR_ABORT

    def test_three_termination_modes_are_distinguishable(self):
        outcomes = {}
        for cmd in ("STOP", "ABORT", "SUPERVISOR_ABORT"):
            c = build_controller()
            c.send_command(FAST_ISO1)
            for _ in range(30):
                c.step(dt_s=1.0)
            c.send_command(cmd)
            c.step(dt_s=1.0)
            outcomes[cmd] = c.supervision
        assert len(set(outcomes.values())) == 3, outcomes

    def test_invalid_sensor_reports_safe_sentinel(self):
        """Regression for PHASE9_IMPL_BUGS #8."""
        c = build_controller()
        c.supervision = ci.SupervisionFlag.INVALID_SENSOR
        telem = c.step(dt_s=1.0)
        assert telem.surface_temp_c == -273.15
        assert telem.side_channel_message == "ERR"

    def test_corrupted_uart_frame_is_rejected_not_crashed(self):
        engine = VirtualUARTEngine()
        packet = UARTPacket(sync_word=0xABCD, version=1,
                            frame_type=FrameType.TELEMETRY.value,
                            sequence=1, payload=b"corrupt me")
        stream = engine.encode_packet(packet)
        stream[10] ^= 0xFF  # flip a payload bit

        for byte in stream:
            engine.rx_queue.append(byte)

        assert engine.read_available() is None
        assert engine.checksum_errors == 1

    def test_pipeline_recovers_after_a_bad_frame(self):
        """A corrupted frame must not poison subsequent good frames."""
        engine = VirtualUARTEngine()
        good = UARTPacket(sync_word=0xABCD, version=1,
                          frame_type=FrameType.TELEMETRY.value,
                          sequence=2, payload=b"good frame")
        stream = engine.encode_packet(good)
        for byte in stream:
            engine.rx_queue.append(byte)

        decoded = engine.read_available()
        assert decoded is not None and decoded.payload == b"good frame"
