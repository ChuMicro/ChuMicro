# Decision 0097: runner io-contract slim

Status: `proposed`
Date: `2026-07-03`
Summary: An `io_interest` bitmask replaces the two boolean interest hooks and `io_error` folds into the single dispatch lane; the runner's architecture is otherwise unchanged.
Related: 0080 (reactor), 0087 (generator tasks), 0051/0014 (service contract — watched question in the campaign workstream), campaign reports `plans/reviews/2026-07-03-{greenfield-core-redesign,consumer-driven-design-synthesis,adr-drift-audit}.md`

## Context

The io-service contract exposes two boolean interest hooks where one bitmask belongs,
and `io_error` dispatches through its own lane beside the main one — the split that
produced the G1/RUN-2 bug class (iterating live entries while `_mark_done` mutates).
The greenfield seat stress-tested the alternatives (readiness dispatch, async, capability
handles, run-loop ownership) and every one loses on recorded field evidence; the fix is
contract hygiene, not architecture.  The consumer seat verified zero template apps and
exactly one demo implement `io_*`, so the migration is cheaper than priced.

## Decision

1. `io_interest(now_ms) -> int` (READ/WRITE bitmask constants) replaces the paired
   boolean hooks.
2. `io_error` folds into the one dispatch lane; the error path uses the same snapshot
   iteration as everything else, making the G1/RUN-2 class structurally impossible.
3. `check`/`handle` and the generator substrate are unchanged.  The drift-audit's deeper
   question — should generators be the base contract — is deliberately not decided here;
   it is re-posed after this wave lands (see the campaign workstream's watched question).

## Consequences

Library io-services (sockets adapters, websockets/mqtt sessions) migrate in one wave
with 0095/0098; app authors are untouched.  One demo updates.  The `io_error` isolation
finding from the generator-io review closes structurally rather than by point fix.
