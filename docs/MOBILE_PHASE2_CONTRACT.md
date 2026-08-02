# Mobile UI Phase 2 Contract — Safe Review Sheet

## Scope
Upgrade the existing pre-start review modal in `app/static/index.html` into a mobile bottom sheet while preserving the desktop centered modal and all existing experiment semantics.

## Requirements
1. On widths <=600 px, review appears as a bottom sheet anchored to the viewport bottom.
2. Sheet has a visible drag-handle decoration, compact header, independently scrollable details body, and fixed action footer.
3. On desktop, retain the current centered modal presentation.
4. Review content is an immutable snapshot created by `buildReviewModel()`; changes behind the open modal must not alter `pendingReviewPayload`.
5. Existing `buildExperimentPayload()`, `/api/start_experiment` route, and payload fields remain unchanged.
6. The exact selected values are visible: operator, sample, mode, mode parameters, illumination strategy, logging interval, and safety cutoff.
7. Cancel/back returns focus to the opener and preserves entered form values.
8. Escape and backdrop close review. Tab and Shift+Tab remain trapped between review actions.
9. Confirm can fire only once per review. Disable both actions while a start request is pending; restore them on rejected/failed start without losing the snapshot.
10. Sheet must not overflow horizontally at 320/390/412 px; its top must remain on-screen and details must scroll internally for long modes/short viewports.
11. Use safe-area bottom padding. All visible actions >=44 px.
12. Do not start a real experiment during browser QA; intercept all mutations.

## Verification
- Inline JS syntax.
- Existing frontend tests + PTStats JS tests + full Python suite excluding `tests/test_models.py`.
- Real-handler browser QA on temporary served candidate at 320x568, 390x844, 412x915, and desktop 1440x1000.
- Verify immutable payload snapshot and cancel focus restoration.
- Verify responsive geometry, internal scrolling, backdrop/Escape close, focus trap, and duplicate-confirm guard.
- Production deployment only after all gates pass, with rollback image and direct-origin verification.
