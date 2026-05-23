# Handoff 2026-05-23 — validate fragmentation gc.collect work on Pi Pico W CP (custom firmware)

## What this session was about

Continuation of the rp2-MP TLS-fragmentation hunt (prior handoff:
`2026-05-22-mqtt-tls-validated-pico-mp-fragmentation.md`).  The
prior session validated MQTT+TLS on 3/4 boards and identified Pi Pico
W MP as the holdout, with a Swiss-cheese heap pattern blocking the
TLS handshake's ~25 KB contiguous requirement.

This session started with `/audit-embedded chumicro_mqtt` — three
audit commits landed (chumicro_mqtt 0.13.0, commits `061c5850`,
`423cbc31`, `ddcf2b9f`, version bump `c08b015b`) — and then user
escalated to a 25-iteration exploration of fragmentation reduction
across the broader import chain.  The exploration landed as commit
`a99221b9` (+ lint follow-up `013f5988`, audit-embedded skill update
`93b95399`, next-up cleanup `99abcf26`).  Six strategic
`gc.collect()` placements across `chumicro_mqtt` / `chumicro_sockets` /
`chumicro_config` / `chumicro_runner` / `chumicro_timing` fixed the
Pi Pico W MP TLS handshake failure — `mqtt_tls_probe` TLS_NOVERIFY +
TLS_CA legs now succeed.  [VERIFIED: `chumicro-workspace deploy
mqtt_tls_probe --device pi-pico-w-mp --tail 60` produced
`PLAIN ROUND_TRIP` / `TLS_NOVERIFY ROUND_TRIP` / `TLS_CA ROUND_TRIP`
end-to-end; capture in `.scratch/pico-mp-mqtt-tls-post-exploration.log`]

User then requested validation on the CircuitPython side: "I put
custom firmware on circuit python pi pico w for testing too in case
circuit python has other issues."  That's the next session's work.

## What's in flight

Nothing in `libraries/` or `plans/` is uncommitted on the work itself.
Working-tree drift on `.idea/chumicro.iml`, `workbench/deploy/src/
chumicro_deploy/firmware.py`, `workbench/deploy/tests/test_flash_
firmware.py`, and the untracked `firmware.bin` are pre-existing and
unrelated to this session's work.

The prior handoff `plans/handoffs/2026-05-22-mqtt-tls-validated-
pico-mp-fragmentation.md` is still on disk.  The session-resume skill
directs deletion when the work lands, but the auto-mode classifier
blocked `git rm` on that file as "irreversible local destruction
of a file the agent did not create."  **The user needs to either
explicitly authorize the delete on resume, or move it manually.**

## What got done

Five commits landed since the prior session's `7b42cb41`:

- `061c5850` — audit-embedded mqtt: trim `__all__` to 9 names; demote codec helpers to `_wire`.
- `423cbc31` — audit-embedded mqtt: `Awaiting` class -> `_AWAIT_*` module-level strings.
- `ddcf2b9f` — audit-embedded mqtt: dissolve `InFlightTable` into a dict on `MQTTClient`.
- `c08b015b` — mqtt: bump 0.13.0 (post-audit version).
- `a99221b9` — heap fragmentation: `gc.collect()` at library-import boundaries (6 placements across 6 libraries; the exploration win).
- `013f5988` — lint follow-up (noqa pragmas on the new import-boundary blocks).
- `93b95399` — audit-embedded skill: add the fragmentation methodology + `gc.collect at import boundaries` field-reality section.
- `99abcf26` — next-up: clear the prior handoff pointer.

Six VERSIONs bumped in `a99221b9`: chumicro_mqtt 0.13.1, chumicro_sockets 0.6.5, chumicro_config 0.5.4, chumicro_runner 0.3.4, chumicro_timing 0.3.7.  (chumicro_msgpack was NOT bumped — its `gc.collect` placement was reverted as not measurably useful.)

The originally-failing TLS scenario on Pi Pico W MP:

| Leg | Pre-audit (handoff state) | Post-audit (0.13.0) | Post-exploration (0.13.1 + chain) |
|---|---|---|---|
| PLAIN | ✓ (133/19 ms) | ✓ | ✓ (140/28 ms) |
| TLS_NOVERIFY | ✗ ENOMEM | ✗ ENOMEM | **✓ (137/22 ms)** |
| TLS_CA | ✗ ENOMEM | ✗ ENOMEM | **✓ (137/22 ms)** |

Post-import `max_free_sz` on Pi Pico W MP: 4089 blocks → 6170 blocks (~+33 KB contiguous).
[VERIFIED: `.scratch/frag-iter-log.md` captures the 25-iteration sweep and final state]

