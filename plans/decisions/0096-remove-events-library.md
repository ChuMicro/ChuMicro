# Decision 0096: remove the events library

Status: `proposed`
Date: `2026-07-03`
Summary: `chumicro_events` is deleted; direct callbacks and `Signal` are the sanctioned notification patterns; a bus returns only inside a concrete consumer that needs one.
Related: 0014 (the runner's bus was removed once already), 0091/0095 (Signal), 0092, campaign reports `plans/reviews/2026-07-03-{rudiment-api-fitness,greenfield-core-redesign}.md`

## Context

`EventBus` has zero consumers anywhere in the repo outside its own tests and examples;
demos and libraries wire `on_*` callbacks directly, and `Signal` covers the
generator-bridge case.  This is the second time the ecosystem has rejected a bus:
Decision 0014 removed one from the runner.  Meanwhile the wifi guide actively recruits
users into EventBus, teaching a pattern nothing else uses.  Two independent campaign
seats reached the delete verdict blind.

## Decision

Delete `libraries/events` entirely (0092: no deprecation period, nothing published).
Sweep the recruitment out of docs — the wifi guide's EventBus section foremost — and out
of bundle/channel manifests.  The sanctioned notification patterns are direct callbacks
(`on_state_change`, `on_connect`, …) and `Signal`.  If a future library (e.g. a presence
or automation layer) genuinely needs fan-out, the bus is revived inside that consumer
with its requirements in hand, not speculatively.

## Consequences

One less library, test suite, unix-port lane, and bundle entry.  Decision 0014 gains a
cross-link recording the second rejection.  Anyone importing `chumicro_events` breaks
loudly at import — acceptable pre-publication, and there are provably no such importers.
