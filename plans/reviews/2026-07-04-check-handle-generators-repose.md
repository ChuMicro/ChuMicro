# Check/handle vs generators — the base-contract question, re-posed (2026-07-04)

> Commissioned question: the 2026-07-03 ADR drift audit (C2) argued the generator substrate
> (Decision 0087) should have been the BASE service contract instead of `check`/`handle`
> (Decisions 0051/0014); the greenfield seat kept `check`/`handle` on evidence; Decision 0097 §3
> deliberately deferred the call.  The campaign workstream's recorded resolution path —
> "waves 1–2 shrink the two-shape overhead 0087 admits to; re-pose the question after they land,
> with fresh field data" — is now due: timing 0.7.0 (0095), runner 0.18.0 (0097), sockets 0.17.0
> (0098), mqtt 0.22.0 (0099) all landed, the four-board bake matrix is green, and the sister-repo
> template was rebased onto current main (Wave 4, 2026-07-04).  This report is the re-pose:
> a full two-repo census, the overhead quantified, the sharp edges inventoried, and a three-way
> judgment — FLIP / KEEP / RESHAPE.

## Method and evidence base

Read for this study: Decisions 0014, 0051, 0087, 0092, 0095, 0097, 0098, 0099; the 2026-07-03
adr-drift-audit, greenfield-core-redesign, and 2026-06-13 generator-io-final-review;
`plans/workstreams/{core-design-realignment,runner-api-design-pass}.md`; full source of
`runner/core.py` (923 lines, runner 0.18.0), `runner/_generator.py`, `runner/generators.py`,
`sockets/_connector.py`, `sockets/generators.py`, `requests/generators.py`, `timing/waits.py`,
the mqtt/websockets `next_message` surfaces, and all eight demos plus the sister repo's
projects/examples trees.  Every count below re-derived by grep/read with `file:line`; nothing
taken from the prior reports on faith.  Measurements: per-task RAM on the MicroPython v1.26.0
unix port (`gc.mem_alloc` deltas, `gc.collect()`-bracketed), deploy weight via the real minifier
(`chumicro_deploy.source_minify.strip_source`).

The contract under judgment, as shipped today:

- **check/handle** (0014/0051, slimmed by 0097): `check(now_ms) -> bool` + `handle(now_ms)`,
  optional `io_socket` / `io_interest(now_ms) -> int` (IO_READ=1, IO_WRITE=2) /
  `next_deadline(now_ms)` / `io_error(now_ms, eventmask)` / `cancel()`.  Duck-typed; services
  never import the runner.
- **generator substrate** (0087/0091/0095): generator functions registered via
  `runner.add_generator(gen) -> GeneratorHandle`, yielding duck-typed waits that expose the
  *same* `io_socket` / `io_interest` / `next_deadline` (+ `ready(now_ms)`) vocabulary; the
  private `_GeneratorWrapper` adapts the generator onto the check/handle contract
  (`runner/_generator.py:97-278`).

---

## 1. Census — check/handle services

### 1a. Production services (library `src/` trees)

