# Workstream: OTA (over-the-air updates)

Status: `unscoped` — placeholder for a potential future workstream.  Not in active scope.

Carved out of `project-workspace.md` as Phase 8 on 2026-04-27 so the project-workspace workstream could close cleanly.  The idea is preserved here as a discrete thing-to-do without a current scope, sequence, or estimate.

## Why this exists as a separate file

Project-workspace closed clean once OTA moved out.  A thing on a wall / in a yard / stuck somewhere inconvenient eventually needs an update without dragging it back to a laptop, and we'd rather have a short note pointing at the design exploration than nothing when that need surfaces.

## Trigger

Revisit when a real thing has been deployed in the field for long enough that "deploy without crawling behind the couch" is a felt need — not a hypothetical.  Until then, do not invest in design.

## Where the prior thinking lives

Design exploration sits in `plans/workstreams/project-workspace-research.md` §OTA — proposed shape (`chumicro-update` library, runner-shaped service over MQTT primary + HTTP later), CP CIRCUITPY-drive vs filesystem-writable boot-time auto-detect, security tier, scoped-out items.  Read that section first if you're picking this up.

## What this workstream would NOT cover

* CP firmware self-update — no exposed API, structurally out of scope.
* MP ESP32 A/B firmware OTA via `esp32.Partition` — possible but a separate spike.
* Zephyr / MCUboot / secure-boot fuses — different ecosystem.

## Next step when work begins

Promote this file from `unscoped` to `proposed`, expand it into Purpose / Scope / Sequencing sections matching the workstream-doc convention, and link from `plans/next-up.md` `## Next`.
