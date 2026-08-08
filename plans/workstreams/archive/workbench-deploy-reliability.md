# Workstream: Workbench Deploy + Tail Reliability

Status: **closed.**  Root cause for the silent-deploys on `while True:` examples found 2026-05-09: `deploy_files` actively interrupted the running `code.py` on its way out by sending Ctrl-C × 2 (via the trailing `_enter_raw_repl()` call); the explicit Ctrl-D soft-reboot we triggered ourselves also raised the S2 FAT-RO race risk.  All six steps (1, 1b, 2, 2b, 3, 4) shipped 2026-05-09 + bench-validated across the canonical 4-board sweep (Lolin S2 CP, Pi Pico W CP, Lolin S2 MP, Pi Pico W MP).  Two follow-ups surfaced during the sweep are tracked separately in [`archive/deploy-multi-board-and-fskit-followups.md`](deploy-multi-board-and-fskit-followups.md).  Every step in §"4-step plan" is flipped to ✅.

## Purpose

Pyright-cleanup wrap-up included on-board validation of three changed examples (`http_server/circuitpython_two_thing_server`, `mqtt/circuitpython_telemetry`, `sockets/circuitpython_udp_echo_client`) on `lolin-s2-circuitpython-board` and `pi-pico-w-circuitpython-board`.  More errors than successes — only the http_server example produced captured runtime evidence; the other two deployed but went silent.  Findings below drive the deploy-package fix; **the examples stay as-is** — packages need to handle real-world `while True:` programs without killing them.

## What worked

- **Deploy of `http_server/circuitpython_two_thing_server` to Pi Pico W CP** — captured `ADAPTER: cp`, `WIFI_OK ip=192.0.2.21`, and `Server listening on 0.0.0.0:8080` inline during the deploy's serial-attached window.  Confirmed `_State` class-level annotations don't break CP runtime (annotations stripped per Decision 0021).
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