| # | Service | File:line (check) | Kind | Optional surface implemented |
|---|---------|-------------------|------|------------------------------|
| 1 | `MQTTClient` | `libraries/mqtt/src/chumicro_mqtt/client.py:1117` | protocol client | `io_socket` :1139, `io_interest` :1158, `io_error` :1190, `next_deadline` :1211 |
| 2 | `WebSocketClient` | `libraries/websockets/src/chumicro_websockets/client.py:319` | protocol client | `io_socket`/`io_interest`/`next_deadline` via `_BaseSession` (`_session.py:280,295,332`) + client `next_deadline` :368 |
| 3 | `Connection` (server-side session) | `libraries/websockets/src/chumicro_websockets/server.py:138` | protocol session (internal — driven by `WebSocketServer`, not registered directly) | session io surface via `_BaseSession` |
| 4 | `WebSocketServer` | `libraries/websockets/src/chumicro_websockets/server.py:464` | server | none — `check` returns True until closed (poll-every-tick) |
| 5 | `HttpClient` | `libraries/requests/src/chumicro_requests/client.py:767` | protocol client | `io_socket` :597, `io_interest` :612, `next_deadline` :630 |
| 6 | `HttpServer` | `libraries/http_server/src/chumicro_http_server/server.py:891` | server | `io_socket` :913, `io_interest` :924, `next_deadline` :930 |
| 7 | `NTPClient` | `libraries/ntp/src/chumicro_ntp/core.py:349` | protocol client | none (check/handle only) |
| 8 | `WifiService` | `libraries/wifi/src/chumicro_wifi/service.py:155` | link manager | none (check/handle only) |
| 9 | `BufferedHandler` | `libraries/logging/src/chumicro_logging/core.py:277` | app-side service (log flush) | none (check/handle only) |
| 10 | `SocketConnector` | `libraries/sockets/src/chumicro_sockets/_connector.py:115` | connector state machine (base of 3 per-runtime subclasses) | `io_socket` :95, `io_interest` :107, `next_deadline` :136, `cancel` :174 |

**10 production services** (12 counting the websockets server-session and the connector's three
runtime subclasses as one each).  Kind split: 4 protocol clients, 2 servers + 1 internal session,
1 connector, 3 app/infra services.  `io_error` has exactly **one** production implementor (mqtt)
plus the generator wrapper — the 0097 fold left it a narrow surface.

### 1b. Demo / example app services

