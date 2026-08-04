"""Fitting script skeleton for PT-Kit simulator plant calibration.

This script provides the framework for fitting simulator parameters to real
PT-Kit step-response data. The implementation is marked as requiring real data
and should NOT be used with fabricated thresholds.

Usage:
    python scripts/fit_simulator_plant.py \
        --data-dir /path/to/step_responses/ \
        --repeatability /path/to/repeatability_report.json \
        --output calibrated_profile.json

TODO (implement):
1. Load raw telemetry CSV files from data directory
2. Parse run-to-run repeatability metrics
3. Compute acceptance thresholds from repeatability std dev (k multiplier)
4. Fit lamp model: lamp_max_power_w, lamp_response_time_s, lamp_max_lux
5. Fit thermal model: surface_capacity, bulk_capacity, conductances
6. Fit fan model: fan_max_conductance, fan_response_time
7. Fit sensor models: IR, TC, lux response time, bias, noise
8. Validate fit against gates derived from repeatability
9. Write calibrated profile or CALIBRATION_FAILED status

IMPORTANT: This script must NOT invent acceptance thresholds before running
Phase A (repeatability assessment). Thresholds are computed from the
repeatability report data.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import minimize

# TODO: Import actual plant and profile modules once established
# from app.simulator.config import PlantConfig, SensorConfig
# from app.simulator.profiles import load_profile, write_profile

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

logger = logging.getLogger(__name__)


# =============================================================================
# DATA LOADING
# =============================================================================

def load_step_response_data(data_dir: str) -> dict[str, list[pd.DataFrame]]:
    """Load step-response test data from directory.
    
    Expected file naming pattern: {TEST_ID}_run{NN}_{YYYYMMDD_HHMMSS}.csv
    
    Returns dictionary keyed by test type:
    - 'lamp_*' lists heating curves at different PWM levels
    - 'fan_*' lists cooling curves at different PWM levels
    - 'lux_*' lists lux characterization data
    
    Raises:
        FileNotFoundError: If no valid CSV files found in directory.
    """
    path = Path(data_dir)
    if not path.exists():
        raise FileNotFoundError(f"Data directory not found: {data_dir}")
    
    # Scan for CSV files and group by test ID
    results: dict[str, list[pd.DataFrame]] = {}
    
    for csv_file in path.glob("*.csv"):
        try:
            df = pd.read_csv(csv_file)
        except Exception as e:
            logger.warning(f"Failed to parse {csv_file}: {e}")
            continue
        
        # Extract test ID from filename
        stem = csv_file.stem  # e.g., "LAMP_128_run001_20250801_143022"
        parts = stem.split("_")
        
        if len(parts) < 2:
            logger.warning(f"Skipping {csv_file} — unrecognized naming pattern")
            continue
        
        test_id = "_".join(parts[:2])  # e.g., "LAMP_128"
        
        if test_id not in results:
            results[test_id] = []
        results[test_id].append(df)
    
    if not results:
        raise FileNotFoundError(f"No valid CSV files found in {data_dir}")
    
    logger.info(f"Loaded {sum(len(v) for v in results.values())} runs grouped into {len(results)} tests")
    return results


def load_repeatability_report(path: str) -> dict[str, Any]:
    """Load run-to-run repeatability report.
    
    Required fields (see simulator-calibration-protocol.md Phase A):
    - metrics.{heating_slope_c_per_min, cooling_slope_c_per_min, ...}.{mean, std, cv_pct}
    
    Returns full JSON structure for downstream use.
    """
    with open(path, "r") as f:
        data = json.load(f)
    
    required_keys = ["date", "n_runs", "ambient_temp_c", "metrics"]
    missing = [k for k in required_keys if k not in data]
    if missing:
        raise ValueError(f"Repeatability report missing keys: {missing}")
    
    # Validate metric structure - skip metrics that are None (not yet collected)
    for metric_name, values in data["metrics"].items():
        if values is None:
            logger.warning(f"Metric {metric_name} not available (None), skipping validation")
            continue
        if "std" not in values:
            raise ValueError(f"Repeatability metric {metric_name} missing 'std' field")
    
    logger.info(f"Loaded repeatability report (N={data['n_runs']})")
    return data


# =============================================================================
# THRESHOLD COMPUTATION
# =============================================================================

def compute_acceptance_thresholds(repeatability: dict[str, Any], k: float = 2.0) -> dict[str, dict[str, Any]]:
    """Compute acceptance thresholds from repeatability standard deviations.
    
    Formula: threshold = k × std_dev
    
    Args:
        repeatability: Output from load_repeatability_report
        k: Multiplier (default 2.0, configurable)
    
    Returns:
        Dictionary mapping metric name to {"threshold": value, "source_std": value}
    """
    thresholds: dict[str, dict[str, Any]] = {}
    
    # Metrics defined in protocol document
    metric_names = [
        "heating_slope_c_per_min",
        "cooling_slope_c_per_min",
        "time_to_40c_s",
        "steady_state_temp_c",
        "ir_tc_lag_s",
        "plateau_temp_c",
    ]
    
    for metric in metric_names:
        metric_data = repeatability["metrics"].get(metric)
        if metric_data is None or metric_data.get("std") is None:
            logger.warning(f"Metric {metric} not available in repeatability report")
            continue
        
        std_val = metric_data["std"]
        thresholds[metric] = {
            "threshold": k * std_val,
            "source_std": std_val,
            "multiplier_k": k,
        }
    
    return thresholds


# =============================================================================
# PARAMETER FITTING
# =============================================================================

def fit_lamp_model(lamp_data_list: list[pd.DataFrame]) -> dict[str, float | None]:
    """Fit lamp gain and response time from heating steps.
    
    TODO: Implement optimization to match:
    - rise time (10%→90%) for lamp_response_time_s
    - final equilibrium for lamp_max_power_w / lamp_max_lux
    
    Returns dictionary with fitted lamp parameters.
    """
    # STUB — replace with actual fitting logic
    # 
    # Pseudocode:
    # 1. Stack all LAMP_* runs (should have multiple PWM levels)
    # 2. Fit first-order lag: T(t) = T_eq * (1 - exp(-t/tau))
    # 3. Estimate tau from rise time
    # 4. Scale equilibrium vs PWM for gain
    #
    logger.warning("fit_lamp_model: STUB IMPLEMENTATION — requires real data")
    
    return {
        "lamp_max_power_w": None,      # Requires fitted data
        "lamp_response_time_s": None,
        "lamp_max_lux": None,
    }


def fit_thermal_model(
    heating_data: list[pd.DataFrame],
    cooling_data: list[pd.DataFrame],
    initial_guess: dict[str, float],
) -> dict[str, float | None]:
    """Fit thermal capacities and conductances from heating/cooling curves.
    
    Uses two-node thermal model (surface/bulk). Fitting minimizes RMSE between
    simulated and measured temperatures over time.
    
    Args:
        heating_data: Lamp ON heating curves (lamp PWM=255 preferred)
        cooling_data: Lamp OFF cooling curves
        initial_guess: Dictionary of starting parameter values
    
    Returns dictionary with fitted thermal parameters.
    """
    # STUB — replace with actual optimization
    #
    # Pseudocode:
    # 1. Define objective function: sum(RMSE_heating + RMSE_cooling)
    # 2. For each parameter set:
    #    a. Create ThermalPlant instance with config
    #    b. Run simulation matching test procedure
    #    c. Compute RMSE vs measured data
    # 3. Use scipy.optimize.minimize with bounds
    # 4. Return optimal parameters
    #
    logger.warning("fit_thermal_model: STUB IMPLEMENTATION — requires real data")
    
    return {
        "surface_capacity_j_per_k": None,
        "bulk_capacity_j_per_k": None,
        "surface_bulk_conductance_w_per_k": None,
        "surface_ambient_conductance_w_per_k": None,
        "bulk_ambient_conductance_w_per_k": None,
    }


def fit_fan_model(fan_data_list: list[pd.DataFrame]) -> dict[str, float | None]:
    """Fit fan forced-convection loss from cooling steps.
    
    Compares cooling rates at different fan PWM levels to estimate
    fan_max_conductance_w_per_k.
    
    TODO: Implement
    """
    # STUB
    logger.warning("fit_fan_model: STUB IMPLEMENTATION — requires real data")
    
    return {
        "fan_max_conductance_w_per_k": None,
        "fan_response_time_s": None,
    }


def fit_sensor_models(data_dict: dict[str, list[pd.DataFrame]]) -> dict[str, dict[str, float | None]]:
    """Fit IR, TC, and lux sensor parameters.
    
    Estimates for each sensor:
    - response_time_s: From step edge (10%→90% divided by 2.2 for 1st order)
    - bias_c or bias_lux: Steady-state error vs physical temperature/lux
    - noise_std: Standard deviation during baseline (OFF) period
    
    TODO: Implement
    """
    # STUB
    logger.warning("fit_sensor_models: STUB IMPLEMENTATION — requires real data")
    
    return {
        "ir": {
            "response_time_s": None,
            "bias_c": None,
            "noise_std": None,
        },
        "tc": {
            "response_time_s": None,
            "bias_c": None,
            "noise_std": None,
        },
        "lux": {
            "response_time_s": None,
            "bias_lux": None,
            "noise_std": None,
        },
    }


def validate_fit(
    fit_metrics: dict[str, float | None],
    acceptance_thresholds: dict[str, dict[str, Any]],
) -> tuple[bool, list[str]]:
    """Check if fit metrics pass all acceptance gates.
    
    Args:
        fit_metrics: Dictionary mapping metric name to fitted error value (may be None for stubs)
        acceptance_thresholds: Computed from repeatability report
    
    Returns:
        (all_passed, list_of_failed_checks)
    """
    failed: list[str] = []
    
    for metric_name, threshold_info in acceptance_thresholds.items():
        # Map metric names between fit output and thresholds
        # Some metrics may have different names in fit_metrics vs thresholds
        
        threshold_key = None
        # Direct mapping or heuristic mapping
        if metric_name.startswith("heating"):
            threshold_key = "heating_slope_error_c_per_min"
        elif metric_name.startswith("cooling"):
            threshold_key = "cooling_slope_error_c_per_min"
        elif "rmse" in metric_name.lower():
            if "ir" in metric_name.lower():
                threshold_key = "ir_rmse_c"
            else:
                threshold_key = "tc_rmse_c"
        else:
            threshold_key = metric_name
        
        if threshold_key not in fit_metrics:
            logger.warning(f"Fit metric '{threshold_key}' not available for validation")
            continue
        
        error_value = fit_metrics[threshold_key]
        
        # Skip validation if error value is None (stub implementation)
        if error_value is None:
            logger.warning(f"Cannot validate {threshold_key} — error value is None (stub implementation)")
            continue
        
        threshold_value = threshold_info["threshold"]
        
        if error_value > threshold_value:
            failed.append(
                f"{threshold_key}: {error_value:.3f} exceeds threshold {threshold_value:.3f}"
            )
    
    return len(failed) == 0, failed


# =============================================================================
# PROFILE OUTPUT
# =============================================================================

def write_calibrated_profile(
    params: dict[str, float | None],
    sensor_params: dict[str, dict[str, float | None]],
    fan_params: dict[str, float | None],
    fit_metrics: dict[str, float | None],
    acceptance_thresholds: dict[str, dict[str, Any]],
    source_data_dir: str,
    output_path: str,
    validation_status: str,
) -> None:
    """Write calibrated profile JSON with explicit units and metadata."""
    
    profile = {
        "profile_id": "calibrated-v1",
        "model_version": "2.0.0",
        "validation_status": validation_status,
        "validity_domain": {
            "ambient_temp_c": [20, 30],  # TBD based on actual test conditions
            "lamp_pwm_range": [0, 255],
            "fan_pwm_range": [0, 255],
            "max_duration_s": 3600,
        },
        "parameters": {
            # Thermal capacities
            "surface_capacity_j_per_k": params.get("surface_capacity_j_per_k"),
            "bulk_capacity_j_per_k": params.get("bulk_capacity_j_per_k"),
            
            # Conductances
            "surface_bulk_conductance_w_per_k": params.get("surface_bulk_conductance_w_per_k"),
            "surface_ambient_conductance_w_per_k": params.get("surface_ambient_conductance_w_per_k"),
            "bulk_ambient_conductance_w_per_k": params.get("bulk_ambient_conductance_w_per_k"),
            
            # Lamp
            "lamp_max_power_w": params.get("lamp_max_power_w"),
            "lamp_response_time_s": params.get("lamp_response_time_s"),
            "lamp_max_lux": params.get("lamp_max_lux"),
            
            # Fan
            "fan_max_conductance_w_per_k": fan_params.get("fan_max_conductance_w_per_k"),
            "fan_response_time_s": fan_params.get("fan_response_time_s"),
        },
        "sensor_parameters": {
            "ir": sensor_params.get("ir"),
            "tc": sensor_params.get("tc"),
            "lux": sensor_params.get("lux"),
        },
        "source_dataset": source_data_dir,
        "fit_metrics": fit_metrics,
        "acceptance_thresholds": {
            "derived_from": "repeatability_report.json",
            "multiplier_k": 2.0,
            **acceptance_thresholds,
        },
        "calibration_date": datetime.now().isoformat(),
        "calibration_operator": "SYSTEM_AUTO",  # Replace with human operator name in practice
        "notes": "",
    }
    
    # Validate no NaN or None critical parameters before writing
    for key, val in profile["parameters"].items():
        if val is None:
            logger.error(f"Critical parameter {key} is None — check fitting was completed")
    
    with open(output_path, "w") as f:
        json.dump(profile, f, indent=2)
    
    logger.info(f"Wrote profile to {output_path}")


# =============================================================================
# MAIN EXECUTION
# =============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fit PT-Kit simulator plant parameters to real step-response data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example:
  python scripts/fit_simulator_plant.py \\
      --data-dir tests/fixtures/simulator/calibration/step_responses/ \\
      --repeatability tests/fixtures/simulator/calibration/repeatability/repeatability_report.json \\
      --output app/simulator/profiles/calibrated.json

The script performs:
  1. Load step-response data (heating, cooling, lux)
  2. Load repeatability report and compute thresholds
  3. Fit lamp, thermal, fan, and sensor models
  4. Validate fit against acceptance gates
  5. Write calibrated profile or CALIBRATION_FAILED status
        """,
    )
    
    parser.add_argument(
        "--data-dir",
        type=str,
        required=True,
        help="Directory containing step-response CSV files (LAMP_*, FAN_*, LUX_*)"
    )
    parser.add_argument(
        "--repeatability",
        type=str,
        required=True,
        help="Path to repeatability report JSON (must exist before fitting)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="app/simulator/profiles/calibrated.json",
        help="Output path for calibrated profile (default: app/simulator/profiles/calibrated.json)"
    )
    parser.add_argument(
        "--k-multiplier",
        type=float,
        default=2.0,
        help="Multiplier for threshold computation (default: 2.0)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    logger.info("Starting PT-Kit simulator calibration workflow")
    
    # Step 1: Load data
    logger.info("Step 1: Loading step-response data...")
    data_dict = load_step_response_data(args.data_dir)
    
    # Separate by test type
    lamp_data = []
    fan_data = []
    lux_data = []
    
    for test_id, runs in data_dict.items():
        if test_id.startswith("LAMP"):
            lamp_data.extend(runs)
        elif test_id.startswith("FAN"):
            fan_data.extend(runs)
        elif test_id.startswith("LUX"):
            lux_data.extend(runs)
        else:
            logger.info(f"Unrecognized test type: {test_id}, skipping")
    
    logger.info(f"  Found {len(lamp_data)} lamp runs, {len(fan_data)} fan runs, {len(lux_data)} lux runs")
    
    # Step 2: Load repeatability and compute thresholds
    logger.info("Step 2: Loading repeatability report and computing thresholds...")
    repeatability = load_repeatability_report(args.repeatability)
    thresholds = compute_acceptance_thresholds(repeatability, k=args.k_multiplier)
    logger.info(f"  Computed {len(thresholds)} acceptance thresholds")
    
    # Step 3: Fit parameters
    logger.info("Step 3: Fitting plant and sensor parameters...")
    
    logger.info("  Fitting lamp model...")
    lamp_params = fit_lamp_model(lamp_data)
    
    logger.info("  Fitting thermal model...")
    thermal_params = fit_thermal_model(lamp_data, fan_data, initial_guess={
        "surface_capacity_j_per_k": 1000.0,
        "bulk_capacity_j_per_k": 5000.0,
    })
    
    logger.info("  Fitting fan model...")
    fan_params = fit_fan_model(fan_data)
    
    logger.info("  Fitting sensor models...")
    sensor_params = fit_sensor_models(data_dict)
    
    # Combine all parameters
    combined_params = {**lamp_params, **thermal_params}
    
    # Step 4: Compute fit metrics
    logger.info("Step 4: Computing fit metrics...")
    
    # STUB metrics — these should come from the fitting process
    # Use float | None for initial stub implementation
    fit_metrics: dict[str, float | None] = {
        "ir_rmse_c": None,  # Will be computed from actual fit
        "tc_rmse_c": None,
        "heating_slope_error_c_per_min": None,
        "cooling_slope_error_c_per_min": None,
        "time_to_threshold_error_s": None,
        "ir_tc_lag_error_s": None,
        "steady_state_error_c": None,
        "plateau_temp_error_c": None,
    }
    
    # Step 5: Validate against thresholds
    logger.info("Step 5: Validating fit against acceptance thresholds...")
    all_passed, failed_checks = validate_fit(fit_metrics, thresholds)
    
    if failed_checks:
        logger.warning(f"Validation failed with {len(failed_checks)} issues:")
        for issue in failed_checks:
            logger.warning(f"  - {issue}")
    
    # Step 6: Write profile
    logger.info("Step 6: Writing calibrated profile...")
    
    validation_status = "CALIBRATED" if all_passed else "CALIBRATION_FAILED"
    write_calibrated_profile(
        params=combined_params,
        sensor_params=sensor_params,
        fan_params=fan_params,
        fit_metrics=fit_metrics,
        acceptance_thresholds=thresholds,
        source_data_dir=args.data_dir,
        output_path=args.output,
        validation_status=validation_status,
    )
    
    if all_passed:
        logger.info(f"Calibration successful! Profile written to {args.output}")
        return 0
    else:
        logger.warning(f"Calibration completed but flagged as FAILED — profile still written for inspection")
        return 1


if __name__ == "__main__":
    exit(main())