## Decisions made (not yet captured in ADRs)

- **`gc.collect()` at module-import boundaries is a chumicro pattern**, not a hot-path anti-pattern.  AGENTS.md / `/audit-library`'s ban is explicitly about *hot paths* (tick / handle / per-message callbacks).  Module-import time is housekeeping.  Captured in the `audit-embedded` skill (§4 and §10) + `field-reality.md` ("gc.collect at import boundaries").  Not promoted to an ADR — pattern lives in the skill where future audits will find it.
- **The audit-embedded `InFlightTable` dissolution and the exploration's `gc.collect` placements are additive, not redundant.**  The audit dropped persistent-state class machinery (~16 KB contiguous recovered).  The exploration defragmented compile scratch (~33 KB more).  Different mechanisms.  Don't conflate them when explaining the win.
- **The exploration's structural changes (helper-function inlining, docstring trimming, method consolidation) net-negative and were reverted.**  Counter-intuitive: removing a long docstring made fragmentation *worse* by ~5 blocks (the freed string-block became a hole that small allocations scattered into).  Inlining a single-call helper saved -1 1-block but cost -8 `max_free_sz` blocks.  *Large contiguous allocations are protective; small scattered allocations fragment.*  Full table in `.scratch/frag-iter-log.md`.
- **mpy-cross frozen bytecode is deferred until the `.py`-side is as efficient as possible.**  User policy as of 2026-05-23: max out source-level efficiency first, then evaluate freezing.  Don't propose `prepare-mpy-cross` runs as the next RAM-saving lever until source-side per-change benches have plateaued.  mpy-cross is the standout untapped lever (~50-80 KB heap on Pi Pico W MP, RAM-neutral on fragmentation pattern), but only after `.py` source has captured its share.
- **Trade-off model for source changes (worked out this session): three categories.**  (A) **Strict wins** — reduce RAM *and* fragmentation: dead-code removal, allocation consolidation (one big buffer vs N small), pre-allocation vs per-call churn.  (B) **Net-negative trades** — less RAM, *more* fragmentation: removing coherent large allocations (docstrings, long string literals), inlining helpers into scattered call sites, replacing big methods with many small ones.  This is the "moving the bump under the rug" failure mode and the exploration confirmed it.  (C) **RAM-neutral, fragmentation-positive** — dissolving class machinery into dict storage (audit's `InFlightTable` removal), gc.collect placement.  The rule for next session: a change qualifies as a strict win only when both `max_free_sz` AND 1-block count improve or hold; if either degrades the change is a B-class trade and revert.

## What was learned

- **`gc.collect()` at the END of a library's `__init__.py` is load-bearing for downstream imports**, not redundant with the consumer's next `gc.collect`.  Subsequent imports' compile scratch lands amid this library's residue if it's not swept first.  Removing the iter-01 end-of-init placement alone dropped `max_free_sz` by 1117 blocks (~18 KB).  [VERIFIED: `.scratch/frag-iter-22-no-end-init-gc.log`]
- **`gc.collect()` BETWEEN submodule imports inside `__init__.py` also matters** when the package spans multiple `.py` files (e.g. `chumicro_mqtt._wire` then `chumicro_mqtt.client`).  Adds another ~15 KB on top of end-only.  [VERIFIED: iter 01 vs iter 02 in the log]
- **Adding `gc.collect()` to small libraries (`chumicro_config`, `chumicro_runner`, `chumicro_timing`) gave zero measurable benefit in the specific probe chain** (their compile scratch is too small).  Kept for cross-chain defensive symmetry — they could help different consumer import orders.
- **Module-import-time and runtime fragmentation are distinct concerns.**  The exploration captured the import-time win.  Runtime is already stable: 20-publish session against the broker held `max_free_sz` at 6170 throughout, with 1-blocks growing only +215 from boot to disconnect (no contiguous loss).  [VERIFIED: `.scratch/frag-iter-00-baseline.log` checkpoint deltas]
- **`micropython.mem_info(1)`'s `max_free_sz` is the load-bearing fragmentation metric**, not `gc.mem_free()`.  Total free can be 140 KB while max contiguous run is 8 KB — exactly the failure mode of the original probe.  Documented in audit-embedded §10.

## Riskiest assumption

That **structural per-change benches can find real additional wins
beyond the audit + gc.collect work**.  The exploration's category-B
result (5 of 5 structural-trim attempts went net-negative) was
strong evidence that source-level structural intuition lies for
fragmentation reduction.  The candidates listed in §5 below are
plausible — but they're plausible the same way the docstring trim
was plausible, and the docstring trim cost blocks.  The riskiest
belief in the queued next-session plan is that 5-15 KB of further
source-level RAM is recoverable without trading it back via
fragmentation.  If the first 2-3 per-change benches all land
net-negative or net-zero, that's the signal that source-side is
exhausted and mpy-cross becomes the live question after all (despite
the user's preference to defer it).

[HYPOTHESIS: cheapest test = pick the highest-payoff candidate from
§5 (MQTTClient instance attribute consolidation) and bench it
in-isolation.  Expected wins: 5-15 fewer 1-blocks per MQTTClient
instance, no `max_free_sz` regression at post_import.  If the
candidate lands category-A, source-side has more juice; if it lands
category-B with the same scatter pattern the audit saw, the exhaustion
signal fires earlier.]

**Secondary riskiest assumption (held over from prior handoff):**
that the `gc.collect()` placement pattern carries over cleanly from
MicroPython to CircuitPython.  Both runtimes ship `gc.collect()` and
both have the same auto-GC-only-on-pressure behavior, but CP's heap
layout, mbedTLS build, and module-import allocation patterns differ.
[HYPOTHESIS: cheapest test = deploy `frag_probe_runtime` to
`pi-pico-w-cp` (at `/dev/cu.usbmodem112301` per `devices.yml`) with
the current committed state.  CP's `micropython.mem_info(1)` does
not exist — use `gc.mem_alloc()` / `gc.mem_free()` plus a
`bytearray(N)` allocation probe at successive Ns (25_000, 16_384,
8_192) to find the contiguous floor at each checkpoint.]

## To re-research / verify next session

1. **Run `frag_probe_runtime` against `pi-pico-w-cp` with current
   committed state.**  Adapt the probe — `micropython.mem_info(1)`
   doesn't exist on CP.  Capture `gc.mem_alloc()` + `gc.mem_free()`
   at the same six checkpoints and a `bytearray(N)` allocation probe
   (try N = 25_000, 16_384, 8_192) at each to surface the fragmentation
   floor.  [HYPOTHESIS: cheapest test = `.scratch/frag-probe-cp-baseline.
   log` from a deploy run.]
2. **Run `mqtt_tls_probe` against `pi-pico-w-cp` with all three legs
   enabled.**  Confirm TLS_NOVERIFY + TLS_CA succeed.  Pi Pico W CP
   passed all three legs in the prior session (handoff table) — the
   gc.collect changes shouldn't regress that.  If they do, that's
   a CP-specific finding worth a separate workstream.
3. **Verify the custom firmware the user mentioned.**  The user said
   "I put custom firmware on circuit python pi pico w for testing too
   in case circuit python has other issues."  Confirm which board UID
   has the custom firmware and which CP version it reports
   (`chumicro-workspace devices` + a quick probe).  Devices.yml currently
   lists `pi-pico-w-cp` at firmware_version `10.2.0` with UID
   `E6614103E7174624`.
4. **Re-run `mqtt_tls_probe` against Lolin S2 MP + Lolin S2 CP**
   to confirm the gc.collect changes don't regress the 3 boards that
   were already passing.  Quick sanity check.
5. **Per-change benching pass — the priority next session.**  User
   explicitly: *"we should explore more per change benches in the next
   session."*  Treat each candidate below as its own bench cycle:
   apply → deploy → capture mem_info(1) → compare to baseline → re-run
   to confirm (±10 block noise) → keep iff both `max_free_sz` AND
   1-block count improve or hold (decision-rule category A above).
   Maintain a running table in `.scratch/frag-iter-NN-<slug>.log` +
   summary markdown.  Concrete candidates worth benching, in
   estimated-payoff order:

   - **MQTTClient instance attribute consolidation.**  `MQTTClient.
     __init__` writes ~30 `self._foo = value` attributes.  Each is a
     dict entry per instance, ~1 small allocation each.  Candidate:
     consolidate into a single `_state` dict / tuple / dataclass-like
     namespace.  Bench at `post_connect` after `client = MQTTClient(...)`.
     Estimated win 5-15 1-blocks per client instance; tradeoff is
     readability of `self._state["client_id"]` vs `self._client_id`.
   - **`_decoder_kwargs` storage shape.**  Stored on the MQTTClient
     instance only for `_attempt_self_heal` reconstruction.  Could
     hold construction-time params in a single small tuple instead of
     dict.  Bench: 1-block delta after `MQTTClient(...)`.
   - **PacketDecoder drain-state attributes.**  12 `self._drain_*`
     fields exist permanently but are all `None` / 0 when not draining.
     Could be a single drain-state tuple swapped in on tier-2/3 entry.
     Bench: 1-block count at `post_subscribe` (decoder allocated but
     idle).  Readability cost: drain-mode accessors get uglier.
   - **`chumicro_sockets` runtime-gated function tree.**  `tcp_client_socket`,
     `tls_client_socket`, `udp_socket` etc. each branch on
     `_runtime_name()` and lazy-import an adapter.  Could resolve the
     adapter ONCE at module load and assign module-level function
     references.  Bench: `post_import` `max_free_sz` + `post_connect`
     delta.  Risk: changes when adapter imports fire (`_adapters/cp`
     vs `_adapters/mp`), and the CP / MP build difference is a tested
     surface.
   - **`chumicro_msgpack._pure` mid-module gc.collect.**  407 lines.
     The mid-class break that worked in `_wire.py` (iter 12, +5 blocks)
     might apply here.  Bench: post_import after triggering a
     `load_runtime_config()` call.  Low payoff but cheap to try.
   - **WhenOversized class → module-level constants.**  Documented
     public API but Decision 0061 framed it as a cross-library
     contract.  3 string constants in a class body.  Audit declined
     to touch this in the first pass.  Bench against module-level
     constants with a class-attribute compatibility shim if API has
     to stay stable.  Risk: 21 external consumers (libraries +
     site-generated HTML) reference `WhenOversized.DROP_WITH_EVENT`.
   - **`MQTTPublisher` retirement.**  Documented public API, zero
     external usage (per audit).  Bench post_import after removing
     the class.  Tradeoff: removes a documented ergonomic affordance.
     If kept and unused, costs ~3-5 small allocations forever.

   Each is a candidate, not a recommendation.  Bench-first, decide-
   after.  The exploration's central lesson is that structural
   intuition lies — every candidate above could plausibly land in
   category A or B; the measurement is what tells you which.

6. **Look at `chumicro_runner.core` and `chumicro_websockets`** as
   broader RAM consumers worth a `/audit-embedded` pass once the
   per-change bench loop is established.  Both are large libraries
   (runner core.py 488 lines; websockets 1500+ lines across 6 files).
   Future audit-embedded passes can use the bench harness instead
   of static review for the structural-change calls.
6. **Decide on the broader chumicro_runner test-coverage gap.**
   The runner package is at 90.29% coverage; the gap is in
   `_SelectPollAdapter` + `Runner.wait`'s select.poll path, which
   tests exercise via `FakePoller`.  Pre-existing (not caused by this
   session); preflight is currently failing on this threshold.  Either
   add unit tests that exercise the real `_SelectPollAdapter`, lower
   the per-package threshold in `libraries/runner/pyproject.toml`, or
   document it as a known gap.  [VERIFIED: `git stash` of exploration
   changes still shows 90.29% — pre-existing]
7. **Audit the comment style of the audit-embedded skill additions
   for consistency** — the new bullet in §4 and the expanded §10 should
   match the existing tone.  Sanity re-read after the session-handoff
   ritual.

8. **Bench the existing kept changes individually** as a sanity-check
   on the audit + exploration's reported contributions.  The
   `frag-iter-log.md` table shows per-change deltas but they were
   measured cumulatively (each iter on top of the prior).  A fresh
   bench from PRE-AUDIT baseline against the FINAL state, isolating
   each change one-at-a-time, gives a defensible attribution.  Cheap
   to run from `git stash` + `checkout`-by-file.  Not load-bearing
   but useful for the per-change discipline the next session is
   building.

## Dead ends

The 25-iteration sweep produced a long list of things that didn't
work; full table in `.scratch/frag-iter-log.md`.  Notable highlights:

- **Inlining single-call helper functions (`_force_non_blocking`)
  and methods (`_parse_connack`):** -1 1-block but -8 `max_free_sz`
  blocks.  Net negative.  The structural-readability cost is real and
  the win is noise.  Don't re-attempt.
- **Trimming long docstrings:** -5 `max_free_sz` blocks (worse, not
  better).  Counter-intuitive but reproducible — removing a large
  contiguous string allocation creates a hole that small allocations
  scatter into, *increasing* fragmentation.  Big strings are
  protective.
- **`gc.collect()` at the START of `chumicro_mqtt/__init__.py`:**
  redundant with the probe's own pre-import sweep.  No measurable
  benefit.
- **`gc.collect()` mid-`client.py` (between helper classes and
  `MQTTClient`):** -17 blocks.  The `import gc` statement mid-file
  disrupts the class body's heap layout.
- **Double `gc.collect()` at each kept site:** no improvement.  MP's
  single-pass collector is already effective for compile scratch.
- **Eager `from chumicro_timing import ticks` in client.py:** -11
  blocks.  The lazy DI-fallback path is actually fine.
- **`gc.collect()` in small libraries with no downstream consumer
  imports** (chumicro_runner is the last import in the probe chain):
  no measurable benefit (kept for cross-chain symmetry but don't
  expect specific measurement gains in this chain).
- **`gc.collect()` mid-class-body in `_wire.py`** (before PacketDecoder):
  +5 blocks — kept but very marginal.  Re-verify in CP context; it
  may not transfer.
- **CHU027 fired on identical one-line cross-reference comments
  across config / runner / timing**; resolved by varying the wording
  slightly.  Beware: if all three get re-edited to the same text
  again, CHU027 will resurface.

## How to rebuild context fast

Read in this order:

- **`.scratch/frag-iter-log.md`** — the 25-iteration sweep table
  with `max_free_sz` and 1-block deltas per change.  This is the
  primary record of what was tried and what worked.
- **Commit `a99221b9`'s body** — the recommendation set with the
  measured impact per placement and the broader story.
- **`.github/skills/audit-embedded/field-reality.md`** — "gc.collect
  at import boundaries" section has the full methodology + things
  that didn't work, written for cold readers.
- **`libraries/mqtt/src/chumicro_mqtt/__init__.py`** — the new docstring
  explains the load-bearing rationale (compile scratch, auto-GC-only-
  on-pressure, end-of-init protects downstream imports).
- **`projects/frag_probe_runtime/app.py`** (workspace-template) — the
  measurement harness.  Reference for the CP-side variant.
- **`projects/mqtt_tls_probe/app.py`** (workspace-template) — the
  end-to-end TLS-against-mosquitto probe.  Should run as-is on CP.

Recent commits worth scanning:

```
git --no-pager log --oneline -10
```

The chunk from `a99221b9` to `99abcf26` is this session's exploration.

## Gotchas

- **The pre-existing handoff file `plans/handoffs/2026-05-22-mqtt-tls-validated-pico-mp-fragmentation.md`
  is still on disk.**  The session-resume skill directs deletion when
  the work lands; the auto-mode classifier blocked `git rm` on it.
  Either authorize the delete on resume, move it manually, or accept
  it sitting there.
- **`pi-pico-w-cp` is at `/dev/cu.usbmodem112301`** as of session end —
  IPs and ports shift on reconnect, re-probe via `chumicro-workspace
  devices` on resume.  All four boards in `devices.yml` had been
  healthy in the prior session's matrix — the CP board running the
  user's custom firmware should still be there but **re-verify the
  UID and firmware_version match what devices.yml records.**
- **Mosquitto broker:** still running as of session end (PID 23301,
  `mosquitto -c .scratch/mqtt-probe-config/mosquitto.conf -v >
  .scratch/mqtt-probe-config/mosquitto.log 2>&1 &`).  Listeners on
  1883 (plain) and 8883 (TLS).  If stopped, restart from the same
  command.  Cert validity goes to 2099-12-31.
- **mDNS hostname `charless-macbook-pro.local`** is the broker host
  for TLS legs.  `scutil --get LocalHostName` to re-confirm; current
  value is `Charless-MacBook-Pro` (Bonjour is case-insensitive).
- **Pre-existing runner coverage failure (90.29%)** is unrelated to
  this session's work.  `git stash` of exploration changes still shows
  90.29%.  Don't try to "fix" it by reverting the exploration — that
  would just remove the fragmentation fix without addressing the gap
  in `_SelectPollAdapter` tests.
- **CHU027 + the gc.collect cross-reference comments:**  the comments
  in `chumicro_config/__init__.py:42`, `chumicro_runner/__init__.py:13`,
  `chumicro_timing/__init__.py:13` are intentionally slightly different
  wordings to avoid duplicate-comment detection.  Don't homogenize them.
- **The exploration's `.scratch/frag-iter-*.log` files are throwaway
  records** of individual iterations.  `frag-iter-log.md` is the
  canonical summary.  Don't bother grepping all 25 logs — the table
  has the deltas already extracted.
- **`projects/frag_probe_runtime/app.py` and `projects/frag_probe/
  app.py` are both in workspace-template** as research scaffolding.
  They're gitignored (workspace-template's `projects/` is gitignored).
  If the workspace-template gets pushed at some point, these stay local.
- **`micropython.mem_info(1)` does not exist on CircuitPython.**  The
  CP-side probe will need a different fragmentation-detection strategy
  (suggested in §1 of "To re-research": `bytearray(N)` allocation
  probes at successive Ns to find the contiguous floor).
