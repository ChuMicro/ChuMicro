# Workstream: deploy-bundle bloat overflows the minimum-tier flash

Status: **proposed** (surfaced 2026-06-13 during the generator-networking-apis real-board bake).

## Problem

A *basic* demo can no longer be deployed to the minimum-tier board. Deploying
`demos/requests_fetch` (a one-shot HTTP GET) to a Raspberry Pi Pico W on
CircuitPython failed with `rsync: No space left on device`. The board reports
**~500 KB capacity, 2 KB free** after the deploy attempt. The same demo deploys
and runs fine on an ESP32-S2 CP board (4 MB) and on the Pico W under MicroPython
(mpremote, which does not stage onto the FAT drive the same way).

The user's read, and it is hard to argue with: "so much code bloat now that we
can't do a basic test without running out of disk space — the dependency bloat
and the sheer amount of boilerplate seems out of this world."

This is a tier-contract problem. [Decision 0015](../decisions/0015-board-architecture-support.md)
names 256 KB RAM / 2 MB physical / ~800 KB usable flash as the minimum board.
If a one-request demo cannot be staged there, the ecosystem has outgrown its own
stated floor.

## Suspected contributors (to measure, not assume)

- **Test-harness staging on the demo path.** The user identified the
  `chumicro_test_harness` rsync as what tipped it over. A demo runs `app.py` and
  prints stdout markers the host driver reads over serial — it is not clear the
  full on-device test harness needs to land on the FAT drive for a *demo* deploy
  (vs the on-device *unit-test* sweep, which does). If demo/app deploys can skip
  the harness, that is likely the biggest single win. Measure the harness's
  staged byte cost first.
- **Dependency-chain footprint.** requests_fetch pulls chumicro_requests +
  chumicro_runner + chumicro_sockets + chumicro_wifi + chumicro_config +
  chumicro_timing. Each is modest alone; the sum plus the harness overflows
  500 KB. Measure per-module staged bytes (`.mpy`/`.py`) and find the heavy ones.
- **Per-library size.** Existing next-up bullets already flag this: chumicro_mqtt
  is ~2x the reference impl; `/audit-embedded chumicro_runner.core` +
  chumicro_websockets are queued. Fold those measurements in here.
- **Boilerplate.** Copied `examples/helpers.py` per library, the inline
  runtime_config msgpack decoder, repeated wifi-up scaffolding. Quantify how much
  is duplicated vs load-bearing.

## First steps

1. Measure: `chumicro-workspace`/`chumicro-deploy` staged byte breakdown for the
   requests_fetch deploy on rp2040 CP (per file). Confirm the harness share.
2. Decide whether demo/app (non-unit-test) deploys should stage the test harness
   at all; if not, exclude it from that deploy mode.
3. Re-attempt the requests_fetch deploy on the Pico W CP; it should fit if the
   harness is the main offender.

## Why it matters

The generator-networking-apis demos validated on s2mini-cp (CP, 4 MB) and the
Pico W MP (264 KB RAM) but could not be staged on the Pico W CP — not for a RAM
reason, purely a flash-bundle-size reason. The minimum-tier contract should hold
for a basic demo, or the contract (or the deploy bundle) needs to change.
