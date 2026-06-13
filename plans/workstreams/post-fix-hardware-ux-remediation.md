# Workstream: Post-fix hardware + UX remediation (2026-06)

Status: **in progress — opened 2026-06-13.** Phase 0 (coverage gap) done — WS-1 / HTTP-3 / HTTP-1 re-read and verified clean. Phase A (library correctness, L1 + L2) shipped. Phase B (workbench failure handling) shipped (workspace 0.42.1). Phase C (workbench coaching) shipped (deploy 0.33.0, workspace 0.42.2). Phase D (docs) next. Full evidence for every finding ID lives in the research artifact: [`plans/reviews/2026-06-13-post-fix-hardware-ux-review.md`](../reviews/2026-06-13-post-fix-hardware-ux-review.md).

Counts: 1 HIGH + 2 MEDIUM library, 1 MEDIUM cross-cutting (docs), 6 HIGH + 2 MEDIUM + 1 LOW workbench.

## Problem

The second review pass (after the deep-code-review remediation Phases 1-9 landed) re-derived the recent fixes against source and found most held — MQTT-1/MQTT-3, WS-2 (both sites), SOCK-2, MSG-1 are verified clean. One regression slipped in (L1), two pre-existing-but-now-sharper interaction bugs surfaced (L2, L3), the connect-blocks-the-reactor substrate limit needs to reach the user guide (H1), and the workbench recovery machinery is bypassed by three of four hardware-touching CLIs (the W-cluster).

Each finding's full evidence lives in the report; this file is the execution plan + status tracker. Re-derive any claim before fixing. The report already re-derived every library finding and hand-verified W6; the rest of the W-cluster is the UX agent's, marked accordingly.

## Scope boundary

- The deep-review remediation already shipped WS-1 (Phase 4) and HTTP-3 (Phase 3). This pass did **not** re-read `websockets/_wire.py` or `http_server/_wire.py` — Phase 0 closes that, verifying the prior fixes held and checking for anything new. It is verification, not re-implementation.
- Verified-clean this pass (do not re-open): MQTT-1 atomic enqueue, MQTT-3 cached DUP bytes, WS-2 memoryview lifetime (websockets + requests), SOCK-2 (the setblocking-on-failure worry is moot — `SocketConnector._fail` closes the socket), MSG-1 exception tuple, the HTTP/WS/MQTT sender-controlled allocation caps.
- SOCK-1 / WIFI-1 stay documented-not-fixed per the 2026-06-13 user guidance (a non-blocking resolution compromises connect ergonomics). H1 extends that documentation stance to MP-TLS + the user guide; it is not a behavior change.

## Implementation phases

### Phase 0 — Close review coverage gap

**Done 2026-06-13 — both files read, prior fixes verified clean, no new actionable findings.**

Five of six library review agents died on a transient API rate limit, so the libraries were read by hand and two parser files went unread. Re-read this pass.

- **GAP-WS1** — `websockets/_wire.py` read. WS-1 hand-indexed unmask (`_wire.py:944-950`) is allocation-free (bytearray indexed-assign, memoryview index, no `range()`) and **correct across feed-chunk boundaries**: it masks with the absolute payload offset `(write_offset + index) & 3`, not a chunk-relative index, which is the subtle part. Length tiers (0 / <126 / len16 / len64), control-frame ≤125 enforcement, and tier-3 oversized drain all correct. *verified clean.*
- **GAP-HTTP3** — `http_server/_wire.py` + `server.py` read. HTTP-3 request-line cap rejects before slicing (`_wire.py:546-550`); body cap rejects >`max_body_bytes` as 413 before any allocation (`:659-668`); headers cap → 431 (`:596-600`); Transfer-Encoding request bodies rejected to block smuggling (`:634-641`). HTTP-1 `_reject_control_chars` (`server.py:419-428`) applied to reason + every response header name/value (`:444-454`). *verified clean.*
- **GAP-OBS-1** (LOW, pre-existing, not actionable) — client-side `make_mask_key`→`os.urandom(4)` (`_wire.py:1106`) runs per outbound frame and per auto-pong inside a tick; AGENTS.md lists MP `os.urandom` as a tick-budget offender, but it is hardware-RNG-backed and fast on rp2/esp32, and RFC 6455 §5.3 requires strong randomness so a PRNG is the wrong fix. Note only; confirm timing if a websocket-client bench is ever run.

### Phase A — Library correctness regressions

Small, isolated, well-testable. L1 is the priority — a crash regression in a library everything logs through.

