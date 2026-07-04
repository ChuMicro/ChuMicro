# Greenfield core redesign study — timing, runner, sockets, events, msgpack (2026-07-03)

> Commissioned question, verbatim: *"if we re-wrote these core libraries from scratch with new
> designs, how would it benefit this mono repo and excel our work even further"* — think outside
> the box.  mqtt (plus websockets / requests) is the stress-test consumer every candidate design
> is checked against, not a redesign target.  ADRs are treated as evidence of past reasoning, not
> law.  Binding constraints: 264 KB-class boards (measured free after boot on Pico W: MP 201,360 B,
> CP 126,288 B), one source tree serving CircuitPython + MicroPython + CPython, no `async`/`await`
> on device code, and Decision 0092 (never published — migration means editing this repo only).

## Method and evidence base

Read for this study: `AGENTS.md` (embedded rubric); Decisions 0014, 0031, 0043, 0073, 0080, 0081,
0087, 0088, 0089, 0091, 0092, 0093, 0094; the 2026-06-13 deep code review and generator-io final
review; full source of `timing`, `runner` (core + generator machinery), `sockets` (`__init__`,
`_connector`, `generators`, the MP adapter in full, CP/CPython adapters via the review record),
`events`, `msgpack`; the mqtt client's reactor surface (`check` / `io_*` / `next_deadline` /
`handle` / self-heal / `_advance_connector`) and `sockets_factory`; `requests/generators.py`;
the websockets `_session` wait shapes; `demos/mqtt_pub_sub/app.py`; heap budgets in
`target-runtimes.toml`; and the bake-incident trail in `git log` (TLS-on-silicon fixes, the
six-unwrap wrapper hunt, M49 silent generator death, the SUBACK marker race, Decision 0094).

Deploy-stripped sizes, measured with the real minifier
(`chumicro_deploy.source_minify.strip_source` over each `src/` tree, 2026-07-03):

| library | stripped bytes | | library | stripped bytes |
|---|---|---|---|---|
| timing | 3,492 | | sockets | 43,346 |
| runner | 22,160 | | mqtt | 60,278 |
| events | 4,471 | | websockets | 78,636 |
| msgpack | 10,221 | | requests | 58,463 |

## What the field evidence says the current designs made hard

The incident ledger, grouped by the design that produced it:

