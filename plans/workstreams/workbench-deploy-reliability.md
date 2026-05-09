# Workstream: Workbench Deploy + Tail Reliability

Status: **research / observations.**  Captured 2026-05-09 from a session where on-board verification of three example files yielded one clean success and two cases where the deploy succeeded mechanically but the runtime evidence couldn't be captured.  The pattern of "deploy returns exit 0 yet I can't prove the code is actually running" suggests workbench-package design gaps worth investigating before the next deploy-heavy workstream lands.

## Purpose

Pyright-cleanup wrap-up included on-board validation of three changed examples (`http_server/circuitpython_two_thing_server`, `mqtt/circuitpython_telemetry`, `sockets/circuitpython_udp_echo_client`) on `lolin-s2-circuitpython-board` and `pi-pico-w-circuitpython-board`.  More errors than successes — only the http_server example produced captured runtime evidence; the other two deployed but went silent.  Findings below should drive the next workbench reliability session.

## What worked

- **Deploy of `http_server/circuitpython_two_thing_server` to Pi Pico W CP** — captured `ADAPTER: cp`, `WIFI_OK ip=172.16.1.21`, and `Server listening on 0.0.0.0:8080` inline during the deploy's serial-attached window.  Confirmed `_State` class-level annotations don't break CP runtime (annotations stripped per Decision 0021).
- **`verify-examples --all`** — 55/55 examples pass host-side import + AST checks.  Catches example breakage before the device round-trip.
- **`preflight` + `test-all-runtimes`** — all green at 96% coverage; cross-runtime CPython + MP unix-port + CP unix-port suites pass.

## What didn't (the research surface)

### Finding 1 — CIRCUITPY auto-eject race during rsync

**Observed:** `chumicro-deploy` rsync to LOLIN S2 CIRCUITPY drive failed mid-copy with `mkpathat: Read-only file system`.  Recovery hint suggested CP autoreload remounted the drive while a write was in flight.  Three retry attempts all hit the same RO state.  Drive stayed read-only for the rest of the session — would need a physical RESET to remount RW.  Verified via `mount`:

```
/dev/disk14s1 on /Volumes/CIRCUITPY (msdos, local, nodev, nosuid, read-only, ...)
/dev/disk15s1 on /Volumes/CIRCUITPY 1 (msdos, local, nodev, nosuid, ...)
```

**Design questions:**

- Can the deploy lock CP autoreload before starting rsync (e.g., write a sentinel that pauses autoreload, rsync, release the sentinel)?
- Can the deploy detect the RO state pre-rsync and refuse with a clear "tap RESET" message instead of failing partway through?
- The classifier-driven recovery hint is good but doesn't help when the RO state persists across retries.

### Finding 2 — `--non-interactive` exits before code.py runs to completion

**Observed:** `deploy-example --non-interactive` implies `--no-tail`, which exits as soon as rsync completes.  CircuitPython then auto-reloads and reruns code.py — but the deploy command has already disconnected from serial.  Output captured during the deploy is whatever happened to be emitted in the brief window between rsync-complete and command-exit; everything after autoreload is invisible.

The http_server deploy got lucky — `WIFI_OK` and `Server listening` arrived during this window.  The mqtt and udp examples take longer to reach their first `print` calls (mqtt has a 15s MQTT-connect window; udp has a 5s UDP-echo timeout) and missed the window entirely.

**Design questions:**

- Add a `--tail-seconds <N>` flag for scripted use: deploy, then stream output for N seconds, then exit.  Middle-ground between blocking `--tail` and zero-tail `--non-interactive`.
- Does `--non-interactive` need to imply `--no-tail`?  A non-blocking tail with a hard deadline would suit CI fine.

### Finding 3 — serial reconnect race loses post-deploy output

