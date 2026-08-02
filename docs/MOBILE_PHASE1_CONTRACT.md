# Mobile UI Phase 1 Contract

## Scope
Implement Phase 1 compact mobile setup in `app/static/index.html` only unless tests require a small dedicated test file.

1. Fix illumination radio horizontal overflow.
2. Make Data archive / Lux calibration touch targets at least 44 px high.
3. Collapse System Log by default on mobile, preserving all existing log content and toggle behavior.
4. Convert the Illumination and Safety fieldsets into accessible mobile accordions with live collapsed summaries. Desktop remains visually unchanged.
5. Add a mobile-only sticky bottom Review action bar that invokes the existing review/start flow; it must not obscure page content.

## Hard constraints
- Preserve all form element IDs and backend/API payload fields.
- Preserve current mode visibility behavior and existing review modal/start logic.
- Do not start or stop a real experiment during QA.
- Desktop behavior/layout must remain unchanged at widths >600 px.
- Mobile viewports: 320, 390, 412 px. Acceptance: `scrollWidth == clientWidth`, no offscreen meaningful controls, all visible controls >=44 px high.
- Hidden radio inputs must be 1x1 or otherwise non-layout-affecting.
- A collapsed fieldset must auto-open/focus when it contains an invalid input.
- Sticky action is IDLE/setup only; hide while running/terminal states as appropriate using existing UI state.
- Add bottom padding equal to action-bar height on mobile.
- No database mutation in QA.

## Verification
- HTML/inline-JS syntax smoke check.
- Existing Python suite: `pytest tests/ --ignore=tests/test_models.py` using Hermes venv.
- Existing JS stats tests.
- Read-only Playwright mobile geometry test against a temporary candidate server.
- Compare desktop geometry/appearance markers.
- Rollback-safe web-service deployment only after all gates pass.

## Ownership partition
- Worker A: inspect and propose exact CSS/HTML changes for overflow, touch targets, accordions; no edits.
- Worker B: inspect JS state/modal/log handlers and propose integration points for summaries and sticky review; no edits.
- Worker C: design QA assertions and edge cases; no edits.
- Main agent: integrate implementation, tests, deployment, and verification.
