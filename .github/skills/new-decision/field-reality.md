# Field reality — `new-decision`

Incidents that motivated specific steps in [SKILL.md](SKILL.md).

## chumicro_mqtt three-tier reshape — missed conflict with Decision 0061

The user and I aligned on a tier-3 design that would have delivered a truncated payload via `on_oversized(reported_length, topic, truncated_payload)`. Decision 0061 — a cross-library `WhenOversized` contract written **the previous day** — specified `on_oversized(reported_length, topic)` exactly two positional args and "drop the oversized payload" semantics. The conflict surfaced only when I read `plans/decisions/` during the "survey existing tests + ADR template" task at the start of implementation, after the design was supposedly final. Caught in time, but later than it should have been. The 30 seconds of `ls plans/decisions/ | xargs grep -l <primitive>` before drafting would have surfaced it during planning.

**Lesson.** Before locking a new design, search `plans/decisions/` for any ADR that touches the same primitive — same cross-library contract, same shared enum, same callback signature, same protocol semantic. The conflict-search recipe in step 1 of [SKILL.md](SKILL.md) is the operational form of this lesson.
