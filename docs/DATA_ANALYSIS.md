# PT-Kit Data Analysis Conventions

> Authoritative description of the statistics methodology used by the history/archive view.
> Single source of truth in code: `app/static/pt-stats.js` (DOM-free module, exposed as `window.PTStats` in the browser and `module.exports` in Node).
> Test suite: `tests/js/pt-stats.test.js` (run with plain `node` — 20 tests).
> Consumers: `app/static/history.html` (archive view), `app/static/index.html` (live dashboard, see §8).

## Table of Contents

1. [Row Filtering](#1-row-filtering)
2. [Cycle-Aware Regression (primary statistic)](#2-cycle-aware-regression-primary-statistic)
3. [Pooled Regression & R² (visual guide only)](#3-pooled-regression--r²-visual-guide-only)
4. [Overlay Mean/SD Bands via Common Time Grid](#4-overlay-meansd-bands-via-common-time-grid)
5. [Cross-Experiment Compare Alignment](#5-cross-experiment-compare-alignment)
6. [Inferential Statistics: CI95 and Welch t-test](#6-inferential-statistics-ci95-and-welch-t-test)
7. [Numerical Edge Cases](#7-numerical-edge-cases)
8. [Live vs Archive Parity](#8-live-vs-archive-parity)
9. [Design Rationale (why not pooled regression)](#9-design-rationale-why-not-pooled-regression)

---

## 1. Row Filtering

All analysis operates on **state-filtered** rows (`state_label` from the backend, or the `State` column in exports):

- **Plottable rows** — everything except `PRE_HEAT`, `IDLE`, `DONE` (`isPlottableRow`). Used for overlays and mean/SD bands. The filter is substring-based (`!includes('PRE')`, `!includes('IDLE')`, `!includes('DONE')`) so plateau/isothermal states (e.g. `ISO_HOLD`, `PLATEAU_HEATING`) are retained.
- **Heating rows** — strictly the heating phase (`isHeatingRow`): label is exactly `HEATING`, or contains `HEAT` but not `PRE` (so `PLATEAU_HEATING` qualifies; `PRE_HEAT` never does). Used for all slope/regression fits.
- Rows without state information: kept as plottable, **never** treated as heating (slope fits require state info).

## 2. Cycle-Aware Regression (primary statistic)

`calculateSlopeStats(data, kCyc, kState, kTime, kTemp)`:

1. Group rows by `cycle_num`.
2. Per cycle: select heating rows only; require **> 2 points** (n ≥ 3) else the cycle is skipped.
3. x-axis: **time relative to the cycle's own first row** (`x = d[kTime] − cData[0][kTime]`); y: temperature (IR or TC).
4. Ordinary least-squares slope per cycle.
5. Report `{ mean, sd, n, slopes }` over the distribution of per-cycle slopes (sample SD, ÷(n−1)).

The **per-cycle slope distribution is the primary inferential unit** for all reported heating-rate statistics. This treats each cycle as one experimental replicate instead of treating every sample point as independent.

Minimum gates: a cycle needs ≥ 3 heating points; CI/t-test need ≥ 2 usable cycles (see §6).

## 3. Pooled Regression & R² (visual guide only)

`calculateLinearRegression(...)` pools every cycle's heating points onto one scatter (each cycle x-referenced to its own start) and returns `{ slope, intercept, r2, points, count }`.

- The UI draws it as a dashed trend line and labels it **"Pooled heating R² (visual guide only)"** (`history.html`).
- It is **excluded from all inferential statistics** (no CI, no t-test) because pooling repeated in-cycle measurements as independent points exaggerates confidence.
- Known cosmetic nit: its x-origin is the cycle's first row (including PRE_HEAT timestamps), while the displayed heating series starts at the heating phase — so the pooled line's intercept is shifted slightly relative to the plotted data. Slope and R² are unaffected. Tracked as LOW severity; intentionally left as-is because the line is explicitly visual-only.

## 4. Overlay Mean/SD Bands via Common Time Grid

`calculateStatistics(data, kCyc, kTime, kIR, kTC, kState)` produces the overlay mean and ±SD bands:

1. Per cycle, filter to plottable rows; relative time x = time − **first plottable row of that cycle** (not the cycle's DB start).
2. `buildCommonTimeGrid(series, stepS=1)`: union grid, 0 → max relative end, **1-second steps**.
3. `interpolateToGrid(points, grid)`: linear interpolation per cycle onto the grid; grid times outside a cycle's own [min,max] range yield `null` (never extrapolated).
4. Per grid time: mean and **population SD (÷n)** across whichever cycles cover that time; band = mean ± SD. Grid times covered by < 1 cycle are omitted.

This replaces the earlier exact-timestamp bucketing, which fragmented into near-single-point bins when sampling intervals differed slightly between cycles.

## 5. Cross-Experiment Compare Alignment

`loadCompare()` in `history.html` aligns multiple experiments on the x-axis by **elapsed time relative to each experiment's own first row**:

```js
var t0 = data.length ? data[0][kTime] : 0;
x = d[kTime] - t0
```

Rationale (code comment, now documented here): experiments with different sampling intervals must not be compared by row index, which distorts the time axis. Compare view plots IR temperature only; statistical comparison of heating rates uses the Welch t-test on per-cycle slopes (§6).

## 6. Inferential Statistics: CI95 and Welch t-test

**95% CI for the mean per-cycle slope** — `slopeCI95(stats, studentTInv)`:

```
half-width = (sd / √n) × t(0.975, n−1)
```

- Requires n ≥ 2 cycles; returns null otherwise.
- The Student-t inverse is **injected** (jStat in the browser). Fallback: z = 1.96 normal approximation — acceptable for n ≳ 30, approximate for the small n typical of this instrument. Treat small-n CIs accordingly.

**Welch two-sample t-test (unequal variances)** — `welchTTest(A, B, studentTCdf)` on the per-cycle slope arrays of two experiments:

- Gates: n ≥ 2 cycles in each sample; zero pooled standard error → null.
- Degrees of freedom: Welch–Satterthwaite.
- p = 2 × t-CDF(−|t|, df), two-sided. **p is `null` without an injected t-CDF** — there is no honest closed-form fallback; the UI must not fabricate a p-value.

> **jStat pitfall (verified from source):** jStat 1.9.6's `ttest()` has **no two-independent-samples code path** — it silently falls through to a one-sample-vs-array branch and returns meaningless output. Never use `jStat.ttest(A, B, …)` for compare; `PTStats.welchTTest` exists precisely to avoid this.

## 7. Numerical Edge Cases

- Constant x or constant y within a fit window ⇒ zero denominator ⇒ `NaN` slope/R². Currently **unhandled**; callers should treat non-finite results as "insufficient data" rather than displaying them.
- Non-finite sensor values are nulled at ingestion (`parse_telemetry`) and excluded from band means (`Number.isFinite` filter).
- Slopes are computed on raw floats; no unit conversion is applied in the stats layer (°C/s when `kTime` is seconds).

## 8. Live vs Archive Parity

The live dashboard (`index.html`) and archive (`history.html` + `pt-stats.js`) intentionally use **different implementations of the same concept**:

| Aspect | Live (index.html) | Archive (history.html) |
|---|---|---|
| Fit window | Growing window **within the current heating phase**, reset per phase | Complete **per-cycle** fits, then aggregated |
| x-origin | Heating-phase start | Cycle's first row |
| Min points | 2 | 3 |
| R² display | Live KPI color coding (green > 0.95) | Per-cycle R² in history table; pooled R² labeled visual-only |
| Purpose | Immediate feedback | Post-hoc inference (mean/SD/CI/t-test) |

An inline comment in `index.html` says "same formula as history.html" — this is aspirational, not literal. The difference (growing-window vs per-cycle aggregate) is **intentional**: live needs instantaneous feedback mid-phase; archive needs replicate-based inference.

## 9. Design Rationale (why not pooled regression)

A pooled OLS fit across all heating points treats hundreds of correlated, in-cycle samples as independent — understating standard errors and overstating R² significance. The correct replicate unit for a cyclic photothermal experiment is the **cycle**: one slope per cycle, then mean/SD/CI across cycles. The pooled line survives only as a visual trend guide, clearly labeled as such, and is never used for inference.

---

> Related: `docs/BACKEND_API.md` (telemetry fields feeding these functions), `tests/js/pt-stats.test.js` (executable specification of every convention above).
