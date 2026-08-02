"""Deterministic regression tests for ThermalPlant.

These tests verify core physical behavior without any randomness:

* Zero-output equilibrium at ambient temperature
* Heating monotonicity (lamps only)
* Stronger lamp increases heating rate
* Higher fan increases cooling rate
* Finite energy/temperatures under bounded inputs
* Irregular intervals match fine-step reference
* Ambient floor behavior (temps stay >= ambient when no power)

All assertions are exact within floating-point tolerance.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

# Add project root to Python path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dataclasses import replace

import pytest
from app.simulator.config import PlantConfig
from app.simulator.plant import PlantState, ThermalPlant


@pytest.fixture
def small_config() -> PlantConfig:
    """Minimal realistic parameters."""
    return PlantConfig(
        surface_capacity_j_per_k=10.0,  # J/K
        bulk_capacity_j_per_k=100.0,  # J/K
        surface_bulk_conductance_w_per_k=2.0,  # W/K
        surface_ambient_conductance_w_per_k=1.0,  # W/K
        bulk_ambient_conductance_w_per_k=0.5,  # W/K
        lamp_max_power_w=50.0,  # W at PWM=255
        lamp_response_time_s=0.1,  # s
        lamp_max_lux=50000.0,  # lux
        fan_max_conductance_w_per_k=3.0,  # W/K additional at PWM=255
        fan_response_time_s=0.1,  # s
        ambient_temp_c=25.0,  # °C
        max_substep_s=0.05,  # s
    )


@pytest.fixture
def medium_config() -> PlantConfig:
    """Parameters tuned for longer transients."""
    return PlantConfig(
        surface_capacity_j_per_k=15.0,  # J/K
        bulk_capacity_j_per_k=150.0,  # J/K
        surface_bulk_conductance_w_per_k=3.0,  # W/K
        surface_ambient_conductance_w_per_k=1.5,  # W/K
        bulk_ambient_conductance_w_per_k=0.8,  # W/K
        lamp_max_power_w=80.0,  # W
        lamp_response_time_s=0.08,  # s
        lamp_max_lux=80000.0,  # lux
        fan_max_conductance_w_per_k=4.5,  # W/K
        fan_response_time_s=0.08,  # s
        ambient_temp_c=20.0,  # °C
        max_substep_s=0.02,  # s
    )


@pytest.fixture
def zero_state(small_config: PlantConfig) -> PlantState:
    """Zero-output equilibrium state (all actuator outputs = 0)."""
    return PlantState(
        surface_temp_c=small_config.ambient_temp_c,
        bulk_temp_c=small_config.ambient_temp_c,
        ambient_temp_c=small_config.ambient_temp_c,
        lamp_output_lux=0.0,
        fan_airflow=0.0,
        lamp_pwm=0,
        fan_pwm=0,
        time_s=0.0,
    )


@pytest.fixture
def hot_initial_state(medium_config: PlantConfig) -> PlantState:
    """Non-equilibrium initial state (hot sample)."""
    t_amb = medium_config.ambient_temp_c
    t_surf = t_amb + 10.0
    t_bulk = t_amb + 50.0
    return PlantState(
        surface_temp_c=t_surf,
        bulk_temp_c=t_bulk,
        ambient_temp_c=t_amb,
        lamp_output_lux=0.0,
        fan_airflow=0.0,
        lamp_pwm=0,
        fan_pwm=0,
        time_s=0.0,
    )


class TestPlantConstruction:
    def test_default_initial_state_is_equilibrium(self, small_config: PlantConfig) -> None:
        plant = ThermalPlant(small_config)
        st = plant.state
        assert st.surface_temp_c == small_config.ambient_temp_c
        assert st.bulk_temp_c == small_config.ambient_temp_c
        assert st.ambient_temp_c == small_config.ambient_temp_c
        assert st.lamp_output_lux == 0.0
        assert st.fan_airflow == 0.0
        assert st.lamp_pwm == 0
        assert st.fan_pwm == 0
        assert st.time_s == 0.0

    def test_custom_initial_state(self, small_config: PlantConfig) -> None:
        init = PlantState(
            surface_temp_c=30.0,
            bulk_temp_c=35.0,
            ambient_temp_c=25.0,
            lamp_output_lux=25000.0,
            fan_airflow=0.5,
            lamp_pwm=128,
            fan_pwm=128,
            time_s=42.0,
        )
        plant = ThermalPlant(small_config, init)
        st = plant.state
        # Temperatures preserved exactly; other fields recoverable from state.
        assert math.isclose(st.surface_temp_c, 30.0)
        assert math.isclose(st.bulk_temp_c, 35.0)
        assert math.isclose(st.time_s, 42.0)
        assert st.lamp_pwm == 128
        assert st.fan_pwm == 128

    def test_reset_to_equilibrium(self, small_config: PlantConfig) -> None:
        init = PlantState(
            surface_temp_c=60.0,
            bulk_temp_c=70.0,
            ambient_temp_c=25.0,
            lamp_output_lux=40000.0,
            fan_airflow=0.8,
            lamp_pwm=200,
            fan_pwm=200,
            time_s=100.0,
        )
        plant = ThermalPlant(small_config, init)
        plant.step(255, 255, 1.0)
        plant.reset()
        st = plant.state
        assert st.surface_temp_c == small_config.ambient_temp_c
        assert st.bulk_temp_c == small_config.ambient_temp_c
        assert st.lamp_output_lux == 0.0
        assert st.fan_airflow == 0.0
        assert st.time_s == 0.0


class TestZeroOutputEquilibrium:
    """When lamp and fan remain off, temps should remain at ambient."""

    def test_zero_stays_at_ambient(self, small_config: PlantConfig, zero_state: PlantState) -> None:
        plant = ThermalPlant(small_config, zero_state)
        st = plant.state
        for _ in range(100):
            st = plant.step(0, 0, 0.1)
            assert st.time_s > 0.0
        # Floating-point tolerance for numerical stability
        tol = 1e-6
        assert abs(st.surface_temp_c - small_config.ambient_temp_c) < tol
        assert abs(st.bulk_temp_c - small_config.ambient_temp_c) < tol

    def test_zero_step_no_change(self, small_config: PlantConfig, zero_state: PlantState) -> None:
        plant = ThermalPlant(small_config, zero_state)
        st_before = plant.state
        st_after = plant.step(0, 0, 1.0)
        tol = 1e-9
        assert abs(st_before.surface_temp_c - st_after.surface_temp_c) < tol
        assert abs(st_before.bulk_temp_c - st_after.bulk_temp_c) < tol
        assert st_after.lamp_output_lux == 0.0
        assert st_after.fan_airflow == 0.0


class TestHeatingMonotonicity:
    """With lamps only, temperatures must rise monotonically."""

    def test_lamps_only_rises_surface(self, small_config: PlantConfig, zero_state: PlantState) -> None:
        plant = ThermalPlant(small_config, zero_state)
        prev_t_s = zero_state.surface_temp_c
        prev_t_b = zero_state.bulk_temp_c
        for dt in [0.1] * 10:
            st = plant.step(255, 0, dt)
            assert st.surface_temp_c > prev_t_s, "surface temp must strictly increase with full lamp"
            assert st.bulk_temp_c > prev_t_b, "bulk temp must strictly increase with full lamp"
            prev_t_s, prev_t_b = st.surface_temp_c, st.bulk_temp_c

    def test_lamps_only_rises_bulk(self, medium_config: PlantConfig, zero_state: PlantState) -> None:
        plant = ThermalPlant(medium_config, zero_state)
        t_bulk_init = zero_state.bulk_temp_c
        for _ in range(50):
            st = plant.step(255, 0, 0.2)
            assert st.bulk_temp_c > t_bulk_init
            t_bulk_init = st.bulk_temp_c

    def test_partial_lamp_raises_temperature(self, small_config: PlantConfig, zero_state: PlantState) -> None:
        plant = ThermalPlant(small_config, zero_state)
        t_start = zero_state.surface_temp_c
        st = plant.step(128, 0, 0.5)
        assert st.surface_temp_c > t_start
        assert st.bulk_temp_c > t_start


class TestStrongerLampIncreasesRate:
    """Comparing two runs, stronger lamp heats faster."""

    def test_128_vs_255_heats_faster(self, small_config: PlantConfig) -> None:
        init = PlantState(
            surface_temp_c=small_config.ambient_temp_c,
            bulk_temp_c=small_config.ambient_temp_c,
            ambient_temp_c=small_config.ambient_temp_c,
            lamp_output_lux=0.0,
            fan_airflow=0.0,
            lamp_pwm=0,
            fan_pwm=0,
            time_s=0.0,
        )
        low_cfg = replace(small_config, lamp_max_power_w=30.0)
        high_cfg = replace(small_config, lamp_max_power_w=30.0)

        plant_low = ThermalPlant(low_cfg, init)
        plant_high = ThermalPlant(high_cfg, init)

        for _ in range(20):
            plant_low.step(128, 0, 0.1)
            plant_high.step(255, 0, 0.1)

        assert plant_high.state.surface_temp_c > plant_low.state.surface_temp_c
        assert plant_high.state.bulk_temp_c > plant_low.state.bulk_temp_c

    def test_255_vs_0_demonstrates_rate_difference(self, small_config: PlantConfig) -> None:
        init = PlantState(
            surface_temp_c=small_config.ambient_temp_c,
            bulk_temp_c=small_config.ambient_temp_c,
            ambient_temp_c=small_config.ambient_temp_c,
            lamp_output_lux=0.0,
            fan_airflow=0.0,
            lamp_pwm=0,
            fan_pwm=0,
            time_s=0.0,
        )
        plant_off = ThermalPlant(small_config, init)
        plant_on = ThermalPlant(small_config, init)

        plant_off.step(0, 0, 2.0)
        plant_on.step(255, 0, 2.0)

        dT_off = plant_off.state.surface_temp_c - init.surface_temp_c
        dT_on = plant_on.state.surface_temp_c - init.surface_temp_c
        assert dT_on > dT_off
        assert dT_on > 0.0


class TestHigherFanIncreasesCooling:
    """With ambient floor, higher fan speeds cool a hot sample faster."""

    def test_hot_sample_cools_faster_with_full_fan(self, medium_config: PlantConfig, hot_initial_state: PlantState) -> None:
        t_amb = medium_config.ambient_temp_c
        init_low = PlantState(
            surface_temp_c=t_amb + 20.0,
            bulk_temp_c=t_amb + 40.0,
            ambient_temp_c=t_amb,
            lamp_output_lux=0.0,
            fan_airflow=0.0,
            lamp_pwm=0,
            fan_pwm=0,
            time_s=0.0,
        )
        init_high = PlantState(
            surface_temp_c=t_amb + 20.0,
            bulk_temp_c=t_amb + 40.0,
            ambient_temp_c=t_amb,
            lamp_output_lux=0.0,
            fan_airflow=0.0,
            lamp_pwm=0,
            fan_pwm=0,
            time_s=0.0,
        )

        plant_low = ThermalPlant(medium_config, init_low)
        plant_high = ThermalPlant(medium_config, init_high)

        for _ in range(25):
            plant_low.step(0, 0, 0.4)
            plant_high.step(0, 255, 0.4)

        assert plant_low.state.surface_temp_c > plant_high.state.surface_temp_c
        assert plant_low.state.bulk_temp_c > plant_high.state.bulk_temp_c

    def test_same_run_fan_down_then_up(self, small_config: PlantConfig) -> None:
        init = PlantState(
            surface_temp_c=small_config.ambient_temp_c + 10.0,
            bulk_temp_c=small_config.ambient_temp_c + 30.0,
            ambient_temp_c=small_config.ambient_temp_c,
            lamp_output_lux=0.0,
            fan_airflow=0.0,
            lamp_pwm=0,
            fan_pwm=0,
            time_s=0.0,
        )
        plant = ThermalPlant(small_config, init)
        plant.step(0, 0, 1.0)
        t1 = plant.state.bulk_temp_c
        plant.step(0, 255, 1.0)
        t2 = plant.state.bulk_temp_c
        assert t2 < t1


class TestFiniteEnergyTemperatures:
    """Bounded inputs produce finite energies and temperatures."""

    def test_temps_remain_finite_under_extreme_inputs(self, small_config: PlantConfig) -> None:
        init = PlantState(
            surface_temp_c=small_config.ambient_temp_c,
            bulk_temp_c=small_config.ambient_temp_c,
            ambient_temp_c=small_config.ambient_temp_c,
            lamp_output_lux=0.0,
            fan_airflow=0.0,
            lamp_pwm=0,
            fan_pwm=0,
            time_s=0.0,
        )
        plant = ThermalPlant(small_config, init)

        # Run very long under sustained maximum power.
        for _ in range(1000):
            st = plant.step(255, 255, 0.1)
            assert math.isfinite(st.surface_temp_c)
            assert math.isfinite(st.bulk_temp_c)
            assert math.isfinite(st.lamp_output_lux)
            assert math.isfinite(st.fan_airflow)

    def test_temps_do_not_diverge_with_just_lamps(self, medium_config: PlantConfig) -> None:
        init = PlantState(
            surface_temp_c=medium_config.ambient_temp_c,
            bulk_temp_c=medium_config.ambient_temp_c,
            ambient_temp_c=medium_config.ambient_temp_c,
            lamp_output_lux=0.0,
            fan_airflow=0.0,
            lamp_pwm=0,
            fan_pwm=0,
            time_s=0.0,
        )
        plant = ThermalPlant(medium_config, init)
        for _ in range(1000):
            st = plant.step(255, 0, 0.1)
            assert st.surface_temp_c < 200.0
            assert st.bulk_temp_c < 200.0

    def test_temps_do_not_diverge_with_lamps_and_fan(self, small_config: PlantConfig) -> None:
        init = PlantState(
            surface_temp_c=small_config.ambient_temp_c,
            bulk_temp_c=small_config.ambient_temp_c,
            ambient_temp_c=small_config.ambient_temp_c,
            lamp_output_lux=0.0,
            fan_airflow=0.0,
            lamp_pwm=0,
            fan_pwm=0,
            time_s=0.0,
        )
        plant = ThermalPlant(small_config, init)
        for _ in range(500):
            st = plant.step(255, 255, 0.2)
            assert st.surface_temp_c < 100.0
            assert st.bulk_temp_c < 100.0


class TestIrregularIntervalsMatchFineStepReference:
    """Irregular steps should reproduce a fine-step reference due to analytic update."""

    def test_irregular_coarse_steps_match_fine_reference(self) -> None:
        # Use a config where max_substep_s << actuator time constants so the
        # actuator-thermal coupling error per substep is negligible.
        cfg = PlantConfig(
            surface_capacity_j_per_k=10.0,
            bulk_capacity_j_per_k=100.0,
            surface_bulk_conductance_w_per_k=2.0,
            surface_ambient_conductance_w_per_k=1.0,
            bulk_ambient_conductance_w_per_k=0.5,
            lamp_max_power_w=50.0,
            lamp_response_time_s=0.1,
            lamp_max_lux=50000.0,
            fan_max_conductance_w_per_k=3.0,
            fan_response_time_s=0.1,
            ambient_temp_c=25.0,
            max_substep_s=0.001,  # much smaller than tau_lamp/tau_fan
        )
        init = PlantState(
            surface_temp_c=cfg.ambient_temp_c,
            bulk_temp_c=cfg.ambient_temp_c,
            ambient_temp_c=cfg.ambient_temp_c,
            lamp_output_lux=0.0,
            fan_airflow=0.0,
            lamp_pwm=0,
            fan_pwm=0,
            time_s=0.0,
        )

        # Irregular schedule whose steps sum exactly to the total duration.
        irregular_dts = [0.37, 0.11, 0.53, 0.09, 0.40, 0.25, 0.18, 0.07, 0.31, 0.19]
        total_dt = sum(irregular_dts)  # 2.5 s

        # Fine-step reference: many equal substeps covering the same total.
        h_ref = 0.001  # seconds, equals max_substep_s
        n_ref = int(round(total_dt / h_ref))

        plant_fine = ThermalPlant(cfg, init)
        for _ in range(n_ref):
            plant_fine.step(255, 128, h_ref)
        ref_state = plant_fine.state

        # Coarse irregular steps over the same total duration.
        plant_coarse = ThermalPlant(cfg, init)
        for dt in irregular_dts:
            plant_coarse.step(255, 128, dt)
        final_state = plant_coarse.state

        # The analytic update is exact for constant inputs, so both paths
        # solve the same ODE and agree to floating-point precision.
        tol = 1e-9
        assert abs(final_state.surface_temp_c - ref_state.surface_temp_c) < tol
        assert abs(final_state.bulk_temp_c - ref_state.bulk_temp_c) < tol
        assert abs(final_state.time_s - ref_state.time_s) < 1e-9

    def test_single_step_vs_multiple_equal_steps(self, small_config: PlantConfig) -> None:
        total_dt = 0.5
        init = PlantState(
            surface_temp_c=small_config.ambient_temp_c,
            bulk_temp_c=small_config.ambient_temp_c,
            ambient_temp_c=small_config.ambient_temp_c,
            lamp_output_lux=0.0,
            fan_airflow=0.0,
            lamp_pwm=0,
            fan_pwm=0,
            time_s=0.0,
        )
        plant_one = ThermalPlant(small_config, init)
        plant_one.step(255, 255, total_dt)
        one_result = plant_one.state

        init2 = PlantState(
            surface_temp_c=small_config.ambient_temp_c,
            bulk_temp_c=small_config.ambient_temp_c,
            ambient_temp_c=small_config.ambient_temp_c,
            lamp_output_lux=0.0,
            fan_airflow=0.0,
            lamp_pwm=0,
            fan_pwm=0,
            time_s=0.0,
        )
        plant_many = ThermalPlant(small_config, init2)
        n = 5
        dt_each = total_dt / n
        for _ in range(n):
            plant_many.step(255, 255, dt_each)
        many_result = plant_many.state

        # Due to analytic update, single step equals multiple equal steps.
        tol = 1e-9
        assert abs(one_result.surface_temp_c - many_result.surface_temp_c) < tol
        assert abs(one_result.bulk_temp_c - many_result.bulk_temp_c) < tol
        assert abs(one_result.time_s - many_result.time_s) < 1e-9


class TestAmbientFloorBehavior:
    """Temperatures should never dip below ambient when lamp=fan=0."""

    def test_temps_stay_above_ambient_when_idle(self, small_config: PlantConfig) -> None:
        init = PlantState(
            surface_temp_c=small_config.ambient_temp_c + 5.0,
            bulk_temp_c=small_config.ambient_temp_c + 20.0,
            ambient_temp_c=small_config.ambient_temp_c,
            lamp_output_lux=0.0,
            fan_airflow=0.0,
            lamp_pwm=0,
            fan_pwm=0,
            time_s=0.0,
        )
        plant = ThermalPlant(small_config, init)
        for _ in range(100):
            st = plant.step(0, 0, 0.1)
            assert st.surface_temp_c >= small_config.ambient_temp_c
            assert st.bulk_temp_c >= small_config.ambient_temp_c

    def test_with_power_temps_can_exceed_ambient_floor(self, medium_config: PlantConfig) -> None:
        init = PlantState(
            surface_temp_c=medium_config.ambient_temp_c,
            bulk_temp_c=medium_config.ambient_temp_c,
            ambient_temp_c=medium_config.ambient_temp_c,
            lamp_output_lux=0.0,
            fan_airflow=0.0,
            lamp_pwm=0,
            fan_pwm=0,
            time_s=0.0,
        )
        plant = ThermalPlant(medium_config, init)
        st = plant.step(255, 0, 10.0)
        assert st.surface_temp_c > medium_config.ambient_temp_c
        assert st.bulk_temp_c > medium_config.ambient_temp_c


class TestPWMValidation:
    """PWM inputs must be integers in [0, 255]."""

    @pytest.mark.parametrize("pwm", [-1, 256, True])
    def test_invalid_pwm_rejected(self, small_config: PlantConfig, pwm: object) -> None:
        plant = ThermalPlant(small_config)
        with pytest.raises((TypeError, ValueError)):
            plant.step(pwm, 0, 0.1)  # type: ignore[arg-type]

    @pytest.mark.parametrize("dt", [-1.0, float("inf"), float("nan")])
    def test_invalid_dt_rejected(self, small_config: PlantConfig, dt: float) -> None:
        plant = ThermalPlant(small_config)
        with pytest.raises((ValueError, TypeError)):
            plant.step(0, 0, dt)


class TestActuatorStatesRecoverFromInitialState:
    """Actuator states recovered from an initial state match expected values."""

    def test_actuators_recover_correctly(self, small_config: PlantConfig) -> None:
        # Given an initial state with non-zero actuator outputs, the plant should
        # maintain equivalent internal states after creation.
        init = PlantState(
            surface_temp_c=30.0,
            bulk_temp_c=35.0,
            ambient_temp_c=small_config.ambient_temp_c,
            lamp_output_lux=25000.0,
            fan_airflow=0.5,
            lamp_pwm=128,
            fan_pwm=128,
            time_s=42.0,
        )
        plant = ThermalPlant(small_config, init)
        st = plant.state
        # Lamp output should recover from the ratio.
        expected_lamp_lux = (init.lamp_output_lux / small_config.lamp_max_lux) * small_config.lamp_max_lux
        assert abs(st.lamp_output_lux - expected_lamp_lux) < 1e-6
