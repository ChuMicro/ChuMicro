# Runner reactor (axis 2) + result composition (axis 1)

Opened 2026-05-21, out of a design conversation about the `requests`
completion model. Two separable axes surfaced. This workstream designs
both, with axis 2 (the runner reactor) as the deeper change.
**ADR-before-code**: the axis-2 wait model is recorded in
[Decision 0080](../../decisions/0080-runner-reactor.md), which re-scopes
[Decision 0051](../../decisions/0051-runner-shaped-as-project-policy.md)'s
`select.poll(timeout > 0)` ban to carve out the runner's central wait.

## The two axes (do not conflate them)

The conversation started at "how does a request hand back its result"
and drifted into "should the runner be async." Those are two independent
axes, and only one of them is the real pain.

- **Axis 1, how you express *what happens next*.** Progression:
  shared slot, then one-shot callback (`on_done` / `.on_reply`). Axis 1
  stops at the callback. The further rungs (a composable future, then a
  coroutine) are rejected on memory grounds, see Axis 1 below. This is about
  result-handling ergonomics.
- **Axis 2, *when* the loop does work and whether the CPU sleeps.**
  Progression: busy-poll every service every tick (today), then an I/O
  reactor that blocks in one central `poll(timeout=next_deadline)` until a
  socket is ready or a timer is due.

`async`/`await` bundles both (coroutines riding a selector loop). The
project has twice rejected it on *shape* grounds (Decision 0014, then
Decision 0051's *Rejected* section). The conclusion both decisions reach,
and that this workstream re-affirms: take the *good half* of an event loop
(axis 2, sleep-until-work) without the *indirection half* (axis 1
coroutines). The good half is concrete and already shipped on every
runtime we target, as the next section shows.

The user's stated pain, "pretty bad about IO and non-blocking polling,"
is **axis 2**. Axis 1 is settled: callbacks shipped in `requests` 0.10.0
are the result mechanism, and futures are rejected on memory grounds (see
Axis 1 below).

## Cost discipline (this is embedded, abstraction is not free)

The dominant failure mode on these boards is **heap fragmentation, not
byte count**. MicroPython and CircuitPython use a non-compacting
mark-and-sweep GC: freed objects leave non-contiguous holes that never
coalesce, so allocate-and-free churn (a transient object every tick or
every request) eventually `MemoryError`s a modest allocation despite
ample *total* free. So the enemy is per-loop transient allocation, not
bytes-at-rest. A larger structure preallocated once and held forever beats
a small one churned every loop. Hard constraints on both axes:

- **The reactor lives in `chumicro-runner` only.** Leaf services do not
  grow a reactor; a socket-owning service gains a register call at connect
  and an unregister call at close. No new module, no new library for axis 2.
- **Zero per-tick allocation in the wait path.** The runner holds one
  `select.poll` object for its whole life. Services register and unregister
  their socket at lifecycle transitions (connect, close, read-to-write
  flip), which are rare events, not per-tick work. The `poll` map and its
  internal pollfd array are allocated once and mutated in place. The wait
  itself calls **`ipoll(timeout)`, not `poll(timeout)`**: `poll` returns a
  fresh list of `(obj, event)` tuples every call (per-wait churn), while
  `ipoll` yields from one reused internal tuple and allocates nothing
  steady-state. Both runtimes' asyncio cores use `ipoll` for exactly this
  reason. `ipoll` exists on MicroPython and CircuitPython but not on
  CPython's `select.poll`, so the on-device path uses `ipoll` and the
  injected host-test fake poller provides an `ipoll`-shaped method. Verify
  steady-state with the tracemalloc heap-drift test (Decision 0051's
  tracemalloc-standard consequence).
- **`Future` is opt-in and the heavy path; the bare callback is the lean
  default.** A `Future` per request (state + callback list + chained
  links) is real heap. Most callers want one continuation, so they get a
  callback with no `Future` allocated. Only callers that chain pay for the
  object. Never make the heavy shape mandatory.
- **Prefer a method on an existing object over a new file.** Each new
  module is flash bytes. If `Future` can live as a small addition to an
  existing library rather than a new `libraries/futures`, that wins on
  filesize unless the coupling argument is strong.
- **Name the cost in every proposal.** When this workstream proposes an
  abstraction, it states what it costs (bytes / allocations) and whether a
  leaner shape would do.

## Axis 2, the runner reactor (the prize)

### Why the runner busy-polls today

`Runner.tick()` (`libraries/runner/src/chumicro_runner/core.py`) walks
every entry, time-gates on `next_due_ms`, then calls `check(now_ms)`. The
main loop is `while True: runner.tick()`, which spins as fast as the CPU
allows. The waste is concentrated in the I/O services: `HttpClient.check`
returns `self._state != IDLE` (`requests/client.py:632`), which means "I
am in flight," not "my socket has data." So while a request is mid-flight,
`check()` returns `True` every tick, `handle()` runs, `recv_into` raises
`EAGAIN` (`requests/client.py:776`), and we spin. The CPU never sleeps; on
battery this is the difference between mA and µA.

No library uses `select.poll` today. The only poll *example* in the tree
is the `chumicro-sockets` guide, and it registers `sock.fileno()` (an
integer fd), which is the wrong primitive (see below) and is why that
example needs its `fileno() == -1` fallback caveat.

### Both target runtimes already ship this exact reactor

This is the load-bearing finding, and it corrects an earlier assumption in
this doc that CircuitPython could not poll sockets. It can.

MicroPython's asyncio (`.tools/micropython-v1.26.0/extmod/asyncio/core.py`)
and CircuitPython's asyncio (the frozen `Adafruit_CircuitPython_asyncio`
port, `asyncio/core.py`) are structurally identical event loops. Each
holds one `select.poll()` in an `IOQueue`, registers each socket, computes
`dt = nearest_timer_deadline - now`, then blocks in `poller.ipoll(dt)`.
That is `poll(sockets, nearest_deadline)`, both wins in one call, on both
boards. uasyncio runs on the Pico W with this. The reactor is not novel; it
is the half of asyncio we already endorse, lifted out without coroutines.