**Observed:** running `chumicro-repl --tail 25` immediately after `deploy-example --non-interactive` captured **zero lines** for 25s on a board where code.py was definitely running fresh.  Suspected window: deploy-exit → CP autoreload → CP serial briefly disconnects → tail reconnects but the boot prints have already passed.

This is the same root cause as Finding 2 from the deploy side — the host's serial connection to the board is not continuous across the autoreload boundary.

**Design questions:**

- Can the workbench keep the serial port open across the autoreload, so tail attaches before the board reset rather than after?
- Even raw pyserial reads (bypassing chumicro-repl) caught nothing — see Finding 4.

### Finding 4 — soft-reboot puts board into "running but silent" state

**Observed:** after sending `Ctrl-C` + `Ctrl-D` (soft reset) to the Pi Pico W several times via raw pyserial, the device entered a state where:

- `\r\n` to serial elicits `>>>` REPL prompts (input/output works in interactive mode)
- A soft-reset prints `Auto-reload is off` then `code.py output:` then nothing for 30s
- Pure passive listen for 30s captures zero bytes
- `ping 172.16.1.21` (the board's previously-known IP) gets no response — wifi may have disconnected during the reboot loop

The board is presumably running code.py but its serial CDC output is silent.  Recovery requires a physical RESET button press.  Did NOT happen during the original (working) deploy of http_server to the same board — only after my repeated programmatic soft-reboots while debugging.

**Design questions:**

- Is this a CircuitPython USB-CDC quirk after rapid soft-resets?  A macOS-side serial-driver quirk?  Reproducible on the workbench end?
- Should chumicro-repl avoid sending `Ctrl-D` soft-resets after deploy?  Or detect the silent-state and surface a "tap RESET" hint?

### Finding 5 — `chumicro-workspace devices` doesn't show the CIRCUITPY drive path

**Observed:** when multiple CIRCUITPY drives are mounted (two CP boards plugged in), macOS appends ` 1` to the second mount.  `chumicro-workspace devices` lists `(id, runtime, address)` but not the `/Volumes/CIRCUITPY*` path each board owns.  Had to read `boot_out.txt` from each drive manually (board UID + Board ID inside) to figure out which mount was which board.

**Design question:**

- `chumicro-workspace devices --verbose` (or the default for CP boards) should show the resolved drive path next to each board ID.

### Finding 6 — "deploy exit 0" doesn't mean "code is running on device"

**Observed:** in two of three cases, the deploy returned exit 0, the file landed on the CIRCUITPY drive (verified by reading `code.py` from `/Volumes/CIRCUITPY 1/`), but no runtime evidence reached the host.  The deploy machinery succeeds-by-rsync-success, not by-code-runs-and-emits-something.

**Design question:**

- Add an optional "deploy + boot confirmation" mode: deploy, watch serial, look for any output within N seconds, exit with a distinct failure if zero output (suggesting board is stuck).  Distinct exit code so CI can react.

## What's NOT being claimed

- The example code changes (`is_connected` rename, `sender = None` init, `_State` annotations) are correct as written; AST + verify-examples + unit tests + preflight all pass, and the http_server case validated the runtime path of the same kind of change.
- The workbench is not fundamentally broken — http_server's clean run shows the happy path works.  The findings above are about *off-happy-path resilience* and *observability*.

## Suggested research-session shape

1. Reproduce Finding 1 (CIRCUITPY RO race) deliberately — write a script that triggers autoreload + rsync simultaneously.  Measure how often it lands.
2. Reproduce Finding 4 (silent-after-soft-reboot) — script N soft-resets in sequence, count how many it takes to silence the device.  Investigate whether it's the host-side serial driver or the device's CDC stack.
3. Prototype the `--tail-seconds <N>` flag (Finding 2) — smallest change, biggest UX win.
4. Decide between (a) keep-serial-open-across-autoreload and (b) attach-after-with-replay-buffer for Finding 3.

Detail belongs in commit messages + this workstream — `plans/next-up.md` carries a one-line pointer.
