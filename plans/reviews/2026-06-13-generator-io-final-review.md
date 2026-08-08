# Final review — generator I/O surface (2026-06-13)

Third review pass, after the post-fix remediation (Phases 0 + A–D) and the
generator-protocol redesign landed. Manual deep read (the clean-room
`audit-branch` pipeline is broken on a CLI flag — `--safe-mode` removed in
CLI 2.1.153; tracked separately). Change-set `c3b6674f..HEAD`, focused on the
unreviewed generator-networking I/O surface.

Lens: bugs, broken caller contracts, hollow coverage, embedded correctness
(hot-path allocation, ≤5 ms tick, sender-controlled caps, CP/MP divergence).

## Method + coverage

Every finding re-derived from source — file:line cited, checkable. Reference
runtime C source (`.tools/`) consulted for the two cross-runtime claims
(errno aliasing, deque overflow).

- **Deeply read this pass:** `runner/_generator.py`, `runner/core.py`
  (tick/wait/dispatch), `sockets/generators.py`, `requests/generators.py`,
  `websockets/_session.py` (next_message + inbound deque), `deploy/source_minify.py`,
  `checks/rules/chu033.py`, `runner/tests/test_generator.py`,
  `sockets/tests/test_generators_pytest.py`.
- **Verified clean (no finding):** errno `.args[0]` vs `.errno` divergence,
  websockets drop-oldest deque, `next_message` every-tick resume, source_minify
  equivalence guard, `add_generator` priming-raise ordering. Detail under
  "Verified clean" below.

## Severity summary

| # | Sev | Area | One-line |
|---|-----|------|----------|
| G1 | MEDIUM | runner | `io_error` (POLLERR/POLLHUP) dispatch is unisolated — a generator that lets `OSError` propagate crashes the whole reactor, asymmetric with the L2 tick-path hardening just shipped |
| G2 | LOW-MED | sockets | `send_all`/`recv_exact` re-slice `view[offset:]` every EAGAIN iteration (memoryview churn); `send_all` docstring claims "zero-allocation"; the tracemalloc test that should pin this measures net-retained, so it can't catch the churn |
| G3 | LOW | requests | `fetch(timeout_ms=…)` bounds only the receive loop — DNS/connect/TLS are unbounded, and connect is the phase most likely to hang on real hardware |
| G4 | LOW | checks | CHU033 bans async in `workbench/` (host-only) but its rationale says "device-bound and cross-runtime"; `scripts/` (also host-only) is not in scope — scope/rationale mismatch |

---

## G1 — MEDIUM — unisolated `io_error` dispatch crashes the reactor