The critical detail is **what gets registered**. `select.poll().register()`
on MicroPython and CircuitPython takes the **socket object**, not an
integer fd. It polls the object through the runtime's C-level stream
`ioctl(MP_STREAM_POLL)`:

- CircuitPython's `socketpool.Socket` implements `MP_STREAM_POLL` in
  `socket_ioctl` (`shared-bindings/socketpool/Socket.c:449`), reporting
  readable / writable. CP sockets are fully pollable.
- CP's `select.poll` has an explicit non-fd-object path
  (`extmod/modselect.c:300-420`): when an object has no integer fd it calls
  the ioctl and sleeps the CPU between probes via `mp_event_wait_ms(timeout
  - elapsed)`. That is a CPU-idling wait, not a hot spin.

So `fileno()` returning `-1` on CP radio sockets is irrelevant to polling.
It means "no POSIX integer fd," not "cannot be polled." The runtime matrix
is therefore uniform, not a CircuitPython special case:

| Runtime | `select.poll` registering the socket object | Reactor mode |
|---|---|---|
| CPython (host/dev) | yes (real fds) | true poll wait |
| MicroPython (ESP32, Pico W) | yes (stream ioctl on the socket object) | true poll wait |
| CircuitPython (ESP32, radio) | yes (`MP_STREAM_POLL` ioctl on the socket object) | true poll wait, CPU idles via `mp_event_wait_ms` |

The earlier "CircuitPython must degrade to a bounded busy-poll" plan was an
artifact of reasoning from `fileno() -> int`. Registering the object
removes it. There is no degrade branch.

**Validated on hardware 2026-05-21** across all four boards (Pico W + Lolin
S2, each in MicroPython and CircuitPython). On every board,
`select.poll().register(socket)` accepted the socket object and reported
real readiness, an idle `poll(800)` blocked the full ~810 ms (Win B, the
CPU sleeps), and 20 register/poll/recv/unregister/close cycles drifted at
most 448 bytes of heap (no leak, no fragmentation walk). The `fileno`
result varied exactly as predicted and confirms why the object is the
right thing to register: rp2 MicroPython sockets and CircuitPython
socketpool sockets have **no `fileno`**, while esp32-s2 MicroPython sockets
return a real fd (`54`). Object registration worked identically regardless.
Scripts in `.scratch/mp_poll_validate.template.py` /
`cp_poll_validate.template.py`.

### The integration seam: register the object, not the fd

The chumicro-sockets wrappers (`_MpSocketWrapper`, the CP adapter) are
plain Python objects, so `select.poll().register(wrapper)` cannot work,
the poller needs the underlying stream-protocol socket whose C ioctl it
calls. So the one genuinely new requirement this design adds is that
**`chumicro-sockets` must expose the raw pollable socket** the runner
registers. A small accessor on the wrapper (return the underlying
`socketpool.Socket` / lwIP socket) settles it. The existing `fileno() ->
int` contract stays for any caller that genuinely wants an fd, but the
reactor does not use it.

