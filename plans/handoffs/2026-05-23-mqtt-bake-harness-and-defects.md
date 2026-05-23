# Handoff 2026-05-23 — MQTT bake harness, false-freeze diagnosis, chumicro defect inventory

## What this session was about

Resumed from `2026-05-23-pi-pico-w-cp-fragmentation-validation` (prior handoff).  Two phases:

1. **Phase 1 (early session):** per-change fragmentation benches on top of the prior session's six-placement gc.collect chain.  Goal: find category-A wins (RAM + fragmentation both improve) and lift patterns to the audit-embedded skill, and answer "are we at the source-side floor?"  Landed two changes (commits 8bef7883 chumicro_mqtt 0.14.0, c2613794 chumicro_msgpack 0.1.28), lifted four pattern sections to audit-embedded/field-reality.md (commit 7ee4c67f), declared the source-side floor reached.

2. **Phase 2 (rest of session):** user asked for a longer "bake test" against MQTT.  Built `projects/mqtt_bake/` and `projects/mqtt_bake_diag*/` in workspace-template, plus `.scratch/mqtt_bake_mac_driver.py`.  Ran 5-min and 9-min bakes across Pi Pico W MP, Pi Pico W CP custom firmware (10.2.0-dirty), Lolin S2 attempts.  Diagnosed an apparent "freeze at t=234s" on every CP run.  After many false hypotheses, the freeze turned out to be a **clock-domain bug in the bake harness** (mixed `time.monotonic` with `supervisor.ticks_ms` via `runner.tick()`).  Real chumicro defects surfaced during the wild goose chase and were filed as a separate workstream.

## What's in flight

Uncommitted as of write:

- `plans/workstreams/chumicro-mqtt-runner-cooperative-tick-convergence.md` — new, captures defects vs the user's reference impl + the holistic-research-pass directive
- `plans/workstreams/mqtt-negative-testing-suite.md` — new, captures negative-testing inventory
- `plans/next-up.md` — `## Now` was cleared earlier; needs the handoff pointer added
- `.idea/chumicro.iml` — pre-existing drift, unrelated to this session
- `workbench/deploy/src/chumicro_deploy/firmware.py`, `workbench/deploy/tests/test_flash_firmware.py` — pre-existing drift, unrelated
- `firmware.bin` (untracked) — pre-existing, unrelated

