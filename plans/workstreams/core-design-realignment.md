# Core design realignment (2026-07 design campaign)

Status: **ALL WAVES SHIPPED** (approved 2026-07-03 "wave zero until done"; Waves 0-3 +
the mqtt wave landed on monorepo main 2026-07-03/04, Wave 4 on the template repo
2026-07-04).  Landed: Wave 0 hygiene (events deleted per 0096; 0020 gate warn-only;
hot-path D2-D7 with measured drops; stale ADRs trued); Wave 1 core migration — timing
0.7.0 wait vocabulary (0095), runner 0.18.0 io_interest + one dispatch lane (0097),
sockets 0.17.0 connect collapse + transport_factory= across five libraries (0098, with
five ADR-premise corrections recorded); Wave 2 mqtt 0.22.0 surface corrections (0099,
lanes dropped to 240K); Wave 3 the standalone-integration recipe; Wave 4 the template
rebased to current main (flagship 174→61 lines, baked end-to-end to a public broker
from real silicon).  Residuals closed 2026-07-04: the FSKit
recovery landed and the full four-board closing matrix went green; the io_interest
TLS-handshake refinement shipped in sockets 0.17.1 (the connector narrows its
``awaiting_tls`` interest to the direction the last ``SSLWant*`` signal named); the
watched question below was re-posed and closed 2026-07-04 — verdict KEEP.  Eight-report adversarial
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

Watched question — RESOLVED 2026-07-04.  The re-pose ran with post-wave field data and
returned **KEEP** (check/handle stays the base contract; generators stay the convenience
layer), with five explicit reopening criteria so the question is *closed*, not watched —
see [`../reviews/2026-07-04-check-handle-generators-repose.md`](../reviews/2026-07-04-check-handle-generators-repose.md).
Headline evidence: 43 sister-repo check/handle registrations vs zero app-code generator
tasks (including the from-scratch Wave-4 template rewrite); the generator lane is a
278-line client of the base contract, not a peer (a check/handle object *is* a valid
wait token); per-task RAM at parity (544 vs 448 B on the MP unix port).  Future design
passes cite the report instead of re-litigating.  Census by-catch: the six private wait
shapes are Decision 0095's dropped second half (queued in next-up); the runner README's
removed callable-registration section was fixed on closure.

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

Missing ADRs: the ~2,500-line `.claude/surfaces/` picker subsystem, the ship-channel manifest
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
- [`2026-07-04-check-handle-generators-repose.md`](../reviews/2026-07-04-check-handle-generators-repose.md)
