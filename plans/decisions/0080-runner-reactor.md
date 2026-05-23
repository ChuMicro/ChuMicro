# Decision 0080: Runner reactor, one central poll that sleeps until work

Status: `accepted`
Date: `2026-05-21`
Related: Decision 0014 (runner contract), Decision 0051 (runner-shaped policy and the `poll(timeout > 0)` ban this re-scopes), Decision 0010 (constructor injection), Decision 0031 (chumicro-sockets protocol).

## Context

The runner busy-polls. The application loop is `while True: runner.tick()`, which spins as fast as the CPU allows. An I/O service's `check()` reports "I am in flight," not "my socket has data" (`requests/client.py:632`), so mid-request the loop calls `handle()`, `recv_into` raises `EAGAIN`, and it re-spins. The CPU never sleeps, which on battery is the difference between mA and µA. Decision 0051 bans `select.poll(timeout > 0)` in `libraries/*/src/`, which is correct for leaf services but forces the runner itself to busy-spin.

Device validation on all four boards (Pico W and Lolin S2, each in MicroPython and CircuitPython) confirmed that `select.poll` registering the socket **object** reports real readiness and idles the CPU until a socket is ready or a timeout elapses, on every runtime, including TLS sockets (poll tracks the mbedTLS buffer, it does not lie).

## Decision

### One central wait, owned by the loop, not the library

Leaf services never block the loop. The runner exposes **one** sanctioned blocking point, `Runner.wait(now_ms)`, which the application calls in its own loop right after `tick()`:

```python
while True:
    now_ms = runner.tick()      # gate + batch-fire, unchanged
    runner.wait(now_ms)         # idle until a registered socket is ready or the next deadline
```

`wait` computes `timeout = min(all next_due_ms, all next_deadline()) - now_ms` and blocks in `ipoll(timeout)` over the registered sockets, or `sleep`s the timeout when no socket is registered. The application owns the `while True:`. The runner must **not** own it (no `Runner.run()`): hiding the loop forfeits the read-and-single-step transparency the runner pattern exists to protect.

`ipoll`, not `poll`: `poll` allocates a fresh list every call, `ipoll` reuses one internal tuple and allocates nothing steady-state. `ipoll` exists on MicroPython and CircuitPython but not on CPython, so the on-device path uses `ipoll` and host tests inject a fake poller (constructor injection, like `ticks`).

### Services expose I/O interest as attributes; the runner reads each wait

A socket-owning service exposes three duck-typed attributes — `io_socket` (the underlying pollable socket, or `None`), `io_wants_read`, and `io_wants_write`. The runner reads them for every entry each `wait()` and registers, modifies, or unregisters the poller only when the read interest differs from what is currently registered. Reads are allocation-free (attribute lookups on already-allocated state).

Read-on-wait beats event-driven `watch` / `unwatch` calls because the latter miss app-initiated work queued *between* ticks: a `publish()` that queues outbound bytes between tick N and N+1 does not itself fire a `modify`, so a sleeping `wait()` would not know to wake on writability. Reading fresh every iteration catches it, because the app code that queued the send ran in the loop body just before `wait`.

The runner registers the **socket object**, not a fd: `fileno()` is `-1` or absent on CircuitPython radio sockets and rp2 MicroPython sockets, but the object is pollable through the runtime's stream `ioctl` on all three runtimes. `chumicro-sockets` exposes an accessor returning the underlying pollable socket, since its wrappers are plain Python objects the poller cannot register directly.

### Dynamic deadlines via an optional duck-typed hint

A service whose next deadline is not a fixed period (an MQTT keepalive that resets on every publish, a per-request timeout) exposes `next_deadline(now_ms) -> int | None`, the earliest tick it must run even if no I/O arrives. The runner reads it in `wait` alongside each entry's `next_due_ms`. Optional and duck-typed, the same posture as `check`/`handle`.

### check/handle unchanged, readiness only decides when to sleep

`check(now_ms) -> bool` stays the authoritative dispatch gate. The wait sources (sockets, deadlines) only decide *when the loop stops sleeping*, not *whether a handler fires*. After waking, `tick()` runs and `check()` confirms. This is Model 1. Model 2 (poll readiness drives dispatch per-socket and `check` retires) is deferred until Model 1's coarseness is shown to bite.

## Rejected

- **Adopt asyncio.** Its I/O reactor is coroutine-bound (readiness reschedules the `await`-ing task, so no coroutine means no I/O sleep), and its C `TaskQueue` is an intrusive heap that blind-casts pushed objects to the `Task` struct, so neither piece can be borrowed without going all-in on coroutines. The wait we actually need is `select.poll().ipoll`, a C call we already make directly, and with 3 to 10 services a linear `min(next_due_ms)` scan replaces the task heap. Re-affirms Decision 0014 and 0051 on shape, now with the C-engine evidence.
- **`Runner.run()` owning the loop.** Forfeits the transparency the pattern protects.
- **An fd-list primitive (`poll.register(fileno())`).** Breaks on CircuitPython radio and rp2 sockets, which have no usable `fileno`.
- **Event-driven `watch` / `unwatch` registration calls (option A).** Services calling `runner.watch(sock, read=, write=)` at lifecycle transitions miss app-initiated work queued *between* ticks: a `publish()` that queues bytes does not fire a `modify`, leaving a sleeping `wait()` stuck until its timer deadline. Read-on-wait via stable `io_*` attributes catches it because the runner re-reads service interest fresh every loop.
- **Folding dynamic deadlines into the runner's `next_due_ms`.** Couples a service to its own `TaskHandle`. The duck-typed `next_deadline` hint keeps the service decoupled.
- **Platform deep/light sleep as a runner tier.** Deep sleep reboots and drops wifi, and light sleep is a no-op while USB-connected and often saves nothing. A board that keeps a live connection open cannot get down to microamps. The best it can do is idle the CPU between events while the radio stays powered, which is what `ipoll` already does. Microamp sleep means dropping the connection and waking through reboots, a separate application architecture that is out of the runner's scope.

## Consequences

- Decision 0051's `poll(timeout > 0)` ban is edited in place to carve out the runner's single central wait. The leaf-service ban stands.
- `chumicro-runner` gains `wait`, a min-deadline scan, a per-loop read of each service's `io_*` interest, and an optional `next_deadline` read. A heap-drift test must show zero steady-state allocation in the wait path (Decision 0051's tracemalloc standard).
- `chumicro-sockets` gains an accessor returning the underlying pollable socket.
- Long-lived I/O services (`requests`, `mqtt`, `websockets`, `http_server`) expose `io_socket` / `io_wants_read` / `io_wants_write` attributes and an optional `next_deadline`. Additive, no API break.
- Non-pollable inputs (buttons, encoders) are serviced by a periodic scan whose period is the debounce window, which bounds how long `wait` sleeps while the input is registered. Platform input peripherals (`keypad`, `countio`, rp2 PIO, esp32 PCNT) live in a future digital-input library's per-runtime adapters, never in runner core.
- `AGENTS.md`'s runner-shaped rule is updated for the central-wait carve-out.