**Phase A complete 2026-06-13: L1 (logging 0.3.1) + L2 (runner 0.8.0) shipped. L2's behavior change was approved by the user 2026-06-13 — a re-entrant tick now propagates loudly.**

- **L1** (HIGH, `libraries/logging/src/chumicro_logging/core.py:124`) — `Logger.log`'s `message % args` interpolation sat outside the `try/except` that wraps `handler.emit`, so a format/arg mismatch raised into the caller and broke the class's documented "logging never crashes the app" contract. **Shipped (logging 0.3.1):** guarded the interpolation in a `try/except Exception`, rendered a visible fallback `f"{message!r} % {args!r} (log-format error: …)"`, counted it in `handler_errors`; updated both docstrings; test `test_logger_format_mismatch_does_not_crash_the_caller`. *verified.*
- **L2** (MEDIUM, `libraries/runner/src/chumicro_runner/core.py`) — RUN-1's `except Exception` swallowed the re-entrancy guard's `RuntimeError`, so a handler that re-entered `tick()` got a silent `handler_errors` bump instead of a loud crash. **Shipped 2026-06-13 (runner 0.8.0), user-approved.** Re-entering the reactor is framework misuse, categorically different from a service handler raising a domain exception, so it now propagates. Added `ReentrantTickError(RuntimeError)` (exported), the guard raises it, and the dispatch loop re-raises it past the handler-fault isolation while ordinary faults stay isolated unchanged. Rewrote `test_reentrant_tick_from_handler_is_isolated` to `test_reentrant_tick_from_handler_propagates` (asserts it raises, `handler_errors == 0`, and the runner recovers once the offending handler is removed). *verified.*

### Phase B — Workbench failure-handling root cause

**Shipped 2026-06-13 (workspace 0.42.1).** The report's paths were the agent's and partly wrong: the recovery machinery (`DeployFailureKind`, `classify_deploy_failure`, `RecoveringDeployer`) lives in `chumicro_deploy`, not `chumicro_workspace`. Re-derived against the real files; the root cause held — three of four hardware-touching CLIs don't catch what the machinery re-raises.

- **W2 + W3** (HIGH, `cli/deploy.py`) — the per-device `deploy_diff` call now sits in `try/except (CircuitpythonTransportError, MicropythonTransportError)` that prints `deploy: <transport>@<address>: <error>` to stderr, sets exit 1, and `continue`s. A physical-layer failure exits cleanly instead of dumping a traceback (W2), and the remaining devices in `--all-devices` still get their turn (W3). Tests: `test_transport_error_surfaces_message_not_traceback`, `test_all_devices_continues_past_a_failing_device` (FakeTransport `connect_raises`). *verified.*
- **W4** (HIGH, `cli/firmware.py`) — `install-firmware` wraps the flash in `except FlashFirmwareError` (surfaces the message + exit 1) and wires an `on_progress` printer so a multi-MB flash isn't a silent terminal; `reset-board` wraps connect + wipe in `except (CircuitpythonTransportError, MicropythonTransportError)` with a replug hint + exit 1. Test: `test_flash_failure_surfaces_message_not_traceback`. *verified.*
- **W6** (HIGH, `cli/deploy.py` + `cli/firmware.py`) — `--non-interactive` now auto-detects from `sys.stdin.isatty()` in `_cmd_deploy` + `_cmd_install_firmware` (an explicit flag wins), matching `deploy-example`. **Scoped, not central:** a first attempt at a global resolver in `main()` flipped *every* command non-interactive under the non-tty test stdin and disabled `repl`'s coaching loop, so the auto-detect lives in the two handlers the finding named. *verified.*
- **W9** (LOW → resolved by W4, `chumicro_deploy/firmware.py:132`) — **no `FirmwareFailureKind` enum added.** `FlashFirmwareError` deliberately carries recovery guidance in its message ("Catchers typically surface the message directly rather than introspect"), and `_download_firmware` already wraps `URLError` into it. A parallel classifier would fight that design; W4's catch-and-surface honors it. *resolved.*

### Phase C — Workbench coaching copy + heuristics

**Shipped 2026-06-13 (deploy 0.33.0, workspace 0.42.2).**