### The unifying primitive: a wait source

Both wakeup reasons reduce to one question the runner asks each loop:
**"when, or on what, do I next need to wake?"** Two kinds of answer:

1. **Timer source.** "Wake me at tick `T`." Already present, every entry's
   `next_due_ms`. The runner can compute `min(next_due_ms)` across timed
   entries today.
2. **I/O source.** "Wake me when *this* socket is readable / writable."
   New, sourced from services that hold a live socket and have registered
   it with the runner's poller.

The runner collects both each loop, computes `timeout =
nearest_timer_deadline - now`, and blocks in `poll(timeout)`. It wakes on
the earliest of: a registered socket becoming ready, or the timeout
elapsing. When no sockets are registered, it `sleep`s the timeout instead
of polling.

### `timeout=0` is not the fix, it is the status quo

A trap worth naming. `poll()` buys two independent things:

- **Win A, one call learns readiness of N sockets**, instead of N
  `recv_into` calls that each `EAGAIN`. Scales as services are added.
- **Win B, the CPU sleeps until there is work.**

`poll(timeout=0)` buys only Win A. It returns instantly whether or not any
socket is ready, so `while True: poll(0); dispatch()` still pins the CPU.
Win B, the actual axis-2 pain, is untouched.

Win B requires `timeout > 0`, specifically a timeout *computed each loop*
as `nearest_timer_deadline - now`. That call idles the CPU until either a
socket becomes ready or the nearest timer is due, whichever first. Timers
never run late; the CPU idles in between. `timeout=0` is just the
degenerate "a timer is due right now" case.