1. **Runner dispatch surface grew by retrofit.** Fault isolation (RUN-1, CRITICAL), `io_error`
   isolation (G1), re-entrancy guarding, `handle.error` death recording (M49 — a demo generator
   died on its first text frame and the only symptom was a marker timeout), and the
   `_dispatch_io_error` live-list mutation fix (RUN-2) were all added after bakes or reviews found
   the hole.  Root cause each time: the runner has *two* dispatch lanes (tick's handler fire,
   wait's `io_error` hook) and *seven* duck-typed service attributes, so every safety property had
   to be built twice and audited per attribute.
2. **The sockets stack maintains two connect implementations per runtime.** Synchronous factories
   (`connect_tcp` / `connect_tls`) and tick-driven connectors (`_MpConnector` etc.) encode the same
   DNS → TCP → TLS flow twice.  SOCK-2 (TLS `wrap_socket` on a non-blocking socket in the connector
   path while the listener path flips blocking first) is exactly the divergence class parallel
   implementations breed; the 2026-07-03 TLS-on-silicon commit paid the bake cost.
3. **The adapter wrapper's `.sock` convention produced a bug hunt.** Six producer-side unwraps
   were "audited into existence the hard way" before commit `a298db15` moved the unwrap to the one
   consumer (`Runner._pollable_of`).  The wrapper itself is forced by real substrate divergence
   (MP `readinto` polyfill, EAGAIN-on-`None` normalization), but the convention leaked for months.
4. **Wait tokens are re-invented per library.** Seven private shapes implementing the same
   duck-typed protocol: `_ReadWait` / `_WriteWait` (`sockets/generators.py`), `_NextTickWait`
   (`runner/_generator.py`), `_DeadlineWait` (`runner/generators.py`), `_ReadDeadlineWait`
   (`requests/generators.py`), `_InboundWait` twice (`mqtt/client.py:93`,
   `websockets/_session.py:130`).  Each is small; the protocol they encode lives in six
   docstrings that must not drift.
5. **Deadline bookkeeping is hand-rolled at every site.** `MQTTClient.next_deadline` runs three
   None-aware min-scans plus a keepalive compare; `Runner._compute_timeout` re-implements the same
   scan; `wait_for` re-implements timeout expiry; `sockets.generators.connect` threads a `ticks`
   object solely to do deadline arithmetic; RUN-3 (connector fed a literal `tick(0)`) is what a
   missing shared idiom looks like when it fails.
6. **The factory plumbing drifted into three contracts** (M77) until Decision 0093 pinned one —
   but the five local copies remain (`mqtt` 46 + `websockets` 53 + `http_server` 53 + `requests`
   30 + `ntp` 18 = 200 lines) and each re-derives tcp-vs-tls routing that `SocketConnector`
   already unifies internally (`SocketConnector(host, port, tls=..., context=...)`).
7. **events has zero consumers.** `grep -rln chumicro_events libraries demos workbench support
   scripts` outside its own tree returns nothing.  The demos wire callbacks directly
   (`wifi.on_state_change(on_wifi_state)`); generator flows use Decision 0091's `Signal`.
8. **What was *not* hard — say it plainly.** The ticks ring arithmetic has survived every bake;
   the sender-controlled-allocation trust boundaries (msgpack, MQTT remaining-length, WS frames,
   HTTP bodies) were audited genuinely defended; the read-on-wait `io_*` model caught the
   between-tick `publish()` case its watch/unwatch alternative provably misses; and the generator
   substrate collapsed the 80-line `EchoService` to 7 lines as promised.

---

## 1. timing — is an adafruit_ticks copy the right core?

### The doubt, examined

`ticks.py` is 73 lines: `ticks_ms` / `ticks_add` / `ticks_diff` over a 2^29 ring.  The ring size
is not incidental — it matches CP's `supervisor.ticks_ms` wrap and keeps every add/diff result
under 2^30 so boards without big-int support never heap-allocate a long.  `Heartbeat` (51 lines)
is orphaned: the runner inlines its own `next_due_ms` gating (Decision 0014's "runner creates an
internal Heartbeat" drifted out of the code), and production consumers are zero (one example, one
functional test).

Should deadlines / rate-limits / schedules be their own objects that runner and sockets consume
natively?  Half yes.  The **representation** is already right: a deadline as a plain `int` in the
ticks domain is the RAM-optimal form — mqtt keeps one int per in-flight publish
(`InFlightPublish.deadline_ticks`); an object per deadline would add a heap allocation and an
attribute dereference to every min-scan on the hot path, violating the steady-state-zero-alloc
rule for nothing.  What is missing is not objectness but **shared idioms and a shared wait
vocabulary**.  The generator layer *already* pays for wait objects (they are cached and reused, so
they are allocation-free steady-state) — those are the places where a deadline-as-object earns
its keep, and today each library builds its own.

### From-scratch API

`ticks.py` unchanged.  `heartbeat.py` deleted.  New surface (~110 lines total):

```python
# chumicro_timing — additions
def earliest(a: int | None, b: int | None) -> int | None:
    """None-aware wrap-safe min of two absolute ticks."""
    # the 4-line pattern hand-rolled today in MQTTClient.next_deadline (x4)
    # and Runner._compute_timeout (x2)

class Rate:                       # absorbs Heartbeat + Decision-0088 anchoring
    def __init__(self, period_ms: int, *, preserve_phase: bool = False): ...
    def due(self, now_ms: int) -> bool: ...        # advances per anchoring mode
    def reset(self, now_ms: int) -> None: ...
    def next_deadline(self, now_ms: int) -> int | None: ...   # wait protocol

class Deadline:                   # a wait token: yieldable, runner-readable
    @classmethod
    def after(cls, delay_ms: int, *, now_ms: int | None = None) -> "Deadline": ...
    def expired(self, now_ms: int) -> bool: ...
    def next_deadline(self, now_ms: int) -> int | None: ...

class ReadWait:                   # io_socket + io_wants_read (+ optional deadline)
    def __init__(self, sock: object, *, deadline_ms: int | None = None): ...
class WriteWait: ...              # io_socket + io_wants_write
class Signal: ...                 # moves here from chumicro_runner.generators
```

The load-bearing move: **timing owns the fleet's wait vocabulary.**  Timing is the dependency
floor — runner, sockets, and every networking library already import it, so hoisting the token
shapes here adds zero deploy weight and zero new dependency edges (the same cannot be said of
runner or sockets as the home).  Time-waits and io-waits are one duck-typed protocol the reactor
reads; today that protocol has no owner, only six docstring copies.

### What it buys / breaks / costs

- **Buys:** deletes the seven private wait shapes (~100 source lines, and — the real prize — the
  drift class across six files); deletes both hand-rolled min-scan idioms; gives Decision 0088's
  phase math one home (`Rate`) instead of inline arithmetic in `Runner.tick`; kills the
  RUN-3-class bug shape (deadline arithmetic without a ticks source) because `Deadline.after`
  owns it.  timing grows from 3.5 KB to ≈ 4.5 KB stripped; the fleet sheds slightly more than it
  gains.
- **Breaks:** `Heartbeat` (near-zero consumers), `chumicro_runner.generators.Signal` import path,
  every private wait-shape site (mechanical edits in 6 files).  All in-repo, one commit each per
  Decision 0092.
- **Confronts Decision 0093's local-copy doctrine honestly:** 0093 kept factory copies local to
  keep deploy graphs per-library.  That reasoning does not transfer here — timing rides every
  deploy already, so this hoist has no graph cost.  Copies-stay-copies was right for factories
  and is wrong for wait tokens.

**Verdict: the ticks core is right — rewriting it would be churn.  The library's *scope* is
wrong: too small.  Extend, don't rewrite.**

---

## 2. runner — is generator-yield the right cooperation primitive?

### Alternatives, taken seriously

- **Explicit frame scheduler** (services as state machines polled for next-wake): this is what
  `check`/`handle` already is.  The 80-line `EchoService` demo is the recorded cost of forcing
  sequential flows into it; Decision 0087 measured the collapse to 7 lines.  No new information
  since favors going back.
- **`async`/`await` revisit:** the CP compiler evidence stands (`await` emits
  `__await__`-dispatch + a fresh generator per await on CP — one heap allocation per tick in a
  recv loop; `yield from` is one bytecode on both device runtimes).  Under the 264 KB constraint
  this is not a style choice.  Generators win on the numbers.
- **Event-driven readiness dispatch (0080's "Model 2"):** poll results route straight to the
  owning service, `check` retires for socket services.  The win is skipping N−1 `check` calls per
  wake — with 3–10 registered services, tens of microseconds.  The costs are concrete: (i) two
  dispatch paths again (timer vs readiness) — the exact shape that made RUN-1/G1 a two-part fix;
  (ii) the stress-test consumer says no: `MQTTClient.handle` runs a *documented, bake-tuned
  order* (deadlines → read → drain, so a wedged recv can't mask timeout detection and the PUBACK
  queued by the read drains the same tick).  Readiness dispatch decomposes that into
  `on_readable` / `on_writable` / `on_deadline` entry points and surrenders intra-tick ordering —
  more surface, worse guarantees, and the SUBACK-race class gets a new home; (iii) app-queued
  work between ticks (the `publish()` case in 0080) still forces a full interest re-read before
  every sleep, so Model 2 keeps Model 1's scan *and* adds routing.  Rejected on evidence, not
  taste.
- **Capability handles** (runner hands each service a handle through which it requests I/O and
  timers): inverts ownership so the runner allocates per-service state, and breaks the property
  the fleet is built on — services never import the runner (Decision 0014's duck typing is what
  lets `MQTTClient` run under a bare `while True: client.handle(ticks_ms())` loop with a BYOS
  socket).  Rejected.
- **One reactor owning all sockets:** cross-cutting section below.

**The generator-yield substrate and the reactive `check`/`handle` core are both right.**  The
two-shape model is real conceptual overhead, but each shape's alternative was tried or measured
and lost.  What the incident ledger indicts is not the primitive — it is the *contract width*.

### From-scratch contract (v2): same architecture, half the surface

```python
# Service duck contract v2 — four attributes, one dispatch lane
check(now_ms) -> bool
handle(now_ms) -> None
io_socket   -> pollable | None      # unchanged; runner still owns the .sock unwrap
io_interest -> int                  # POLL_READ | POLL_WRITE bitmask
                                    # replaces io_wants_read + io_wants_write
next_deadline(now_ms) -> int | None # unchanged, optional
# io_error retired: wait() records the error mask on the entry and lets the
# normal tick dispatch deliver it (service reads entry-supplied mask, or for
# generators the wrapper throws on its next handle()).  One dispatch lane,
# one isolation wrapper, one thing to audit.
```

- `io_interest` halves the per-service getattr count in `_sync_poll_set` (runs on **every**
  `wait`), and services already think in masks — mqtt's three boolean properties each re-derive
  state that one bitmask property expresses directly.
- Folding `io_error` into the tick lane makes G1-class asymmetric-isolation bugs structurally
  impossible: there is only one place a service exception can surface, and it is already wrapped.
  It also deletes `_dispatch_io_error`'s identity-matching walk (the RUN-2 mutation hazard site).
- Keep: two-phase batch-fire, read-on-wait, the linear min-scan (see deadline-wheel rejection),
  `run_until`, `add_generator`, `handle.error`, `preserve_phase` (delegated to `timing.Rate`).

Estimated delta: `core.py` 864 → ≈ 700 lines; each networking library sheds ~15–25 lines of
boolean-property and `io_error` plumbing; runner stripped 22.2 KB → ≈ 19 KB.  Breaks every
`io_*` implementor (5 libraries + demos + ~3.4 K runner test lines touched in part) — a
mechanical, greppable migration, but a real-board bake matrix is mandatory (this is orchestration
code; unit green is not sufficient per the standing rule).

**Verdict: do not re-architect.  A contract-slim pass is worth it only if it rides the same
migration wave as the sockets and timing changes; as a standalone rewrite it is churn.**

---

## 3. sockets — collapse the connector/factory/adapter stack?

### Where the stack actually is

Six layers: 12 public callables in `__all__` → `_get_adapter()` runtime dispatch → three adapter
modules (cp 469 / cpython 439 / mp 697 lines) with wrapper classes → `SocketConnector` base +
three per-runtime connector subclasses → `generators.py` helpers → five per-consumer
`sockets_factory` copies + `from_config` classmethods.  43.3 KB stripped — the largest core
library, twice the runner.

### What collapses, what stays

**Collapse 1 — one connect implementation per runtime.**  The synchronous factories duplicate the
connectors' DNS → TCP → TLS flow.  From scratch, the connector is the only state machine and the
synchronous form is a driver:

```python
def connector(host, port, *, tls=False, context=None, radio=None) -> SocketConnector
def connect_now(host, port, *, tls=False, context=None, radio=None,
                timeout_ms=None) -> Socket
    # drives connector() to terminal inline; poll-sleeps between phases.
    # REPL / scripts / pre-loop main keep their one-call form.
```

Deletes `connect_tcp` / `connect_tls` from every adapter (~150 lines across three) and — the real
win — deletes the divergence class that produced SOCK-2 (the two paths handled `wrap_socket`
blocking-mode differently until a silicon bake caught it).  One path, one bake matrix.

**Collapse 2 — one connect entry point, `tls` as a parameter.**  Decision 0031 §3 rejected an
overloaded `ssl=False|True|context` argument, and that was right for a 3-types-in-1 flag.  But the
internal layer (`SocketConnector(host, port, tls=..., context=...)`) and the ecosystem's own
factory contract (Decision 0093: `(host, port, use_tls)`) both settled on tls-as-parameter — the
public sibling split now contradicts the two contracts everyone actually codes against.
`connector(host, port, tls=..., context=...)` + `listener(...)` + `udp(...)` shrinks the public
surface from 12 callables to ~8 (the four `ssl_context_*` helpers and `set_default_ca_bundle`
stay; they encode measured per-runtime trust behavior that must not move).

**Collapse 3 — the consumer factory copies shrink or vanish.**  Each copy's tcp-vs-tls routing
disappears into the single entry point; mqtt's becomes:

```python
def chumicro_sockets_connector_factory(config, *, radio=None, ssl_context=None):
    _require(config, "mqtt.broker.host", "mqtt.broker.port")
    host, port = config["mqtt.broker.host"], config["mqtt.broker.port"]
    def factory():
        from chumicro_sockets import connector                # lazy, 0062-guarded
        return connector(host, port, tls=ssl_context is not None,
                         context=ssl_context, radio=radio)
    return factory
```

~12 lines instead of 46; fleet-wide the 200 copy lines drop to ~70.  The copies stay local
(Decision 0093's graph reasoning holds); they just stop carrying routing logic that can drift.

**Stays — the wrapper objects and the runner-side unwrap.**  I pressure-tested the radical
alternative: adapters return *native* sockets and the divergences move to per-runtime free
functions (`sockets.recv_into(sock, buf)`).  It makes every `io_socket` natively pollable and
deletes the `.sock` convention — but it turns every recv/send call site in five consumer
libraries into a module-function call with dispatch overhead on the hottest paths, and the MP
EAGAIN-on-`None` normalization then has to be *remembered* at N call sites instead of enforced at
one wrapper.  The six-unwrap incident was real, but its fix (unwrap at the single consumer,
`core.py:_pollable_of`) already closed the bug class.  Wrappers stay.

**Stays — the connector's runner-contract surface** (`check`/`handle`/`io_*`/`next_deadline`/
`cancel`), which is what lets mqtt drive it, `generators.connect` yield it, and `Runner.add`
register it raw.  This triple-consumability is the stack's best property.

### What it buys / breaks

- **Buys:** sockets 43.3 KB → ≈ 34 KB stripped; one connect state machine per runtime (SOCK-2
  class gone); public callables 12 → 8; consumer copies −130 lines; the factories'
  `test_factories*` / connector test split (≈ 4.6 K test lines total in sockets) consolidates,
  plausibly enough to lower the sockets CP heap override (160 K today) — treat that as a
  hypothesis to measure, not a claim.
- **Breaks:** every networking library's transport wiring, all sockets tests, four demos, ADR
  0031 §2–§3 edited in place, docs.  This is the widest blast radius of the five — and the only
  one whose payoff (deleting a proven divergence-bug factory) compounds with every future bake.

**Verdict: yes — this is the rewrite worth doing.**

---

## 4. events — does it deserve to exist?

No — not as shipped.  The evidence is unambiguous: zero consumers across libraries, demos,
workbench, support, and scripts after ~2.5 months in tree; the demos solve its stated problem
(wifi-state → app handler) with direct callbacks; Decision 0091's `Signal` covers the
callback-to-generator bridge; and the runner's own history already removed an event-bus layer
once (Decision 0014's rejected alternatives — this is the second time the ecosystem has told us
the same thing).  Meanwhile it costs what every library costs forever: 518 test lines across
three runtime lanes, a VERSION/audit/docs surface, preflight minutes, and a README row implying
it is load-bearing.

The one future consumer on record — `chumicro-presence` (Decision 0042 §167-168) — is flagged in
`plans/open-questions.md` as a stale, unaudited sketch that must be re-derived before anything
builds on it.  Carrying a live library against a suspect sketch is backwards; Decision 0092 makes
delete-and-revive nearly free (git preserves the implementation; the drop-oldest deque and
snapshot-dispatch subtleties survive in history and in this study's record).

Design note if it is ever revived: revive it as a *module inside the consumer that needs it* (or
inside timing's wait vocabulary if the consumer is generator-shaped), not as a standalone
package — its 4.5 KB and its bus-vs-`Signal` overlap both argue against a 16th library.

**Verdict: the best rewrite is deletion.  Park, don't polish.**

---

## 5. msgpack — leaner encoding?

Examined and rejected; the current design wins on the constraint that matters most (CP RAM):

1. **On CircuitPython the pure decoder never loads.**  `__init__.py` delegates to CP's native C
   `msgpack` module; a bespoke "leaner" codec would *always* load Python code on the tightest
   runtime (CP: 126 K free) — a custom format is a RAM regression exactly where RAM is scarcest.
2. **The format is a host↔device contract.**  Workbench tools are banned from importing device
   libraries and pack with PyPI `msgpack(use_single_float=True)`; byte-identity is pinned by
   test.  A custom TLV/CBOR-subset codec forfeits inspectability by standard tooling and forces a
   host-side custom implementation — recreating the drift surface 0093 just killed for factories.
3. **The subset already is the lean encoding.**  32-bit ints, float32, 16-bit lengths: msgpack
   with the fat removed, while staying spec-compliant for any standard reader.  10.2 KB stripped,
   pure-Python side, is near the floor for a codec plus the 0073 hardening (length-vs-remaining,
   depth cap, trailing-bytes) that an adversarial audit paid for once and a rewrite would pay
   again.

Residual worth noting, not worth a rewrite: MSG-1 (truncated multi-byte headers can raise
`IndexError`/`struct.error` instead of the documented `ValueError`) is a contract-honesty fix of
~10 lines in `_pure.py`, tracked from the June review.

**Verdict: keep.  A rewrite here is pure churn.**

---

## 6. Cross-cutting radical moves the per-library frame hides

- **One I/O reactor as THE library** (timing + runner + sockets merged, protocols on top — the
  trio shape): rejected.  It buys co-design of waits/connectors/poll-sync — which the duck-typed
  contracts plus one source tree already deliver — and costs the fleet's defining property:
  per-library deploys and BYOS.  A blinky app ships 3.5 KB of timing today; under a monolith it
  ships ≈ 69 KB (timing 3.5 + runner 22 + sockets 43) or the monolith grows a deploy-time
  tree-shaker (a new tool nobody asked for).  The stress-test consumer objects too: `MQTTClient`
  accepts a bare injected `socket=` and runs without runner or sockets on board; a reactor-owned
  socket world deletes that constructor path and every test built on `FakeSocket`.
- **Shared buffer arena:** rejected.  The genuinely shareable buffers are the small per-library
  recv scratches (256–512 B × ~4 libraries ≈ 1–2 KB); the big buffers (mqtt rx, websockets
  session, requests body) hold partially-parsed state *across* ticks and cannot be lent out.  An
  arena adds a cross-library dependency edge (against the runtime-optional substrate rule) and an
  ownership protocol, to reclaim ~1.5 KB on a board with 126–201 K free.  Decision 0094's heap
  gates already police the real number where it can regress.
- **Unified deadline wheel / heap:** rejected.  `wait`'s linear scan over ≤ 10 services costs
  ~30 allocation-free operations; deadlines mutate constantly (every publish re-arms keepalive,
  every recv re-arms a timeout), so a heap pays an allocation per mutation to speed up a peek
  that was never slow.  0080 already rejected asyncio's C TaskQueue on the same grounds; the
  crossover point (N ≳ 50 live deadline sources) is unreachable on a 264 KB board.
- **The move the frame hides that IS worth it:** the wait-token protocol is the fleet's real
  shared interface — and it has no owner.  Giving it one (timing, §1) is the cheap cross-cutting
  win: one documented protocol, seven private copies deleted, and the runner/sockets/consumer
  seams all narrate themselves in the same vocabulary.

---

## 7. The consumers rebuilt (stress test)

Under the recommended package (timing v2 + runner contract v2 + sockets collapse):

- **mqtt:** `sockets_factory` 46 → ~12 lines; three `io_wants_*` properties → one `io_interest`
  mask; `io_error` body folds into the FAILED transition it already performs; `next_deadline`'s
  min-scans become `earliest()` chains (−10 lines, same allocation profile); `_advance_connector`
  and the whole three-tier decoder are untouched.  Client core is structurally identical — the
  rebuild is an edit, which is the point: the reactive architecture survives the redesign because
  it was right.
- **websockets:** `_InboundWait` and the pong/auto-ping deadline plumbing move onto shared
  tokens/`Rate`; session frame machinery untouched.  ~−40 lines.
- **requests:** `_ReadDeadlineWait` deleted in favor of `timing.ReadWait(sock, deadline_ms=...)`;
  `fetch`'s ticks-threading shrinks under `Deadline.after`.  ~−30 lines.
- Under the **rejected** moves, for the record: Model-2 dispatch would decompose mqtt's
  bake-tuned handle order into three entry points; the reactor monolith would delete mqtt's BYOS
  constructor and its entire `FakeSocket` test seam.  Both fail the stress test outright — that,
  more than any per-library argument, is why they are rejected.

## 8. What the monorepo gains

- **Audit and drift surface (the compounding one).**  The 144-agent audit and its remediation
  sweeps price every duplicated contract: two connect paths, seven wait shapes, five routing
  copies, two dispatch lanes each bought findings (SOCK-2, G1, RUN-2/3, M77).  The package above
  removes ~4 standing duplication classes; every future audit, comment pass, and bake matrix gets
  proportionally cheaper.  This is the honest answer to "excel our work even further": the fleet's
  velocity ceiling is audit/bake cost, not feature cost.
- **Test-suite weight:** events −518 lines and three runtime lanes gone; sockets' factory/
  connector suites consolidate (measure the CP 160 K override afterwards); runner keeps its suite
  but loses the io_error-lane permutations.
- **Deploy size:** modest and honest — a full mqtt-over-TLS stack goes from ≈ 129 K to ≈ 119 K of
  stripped `.py` (sockets −9 K, runner −3 K, timing +1 K).  Heap budgets barely move: mqtt's
  192 K import floor is mqtt's own 60 K, not the substrate's.  Nobody should sell this rewrite on
  RAM.
- **Demo/project legibility:** the big win already shipped (generators + `run_until`); the
  remaining gains are one connect vocabulary (`connector(...)` everywhere, including in prose) and
  wait tokens with public names instead of per-library underscores.
- **Project-authoring simplicity:** one factory idiom to copy for a new networking library
  (Decision 0093's contract, now ~12 lines), one wait vocabulary to learn, one place (`timing`)
  where "how do I wait for X" is answered.

## 9. Ranked verdict

| # | Move | Call | Why |
|---|------|------|-----|
| 1 | **sockets: collapse sync-factory/connector duplication; one `connector(host, port, tls=, context=)` entry; consumer copies shrink to ~12 lines** | **Rewrite — worth it** | Deletes a proven divergence-bug factory (SOCK-2 class); −9 KB; 12 → 8 public callables; payoff compounds every bake |
| 2 | **events: delete the library, revive-inside-consumer if presence ever materializes** | **Remove — worth it** | Zero consumers; second time the ecosystem rejected a bus; 0092 makes deletion nearly free |
| 3 | **timing: keep ticks verbatim; absorb the wait vocabulary (`ReadWait`/`WriteWait`/`Deadline`/`Signal`), `earliest()`, `Rate` (absorbing orphaned `Heartbeat` + 0088 phase math)** | **Extend — worth it** | Seven private wait shapes and two min-scan idioms get one owner at zero deploy-graph cost |
| 4 | **runner: contract slim (`io_interest` mask; fold `io_error` into the single dispatch lane); architecture unchanged** | **Worth it only riding #1–3's migration wave** | Halves the duck surface and makes G1-class bugs structural non-events; standalone it is churn |
| 5 | **runner re-architecture: Model-2 readiness dispatch, `async`/`await`, capability handles, run-loop ownership** | **Churn — keep current design** | Each alternative loses on recorded evidence (CP bytecode cost, mqtt's bake-tuned tick order, BYOS) |
| 6 | **msgpack: leaner/custom codec** | **Churn — keep** | CP native delegation makes any custom codec a RAM regression; the format is the host↔device contract |
| 7 | **Monolith reactor, shared buffer arena, deadline wheel** | **Churn — rejected** | Kill per-library deploys / reclaim ~1.5 KB / speed up a scan that costs ~30 ops — all bad trades at fleet size |

Sequencing note: #1–4 break overlapping consumers, so they land cheapest as one coordinated
0092-style migration (per-library commits, each breaking and migrating its consumers same-commit),
with the full four-board bake matrix as the exit gate.  Items #5–7 should be recorded as rejected
in any follow-up ADR so the next design pass does not re-litigate them without new evidence.
