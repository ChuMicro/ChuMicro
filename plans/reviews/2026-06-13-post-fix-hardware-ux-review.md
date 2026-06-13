# Post-fix critical review — hardware + ease-of-use (2026-06-13)

Second review pass, after the deep-code-review remediation (Phases 1-9) landed.
Lens: *will this bite on the real hardware* (Pico W / ESP32-S2, 256 KB RAM,
CircuitPython **and** MicroPython) and *can we make it easier for the user*, with
extra scrutiny on the code the remediation just changed.

## Method + coverage (read this before trusting the table)

Every CRITICAL/HIGH/MEDIUM below was re-derived from source — file:line cited so each
is checkable. Coverage is uneven and that matters:

- **Deeply read this pass:** `runner/core.py`, `sockets/_adapters/mp.py`,
  `sockets/_connector.py`, `logging/core.py`, `mqtt/client.py` (full),
  `msgpack/_pure.py`, `websockets/_session.py`, `requests/client.py`,
  `workspace/cli/_common.py`.
- **Covered by the workbench/UX agent** (headline `--non-interactive` claim
  re-verified by hand against `_common.py`): `deploy/*_transport.py`, `firmware.py`,
  `workspace/cli/deploy.py`, the recovery machinery.
- **NOT read this pass — follow-up needed:** `websockets/_wire.py` (WS-1 unmask
  correctness), `http_server/server.py` + `_wire.py` (HTTP-1/HTTP-3 the *parser* side),
  `wifi/service.py` + `config.py` (WIFI-1/2 beyond docstrings), `ntp/core.py`,
  `timing/heartbeat.py`, `kvstore`. The five library agents that would have covered
  these died on a transient API rate limit. WS-1 and HTTP-3 are the notable gaps —
  re-run those two reads before calling the review complete.

## Severity summary

| # | Sev | Area | One-line |
|---|-----|------|----------|
| L1 | HIGH | logging | `message % args` interpolation unguarded — a format/arg mismatch crashes the caller, breaking the documented "logging never crashes the app" contract |
| L2 | MEDIUM | runner | re-entrancy `RuntimeError` is now swallowed by RUN-1's `except Exception`; a handler that re-enters `tick()` gets a silent counter bump, not a loud crash |
| L3 | MEDIUM | msgpack | container element count bounded only by remaining buffer bytes (~8× memory amplifier); fine for trusted config, an OOM vector if fed untrusted wire data |
| H1 | MEDIUM | cross-cutting hardware | MP TLS handshake and CP wifi connect block the whole cooperative reactor for the full round-trip (seconds); documented in docstrings, invisible in the user guide |
| W1 | HIGH | workbench | `install-firmware` no-runtime coaching cites flags that don't exist (`--board`/`--address`/`--list-boards`), omits required `--method` |
| W2 | HIGH | workbench | `deploy` leaks raw tracebacks on common physical failures; only `deploy-example` catches-and-classifies |
| W3 | HIGH | workbench | `deploy --all-devices` aborts the whole loop on the first device's transport error — opposite of its `--help` |
| W4 | HIGH | workbench | `install-firmware` / `reset-board` leak raw tracebacks on flash/wipe failure; no download progress on a multi-MB flash |
| W5 | HIGH | workbench | mpremote 120 s timeout classifies as `UNKNOWN`+retryable → retries a wedged board into a ~6-min hang |
| W6 | HIGH | workbench | `--non-interactive` auto-detect is documented but unwired on `deploy` → `EOFError`/hang in CI |
| W7 | MEDIUM | workbench | DEP-3 wrong-board refusal reports a count not paths, and false-refuses one real board + one stale `CIRCUITPY 1` |
| W8 | MEDIUM | workbench | hard-reset refusal (TEST-4) scans only the entrypoint file, not the import graph the boot-shim runs |
| W9 | LOW | workbench | firmware path lacks a closed-set failure-kind classifier (the gap that lets W2/W4 exist) |

## Library findings (this pass, source-verified)

### [HIGH] L1 — logging interpolation can crash the caller — `libraries/logging/src/chumicro_logging/core.py:124`

