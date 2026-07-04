# Core design realignment (2026-07 design campaign)

Status: **decision menu awaiting user verdicts** (2026-07-03).  Eight-report adversarial
design campaign: API fitness (mqtt, rudiments), hot-path buffer audit, ADR drift audit,
consumer angle (sister repo), DI cost measurement, and two independent design seats
(greenfield + consumer-driven synthesis).  Every claim below is evidenced in
[`../reviews/`](../reviews/) — file list at the bottom.  Draft ADRs 0095–0099 carry the
proposed decisions; nothing ships until the user picks.

## Decision menu

| # | Surface | Verdict | Cost | First consumer that benefits | Where |
|---|---------|---------|------|------------------------------|-------|
| 1 | timing | **extend** — `Deadline`/`earliest()`/`Rate`; `Signal`+waits move in from runner | 6 pts | six libraries delete seven hand-rolled wait shapes | [ADR 0095](../decisions/0095-timing-wait-vocabulary.md) |
| 2 | events | **remove** — zero consumers, second bus rejection | 2 pts | doc truth (wifi guide recruits users into a dead end) | [ADR 0096](../decisions/0096-remove-events-library.md) |
| 3 | runner | **contract slim only** — `io_interest` bitmask, fold `io_error`; architecture stays | 4 pts | G1/RUN-2 bug class becomes structurally impossible | [ADR 0097](../decisions/0097-runner-io-contract-slim.md) |
| 4 | sockets | **rewrite connect path** — one state machine, 12→8 callables, `transport_factory=` everywhere | 8 pts | standalone integrators + the bake matrix (SOCK-2 class deleted) | [ADR 0098](../decisions/0098-sockets-connect-collapse.md) |
| 5 | mqtt | **three surface corrections + session honesty** | 10 pts | every consumer deletes the pre-connect workaround | [ADR 0099](../decisions/0099-mqtt-surface-corrections.md) |
| 6 | DI | **keep** — measured cost ~3.2 KB flash, 0 hot-path frames; static-resolution recorded as pre-approved fallback, unscheduled | 0 pts | — | DI report §5 |
| 7 | msgpack, config, kvstore, logging | **keep** (logging: re-check unadopted `BufferedHandler` pre-publish) | 0 pts | — | rudiment report |
| 8 | check-api SemVer gate (0020) | **demote to warn-only until publication** — contradicts 0092 in CI today | 1 pt | every breaking migration stops needing SemVer theater | drift audit #1 |
| 9 | hot-path deviations D3–D7 | **fix internally** (one-liners, no API change) | 2 pts | websockets/mqtt per-tick churn | buffer audit §3 |
| 10 | requests chunked-body O(n²) (D2) | **mitigate internally now** (geometric growth); streaming-body API recorded as open design | 1 pt | 8 KB body decode drops from 7.5× penalty | buffer audit §4 |
| 11 | template repo repair | **gated on waves 1–2**; 1-pt hotfix now for the two hard-broken files | 6 pts | new users cloning the flagship | consumer report |

Rejected with evidence (do not reopen without new facts): monolith reactor (3.5 KB blinky
→ 69 KB), shared buffer arena (~1.5 KB reclaim, cross-tick parse state unshareable),
deadline wheel (pays allocations to speed an allocation-free ~30-op scan), 64-bit
monotonic (defeats the no-bigint design), RTC/calendar in timing (ntp's job), custom
codec over msgpack (RAM regression on CP-native builds).

Watched question, deliberately not flipped now: the drift audit argues the generator
substrate should have been the base service contract instead of `check`/`handle`
(0051/0014 lock); the greenfield seat kept `check`/`handle` on evidence.  Resolution
path: waves 1–2 shrink the two-shape overhead 0087 admits to; re-pose the question
after they land, with fresh field data.

## Waves (~42 pts total, dependency-ordered — consumer-synthesis §4)

- **Wave 0 — hygiene (5 pts, no gates):** menu items 2, 8, 9, 10; stale-ADR in-place
  edits (0014 callable registration, 0064 §5 `MQTTPublisher`, 0082 unshipped promotion);
  template hard-break hotfix (menu 11's escape hatch); mqtt session-resume honesty.
- **Wave 1 — core migration (18 pts, bake-matrix gate via `sweep-devices`):** timing
  vocabulary (0095) → runner slim (0097) → sockets collapse + `transport_factory=`
  rename riding the copy-rewrite (0098).  Load-bearing order; one library migrates at a
  time under 0092 (break + migrate all consumers in one commit).
- **Wave 2 — mqtt shape (10 pts):** 0099, after Wave 1's timing/sockets land.
- **Wave 3 — DI recipe docs (2 pts):** the documented empty-closure standalone recipe.
- **Wave 4 — template repair (6 pts, gated on 1–2):** rewrite the six template apps to
  the target state (55-line flagship, consumer-synthesis §3), README/CLI doc sweep.

## Documentation debt surfaced (not gated on the menu)

Missing ADRs: the ~2,500-line `webui/` picker subsystem, the ship-channel manifest
contract, `Runner.run_until`, CHU029/031/032.  Numbering gap at 0050 (leave it).

## Report index

- [`2026-07-03-mqtt-api-fitness.md`](../reviews/2026-07-03-mqtt-api-fitness.md)
- [`2026-07-03-rudiment-api-fitness.md`](../reviews/2026-07-03-rudiment-api-fitness.md)
- [`2026-07-03-hot-path-buffer-audit.md`](../reviews/2026-07-03-hot-path-buffer-audit.md)
- [`2026-07-03-adr-drift-audit.md`](../reviews/2026-07-03-adr-drift-audit.md)
- [`2026-07-03-consumer-angle-workspace-template.md`](../reviews/2026-07-03-consumer-angle-workspace-template.md)
- [`2026-07-03-di-cost-measurement.md`](../reviews/2026-07-03-di-cost-measurement.md)
- [`2026-07-03-greenfield-core-redesign.md`](../reviews/2026-07-03-greenfield-core-redesign.md)
- [`2026-07-03-consumer-driven-design-synthesis.md`](../reviews/2026-07-03-consumer-driven-design-synthesis.md)
