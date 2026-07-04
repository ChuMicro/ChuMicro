# Consumer-driven design synthesis — DI verdict, seat-one cross-examination, target state, sequencing

Date: 2026-07-03
Seat: second Fable seat (consumer's chair + cross-examination of the greenfield seat).
Inputs: the five 2026-07-03 sibling reports (consumer-angle workspace-template, DI cost
measurement, greenfield core redesign, rudiment API fitness, mqtt API fitness). Every
load-bearing claim reused below was re-verified against source, not taken on faith;
re-verification notes are flagged inline as **[verified]** with `file:line`.

Claims re-checked directly for this synthesis:

- Factory kwarg spellings **[verified]**: `connector_factory=` on mqtt
  (`libraries/mqtt/src/chumicro_mqtt/client.py:264,317` — zero-arg closure), requests
  (`libraries/requests/src/chumicro_requests/client.py:398,454` — per-call
  `(host, port, use_tls)`), websockets (`libraries/websockets/src/chumicro_websockets/client.py:126,163`
  — per-call); `socket_factory=` on ntp (`libraries/ntp/src/chumicro_ntp/core.py:216,259`);
  `listener_factory=` on http_server (`libraries/http_server/src/chumicro_http_server/server.py:574,634`).
  Same name, two arities on the three `connector_factory` libs; two more names for the same
  concept on ntp/http_server.
- mqtt publish guard **[verified]**: `publish()` raises `MQTTError` when
  `state != ProtocolState.CONNECTED` (`client.py:793-796`).
- events consumers **[verified]**: zero code consumers outside its own tree — but **three
  doc/config touchpoints seat one did not list**: `libraries/wifi/docs/guide.md:84-86`
  (a live `EventBus` example recruiting wifi users into events),
  `workbench/deploy/docs/testing.md:102` (cites `chumicro_events.testing.RecordingSubscriber`
  as an exemplar), and sister `ChuMicro-Workspace-Template/workspace.yml:19` (maps the
  library path).
- Runner surface **[verified]**: `add` (core.py:270), `add_generator` (:352),
  `add_periodic(handler, period_ms, ...)` (:400), `tick` (:432), `wait` (:549),
  `run_until(predicate=None, *, timeout_ms=None)` (:630) — the bare-predicate form runs
  forever with `wait()` parking; a `None` predicate "never completes on its own" (:649-652).
- Runner `io_*` exposure in consumers **[verified]**: `grep io_wants|io_error|io_socket`
  over the whole template repo returns **nothing**; in `demos/` exactly one file
  (`demos/sockets_runner_connector_explicit/app.py`). App authors write `check`/`handle`
  objects and never touch the io contract.
- Decision 0093 **[verified]**: pins **two factory arities deliberately** (per-call for
  connect-family, zero-arg for endpoint-baked, §3) and — decisive for the naming question —
  the ADR's own title and summary call the concept the **"transport-factory contract"**
  while no library spells the kwarg that way.
- Config access **[verified]**: `get` / `require` / `__getitem__` all live on the section
  wrapper (`libraries/config/src/chumicro_config/section.py:41,44,51`) — the
  three-idioms observation is a docs/convention gap, not phantom API.

---

## 1. The DI verdict, settled

The owner's words: *"i want people to integrate chumicro libs into their existing codebase
but if chumicro can do their codebase easier and its better for them to instead port to
chumicro, maybe this is a futile exercise adding all this di. i still think its probably
right, so not sure."*

### Verdict: keep constructor DI. It is right, and the futility framing is false.

The futility argument assumes DI has one payoff (standalone integration) that one adoption
outcome (everyone ports) would nullify. The measurement report shows DI has **two** payoffs,
and the first survives every adoption outcome:

1. **Host testability is internal and unconditional.** 256 injection call-sites, 12 fakes
   never flashed, full host pytest with no board. Even in a world where every user ports
   their whole project into chumicro, the repo itself needs these seams — they are how the
   fleet is tested at all. DI already pays for itself before the first external adopter.
2. **Standalone integration is a free strategic option riding on top.** `import
   chumicro_mqtt` pulls zero sockets code; BYO transport + injected `ticks=` reaches an
   **empty** chumicro closure for mqtt/websockets/requests (consumer report §3, verified by
   the measurement seat). The option costs ~3.2 KB flash (~0.4 % of usable), 0.5–1.3 KB
   one-time heap per lib, and **zero hot-path frames** (one extra frame per connect,
   invisible against a TLS round-trip).

At sub-1 % device cost, this is a product choice, not a resource choice — and the product
choice is already made in the owner's first clause: he *wants* integrate-into-existing-codebase
to work. What is missing is not architecture; both sibling reports converge on the same
finding: the seams exist and are stable by design (0093 §2), but the path is
**under-marketed and inconsistently spelled**. That is polish, listed below.

### Conditions under which the verdict flips

None of these flips remove DI from *source*; the worst case is resolving it away in the
*artifact* (option c). Reconsider only if:

- **A materially smaller target class lands** (sub-128 KB-flash / sub-100 KB-heap boards)
  where 3 KB flash and 1 KB heap stop being noise → schedule deploy-time static resolution
  (below), which recovers the full cost with test seams intact.
- **Post-publication evidence shows zero standalone integrators** *and* factory-copy
  maintenance produces a recurrence of M77-class drift despite 0093 → demote the standalone
  recipe from first-class docs to an appendix; still keep the seams (payoff 1 stands).
- **The 0094 heap gates regress** and the 0.5–1.3 KB factory-module tax is implicated →
  same answer: option (c), not removal.

### The polish package that makes standalone adoption first-class

**(i) One factory-kwarg vocabulary: `transport_factory=`.**

The one spelling is **`transport_factory`**, across all five networked libraries
(mqtt, websockets, requests, http_server, ntp — "the four networked libs" plus ntp, which
must not be left as the odd sibling). Why this word and not the incumbent
`connector_factory` (already 3 of 5):

- **It is the name the ecosystem already gave the concept.** Decision 0093 is titled "One
  transport-factory contract" **[verified]**. The code should say what the contract says.
- **`connector_factory` is a lie on two of the five.** http_server's factory returns a
  *listening* socket (it accepts, it never connects) and ntp's returns a UDP socket. A
  connector is specifically the non-blocking connect state machine (Decision 0081);
  stretching the word to listeners breaks the one precise term the sockets collapse (§2.1)
  is about to make load-bearing (`connector(host, port, tls=...)`).
- **Retiring the `socket_factory` spelling has a concrete safety payoff.** The template's
  two hard-broken files call `MQTTClient(socket_factory=...)` — a kwarg that survives
  *today* on ntp, so a user grepping the workspace finds a live `socket_factory=` and
  concludes their stale mqtt code is plausible. After the rename, the stale spelling greps
  to nothing: dead code looks dead.

What does **not** change: the two arities (per-call `(host, port, use_tls)` for
requests/websockets; zero-arg endpoint-baked for mqtt/ntp/http_server) stay per 0093 §3 —
the arity split is real transport-role variance, the *vocabulary* is what unifies. The
`sockets_factory.py` module name and the `__chumicro_skip_factories__` marker stay (deploy
machinery keys on them). The direct-inject overrides (`socket=`, `listener=`) stay as-is —
they are a different concept (pre-built transport, mostly a test seam: 72 + 13 host-test
sites); unifying them to `transport=` is recorded as an option, not scheduled.

**Migration** (one 0092-style commit series, consumers migrated same-commit):
rename the constructor kwarg + `from_config` internals in 5 libraries; ~63
`connector_factory=` + ntp/http_server test sites (mechanical grep-and-replace); 2 demos
(`requests_fetch`, `sockets_runner_connector_explicit`); guides + Decision 0093 annotated
in place with the spelling. Private attributes (`self._connector_factory`) may keep their
names where they genuinely hold a connector factory. Effort: 2 pts. Rides Wave 1 (§4)
because the factory copies are being rewritten there anyway — renaming them a week before
rewriting them would be double work.

**(ii) The documented DI recipe.** One "Integrate this library standalone" section per
networked-lib guide plus one workspace-level page, all saying the same thing:

> Pass `transport_factory=<yours>` (shape for this library: …per-call/zero-arg…) and
> `ticks=<yours>`; add `__chumicro_skip_factories__` to your deploy to strip the default
> wiring; your chumicro closure is now empty (no sibling imports). If you skip `ticks=`,
> you inherit the 3.5 KB `chumicro_timing` leaf — deliberate default, not a bug.

The last sentence resolves the consumer report's "silent ticks fallback" friction the
cheap way: keep the fallback (failing hard would tax the ergonomic path that 90 % of users
take), document the inheritance. Effort: 2 pts, gated on the rename (docs must show the
final spelling).

**(iii) Deploy-time static resolution: record, don't schedule.** Alternative (c) in the
measurement report is the designated fallback: it recovers ~1–3 KB flash and ~1 KB/lib heap
by rewriting DI to direct calls in the deploy artifact, keeping every source seam. Against
that stands real engineering risk — an AST-rewrite pass with a parse-tree equivalence
guard, and deployed source diverging from repo source (worse on-device tracebacks). At
0.4 % of flash the trade is currently negative. Record it in an ADR as the pre-approved
answer to future flash pressure so the next flash scare doesn't re-litigate DI itself.

---

## 2. Cross-examination of seat one's five ranked verdicts

### 2.1 Sockets collapse (seat one #1: "the rewrite worth doing") — SURVIVES, but reframed

Judged against project-authoring reality: **the single `connector()` entry does not make
app.py simpler, because the target-state app.py never touches sockets at all.** The
canonical consumer path is `from_config(config, radio=...)`, which hides the factory
entirely (demo `demos/mqtt_pub_sub/app.py:49`). Anyone selling this collapse on app-level
line count is selling it wrong.

It survives anyway, on three consumer-side grounds seat one under-argued:

- **The standalone integrator gets one function to mirror.** The DI recipe (§1.ii) tells a
  BYO-transport user what to implement; today the reference implementation they'd crib is
  spread over sync factories + connectors + five factory copies. After the collapse, "your
  factory must return what `connector(host, port, tls=...)` returns" is one sentence
  pointing at one callable. The first consumer of the collapse is the exact audience the
  owner named in the DI question.
- **It makes the 0081 anti-pattern unwritable.** The template's obsolete
  `_make_socket_factory` closures build *blocking* sockets via
  `tcp_client_socket`/`tls_client_socket` — the synchronous stall Decision 0081 killed.
  The collapse deletes those exact exports; the broken pattern stops compiling instead of
  lurking as an attractive nuisance in old snippets.
- **The bake/audit payoff compounds** (seat one's own strongest point — SOCK-2's divergence
  class dies with the second implementation). Agreed as argued.

One consequence seat one's sequencing note missed: **template repair is gated on this
collapse** — repairing the two hard-broken template files before it means migrating them
twice (once onto today's factory spelling, again after the collapse + rename). Placed
accordingly in §4.

### 2.2 Events deletion (seat one #2) — SURVIVES, with a consumer-facing sweep seat one missed

Zero code consumers re-verified. But "delete the library" is not consumer-neutral as
scoped: **the wifi guide actively recruits users into EventBus**
(`libraries/wifi/docs/guide.md:84-86` builds a bus in its wiring example) — a template
author reading the wifi guide today is being taught a library that is about to vanish.
Two more touchpoints dangle: `workbench/deploy/docs/testing.md:102` (cites its fakes as an
exemplar of the workspace pattern) and sister `workspace.yml:19` (path mapping, folds into
template repair).

So the deletion ships as: library delete + **three-file doc sweep**, with the wifi guide
section rewritten to what the demos actually do — direct `on_state_change` callbacks and
Decision-0091 `Signal`. Functional consumer loss: none; the replacement idiom is already
the practiced one everywhere. Agreed, with the sweep added to the work item.

### 2.3 Timing extension (seat one #3) — SURVIVES; highest consumer leverage after the mqtt queue; one gap

Checked against what template apps actually hand-roll (consumer report §2): every tick
object re-implements `ticks_ms`/`ticks_add`/`ticks_diff` re-anchoring; the raw-`+` footgun
is already tripped in shipped code (demo `http_server_roundtrip/app.py:59`, sister
`mqtt_bake_diag_plain/app.py:250,270,293`); seven libraries hand-roll arm/expire/earliest.
The extension answers all of that. Two synthesis additions:

- **Merge the two seats' surfaces — they differ.** Seat one sketches
  `Deadline.after(delay_ms)` + `Rate(preserve_phase)` + `earliest()` + wait tokens +
  `Signal`; the rudiment seat sketches `Deadline(delay_ms)` with **`.remaining()`** +
  `Stopwatch` + `Deadline.earliest()`. The merged surface: ticks verbatim; `Deadline` with
  `.expired/.remaining/.restart` (`.remaining` is load-bearing — requests' connect-budget
  arithmetic, `requests/generators.py:170`, is exactly a `remaining()` call); free
  `earliest()`; `Rate` absorbing the orphaned `Heartbeat` + 0088 phase math;
  `ReadWait`/`WriteWait`; `Signal` relocated from `chumicro_runner.generators`.
  `Stopwatch` is **recorded, not scheduled** — the rudiment census's hand-rolls are almost
  all in examples/demos, not libraries; it can ride later if a library wants it.
- **The gap both seats underplay: nothing in the package deletes the single most-copied
  template block** — the 7-line wifi bring-up spin, verbatim in 6 files. The fix needs no
  new API: `runner.run_until(lambda: wifi.connected or wifi.state == WifiState.FAILED,
  timeout_ms=...)` already expresses it **[verified against run_until's contract,
  core.py:630-687]**, and the generator form (`Signal` + `wait_for`, as in
  `demos/requests_fetch/app.py:29`) covers generator flows. The wave-1 guide/doc pass must
  bless one of these spellings by name; a `WifiService.link` ready-made `Signal` is
  recorded as optional polish (it would shave the 8-line callback wire in generator apps,
  see requests_fetch:45-53).

### 2.4 Runner contract slim (seat one #4: "only riding the wave") — SURVIVES, and is *cheaper* than seat one priced it

Seat one priced the break as "every `io_*` implementor (5 libraries + demos + ~3.4 K runner
test lines touched in part)." The consumer-side measurement: **no template app and exactly
one demo implement any `io_*` attribute** **[verified]**. App authors live entirely in
`check`/`handle` objects, `add_periodic`, and `run_until` — none of which the slim touches.
The migration burden is libraries + connector classes + runner tests; the six template
apps' repair is **not gated on it**. Two consequences:

- Agreed with "ride the wave," with a stronger consumer case: the slim is invisible to the
  audience the template serves, so there is no reason to hesitate on their behalf.
- Sequencing refinement: land the slim **before** the sockets collapse inside Wave 1, so
  the connector classes (which implement the io contract and are being rewritten by the
  collapse) are rewritten once against the new contract, not twice.

### 2.5 msgpack keep (seat one #5) — AGREE; the consumer case seat one missed

Both prior seats argued from device RAM (CP-native delegation) and host↔device contract.
The consumer-chair addition: **the format is the project author's debugging surface.** The
two-file merge (`secrets.toml` + `project_config.toml` → `/runtime_config.msgpack`) is what
the `add-new-project` skill teaches, `dump-config` renders it, and `_generated/
runtime_config.msgpack` files sit visibly in template scratch projects. A bespoke codec
would break inspectability-by-standard-tooling exactly where new users debug their first
config mistake. Keep, and let the ~10-line MSG-1 contract-honesty fix (truncated multi-byte
headers must raise `ValueError` as documented) ride any wave.

---

## 3. The project-authoring target state — flagship sensor app, before/after

### Before — today's committed template flagship (`ChuMicro-Workspace-Template/projects/example_sensor/app.py`)

**175 lines, and it does not run**: `MQTTClient(socket_factory=...)` is a `TypeError` at
construction (the kwarg no longer exists), and its `_make_socket_factory` builds the
blocking socket 0081 killed. Structure of those 175 lines:

- module-global `_SHUTDOWN_REQUESTED` + `request_shutdown()` (invented "run until told to
  stop" — app.py:34-40)
- `_TemperatureProbe` class (app.py:43-62)
- `HeartbeatPublisher` check/handle class: state guard on `ProtocolState.CONNECTED`,
  `ticks_add`/`ticks_diff` re-anchoring, hand-rolled retry backoff, `try/except` around
  `publish()` (app.py:65-101)
- `_make_socket_factory` transport closure, tcp-vs-tls routing (app.py:111-127)
- hand-rolled wifi bring-up spin (app.py:143-148)
- busy-spin `while not _SHUTDOWN_REQUESTED: runner.tick()` with no `wait()` — never parks
  the CPU (app.py:169-173)

**Concepts a new author must hold to modify it: 10** — (1) the manual loop +
shutdown-flag + KeyboardInterrupt, (2) the check/handle object protocol, (3) monotonic
ticks wrap arithmetic, (4) the mqtt state machine and its guard, (5) publish
exception/backoff defense, (6) the transport-factory closure + tcp/tls choice, (7) the
wifi bring-up spin, (8) the WifiState machine, (9) config `require`/`get` styles,
(10) the kvstore commit lifecycle. Six of the ten (1–7 minus wifi basics) are plumbing the
libraries now own or will own under the accepted changes.

### After — the same app under the combined recommendations

(timing wait vocabulary + sockets collapse + `transport_factory` spelling + mqtt
pre-connect queue + `run_until`; everything below except `publish()`'s queue default is
**shipping API today** — this is nearly-current, not speculative)

```python
"""Example sensor — temperature publisher with persistent boot counter."""

import json

from chumicro_config import load_runtime_config
from chumicro_kvstore import KVStore
from chumicro_mqtt import MQTTClient
from chumicro_runner import Runner
from chumicro_wifi import WifiConfig, WifiService, WifiState


def read_celsius():
    try:
        import microcontroller
        return float(microcontroller.cpu.temperature)
    except (ImportError, AttributeError, RuntimeError):
        return 20.0  # sensorless board: fixed synthetic reading


def run():
    config = load_runtime_config()
    topic = config.require("sensor.topic")

    kv = KVStore()
    boot_count = kv.get("boot_count", 0) + 1
    kv["boot_count"] = boot_count
    kv.commit()
    print(f"sensor: boot #{boot_count}")

    wifi = WifiService(WifiConfig.from_config(config))
    mqtt = MQTTClient.from_config(config, radio=wifi.adapter.radio)

    def on_wifi_state(_old, new):
        if new == WifiState.CONNECTED:
            mqtt.connect()

    wifi.on_state_change(on_wifi_state)

    seq = 0

    def publish_reading(now_ms):
        nonlocal seq
        seq += 1
        payload = json.dumps(
            {"boot": boot_count, "celsius": read_celsius(), "n": seq})
        mqtt.publish(topic, payload, qos=1)  # queues until CONNECTED, flushes on CONNACK

    runner = Runner()
    runner.add(wifi)
    runner.add(mqtt)
    runner.add_periodic(publish_reading,
                        period_ms=config.require("sensor.publish_period_ms"))

    runner.run_until(lambda: wifi.state == WifiState.FAILED)
    raise SystemExit(f"sensor: wifi failed: {wifi.last_error}")
```

**55 lines (vs 175), and it parks the CPU between events.** Concepts: **7** — services +
`runner.add`, `add_periodic`, `run_until`, `from_config`, one callback wire, config,
kvstore. The three heaviest before-concepts — the tick-object class protocol, ticks wrap
arithmetic, and the transport closure — are **gone entirely**, along with the state guard,
the publish `try/except`, the shutdown flag, and the busy-spin. What remains is almost all
domain (what to publish, when) rather than plumbing (how to cooperate).

Line-by-line attribution of the collapse: `run_until` deletes the loop/flag/interrupt
block (−12); `add_periodic` deletes the `HeartbeatPublisher` class (−37); the pre-connect
queue deletes the state guard and the try/except/backoff (−8 and one concept); `from_config`
deletes `_make_socket_factory` (−17); the `run_until(FAILED)` tail deletes the bring-up
spin (−6). The before/after **is** the argument: every accepted change in this synthesis
buys visible lines in the flagship file.

---

## 4. Sequencing — one dependency-ordered plan

Effort points: 1 pt ≈ half a focused day, includes tests + docs for the item. Every wave
lands as 0092-style per-library commits (break + migrate consumers same-commit). Total
≈ 42 pts.

### Wave 0 — independent hygiene (5 pts, anytime, parallelizable, no gates)

| item | pts |
|---|---|
| events: delete library + three-file doc sweep (wifi guide §events → callbacks/Signal; deploy testing.md exemplar; README row) | 2 |
| msgpack MSG-1: truncated-header `ValueError` contract fix | 1 |
| mqtt session-resume: gate `_replay_subscriptions` on CONNACK session-present, or drop `clean_session=False` + document clean-only | 1 |
| ADR housekeeping: annotate 0064 (`MQTTPublisher` removed); record seat one's rejected moves (#5–7) + static-DI-resolution fallback so they aren't re-litigated | 1 |

### Wave 1 — the coordinated core migration (18 pts, ordered, four-board bake matrix as exit gate)

Order is load-bearing:

1. **timing extension** (merged surface per §2.3: `Deadline` w/ `.remaining`, `earliest`,
   `Rate`, `ReadWait`/`WriteWait`, `Signal` relocation; `Heartbeat` deleted) — **3 pts**.
   First, because everything downstream consumes its tokens.
2. **runner contract slim** (`io_interest` mask; `io_error` folded into the single dispatch
   lane) — **5 pts**. Before sockets, so the connector classes are rewritten once against
   the new contract (§2.4).
3. **sockets collapse** (one connect state machine per runtime; `connector(host, port,
   tls=, context=)` + `connect_now` driver; sync factories deleted; five consumer factory
   copies shrink to ~12 lines) — **8 pts**. The widest blast radius; the copies-rewrite is
   where item 4 rides.
4. **`transport_factory=` rename** across the 5 networked libs + 2 demos + guides + 0093
   annotation — **2 pts**. Rides the factory-copy rewrite it would otherwise double-touch.

Wave-1 doc pass blesses the wifi bring-up spelling
(`run_until(lambda: wifi.connected or ...)` / `wait_for(Signal)`) by name in the runner and
wifi guides.

### Wave 2 — mqtt consumer-shape fixes (10 pts, after Wave 1)

Gated on Wave 1 not by code dependency but by churn discipline: these rewrite the same
`client.py` regions and guide sections Wave 1 touches (factory copy, io properties,
getting-started), and the queue's flush hooks into the self-heal path the rename just
edited. Landing them second means demos and guides are rewritten once.

| item | pts |
|---|---|
| pre-connect queue: `publish/subscribe(when_disconnected="queue"|"drop"|"raise")`, bounded, flushed on CONNACK + self-heal; QoS-0 backpressure softened to drop-oldest/boolean, raise reserved for QoS 1 | 5 |
| cut the intact decoder tier (`_DRAIN_INTACT`): two tiers — steady parse, oversize→policy rolling discard; sizing guidance already coaches `rx_buffer_size` | 3 |
| delete the pattern-handler router; inbound converges on `on_message` + `next_message` + public `topic_matches()`; mqtt_pub_sub demo + host driver lose `PATTERN_HIT` | 2 |

### Wave 3 — DI polish docs (2 pts, gated on Wave 1's rename)

The standalone-integration recipe (§1.ii) per networked-lib guide + one workspace page;
guide regeneration where sections were touched.

### Wave 4 — template-repo repair (5 pts, gated on Waves 1–2: the API must settle first)

- Migrate `projects/example_sensor` + `examples/telemetry_publisher` to the §3 target
  shape (`from_config`, `add_periodic`, `run_until`, queue-default publish); delete
  `_make_socket_factory` / `_SHUTDOWN_REQUESTED`.
- Sweep the other four apps: `run_until` (or `wait(now)`), `add_periodic` for pure
  periodics, `radio=` on requests factories.
- README + skills: `install-libraries` → `library add`; `repl`-deploy-follow →
  `deploy --tail`; drop `set-default`; document the clean-slate deploy default and its
  conflict with hand-installed `/lib`.
- `workspace.yml`: drop the `chumicro_events` mapping (pairs with Wave 0's deletion).
- Purge committed `__pycache__` / `_generated` cruft; repoint `add-new-project` SKILL.md
  at the repaired reference.

**Escape hatch:** if template users are active *now*, a 1-pt throwaway hotfix migrating
only the two hard-broken files onto today's `from_config` is defensible — they are broken
regardless — accepting one deliberate double-migration. Otherwise wait for the gate.

### Recorded, not scheduled

Deploy-time static DI resolution (the designated flash-pressure fallback); `transport=`
direct-inject unification; `WifiService.link` Signal convenience; `Stopwatch`;
`publish(json=…)` encoding convenience.

---

## Decision menu — synthesis seat's contribution

One line per proposed change: **surface — verdict — cost — first consumer that benefits.**

- **DI (constructor injection, status quo)** — keep — 0 pts (it's built; ~0.4 % flash) — the existing-codebase integrator the owner named; the repo's own 256-site host test suite either way.
- **`transport_factory=` one-word rename (5 libs)** — accept, Wave 1 — 2 pts — the new author reading two libraries' docs back-to-back; stale `socket_factory` code starts grepping as dead.
- **Standalone-integration recipe (docs)** — accept, Wave 3 — 2 pts — the BYO-transport adopter who today has to reverse-engineer the empty-closure path from Decision 0093.
- **Deploy-time static DI resolution** — record only — 0 pts now — a future sub-128 KB target, if one ever lands.
- **timing extension (Deadline/.remaining, earliest, Rate, waits, Signal)** — accept, Wave 1 — 3 pts — requests' connect-budget math and every library's private wait shape; the raw-`+` footgun class dies.
- **runner contract slim (io_interest, io_error fold)** — accept, rides Wave 1 — 5 pts — library maintainers and the bake matrix; app authors provably untouched (zero template io_* sites).
- **sockets collapse (one connector entry, sync factories deleted)** — accept, Wave 1 — 8 pts — the standalone integrator (one function to mirror) and every future bake (SOCK-2 divergence class gone); the 0081 blocking anti-pattern becomes unwritable.
- **events deletion + 3-doc sweep** — accept, Wave 0 — 2 pts — wifi-guide readers stop being recruited into a zero-consumer library; the fleet sheds 518 test lines × 3 lanes.
- **msgpack keep + MSG-1 fix** — keep — 1 pt — the new user debugging their first config through `dump-config` with standard tooling.
- **mqtt pre-connect queue (`when_disconnected="queue"`)** — accept, Wave 2 — 5 pts — every publish site in repo + template; deletes the state-guard/try-except dance from 100 % of observed consumers.
- **mqtt intact decoder tier cut** — accept, Wave 2 — 3 pts — the audit/bake budget (~150 lines, one drain machine); no observed consumer loses capability.
- **mqtt pattern-router deletion** — accept, Wave 2 — 2 pts — guide readers (one fewer "pick a surface" fork); the one demo call-site migrates to `topic_matches()`.
- **mqtt session-resume honesty fix** — accept, Wave 0 — 1 pt — the `clean_session=False` user whose knob currently doesn't do what it says.
- **template-repo repair** — accept, gated on Waves 1–2 — 5 pts — every new user cloning the starter: the flagship app goes from TypeError-at-construction to the 55-line §3 shape.
- **wifi `link` Signal / `Stopwatch` / `transport=` / `publish(json=…)`** — record only — 0 pts now — generator-flow authors, if demand shows.