| Service | File:line | Kind |
|---------|-----------|------|
| `EchoService` | `demos/sockets_runner_connector_explicit/app.py:67` (io_socket :144, io_interest :151) | teaching companion — the only demo implementing `io_*` (confirms 0097's consumer-seat count) |
| button/LED, multi-service, sensor-threshold services | `libraries/runner/examples/{micropython_button_led.py:57, circuitpython_button_led.py:95, multi_service.py:66, sensor_threshold.py:65}` | example app services (4) |

### 1c. Sister repo (ChuMicro-Workspace-Template)

| Service | File:line | Kind |
|---------|-----------|------|
| `_StatusBeacon` | `projects/wifi_only/app.py:43` | app service |
| `_PeriodicPoster` | `projects/two_board_test/client/app.py:57` | app service |
| `_PeriodicFetcher` | `examples/periodic_get/app.py:39` | app service |
| `_PeriodicPoster` | `examples/two_board_handshake/client/app.py:59` | app service |

Registration census across the sister repo's 18 app files: **31 `runner.add(service)` object
registrations + 12 `add_periodic` handlers, 0 `add_generator` calls, 0 `yield` statements
anywhere in `projects/`, `examples/`, `shared/`, or `packages/`.**  This includes the Wave-4
template rebase (commit `c96a07e`, 2026-07-04, flagship `projects/example_sensor/app.py` at 61
lines) — a from-scratch rewrite made with both shapes fully available, which chose
check/handle + `run_until` for all six template apps.

### 1d. Test fakes

11 in-tree fakes/helpers implement the contract: `FakeSocketConnector`
(`libraries/sockets/src/chumicro_sockets/testing.py:389`), `FakeHttpClient`
(`libraries/requests/src/chumicro_requests/testing.py:245`), and the runner suite's `_GateTask` /
`_IOService` / `_IOServiceWithErrorHook` (`tests/_core_helpers.py:12,31,63`), `_StableService` /
`_FlappingService` (`tests/test_memory_pressure_pytest.py:32,56`), `_OrderedGate` / `_Recorder`
(`tests/test_core_scheduling.py:185,226`), a poller service (`tests/test_default_poller_pytest.py:47`),
`Gated` / `MyTask` (`functional_tests/test_runner.py:65,144`).  `workbench/` and `scripts/`
contain **zero** runner-shaped services (the `chumicro_checks` `check(repo_root)` rules are an
unrelated contract; two check-rule tests carry the signature only as string fixtures).

**Bottom line: 19 real (non-fake) check/handle implementations across both repos, plus 43
sister-repo registrations of them.**

---

## 2. Census — generator tasks

Spawn entrypoint: `Runner.add_generator(gen)` (`core.py:379`), the only one.  (`run_until` drives
either shape and is counted as loop plumbing, not a spawn.)

### 2a. Tasks in shipped app code

| Task | Spawn site | Kind |
|------|-----------|------|
| `fetch_run` (one-shot HTTP GET) | `demos/requests_fetch/app.py:55` | demo |
| `echo_run` (one-shot TCP echo) | `demos/sockets_runner_connector/app.py:69` | demo |
| `receive_stream` (WS receive loop) | `demos/websockets_stream/app.py:65` | demo |
| `consume_commands` (MQTT receive loop) | `libraries/mqtt/examples/receive_stream.py:88` | example |
| `fetch_once` | `libraries/requests/examples/generator_fetch.py:68` | example |
| `stepwise_work` | `libraries/runner/examples/generator_basic.py:55` | example |
| `receive_stream` | `libraries/websockets/examples/receive_stream.py:80` | example |

**7 tasks: 3 of 8 demos, 4 of ~45 library examples.  Sister repo: 0.  workbench/scripts: 0.**
All 7 are exactly the 0087-sanctioned profile: one-shot sequential I/O or a single-subscription
receive loop.

### 2b. Yield-from-able library surfaces (the generator lane's payload)

| Surface | File | Shape |
|---------|------|-------|
| `connect` / `send_all` / `recv_until` / `recv_exact` | `libraries/sockets/src/chumicro_sockets/generators.py` | socket lifecycle helpers |
| `fetch` + `get/post/put/patch/delete` | `libraries/requests/src/chumicro_requests/generators.py` | one-shot HTTP |
| `MQTTClient.next_message` | `libraries/mqtt/src/chumicro_mqtt/client.py:1048` | receive stream (0099 kept it and deleted the router because of it) |
| `_BaseSession.next_message` | `libraries/websockets/src/chumicro_websockets/_session.py:407` | receive stream |
| `sleep_until` | `libraries/runner/src/chumicro_runner/generators.py:26` | deadline wait |
| `Signal` / `wait_for` | `libraries/timing/src/chumicro_timing/waits.py` | callback→generator bridge (0095) |

### 2c. Tests

~49 `add_generator` sites in the runner suite (`test_generator.py` ×25, `test_generator_io.py`
×11, `test_socket_generators.py` ×9, `test_core_wait_edges.py` ×2, lazy-import ×2) plus the
consumer-surface suites (§3c).

---

## 3. The two-shape overhead, quantified

### 3a. Runner package split (runner 0.18.0)

| Piece | Source lines | Stripped bytes (real minifier) | Lane |
|-------|-------------:|------------------------------:|------|
| `core.py` | 923 | 15,410 | shared reactor (tick, wait, poll-sync, `run_until`, `TaskHandle`) |
| — of which `add_generator` | 47 (:379-425, ~14 code) | ~400 | generator-only |
| `_generator.py` (`_GeneratorWrapper` + `GeneratorHandle` + `_NextTickWait`) | 278 | 3,614 | generator-only |
| `generators.py` (`sleep_until` + `_DeadlineWait`) | 43 | 300 | generator-only |
| `__init__.py` / `testing.py` | 42 / 88 | 516 / 1,370 | shared |
| **runner total** | **1,374** | **21,210** | generator lane ≈ **4.3 KB ≈ 20%** |

The load-bearing structural fact: the generator lane is a **client** of the check/handle
contract, not a peer.  `_GeneratorWrapper` satisfies check/handle/io_* and rides the same
dispatch, poll-set, deadline-scan, and fault-isolation machinery (`_generator.py:97-113`);
`core.py` contains no generator-specific dispatch beyond the 14-line `add_generator` body and
its lazy import.  There are not two runner lanes to maintain; there is one contract and one
278-line adapter.

### 3b. Code that exists only because there are two shapes

Pure shape-translation (would delete if either shape vanished):

| Piece | Lines | Stripped B |
|-------|------:|-----------:|
| `_GeneratorWrapper` + `GeneratorHandle` (`runner/_generator.py`) | 278 | 3,614 |
| `Signal`/`wait_for` callback→generator bridge (`timing/waits.py`) | 107 | 1,098 |
| Private wait shims: `_NextTickWait` (`runner/_generator.py:53`), `_DeadlineWait` (`runner/generators.py:16`), `_ReadWait`/`_WriteWait` (`sockets/generators.py:47,60`), `_ReadDeadlineWait` (`requests/generators.py:55`), `_InboundWait` ×2 (`mqtt/client.py:99`, `websockets/_session.py:136`) | ~110 | ~800 |
| **Pure translation total** | **≈ 495** | **≈ 5.5 KB** |

Generator-lane feature payload (user-facing surfaces that exist only because the second shape
exists — not dead weight, but carried weight):

| Piece | Lines | Stripped B |
|-------|------:|-----------:|
| `sockets/generators.py` (4 helpers) | 318 | 3,737 |
| `requests/generators.py` (`fetch` re-drives the same `_wire` machinery `HttpClient` drives reactively — the one genuine parallel implementation) | 261 | 5,498 |
| mqtt `next_message` + inbound queue plumbing | ~85 | ~900 |
| websockets `next_message` + inbound queue plumbing | ~70 | ~750 |
| **Payload total** | **≈ 735** | **≈ 10.9 KB** |

The 0098 dual exposure is the cheapest kind of field data: `sockets/generators.connect` does
**not** re-implement the connector — it `yield`s the `SocketConnector` itself
(`generators.py:162`), because a check/handle service already *is* a valid wait token (same
`io_socket`/`io_interest`/`next_deadline` attributes).  The two shapes share one io vocabulary;
the "bridge" for the connector is 26 code lines, most of it the timeout feature.

### 3c. Test and doc duplication

- Runner suite: generator-lane tests 970 lines (`test_generator.py` 383, `test_generator_io.py`
  256, `test_socket_generators.py` 231, `test_lazy_generator_import_pytest.py` 55,
  `_generator_helpers.py` 45) beside ~2,516 lines of core-lane tests.
- Consumer generator-surface suites: sockets 504 (`test_generators{,_pytest}.py`), requests 347
  (`test_generators_{fetch,errors,pytest}.py` + helpers), mqtt 116 (`test_next_message.py`),
  websockets 192 (`test_next_message.py`).  **Generator-lane test weight ≈ 2,129 lines across
  five libraries** — each running three runtime lanes.
- Docs: the runner README (385 lines) teaches four registration shapes plus a
  "when to pick generators vs check/handle" section (21 generator mentions; guide.md 16 more);
  the demo pair `sockets_runner_connector` (70 lines) / `sockets_runner_connector_explicit`
  (189 lines) exists specifically to teach the same wire behavior in both shapes.

**Total carrying cost of the second shape: ≈ 1,230 source lines (≈ 16 KB stripped across five
libraries), ≈ 2,100 test lines, one dual-taught doc surface.**  For scale: the five networking
libraries measure 275 KB stripped today (mqtt 58.1 K, websockets 79.3 K, requests 58.5 K,
http_server 38.6 K, sockets 40.5 K — re-measured with the same minifier); the second shape is
≈ 6% of that fleet.

---

## 4. Sharp-edge inventory (live today)

### 4a. Generator-lane edges

1. **M49 (silent generator death) — CLOSED, with a residual.**  Shipped in runner 0.14.0 as
   "both surfaces" (`plans/workstreams/runner-api-design-pass.md:3`): the wrapper records
   `handle.error` and re-raises into the tick lane's isolation (`_generator.py:224-232`), so the
   death is counted in `handler_errors` and reported to `on_handler_error`; `run_until(handle)`
   re-raises the stored error (`core.py:704-708`).  Residual: a hand-rolled
   `while not handle.done` driver that never reads `handle.error` still sees a silent clean
   `done` — mitigated-by-default only for `run_until`/hook users.  Housekeeping: the M49 bullet
   in `plans/next-up.md:13` is still unchecked despite having shipped — stale.
2. **Priming contract.**  `add_generator` requires a fresh, un-advanced generator; an advanced
   one has its first wait *silently skipped* (`core.py:381-388`).  Documented, unlintable.
3. **Six private wait shapes remain unowned.**  0095 gave `Signal` a public home but explicitly
   punted the read/write markers to "Decision 0098's wave" (`0095:26-27`) — 0098's text never
   picks them up.  The duck-typed wait protocol still lives in six docstring copies across five
   files (§3b table).  The greenfield study's drift-class finding is narrowed, not closed.
4. **First-use lane cost.**  Measured on the MP unix port: the first `add_generator` call costs
   **5,312 B** of heap (lazy module import + first task).  Fine against MP's 201 K free; a real
   step on CP's 126 K.  The docs' "make the first call at startup" advice (`core.py:404-407`)
   is the mitigation.
5. Fixed since the June review, confirmed in source: G1 io_error isolation (0097's one-lane
   fold, `core.py:715-734`), G2 EAGAIN memoryview churn (re-slice only on progress,
   `sockets/generators.py:193-205`), G3 fetch timeout now covers connect
   (`requests/generators.py:176-190`).

### 4b. check/handle-lane edges

1. **Sequential-flow boilerplate is real and measured.**  The explicit `EchoService` teaching
   demo is 189 lines against its 70-line generator twin (2.7×) — four state strings, three
   `_handle_*` methods, manual `_send_offset` bookkeeping.  This is the recorded cost 0087 was
   built to remove, and it is what every sequential flow pays if the generator lane is deleted.
2. **The IO bit values are a pinned-by-value contract.**  `IO_READ = 1` / `IO_WRITE = 2` are
   mirrored as literals in **9 files (16 mirrored definitions)** beside the canonical pair in
   `core.py:67-68`, because services must not import the runner (`sockets/_connector.py:48-49`,
   `sockets/generators.py:43-44`, `sockets/testing.py:50-51`, mqtt/websockets/requests/
   http_server clients).  Guarded only by comments; a drift is a silent poll-direction bug.
3. **`now_ms` threading discipline.**  Re-fetching `ticks_ms()` mid-tick breaks deadline
   coherence; 0014 documents two blessed helper patterns precisely because the footgun fires in
   practice.
4. **`check()` must not mutate the task set** (`core.py:466-472`) — documented, unguarded;
   phase-1 walks the live entry list.
5. **Live doc drift found by this census:** the runner README still teaches the removed
   callable-based registration (`libraries/runner/README.md:196-205`,
   `runner.add(lambda now_ms: ..., handler=...)`), which raises `ValueError` since the 0092
   removal wave (`core.py:340-345`).  Wave 0 trued ADR 0014 but the README section slipped.
6. **Poll-every-tick services are legal and easy to write accidentally.**  `WebSocketServer.check`
   returns True until closed (`server.py:464`) and exposes no io surface, so a server-only app
   never parks the CPU in `wait()`.  Deliberate here, but the contract offers no nudge.

Symmetry observation: the generator lane's worst edge (M49) was closed *inside the wrapper*
without touching the base contract or any service — evidence that the layering (generator lane
as client of check/handle) localizes its own failure modes.

---

## 5. Memory / flash measurements

MicroPython v1.26.0 unix port (`.tools/micropython.path` build), `gc.mem_alloc` deltas with
`gc.collect()` bracketing; classes/functions defined before measurement so only instance cost is
counted:

| Quantity | Measured |
|----------|---------:|
| check/handle service instance + `TaskHandle` (2-attr service) | **448 B** |
| generator task (frame + `_GeneratorWrapper` + `GeneratorHandle` + `TaskHandle`) | **544 B** |
| generator machinery first use (lazy `_generator` import + first task) | **5,312 B** |

Deploy weight (stripped, real minifier): the generator lane costs an app that uses it
`_generator.py` 3,614 B + whichever helper modules it pulls (`sockets/generators.py` 3,737 B,
`requests/generators.py` 5,498 B, `timing/waits.py` 1,098 B — all opt-in submodules that stay
off flash otherwise, per the 0062 skip-factories / lazy-import posture).  An app that never
calls `add_generator` ships and loads none of it.

Per-task RAM is near-parity (+96 B for a generator task).  Neither shape wins the RAM argument
at task granularity; the asymmetry is that the *current* base contract lets the 5.3 KB lane be
optional, while a generator-base runner would make it unconditional.

---

## 6. The judgment

### (a) FLIP — generators become the base contract.  Rejected on field data.

1. **The app-author census is unambiguous and fresh.**  The sister repo — the audience a
   friendlier base contract would serve — contains 43 check/handle registrations, 4 hand-written
   check/handle services, and **zero** generator tasks, *including* the Wave-4 template rewrite
   (2026-07-04, flagship 61 lines) performed by authors with both shapes fully available and
   `run_until` shipped.  Real app services in the field are periodic beacons, posters, and
   fetchers — 20-line reactive gates, exactly the profile 0087 said reads worse as
   `while True: yield Sleep(N)`.
2. **All 10 production services are reactive multiplexers, not linear flows.**  mqtt's `handle`
   runs a documented, bake-tuned order (deadlines → read → drain); the http server accepts plus
   advances N connections; wifi runs a backoff state machine.  As generators these become
   while-True dispatch loops that re-implement `check` inside the body — pure shape translation,
   no legibility gain, and the intra-tick ordering guarantees (the SUBACK-race class) get
   re-audited for nothing.  The greenfield seat's rejection of readiness dispatch (§2) applies
   with the same force here; no new evidence since contradicts it.
3. **The base contract is what makes bring-your-own-scheduler possible.**  `MQTTClient` runs
   under a bare `while True: client.handle(ticks_ms())` with an injected socket;
   `demos/http_server_roundtrip/app.py:61-82` drives wifi + server with a hand loop and no
   runner import at all.  A generator-base fleet requires every driver to speak
   `.send()`/wait-token — i.e. to *be* a scheduler.  The empty-import-closure DI posture
   (0010/0042/0093) and the standalone-integrator recipe (campaign Wave 3) survive only with
   the polled-object shape as the floor.
4. **Migration cost with zero offset.**  10 services, 43 sister-repo registrations, ~2.5 K lines
   of core-lane tests, every demo, and five libraries' reactor surfaces — against a payoff of
   deleting a 278-line wrapper and one README section.  0092 makes it *free of compatibility
   ceremony*, not free of work or bake risk.
5. **The measured numbers remove the remaining motive.**  Per-task RAM parity (544 vs 448 B);
   the runner's generator lane is 20% of a 21 KB package; and M49 — the flagship "generators are
   second-class" wound — closed inside the wrapper.  The drift audit's C2 was a design-debt flag
   ("not an actionable flip today", its own words); the debt it named has since been paid down by
   0095/0097/0098 exactly where it was real (contract width, wait vocabulary, dual connect paths).

### (c) RESHAPE — examined and mostly already done.

- **Delete the generator lane** (the inverse reshape): rejected.  7 shipped tasks, the 2.7×
  boilerplate collapse is real and demo-proven, and 0099 *deepened* the dependency two days ago —
  it deleted the mqtt pattern-router because `next_message()` covers the use.  Reversing that
  without new evidence is churn.
- **One-shape-with-adapter:** already the shipped architecture.  The generator lane *is* a thin
  adapter (278 lines) over the base contract, and a check/handle object *is* a wait token
  (`connect` yields the connector itself).  There is no third structure the field data supports
  that is not the status quo viewed correctly.
- **The one genuine leftover** the census surfaced is not a contract change: the six private
  wait shapes (§4a.3) are the unfinished half of 0095 — the read/write markers were deferred to
  0098's wave and dropped.  A ~1 KB hygiene pass (public homes for `ReadWait`/`WriteWait`/
  read-with-deadline, mqtt/websockets keep their trivial `_InboundWait`s) closes the last
  standing drift class.  That is 0095 completion work, not a base-contract decision.
