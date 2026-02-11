# Index.html Update - Graph Reset on Start/End

## Date: 2026-02-11

## Summary
Improved graph reset behavior to handle transitions properly with Arduino/ESP32 delays:
1. **Clear IDLE data when starting experiment**
2. **Clear experiment data when ending (back to IDLE monitoring)**
3. **Account for Arduino/ESP32 communication delays**

## Problem Statement

**Before:**
- When starting: IDLE monitoring data mixed with new experiment data
- When ending: Experiment data remained on graph, no automatic transition back to IDLE
- No handling for Arduino/ESP32 reset delays

**After:**
- Clean graph reset on both start and end transitions
- Proper state management for transitions
- Automatic detection of Arduino/ESP32 reset completion

## Key Changes

### 1. **New State Variable: `isWaitingReset`**

```javascript
var isWaitingReset = false; // Waiting for Arduino/ESP32 to reset to IDLE
```

This flag tracks when we're waiting for hardware to reset after experiment ends.

### 2. **Starting Experiment - Clear IDLE Data**

**Flow:**
```
User clicks START
  ↓
1. Log: "Starting experiment. Clearing IDLE data..."
2. Set isProcessingStart = true (block updates)
3. Set startWaitData = true (wait for reset data)
4. Clear isWaitingReset = false
5. IMMEDIATELY call resetChartData() → GRAPH CLEARED
6. Send start command to server
7. Wait for data with totalSecs < 5 (Arduino reset detected)
8. Resume plotting experiment data
```

**Code:**
```javascript
function startExperiment() {
    log("Starting experiment. Clearing IDLE data...");
    
    isProcessingStart = true;
    startWaitData = true;
    isWaitingReset = false; // Clear any waiting flag
    
    resetChartData(); // IMMEDIATE CLEAR - removes all IDLE data
    
    // Send start command...
}
```

### 3. **Ending Experiment - Transition to IDLE**

**Flow:**
```
Experiment DONE (state = 5)
  ↓
1. experimentFinished() called
2. Log: "Experiment Completed! Waiting for Arduino/ESP32 reset..."
3. Set isWaitingReset = true
4. Show DONE panel (download button)
  ↓
Wait for Arduino/ESP32 to reset...
  ↓
State changes to IDLE (state = 0)
  ↓
1. Detect: isWaitingReset && stateCode == 0
2. Log: "Arduino/ESP32 reset detected. Clearing experiment data..."
3. Call resetChartData() → GRAPH CLEARED
4. Resume IDLE monitoring with ambient data
```

**Code:**
```javascript
function experimentFinished() {
    log("Experiment Completed! Waiting for Arduino/ESP32 reset...");
    setUIState('DONE');
    isWaitingReset = true; // Wait for hardware reset
    // ... show download panel
}

// In updateStatus():
if (isWaitingReset && stateCode == 0) { // Arduino reset to IDLE
    log("Arduino/ESP32 reset detected. Clearing experiment data...");
    isWaitingReset = false;
    resetChartData(); // Clear graph
    // Resume IDLE monitoring
}
```

### 4. **Emergency Stop Handling**

```javascript
function stopExperiment() {
    log("Stopped by User. Waiting for reset...");
    isWaitingReset = true; // Also wait for reset after stop
    // ...
}
```

### 5. **Three Plotting Modes**

```javascript
// A. MODE IDLE - Normal ambient monitoring
if (!isRunning && !isWaitingReset) {
    // Plot recent 60 points (scrolling CCTV mode)
}

// B. MODE WAITING RESET - Transition period
else if (isWaitingReset) {
    // DON'T PLOT - wait for IDLE state detection
    return;
}

// C. MODE RUNNING - Recording experiment
else {
    // Plot all experiment data
}
```

## State Machine Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                         IDLE STATE                          │
│              (Ambient monitoring, 60 pts scroll)            │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       │ User clicks START
                       │ ├─ Clear isWaitingReset
                       │ ├─ resetChartData() → GRAPH CLEARED
                       │ └─ Wait for totalTime < 5
                       ↓
┌─────────────────────────────────────────────────────────────┐
│                      RUNNING STATE                          │
│              (Recording all experiment data)                │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       │ State = DONE (5)
                       │ ├─ Set isWaitingReset = true
                       │ └─ Show download panel
                       ↓
┌─────────────────────────────────────────────────────────────┐
│                   WAITING RESET STATE                       │
│         (Don't plot, wait for Arduino to reset)             │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       │ State = IDLE (0) detected
                       │ ├─ resetChartData() → GRAPH CLEARED
                       │ └─ Clear isWaitingReset
                       ↓
                  Back to IDLE
```

## Delay Handling

**Arduino/ESP32 Reset Delay:**
- Typical delay: 1-3 seconds after DONE state
- Detection method: Monitor state change from 5 (DONE) → 0 (IDLE)
- During delay: Graph plotting is paused (isWaitingReset = true)
- After reset: Graph cleared and IDLE monitoring resumes

**Start Delay:**
- Wait for `totalSecs < 5` to ensure Arduino has reset
- Blocks plotting during this period (startWaitData = true)
- Old IDLE data already cleared immediately on START click

## Benefits

1. **Clean Transitions**: Graph always shows relevant data only
2. **No Data Mixing**: IDLE and experiment data never overlap
3. **Automatic Reset**: No manual intervention needed after experiment
4. **Visual Clarity**: User sees clean graph at all times
5. **Delay Tolerant**: Works with variable Arduino/ESP32 response times

## Edge Cases Handled

- User clicks START multiple times → Blocked by isProcessingStart
- Network delay → State monitoring continues, reset detected when possible
- Manual stop → Same reset logic as natural completion
- Power loss → Next connection resumes normal state detection
- Quick restart → isWaitingReset cleared on new START

## Testing Checklist

- [ ] Graph clears immediately when clicking START
- [ ] IDLE monitoring stops during experiment
- [ ] Graph shows only experiment data during recording
- [ ] After DONE, system waits for Arduino reset
- [ ] Graph clears automatically when Arduino resets to IDLE
- [ ] IDLE monitoring resumes after automatic clear
- [ ] Emergency STOP also triggers reset wait
- [ ] NEW EXPERIMENT button works correctly
- [ ] No data mixing between IDLE and experiment
- [ ] State transitions logged properly in System Log
