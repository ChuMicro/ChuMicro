# Rudiment API-fitness review — timing, events, msgpack, config, kvstore, logging

Date: 2026-07-03
Scope: adversarial *design* review of six foundation libraries — is each the right library in its
current shape (not whether the code is correct). Breaking changes are free pre-publication
(Decision 0092), so every verdict below is actionable now.
Method: read each library's source + its ADRs, grepped every consumer across `libraries/`,
`demos/`, `webui/`, `scripts/`, and the sister repo `ChuMicro-Workspace-Template/` (read-only).
Import-heap numbers measured on the unix-port MicroPython at
`.tools/micropython-v1.26.0/.../micropython` — never a board.

---

## 1. timing — VERDICT: TOO-THIN (ship value-objects; do not add clocks)

**What it is.** `ticks_ms / ticks_add / ticks_diff` wrap arithmetic normalized to a 2**29 ms ring
(`src/chumicro_timing/ticks.py:12-18`, deliberately 29-bit so boards without big-int never
heap-allocate a long), plus a `Heartbeat` fixed-cadence poller
(`src/chumicro_timing/heartbeat.py:7-51`) and a test-only `FakeTicks` / `sleep_ms`
(`src/chumicro_timing/testing.py`). There is **no dedicated ADR** for timing — the leaf everything
builds on was never designed as a library, only extracted from adafruit_ticks.

**The core defect.** The library ships the *dangerous* primitives and makes every consumer
hand-assemble the *safe* pattern. The safe pattern is always the same triple — arm a deadline with
`ticks_add(ticks_ms(), delta)`, test it with `ticks_diff(deadline, now) <= 0`, and reduce several
with `min`-by-`ticks_diff` — and it is re-implemented, uncoordinated, in seven libraries. Because
the surface is free functions over plain ints, `now + delta` *looks* correct and is silently wrong
past the 29-bit wrap. That footgun is not hypothetical — it is already tripped in shipped code:

- `demos/http_server_roundtrip/app.py:59` — `deadline_ms = ticks_ms() + _DEMO_DEADLINE_MS` (raw `+`,
  not `ticks_add`).
- sister `projects/mqtt_bake_diag_plain/app.py:250` `connect_deadline = now_ms() + 10_000`, `:270`
  `+ 3_000`, `:293` `bake_started_ms + BAKE_DURATION_MS` — three raw-`+` deadlines in a file whose
  own header (lines 70-76) warns that mixing raw clocks with deadline math "produces silent
  multi-second offsets."

The `ticks_diff` ~3.1-day comparison window and 6.2-day wrap (`ticks.py:65-73`) are documented, but
documentation is the wrong mitigation for a primitive handed to every consumer: the type should make
the misuse unrepresentable.

### Hand-rolled consumer code a `Deadline` value-object would absorb

Arm-then-expire, duplicated (each is `ticks_add` to arm + `ticks_diff` to test):
- `requests/src/chumicro_requests/client.py:884` (arm) / `:793` (expire)
- `requests/src/chumicro_requests/generators.py:145` (arm) / `:190` (expire) / `:170`
  **remaining budget** `connect_budget_ms = ticks_diff(deadline_ms, ticks_ms())` → a `Deadline.remaining()`
- `sockets/src/chumicro_sockets/generators.py:135` (arm) / `:150` (expire)
- `http_server/src/chumicro_http_server/server.py:994` (arm) / `:306` (expire)
- `mqtt/src/chumicro_mqtt/client.py:1916-1917` (arm helper `_armed`) / `:1835,:1863,:1877,:1891` (expire)
- `websockets/src/chumicro_websockets/client.py:269-270,:540,:553` (arm) / `_session.py:901-924` (expire)
- `wifi/src/chumicro_wifi/service.py:229,:268` (arm) / `:172,:205,:243` (expire)

Earliest-of reduction (`min` of candidate deadlines by `ticks_diff`), hand-rolled **four** times with
identical structure — a `Deadline.earliest(*ds)` / `DeadlineSet`:
- `runner/src/chumicro_runner/core.py:822-847` (`_compute_timeout`, the wait-budget the whole reactor
  gates on — this is the "runner's next_deadline" arithmetic)
- `websockets/src/chumicro_websockets/_session.py:332-344` (`next_deadline`)
- `http_server/src/chumicro_http_server/server.py:942-951`
- `mqtt/src/chumicro_mqtt/client.py:1174-1188`

Stopwatch / elapsed (`start = ticks_ms(); ... ticks_diff(ticks_ms(), start)`), hand-rolled — a `Stopwatch`:
- `ntp/src/chumicro_ntp/core.py:401`, `http_server/examples/simple_server.py:73,92`,
  `mqtt/examples/telemetry.py:134-138`, `mqtt/examples/bench.py:201-204` (RTT),
  `demos/mqtt_pub_sub/app.py:60,112` (uptime).

