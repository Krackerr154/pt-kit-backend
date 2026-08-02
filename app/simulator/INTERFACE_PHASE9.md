# Phase 9 Interface Contract: Full System Integration Testing

## Objective
Prove all 8 layers work together as one coherent digital twin. No new features — verification, regression consolidation, and E2E validation only.

## Baseline (measured 2026-08-02, full suite `pytest tests/ --ignore=tests/test_models.py`)
- **489 passed, 48 failed, 55 errors**
- `tests/test_models.py` EXCLUDED permanently from simulator scope (imports app.main → psycopg2 → production DB stack)

### Failure clusters (full-suite run):
| Cluster | Count | Nature |
|---------|-------|--------|
| test_isolated_backend_api.py | 30 ERRORS | Passes 30/30 in isolation → cross-test contamination (fixture/state collision from another module) |
| test_dashboard_server.py | 25 ERRORS + 6 FAILED | Likely same contamination class |
| test_simulator_virtual_uart.py | 16 FAILED | e.g. test_decode_empty_packet expects sequence 0x0100, gets 1 → test's byte-order assumption vs implementation; verify against docs/phase4-uart-protocol-spec.md before changing either side |
| test_simulator_controller_modes.py | 8 FAILED | TBD |
| test_batch_processor.py | 8 FAILED | Known: test/API name mismatches vs BatchProcessorManager |
| test_simulator_termination_semantics.py | 5 FAILED | TBD |
| test_historical_analysis.py | 5 FAILED | Known: sync/async signature mismatches |

## Ground rules
1. Implementation is AUTHORITY where golden traces already validated it (Phases 4-6 gates passed). Fix TESTS to match implementation unless the protocol spec (docs/phase4-uart-protocol-spec.md) proves the implementation wrong.
2. NEVER touch `/api/insert_data`, physical command cache, calibration state, production DB. Simulator uses `/api/simulator/*` only.
3. Determinism: seed 42 must produce identical traces run-to-run.
4. STOP command must NOT trigger firmware ABORT semantics.
5. Python 3.11, pytest, asyncio_mode=strict (pytest-asyncio 1.3.0 installed).
6. Run tests with `--ignore=tests/test_models.py` always.

## Task split
- **Task 9.1**: Fix cross-test contamination so full suite runs clean (isolated_backend_api + dashboard_server errors). Root-cause the module-order dependency (run `pytest tests/test_A.py tests/test_isolated_backend_api.py` pairs to bisect). Deliver: conftest.py fixes / fixture isolation, zero ERRORs in full-suite run.
- **Task 9.2**: Fix failing unit tests: virtual_uart (16), controller_modes (8), termination_semantics (5), batch_processor (8), historical_analysis (5). Test-side fixes preferred per rule 1.
- **Task 9.3**: New E2E integration test file `tests/test_phase9_integration.py`: profile→plant→sensors→arduino→uart→esp32→backend pipeline; golden trace determinism cross-layer (seed 42, two runs, byte-identical); isolation verification (no production endpoint ever called — assert via mock/spy); fault injection mid-run recovery.

## Acceptance gate
`python -m pytest tests/ --ignore=tests/test_models.py -q` → **0 failed, 0 errors**.