| Strategy | Win A (multi-socket) | Win B (CPU sleeps) |
|---|---|---|
| N× `recv` + `EAGAIN` (today's leaf services) | no | no |
| `poll(0)` (the sockets-guide example, fd-based) | yes | no |
| `poll(nearest_deadline)` registering objects (reactor) | yes | yes |

Decision 0051 forbids `select.poll(timeout > 0)` in `libraries/*/src/`,
which is what makes the runner busy-spin. That rule is correct for **leaf
services** and wrong for **the loop itself**. The amendment re-scopes it
(see *The ADR tension*, below).

### How a service advertises I/O interest

Additive, optional, lifecycle-driven. A service that holds a socket
registers it with the runner's poller when it acquires the socket and
unregisters when it closes. Read-vs-write interest changes with the request
lifecycle (write while SENDING, read while RECEIVING), so the service calls
a `modify` at that one transition. `HttpClient` already tracks `_state` and
`_socket` (`requests/client.py:483`, `742`, `757`), so these calls land on
transitions it already has, with no per-tick work and no new allocation.

The exact API on the runner (`watch(sock, read=, write=)` /
`unwatch(sock)`, mirroring asyncio's `IOQueue.queue_read` /
`queue_write` / `remove`) is settled in the ADR. Whatever shape wins, it
registers an object and mutates the held poll map in place.

Services that own no I/O (a `Heartbeat`) register nothing and contribute
only their timer deadline.

### What the contract looks like, per kind of service

`check`/`handle` stay for everyone. The reactor adds optional socket
registration and changes nothing for services that don't own a socket.
The registration and the dispatch contract answer different questions:

- `check(now_ms) -> bool`: "is there work to do *this tick*?"
  (authoritative for whether `handle` fires).
- socket registration: "*what* should the loop wake on?" (advisory, it
  only feeds the poll set; `check` still gates dispatch in Model 1).

| Service kind | `check`/`handle` | Reactor interaction |
|---|---|---|
| Pure timer (`Heartbeat`, `period_ms`) | yes, unchanged | none, runner already knows `next_due_ms` |
| Polled input (button, encoder), period = scan/debounce window | yes | `period_ms` gating; `check` does edge detection, fires `handle` only on a transition |
| Socket only | yes | `watch(sock)` at connect, `unwatch(sock)` at close |
| Socket + regular timing | yes | `watch` + `period_ms` gating (runner owns the deadline) |
| Socket + dynamic timing (MQTT keepalive, per-request timeout) | yes | `watch` + a `next_deadline(now)` hint returning a tick or `None` |

`next_deadline` exists because a *dynamic* deadline (an MQTT keepalive that
resets on every publish, a request timeout that differs per request) can't
be a fixed `period_ms`. MQTT already computes these via `_deadline` /
`_next_ping_due_ticks` (`mqtt/client.py:1257-1276`); `next_deadline` would
surface the soonest of them. The runner's wait is then:

```
timeout = min(all next_due_ms, all next_deadline()) - now
ipoll(timeout)   # wakes on earliest of: any registered socket ready, or timeout
```

### Every service answers "when do I next wake?", and almost none answer "every tick"

The contract tightens once you notice what real `check()` methods actually
test. Nearly every one is a deadline or a readiness check:

- **Time checks** — "has my deadline passed?" MQTT keepalive
  (`now >= next_ping_due`), websocket pong timeout, per-request timeout, a
  heartbeat period. These belong to the period / `next_deadline` mechanism.
  The runner sleeps to the soonest one and calls `check` on wake only to
  confirm.
- **Readiness checks** — "do I have data, can I write?" `HttpClient.check`
  returning `self._state != IDLE` means "wake me when my socket moves." That
  belongs to the poller.

A polled input (button, rotary encoder) is the rare third kind, a
level-sensitive signal you learn about only by sampling. But even it isn't
"every tick", it is "every scan period", which is just a fast timer that
folds into `period_ms`. So the genuine "must run every literal tick, cannot
predict the next wake" case is **essentially empty** for well-built
services. The shapes that seem to want it resolve elsewhere: "push bytes as
fast as possible" (chunked TLS handshake, chunked send) is gated by socket
*writability*, so it is readiness-driven; "sample a sensor at max rate" is
high-rate periodic; "bit-bang a timing-critical protocol" is too
timing-sensitive for cooperative scheduling and should not be a runner
service at all.

The consequence for the contract: every service answers "when do I next
need to wake?" with a deadline or a socket, and `check()` demotes from "the
thing the loop consults to decide whether to sleep" to a cheap post-wake
confirmation gate. The handler-only-every-tick shape (`add(handler=fn)` with
no period) survives only as a legibility escape hatch and a backstop, not a
pattern to reach for. It forces `timeout=0` and defeats sleeping, and in
practice nothing well-built needs it, so the reactor's pressure to express
work as a deadline or a readiness gate costs almost nothing.

### Testing on CPython

CPython's `select.poll` needs a real OS fd, so `FakeSocket.set_fileno()`'s
arbitrary integer won't drive a real poller. Two clean options for host
tests: inject a fake poller into the runner (the same constructor-injection
posture as `ticks`), or back the fakes with a real `socketpair()`. The
injected-poller route keeps the unit tests allocation-free and
deterministic and matches how `FakeTicks` is already wired.

### Two increments, recommend Model 1 first

**Model 1, "sleep between ticks" (additive, low-risk).** Keep `tick()`
exactly as it is. Add a `Runner.wait(now_ms)` method that the application
calls in its own loop right after `tick()`:

```python
while True:
    now_ms = runner.tick()      # gate + batch-fire, unchanged
    runner.wait(now_ms)         # central poll(nearest_deadline - now_ms), sleeps the CPU
```

`wait` computes the timeout as `nearest_timer_deadline - now_ms` and blocks
in `poll(timeout)` over the registered sockets, or `sleep`s the timeout
when no socket is registered, instead of the loop immediately re-ticking.
The application still owns and drives the `while True:`; the runner only
supplies the "what should I block on now" computation. This is deliberate,
the runner must **not** own the loop. Decision 0051's transparency argument
(the developer can read, breakpoint, and single-step their own loop) is the
reason async/await was rejected, so hiding the loop inside a `Runner.run()`
would forfeit exactly what the runner pattern exists to protect. Services
keep `check`/`handle` unchanged. The win: when nothing is due and no socket
is ready, the CPU sleeps. The coarse `check()` gate stays as a backstop.
This delivers the power win with zero change to the service contract;
registration and `wait` are purely additive.

**Model 2, full reactor (later, if Model 1's coarseness bites).** `poll()`
readiness *drives* `handle()` dispatch per-socket, and `check()` retires in
favor of true readiness. Bigger: touches every I/O service's contract.
Defer until Model 1 proves insufficient.

### The ADR tension to resolve first

Decision 0051's *Forbidden in library code* list forbids
`select.poll(timeout > 0)` in `libraries/*/src/`, and `chumicro-runner`
lives there. A blocking central `poll`/`sleep` inside the runner therefore
violates the rule as written. The amendment (a new ADR, or an in-place 0051
amendment) must re-scope the rule:

> Leaf services never block the loop (`poll(timeout=0)`, no `sleep > 5ms`).
> The runner's single central wait (`Runner.wait`, called once per iteration
> by the application's own loop) *may* block until the next deadline. It is
> the loop's idle step, not a service stalling the loop. This is the one
> sanctioned blocking point, and it is exactly what bounds latency rather
> than harming it.

This is the asyncio-loop argument applied honestly: one `poll` with a
computed timeout, called by the application's loop between ticks, is not "a
library blocking the loop," it is the loop idling correctly. The
application still owns the `while True:`. Decision 0051's own asyncio
critique (blocking DNS) does not apply, because the reactor keeps the
existing non-blocking-DNS and chunked-yield machinery untouched. It changes
only *when the loop wakes*, not *how a service yields*.

### Open questions (axis 2)

- TLS-wrapped sockets: **resolved on hardware 2026-05-21, poll tracks the
  TLS buffer, it does not lie.** On all four boards a TLS-wrapped socket
  registered with `poll`, and the sharp test (read one byte to pull the
  rest of the record into the mbedTLS buffer, leaving the TCP fd quiet,
  then poll) returned *ready*, not empty. A 16-byte-buffer poll-gated read
  loop reported zero poll-lies (read the whole ~800-byte body, every
  `poll`-empty round genuinely had no data). Both runtimes' SSL sockets
  implement the poll ioctl to account for buffered decrypted bytes, so the
  reactor can trust `poll()` for `wss://` / `https://`. One CircuitPython
  wrinkle surfaced and is worth recording: a non-blocking `connect()` on a
  socketpool socket is unreliable (saw `ECONNABORTED`); the working shape
  is a blocking connect, then `setblocking(False)` for the poll/recv phase.
  Scripts in `.scratch/mp_tls_validate.template.py` /
  `cp_tls_validate.template.py`.
- **Resolved: the runner does not own the loop.** The application owns the
  `while True:` and calls `runner.tick()` then `runner.wait(now_ms)`. A
  `Runner.run()` that contained the loop is rejected, it would hide the
  loop inside the library and forfeit the read-and-single-step transparency
  Decision 0051 leans on. `wait` is a helper the app's loop calls, never the
  loop itself.
- Exact `wait` / `watch` / `unwatch` / `next_deadline` signatures, settled
  in the ADR against the tracemalloc test. Open detail: whether `wait`
  takes `now_ms` from `tick`'s return (one shared instant, minor staleness
  in the timeout bound, harmless because it is re-checked next tick) or
  captures its own time between ticks.

### Before code: four gaps, researched 2026-05-21

Three of the four are now resolved by research, one stays a design choice
the next session ratifies. None reopens the design.

- **How a decoupled service registers its socket (the crux). Recommend
  option B.** A service must not import `chumicro-runner` (Decision 0051's
  duck-typing), so it cannot call `runner.watch` directly. Two shapes were
  on the table. Option A injects a register/unregister callable into the
  service at construction, like the `ticks` injection. Option B has the
  service expose stable attributes (`io_socket`, `io_wants_read`,
  `io_wants_write`) that the runner reads and syncs into the poll set each
  `wait`. Recommend B, for a reason the gap-4 audit surfaced: app-initiated
  work between ticks (a `publish()`, a queued send) is not a socket event,
  so it cannot wake a sleeping loop on its own. The cooperative model saves
  it only if `wait` reads each service's *current* interest fresh every
  iteration, because the app code that queued the send ran in the loop body
  just before `wait`. Option B re-reads every loop and so catches it.
  Option A's event-driven registration misses it unless the service
  re-calls `modify`. B reads allocation-free (int and bool attributes, no
  fresh tuple), and the runner registers or modifies the poller only when
  the read interest differs from what is registered. Ratified in ADR 0080
  on 2026-05-22 (attribute names `io_socket`, `io_wants_read`,
  `io_wants_write`).
- **The runner must retain the service object. Confirmed.** `TaskHandle`
  stores only the bound `check`/`handle` methods (`runner/core.py:39-40`),
  not the service, and `add()` extracts those methods. `wait` needs to reach
  `service.next_deadline(now)` and the service's `io_*` attributes, so
  `add()` must keep the service reference and duck-type-probe it. A small,
  contained change to `add` and `TaskHandle`.
- **Production poll shape on device. Closed, validated 2026-05-21.** Tested
  `ipoll` (not `poll`) on one long-lived poller across 20 to 30
  register/unregister cycles, on all four boards. The combined wake works:
  an idle registered socket under a 400 ms cap blocked the full cap with
  zero ready (timer wins), and a live socket returned ready in 0 to 88 ms
  well under a 5 s cap (socket wins). Heap drift across the reused-poller
  cycles was 48 to 160 bytes, no leak. Use level-triggered `ipoll` (default
  flags), not `FLAG_ONESHOT`: `check` re-gates dispatch each tick, so a
  still-readable socket that wakes the loop is harmless and re-arming would
  be extra bookkeeping. Scripts in `.scratch/mp_ipoll_validate.template.py`
  and `.scratch/cp_ipoll_validate.template.py`.
- **Existing I/O services and every-tick reliance. Audited.** Every one of
  the four returns `True` whenever active: `requests` (`!= IDLE`,
  `client.py:634`), `mqtt` ("any non-terminal state is worth a tick",
  `client.py:860`), `websockets` (`!= CLOSED`), websockets server and
  `http_server` (`return True`). This is not a stall risk under Model 1,
  provided each service exposes its current socket interest (option B above)
  so `wait` wakes on readiness. The `http_server` accept loop is
  readiness-driven too: a listening socket polls readable when a connection
  is pending, so the listener registers for read. The only real requirement
  the audit produces: each service keeps `io_wants_write` set while it has
  outbound bytes queued, so a connected (and so writable) socket wakes the
  loop promptly to drain the send. No service needs a period added.

### Why not just adopt asyncio (and why we can't borrow it piecemeal)

This was reopened seriously, because asyncio already implements the wait we
want, in C, on both boards. The conclusion is to stay runner-shaped, and the
reasons sharpened with what the investigation found:

- **The expensive part is shared C either way.** The blocking wait is
  `select.poll().ipoll(dt)`, a C call. Our reactor calls the *same* C
  `ipoll`. We are not reimplementing the wait. asyncio's other C asset is a
  pairing-heap deadline queue (`TaskQueue`), which matters at hundreds of
  tasks. With 3 to 10 services the runner finds the soonest deadline with a
  linear `min(next_due_ms)` scan over `_entries`, microseconds over
  already-allocated storage. So "leverage the C engine" buys little we don't
  already get.
- **asyncio's I/O reactor is coroutine-bound.** Its socket-readiness wakeup
  only fires for a task parked on `await`: `await stream.read()` stores the
  *current task* against the fd in `IOQueue`, and readiness reschedules that
  task. A single `while True: check/handle` task never `await`s a socket, so
  `IOQueue` stays empty and the I/O sleep never happens. You cannot get
  asyncio's I/O reactor without writing coroutines. So "wrap asyncio but
  take it out of async" cannot deliver the I/O sleep, which is the prize.
- **`TaskQueue` cannot hold our handles.** The C `task_queue_push`
  (`modasyncio.c:115`) blind-casts the pushed object to `mp_obj_task_t *`
  and writes heap linkage into the embedded `pairheap` field, no type check.
  Pushing a `TaskHandle` is memory corruption. The heap is intrusive and
  only holds real `Task` objects, which wrap coroutines. So there is no
  borrow-just-the-scheduler seam either.

Net: both of asyncio's valuable C pieces are welded to `Task`/coroutine
objects. It is all-or-nothing (coroutines everywhere, or neither), and the
piece we actually need (the `ipoll` wait) we already call directly. The
remaining asyncio advantage is composition ergonomics for deeply chained
flows, which our single-in-flight workloads do not need and axis 1 covers.
A future contributor will ask this, so the ADR records it explicitly.

### The sleep is `ipoll` CPU-idle, not deep sleep

`ipoll(timeout)` idles the CPU (wait-for-interrupt) while RAM and the radio
stay powered. That is the runner's only sleep tool, and it is the right one
for the ms-to-low-seconds gaps a connected board sits in between socket
events and timer deadlines. The platform deep-sleep modes are a different
operating mode, not a deeper `wait`:

- **CircuitPython deep sleep** (`alarm.exit_and_deep_sleep_until_alarms`)
  powers down CPU and RAM and **restarts `code.py` from the beginning** on
  wake (only `alarm.sleep_memory` survives). Wifi is gone. Reconnect alone
  is seconds. It only pays off duty-cycling over minutes, and it is an
  application architecture (wake, work, tear down, deep-sleep, reboot), not
  a knob the runner turns mid-loop.
- **Light sleep** (CP `alarm.light_sleep_until_alarms`, MP
  `machine.lightsleep`) resumes in place and keeps wifi, but the CP docs
  note "in some cases there may be no decrease in power consumption," and it
  is a no-op while USB-connected (it keeps the host link for ctrl-C and
  CIRCUITPY edits). Marginal for our connected use, and not for ms sleeps.

The hard constraint behind this: **a board that keeps a live connection open
cannot get down to microamps.** The best it can do is idle the CPU between
events while the radio stays powered, which is what `ipoll` already does.
Microamp sleep requires dropping the connection and waking through reboots, a
different application shape.
So the reactor's honest claim is "stop the busy-spin, idle the CPU between
events for a connected board," not "deep sleep." A two-tier handoff where
the runner drops to `alarm` light-sleep was floated and rejected: it does
nothing useful while connected.

### Non-pollable inputs and platform leverage (stays out of runner core)

A button or other GPIO input is not a pollable stream, so `ipoll` cannot
wake on it. The portable answer is a periodic scan whose period is the
debounce window (10 to 20 ms), which caps how long the loop sleeps while the
input is registered and gives the input a worst-case latency of one scan.
The scan period *is* the debounce, so a single sample per scan suffices.
This is the "polled input" row in the contract table. The button service:

```python
class Button:
    # A debounced push-button as a runner service.  The pin reader is
    # injected (Decision 0010) so the same class runs on every runtime.
    # check() does edge detection so handle() fires on the press, not for
    # every tick the button is held.  now_ms is unused: a button has no
    # deadline of its own, the runner's period_ms gates the scan.
    def __init__(self, read_pin, *, on_press=None):
        self._read_pin = read_pin
        self._on_press = on_press
        self._was_down = False
        self._fire = False

    def check(self, now_ms):
        down = self._read_pin()
        self._fire = down and not self._was_down
        self._was_down = down
        return self._fire

    def handle(self, now_ms):
        if self._fire and self._on_press:
            self._on_press()
```

Registered as `runner.add(Button(read_pin, on_press=fn), period_ms=20)`.

Platforms offer better than a scan for inputs, but none of it is portable,
so it lives in a future digital-input library's per-runtime adapters, never
in `chumicro-runner` core (which stays on the `ipoll` + ticks common
subset). Confirmed on the actual boards:

- **CircuitPython** ships background-capture modules: `keypad` (scans and
  debounces in the background, drains an event queue), `countio` (hardware
  edge counter, PCNT-backed on esp32), `rotaryio`, `pulseio`. The loop reads
  accumulated events on wake and can sleep to its real deadline instead of a
  scan cadence.
- **MicroPython** has no `countio`, but exposes the hardware directly:
  `rp2.PIO` / `rp2.StateMachine` / `@rp2.asm_pio` on the Pico W, and
  `esp32.PCNT` on the Lolin S2 (esp32-s2). Both verified present on the
  plugged-in boards. These count edges CPU-free and handle high rates.
- **ISR is the MicroPython-only fallback**, for a low-rate input or when the
  finite hardware units (8 rp2 PIO state machines, a few esp32 PCNT units)
  are exhausted. A `machine.Pin.irq` handler that increments a counter
  re-implements `countio`'s background-capture idea (the ISR body is a
  small-int increment, allocation-free, so it is ISR-safe). Note a bare ISR
  does **not** wake a blocked `ipoll`: the interrupt wakes the WFI, the ISR
  runs, but `poll` re-probes, finds no registered object ready, and sleeps
  again until its timeout. To wake the loop promptly you also register a
  tiny self-wake pollable object (an `ioctl(MP_STREAM_POLL)` that reports
  readable when the ISR set a flag), the embedded self-pipe trick. That is
  reserved for a genuine sub-scan-latency need, as a documented MP-only
  exception, since CircuitPython has no user ISRs and the project bans them
  by default (Decision 0014).