`Runner.tick()` isolates a faulting handler ([core.py:479](../../libraries/runner/src/chumicro_runner/core.py#L479) `except Exception` → count + `on_handler_error`, reactor survives). `Runner.wait()` does **not**: the POLLERR/POLLHUP path calls `_dispatch_io_error` ([core.py:572](../../libraries/runner/src/chumicro_runner/core.py#L572)) which calls `service.io_error(...)` with no try/except ([core.py:597-599](../../libraries/runner/src/chumicro_runner/core.py#L597)).

For a generator service, `io_error` throws `OSError` into the generator ([_generator.py:153](../../libraries/runner/src/chumicro_runner/_generator.py#L153)). If the generator does not catch it, `_advance_throw` marks done **and re-raises** ([_generator.py:194-196](../../libraries/runner/src/chumicro_runner/_generator.py#L194)) → the `OSError` escapes `wait()` → the `while True: tick(); wait()` reactor loop dies.

**Reachability is real.** `poll()` always reports POLLERR/POLLHUP (can't be masked out), so any generator blocked in `recv_until` / `recv_exact` / `fetch`'s recv loop gets the throw when the peer sends RST (server crash, LB drop, firewall reject — common on flaky embedded WiFi). The throw lands at the `yield` *inside* the helper's `except OSError: if EAGAIN` block, which cannot catch its own re-thrown error — it propagates out of the helper, and the documented happy-path example (`response = yield from get(...)`, no try/except) crashes the reactor on peer reset. Clean FIN is fine (POLLIN + `recv→0`, handled); only RST/error hits this.

**Known gap, not closed.** [test_generator.py:310-324](../../libraries/runner/tests/test_generator.py#L310) (`test_io_error_unhandled_propagates_done`) asserts the propagation and comments "the error currently surfaces to the io_error caller … a future iteration may log + swallow." This change-set is that iteration: the generator wrapper is the first `io_error` impl that can raise (regular services treat it as a clean state-transition hook), so the pre-existing unisolated dispatch is newly load-bearing. The L2 work hardened the symmetric tick path; this is its other half.

**Fix.** Isolate the `io_error` call in `wait()` the way `tick()` isolates `handle()`: wrap `_dispatch_io_error`'s `handler(now_ms, eventmask)` in `try/except Exception` → `handler_errors += 1` + `on_handler_error`. Keep the wrapper's re-raise (so the runner can observe + count the fault); fix at the runner level. `test_io_error_unhandled_propagates_done` then flips from "asserts crash" to "asserts reactor survives + count incremented." Small, behavior-only + one test, VERSION patch on runner; fold into the RUN-1 real-board bake.

## G2 — LOW-MED — EAGAIN-loop memoryview churn + a test that can't see it

`send_all` re-evaluates `view[offset:]` every loop iteration ([generators.py:157](../../libraries/sockets/src/chumicro_sockets/generators.py#L157)); so does `recv_exact` ([generators.py:261](../../libraries/sockets/src/chumicro_sockets/generators.py#L261)). A memoryview slice allocates a new memoryview object (no buffer copy, but a heap object). On EAGAIN the slice is built, `send`/`recv_into` raises, the slice becomes garbage, then the loop re-slices on the next resume — one transient memoryview **per backpressured tick**. For a large or slow-link send/recv that is exactly the steady-state per-tick churn the zero-allocation rule targets (GC pressure → fragmentation → tick-budget risk on MP/CP).

`send_all`'s docstring claims "the helper allocates the wait once outside the loop so steady-state iterations are zero-allocation" ([generators.py:135-137](../../libraries/sockets/src/chumicro_sockets/generators.py#L135)). The wait *is* hoisted; the slice is not — the conclusion is false.

The dedicated guard does not catch it. [test_generators_pytest.py:34-43](../../libraries/sockets/tests/test_generators_pytest.py#L34) reads `tracemalloc.get_traced_memory()[0]` **after `gc.collect()`** — net-retained bytes, not churn. The `view[offset:]` transient is freed by refcount immediately, so net-retained is ~0 and the `< 2048 bytes` assertion passes regardless. Its docstring claims it pins "nothing per iteration" and would surface "a regression that allocates inside the EAGAIN branch" — it would only catch a *leak*, not transient churn. AGENTS.md specifies this contract is verified with `gc.mem_alloc()` bracketed by `gc.disable()` (captures churn), not tracemalloc-after-collect.

**Fix.** Hoist the slice, re-slice only on progress (EAGAIN reuses it):
```python
chunk = view
while offset < total:
    try:
        sent = sock.send(chunk)
    except OSError as error:
        if error.args[0] == errno.EAGAIN:
            yield write_wait
            continue
        raise
    if sent == 0:
        raise OSError("peer closed during send")
    offset += sent
    chunk = view[offset:]
```
Same shape for `recv_exact`. Then the docstring is true. Separately, strengthen the test to count allocations (a `gc.mem_alloc` lane, or a tracemalloc allocation-count snapshot) so it actually pins the EAGAIN-branch contract — otherwise it is a false guard. Practical impact is bounded for small fetches (1–2 send iterations); it's the public helper's large/backpressured use and the false claims that earn the fix.

## G3 — LOW — `fetch` timeout doesn't cover connect

`fetch`'s deadline check sits only inside the recv loop ([requests/generators.py:165](../../libraries/requests/src/chumicro_requests/generators.py#L165)). `connect` ([requests/generators.py:159](../../libraries/requests/src/chumicro_requests/generators.py#L159)) runs first and is unbounded by `timeout_ms` — the connectors take no timeout ([sockets/__init__.py:180](../../libraries/sockets/src/chumicro_sockets/__init__.py#L180), [:217](../../libraries/sockets/src/chumicro_sockets/__init__.py#L217)). The docstring scopes it narrowly ("Deadline for the receive phase across all hops"), so it is not a contract break — but a user reaches for `timeout_ms` precisely to bound a flaky call, and the phase *most* likely to hang (TCP connect to an unreachable host) falls back to the OS connect timeout (tens of seconds to minutes). DNS `getaddrinfo` and the MP/CP TLS handshake block the whole reactor for their duration and are likewise uncapped. This is a real ease-of-use sharp edge, not a crash. A full fix threads a deadline through `connect` (it can't intercept a `yield from`); the cheap interim is a louder docstring that `timeout_ms` excludes connect and that DNS/TLS stall the reactor.

## G4 — LOW — CHU033 scope vs rationale

CHU033 scopes the async ban to `("libraries", "support", "workbench")` ([chu033.py:35](../../workbench/checks/src/chumicro_checks/rules/chu033.py#L35)), but its rationale says "banned in device-bound and cross-runtime code" ([chu033.py:5](../../workbench/checks/src/chumicro_checks/rules/chu033.py#L5)). `workbench/` is host-only CPython (AGENTS.md: library rules don't apply there), and `scripts/` — also host-only — is **not** in scope. So async is banned in one host-only tree and allowed in the other, and the stated rationale doesn't cover the workbench inclusion. Either narrow scope to the device + cross-runtime trees (drop workbench, keep the `functional_tests` carve-out moot), or keep the codebase-wide ban and update the rationale + add `scripts/` for consistency. A deliberate call for the author, not a bug.

## Verified clean (checked, no finding)

- **errno `.args[0]` vs `.errno`.** New generators use `error.args[0] == errno.EAGAIN`; the rest of the stack (`requests/client.py`, `mqtt`, `websockets`) uses `.errno`. Confirmed behaviorally identical on all three runtimes: MicroPython aliases `.errno` to `args[0]` ([objexcept.c:286-288](https://github.com/micropython/micropython/blob/v1.26.0/py/objexcept.c)), CircuitPython does the same under `MICROPY_CPYTHON_COMPAT` ([objexcept.c:343-344](../../.tools/circuitpython-10.2.0/py/objexcept.c)), CPython populates both for real non-blocking sockets (`BlockingIOError`). `.args[0]` is marginally more robust (works for a 1-arg `OSError` on CPython too). Nit only: match the `.errno` house idiom, or leave a one-line note on the deliberate choice.
- **websockets inbound drop-oldest.** Bare 2-arg `deque((), maxlen)` ([_session.py:427](../../libraries/websockets/src/chumicro_websockets/_session.py#L427)) is valid on MP/CP (`mp_arg_check_num(…, 2, 3, …)`) and drops the oldest on overflow with flags=0 ([objdeque.c:107-118](https://github.com/micropython/micropython/blob/v1.26.0/py/objdeque.c)) — matching CPython `maxlen`. The comment is correct.
- **`next_message` every-tick resume.** `_INBOUND_WAIT` carries no socket/deadline so the wrapper resumes it each tick, but `wait()` still blocks on the *session's* own socket registration — no busy-spin. The no-own-socket choice (avoids colliding with the session's poll-set entry) is sound.
- **source_minify equivalence guard.** The line-based comment scanner can corrupt multi-line strings, but `strip_source` compares code signatures (docstrings removed) and ships the original verbatim on any mismatch ([source_minify.py:53](../../workbench/deploy/src/chumicro_deploy/source_minify.py#L53)). Line-count is invariant (one output line per input line), so device tracebacks + on-device test splitting keep correct line numbers. Robust.
- **`add_generator` priming-raise.** `_task_handle` is set ([core.py:360](../../libraries/runner/src/chumicro_runner/core.py#L360)) before `start()` ([core.py:362](../../libraries/runner/src/chumicro_runner/core.py#L362)), so a generator that raises on priming cleanly self-removes — no lingering entry.

## Recommendation

G1 is worth doing now — it completes the L2 reactor-isolation hardening and is a small, well-bounded change (runner + one test, real-board bake). G2 is a two-line code fix per helper plus a test strengthen; do it with G1 since both touch the generator I/O contract. G3/G4 are doc/scope calls for the author.
