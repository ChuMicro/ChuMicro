# Handoff 2026-05-22 — runner reactor workstream ready to iterate

## What this session was about

User asked for a fresh-eyes investigation of the runner reactor workstream ([workstreams/runner-reactor-and-futures.md](../workstreams/runner-reactor-and-futures.md), axis 2): is the design sound, or are we making the stack confusingly more complex?  Explicit ask was to be skeptical, not blindly trust ADRs, and to verify against the actual MicroPython / CircuitPython sources in `.tools/`.  User's stated pain was that the README's multi-service MQTT example read "overly complex and unbound" — the fetch call sitting far from the reply wiring.

## What got done

Two commits landed (both pushed to `origin/main`):

- `6513f00e` — README MQTT example rewritten to use `on_done` (axis 1 canary; collapsed three glue functions into one callback; 38 lines → 24).
- `0a226a9f` — ADR 0080 ratified option B (services expose `io_socket` / `io_wants_read` / `io_wants_write` as stable duck-typed attributes; runner reads each `wait()` and syncs the poll set on diff).  Option A added to the Rejected list with the missed-work rationale.  Workstream's gap-1 todo marked ratified.

Preflight ran clean (`python scripts/run.py preflight` → "Preflight passed").

## Decisions made

**Option B over option A for socket-interest registration.**  Recorded in ADR 0080.  Option A (services call `runner.watch(sock, read=, write=)` at lifecycle transitions) misses bytes queued *between* ticks: a `publish()` that enqueues outbound bytes between tick N and N+1 doesn't itself fire a `modify`, so a sleeping `wait()` can't know to wake on writability.  Option B re-reads stable attributes each loop and catches it, allocation-free.

## What was learned (session-state, not durable)

The workstream's load-bearing technical claims were independently verified this session — the resumer can skip re-verifying these unless suspicious:

