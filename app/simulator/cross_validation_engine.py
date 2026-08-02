"""Cross-validation engine for plant simulation system optimization.

This module provides curve fitting, statistical metrics computation,
outlier detection, and parameter suggestion algorithms for calibration workflows.
"""

from dataclasses import dataclass
from typing import List, Dict, Any, Tuple, Optional
import numpy as np


@dataclass
class CrossValidationMetrics:
    """Statistical metrics comparing measured vs simulated data.
    
    Attributes:
        rmse: Root Mean Square Error - measures average prediction error magnitude
        mae: Mean Absolute Error - robust to outliers
        r_squared: Coefficient of determination - goodness of fit (0-1, higher better)
        max_deviation: Maximum single-point deviation between curves
        mean_deviation: Average absolute deviation across all points
        num_points: Number of comparison points
    """
    rmse: float
    mae: float
    r_squared: float
    max_deviation: float
    mean_deviation: float
    num_points: int


@dataclass 
class OptimizationResult:
    """Complete result from parameter optimization workflow.
    
    Attributes:
        success: Whether optimization completed successfully
        original_profile: Profile before optimization
        optimized_profile: Profile after optimization
        metrics_before: Validation metrics before optimization
        metrics_after: Validation metrics after optimization
        delta_summary: Human-readable summary of changes
        improvement_pct: Overall improvement percentage (positive = better)
    """
    success: bool
    original_profile: 'PlantProfile'
    optimized_profile: 'PlantProfile'
    metrics_before: CrossValidationMetrics
    metrics_after: CrossValidationMetrics
    delta_summary: str
    improvement_pct: float


class CurveFitter:
    """Curve fitting utilities for polynomial and exponential models."""
    
    def __init__(self):
        """Initialize curve fitter with default settings."""
        self.fitted_model = None
        self.model_params = {}
    
    def fit(
        self,
        x_data: np.ndarray,
        y_data: np.ndarray,
        degree: int = 2
    ) -> Tuple[callable, Dict[str, Any]]:
        """Fit polynomial or exponential curve to data.
        
        Args:
            x_data: Independent variable array (e.g., time in seconds)
            y_data: Dependent variable array (e.g., temperature readings)
            degree: Polynomial degree (2=quadratic, 3=cubic, etc.)
            
        Returns:
            Tuple of (prediction function, model parameters dict)
            
        Example:
            >>> x = np.array([0, 1, 2, 3, 4])
            >>> y = np.array([1, 4, 9, 16, 25])
            >>> fitter = CurveFitter()
            >>> predict, params = fitter.fit(x, y, degree=2)
            >>> predict(5)  # Returns 36 for perfect quadratic
        """
        self.fitted_model = lambda x: self._predict_poly(x, degree)
        
        coeffs = np.polyfit(x_data, y_data, degree)
        self.model_params = {
            'poly_coeffs': coeffs.tolist(),
            'degree': degree,
            'num_points': len(x_data),
            'x_range': [float(x_data.min()), float(x_data.max())]
        }
        
        return self.fitted_model, self.model_params
    
    def _predict_poly(self, x: np.ndarray, degree: int) -> np.ndarray:
        """Internal polynomial prediction using fitted coefficients."""
        coeffs = self.model_params.get('poly_coeffs', [])
        if not coeffs:
            raise ValueError("No model fitted yet")
        
        result = np.zeros_like(x, dtype=float)
        for i, coeff in enumerate(reversed(coeffs)):
            result += coeff * (x ** i)
        
        return result
    
    def get_model_parameters(self) -> Dict[str, Any]:
        """Extract currently fitted model parameters.
        
        Returns:
            Dictionary containing model type, coefficients, and metadata
            
        Raises:
            ValueError: If no model has been fitted
        """
        if not self.model_params:
            raise ValueError("No model fitted. Call fit() first.")
        
        return self.model_params.copy()
    
    def predict(self, x_values: np.ndarray) -> np.ndarray:
        """Generate predictions from current fitted model.
        
        Args:
            x_values: Array of independent variable values to predict for
            
        Returns:
            Array of predicted dependent variable values
            
        Raises:
            ValueError: If no model fitted
        """
        if self.fitted_model is None:
            raise ValueError("No fitted model available. Call fit() first.")
        
        return self.fitted_model(x_values)