`Logger.log` gained `*args` + `message % args` after the level gate (the LOG-1
change). The interpolation at line 124 sits **outside** the `try/except` that wraps
`handler.emit` (lines 126-129). A format/arg mismatch — `log.info("%d", "x")`,
`log.warning("%d %d", 5)`, `log.error("done %s")` with no arg-but-a-stray-`%` is
safe (the `if args:` guard skips zero-arg calls, line 123) — raises `TypeError`/
`ValueError` straight out of `log()` into the caller.

- **Hardware impact:** logging is called from everywhere, including error/except
  paths. A bad format string in an error log *replaces* the original error with a
  formatting crash. Under the runner the exception is at least isolated (counted in
  `handler_errors`) but the log line is lost and the service's tick aborts; called
  from non-runner code it crashes outright. The class docstring (lines 60-62)
  explicitly promises "Logging must not crash the application that uses it" — L1
  breaks that promise, and it's a regression: before LOG-1 callers passed
  pre-formatted strings, so no interpolation could fail inside the logger.
- **Fix:** guard the interpolation; fall back to a non-crashing rendering and
  (optionally) count it:
  ```python
  if args:
      try:
          message = message % args
      except (TypeError, ValueError) as format_error:
          message = f"{message!r} % {args!r} (log-format error: {format_error})"
  ```

### [MEDIUM] L2 — re-entrancy guard's RuntimeError is swallowed by fault isolation — `libraries/runner/src/chumicro_runner/core.py:402-405` + `446-462`

`tick()` rejects re-entrancy with `raise RuntimeError(...)` (line 403) before the
`try`. But the dispatch loop's `except Exception as error` (line 448) catches
`Exception` — and `RuntimeError` is an `Exception`. So when a handler calls
`runner.tick()` (directly, or via a helper that drives the runner), the inner call's
RuntimeError propagates into the outer handler-call site, gets caught, counted in
`handler_errors`, and the reactor continues. The guard still *prevents* the
re-entrancy (the inner tick did no work), but the loud signal is gone.

- **Hardware impact:** a developer who accidentally drives the runner re-entrantly
  sees only a silently climbing `handler_errors` and a handler that mysteriously
  returns early — no traceback, no crash. Before RUN-1 the RuntimeError propagated
  out of `tick()` and crashed visibly, which is the correct teaching signal for a
  programming error. RUN-1's isolation (right for *service* faults) now also muffles
  this *programmer* fault.
- **Fix:** give the guard a dedicated exception type and re-raise it past the
  isolation, e.g. `class ReentrantTickError(RuntimeError)` raised by the guard, and at
  the top of the `except Exception as error` block: `if isinstance(error,
  ReentrantTickError): raise`. Genuine handler faults stay isolated; the re-entrancy
  bug stays loud.

### [MEDIUM] L3 — msgpack bounds container *breadth* only by buffer size — `libraries/msgpack/src/chumicro_msgpack/_pure.py:318, 333`

The decoder is otherwise well-guarded: depth cap `_MAX_DEPTH = 8` (line 169),
`_bounded_end` slice checks (line 187), and `_decode_array`/`_decode_map` reject a
claimed length past the *remaining buffer* before allocating. But "past the remaining
buffer" is the only bound: an N-byte input can legitimately drive an N-element `list`
(`0xdc 0xff 0xff` + 65535 fixint bytes → a 65535-element list). On a 256 KB board a
list is ~8 bytes/slot of pointers, so N input bytes → ~8N resident — a memory
amplifier. MSG-1's exception tuple is correct and verified (`hasattr(struct, "error")`
guard, IndexError on every runtime, MP's struct ValueError already satisfies the
contract).

- **Hardware impact:** for the documented threat model — trusted, small config blobs
  (`runtime_config.msgpack`, kvstore) — this is a non-issue, and the `unpackb`
  docstring (lines 369-376) does disclaim attacker-reachable use. The risk is a
  project that decodes msgpack from an MQTT payload or HTTP body: MQTT's 8 KB default
  cap → ~8000-element list → ~64 KB+ of pointers, plausibly an OOM on a board with
  ~100-180 KB free. Nothing in the code *enforces* the trusted-only boundary the
  docstring describes.
- **Fix:** add an optional `max_items` knob to `unpackb` (absolute cap across all
  containers), defaulted off to keep the trusted path free; OR keep the disclaimer but
  make it load-bearing — a one-liner in the MQTT/requests guides: "do not `unpackb`
  attacker-controlled payloads without a size cap."