## Axis 1, result composition (callbacks; futures rejected)

Settled 2026-05-21: callbacks are the result-composition mechanism, and
futures are dropped. `requests` 0.10.0 added `on_done` (a one-shot
completion callback; ADR 0040 §10), and the optional fluent
`http.get(url).on_reply(fn)` skin is a roughly five-line addition on
`RequestHandle` (store the callback, `return self`, fire immediately if
already `done`). Both are callback-based and lean.

**Futures were considered and rejected on memory grounds.** A future is a
callback plus retained state: a state slot, a result slot, an error slot,
and a callback list, per future, with a new future allocated for every
`.then` in a chain. Libraries cannot use `__slots__` here (MP and CP do not
implement it), so each future also carries its instance dict. That
structure churns the non-compacting heap, and the resizing callback list is
the worst of it, exactly where a callback churns almost nothing. A
synchronously-resolved chain also grows the stack with its depth, on boards
whose stack is a few KB. A future is never lighter than the callback it
wraps, so on a 256 KB board the callback is the floor and the future only
adds cost. The composition ergonomics do not earn that cost here, the more
so because `HttpClient` is single-in-flight (ADR 0040 §1), so the
concurrent `gather` / `race` flows futures are best at cannot run anyway.
When a multi-step flow needs sequential chaining, a callback that issues the
next request, or the `.on_reply` skin, covers it without the future's heap.

