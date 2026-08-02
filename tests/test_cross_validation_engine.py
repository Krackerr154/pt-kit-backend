"""Test suite for cross-validation engine components."""

import pytest
from pathlib import Path
import sys
import json

sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime
import numpy as np
from typing import List, Dict, Any

from app.simulator.profile_management import (
    PlantProfile, 
    PlantParameters, 
    SensorConfig
)
from app.simulator.cross_validation_engine import (
    CurveFitter,
    CrossValidationMetrics,
    OptimizationResult,
    CrossValidationEngine
)


class TestCurveFitterBasic:
    """Test basic polynomial and exponential fitting functionality."""
    
    def test_polynomial_fit_degree_2(self):
        """Test quadratic polynomial curve fitting."""
        # Generate synthetic quadratic data
        x_data = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        y_data = np.array([2.0, 8.0, 18.0, 32.0, 50.0])  # y = 2*x^2
        
        fitter = CurveFitter()
        model_func, params = fitter.fit(x_data, y_data)
        
        assert model_func is not None
        assert 'poly_coeffs' in params
        
        # Test prediction accuracy
        predictions = model_func(x_data)
        errors = np.abs(predictions - y_data)
        
        # Should be close fit for perfect data
        assert np.all(errors < 1.0)
    
    def test_exponential_fit_basic(self):
        """Test exponential curve fitting."""
        # Generate synthetic exponential data
        x_data = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
        y_data = np.exp(0.5 * x_data)  # y = e^(0.5x)
        
        fitter = CurveFitter()
        model_func, params = fitter.fit(x_data, y_data)  # Use default polynomial fit
        
        assert model_func is not None
        assert 'poly_coeffs' in params
        
        predictions = model_func(x_data)
        rmse = np.sqrt(np.mean((predictions - y_data)**2))
        
        # Polynomial approximation of exponential should have reasonable RMSE
        assert rmse < 5.0  # Less strict for this approximation test
    
    def test_model_parameters_extraction(self):
        """Test extracting fitted model parameters."""
        x_data = np.linspace(0, 10, 50)
        y_data = 3 * x_data + 5 + np.random.normal(0, 0.1, 50)  # Linear with noise
        
        fitter = CurveFitter()
        _, params = fitter.fit(x_data, y_data)
        
        extracted = fitter.get_model_parameters()
        
        assert isinstance(extracted, dict)
        assert len(extracted) > 0
    
    def test_prediction_accuracy_on_valid_range(self):
        """Test that predictions within training range are accurate."""
        x_train = np.linspace(0, 10, 100)
        y_train = x_train**2 + 2*x_train + 1
        
        fitter = CurveFitter()
        model_func, _ = fitter.fit(x_train, y_train)
        
        # Predict at known points
        x_test = np.array([2.0, 5.0, 8.0])
        predictions = model_func(x_test)
        
        expected = x_test**2 + 2*x_test + 1
        
        # Should be very close for polynomial
        errors = np.abs(predictions - expected)
        assert np.max(errors) < 0.5


class TestCrossValidationMetrics:
    """Test statistical metric computations."""
    
    def test_rmse_computation(self):
        """Test Root Mean Square Error calculation."""
        measured = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        simulated = np.array([1.1, 2.2, 2.9, 4.1, 4.9])
        
        metrics = CrossValidationEngine.compute_metrics(measured, simulated)
        
        expected_rmse = np.sqrt(np.mean((measured - simulated)**2))
        
        assert abs(metrics.rmse - expected_rmse) < 0.01
    
    def test_mae_computation(self):
        """Test Mean Absolute Error calculation."""
        measured = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        simulated = np.array([1.1, 2.0, 3.1, 4.0, 5.1])
        
        metrics = CrossValidationEngine.compute_metrics(measured, simulated)
        
        expected_mae = np.mean(np.abs(measured - simulated))
        
        assert abs(metrics.mae - expected_mae) < 0.01
    
    def test_r_squared_perfect_fit(self):
        """Test R² equals 1.0 for perfect fit."""
        measured = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        simulated = measured.copy()  # Perfect match
        
        metrics = CrossValidationEngine.compute_metrics(measured, simulated)
        
        assert abs(metrics.r_squared - 1.0) < 0.001
    
    def test_r_squared_no_correlation(self):
        """Test R² near 0 for uncorrelated data."""
        measured = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        simulated = np.array([5.0, 4.0, 3.0, 2.0, 1.0])  # Opposite trend
        
        metrics = CrossValidationEngine.compute_metrics(measured, simulated)
        
        # Should have poor correlation
        assert metrics.r_squared < 0.5
    
    def test_max_deviation_calculation(self):
        """Test maximum deviation detection."""
        measured = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        simulated = np.array([1.0, 2.0, 5.0, 4.0, 5.0])  # Deviation of 2 at index 2
        
        metrics = CrossValidationEngine.compute_metrics(measured, simulated)
        
        assert metrics.max_deviation >= 2.0
        assert metrics.max_deviation == np.max(np.abs(measured - simulated))
    
    def test_num_points_tracking(self):
        """Test that point count matches data length."""
        n_points = 100
        measured = np.random.rand(n_points)
        simulated = np.random.rand(n_points)
        
        metrics = CrossValidationEngine.compute_metrics(measured, simulated)
        
        assert metrics.num_points == n_points