### Verified clean (recent fixes that held up)

Stating these so the next reader doesn't re-litigate:

- **MQTT-1** (`_enqueue_user_tx` variadic, `client.py:1289-1296`): genuinely all-or-none
  — the cap is checked for all items before any `append`, and there's no yield between
  check and appends. "Atomic" is earned.
- **MQTT-3** (`InFlightPublish.dup_packet_bytes`, `client.py:1544-1548`): DUP bit (0x08,
  byte 0) set once on a `bytearray(packet_bytes)` copy, cached as immutable `bytes`,
  per-entry — never stale, since packet-id/topic/payload don't change for an entry.
- **WS-2** (`websockets/_session.py:625`, `requests/client.py:879`): the
  `memoryview(popleft())` keeps the dequeued bytes alive via `_tx_partial` across a
  partial send; requests' hoisted `tx_view` is a per-tick local over a buffer never
  reassigned mid-loop. No use-after-free.
- **SOCK-2** (`sockets/_adapters/mp.py:610-616`): the `setblocking(True)` around
  `wrap_socket` is *required* (the handshake can't run on a non-blocking socket), and
  the worry about `setblocking(False)` not being restored on a `wrap_socket` exception
  is moot — `SocketConnector._fail` (`_connector.py:143-158`) closes the socket on any
  `tick()` exception.
- **HTTP/WS sender-controlled allocation**: bounded — requests `max_body_bytes` (64 KB
  default), websockets `max_message_bytes` + frame-level `FrameParser(max_payload_bytes)`
  + the `_MAX_EMPTY_FRAGMENT_RUN = 64` zero-length-fragment liveness guard, MQTT
  `max_message_bytes` (8 KB) + tiered drop-without-payload-alloc. (HTTP-3's
  cap-before-slice and WS-1's unmask not directly read — see coverage note.)

## H1 — cross-cutting hardware reality: connect blocks the reactor

Not a regression — a substrate limit, documented in the right docstrings — but exactly
the "issue we run into given the hardware" the review was asked for, and it's invisible
where a user would look.

- **MP TLS:** `_MpConnector.tick` runs `ssl.SSLContext.wrap_socket` inline
  (`mp.py:612`); MP's mbedTLS has no `do_handshake_on_connect=False`, so the
  `awaiting_tls` phase is **one blocking tick for the whole handshake** — seconds
  against a slow broker. `_MpTLSListenerWrapper.accept` (`mp.py:366-368`) blocks the
  same way server-side.
- **CP wifi:** `wifi.radio.connect` blocks ~15 s (WIFI-1, documented on `WifiService`).

During either, the cooperative reactor is frozen: a watchdog-feed service, a
sensor-sample loop, an LED heartbeat — all starve for the full duration. A first-time
user wiring up MQTT-over-TLS sees their 50 ms sensor loop freeze for 3 s on connect and
reasonably reads it as a hang/bug.

- **Fix (docs + ergonomics, not behavior):** a loud "what freezes during connect"
  section in the user guide with a measured worst-case per board/runtime; guidance to
  complete connect *before* starting time-critical services, or to budget the stall;
  and surface it on the `connect()`/`from_config` docstrings of mqtt + requests, not
  only deep in the sockets adapter. WIFI-2's `connect_timeout_ms`-is-CP-only also needs
  a "what happens on MicroPython" line (silently ignored today, per its docstring) —
  follow-up once `wifi/` is read directly.

## Workbench / ease-of-use findings (UX agent; W6 hand-verified)

Root cause for W2/W3/W4: the deploy-recovery machinery (closed-set enum + classifier +
coaching loop in `chumicro_workspace.recovery`) is strong, but three of the four
hardware-touching commands — `deploy`, `install-firmware`, `reset-board` — don't catch
the exceptions it re-raises. Only `deploy-example` does (`cli/examples.py:449-461`).
Fixing the catch-and-classify gap at those three call sites resolves W2/W3/W4 together.

- **W1** `recovery_plans.py:51-54` — `NO_PYTHON_RUNTIME` coaching (the canonical
  first-run failure) tells the user to run `install-firmware --board <model> --address
  <port> --list-boards`; the real flags are `--device` (not `--address`), no `--board`,
  no `--list-boards` command exists, and the **required `--method uf2|esptool` is
  omitted**. The most-likely first failure has broken recovery copy. Prose-vs-code
  drift (Decision 0074 class).
- **W2** `cli/deploy.py:609-616` — `_cmd_deploy` calls `deploy_diff` with no
  try/except; `main()` has no top-level handler, so a port-busy / missing-CIRCUITPY /
  unresponsive-REPL failure prints the coached recovery *and then* a raw traceback,
  reading like a tool crash.
- **W3** `cli/deploy.py:565-616` — `--help` promises "per-device failures don't abort
  the loop," but the `deploy_diff` call is outside the loop's only try/except, so
  device 1's transport error propagates and devices 2..N never get touched.
- **W4** `cli/firmware.py:66-74, 110-114` — `install-firmware` (flash) and
  `reset-board` (`wipe_filesystem`) leak raw tracebacks on failure; no `on_progress`
  wired, so a multi-MB download+flash shows a silent terminal for a minute.
- **W5** `micropython_transport.py:1363-1371` + `recovery.py:121-127` — the DEP-1 120 s
  timeout raises a `MicropythonTransportError` whose message matches no classification
  row, so it lands as `UNKNOWN`+`retryable=True`; the interactive loop then retries a
  wedged USB-CDC into the same 120 s hang up to 3× (~6 min). Add a timeout pattern row
  mapped to a non-retryable `USB_WEDGED`-style kind + a test asserting the
  classification.
- **W6** `cli/_common.py:89-105` (**hand-verified**) — `_add_non_interactive_arg` is a
  plain `store_true`; its help text and docstring both claim "auto-detected from stdin
  TTY status when omitted," but nothing auto-detects. `deploy` reads `args.non_interactive`
  raw, so a CI/piped run without the flag builds a prompting `RecoveringDeployer` and
  hits `EOFError`/blocks on the first failure. `deploy-example` does the right thing
  (`not sys.stdin.isatty()`), inconsistently. Resolve once near `main()` so the
  documented contract is real everywhere.
- **W7** `circuitpython_transport.py:567-586` — DEP-3 refusal reports "{N} volumes" not
  the paths, and its trigger (`probe None` AND `>1 CIRCUITPY*` candidate, counting any
  dir without checking `boot_out.txt`) false-refuses the common one-real-board +
  leftover-`CIRCUITPY 1` case that AGENTS.md itself calls normal. List the paths, flag
  empty ones, and count only `boot_out.txt`-bearing mounts toward "ambiguous."
- **W8** `cli/deploy.py:175-191` — TEST-4's AST scan is clean (no literal/comment false
  positives) but only scans `code.py`/`main.py`/`app.py`; a `machine.reset()` at module
  top-level of an imported module still bricks into a reset loop and isn't caught.
  Scan the resolved import-graph for boot-shim layouts, or document the limit in the
  refusal message. (The `from machine import reset` alias gap is a known lower-priority
  true-negative.)
- **W9** `firmware.py:132-139` — the firmware path uses one `FlashFirmwareError`
  (a bare `Exception`) instead of a closed-set `FirmwareFailureKind`; this is the
  inconsistency that made "don't catch at all" the path of least resistance for W2/W4.

## Suggested phase grouping (for review → phases conversion)

- **Phase A (correctness, small + isolated):** L1 (logging guard), L2 (runner
  re-entrancy sentinel). Both are a few lines + a test each.
- **Phase B (workbench UX, one root cause):** W2/W3/W4/W9 — add firmware failure-kind
  classification and catch-and-classify at the three CLI call sites; W6 (central
  non-interactive resolver). High user-facing payoff.
- **Phase C (workbench copy + heuristics):** W1 (fix no-runtime coaching flags),
  W5 (timeout classification + non-retryable), W7 (DEP-3 path-listing + boot_out.txt
  trigger), W8 (import-graph hard-reset scan).
- **Phase D (docs):** H1 (connect-blocks-the-reactor guide section + per-board
  worst-case); L3 (msgpack untrusted-input caveat or `max_items` knob).
- **Before "done":** read `websockets/_wire.py` (WS-1) and `http_server/_wire.py`
  (HTTP-3) directly, or re-run those two library agents — the only material coverage
  gaps in this pass.