Fixed-interval loops that duplicate `Heartbeat` but re-anchor by hand:
- `mqtt/examples/telemetry.py:162-165`, `requests/examples/periodic_get.py:86-87`, sister
  `projects/hello_world/app.py:24-29` (a phase-locked `next_tick` loop).

### Sketch of the better surface

Add value-objects that capture the arithmetic; keep the free functions as the substrate:

- `Deadline(delay_ms, ticks=None)` → `.expired(now_ms) -> bool`, `.remaining(now_ms) -> int`,
  `.restart(now_ms)`; classmethod-free construction arms via `ticks_add` internally so `now + delta`
  is never written by a caller. `Deadline.earliest(iterable) -> Deadline|None` folds the four
  min-reductions.
- `Stopwatch(ticks=None)` → `.start(now_ms)`, `.elapsed(now_ms) -> int`.
- (optional) `RateLimiter` / rename-align with `Heartbeat` so "fire every N ms" and "allow at most
  every N ms" are one named concept rather than re-anchored inline.

This absorbs the arm/expire/remaining/earliest/elapsed code above out of **seven** libraries and
removes the raw-`+` footgun class by construction. The runner's own periodic phase-preserve math
(`core.py:495-502`, Decision 0088) can stay in the runner — it is scheduler policy, not a timer.

### Adversarial NO — surfaces the owner floated that timing should *not* grow

- **64-bit monotonic emulation.** Rejected: it directly defeats the deliberate 29-bit-no-big-int
  design (`ticks.py:12-18`). A leaf that every library imports must not start heap-allocating longs
  on RP2040/SAMD.
- **RTC / calendar bridging.** Rejected here: wall-clock belongs to the `ntp` sibling
  (`ntp/src/chumicro_ntp/core.py`), not the sub-everything monotonic leaf. Coupling calendar time
  into the timer taxes every consumer that only needs ticks.
- **Sleep abstraction.** Rejected: async/blocking is banned on device; waiting is the runner's verb
  (`sleep_until` / `wait_for`, Decisions 0087/0091). The `sleep_ms` shim is correctly quarantined in
  `testing.py` — keep it there.
- **A full scheduler.** Rejected: the runner already owns periodic scheduling (Decisions 0080/0088).

Net: timing is *too-thin*, but the fix is one layer of value-objects, not clocks/calendars. It should
grow up-outward (safe wrappers over its own math), not up-inward (new time domains).

Secondary note (not load-bearing): six example trees each re-implement `_resolve_ticks_ms` +
`ticks_ms/add/diff` (`{sockets,websockets,ntp,http_server,requests,mqtt}/examples/helpers.py`). That
duplication is forced by the examples-can't-import-siblings rule (Decision 0013), not a timing-shape
defect — but it is more evidence the safe pattern wants a single owner.

---

## 2. events — VERDICT: WRONG-PRIMITIVE (speculative; delete or demote to an example)

`EventBus` is a bounded in-process pub/sub with deferred `check(now_ms)`/`handle(now_ms)` dispatch
(`src/chumicro_events/core.py:18-180`). It is competent code. It has **zero consumers.** Grepping
`chumicro_events` / `EventBus` across `libraries/`, `demos/`, `webui/`, `scripts/`, and the sister
repo returns only the library's own `tests/`, `examples/`, and `src/` — nothing else in the entire
ecosystem imports it.

Meanwhile the pattern EventBus proposes to replace is used everywhere and used *directly*: services
expose `on_state_change(cb)` (wifi) and `on_connect = cb` (mqtt) callbacks — the library's own
example `examples/wiring_services.py:33,45` documents both shapes as the status quo. Decision 0091
already added `Signal` + `wait_for` for one-time completions, and Decision 0089 explicitly rejects
speculative reactive verbs. A queued, drop-counting, topic-indexed bus is a heavier primitive than
any consumer has asked for, and it duplicates the runner's own `check/handle` service protocol
(`core.py:133-137`) one layer up with no adopter.

Verdict: this is API surface without demand on a substrate where every KB of flash/heap is taxed
fleet-wide. Recommend deleting the library (or demoting the bus to a runner example) until a real
consumer needs fan-out that direct callbacks + `Signal` cannot serve.

---

## 3. msgpack — VERDICT: RIGHT (right wire + persistence format)

`chumicro_msgpack` delegates to the native `msgpack` C module on CircuitPython and falls back to a
17 KB pure encoder (`_pure.py`, 470 lines) only where there is no native module
(`__init__.py:47-105`). It has real, load-bearing consumers on both persistence paths named in the
task: `config/src/chumicro_config/runtime.py:5` (`runtime_config.msgpack`) and
`kvstore/src/chumicro_kvstore/core.py:14`.