This closes axis 1. No `Future`, no `.then`, no `libraries/futures`, and no
further design here.

## Sequencing

1. **ADR for axis 2**, done 2026-05-21: [Decision 0080](../../decisions/0080-runner-reactor.md)
   records the central-wait model, the register-the-object primitive, the
   `next_deadline` hint, and the chumicro-sockets raw-socket accessor, and
   re-scopes Decision 0051's leaf-vs-loop blocking rule.
2. **Device check**, done 2026-05-21. `poll()` on a registered socket
   object behaves on all four boards for both plain TCP and TLS, including
   the TLS-buffer-vs-poll question (poll tracks the buffer). See the axis-2
   runtime table and open-questions notes above.
3. **chumicro-sockets raw-socket accessor**, the small wrapper addition the
   runner registers.
4. **Model 1 reactor**, `Runner.wait(now_ms)` (a helper the app's loop
   calls, not a loop-owning `run()`) + `watch`/`unwatch`, additive. Inject a
   fake poller for host tests. Heap-drift test per the Decision 0051
   tracemalloc standard.
5. **Axis 1, settled**, callbacks are the result mechanism (`on_done`
   shipped, optional `.on_reply` skin). Futures are rejected on memory
   grounds, see Axis 1. Nothing further to build here.

## Status

