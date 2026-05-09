# Workstream: Workbench Deploy + Tail Reliability

Status: **research / observations.**  Captured 2026-05-09 from a session where on-board verification of three example files yielded one clean success and two cases where the deploy succeeded mechanically but the runtime evidence couldn't be captured.  The pattern of "deploy returns exit 0 yet I can't prove the code is actually running" suggests workbench-package design gaps worth investigating before the next deploy-heavy workstream lands.

## Purpose

Pyright-cleanup wrap-up included on-board validation of three changed examples (`http_server/circuitpython_two_thing_server`, `mqtt/circuitpython_telemetry`, `sockets/circuitpython_udp_echo_client`) on `lolin-s2-circuitpython-board` and `pi-pico-w-circuitpython-board`.  More errors than successes — only the http_server example produced captured runtime evidence; the other two deployed but went silent.  Findings below should drive the next workbench reliability session.

## What worked

- **Deploy of `http_server/circuitpython_two_thing_server` to Pi Pico W CP** — captured `ADAPTER: cp`, `WIFI_OK ip=172.16.1.21`, and `Server listening on 0.0.0.0:8080` inline during the deploy's serial-attached window.  Confirmed `_State` class-level annotations don't break CP runtime (annotations stripped per Decision 0021).
- **`verify-examples --all`** — 55/55 examples pass host-side import + AST checks.  Catches example breakage before the device round-trip.
- **`preflight` + `test-all-runtimes`** — all green at 96% coverage; cross-runtime CPython + MP unix-port + CP unix-port suites pass.

## What didn't (the research surface)

### Finding 1 — CIRCUITPY drive went read-only mid-rsync; cause unknown (recovery hint blames autoreload, but deploy already disables it)

**Observed:** `chumicro-deploy` rsync to LOLIN S2 CIRCUITPY drive failed mid-copy with `mkpathat: Read-only file system`.  Three retry attempts all hit the same RO state.  Drive stayed read-only for the rest of the session — needs a physical RESET to remount RW.  Verified via `mount`:

```
/dev/disk14s1 on /Volumes/CIRCUITPY (msdos, local, nodev, nosuid, read-only, ...)
/dev/disk15s1 on /Volumes/CIRCUITPY 1 (msdos, local, nodev, nosuid, ...)
```

**Initial hypothesis was wrong.**  The classifier surfaced `flash_copy_failed` with the recovery hint: *"CircuitPython's autoreload can remount while a write is in flight."*  That hint is **stale guidance** — `chumicro_deploy.circuitpython_transport._disable_autoreload_before_drive_writes` (`circuitpython_transport.py:605`) sends `import supervisor; supervisor.runtime.autoreload = False` over raw REPL **before** any host-side rsync starts.  Autoreload is off during the entire copy window.  The recovery message in `chumicro_deploy.recovery.py:537-539` still names autoreload as the cause and is misleading.

**More-likely causes worth investigating:**

- **FAT32 corruption from concurrent host-write + device-USB-MSC interaction.**  FAT32 on USB-MSC has no journaling; a partially-written FAT chain can leave the volume in a state where the macOS `msdosfs` driver remounts it read-only as a self-defence measure.  The Pi Pico W's slower MSC controller (already noted in `circuitpython_transport.py:1442-1447` as a known stale-FAT-view source) makes this more likely on rp2 boards.
- **macOS `msdosfs` driver downgrading to RO on detected inconsistency.**  `mount` shows the volume at `/Volumes/CIRCUITPY` mounted with `read-only`; the kernel does this autonomously when it sees write errors or inconsistent FAT entries.  A diskutil verify pass would confirm.
- **CP's own filesystem-write protection.**  CP can mark the drive read-only from the device side (`storage.remount("/", readonly=True)`); something in our deploy / example chain might be triggering it indirectly.

**Design questions for the research session:**

