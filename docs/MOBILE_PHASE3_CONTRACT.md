# Mobile UI Phase 3 Contract — State-aware Monitoring Density

## Scope
Reduce IDLE/no-telemetry clutter in `app/static/index.html` without changing telemetry ingestion, scientific buffers, charts, experiment payloads, or physical behavior.

## Requirements
1. Before the first valid scientific sample, hide the five KPI cards and cycle-history card.
2. Show one compact monitoring empty state with backend/device context. On mobile its minimum height must be <=180 px; desktop may remain comfortable but not imply data.
3. Do not repeat IR/TC/Lux "No data" health chips before any sample exists. Initial health shows only Backend, Telemetry, and Device.
4. After any sample exists, reveal KPI cards and detailed channel health. Invalid channels remain independently reported.
5. After valid samples have existed, backend failure/staleness must retain KPI values, charts, and history; do not revert to first-use blank state.
6. Mark retained data context as stale/offline through existing health and chart overlay behavior.
7. During RUNNING/STOPPING, monitoring remains first in responsive order and the persistent Stop control remains unchanged.
8. DONE/ABORTED preserve result cards, cycle history, export, and reset behavior.
9. No horizontal overflow at 320/390/412 px; desktop unchanged.
10. Browser QA must not mutate production or start an experiment.

## Acceptance
- Initial IDLE: KPI hidden, cycle history hidden, compact empty state visible, 3 compact health items.
- First valid sample: KPI and detailed health visible, charts visible.
- Later backend loss: prior KPI/charts remain visible and are labelled stale/disconnected.
- Fresh no-data page remains honest and compact.
- Existing frontend and Python regressions pass.
- Rollback image before web-only deployment.
