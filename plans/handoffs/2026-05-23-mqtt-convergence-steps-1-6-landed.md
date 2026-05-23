# Handoff 2026-05-23 — MQTT convergence steps 1-6 landed + bake-validated; negative bakes + strays remain

## What this session was about

Resumed the 2026-05-23 MQTT bake-harness handoff with the user's explicit ask: "apply all known fixes here this session if possible including adhering to the problem with draining in a loop and not handing back off to the runner."

Phase 1 (early session): holistic end-to-end read of the reference impl `~/circuitpython/pythonProject3/basefilesystem/lib/basefs/mqtt_client.py` (1043 lines) against `libraries/mqtt/src/chumicro_mqtt/client.py` (1283), `_wire.py` (889), and `libraries/runner/src/chumicro_runner/core.py` (488).  Expanded the convergence workstream's 6-row defect table into a severity-tagged inventory (3 architectural + 4 HIGH + 5 MEDIUM + 5 LOW chumicro-improvements-to-keep + 7 strays).

Phase 2 (rest of session): landed all six convergence steps (1 recv-zero, 2 handle reorder, 3 send-timeout, 4 POLLERR/POLLHUP, 5 one-per-tick, 6 polish), plus the cross-library FakeSocket fix that unblocked step 1.  Bake-validated steps 1-6 cumulatively on Pi Pico W CP custom firmware (5-min PLAIN, 290 publishes / 290 PUBACKs / 0 gaps either direction / 0 leaks / 300010 ms).  Also expanded the negative-testing-suite workstream from 9 rows to a 26-test 5-category taxonomy (A1-E3) — the next big chunk of validation work, not run this session.

User noted at the start: **"theres still a lot to do"** — that's the operating principle.  Convergence is a multi-session arc; happy-path bake validation only proves the fixes don't break normal operation, not that they correctly handle the negative paths they were designed for.

## What's in flight

Working tree as of write:

- `.idea/chumicro.iml`, `workbench/deploy/src/chumicro_deploy/firmware.py`, `workbench/deploy/tests/test_flash_firmware.py` — pre-existing drift carried forward from before this session, unrelated.
- `firmware.bin` (untracked) — pre-existing, unrelated.

