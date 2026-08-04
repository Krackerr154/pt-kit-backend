# PT-Kit Improvement Roadmap

> **Date:** 2026-08-04  
> **Branch:** `main`  
> **Repository:** `~/Projects/pt-kit-backend`  
> **Deploy target:** Forge (`10.66.66.5:8000`)

---

## Overview

This document splits PT-Kit improvements into sequenced phases.  
Each phase is independently deliverable, testable, and deployable without breaking prior work.
Phases are ordered by impact-to-effort ratio: fixes that make the dashboard feel correct come first;
polish and new features follow.

---

## Phase 1 — State Integrity & Computation Fixes

**Goal:** The dashboard tells the truth about instrument state and experiment parameters.

### 1.1 ESP32-aware readiness

**Problem:** Green "Ready for experiment" banner and active "Review & start experiment" button appear
even when the ESP32 is disconnected.

**Changes:**
- Tie `Ready for experiment` visibility to backend-online **AND** ESP32-connected.
- When ESP32 is disconnected, show a muted "Waiting for device" banner instead.
- Disable or dim the "Review & start experiment" button when the hardware is offline.
- Show inline tooltip: "Connect ESP32 to begin."
- Change "System ready" to "Backend ready — device disconnected" when ESP32 is offline.

**Affected files:** `app/static/index.html` (JS state logic)  
**Effort:** Small  
**Risk:** Low — pure display logic, no backend changes  
**Test criteria:**
- With ESP32 disconnected: banner says "Waiting for device," button is dimmed.
- With ESP32 connected: banner returns to "Ready for experiment," button activates.
- System Log status reflects the true combined state.

### 1.2 TOTAL TIME computation

**Problem:** `TOTAL TIME 00:00` is always zero regardless of configured parameters.

**Changes:**
- Compute estimated total time from active mode parameters on every field change:
  - **Normal cyclic:** `duration × cycles` seconds
  - **Fixed temperature:** `qualifiedHoldMinutes` minutes (plus ramp estimate)
  - **Natural plateau:** `maxDiscoveryTime` + `confirmationDuration` + `plateauHoldMinutes`
- Display computed time in `HH:MM:SS` or `MM:SS` format.
- Update live as fields change (no need to wait for experiment start).

**Affected files:** `app/static/index.html` (JS computation)  
**Effort:** Small  
**Risk:** Low — display-only  
**Test criteria:**
- Normal cyclic 60s × 5 cycles → displays "05:00"
- Fixed temperature 10 min hold → displays "10:00"
- Changing any parameter updates the timer immediately.

---

## Phase 2 — Empty-State & Guidance Improvements

**Goal:** When the dashboard is idle or disconnected, the user knows exactly what to do next.

### 2.1 Monitoring area troubleshooting hints

**Problem:** The empty telemetry area only says "Waiting for telemetry" with no guidance.

**Changes:**
- Add a collapsible troubleshooting panel below the empty-state message:
  - "Check ESP32 power and USB connection"
  - "Verify the device is provisioned and on the same network"
  - "Restart the backend if the device was recently reconnected"
- Keep the hint compact — a single expandable section.
- Auto-hide when telemetry starts flowing.

**Affected files:** `app/static/index.html` (HTML + CSS)  
**Effort:** Small  
**Risk:** Very low — static guidance text  

### 2.2 System Log collapsed summary

**Problem:** The collapsed System Log only says "System ready," which is misleading when
the ESP32 is disconnected.

**Changes:**
- Show the most recent user-relevant log event in the collapsed bar.
- When idle, show "Waiting for device connection" instead of "System ready."
- Filter internal debug lines; surface only connection changes, experiment events, and errors.

**Affected files:** `app/static/index.html` (JS log filtering)  
**Effort:** Small  
**Risk:** Low  

---

## Phase 3 — Header & Navigation Refresh

**Goal:** The header works cleanly at all desktop widths and surface-level navigation is clear.

### 3.1 Header reorganization

**Problem:** Branding, live status, and utility buttons compete in one row; wrapping is fragile.

**Changes:**
- Split the header into three visual zones:
  1. **Brand block:** PT-Kit + subtitle + health pills
  2. **Live status:** IDLE badge, backend, ESP32, sample
  3. **Utilities:** Data archive, Lux calibration
- At narrower widths, collapse utilities into a "…" overflow menu.
- Use CSS grid with named areas for predictable wrapping.

**Affected files:** `app/static/index.html` (HTML structure + CSS)  
**Effort:** Medium  
**Risk:** Medium — structural HTML change, needs full viewport regression  

### 3.2 Data archive badge

**Problem:** No indication of how many archived experiments exist.

**Changes:**
- Add a small count badge on the "Data archive" button.
- Fetch count from `/api/archive/count` on page load.
- If zero, show no badge.

**Affected files:** `app/static/index.html` (JS), possibly a new API endpoint  
**Effort:** Small  
**Risk:** Low — additive change  

---

## Phase 4 — Mode-Specific Help & Illumination Transparency

**Goal:** Users understand what each mode does and how illumination behaves.

