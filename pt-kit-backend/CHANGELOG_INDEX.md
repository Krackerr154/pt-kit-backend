# Index.html Update - Heating Rate Calculation Improvement

## Date: 2026-02-11

## Summary
Updated `index.html` to use the same heating rate calculation principle as `history.html` - using **Linear Regression** instead of simple buffer averaging.

## Key Changes

### 1. **Heating Phase Filtering** ✅
- **ONLY calculates during HEATING phase (state 2)**
- All other phases (IDLE, PRE_HEAT, COOLING, STABILIZING, DONE) show 0.00 °C/s
- Automatically resets buffers when phase changes

### 2. **Linear Regression Calculation**
- Replaced simple buffer difference: `(last - first) / interval`
- Now uses proper regression: `slope = (n*sumXY - sumX*sumY) / (n*sumXX - sumX*sumX)`
- Matches calculation method in `history.html`

### 3. **Quality Metrics (R²)**
- Added R² (coefficient of determination) to show calculation confidence
- Display format: `0.850 °C/s • R²=0.982`
- Color coding:
  - Green: R² > 0.95 (excellent fit)
  - Yellow/Green: R² > 0.90 (good fit)
  - Gray: R² < 0.90 (poor fit)

### 4. **Enhanced Cycle Table**
- Added R² values to each cycle's heating rate
- Format: `0.123 ±0.005 • R²=0.995`
- Shows both standard error and linearity quality

### 5. **Real-time Accumulation**
- Uses `liveHeatingBufferIR` and `liveHeatingBufferTC` arrays
- Accumulates all points during heating phase
- Recalculates regression continuously for live updates
- Minimum 3 points required for calculation

## Technical Details

### New Variables
```javascript
var liveHeatingBufferIR = [];     // Accumulates IR data during heating
var liveHeatingBufferTC = [];     // Accumulates TC data during heating
var heatingStartTime = 0;         // Tracks when heating phase started
var lastState = 0;                // Tracks state changes
```

### New Functions
```javascript
calculateRegressionLive(dataPoints) {
    // Performs linear regression
    // Returns: { slope, intercept, r2 }
}
```

### Updated Functions
- `updateLiveRate(ir, tc, time, stateCode)` - Now uses regression
- `calculateSlopeAndError(dataPoints)` - Now returns R² value
- `resetChartData()` - Resets new buffer variables

## Phase States Reference
```
0: IDLE         - No calculation
1: PRE_HEAT     - No calculation
2: HEATING      - ✅ ONLY THIS PHASE calculates heating rate
3: COOLING      - No calculation
4: STABILIZING  - No calculation
5: DONE         - No calculation
```

## Benefits
1. **More Accurate**: Linear regression is statistically more robust than simple averaging
2. **Consistent**: Same calculation method as history/archive analysis
3. **Quality Indicator**: R² shows how linear the heating process is
4. **Phase-Specific**: Only calculates during actual heating, no contamination from other phases
5. **Real-time**: Updates continuously during heating with increasing accuracy

## Testing Checklist
- [ ] Verify heating rate shows 0.00 when NOT in heating phase
- [ ] Verify heating rate calculates only during state 2 (HEATING)
- [ ] Verify R² appears in live rate display
- [ ] Verify R² appears in cycle performance table
- [ ] Verify calculations match history.html analysis
- [ ] Verify buffer resets when phase changes
- [ ] Test with multiple cycles
- [ ] Test experiment stop/reset functionality