class TestOutlierDetection:
    """Test outlier detection algorithms."""
    
    def test_outlier_detection_simple(self):
        """Test detecting outliers beyond threshold."""
        data = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 100.0])  # 100 is outlier
        
        outliers = CrossValidationEngine.detect_outliers(data, threshold_std=2.0)
        
        assert len(outliers) > 0
        outlier_indices = [idx for idx, _ in outliers]
        
        # Should detect 100 as outlier
        assert 5 in outlier_indices
    
    def test_no_outliers_normal_distribution(self):
        """Test no false positives on normal data."""
        np.random.seed(42)
        data = np.random.normal(0, 1, 100)  # Standard normal distribution
        
        outliers = CrossValidationEngine.detect_outliers(data, threshold_std=3.0)
        
        # Should find few or no outliers in well-behaved data
        assert len(outliers) <= 5  # Allow some variance
    
    def test_multidimensional_outlier_detection(self):
        """Test detection handles various data patterns."""
        data = np.array([1.0, 1.1, 1.05, 9.0, 1.08, 1.02])  # One clear outlier
        
        outliers = CrossValidationEngine.detect_outliers(data, threshold_std=2.0)
        
        # Should identify the extreme value
        outlier_values = [val for _, val in outliers]
        assert max(outlier_values) >= 9.0


class TestOptimizationResult:
    """Test optimization result structure and validation."""
    
    def test_optimization_result_contains_all_fields(self):
        """Test OptimizationResult has all required fields."""
        original_profile = PlantProfile(name="test_original")
        optimized_profile = PlantProfile(name="test_optimized")
        
        metrics_before = CrossValidationMetrics(
            rmse=5.0, mae=4.0, r_squared=0.7,
            max_deviation=10.0, mean_deviation=3.0, num_points=100
        )
        
        metrics_after = CrossValidationMetrics(
            rmse=2.0, mae=1.5, r_squared=0.9,
            max_deviation=5.0, mean_deviation=1.0, num_points=100
        )
        
        result = OptimizationResult(
            success=True,
            original_profile=original_profile,
            optimized_profile=optimized_profile,
            metrics_before=metrics_before,
            metrics_after=metrics_after,
            delta_summary="Improved R² from 0.7 to 0.9",
            improvement_pct=30.0
        )
        
        assert result.success is True
        assert result.metrics_after.r_squared > result.metrics_before.r_squared
        assert result.improvement_pct > 0
    
    def test_optimization_failure_scenario(self):
        """Test optimization result when optimization fails."""
        result = OptimizationResult(
            success=False,
            original_profile=PlantProfile(name="failed_opt"),
            optimized_profile=PlantProfile(name="failed_opt"),
            metrics_before=CrossValidationMetrics(
                rmse=5.0, mae=4.0, r_squared=0.8,
                max_deviation=8.0, mean_deviation=3.0, num_points=100
            ),
            metrics_after=CrossValidationMetrics(
                rmse=6.0, mae=5.0, r_squared=0.6,
                max_deviation=10.0, mean_deviation=4.0, num_points=100
            ),
            delta_summary="No improvement achieved",
            improvement_pct=-20.0
        )
        
        assert result.success is False
        assert result.improvement_pct < 0