Design captured 2026-05-21, corrected the same day after reading the MP and
CP asyncio cores and CP's `socketpool`/`select` C source: both runtimes
poll sockets by registering the object, so there is no CircuitPython
degrade path and no fd-list primitive. Validated on hardware the same day
across all four boards (Pico W + Lolin S2, MicroPython and CircuitPython):
object registration, real readiness, idle `poll` blocks the full timeout
(CPU sleeps), negligible heap drift, and poll tracks the TLS buffer rather
than lying. The design's load-bearing claims are device-confirmed and the
axis-2 ADR ([Decision 0080](../../decisions/0080-runner-reactor.md)) has
landed. A second device pass validated the production poll shape (`ipoll`
on one reused poller, the combined socket-or-timer wake) on all four boards,
and the four pre-code gaps are researched (see "Before code" above): the
registration mechanism is recommended (option B, runner reads stable `io_*`
attributes), the `TaskHandle`-retains-service change is confirmed, and the
existing-service audit found no stalls.  Option B was ratified in ADR 0080
on 2026-05-22, and the implementation landed the same day across seven
commits: the `chumicro-sockets` `pollable_of` helper; the Model 1 reactor
on `Runner` (`Runner.wait` + service-interest read loop + optional
`next_deadline` + `FakePoller` host-test seam); each I/O service exposing
`io_socket` / `io_wants_read` / `io_wants_write` and an optional
`next_deadline` (`requests`, `mqtt`, `websockets`, `http_server`); the
README four-service example using `runner.wait(now_ms)`; and the
tracemalloc heap-drift test on `tick` + `wait` cycles (0.26 bytes per
iteration on Python 3.14, well under the 2 KiB threshold).

The `requests` callback (axis 1, rung 2) shipped in 0.10.0 ahead of this
workstream; the optional `.on_reply` fluent skin on `RequestHandle`
remains unbuilt and is intentionally not on the punch list — `on_done`
covers the same use case.

Wrapper-mediated hardware validation closed 2026-05-22 across all four
boards (Pi Pico W + Lolin S2, MicroPython + CircuitPython).  A
``runner_reactor_probe`` project deployed via the workspace-template
exercises ``chumicro_sockets.tcp_client_socket(...)`` with
``select.poll().register(pollable_of(wrapper), ...)``: an idle wrapper
blocks the full 400 ms cap with zero ready (timer wins), a live wrapper
becomes ready in 22-28 ms (socket wins), and 20 register/poll/recv
cycles report drift of 0-160 bytes — within the 48-448 band the
2026-05-21 raw-socket runs produced, so the wrapper layer adds nothing
the poller can see.

Workstream closed.