- **Watch, don't reshape:** `requests/generators.fetch` (5.5 KB) is the only true parallel
  drive of shared machinery (`_wire` driven both reactively and generatively).  Deliberate —
  different allocation profiles (reused body buffer vs per-call) — but it is the first place a
  third parallel surface would appear; see reopening criterion 2.

### (b) KEEP — the verdict.

**check/handle stays the base service contract; the generator substrate stays the convenience
layer.**  The 2026-07 field data is stronger for KEEP than anything available when the question
was tabled: the realignment waves collapsed the two contracts onto one io vocabulary
(`io_interest` bitmask everywhere, one dispatch lane, one connect state machine), the sister
repo voted with a from-scratch rewrite, per-task RAM measured at parity, and the worst generator
sharp edge closed without touching the contract.  The two-shape overhead 0087 admitted to now
has a measured price — ≈ 1,230 source lines, ≈ 2,100 test lines, one dual doc surface — and it
buys the 2.7× collapse for exactly the code profile (one-shot sequential I/O, receive streams)
that seven shipped tasks exercise.  That is a convenience layer earning its keep, not a
mis-chosen base.

Non-blocking follow-ups surfaced by this census (hygiene, no ADR needed):

1. Finish 0095: public home for the read/write wait markers (§4a.3) — kills the six-copy
   docstring-pinned protocol drift class.
