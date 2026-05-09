# Workstream: Workbench Deploy + Tail Reliability

Status: **active.**  Root cause for the silent-deploys on `while True:` examples found 2026-05-09: `deploy_files` actively interrupts the running `code.py` on its way out by sending Ctrl-C × 2 (via the trailing `_enter_raw_repl()` call).  Combined with the explicit Ctrl-D soft-reboot we trigger ourselves, this also makes the S2 FAT-RO race a likely outcome (force-reset before FS writes have committed).  Plan in §"4-step plan" below.

## Purpose

Pyright-cleanup wrap-up included on-board validation of three changed examples (`http_server/circuitpython_two_thing_server`, `mqtt/circuitpython_telemetry`, `sockets/circuitpython_udp_echo_client`) on `lolin-s2-circuitpython-board` and `pi-pico-w-circuitpython-board`.  More errors than successes — only the http_server example produced captured runtime evidence; the other two deployed but went silent.  Findings below drive the deploy-package fix; **the examples stay as-is** — packages need to handle real-world `while True:` programs without killing them.

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

### Finding 7 — `deploy_files` actively kills `code.py` on its way out (root cause for Findings 2/3/6)

**Observed by reading the code, not the bench session:** `circuitpython_transport.py:1453-1461` ends the flash-mode deploy with:

```python
self._port.write(_CTRL_B)            # exit raw REPL
self._port.write(_CTRL_D)            # trigger soft-reboot
output = self._read_code_py_output() # capture up to self.timeout (10s)
self._enter_raw_repl()               # ← Ctrl-C × 2 + Ctrl-A — INTERRUPTS the running code.py
```

`_enter_raw_repl()` (`circuitpython_transport.py:582-603`) sends two Ctrl-Cs to interrupt any running program before switching to raw REPL.  So **every flash-mode deploy actively kills the freshly-booted `code.py` after a 10-second capture window**, and `disconnect()` then exits raw REPL leaving the board at friendly REPL with no program running.

This explains Findings 2, 3, and 6 in one stroke:

- **http_server got captured** because it printed `WIFI_OK` + `Server listening` inside the 10 s window — the bytes survived even though the server itself was about to be Ctrl-C'd.
- **mqtt deploys silently** because its 15 s MQTT-connect window means the first `print` doesn't land before our Ctrl-C, and after we Ctrl-C the connect call, the program is dead.
- **udp deploys silently** because its blocking `recv` waits on a packet that never comes within 10 s; we Ctrl-C the recv and exit.
- **`chumicro-repl --tail` sees zero bytes after a deploy** because by the time tail reconnects the board really is silent — `code.py` was Ctrl-C'd and friendly REPL is sitting at `>>>`.

This is not a "while-True examples need special package treatment" problem — it's that the deploy treats every example as a one-shot command that should be cleaned up after.  Real-world programs run forever; the deploy needs to deploy and *get out of the way*.

### Finding 8 — explicit Ctrl-D soft-reboot likely contributes to the S2 FAT-RO race

**The settle stack before our self-issued Ctrl-D:** `_wait_for_board_to_see_entrypoint` polls `os.stat` until the board sees the new file at the expected size, then sleeps `_BOARD_FILE_VISIBLE_POST_SETTLE = 0.5 s` (`circuitpython_transport.py:74-89`), then immediate Ctrl-D.

`os.stat` proves CP saw the directory entry; it says nothing about whether the host's last block writes have committed to FLASH/FAT.  When we Ctrl-D inside that window the CP VM tears down (USB-CDC + USB-MSC drop together) with FAT mid-write — exactly the inconsistency the macOS `msdosfs` driver defends against by remounting read-only.  Once macOS has demoted the volume no host-side rsync can recover it; only physical RESET reboots CP and clears the kernel's RO flag.

CP's autoreload watcher, in contrast, waits for FS quiescence (debounce window) before triggering its own reboot — that's exactly the signal we lack on the host side.

The "two re-enumerations wedged the S2" pain documented in `circuitpython_transport.py:1881-1893` (the comment on `disconnect`) was about layering our Ctrl-D *on top of* an autoreload reboot inside `disconnect()`.  Fix there was to stop double-resetting in `disconnect`.  The same logic applies to `deploy_files()` — pick **one** mechanism.  Autoreload is the better one because it knows when the FS has settled.

## What's NOT being claimed

- The example code changes (`is_connected` rename, `sender = None` init, `_State` annotations) are correct as written; AST + verify-examples + unit tests + preflight all pass, and the http_server case validated the runtime path of the same kind of change.
- The workbench is not fundamentally broken — http_server's clean run shows the happy path works.  The findings above are about *off-happy-path resilience* and *observability*.
- We are NOT changing the example programs.  The fix is in the deploy package; examples with `while True:` are exactly the shape real users will write.