Local-only (gitignored, won't reach git):

- `projects/mqtt_bake/`, `mqtt_bake_diag/`, `mqtt_bake_diag_ka300/`, `mqtt_bake_diag_lolin/`, `mqtt_bake_diag_plain/` in workspace-template — bake harness in five variants, all now use `chumicro_timing.ticks_ms` exclusively (post-fix)
- `.scratch/mqtt_bake_mac_driver.py` — Mac-side driver, supports `--variant` + `--client-suffix` flags, gates publish loop on first board-received message
- `.scratch/bake-diag-plain-board-v2.log` / `.scratch/bake-diag-plain-mac-v2.log` — the clean PLAIN v2 run that proved no actual chumicro freeze
- `.scratch/frag-iter-session-log.md` — Phase 1's fragmentation iteration table

## What got done (committed)

Commits this session, oldest first:

- `44891bf3` — `plans/handoffs: delete landed 2026-05-22 pico MP fragmentation handoff` (prior session's handoff cleanup)
- `8bef7883` — `chumicro_mqtt 0.14.0: remove MQTTPublisher class + client.publisher()` — strong category A: -7 1-blocks, +3.15 KB contiguous on Pi Pico W MP at post_import.  Bench-confirmed.  [VERIFIED: `.scratch/frag-iter-mp-04-no-mqttpublisher.log`]
- `c2613794` — `chumicro_msgpack 0.1.28: mid-file gc.collect in _pure.py` — +944 bytes free on CP custom firmware at post_import (60× run-to-run noise).  No-op on stock CP where native `msgpack` shadows `_pure`.  [VERIFIED: `.scratch/frag-iter-cp-03-msgpack-mid-gc.log`]
- `7ee4c67f` — `audit-embedded skill: four pattern lifts from CP fragmentation benches` — four new sections in field-reality.md (MP instance attr storage is one allocation, eager-adapter-import anti-pattern, mid-module gc.collect caveat, CP contiguous-floor bytearray probe technique)
- `d1a6d1a7` — `plans/handoffs: delete landed 2026-05-23 Pi Pico W CP fragmentation handoff` (Phase 1 handoff cleanup)

Phase 2 (the bake investigation) produced no commits — just local-only test scaffolding, durable signal lifted to memory + the new workstreams.

Memory lifts (durable, cross-session):

- `feedback_two_sided_mqtt_gate.md` — host driver gates its publish loop on board's first publish; avoids losing the first 15-30 messages to async startup
- `feedback_use_chumicro_timing_always.md` — never raw `time.monotonic` / `supervisor.ticks_ms` / `time.ticks_ms` in chumicro code or harnesses; always go through `chumicro_timing.ticks`.  Cost ~2 hours of misdiagnosis this session.

## Decisions made (not yet captured in ADRs)

- **Source-side optimization is at the floor** on the chumicro_mqtt / chumicro_sockets import chain on Pi Pico W MP.  4 candidates benched, 2 kept (both ~marginal), 2 reverted (one category B, one killed by source-level explanation).  The mp_obj_instance_t.members single-table layout means "consolidate N attrs into a tuple" doesn't save allocations at small N.  **Next live RAM lever is mpy-cross frozen bytecode** (50-80 KB potential per prior session estimate), now queued in `plans/next-up.md`.
- **CP custom firmware (10.2.0-dirty) ships *without* native `msgpack`** — iter-03's +944 byte gain only happens if `_pure` is on the import path, which it shouldn't be on stock CP.  Queued as a follow-up: confirm whether the strip was intentional; restoring native `msgpack` likely gives back 5-15 KB heap.
- **Negative testing is its own workstream.**  Convergence work (the library refactor) and negative testing (the validation suite) are separately schedulable but feed each other.  Both filed.
- **Recv-first is the chosen ordering** in the runner's poll-event handler (clear PUBACKs to free in_flight slots before queueing new publishes).  Per user, lines 524-545 of the reference impl set the pattern.  Captured in the convergence workstream.

## What was learned

Phase 1 lifts (already in canonical homes):

- `mp_obj_instance_t.members` is one mp_map_t — see `.tools/micropython-v1.26.0/py/objtype.h:33` + `obj.h:481`.  Kills the "tuple-instead-of-attrs saves allocations" pattern at small N.  Lifted to `audit-embedded/field-reality.md`.
- Eager adapter import perturbs downstream heap layout — moving `chumicro_sockets._adapters import cp` from lazy to module-load regressed post_connect `max_free_sz` by 911 blocks (-14.5 KB).  Lifted.
- Mid-module gc.collect caveat — verify the file is actually imported before assuming the placement matters.  Lifted.
- CP contiguous-floor `bytearray(N)` probe technique.  Lifted.

Phase 2 lifts (already in canonical homes):

- "Mixed clock domains" pattern — the worst-of-both-worlds when `now_ms()` returns `time.monotonic * 1000` on CP but `runner.tick()` returns `supervisor.ticks_ms` (differs by 65_536 ms on this custom firmware).  Lifted to memory.
- "Two-sided MQTT test gating" — gate host publisher on first board publish, not on host's own connect.  Lifted to memory.

Phase 2 not yet in any canonical home (sit here):

- **CP custom firmware seeds `supervisor.ticks_ms` near 2^29 - 65_536 at boot, then wraps to 0 ~65 seconds into boot.**  After that, `supervisor.ticks_ms` runs 65_536 ms behind `time.monotonic` for the rest of the session.  Per the user, this is *deliberate* — exercises the wrap path early so wrap bugs surface in normal testing.  Worth knowing when reading any clock-related output from this board.  [VERIFIED: CLOCKS log in `.scratch/bake-diag-plain-board-v2.log` shows monotonic_ns_init 39_338_861_083_994 ns ≈ 39_338_861 ms, supervisor_ticks_ms_init 39_273_325 ms, difference exactly 65_536.]
- **`chumicro_deploy` mount-mapping with two CIRCUITPY boards plugged in is racy.**  Parallel deploys to `pi-pico-w-cp` and `lolin-s2-cp` both saw `rsync failed: unexpected end of file` because both deploys appear to have targeted the same `/Volumes/CIRCUITPY*` mount.  Sequential deploys work fine.  Worth filing as a deploy-tool defect; not done this session.
- **chumicro_mqtt 0.14.0's MQTTPublisher removal broke `TestMQTTPublisher` class in `test_client_inbound_pubsugar.py`** — the tests were removed in the same commit but preflight may still surface coverage drift (the removed class had ~30 lines of test coverage).  Verified mqtt tests pass standalone (177 tests, 95.46% coverage) but full preflight on libraries/mqtt wasn't re-run.  Cheap to verify next session.

## Riskiest assumption

That **the chumicro defects in the convergence workstream — when fixed per the reference impl — actually converge to the reference impl's multi-week-uptime resilience.**  The reference's `loop()` is monolithic; chumicro's is split between `chumicro_runner.Runner.wait` and `chumicro_mqtt.MQTTClient.handle`.  The split is itself a runner-pattern design choice (Decision 0080).  Some defects (recv-zero swallowed, no POLLERR/HUP) port cleanly.  Others (one-chunk-per-tick, deadline-first ordering) interact with the runner contract and may need ADR-level decisions.

[HYPOTHESIS: cheapest test = pick the recv-zero defect (cleanest, narrowest) and fix it first.  Run the broker-graceful-disconnect negative test from the negative-testing-suite workstream.  If the board now detects + self-heals cleanly, the pattern of "port defects one-at-a-time, validate via negative test" is the right shape and the rest follow.  If even that one is harder than expected, the bigger refactoring assumption is shaky.]

## To re-research / verify next session

1. **TLS v2 confirmation runs.**  PLAIN v2 on Pi Pico W CP custom firmware was clean (290 publishes in 300 sec, 1Hz steady, no drift).  But TLS-specific code paths weren't re-validated against the corrected harness.  Cheap test: deploy `mqtt_bake_diag` (default = TLS) to `pi-pico-w-cp` and `lolin-s2-cp` sequentially, ~12 min total.  Worth doing for completeness but ~95% confident nothing new turns up given the heap data from earlier (now-recognized) runs was real and showed clean fragmentation.
2. **Run preflight on libraries/mqtt** after the 0.14.0 MQTTPublisher removal.  Test removal happened in the same commit but full preflight on the package wasn't re-checked.  `[VERIFIED: standalone tests pass — 177 tests, 95.46% cov]` but preflight gates on workspace coverage threshold.
3. **Negative tests** per `plans/workstreams/mqtt-negative-testing-suite.md`.  Highest-value test for surfacing the convergence-workstream defects: broker hard-kill at t=120, restart at t=150.  Should expose the recv-zero-swallowed defect immediately.  Mosquitto is currently running on the Mac (PID 23301) — to do the kill test:
   ```bash
   # In one shell:
   ps -p 23301  # confirm alive
   pkill -9 mosquitto
   # Wait 30s, then restart:
   mosquitto -c .scratch/mqtt-probe-config/mosquitto.conf -v > .scratch/mqtt-probe-config/mosquitto.log 2>&1 &
   ```
4. **Custom firmware native msgpack** — see Phase 2 not-yet-canonical bullet above.  Worth checking whether the strip is intentional before further footprint work.
5. **Holistic read of `~/circuitpython/pythonProject3/basefilesystem/lib/basefs/mqtt_client.py` end-to-end** against `chumicro_mqtt.client` — see convergence workstream.  Start there before touching code.

## Dead ends

A LOT of bad hypothesis-chasing in Phase 2.  These are recorded so future-me doesn't re-walk them:

- **PINGREQ-at-t=234 causes the freeze** — disproven by ka300 (keep_alive=300s, so only 2 PINGREQs during bake) showing same "freeze" at same wall-clock t=234.  Different ping schedules can't both cause the same per-time event.
- **TLS-specific mbedTLS rekey / session timer at 234s** — disproven by PLAIN bake showing same "freeze".  Not TLS-specific.
- **The 234-second wall-clock event has some specific cause** — disproven by Phase 2's harness clock-domain bug.  The "234s" wasn't a real event; it was the harness's miscount of when the bake started publishing (real start was 65 sec later than the harness thought).
- **CIRCUITPY mount FSKit wedge** when seeing two `/Volumes/CIRCUITPY*` mounts — disproven by user: two CP boards plugged in, both naturally mount as CIRCUITPY.  AGENTS.md's wedge note applies to the single-board case.  Burned 15 minutes on this; future me should `chumicro-workspace devices` *first* to see if multiple CP boards are present.
- **Parallel deploys to two different CIRCUITPY boards** — broke with `rsync failed: unexpected end of file` on at least one of the pair.  Root cause unconfirmed but suspect: deploy tool can't disambiguate which mount belongs to which serial port.  Stick to sequential deploys when multiple CP boards are plugged in.  Worth filing as a deploy-tool defect.
- **Deep-diving chumicro_mqtt defects while tracking the symptom of the freeze** — the defects I found (recv-zero swallowed, deadline ordering, no POLLERR/HUP) are real, but they weren't what caused the apparent freeze.  Don't deep-dive on library defects from probe symptoms before validating the probe is healthy.
- **`on_publish(packet_id)` callback signature** — wrong.  The contract is `on_publish(topic, payload_bytes)` per `chumicro_mqtt.client:609-612`.  TypeError surfaced this on first PUBACK.

## How to rebuild context fast

Read in this order:

- **This handoff** (just confirmed).
- **Commits 8bef7883 → d1a6d1a7** (`git --no-pager log --oneline 8bef7883^..d1a6d1a7`) — Phase 1's narrative + the two committed library changes.
- **`plans/workstreams/chumicro-mqtt-runner-cooperative-tick-convergence.md`** — the load-bearing follow-up.  Read the punch-list AND the "other strays" section; the deeper holistic read is the load-bearing task before code lands.
- **`plans/workstreams/mqtt-negative-testing-suite.md`** — paired test inventory.  Read after the convergence workstream so the test-against-fix relationships make sense.
- **`~/circuitpython/pythonProject3/basefilesystem/lib/basefs/mqtt_client.py`** — the multi-week-uptime reference impl.  Specifically `loop()` (line 476-558), `_read_socket()` (line 651-672), and the poll-mask juggling at lines 516-518 + 548-550.
- **`libraries/mqtt/src/chumicro_mqtt/client.py:872-876`** (the broken order: drain → read → check_deadlines → keepalive → drain) and **`:1042-1063`** (the recv-while-budget loop) and **`:977-994`** (the send-while-queue loop) and **`:1060-1061`** (the `got == 0` silent break).
- **`libraries/runner/src/chumicro_runner/core.py:386-387`** (the poll-event iterator discarded).
- **Memory entries** at `~/.claude/projects/-Users-chuxor-circuitpython-chumicro/memory/` — `feedback_use_chumicro_timing_always.md` + `feedback_two_sided_mqtt_gate.md` are the two new ones.
- **`.scratch/bake-diag-plain-board-v2.log`** — the clean PLAIN v2 run.  Proof that the chumicro stack itself runs 1Hz QoS 1 cleanly for 5 min on CP.
- **`.scratch/frag-iter-session-log.md`** — Phase 1's iteration log + the source-side-floor verdict.

Recent commits worth scanning:

```
git --no-pager log --oneline -10
```

## Gotchas

- **Custom Pi Pico W CP firmware** (`10.2.0-dirty`, on `/dev/cu.usbmodem112301`) seeds `supervisor.ticks_ms` near 2^29 - 65_536 at boot, so it wraps to 0 ~65 sec into boot, then runs 65_536 ms behind `time.monotonic` for the rest of the session.  This is deliberate — stress-tests the wrap path.  Any code mixing the two clocks in deadline math breaks; the bake harness was bitten by this and lost 2 hours.
- **Mosquitto** is still running as of write (PID 23301).  Listeners on 1883 (plain) + 8883 (TLS).  Cert at `.scratch/mqtt-probe-certs/`.  Anonymous auth.  Mosquitto config at `.scratch/mqtt-probe-config/mosquitto.conf`, log at `.scratch/mqtt-probe-config/mosquitto.log` (now 2.5 MB — may want to truncate).  *as of write — re-probe via `ps -p 23301` on resume.*
- **Two CIRCUITPY boards** plugged in.  `chumicro-workspace devices` lists 4 boards total.  Both CP boards naturally mount as `CIRCUITPY` + `CIRCUITPY 1` — this is NORMAL with two boards, NOT an FSKit wedge.  Don't run `reset-board` on the assumption it's wedged.
- **Sequential deploys only** when both CP boards are plugged in.  Parallel deploys race for the same mount and one of them fails with rsync EOF.
- **The bake projects** (`projects/mqtt_bake*` in workspace-template) are gitignored.  They live locally.  Re-verify by `ls /Users/chuxor/circuitpython/ChuMicro-Workspace-Template/projects/`.
- **`.scratch/mqtt_bake_mac_driver.py`** is the Mac driver.  Takes `--variant <name>` (matches the board's VARIANT constant) and `--client-suffix <chars>` (avoid argparse-collision flags like `-a`, use `_a`).
- **Pre-existing working-tree drift** (`.idea/chumicro.iml`, `workbench/deploy/*`, untracked `firmware.bin`) is from before this session.  Not load-bearing for the handoff; don't try to fix.
- **`time.monotonic_ns()` vs `time.monotonic()` vs `supervisor.ticks_ms` vs `chumicro_timing.ticks_ms`** — these are FOUR different clocks on CP.  Use `chumicro_timing.ticks_ms` exclusively in chumicro code AND test harnesses.  Memory entry covers this.