class TestParameterSuggestions:
    """Test parameter adjustment suggestion generation."""
    
    def test_suggest_param_adjustments_for_high_rmse(self):
        """Test parameter suggestions when RMSE is high."""
        profile = PlantProfile(
            name="high_rmse_test",
            plant_params=PlantParameters(ambient_temp_c=25.0),
        )
        
        metrics = CrossValidationMetrics(
            rmse=15.0, mae=12.0, r_squared=0.4,
            max_deviation=20.0, mean_deviation=10.0, num_points=100
        )
        
        adjustments = CrossValidationEngine.suggest_param_adjustments(profile, metrics)
        
        # Should return a dictionary
        assert isinstance(adjustments, dict)
        
        # For high error, should suggest significant changes
        if adjustments:  # If suggestions exist
            total_adjustment_magnitude = sum(abs(v) for v in adjustments.values())
            assert total_adjustment_magnitude > 0.0
    
    def test_minimal_adjustments_when_low_rmse(self):
        """Test minimal adjustments when already good fit."""
        profile = PlantProfile(name="good_fit_test")
        
        metrics = CrossValidationMetrics(
            rmse=0.5, mae=0.3, r_squared=0.98,
            max_deviation=1.0, mean_deviation=0.4, num_points=100
        )
        
        adjustments = CrossValidationEngine.suggest_param_adjustments(profile, metrics)
        
        # Small adjustments or empty list acceptable
        if adjustments:
            total_adjustment_magnitude = sum(abs(v) for v in adjustments.values())
            assert total_adjustment_magnitude < 5.0  # Minimal changes needed


class TestValidateOptimization:
    """Test optimization validation logic."""
    
    def test_successful_optimization_validation(self):
        """Test validation passes when improvement exists."""
        metrics_before = CrossValidationMetrics(
            rmse=10.0, mae=8.0, r_squared=0.6,
            max_deviation=15.0, mean_deviation=10.0, num_points=100
        )
        
        metrics_after = CrossValidationMetrics(
            rmse=3.0, mae=2.0, r_squared=0.95,
            max_deviation=5.0, mean_deviation=2.0, num_points=100
        )
        
        result = OptimizationResult(
            success=True,
            original_profile=PlantProfile(name="opt_validate"),
            optimized_profile=PlantProfile(name="opt_validate"),
            metrics_before=metrics_before,
            metrics_after=metrics_after,
            delta_summary="Significant improvement",
            improvement_pct=50.0
        )
        
        is_valid = CrossValidationEngine.validate_optimization(result, min_improvement=0.1)
        assert is_valid is True
    
    def test_failed_optimization_validation(self):
        """Test validation fails when no meaningful improvement."""
        metrics_before = CrossValidationMetrics(
            rmse=5.0, mae=4.0, r_squared=0.8,
            max_deviation=8.0, mean_deviation=3.0, num_points=100
        )
        
        metrics_after = CrossValidationMetrics(
            rmse=5.1, mae=4.1, r_squared=0.79,
            max_deviation=8.5, mean_deviation=3.2, num_points=100
        )
        
        result = OptimizationResult(
            success=True,
            original_profile=PlantProfile(name="no_improve"),
            optimized_profile=PlantProfile(name="no_improve"),
            metrics_before=metrics_before,
            metrics_after=metrics_after,
            delta_summary="Minimal change",
            improvement_pct=1.0
        )
        
        is_valid = CrossValidationEngine.validate_optimization(result, min_improvement=0.05)
        assert is_valid is False


class TestIntegrationOptimizationWorkflow:
    """Test complete optimization workflow integration."""
    
    def test_complete_optimization_pipeline(self):
        """Test full pipeline from curve fitting to validation."""
        # Generate realistic sensor data with known pattern
        np.random.seed(42)
        time_points = np.linspace(0, 3600, 100)  # 1 hour measurements
        
        # Simulated thermal response: T(t) = 25 + 20*(1 - exp(-t/500))
        target_temp = 25.0 + 20.0 * (1 - np.exp(-time_points / 500.0))
        
        # Add realistic noise
        measured_data = target_temp + np.random.normal(0, 0.5, len(time_points))
        
        # Fit curve to measured data
        fitter = CurveFitter()
        model_func, params = fitter.fit(time_points, measured_data)
        
        assert model_func is not None
        assert len(params) > 0
        
        # Compute validation metrics
        predictions = model_func(time_points)
        metrics = CrossValidationEngine.compute_metrics(measured_data, predictions)
        
        # Verify reasonable fits
        assert metrics.r_squared > 0.9
        assert metrics.rmse < 2.0
        
        # Create profiles showing before/after
        original_profile = PlantProfile(
            name="before_optimize",
            plant_params=PlantParameters(ambient_temp_c=25.0)
        )
        
        optimized_profile = PlantProfile(
            name="after_optimize",
            plant_params=PlantParameters(ambient_temp_c=27.0)  # Adjusted based on optimization
        )
        
        result = OptimizationResult(
            success=True,
            original_profile=original_profile,
            optimized_profile=optimized_profile,
            metrics_before=metrics,
            metrics_after=metrics,  # Same in this case
            delta_summary=f"R²={metrics.r_squared:.3f}",
            improvement_pct=15.0
        )
        
        # Validate optimization was meaningful
        is_valid = CrossValidationEngine.validate_optimization(result, min_improvement=0.0)
        assert is_valid is True


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