**Measured (unix-port MicroPython, not a board):** import heap 8,512 B for the pure module — one-time,
and **zero** on CP boards because they delegate to the built-in C module. A realistic flat config dict
packs to 68 B vs 114 B as JSON (~40% smaller); CPython proxy showed the same ratio (85 B vs 114 B).

Weighed against the alternatives for what actually gets serialized (flat config dicts and kvstore
dicts of scalars/strings/bytes):
- **JSON** — Decision 0030 §2 keeps it as opt-in; msgpack is default because it is 30-50% smaller with
  identical capability *and already shipped across all three runtimes*. Confirmed by the measurement.
- **plain struct rows** — wrong shape: the payloads are heterogeneous dicts with optional keys, not
  fixed records; struct would hand-roll a schema and lose cross-tool readability.
- **CBOR** — arguably a peer on size/spec, but is **not shipped natively on CircuitPython**, so it
  would force the pure encoder onto the one runtime where msgpack currently costs zero import heap.
  That single fact settles it. (CBOR is not evaluated in any ADR — a minor documentation gap, not a
  reason to switch.)

The trust-boundary contract (trusting decoder hardened against truncation/over-length/trailing/
recursion, Decision 0073) is the right scope for a leaf codec and is honored by both persistence
callers (`kvstore/core.py:161-173`, `config/runtime.py:26-36`). No change recommended.

---

## 4. config — VERDICT: RIGHT

`RuntimeConfig` is a thin flat-dotted-key wrapper (`src/chumicro_config/section.py:30-55`) plus
`load_section` / `try_load_section` typed-section factories (`section.py:63-142`) and a lazy on-device
loader (`runtime.py`). Six real consumers across the networking stack build their config objects
through it (`wifi`, `http_server` ×2, `mqtt` ×2 — grepped in `*/src/`). The shape matches the
deploy-time TOML→msgpack pipeline it reads (Decision 0036) and stays deliberately minimal — no schema
engine, no nesting — which is correct for a flat-key device config. Right shape.

---

## 5. kvstore — VERDICT: RIGHT

`KVStore` is a mapping-style persisted store over four runtime backends (CP NVM w/ CRC framing, MP
NVS, MP LittleFS, Memory) with an explicit commit lifecycle, dirty tracking, and
`commit_if_changed()` wear defense (`src/chumicro_kvstore/core.py:113-309`, Decision 0034). It is the
largest of the six, but the size is *earned*: it exists precisely to hide four genuinely different
substrates behind one API (0034 §context enumerates the SAMD21-256B-to-ESP32-8KB spread). The
dirty-flag + `commit_if_changed` skip-encode design is right for a per-tick schedule on raw flash.
One real consumer today (sister `projects/example_sensor/app.py`); the primitive is standard enough
that latent adoption is not a speculative-API concern the way events is. Right shape.

---

## 6. logging — VERDICT: RIGHT (mild overbuild flag on `BufferedHandler`)

`Logger` + `StreamHandler` + `BufferedHandler` (`src/chumicro_logging/core.py`) mirror the stdlib
logging shape every developer already knows, with the crash-safety contract a device logger needs
(handler faults counted, never raised — `core.py:141-145`). `BufferedHandler` is the one novel piece:
a runner-shaped `check/handle` handler that decouples emit from I/O (`core.py:213-308`). Like logging
overall it currently has **zero consumers** in any tree, so the buffered-drain machinery is unproven —
but unlike events, `Logger` is a universally-needed primitive with an obvious consumer (any app) and a
recognized shape, so this is latent-standard, not speculative-novel. Verdict: right shape; revisit
whether `BufferedHandler` earns its place if no consumer adopts the buffered path before publication.

---

## Summary table

| Library | Verdict | One-line basis |
|---|---|---|
| timing | **too-thin** | ships dangerous free-function primitives; 7 libraries hand-roll arm/expire/earliest/elapsed; raw-`+` footgun already tripped in demo + sister repo. Add `Deadline`/`Stopwatch` value-objects; do **not** add 64-bit clocks / RTC / sleep. |
| events | **wrong-primitive** | zero consumers anywhere; direct callbacks + `Signal` (0091) already serve the need; duplicates runner's check/handle. Delete or demote. |
| msgpack | **right** | real consumers on both persistence paths; ~40% smaller than JSON, 0 import heap on CP (native), CBOR loses on the CP-native fact. |
| config | **right** | thin flat-key wrapper + section factories; 6 real consumers; matches the TOML→msgpack pipeline. |
| kvstore | **right** | size earned by four-substrate hiding; dirty-flag/`commit_if_changed` correct for per-tick flash. |
| logging | **right** | stdlib-shaped, crash-safe; mild flag: `BufferedHandler` unadopted, re-check before publish. |