- **FAT32 corruption from concurrent host-write + device-USB-MSC interaction.**  FAT32 on USB-MSC has no journaling; a partially-written FAT chain can leave the volume in a state where the macOS `msdosfs` driver remounts it read-only as a self-defense measure.  The Pi Pico W's slower MSC controller (already noted in `circuitpython_transport.py:1442-1447` as a known stale-FAT-view source) makes this more likely on rp2 boards.
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
- `ping 192.0.2.21` (the board's previously-known IP) gets no response — wifi may have disconnected during the reboot loop

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

Bench-validated on Lolin S2 CP (`/dev/cu.usbmodemABCD1234`) with a `while True: print(counter); time.sleep(0.5)` probe via `chumicro-deploy deploy --transport circuitpython --address ... --drive /Volumes/CIRCUITPY --deploy-mode flash`.  Deploy captured counter=1..20 inside the 10 s window, returned cleanly.  `chumicro-repl --tail 5` immediately afterward saw counter=41..50 — `code.py` survived the deploy and kept printing on its own time.

Pi Pico W CP not validated this step — its `/Volumes/CIRCUITPY 1` mount went stale during the prior session and got force-unmounted; needs a replug for a full 4-board sweep (deferred to Step 6 after Steps 2 + 3 land).

### Step 2 — Bump post-stat settle from 0.5 s to 2 s (correction; was "autoreload-driven reset")

**Original Step 2 was wrong.**  The "let CP's autoreload watcher fire the reset" idea assumed CP would replay write events from the autoreload-off window.  Reading `.tools/circuitpython-10.2.0/supervisor/shared/reload.c`:

- `autoreload_trigger()` (line 67) checks `autoreload_enabled` *at the moment of the trigger*.  If autoreload is off (which it is during our rsync), the trigger is **dropped entirely** — there is no replay queue.
- `autoreload_enable()` (line 45) actively *resets* `last_autoreload_trigger = 0`, so re-enabling autoreload clears any pending state too.

So the "re-enable autoreload, let CP fire its own reset" plan would result in the board sitting at friendly REPL with autoreload on but no trigger pending — `code.py` never runs.  CP's `supervisor.reload()` exists but goes through the same `reload_initiate()` path as Ctrl-D — same race window with FS writes.  And we cannot leave autoreload ON during rsync: the `_disable_autoreload_before_drive_writes` docstring documents the "wedged rsync" failure mode (autoreload fires mid-rsync, USB-CDC re-enumerates, next host-side `write()` hangs in uninterruptible kernel I/O).

The actual lever for the S2 FAT race is **timing**, not mechanism.  The current `_BOARD_FILE_VISIBLE_POST_SETTLE = 0.5` was empirical guesswork and is too short to guarantee in-flight FAT writes have committed before our Ctrl-D.  Bump to 2 s — cheap, reversible, addresses the user's "0.5 s is too short regardless" intuition as a belt-and-suspenders fix.

### Step 2b — Post-rsync verification pass via `rsync --checksum --dry-run` ✅

Shipped 2026-05-09.  `flash_drive.verify_rsync()` runs `rsync --recursive --checksum --dry-run --itemize-changes` against the same staging tree the main rsync just wrote, parses `--itemize-changes` output, and returns the list of paths that would still need updating.  Filtering on the position-1 update marker (`<` / `>` / `c` / `h`) — not per-attribute flags — sidesteps cosmetic FAT-mtime deltas (`.f..T....`) firing false positives.

`_push_staging_to_drive` calls `verify_rsync` after `flush_volume` and before returning.  Non-empty divergent-paths list raises `CircuitpythonTransportError` with the recovery procedure (RESET + replay) named in the message — the deploy fails before Ctrl-D triggers a soft-reboot against an inconsistent volume.

Tests: 7 new `TestVerifyRsync` cases (clean match, content divergence, missing file, time-only diff filter, missing rsync, subprocess error, timeout recovery hint) + 1 transport-side `test_post_rsync_verification_failure_raises`.  840 deploy tests pass at 95% coverage.

Bench-validated on Lolin S2 CP — clean deploy wall-time grew from ~13.6 s (Step 2 alone) to ~13.7 s; verification is essentially free at typical CIRCUITPY payload sizes.  Mount stays read-write across iterations.

### Step 3 — Configurable capture window ✅

Shipped 2026-05-09.  `--tail-seconds N` plumbs end-to-end:

- `CircuitpythonTransport.deploy_files(tail_seconds=N)` — overrides the default `self.timeout` for the post-Ctrl-D read window.  `0.0` short-circuits the read entirely (return immediately, leave board running).  `None` keeps the existing 10 s default for back-compat.
- `Deployer.deploy()` / `.deploy_diff()` accept `tail_seconds=N` and route to CP transports through `_deploy_files_kwargs` (MP transports ignore it — `mpremote` follow mode owns its own timing).
- `_RecoveringDeployer` + `InteractiveDeployer` forward `tail_seconds` through their wrappers.
- `chumicro-deploy deploy --tail-seconds N` CLI flag exposes it.

Default behavior unchanged for back-compat.  842 deploy tests pass at 95% coverage (840 pre-Step-3 + 2 new: `test_tail_seconds_zero_returns_immediately_with_empty_output`, `test_tail_seconds_overrides_default_window`).  `chumicro-deploy 0.9.0 → 0.10.0` (additive API).

Bench-validated on Lolin S2 CP:

- `--tail-seconds 0` → 3.6 s deploy (rsync + verification + Ctrl-D, no capture).  Empty stdout.
- `--tail-seconds 20` → 23.6 s deploy, captured `LOOP_PROBE counter=1..40` (20 s × 2 prints/sec, matches the probe's `time.sleep(0.5)`).

### Step 4 — Strip stale autoreload framing from recovery hint ✅

Shipped 2026-05-09.  `FLASH_COPY_FAILED` recovery-hint fix-steps in `recovery.py` no longer name autoreload as the cause (deploy disables autoreload before any rsync, so it cannot have been the cause).  New phrasing names the actual recovery sequence: tap RESET → wait for remount → retry, with the macOS `msdosfs` RO-flag clearing as the underlying mechanism.  No tests asserted on the old phrasing, so no test changes needed.

After all four land: 4-board validation sweep on Lolin S2 CP+MP and Pi Pico W CP+MP, mqtt + udp + http_server.

### Step 1b — Stop killing main.py at end of MP soft_reboot deploy ✅

Discovered during the 4-board sweep.  `MicropythonTransport.deploy_files(follow="soft_reboot")` was calling `self._serial.enter_raw_repl(soft_reset=False)` after the post-Ctrl-D read window, which sends Ctrl-C × 2 + Ctrl-A (per mpremote `transport_serial.py:163-171`) — same problem as CP's old behavior, just in a different transport.

Fix: dropped the post-soft-reboot `enter_raw_repl` call.  Subsequent transport ops re-enter raw REPL on demand via `_ensure_serial`; disconnect tolerates either REPL state.  Test renamed `test_re_enters_raw_repl_after_read` → `test_does_not_re_enter_raw_repl_after_read` with an index-based assertion that no `enter_raw_repl` appears after the soft-reboot read_until.  842 deploy tests pass.

### 4-board validation sweep — results

Bench-tested 2026-05-09 across Lolin S2 CP, Pi Pico W CP, Lolin S2 MP, Pi Pico W MP.

**loop_probe (deploy + tail proves entrypoint survives the deploy):** all 4 boards — deploy captures counters during the configured window, then `chumicro-repl --tail` immediately afterward sees counters continuing past the captured range.  The structural fix from Step 1 (CP) and Step 1b (MP) is end-to-end on every (board, runtime) pair.

**`test-workbench-functional --workbench deploy` per board:**

- Pi Pico W CP defaults: 14/16 pass.  2 environmental failures, neither caused by workstream changes:
  - `test_circuitpython_diff_deploy_round_trip` — `list_files_in_scope` reads from the configured `circuitpy_drive_path` without the auto-correct path that `_resolve_circuitpy_drive` + `_verify_drive_for_board` provides for `deploy_files`; in a multi-board host where macOS swaps the bare-name vs `CIRCUITPY 1` mounts between sessions, the diff path consults the wrong drive and reports zero stale files.  Fixed locally by swapping `devices.yml` paths.  Real fix: extend the auto-correct to `list_files_in_scope`.
  - `test_circuitpython_wipe_reformats_circuitpy_drive` — after `storage.erase_filesystem()`, the CIRCUITPY volume comes back at `/Volumes/CIRCUITPY*` with `d--x--x--x` permissions (`PermissionError: [Errno 13] Permission denied: ...chu-probe`).  This is the macOS FSKit wedge documented in `chumicro_deploy.macos_fskit.MACOS_FSKIT_RECOVERY_COMMAND` — needs `sudo killall -9 com.apple.fskit.msdos fskitd ...` + `launchctl kickstart -k` to recover, or a physical replug.  Not a chumicro logic bug; the wipe code itself works (manual `chumicro-workspace reset-board --yes` was bench-confirmed before the test ran).
- Lolin S2 CP defaults (after swapping devices.yml defaults): 15/16 pass.  Only the same wipe-wedge failure recurred.

**MP boards** are exercised through the same suite (the deploy package's flash-mode tests cover both transports).  The MP-specific tests (`test_micropython_*`) all pass; only the CP wipe-wedge flake recurs and that's environmental.

Net: deploy reliability changes (Steps 1, 1b, 2, 2b, 3, 4) ship clean across all 4 boards.  Two follow-ups surfaced during the sweep, both unrelated to the workstream's structural goals:

1. `list_files_in_scope` should run the same drive-verify auto-correct as `_resolve_circuitpy_drive` + `_verify_drive_for_board` so multi-board hosts with stale `circuitpy_drive_path` entries don't silently diff against the wrong drive.
2. The CP wipe test's wedge state on macOS is an FSKit / msdosfs interaction we already document in `recovery.py`; no code change needed, but the functional test should probably skip itself when it detects the post-wipe permission-denied state instead of retrying for 10 s and failing — or call the documented unwedge command before retrying.

Detail belongs in commit messages + this workstream — `plans/next-up.md` carries a one-line pointer.