Local-only (gitignored, won't reach git):

- `.scratch/bake-steps3456-board.log`, `.scratch/bake-steps3456-mac.log` — the steps-1-6 cumulative-validation bake outputs.
- `.scratch/bake-postfix-board.log`, `.scratch/bake-postfix-mac.log` — the steps-1+2-only bake outputs from earlier in the session.
- `.scratch/mqtt_bake_mac_driver.py` — Mac-side driver, unchanged from prior session.
- `projects/mqtt_bake_diag_plain/` and siblings in workspace-template — bake harness, unchanged.

## What got done (committed)

Sixteen commits this session, oldest first:

- `1b723f82` — drop resolved msgpack-strip question from next-up.
- `8e045e4b` — expand mqtt-runner convergence workstream with full divergence inventory (3 architectural + 4 HIGH + 5 MEDIUM + 5 LOW + 7 strays).
- `5fe9182d` — **step 2**: reorder `handle()` to `_check_deadlines → _check_keepalive → _read_inbound → _drain_tx_queue`.  Closes HIGH-F (deadlines downstream of I/O) + MEDIUM-N (recv-first within tick).  [VERIFIED: 177 CPython tests / 95.46% cov / MP + CP green]
- `f91374fe` — **FakeSocket fix**: `recv_into` raises EAGAIN on empty queue; new `simulate_peer_close()` for FIN.  Cross-library prerequisite for step 1.  [VERIFIED: 979 tests across sockets / mqtt / websockets / requests / http_server]
- `bb702f64` — **step 1**: `recv_into == 0 ⇒ MQTTProtocolError ⇒ FAILED`.  Closes HIGH-D.  [VERIFIED: new regression test `test_peer_close_marks_failed` uses `simulate_peer_close()`]
- `1e4a6537` — workstream sequencing notes for steps 1+2.
- `8b415424` — `Runner.add_periodic` phase-slip investigation added to next-up (~3-8% drift on 1 Hz schedule; root cause hypothesis: `core.py:318` reschedules from now instead of from previous deadline).
- `00875f05` — retire the 2026-05-23 MQTT bake / defect-inventory handoff.
- `9555c5a8` — expand mqtt-negative-testing-suite workstream from 9 rows to a 5-category (A-E) 26-test taxonomy.
- `599a9615` — **step 5**: one `recv_into` per tick + one `send` per tick in `handle()`.  Closes MEDIUM-C.  `_drain_callback_markers` helper drains QoS 0 callback markers around the single send so the on_publish callback still fires in the same tick.  [VERIFIED: 178 CPython tests / 95% cov / MP + CP green]
- `ffeee534` — **step 3**: send-timeout via `_send_deadline_ticks` (arm on tx-queue-non-empty, re-arm on progress, clear on queue-empty), surfaced via `next_deadline`, checked in `_check_deadlines`.  New `send_timeout_seconds` constructor param (defaults to `ack_timeout_seconds`).  [VERIFIED: 180 CPython tests; 2 new regression tests for stuck-socket + steady-drip paths]
- `5bd6dca6` — **step 6 polish** (2 of 3): idempotent `disconnect()` (early-return on already-DISCONNECTED, skip DISCONNECT-on-FAILED), public `set_will()` (with `prefixed=False` escape hatch, takes-effect-on-next-CONNECT semantics).  Self-heal cost sandboxing deferred to next-up.
- `fa7f32df` — **step 4**: cross-library POLLERR/POLLHUP surfacing.  Runner's `wait()` inspects the ipoll iterator and dispatches to `service.io_error(now_ms, eventmask)` on matching service.  MQTTClient.io_error transitions to FAILED with the raw eventmask in `last_error`.  [VERIFIED: 5 runner-side + 2 mqtt-side regression tests]
- `cdaea8ac` — workstream + next-up updated to reflect steps 3-6 landed; self-heal sandboxing added to next-up.
- `084ae287` — README + guide reflect new public API (`set_will`, `send_timeout_seconds`, new per-syscall meaning of `recv_budget_per_tick`).
- `7c5bff6f` — bake-validation history table in the convergence workstream (pre-convergence baseline, steps 1+2, steps 1-6).

Total: 16 commits, all pushed to main.  4309 workspace tests pass (95% coverage) / MP + CP runtime sweeps green / workspace lint clean.

## Decisions made (not yet captured in ADRs)

These could be promoted to ADRs if the next session wants the formal record; for now they live in commit messages + workstream notes.

- **One I/O per tick, but multi-parse per tick.**  The reference impl does one recv + one parse + one send per loop iteration, but the reference's `loop()` fires continuously from `main`.  Chumicro's runner fires `handle()` only when SOMETHING is due — possibly 30 s away if the only deadline is keepalive.  So one-parse-per-tick would leave decoder-buffered packets undispatched for up to 30 s.  We chose to keep one `recv_into` + one `send` per tick (matches reference's I/O cadence and yields back to runner after every syscall) BUT loop the decoder dispatch through all buffered packets (CPU-bound, allocation-light, can't be stalled by runner cadence).  Bound on dispatches-per-tick is `recv_budget_per_tick / shortest-packet-size`, still bounded.  [HYPOTHESIS: cheapest test = run a 50 Hz publish burst from the Mac driver against a slow-CPU board and confirm tick latency stays under 50 ms.  D2 in the negative-testing-suite covers this.]
- **`_packet_count_that_must_send` discipline isn't needed.**  Reference uses this counter to suppress PINGREQ injection while a partial-send is in flight, preserving wire ordering.  Chumicro's `_partial_send`-resumes-first-and-returns pattern in `_drain_tx_queue` naturally serializes the partial remainder ahead of any new packet from `_check_keepalive` or `_check_deadlines`, so the invariant is satisfied without an explicit counter.  Documented in step 5's commit message.
- **`send_timeout_seconds` defaults to inherit `ack_timeout_seconds`.**  Single-knob deployments see the same wall-clock budget across both timeouts; sites with predictable bursts of unwritability (e.g. a slow uplink with 10 s flushes) opt in to a longer value explicitly.  Avoids adding a second timeout knob that 99% of users would never tune.
- **POLLERR/POLLHUP via opt-in `service.io_error` hook, not a base class.**  Duck-typed contract: services that want error notification expose `io_error(now_ms, eventmask)`; services that don't get no callback.  Matches the existing `io_socket` / `io_wants_read` / `io_wants_write` / `next_deadline` shape (also duck-typed, no abstract base).  Documented in step 4's commit message.
- **FakeSocket fix changed semantics, not API.**  The new `simulate_peer_close()` method is additive; the old `close()` still raises EBADF.  The breaking change is "empty queue raises EAGAIN instead of returning 0" — exactly one downstream test (`test_peer_close_completes_unknown_length_body` in chumicro_requests) relied on the old behaviour, and it was already encoding the same misconception the production silent-break encoded.  Fixed the test to use `simulate_peer_close()` explicitly.

## What was learned

Already in canonical homes (don't duplicate):

- The deadline-driven timeout pattern (arming/clearing/re-arming) is now used in five places in chumicro_mqtt (ack-timeout, PINGRESP, PUBLISH retry, keepalive, send-timeout).  It's a real reusable shape — single-threaded, no timer thread, deadline lives in service state + surfaces via `next_deadline` so the runner wakes by it.  [HYPOTHESIS: worth a pattern.md entry next time someone audits patterns.md.]  Not lifted this session.
- chumicro_requests has a `recv_into == 0 → feed_eof()` path that is correct against real sockets (the production code was always right; the test was working off the buggy FakeSocket contract).  The chumicro_requests audit didn't surface a production defect symmetric to the one chumicro_mqtt had; the convergence pattern is mqtt-specific in production.  Other libraries using FakeSocket weren't audited for the analogous defect — websockets in particular has its own recv-loop and may have the same silent-break shape; worth an audit pass.  [HYPOTHESIS: cheapest test = grep for `got == 0` in `libraries/websockets/src/chumicro_websockets/_session.py` and check whether it raises or silently breaks.]

Not yet in any canonical home (sits here):

- **chumicro_mqtt and chumicro_runner convergence is now mostly principal-defect-clean** against the multi-week-uptime reference impl.  What remains is the 7 strays from the workstream's "Other strays" section (tier-2 intact-allocation concern, `Runner.wait` tight-loop on no-deadlines, self-heal cost sandboxing, `disconnect()` idempotency edge cases beyond what was tested, etc.) and the negative-bake validation surface.  The latter is where the real bugs likely still hide — happy-path bakes can't see them.
- **The `Runner.add_periodic` phase-slip is hidden by sub-percent on most tasks but cumulative.**  Observed ~3-8% slow on a 1 Hz publish over 5 min.  Root cause at `libraries/runner/src/chumicro_runner/core.py:318` is the "reschedule from now" logic; the design tradeoff (phase-preserving vs catch-up-burst suppression) probably warrants a per-registration knob.  Tracked in next-up.

## Riskiest assumption

**That the happy-path bake validates the convergence.**  Steps 1-6 each target a *negative-path* defect (peer closes, ack times out, no POLLOUT, broker FIN, etc.), but the only validation run this session was a 5-min PLAIN bake with no induced failures.  That bake proves the fixes don't break normal operation — it does NOT prove they correctly handle the negative paths they were designed for.

[HYPOTHESIS: cheapest test = pick the broker-graceful-disconnect scenario (A2 in the negative-testing-suite workstream).  Mosquitto is already running, the bake harness is deployed.  Mid-bake, run `mosquitto_ctrl ... disconnect bake-plain-board` from the Mac side.  Expected: board sees `recv_into() == 0`, transitions to FAILED, self-heal succeeds within ~2 ticks.  If THAT works, the rest of the negative tests are likely tractable too.  If it doesn't, something fundamental about step 1's interaction with self-heal is wrong.]

## To re-research / verify next session

1. **A1 / A2 negative bake** (broker hard-kill + restart / broker graceful-disconnect).  Highest signal — exercises self-heal end-to-end against the cumulative steps-1-6 fix set.  Mosquitto is still running as of write — re-probe via `ps -p 23301` on resume.  Mac driver is at `.scratch/mqtt_bake_mac_driver.py`.  Bake project is `~/circuitpython/ChuMicro-Workspace-Template/projects/mqtt_bake_diag_plain/`.
2. **TLS-variant bake** (`projects/mqtt_bake_diag/` is the TLS default).  Confirms steps 1-6 also hold on the TLS path; ~5 min run.  The earlier-session handoff noted ~95% confidence nothing new turns up given the TLS path heap data from before — still worth running for completeness.
3. **chumicro_websockets recv-zero audit.**  `grep -rn "got == 0\|received_length == 0\|recv.*== 0" libraries/websockets/`.  If anywhere swallows the FIN like chumicro_mqtt did, fix symmetrically + add a `simulate_peer_close()`-based regression test.
4. **`Runner.add_periodic` phase-slip ADR.**  The fix at `core.py:318` is one-line (`ticks_add(entry.next_due_ms, entry.period_ms)`) but the tradeoff (catch-up bursts after stalls) is real for LED / UI tasks vs essential for sensing / metering.  Needs a per-registration knob.  Tracked in next-up; would benefit from an ADR.
5. **Implement [Decision 0081](../decisions/0081-non-blocking-connect-via-tick-driven-connector.md) — non-blocking connect via tick-driven connector.**  The ADR landed late this session (commit `e14ba6b0`).  Decision picks option (b): keep self-heal but break BOTH the initial connect AND the self-heal across ticks via a `SocketConnector` state machine in `chumicro_sockets`, consumed by `chumicro_mqtt.MQTTClient` via a new `AWAITING_TRANSPORT` state.  Per-runtime substrate caveats spelled out in the ADR (CPython + MP rp2 have true non-blocking TCP connect via EINPROGRESS; CP socketpool blocks per phase; MP TLS handshake blocks on most ports).  Implementation is multi-session: `chumicro_sockets` first (new factories + `SocketConnector` + per-runtime adapters), then `chumicro_mqtt` migration, then `chumicro_requests` / `chumicro_websockets` / `chumicro_http_server` migrations (mechanical once the connector lands).  Bake-validate against negative-bake A1 (broker hard-kill + restart) -- the connector's value is that self-heal doesn't stall the runner mid-reconnect.
6. **The 26-test negative-bake suite** (A1-E3 in `mqtt-negative-testing-suite.md`).  This is the BIG remaining work — happy-path bakes can't see the bugs these fixes were designed to catch.  A1 / A2 / B1 / B2 are the foundational ones; the rest are deeper edges and TLS-specific paths.  Will take multiple sessions.

## Bloat-trim opportunities surfaced this session

User raised the size/behavior mismatch at handoff time: chumicro_mqtt is ~2× the reference (2172 lines vs 1043) but had WORSE runner-friendliness on the connect path until Decision 0081 lands.  That's a priorities-inversion problem.  Concrete trim candidates:

- **Collapse `publish` / `publish_raw` (and `subscribe` / `subscribe_raw`, `unsubscribe` / `unsubscribe_raw`) into one method each with a `prefixed=True` kwarg.**  ~100 lines of `client.py` plus ~30 of docs + tests.  Same shape `set_will` already uses (prefixed=False opts out).  Tracked as a standalone next-up bullet.
- **`from_config` + sockets-factory plumbing** could move to a separate helper module — ~100 lines.
- The broader `/audit-library libraries/mqtt` pass (also in next-up) is the structured way to find the rest.

These are real wins but separate from Decision 0081.  Sequencing: Decision 0081 first (it's the runner-shape gap the user prioritised), then the bloat-trim passes.

**audit-embedded skill gap.**  User flagged 2026-05-23 that the publish/publish_raw split should have been caught by audit-embedded — method-count bloat costs flash bytecode + import-time class-dict RAM, both within audit-embedded's named focus.  Four prior audit-embedded passes on libraries/mqtt (commits `3444f9e1`, `061c5850`, `423cbc31`, `ddcf2b9f`) caught other real issues but missed this whole category.  **Skill fix landed late this session** (commit `9f17c24a`): SKILL.md §1 gains a wrapper-doubling / prefix-sugar bullet, Process step 4 grep list gains `def \w+_raw(` etc., field-reality.md gets the chumicro_mqtt incident documented.  What's left in next-up: re-pass audit-embedded across previously-audited libraries (sockets, websockets, requests, http_server, msgpack, runner, timing) with the new check — expect 1-3 wrapper-doubling matches per library based on the mqtt rate.

## Dead ends

- **Strict one-parse-per-tick (just one packet dispatched per tick) for step 5.**  Initial implementation broke 4 tests because chumicro's runner doesn't fire on a tight loop like the reference's `main` does — buffered packets would stall up to 30 s waiting for the next keepalive deadline.  Reverted to "one I/O per tick + multi-parse from buffered decoder" which is the right shape for chumicro's runner model.  Took ~10 min to diagnose the test failures and arrive at the corrected design.
- **Landing step 1 (recv-zero fix) without fixing FakeSocket first.**  57 tests broke because FakeSocket's `recv_into` returned 0 on empty queue (conflating FIN with no-data) — production code's silent break and FakeSocket's contract were two sides of the same misconception.  Diagnosis took ~5 min; FakeSocket fix took ~15 min including the test updates.  Total side-quest: ~30 min before step 1 could land.  Note for future similar cross-library defects: check whether the test fakes encode the same wrong contract before applying the production fix.
- **Treating multiple-CIRCUITPY mounts as an FSKit wedge.**  Two CP boards plugged in both naturally mount as CIRCUITPY + CIRCUITPY 1; that's NORMAL with two boards, not the wedge described in `docs/troubleshooting/`.  Was in last session's handoff as a gotcha; lifted to memory this session as `feedback_multiple_cp_boards_normal.md`.
- **Bake-validating recv-zero specifically against broker graceful disconnect.**  Decided not to do this in-session because pre-fix and post-fix both eventually transition to FAILED (pre-fix via the next publish's OSError, post-fix via direct FIN detection ~20 ms vs ~1 s).  The behavioural difference is latency-of-detection, not pass/fail.  Saving the negative-bake validation for the A1/A2 cycle, which is the right shape.

## How to rebuild context fast

Read in this order:

- **This handoff** (just confirmed).
- **`git --no-pager log --oneline -20`** — the full convergence commit chain, oldest first via `8e045e4b` → `7c5bff6f`.
- **`plans/workstreams/chumicro-mqtt-runner-cooperative-tick-convergence.md`** — the full divergence inventory, fix-sequencing notes (steps 1-6 LANDED tags with commit SHAs), bake-validation history table.  The "Other strays / improvements" section is the remaining design surface.
- **`plans/workstreams/mqtt-negative-testing-suite.md`** — the 26-test A1-E3 taxonomy.  This is where the next session's heaviest work lives.
- **`libraries/mqtt/src/chumicro_mqtt/client.py`** — the meat of the changes.  Key sections: `handle()` at 882-907 (new order), `_read_inbound` at 1041-1085 (one-recv-multi-parse), `_drain_tx_queue` at 962-1018 (one-send + callback drain), `_update_send_deadline` at 1020-1038, `_check_deadlines` at 1314-1361 (send-timeout branch), `io_error` at 803-818 (POLLERR/HUP hook), `set_will` at 521-557, `disconnect` at 489-518 (idempotent + state-aware).
- **`libraries/runner/src/chumicro_runner/core.py`** — `Runner.wait` at 391-454 (ipoll-iterator inspection + io_error dispatch), `_dispatch_io_error` at 456-490.
- **`libraries/sockets/src/chumicro_sockets/testing.py`** — FakeSocket recv_into at 117-156, new `simulate_peer_close` at 94-110.
- **Memory entries written this session**: `feedback_multiple_cp_boards_normal.md`, `project_pico_w_cp_custom_fw_msgpack_strip.md`, `project_pico_w_cp_custom_fw_ticks_wrap.md`.

Search terms for tracking down related context:

- `_send_deadline_ticks` — send-timeout machinery.
- `simulate_peer_close` — FakeSocket FIN simulation.
- `io_error` — POLLERR/POLLHUP service hook.
- `set_will` — public will setter.

## Gotchas

- **Mosquitto is still running as of write — re-probe via `ps -p 23301` on resume.**  Two listeners: PLAIN 1883, TLS 8883.  Cert at `.scratch/mqtt-probe-certs/`.  Anonymous auth.  Log at `.scratch/mqtt-probe-config/mosquitto.log` (was 2.5 MB at end of prior session; may want to truncate before next bake).
- **Pi Pico W CP custom firmware** (`10.2.0-dirty`, `/dev/cu.usbmodem112301`) seeds `supervisor.ticks_ms` near rollover.  Mixed-clock-domain arithmetic against this board produces silent 65_536 ms offsets.  Always go through `chumicro_timing.ticks`.  Memory entry: `project_pico_w_cp_custom_fw_ticks_wrap.md`.
- **Two CIRCUITPY boards plugged in** — `chumicro-workspace devices` lists 4 boards total.  Sequential deploys only (parallel races for the same mount).  Memory entry: `feedback_multiple_cp_boards_normal.md`.
- **Custom CP firmware accidentally strips native msgpack** (10.2.0-dirty).  `_pure.py` is on the import path.  User opted not to rebuild.  Memory entry: `project_pico_w_cp_custom_fw_msgpack_strip.md`.
- **Pre-existing working-tree drift** (`.idea/chumicro.iml`, `workbench/deploy/*`, untracked `firmware.bin`) is from before this session — carried from the prior handoff.  Not load-bearing for the handoff; don't try to fix.
- **`recv_budget_per_tick` semantics changed in step 5.**  Was "max bytes drained from the socket in one `handle()` call across multiple recv_into calls."  Is now "cap on the single per-tick `recv_into` call's nbytes."  Same effective per-tick bound, different mechanism.  Docs updated in commit `084ae287`.
- **`set_will` takes effect on next CONNECT, not in-flight.**  The current broker session already has the will from the original CONNECT.  Changing the will mid-session has no broker-side effect.  Documented in the guide.
- **The bake-validation history table in the convergence workstream** shows three rows (pre-convergence, steps 1+2, steps 1-6).  All three are happy-path bakes — they prove the fixes don't break normal operation.  None validate the negative paths the fixes were designed for.  The riskiest assumption note above repeats this.