- **W1** (HIGH, `recovery_plans.py`) — the `NO_PYTHON_RUNTIME` plan now uses the real `install-firmware` surface: `--device <id> --method <uf2|esptool>`, URL derived from the device entry (`--url` to override), with an `add-device` first step. Dropped the nonexistent `--board` / `--address` / `--list-boards` and supplied the omitted-required `--method`. (`--runtime` does exist as a device selector, so it was already valid.) *verified.*
- **W5** (HIGH, `recovery_kind.py` + `recovery_plans.py` + `recovery.py`) — added a non-retryable `DeployFailureKind.COMMAND_TIMED_OUT` with a replug-coaching plan and a `"command timed out"` classification row, ordered before BOOTSTRAP_EXEC (which carries "mpremote command failed"). A wedged-CDC 120 s timeout no longer falls to UNKNOWN+retryable and retries into the same hang. Tests: a classifier bucket case + `test_command_timeout_is_not_retryable`. *verified.*
- **W7** (MEDIUM, `circuitpython_transport.py`) — `_drive_path_or_refuse_unverifiable` now counts only `boot_out.txt`-bearing mounts as real boards (a bare stale `CIRCUITPY 1` no longer false-refuses a single-board deploy) and lists the candidate paths in the refusal instead of a bare count. Refusal test split into a two-real-boards refusal (asserts both paths listed) + a new empty-stale-mount-proceeds test. *verified.*
- **W8** (MEDIUM → documented scope, `cli/deploy.py`) — **the entrypoint-only scan is correct, not a bug.** `module_calls_hard_reset` (`ast.walk`) flags *any* reset call, including one inside a function — the deliberate pattern the refusal recommends — so scanning imported modules with it would false-flag legitimate code. Documented the deliberate scope and the genuine residual gap (an imported module's *top-level* reset still runs at boot and isn't caught; closing it needs a top-level-only AST check, a deferred follow-up — not the naive whole-graph scan). *resolved.*

### Phase D — Hardware-reality docs

No behavior change. Make the substrate limits the user trips on visible where they look.

- **H1** (MEDIUM, docs) — user-guide section: MP TLS handshake (`sockets/_adapters/mp.py:612`) and CP wifi connect block the whole cooperative reactor for the round-trip (seconds); what freezes, measured per-board worst-case, guidance to connect before starting time-critical services. Surface on mqtt + requests `connect()`/`from_config` docstrings, not only the sockets adapter. Add the WIFI-2 `connect_timeout_ms`-is-CP-only "what happens on MicroPython" line (read `wifi/` first).
- **L3** (MEDIUM, `libraries/msgpack/src/chumicro_msgpack/_pure.py:318,333` + docstring) — either add an optional `max_items` absolute cap to `unpackb` (defaulted off), or make the trusted-only disclaimer load-bearing with a one-line caveat in the mqtt + requests guides against `unpackb`-ing attacker-controlled payloads.

## Validation history

- 2026-06-13 — Workstream opened from the post-fix review report.
- 2026-06-13 — Phase 0: re-read `websockets/_wire.py` + `http_server/_wire.py` + `server.py`. WS-1, HTTP-3, HTTP-1 verified clean; no new actionable findings (one LOW `os.urandom` note recorded as GAP-OBS-1). No code changed.
- 2026-06-13 — Phase A / L1 shipped (logging 0.3.1): guarded `Logger.log`'s `message % args` so a format mismatch renders a visible fallback + counts `handler_errors` instead of crashing the caller; test added.
- 2026-06-13 — Phase A / L2 shipped (runner 0.8.0), user-approved: re-entrant `tick()` now propagates `ReentrantTickError` past the handler-fault isolation instead of being silently counted; ordinary handler faults stay isolated. Locking test rewritten to assert propagation. Error-path-only change (steady-state tick + allocation unchanged); real-board validation folds into the already-pending RUN-1 runner-tick bake. Phase A complete.
- 2026-06-13 — Phase B shipped (workspace 0.42.1): W2/W3 (deploy per-device transport-error catch + `continue`), W4 (install-firmware flash-error catch + progress, reset-board wipe catch), W6 (scoped `--non-interactive` isatty auto-detect in deploy + install-firmware). W9 resolved without a new enum (FlashFirmwareError carries its own guidance). 3 new tests; 261 CLI tests green. Agent's `chumicro_workspace` recovery paths corrected to `chumicro_deploy`.
- 2026-06-13 — Phase C shipped (deploy 0.33.0, workspace 0.42.2): W1 (NO_PYTHON_RUNTIME coaching fixed to the real install-firmware flags), W5 (non-retryable COMMAND_TIMED_OUT kind + classification so a wedged-CDC timeout stops retrying into the hang), W7 (wrong-board refusal counts only boot_out.txt mounts + lists paths). W8 resolved as documented-deliberate-scope (a naive import-graph scan would false-flag the recommended in-function reset pattern). 4 new/updated tests.