- Update the recovery hint in `chumicro_deploy.recovery.py:534-546` to drop the autoreload framing and replace with the actual diagnosis once known.  Until known, prefer "drive went read-only mid-rsync — cause not yet diagnosed; tap RESET, replug, and re-deploy.  If it recurs, capture `dmesg`-equivalent (Console.app for macOS) so we can root-cause."
- Pre-rsync drive-RO probe: `os.access(drive_path, os.W_OK)` or write-then-delete a sentinel file.  Refuse before partial-write damage.
- After-rsync verify pass: re-read every file written and compare bytes; surface mismatches (catches FAT-corruption silent-data-loss).
- Repro recipe: try to trigger the RO state deliberately via large rsync workloads on each board class (Pi Pico W vs LOLIN S2 vs others).

### Finding 2 — `--non-interactive` exits before code.py runs to completion

**Observed:** `deploy-example --non-interactive` implies `--no-tail`, which exits as soon as rsync completes.  CircuitPython then auto-reloads and reruns code.py — but the deploy command has already disconnected from serial.  Output captured during the deploy is whatever happened to be emitted in the brief window between rsync-complete and command-exit; everything after autoreload is invisible.

The http_server deploy got lucky — `WIFI_OK` and `Server listening` arrived during this window.  The mqtt and udp examples take longer to reach their first `print` calls (mqtt has a 15s MQTT-connect window; udp has a 5s UDP-echo timeout) and missed the window entirely.

**Design questions:**

- Add a `--tail-seconds <N>` flag for scripted use: deploy, then stream output for N seconds, then exit.  Middle-ground between blocking `--tail` and zero-tail `--non-interactive`.
- Does `--non-interactive` need to imply `--no-tail`?  A non-blocking tail with a hard deadline would suit CI fine.

### Finding 3 — serial reconnect race loses post-deploy output

**Observed:** running `chumicro-repl --tail 25` immediately after `deploy-example --non-interactive` captured **zero lines** for 25s on a board where code.py was definitely running fresh.

**The reset is explicit, not autoreload.**  `circuitpython_transport.py:1453-1456` writes `_CTRL_B` (exit raw REPL) then `_CTRL_D` (soft-reboot) at the end of every flash deploy, then calls `_read_code_py_output()` to capture what comes back.  So the device DOES reset, but it's the deploy's own driver that's doing it — autoreload has been off since the rsync started.

The captured output sits on `_read_code_py_output()`'s side: the deploy reads serial during the soft-reboot's code.py run, then disconnects.  After disconnect, anything code.py prints later (the publish loop in mqtt, the wait-for-RECV in udp_echo) goes to the host's now-closed serial port and is lost.  When `chumicro-repl --tail` reconnects, it's attaching mid-stream to a process that may have already gone silent (if code.py finished and dropped to REPL) or may be in a long blocking call (if code.py is still running but not yet at its next print).

**Design questions:**

- Can `--no-tail` mode end with a "serial released, you can reconnect now" signal instead of an immediate exit?  Or hand the open file descriptor over to a successor process?
- For `--non-interactive` CI use: a `--tail-seconds <N>` flag (Finding 2) sidesteps the reconnect race entirely by keeping the serial held through N seconds of post-reboot output before exiting.

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

1. **Cheap correctness win:** strip the autoreload framing from `chumicro_deploy.recovery.py:537-539` (Finding 1 hint is misleading — autoreload is off during rsync per `circuitpython_transport.py:605-633`).  Replace with "drive went read-only mid-rsync; try replug + RESET; capture Console.app output if it recurs."  10-line change, removes a wrong-direction debugging trail.
2. Reproduce Finding 1 (CIRCUITPY RO mid-rsync) deliberately on each board class — large rsync workloads, watch for the `read-only` mount transition.  Likely FAT32 corruption or `msdosfs` self-defence; `diskutil verifyVolume` mid-issue would confirm.
3. Reproduce Finding 4 (silent-after-soft-reboot) — script N programmatic soft-resets in sequence, count how many it takes to silence the device.  Decide whether the silencing is host-side (serial driver) or device-side (CDC stack).
4. Prototype the `--tail-seconds <N>` flag (Finding 2) — smallest change, biggest UX win, sidesteps Finding 3's reconnect race for CI.
5. Decide whether deploy's own end-of-pipeline soft-reboot (`circuitpython_transport.py:1453-1456`) should leave serial held longer for the `--non-interactive` case, or hand the file descriptor over to a successor tail process.

Detail belongs in commit messages + this workstream — `plans/next-up.md` carries a one-line pointer.