### 4.1 Mode description improvement

**Problem:** Mode descriptions use the same muted gray as everything else and are easy to miss.

**Changes:**
- Add a small `ℹ️` icon beside the mode selector.
- On hover/click, show a tooltip with the full mode description.
- Make the mode-summary text slightly more prominent with a subtle tinted background.

**Affected files:** `app/static/index.html` (CSS + tooltip JS)  
**Effort:** Small  
**Risk:** Low  

### 4.2 Last calibration date display

**Problem:** No indication of when lux calibration was last performed.

**Changes:**
- On the Lux calibration page, show "Last calibrated: <date>" if a record exists.
- If never calibrated, show "Not yet calibrated."

**Affected files:** `app/static/calibration.html` (if separate) or the calibration modal  
**Effort:** Small  
**Risk:** Low  

---

## Phase 5 — Theming & Lab Ergonomics

**Goal:** The dashboard works comfortably in dark lab environments.

### 5.1 Dark mode toggle

**Changes:**
- Add a theme toggle in the header (sun/moon icon).
- Store preference in `localStorage`.
- Define a `[data-theme="dark"]` CSS scope overriding all color variables.
- Apply to all cards, inputs, chart backgrounds, and modals.
- Respect system `prefers-color-scheme` on first visit if no stored preference.

**Affected files:** `app/static/index.html` (CSS custom properties + JS toggle)  
**Effort:** Large (auditing every color declaration)  
**Risk:** Medium — visual regression risk across all states  

### 5.2 Lab-friendly chart colors

**Changes:**
- In dark mode, adjust Chart.js defaults for better contrast.
- Use higher-contrast grid lines and axis labels.

**Affected files:** `app/static/index.html` (Chart.js config)  
**Effort:** Small  
**Risk:** Low  

---

## Phase 6 — Accessibility & Power-User Features

**Goal:** The dashboard is keyboard-navigable and efficient for repeated use.

### 6.1 Keyboard shortcuts

**Changes:**
- `Ctrl+Enter` → Start experiment (from review modal)
- `Ctrl+S` → Focus sample name
- `Escape` → Close any modal or dropdown
- Show shortcut hints on hover for primary actions.

**Affected files:** `app/static/index.html` (JS keydown handlers)  
**Effort:** Medium  
**Risk:** Low  

### 6.2 ARIA and focus management audit

**Changes:**
- Custom dropdown: ensure arrow-key navigation, `aria-activedescendant`.
- Segmented control: ensure `role="radiogroup"` announcements.
- Modal: trap focus, restore on close.
- Review button: announce state changes to screen readers.

**Affected files:** `app/static/index.html` (HTML attributes + JS)  
**Effort:** Medium  
**Risk:** Low  

---

## Phase 7 — Calibration & Guided Workflows

**Goal:** Critical instrument workflows are self-documenting.

### 7.1 Lux calibration wizard

**Changes:**
- Replace the single calibration page with a step-by-step wizard:
  1. Prepare instrument (cover sensor, set distance)
  2. Calibrate zero point
  3. Set reference lux value
  4. Confirm and save
- Show progress indicator.
- Prevent skipping steps.

**Affected files:** `app/static/index.html` (new modal/wizard), possibly backend endpoints  
**Effort:** Large  
**Risk:** Medium — changes calibration workflow  

### 7.2 Pre-experiment checklist

**Changes:**
- Before starting, show a compact checklist:
  - ESP32 connected ✓
  - Sample loaded
  - Safety limits configured
  - Illumination mode selected
- Auto-check items that pass; flag missing ones.

**Affected files:** `app/static/index.html` (review modal enhancement)  
**Effort:** Medium  
**Risk:** Low  

---

## Implementation Schedule

| Phase | Description | Effort | Cumulative |
|-------|-------------|--------|------------|
| 1 | State integrity & computation fixes | Small | — |
| 2 | Empty-state & guidance | Small | P1 done |
| 3 | Header & navigation | Medium | P1–P2 done |
| 4 | Mode help & calibration info | Small | P1–P3 done |
| 5 | Dark mode & theming | Large | P1–P4 done |
| 6 | Accessibility & keyboard | Medium | P1–P5 done |
| 7 | Calibration wizard & checklist | Large | Complete |

---

## Testing Gates Per Phase

Every phase must pass before moving to the next:

1. **JavaScript syntax** — `node -e "new vm.Script(inline)"`  
2. **Frontend tests** — `node --test frontend_tests/*.test.js` (currently 45)  
3. **Docker build** — `sudo docker compose build web`  
4. **Deploy** — `sudo docker compose up -d --force-recreate web`  
5. **HTTP 200** — `curl -s -o /dev/null -w '%{http_code}' http://10.66.66.5:8000/`  
6. **Playwright geometry matrix** — 36 scenarios (5 viewports × 3 modes × System Log open/closed)  
7. **Mobile QA** — 320px, 390px, 412px screenshots  
8. **Git commit + push** — clean working tree, synchronized with `origin/main`

---

*End of roadmap.*