2. Fix `libraries/runner/README.md:196-205` — it teaches the removed callable-based
   registration, which raises `ValueError` on runner 0.18.0.
3. Check off the shipped M49 bullet at `plans/next-up.md:13`.

## 7. Reopening criteria — so the question closes instead of being watched

Per the commission: KEEP must state precisely what evidence would reopen the question.  Reopen
if **any** of these fire; otherwise the question is CLOSED and future design passes should cite
this report rather than re-litigate:

1. **App-author inversion.**  A future census of ≥10 real sister-repo/app projects finds ≥3
   hand-rolling explicit sequential state machines (the `EchoService`-explicit pattern: state
   strings + `_handle_*` methods + offset bookkeeping) while `add_generator` sits unused — the
   convenience layer failing in the field would be evidence the base is on the wrong side.
2. **Translation weight inflection.**  A third parallel inbound/outbound surface appears on any
   networking library (beyond callbacks + `next_message`), or pure shape-translation code (§3b
   upper table) crosses ~1,000 lines, or a bridge appears that cannot live inside
   `_GeneratorWrapper`/a wait token.
3. **Tick-budget evidence.**  A measured bake shows the per-tick `check` scan (not handler work)
   breaking the ≤5 ms tick discipline on a supported board at realistic service counts —
   readiness-routed dispatch was rejected on today's numbers (~tens of µs at 3–10 services);
   real profile data invalidating those numbers reopens the whole dispatch question, not just
   this one.
4. **M49-class recurrence.**  Another silent generator death in a bake *after* runner 0.14.0's
   both-surfaces fix — meaning the wrapper's failure model is structurally insufficient rather
   than incidentally incomplete.
5. **First publication.**  Decision 0092 self-retires at first external publication; the public
   teaching story (which shape leads the README, what external consumers duck-type against)
   must be chosen with downstream-user data.  Re-pose then as a documentation-and-API-story
   question, not a scheduler-architecture question.