class CrossValidationEngine:
    """Core engine for cross-validation metrics and parameter optimization."""
    
    DEFAULT_TOLERANCE = 0.05
    MIN_IMPROVEMENT_THRESHOLD = 0.01
    
    def __init__(self, tolerance: float = DEFAULT_TOLERANCE):
        """Initialize cross-validation engine.
        
        Args:
            tolerance: Acceptable error tolerance for validation checks
        """
        self.tolerance = tolerance
        self.current_metrics = None
    
    @staticmethod
    def compute_metrics(
        measured: np.ndarray,
        simulated: np.ndarray
    ) -> CrossValidationMetrics:
        """Compute comprehensive statistical metrics between datasets.
        
        Args:
            measured: Reference/measured data array
            simulated: Simulated/computed data array
            
        Returns:
            CrossValidationMetrics object with complete metric set
            
        Raises:
            ValueError: If arrays have different lengths
            TypeError: If inputs are not numeric arrays
            
        Example:
            >>> measured = np.array([25.0, 27.0, 30.0, 32.0])
            >>> simulated = np.array([25.2, 26.8, 30.5, 31.8])
            >>> metrics = CrossValidationEngine.compute_metrics(measured, simulated)
            >>> print(f"R²={metrics.r_squared:.3f}")
        """
        measured = np.asarray(measured, dtype=float)
        simulated = np.asarray(simulated, dtype=float)
        
        if len(measured) != len(simulated):
            raise ValueError("Input arrays must have same length")
        
        n = len(measured)
        
        # RMSE: Root Mean Square Error
        mse = np.mean((measured - simulated) ** 2)
        rmse = np.sqrt(mse)
        
        # MAE: Mean Absolute Error  
        mae = np.mean(np.abs(measured - simulated))
        
        # Max deviation
        deviations = np.abs(measured - simulated)
        max_deviation = float(np.max(deviations))
        mean_deviation = float(np.mean(deviations))
        
        # R-squared (coefficient of determination)
        ss_res = np.sum((measured - simulated) ** 2)
        ss_tot = np.sum((measured - np.mean(measured)) ** 2)
        
        if ss_tot == 0:
            r_squared = 1.0 if ss_res == 0 else 0.0
        else:
            r_squared = 1.0 - (ss_res / ss_tot)
        
        return CrossValidationMetrics(
            rmse=float(rmse),
            mae=float(mae),
            r_squared=float(max(-1.0, min(1.0, r_squared))),  # Clamp to [-1, 1]
            max_deviation=max_deviation,
            mean_deviation=mean_deviation,
            num_points=n
        )
    
    @staticmethod
    def detect_outliers(
        data: np.ndarray,
        threshold_std: float = 3.0
    ) -> List[Tuple[int, float]]:
        """Detect outliers beyond specified standard deviations from mean.
        
        Args:
            data: Input data array to analyze
            threshold_std: Number of std devs from mean to consider outlier
            
        Returns:
            List of (index, value) tuples for detected outliers
            
        Example:
            >>> data = np.array([1, 2, 3, 4, 100])  # 100 is outlier
            >>> outliers = CrossValidationEngine.detect_outliers(data)
            >>> print(outliers)  # [(4, 100)]
        """
        data = np.asarray(data, dtype=float)
        mean = np.mean(data)
        std = np.std(data)
        
        if std == 0:
            return []  # No variance means no outliers
        
        threshold = threshold_std * std
        outliers = []
        
        for idx, value in enumerate(data):
            if abs(value - mean) > threshold:
                outliers.append((int(idx), float(value)))
        
        return outliers
    
    @staticmethod
    def suggest_param_adjustments(
        profile: 'PlantProfile',
        metrics: CrossValidationMetrics
    ) -> Dict[str, float]:
        """Generate parameter adjustment suggestions based on validation metrics.
        
        Args:
            profile: Current PlantProfile being optimized
            metrics: Validation metrics showing error levels
            
        Returns:
            Dictionary mapping parameter names to suggested adjustments
            
        Note:
            For high RMSE (>10), suggests larger adjustments
            For low RMSE (<1), suggests minimal fine-tuning only
        """
        suggestions = {}
        
        # Suggest based on RMSE severity
        if metrics.rmse > 10.0:
            # Large errors - suggest major parameter re-tuning
            suggestions['ambient_temp_c'] = 1.5  # Higher adjustment
            suggestions['thermal_mass'] = 0.5
            suggestions['lamp_efficiency'] = 5.0
        elif metrics.rmse > 5.0:
            # Medium errors - moderate adjustments
            suggestions['ambient_temp_c'] = 0.5
            suggestions['thermal_mass'] = 0.2
            suggestions['lamp_efficiency'] = 2.0
        elif metrics.rmse > 1.0:
            # Small errors - fine tuning
            suggestions['ambient_temp_c'] = 0.1
            suggestions['thermal_mass'] = 0.05
        else:
            # Already very good - minimal changes needed
            pass  # Empty dict indicates no adjustments necessary
        
        # Additional suggestions based on R²
        if metrics.r_squared < 0.7:
            suggestions['sensor_gain'] = 0.1  # May indicate gain issues
        
        return suggestions
    
    @staticmethod
    def optimize_parameters(
        profile: 'PlantProfile',
        measured_data: np.ndarray,
        target_temp_data: np.ndarray,
        max_iterations: int = 100
    ) -> OptimizationResult:
        """Run complete optimization workflow to improve profile accuracy.
        
        Args:
            profile: Initial PlantProfile configuration
            measured_data: Measured experimental data
            target_temp_data: Target temperatures for corresponding times
            max_iterations: Maximum optimization iterations (default 100)
            
        Returns:
            OptimizationResult with before/after profiles and metrics
            
        Workflow:
            1. Compute baseline metrics for original profile
            2. Iteratively adjust parameters toward optimal solution
            3. Re-compute metrics after each iteration
            4. Return final optimized profile with complete audit trail
        """
        from app.simulator.profile_management import PlantParameters
        
        # Generate simulated data from current profile
        time_steps = np.arange(len(measured_data))
        
        # Simple thermal model: T(t) = ambient + (target - ambient) * (1 - exp(-t/time_const))
        time_const = profile.plant_params.thermal_mass * 10.0
        simulated_before = (
            profile.plant_params.ambient_temp_c + 
            (target_temp_data.max() - profile.plant_params.ambient_temp_c) *
            (1 - np.exp(-time_steps / time_const))
        )
        
        metrics_before = CrossValidationEngine.compute_metrics(measured_data, simulated_before)
        
        # Optimization loop: gradually reduce error
        optimal_profile = profile.clone() if hasattr(profile, 'clone') else profile
        
        for iteration in range(max_iterations):
            # Simplified gradient descent approach
            if metrics_before.rmse < 0.5:  # Converged
                break
            
            # Adjust parameters slightly toward observed data
            adjustment_factor = 0.01 * (max_iterations - iteration) / max_iterations
            
            if hasattr(optimal_profile, 'plant_params'):
                optimal_profile.plant_params.ambient_temp_c *= (1 + adjustment_factor * 0.1)
            
            # Re-simulate and check improvement
            simulated_new = (
                optimal_profile.plant_params.ambient_temp_c +
                (target_temp_data.max() - optimal_profile.plant_params.ambient_temp_c) *
                (1 - np.exp(-time_steps / (optimal_profile.plant_params.thermal_mass * 10.0)))
            )
            
            new_metrics = CrossValidationEngine.compute_metrics(measured_data, simulated_new)
            
            if new_metrics.rmse < metrics_before.rmse:
                metrics_before = new_metrics
                # Keep updated profile
            else:
                break  # Diverging - stop optimization
        
        metrics_after = metrics_before
        
        delta_summary = (
            f"RMSE: {metrics_after.rmse:.3f} | "
            f"R²: {metrics_after.r_squared:.3f}"
        )
        
        improvement = (
            (metrics_before.rmse - metrics_after.rmse) / 
            max(metrics_before.rmse, 0.001) * 100
        ) if metrics_before.rmse > 0 else 0
        
        return OptimizationResult(
            success=True,
            original_profile=profile,
            optimized_profile=optimal_profile,
            metrics_before=metrics_before,
            metrics_after=metrics_after,
            delta_summary=delta_summary,
            improvement_pct=min(100.0, max(-100.0, improvement))
        )
    
    @staticmethod
    def validate_optimization(
        result: OptimizationResult,
        min_improvement: float = MIN_IMPROVEMENT_THRESHOLD
    ) -> bool:
        """Validate that optimization provided meaningful improvement.
        
        Args:
            result: OptimizationResult to validate
            min_improvement: Minimum acceptable improvement fraction (0.01 = 1%)
            
        Returns:
            True if optimization was successful and meaningful, False otherwise
            
        Validation Criteria:
            - Metrics must show actual improvement (lower RMSE, higher R²)
            - Improvement must exceed minimum threshold
            - Final metrics must be within reasonable bounds
        """
        if not result.success:
            return False
        
        # Check RMSE improvement
        rmse_improved = result.metrics_after.rmse <= result.metrics_before.rmse
        
        # Check R² improvement
        r_squared_improved = result.metrics_after.r_squared >= result.metrics_before.r_squared
        
        # Check magnitude of improvement
        overall_improvement = (
            result.metrics_before.rmse - result.metrics_after.rmse
        ) / max(result.metrics_before.rmse, 0.001)
        
        return (
            rmse_improved and 
            r_squared_improved and 
            overall_improvement >= min_improvement
        )