## 4-step plan

Each step is independently shippable; ordering picks the smallest reversible change first.

### Step 1 — Stop killing `code.py` at the end of `deploy_files` ✅

Shipped 2026-05-09.  Two coordinated edits:

- Dropped the trailing `self._enter_raw_repl()` from `deploy_files` (was line 1461) and replaced the comment with the rationale.
- Simplified `disconnect()` to send a bare `Ctrl-B` (exits raw REPL when in raw, harmless one byte otherwise) and close the port — no leading `_enter_raw_repl` round-trip, no Ctrl-C interrupt.

Both `test_flash_disconnect_does_not_touch_autoreload` and `test_ram_disconnect_does_not_send_autoreload` now lock in "no Ctrl-C at disconnect."  832 deploy tests + full preflight green at 96 % coverage.

Bench-validated on Lolin S2 CP (`/dev/cu.usbmodem84722E7490C31`) with a `while True: print(counter); time.sleep(0.5)` probe via `chumicro-deploy deploy --transport circuitpython --address ... --drive /Volumes/CIRCUITPY --deploy-mode flash`.  Deploy captured counter=1..20 inside the 10 s window, returned cleanly.  `chumicro-repl --tail 5` immediately afterward saw counter=41..50 — `code.py` survived the deploy and kept printing on its own time.

Pi Pico W CP not validated this step — its `/Volumes/CIRCUITPY 1` mount went stale during the prior session and got force-unmounted; needs a replug for a full 4-board sweep (deferred to Step 6 after Steps 2 + 3 land).

### Step 2 — Bump post-stat settle from 0.5 s to 2 s (correction; was "autoreload-driven reset")

**Original Step 2 was wrong.**  The "let CP's autoreload watcher fire the reset" idea assumed CP would replay write events from the autoreload-off window.  Reading `.tools/circuitpython-10.2.0/supervisor/shared/reload.c`:

- `autoreload_trigger()` (line 67) checks `autoreload_enabled` *at the moment of the trigger*.  If autoreload is off (which it is during our rsync), the trigger is **dropped entirely** — there is no replay queue.
- `autoreload_enable()` (line 45) actively *resets* `last_autoreload_trigger = 0`, so re-enabling autoreload clears any pending state too.

So the "re-enable autoreload, let CP fire its own reset" plan would result in the board sitting at friendly REPL with autoreload on but no trigger pending — `code.py` never runs.  CP's `supervisor.reload()` exists but goes through the same `reload_initiate()` path as Ctrl-D — same race window with FS writes.  And we cannot leave autoreload ON during rsync: the `_disable_autoreload_before_drive_writes` docstring documents the "wedged rsync" failure mode (autoreload fires mid-rsync, USB-CDC re-enumerates, next host-side `write()` hangs in uninterruptible kernel I/O).

The actual lever for the S2 FAT race is **timing**, not mechanism.  The current `_BOARD_FILE_VISIBLE_POST_SETTLE = 0.5` was empirical guesswork and is too short to guarantee in-flight FAT writes have committed before our Ctrl-D.  Bump to 2 s — cheap, reversible, addresses the user's "0.5 s is too short regardless" intuition as a belt-and-suspenders fix.

### Step 2b — Post-rsync verification pass via `rsync --checksum --dry-run`

After the main rsync, run a second rsync against the same staging tree with `--checksum --dry-run --itemize-changes`.  If any files come back as needing transfer, the first rsync's writes didn't commit fully (FAT corruption, partial write, USB-MSC race) — fail the deploy with a clear "write didn't commit" message *before* triggering Ctrl-D.  Uses rsync's own machinery rather than a separate read-back loop; FAT-cache concerns on Pi Pico W are the open question worth investigating.

### Step 3 — Configurable capture window

`_read_code_py_output` is currently fixed at `self.timeout` (10 s).  Add a parameter — `--tail-seconds N` at the CLI, plumbing through to `deploy_files(tail_seconds=N)`.  Default `0` for `--non-interactive` (return immediately, leave board running), prompt-driven for interactive.  This is Finding 2's `--tail-seconds` flag, but free since we're already restructuring the capture.

### Step 4 — Strip stale autoreload framing from recovery hint

`recovery.py:534-546` — drop "CircuitPython's autoreload can remount while a write is in flight" since the deploy disables autoreload before any rsync.  Replace with the diagnosed cause (force-reset-before-FS-done, fixed by step 2) plus the recovery path (tap RESET, replug).

After all four land: 4-board validation sweep on Lolin S2 CP+MP and Pi Pico W CP+MP, mqtt + udp + http_server.

Detail belongs in commit messages + this workstream — `plans/next-up.md` carries a one-line pointer.
