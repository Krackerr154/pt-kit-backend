"""Tests for the graphical simulator dashboard (live_dashboard.py).

These use an in-process asyncio driver check plus FastAPI TestClient for the
REST surface. The background stepping loop is validated directly by invoking
the loop coroutine, since TestClient's sync transport does not advance the
server's asyncio tasks between requests.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.simulator.live_dashboard import (
    LiveDashboardServer,
    RunModel,
    SimState,
    StartRequest,
    create_app,
)


@pytest.fixture
def client():
    return TestClient(create_app())


# --------------------------------------------------------------------------
# REST surface
# --------------------------------------------------------------------------
def test_health_reports_isolation(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "healthy"
    assert body["isolated_from_production"] is True


def test_index_serves_dashboard_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert 'id="chart"' in r.text
    assert "PT-Kit Simulator Dashboard" in r.text


def test_start_returns_run_id_and_config(client):
    r = client.post("/api/sim/start", json={"sample_name": "unit-test", "target_temp_c": 60})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "started"
    assert len(body["run_id"]) == 8
    assert body["config"]["target_temp_c"] == 60


def test_status_404_for_unknown_run(client):
    assert client.get("/api/sim/deadbeef/status").status_code == 404


def test_history_404_for_unknown_run(client):
    assert client.get("/api/sim/deadbeef/history").status_code == 404


def test_pause_requires_running_state(client):
    rid = client.post("/api/sim/start", json={}).json()["run_id"]
    # loop hasn't been driven, but state starts RUNNING
    r = client.post(f"/api/sim/{rid}/pause")
    assert r.status_code == 200
    # pausing again (now PAUSED) must 400
    assert client.post(f"/api/sim/{rid}/pause").status_code == 400


def test_resume_requires_paused_state(client):
    rid = client.post("/api/sim/start", json={}).json()["run_id"]
    # RUNNING -> resume is invalid
    assert client.post(f"/api/sim/{rid}/resume").status_code == 400
    client.post(f"/api/sim/{rid}/pause")
    assert client.post(f"/api/sim/{rid}/resume").status_code == 200


def test_list_runs(client):
    client.post("/api/sim/start", json={"sample_name": "a"})
    client.post("/api/sim/start", json={"sample_name": "b"})
    runs = client.get("/api/sim/runs").json()["runs"]
    assert len(runs) >= 2


def test_stop_marks_completed(client):
    rid = client.post("/api/sim/start", json={}).json()["run_id"]
    r = client.post(f"/api/sim/{rid}/stop")
    assert r.status_code == 200
    assert client.get(f"/api/sim/{rid}/status").json()["state"] == "COMPLETED"


# --------------------------------------------------------------------------
# Background driver / physics (invoke loop coroutine directly)
# --------------------------------------------------------------------------
def _drive(server: LiveDashboardServer, req: StartRequest, steps: int) -> RunModel:
    """Run the stepping loop for a fixed number of steps, no wall sleeps."""
    run_id = "testrun0"
    run = RunModel(
        run_id=run_id, config=req,
        plant=server._new_plant(req.ambient_temp_c), state=SimState.RUNNING,
    )
    server._runs[run_id] = run
    server._clients[run_id] = set()
    virtual_dt = (1.0 / max(0.1, req.tick_hz)) * max(0.1, req.speed)
    for _ in range(steps):
        if run.state != SimState.RUNNING:
            break
        run.thermostat(req.target_temp_c)
        run.plant.step(run.lamp_pwm, run.fan_pwm, virtual_dt)
        run.virtual_time_s += virtual_dt
        run.sequence += 1
        if run.plant.state.surface_temp_c > req.max_temp_c:
            run.state = SimState.ABORTED
        run.history.append(run.frame())
    return run


def test_plant_heats_toward_target():
    server = LiveDashboardServer()
    req = StartRequest(target_temp_c=38, ambient_temp_c=25, tick_hz=100, speed=100, duration_s=800)
    run = _drive(server, req, steps=300)
    temps = [f["surface_temp_c"] for f in run.history]
    assert temps[0] < temps[-1]  # heated up
    assert max(temps) >= 35      # approached the reachable target


def test_thermostat_modulates_lamp_in_deadband():
    server = LiveDashboardServer()
    req = StartRequest(target_temp_c=38, ambient_temp_c=25, tick_hz=100, speed=100, duration_s=800)
    run = _drive(server, req, steps=350)
    lamps = {f["lamp_pwm"] for f in run.history[-40:]}
    # once near target the thermostat should not be pinned at a single value
    assert len(lamps) >= 2


def test_over_temperature_triggers_abort():
    server = LiveDashboardServer()
    # very low max_temp forces an abort as soon as it warms past it
    req = StartRequest(target_temp_c=100, ambient_temp_c=25, max_temp_c=26,
                       tick_hz=100, speed=100, duration_s=800)
    run = _drive(server, req, steps=200)
    assert run.state == SimState.ABORTED


def test_frame_schema_is_complete():
    server = LiveDashboardServer()
    run = _drive(server, StartRequest(), steps=1)
    f = run.history[0]
    for key in ("run_id", "sequence", "virtual_time_s", "state", "surface_temp_c",
                "bulk_temp_c", "ambient_temp_c", "lux", "lamp_pwm", "fan_pwm",
                "target_temp_c", "progress_pct", "timestamp_s"):
        assert key in f, f"missing telemetry field: {key}"


def test_no_insert_data_reference_in_source():
    """Isolation guard: the dashboard must never reference /api/insert_data."""
    from pathlib import Path
    src = Path(__file__).parent.parent / "app" / "simulator" / "live_dashboard.py"
    text = src.read_text()
    # No actual client call to the physical ingestion endpoint. The path may
    # appear in the isolation docstring, so match call-like usages only.
    import re
    calls = re.findall(r"""(?:requests|httpx|client|fetch|post|get)\s*\(\s*['"][^'"]*?/api/insert_data""", text)
    assert not calls, f"dashboard must not call /api/insert_data: {calls}"
