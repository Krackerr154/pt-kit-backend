# History.html Update - Phase Filtering

## Date: 2026-02-11

## Summary
Updated `history.html` to:
1. **Calculate heating rate ONLY from HEATING phase** (exclude PRE_HEAT)
2. **Stack overlay ONLY with HEATING, COOLING, STABILIZING** (exclude PRE_HEAT, IDLE, DONE)

## Key Changes

### 1. **Heating Rate Calculation - Exclude PRE_HEAT** ✅

**Problem Before:**
- Used `.includes('HEAT')` which matched both **HEATING** and **PRE_HEAT**
- This contaminated the heating rate calculation with pre-heating data
- Pre-heating has different characteristics than actual heating phase

**Solution:**
```javascript
// OLD: Matched both HEATING and PRE_HEAT
var heatingData = cData.filter(d => d[kState].toUpperCase().includes('HEAT'));

// NEW: Match HEATING only, exclude PRE_HEAT
var heatingData = cData.filter(d => {
    var stateUpper = d[kState].toUpperCase();
    return stateUpper === 'HEATING' || (stateUpper.includes('HEAT') && !stateUpper.includes('PRE'));
});
```

**Updated Functions:**
- `calculateSlopeStats()` - Now filters to HEATING phase only
- `calculateLinearRegression()` - Now filters to HEATING phase only

### 2. **Overlay Stacking - Exclude PRE_HEAT** ✅

**Problem Before:**
- Overlay mode stacked ALL data from each cycle
- Included PRE_HEAT, making cycles appear longer and misaligned
- Mixed different phase characteristics in overlay comparison

**Solution:**
```javascript
// Filter to only: HEATING, COOLING, STABILIZING
var filteredData = cData.filter(d => {
    var stateUpper = d[kState].toUpperCase();
    // Exclude PRE_HEAT, IDLE, DONE
    return !stateUpper.includes('PRE') && 
           !stateUpper.includes('IDLE') && 
           !stateUpper.includes('DONE');
});

// Use filtered data start time as reference (t=0)
var startT = filteredData[0][kTime];
```

**Updated:**
- Overlay mode in `switchView('overlay')`
- Statistics calculation in `calculateStatistics()`

### 3. **Advanced Mode Statistics** ✅

**Updated:**
- Statistics now calculated from HEATING, COOLING, STABILIZING only
- Excludes PRE_HEAT from mean/SD calculations
- More accurate cycle-to-cycle comparison

## Phase Filtering Logic

### Heating Rate Calculation:
```
✅ HEATING        - Calculate slope
❌ PRE_HEAT       - EXCLUDED
❌ COOLING        - Not included
❌ STABILIZING    - Not included
❌ IDLE           - Not included
❌ DONE           - Not included
```

### Overlay Stacking:
```
✅ HEATING        - Include in stack
✅ COOLING        - Include in stack
✅ STABILIZING    - Include in stack
❌ PRE_HEAT       - EXCLUDED
❌ IDLE           - EXCLUDED
❌ DONE           - EXCLUDED
```

## Benefits

1. **More Accurate Heating Rates**: Pre-heating is typically slower and less controlled, excluding it gives true heating phase characteristics
2. **Better Cycle Alignment**: Overlay now starts from actual heating phase, making cycle comparisons more meaningful
3. **Cleaner Statistics**: Mean and SD calculated from relevant phases only
4. **Consistent with index.html**: Both files now use HEATING phase only for rate calculation

## Visual Impact

**Before (Overlay Mode):**
```
Cycle 1: [PRE_HEAT----HEATING----COOLING----STABILIZING]
Cycle 2: [PRE_HEAT----HEATING----COOLING----STABILIZING]
         ↑ Misaligned due to variable pre-heat times
```

**After (Overlay Mode):**
```
Cycle 1: [HEATING----COOLING----STABILIZING]
Cycle 2: [HEATING----COOLING----STABILIZING]
         ↑ Aligned at heating start (t=0)
```

## Testing Checklist
- [ ] Verify heating rate excludes PRE_HEAT phase
- [ ] Verify overlay mode excludes PRE_HEAT, IDLE, DONE
- [ ] Verify overlay cycles align at heating start
- [ ] Verify advanced mode statistics exclude PRE_HEAT
- [ ] Verify regression line only fits HEATING phase data
- [ ] Compare with live index.html calculations (should match)