- Both target runtimes' asyncio cores really do `select.poll().ipoll(dt)` with the **socket object** registered.  [VERIFIED: grep `.tools/micropython-v1.26.0/extmod/asyncio/core.py` lines 70-116 — `class IOQueue` holds `self.poller = select.poll()`, registers `s` (socket object), and `wait_io_event(dt)` calls `self.poller.ipoll(dt)`.  Same shape at `.tools/circuitpython-10.2.0/frozen/Adafruit_CircuitPython_asyncio/asyncio/core.py:159-211`.]
- Decision 0051 already has the `Runner.wait` carve-out in place.  [VERIFIED: `plans/decisions/0051-runner-shaped-as-project-policy.md:27` — leaf services banned from `select.poll(timeout > 0)`, runner's single central wait carved out.]
- `HttpClient.check` returns "I am in flight," not "my socket has data."  [VERIFIED: `libraries/requests/src/chumicro_requests/client.py:634` — `return self._state != _RequestState.IDLE`.]
- `TaskHandle` stores only the bound `check_function` / `handler_function`, not the service object.  The "small contained change to `add` and `TaskHandle`" the workstream cites is real.  [VERIFIED: `libraries/runner/src/chumicro_runner/core.py:39-44`.]
- The chumicro-sockets guide currently registers `sock.fileno()` (int fd — the "wrong primitive" the workstream calls out) with the `fileno() == -1` fallback caveat.  This needs to flip to object-registration alongside the new accessor.  [VERIFIED: `libraries/sockets/docs/guide.md:67-83`.]

**Axis 1 alone resolves the README pain.**  The rewritten MQTT example dropped the module-level `request = None` slot, dropped the `response_ready` shadow-polling task, dropped the `print_response` clearing function, and bound success / error handling next to the request that produced it.  This was the canary the workstream described — and it passed.  Confirms the axis split (axis 1 result composition vs. axis 2 CPU-idle wait) was the right model.

## Riskiest assumption

That the device hardware validation in `.scratch/*_validate.template.py` (run 2026-05-21) holds for the **wrapper-mediated** path the production code will use.  The .scratch scripts registered raw `socket.socket` / `socketpool.Socket` objects directly.  Production will register `wrapper.raw_socket` (the new accessor on `_MpSocketWrapper` / the CP adapter).  [HYPOTHESIS: cheapest test = adapt `.scratch/mp_ipoll_validate.template.py` to use `chumicro_sockets.tcp_client_socket(...)` instead of a raw socket, and confirm `poller.register(wrapper.raw_socket, ...)` reports readiness identically across the 20-30 register/poll/recv cycles.]  Risk class: if the wrapper layer breaks poll readiness (e.g., the underlying lwIP socket isn't exposed cleanly), the whole reactor implementation needs a different seam.  Run the test before writing service-side `io_*` attributes.

## To pick up next session

The workstream is judged ready to iterate.  Implementation order:

1. **`chumicro-sockets` raw-socket accessor + guide update.**  Add a `raw_socket` attribute on `_MpSocketWrapper` (`libraries/sockets/src/chumicro_sockets/_adapters/mp.py:47-107`) and the CP equivalent in `_adapters/cp.py`, returning the underlying pollable object.  Update `libraries/sockets/docs/guide.md:67-83` to register the object instead of `fileno()`, drop the `-1` fallback caveat from the prose, and from the runtime-matrix table (around line 123).
2. **Inject-a-fake-poller seam for host tests.**  Constructor injection on `Runner` (same posture as `ticks`).  Design the poll-shaped surface alongside the runner change — the fakes in `chumicro_sockets.testing` need to expose what the fake poller will call.
3. **`Runner.wait(now_ms)` + service-interest read loop + optional `next_deadline(now_ms)` read.**  Hold one `select.poll` for the runner's life; use `ipoll(timeout)` on device, the fake on host.  `wait` reads each service's `io_socket` / `io_wants_read` / `io_wants_write` and syncs the poll set on diff.  Heap-drift test under tracemalloc per Decision 0051's standard (the .scratch scripts measured 48-448 bytes drift over 20-30 cycles, plausibly noise but the tracemalloc bar is harder).  `TaskHandle` needs to retain the service reference (today it stores only bound methods) so `wait` can read `service.io_*`.
4. **Teach the four I/O services to expose `io_*` and optionally `next_deadline`.**  `requests`, `mqtt`, `websockets`, `http_server`.  Additive, one library at a time.  Each already tracks its socket and state internally — the attributes are mostly properties over existing state.  `mqtt/client.py` has `_deadline` / `_next_ping_due_ticks` (around 1257-1276) that map directly to `next_deadline`.
5. **Add `runner.wait(now_ms)` to the README MQTT example.**  Demonstrates CPU-idle behavior.  Workstream closes.

## Dead ends already ruled out (don't re-walk)

- **Adopt asyncio or borrow its scheduler piecemeal.**  ADR 0080's Rejected section explains why.  The I/O reactor is coroutine-bound (no `await`, no `IOQueue` entry, no I/O sleep); `task_queue_push` in C blind-casts pushed objects to `mp_obj_task_t *` (heap corruption if you push a `TaskHandle`).  Both halves are welded to coroutines — it's all-or-nothing.
- **Futures as result composition.**  Workstream axis-1 section rejects them on heap-fragmentation grounds (state + result + error + resizing callback list per future, allocated per `.then`, no `__slots__` on MP/CP).  Callbacks (`on_done`, shipped in chumicro-requests 0.10.0) are the floor.
- **Event-driven option A (services calling `runner.watch(...)`).**  Ratified out in ADR 0080 today.
- **`Runner.run()` owning the loop.**  Rejected on transparency grounds (Decision 0051's read-and-single-step argument).
- **Platform deep/light sleep as a runner tier.**  Connected board can't get to µA while the radio is up; `ipoll` already idles the CPU between events.  Microamp sleep requires a different application shape (drop the connection, wake through reboots).

## How to rebuild context fast

Re-read in this order:

- [`plans/workstreams/runner-reactor-and-futures.md`](../workstreams/runner-reactor-and-futures.md) — the workstream doc.  "Before code: four gaps" section near the bottom is the implementation-ready summary.  "Status" at the very end captures current state.
- [`plans/decisions/0080-runner-reactor.md`](../decisions/0080-runner-reactor.md) — the ADR, tight (~60 lines), reflects option B as of today.
- [`plans/decisions/0051-runner-shaped-as-project-policy.md`](../decisions/0051-runner-shaped-as-project-policy.md) line 27 — the leaf-vs-loop blocking carve-out.
- [`plans/decisions/0014-runner-pattern.md`](../decisions/0014-runner-pattern.md) — original service contract.

Files to read when implementation starts:

- `.tools/micropython-v1.26.0/extmod/asyncio/core.py:70-116` and `.tools/circuitpython-10.2.0/frozen/Adafruit_CircuitPython_asyncio/asyncio/core.py:159-211` — `IOQueue` + `wait_io_event`, the structural template.
- `.scratch/mp_ipoll_validate.template.py` and `.scratch/cp_ipoll_validate.template.py` — hardware-validation templates (substitute `__SSID__` / `__PASSWORD__` before running; .scratch is gitignored).
- `libraries/sockets/src/chumicro_sockets/_adapters/mp.py:47-107` and `_adapters/cp.py` `_MpSocketWrapper` / CP wrapper — the accessor lands here.
- `libraries/runner/src/chumicro_runner/core.py:39-44, 187-242` — `TaskHandle` + `tick()`; `wait()` lands as a sibling.
- `libraries/requests/src/chumicro_requests/client.py:483-486, 632-666` — `_state` / `_socket` ownership + `check`/`handle`; template for io_* attribute exposure.
- `libraries/mqtt/src/chumicro_mqtt/client.py:442-445, 925-937, 1257-1276` — `_socket` ownership + deadline computation that maps to `next_deadline`.

## Gotchas

- **Hardware state is point-in-time.**  The workstream cites "4 boards healthy as of 2026-05-21 device validation" (Pico W + Lolin S2, MP + CP).  Re-probe with `chumicro-workspace status` or the appropriate device-test invocation before re-running any of the `.scratch` validation scripts; boards drift, get unplugged, get re-flashed.
- **The .scratch templates have credential placeholders.**  Substitute locally, never commit substituted copies.  `.scratch` is gitignored already.
- **Don't pre-stage unrelated work.**  AGENTS.md warns about `git rm` / `git add` staging immediately and riding into the next commit.  Both commits today used explicit pathspecs (`git add README.md`, `git add plans/decisions/0080-runner-reactor.md plans/workstreams/runner-reactor-and-futures.md`) to avoid bundling.  Preserve that discipline.
- **The CP adapter for `chumicro-sockets` hasn't been audited this session.**  I read the MP adapter (`_adapters/mp.py`) but only listed `_adapters/cp.py` exists.  Read it before adding the `raw_socket` accessor — the CP socketpool wrapper shape may differ.
- **Workstream doc is 636 lines.**  About half is "design exploration log" written incrementally during the 2026-05-21 research push.  The ADR (60 lines) is the source of truth for the *decision*; the workstream carries *why* and *what was tried*.  Don't waste time reconciling minor differences in framing — favor the ADR when they disagree.
