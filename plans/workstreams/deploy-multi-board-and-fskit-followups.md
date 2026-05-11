# Workstream: Multi-board CP deploy + FSKit recovery follow-ups

Status: **partly shipped.**  Items 1, 2, 3, 4 + the `doctor --fix-fskit-wedge` wrapper landed 2026-05-09; Item 6 considered and dropped.  Item 5 (end-to-end bench validation of the recovery command) is deferred to the next natural FSKit-wedge occurrence — try-on-demand didn't reproduce.  Each item below names the *evidence*, the *current thinking*, and (for Item 5) *what the next session should verify when the wedge surfaces*.

## For the new session — pickup checklist

1. `git --no-pager log --oneline -10` — the rollover commits (`5246a1b` workstream park → `a2f60b1` framing fix) are from the 2026-05-09 investigation.  Read commit messages `8e39847` (Item 3 fix), `bbe45e7` (Item 1 fix), and `a2f60b1` (Item 3 framing correction) — they cover the evidence + reasoning.
2. Read this whole file.  Pay special attention to:
   - **Item 2** — the wedge-detection wiring is *purely defensive* against a real macOS FSKit wedge during a wipe.  It is NOT the cause of the Item 3 wipe failure (Item 3 disproved that — see Item 3's body).
   - **Operational notes** at the bottom — load-bearing for any bench-touching work.
3. Suggested order: **Item 4 first** (cheap doc note, no bench), then **Item 2** (source-side wiring lands without bench, validation gated on Item 5), then **Item 5** (deliberate FSKit wedge on a fresh boot — bench prerequisite for ending the workstream).
4. Bench artefacts from the 2026-05-09 investigation live under `.scratch/` (gitignored) — useful as a reference for what worked / failed:
   - `repro_wipe_byte_trace.py` — first byte-traced repro showing `OK` + post-soft-reboot artifacts.
   - `repro_suite_wipe_bytes.py` — instrumented `_send_repl_command` showing autoreload-off succeeds and the next `erase_filesystem` is still pre-empted.
   - `repro_with_settle_delay.py` — proves a 2.0 s sleep between sentinel write and `connect()` lets the wipe succeed (the empirical test that anchored the soft-reboot-pre-empt finding).
   - `repro_wipe_uuid_check.py` — diskutil-based volume-UUID before/after compare proving the FAT is genuinely never reformatted.
   - `wipe_fix_full_suite.log` — full 16-test functional-suite green run after the Item 3 fix.

This workstream exists because the deploy-reliability session ran out of cycles to test the hypotheses cleanly, and several of them touch one another (e.g. wedge recovery wiring depends on what the wipe-test failure mode actually is, which depended on the suite-state hypothesis).

## Item 1 — `list_files_in_scope` and `delete_files` skip the drive auto-correct — **DONE 2026-05-09**

`list_files_in_scope` (line 1512 → 1513) and `delete_files` (line 1539 → 1540) now both pair `_resolve_circuitpy_drive` with `_verify_drive_for_board`, matching `_push_staging_to_drive`'s pattern.  Two regression tests landed in `TestListFilesInScopeAndDelete` proving the bug existed (both failed before the fix) and the auto-correct now redirects to the connected board's mount.  Full deploy unit suite (845 tests) green.

Original observation kept below for context.

### Original observation

**Evidence:**
- `_resolve_circuitpy_drive()` is called at three sites in `workbench/deploy/src/chumicro_deploy/circuitpython_transport.py`:
  - Line 1010 in `_push_staging_to_drive` — followed by `_verify_drive_for_board(drive_path)` on line 1011 (auto-correct active).
  - Line 1512 in `list_files_in_scope` — **no follow-up verify call**.
  - Line 1539 in `delete_files` — **no follow-up verify call**.
- Bench-observed during the 2026-05-09 4-board sweep: with `devices.yml` carrying a stale `circuitpy_drive_path` (pointing at the other board's mount because macOS swapped bare-name vs `CIRCUITPY 1` between sessions), `test_circuitpython_diff_deploy_round_trip` reported zero stale files — `list_files_in_scope` had read the wrong drive.

**Current thinking (NOT verified):**
- Adding `_verify_drive_for_board(drive)` after `_resolve_circuitpy_drive()` in both `list_files_in_scope` and `delete_files` should be a one-line fix at each site.  The verify method is already idempotent (fails open when board UID can't be probed) and was bench-validated for the deploy path.
- `delete_files` is the more dangerous of the two: it can wipe user data on the *other* board's CIRCUITPY drive when the diff path runs against a stale path.  `list_files_in_scope` returning a wrong list is correctness-affecting but not destructive.
- A focused unit test could mock `_resolve_circuitpy_drive` returning path A while `_verify_drive_for_board` corrects to path B, then assert that `delete_files(["/x.py"])` actually unlinks from path B.

**What to verify:**
1. Is there a reason the verify call was deliberately *omitted* from these two sites?  Read the `_verify_drive_for_board` docstring and the commit that introduced the auto-correct (probably has a "limited to deploy_files because of <reason>" rationale).
2. Does verify need to be skipped when the transport's `mode` isn't `"flash"`?  `list_files_in_scope` already returns `[]` early on non-flash; double-check `delete_files`.
3. Is there a hardware-light way to test this — i.e. mock the probe so the verify does the redirect — that doesn't require two boards plugged in?

## Item 2 — `detect_fskit_wedge` wiring beyond `InteractiveDeployer` — **source-side DONE 2026-05-09; bench validation gated on Item 5**

> **Important reframing post-Item-3:** Item 3's investigation *disproved* the original hypothesis that the suite-mode wipe failure was an FSKit wedge.  The wipe-test was being pre-empted by a soft-reboot from the test's own host-side direct write; nothing to do with the macOS FSKit kernel-wait state.  Item 2's wedge wiring is therefore **purely defensive** — it catches a *real* macOS FSKit wedge that happens during a wipe (a separate failure class from Item 3), so users see "the FSKit recovery dance" instead of a generic-timeout error.

Source-side wiring shipped in two places:

- `_wait_for_circuitpy_remount`'s timeout error message in `circuitpython_transport.py` was rephrased to "CIRCUITPY drive not mounted at {path} within {N}s of storage.erase_filesystem(); last error: ..." so the substring matches `_CIRCUITPY_DRIVE_PATTERNS["circuitpy drive not mounted"]` in `recovery.py`.  The classifier now routes the timeout to `CIRCUITPY_DRIVE_MISSING`, which `_RecoveringDeployer._resolve_kind` promotes to `MACOS_FSKIT_WEDGED` when `detect_fskit_wedge()` reports True.  `test_wipe_filesystem_remount_timeout_promotes_to_fskit_wedged` proves the chain end-to-end through `InteractiveDeployer`.  The serial-reconnect timeout earlier in `wipe_filesystem` deliberately stays port-shaped — that's a USB-CDC issue, not the FAT-remount-stall signature of an FSKit wedge.
- `workbench/deploy/functional_tests/conftest.py` got a session-scoped autouse fixture that calls `detect_fskit_wedge()` once at session start and `pytest.skip`s the entire suite with the killall recovery command if wedged.  No-op on non-macOS.  Without this, a pre-existing wedge turned the suite into a 10-second-per-test failure cascade.

**`chumicro-workspace doctor --fix-fskit-wedge` shipped same-session.**  The opt-in sudo wrapper lives in `workbench/workspace/src/chumicro_workspace/cli.py` (`_fix_fskit_wedge`).  Detect → refuse-if-not-wedged (per Item 4 caveat) → refuse on non-darwin / non-TTY / no-sudo → run `subprocess.run(MACOS_FSKIT_RECOVERY_COMMAND.split())` so sudo prompts inline → settle 2 s → re-detect → report.  Distinct exit codes (2 non-darwin, 3 not-wedged, 4 no-tty, 5 no-sudo, 6 wedge persists) for scripted callers.  Seven unit tests in `TestDoctorFixFskitWedge` cover each branch with stubbed subprocess + detector.  Doc note added to `docs/troubleshooting/macos-circuitpy.md`.

**Plain `chumicro-workspace doctor` now detects the wedge too (without fixing it).**  New `check_macos_fskit_wedge()` in `workbench/workspace/src/chumicro_workspace/health.py` is the sixth doctor check — calls `detect_fskit_wedge()` on darwin (no-op + OK row on Linux/CI), surfaces an ERROR `HealthFinding` pointing at `--fix-fskit-wedge` and the manual paste fallback when wedged.  Wired into `collect_doctor_findings`, NOT `collect_health_findings` — `status` polls quickly + frequently, the subprocess probe is doctor-tier weight.  Three new tests in `TestCheckMacosFskitWedge` (non-darwin, healthy, wedged) plus a flip-exit-to-one regression in `TestDoctor.test_wedge_detected_flips_exit_to_one`.  An autouse fixture in `TestDoctor` stubs the detector to False so the existing tests stay deterministic regardless of the dev machine's actual wedge state.

**Bench validation pending:** Item 5 — without a deliberate FSKit wedge on a fresh boot, the timeout-message wiring + the wrapper's killall round-trip are unit-tested but not hardware-validated.  See Item 5 below for the runbook.

## Item 3 — Suite-state wipe failure — **DONE 2026-05-09**

Root cause was *not* the Step-1 disconnect change.  Bench-reproduced minimum repro (`test_circuitpython_diff_deploy_round_trip` then `test_circuitpython_wipe_reformats_circuitpy_drive`); volume-UUID before/after comparison proved the FAT was genuinely never reformatted (no host-view-stale issue).  User confirmed `import storage; storage.erase_filesystem()` works fine when run manually — the wipe code itself is healthy.

The trigger is the test's host-side `sentinel.write_bytes(b"marker")` directly to `/Volumes/CIRCUITPY` — outside the rsync/autoreload-protected path the rest of the deploy machinery uses.  That direct write queues a soft-reboot in the device runtime; when the test's `transport.connect()` + raw-REPL `storage.erase_filesystem()` lands shortly after, raw REPL ack-emits `OK` (script accepted), but the queued soft-reboot fires before — or during the very first instruction of — the script's `usb_disconnect → 1000 ms delay → reformat → reset` sequence.  The reformat step never runs.  After the soft-reboot, code.py runs against the un-reformatted FAT, the board lands in "Done"/raw-REPL state, the host's next read picks up the post-soft-reboot artifacts (Done-title + fresh raw-REPL banner — no `\x04` markers, parser raises malformed-response), `wipe_filesystem`'s `except Exception: pass` swallows it, the post-wipe reconnect succeeds because USB-CDC stayed alive across the soft-reboot, `_wait_for_circuitpy_remount` sees a writable directory immediately because the drive never went away, and `wipe_filesystem` returns "successfully" with the FAT intact.  A 2.0 s sleep between the host write and `transport.connect()` makes it succeed reliably (the queued soft-reboot has fired and settled before our raw-REPL session starts).  Setting `supervisor.runtime.autoreload = False` inside the wipe path *does not* fix it (the byte trace confirms autoreload-off succeeds and the next `erase_filesystem` is still pre-empted, so whatever the underlying mechanism is — autoreload-pending exception already queued before the disable, USB-MSC mount-lock state, or something else — it's not reached by the user-toggleable autoreload flag at the moment the wipe path can disable it).

Fix: rewrite `test_circuitpython_wipe_reformats_circuitpy_drive` to plant the sentinel via `Deployer.deploy(FileMapSource({"/code.py": noop, "/wipe_test_sentinel.txt": b"marker"}, ...))`.  The deploy mechanism's existing rsync + autoreload-disable + post-soft-reboot settle dance leaves the board in a quiet known state when the wipe runs.  Full 16-test functional suite green.

**Considered and rejected: a proof-of-life defense in `wipe_filesystem`.**  The Item 3 trigger was a misbehaving test (host-side sentinel write queued an autoreload soft-reboot that landed during the wipe call).  The fix replaced the host-side write with `Deployer.deploy()`, which already disables autoreload + settles the board.  Real users running `chumicro-workspace deploy --wipe` go through the deploy machinery, so they don't set up Item 3's preconditions.  An earlier draft of this workstream proposed catching the soft-reboot signature in `_send_repl_command`'s response bytes and raising loudly; dropped because the only concrete cause was the now-fixed test, the speculative "future causes" list (different host-write timing, queued soft-reboot from a different source, runtime-version difference) had no grounded examples, and the current `try: ... except Exception: pass` is correct for the only real-world outcome (USB-CDC drops mid-call as the success signal).

### Original observation

**Evidence:**
- `test_circuitpython_wipe_reformats_circuitpy_drive` passes in isolation (`pytest workbench/deploy/functional_tests/test_wipe_filesystem_hardware.py::test_circuitpython_wipe_reformats_circuitpy_drive`) but fails when the full suite runs (`pytest workbench/deploy/functional_tests/`).
- Failure mode: `wipe_filesystem()` returns cleanly, drive remounts, but the seeded `wipe_test_sentinel.txt` is still present.  After bench manual-wipe the sentinel was gone — confirming the wipe code itself works.
- Manual `t.wipe_filesystem()` called from a fresh Python session (with the same Pi Pico W board as target) succeeded: drive came back with default `boot_out.txt` + 22-byte default `code.py`, no sentinel.
- diskutil unmount + remount of `/Volumes/CIRCUITPY` did NOT remove the sentinel after the suite-failure case — the sentinel was genuinely on disk, not just stale macOS cache (this means the wipe didn't actually run on the device, OR something rewrote the sentinel after the wipe).
- Step 1 of workbench-deploy-reliability changed `disconnect()` to leave the board in friendly REPL with `code.py` running rather than in raw REPL.  test_deploy_files_hardware deploys short `print(...)` scripts (no `while True`), so the entrypoint exits before disconnect — but the post-disconnect REPL state is now "friendly REPL with autoreload watcher live" instead of "raw REPL exited."

**Current thinking (NOT verified):**
- Most plausible: the suite ordering (test_deploy_files → test_diff_deploy → test_wipe_filesystem) leaves the board in a state where the wipe test's `t.wipe_filesystem()` call sends `storage.erase_filesystem()` over raw REPL but the call doesn't actually execute on the device.  Possible mechanisms:
  - `_enter_raw_repl()` thinks it succeeded but didn't actually cleanly enter raw REPL (the prompt-detection succeeded against pre-buffered bytes from the prior test).
  - The board was in friendly REPL but autoreload had queued a reboot from one of the deploys, and that reboot landed exactly when our `storage.erase_filesystem()` raw-REPL command was sent — so the command went into the bit-bucket during the reset window.
  - macOS's USB-MSC view of the volume was wedged from the previous test's writes, and `storage.erase_filesystem()` ran but the host never saw the post-reformat state.
- Less plausible but worth ruling out: chumicro_pytest_device or another conftest is leaving connections open across tests, holding the serial port and blocking the wipe test's connect.
- Step 1's "leave code.py running" change is the nearest behavior change — but the suite test programs all return immediately (no `while True`), so the "code.py running" angle doesn't apply directly.  More likely it's the *autoreload-watcher-live* post-state that introduces a new race.

**What to verify (the reproducer):**
1. Write a `.scratch/repro_suite_state.py` script that mimics the suite ordering: `Deployer.deploy(short_print_source)` x N → `Deployer.deploy_diff(another_source)` → `transport.wipe_filesystem()`.  Log the raw-REPL response bytes at each step.  Run on Pi Pico W CP first (bench-confirmed failing case).
2. If the reproducer fails, instrument `wipe_filesystem` to read whatever bytes the device actually returned from the `storage.erase_filesystem()` raw-REPL command before swallowing the exception.  The current code has a bare `except Exception: pass` (line ~1542) that hides what actually happened.
3. Bisect Step 1 — temporarily revert the disconnect change in a `.scratch/` branch and re-run the full suite.  If it passes with the revert, the autoreload-watcher-live hypothesis is the cause and the fix is to add an explicit autoreload-OFF in the disconnect path.
4. Check whether `_enter_raw_repl`'s prompt detection is robust against pre-buffered bytes.  `_read_until(_RAW_REPL_PROMPT)` may be eating leftover content from the prior session's print output and falsely returning success.

## Item 4 — "Don't run the FSKit recovery command twice" — **DONE 2026-05-09**

The "only run when wedged" caveat now lives in two places that are part of the user-facing recovery surface: `docs/troubleshooting/macos-circuitpy.md` (paragraph above the bash code block — kept outside the block so the doc-recovery-block-matches-constant drift test stays passing) and the `MACOS_FSKIT_WEDGED` RecoveryPlan in `recovery.py` (new "Run it ONLY ONCE per wedge" fix_step in the InteractiveDeployer coaching output).  Both name the I/O-error state and that physical unplug + replug is the recovery — soft-reboot doesn't work because USB-MSC stays attached across it.  122/122 tests in `test_recovery.py` pass; the `test_macos_fskit_wedged_plan_contains_recovery_command` constant-drift guard stays green.

Open follow-up (not blocking): is there a less-destructive recovery for the post-second-run I/O-error state?  Soft-reboot via raw REPL didn't work in 2026-05-09; `microcontroller.reset()` (full hardware reset, USB re-enumerates) was not tried but might recover without physical replug.  Worth a single-board test on the next bench session — not a workstream-blocker.

## Item 5 — End-to-end bench validation of the corrected `MACOS_FSKIT_RECOVERY_COMMAND` — **deferred to next natural occurrence**

**Status:** validation gated on the wedge happening organically.  A 2026-05-09 bench attempt to deliberately trigger it from a healthy starting state didn't reproduce — try-on-demand isn't reliable.  The wrapper + detection wiring stay source-validated; end-to-end proof rides on the next time the wedge surfaces during normal CP work.

**What was tried 2026-05-09 (none triggered the wedge):**

- 6× alternating CP `chumicro-workspace deploy-example timing circuitpython_blink` (Lolin S2 ↔ Pi Pico W).  All clean, `Ss` state throughout.
- 3× consecutive `pytest workbench/deploy/functional_tests/test_wipe_filesystem_hardware.py::test_circuitpython_wipe_reformats_circuitpy_drive`.  All passed, `Ss`.
- Full `pytest workbench/deploy/functional_tests/` suite (16 tests, 45 s).  All passed, `Ss`.
- 30× tight host-side write+delete loops against each `/Volumes/CIRCUITPY*` drive.  Pi Pico W's drive surfaced transient `Input/output error` mid-loop and recovered to fully functional after settling — daemon stayed `Ss` throughout.  Some directory-listing staleness lingered (rm reported success but `ls` still showed the file) — clears on next drive remount.
- Concurrent host-write loops on both drives + parallel `diskutil list` / `diskutil info` probes.  The Lolin S2 drive (`/Volumes/CIRCUITPY 1`) refused every write with "No such file or directory" throughout the run — carry-over stale-mount state from the earlier 30× write+delete loop on the same drive, not the FSKit wedge.  Post-stress `ps -o state=` showed `Ss` and `detect_fskit_wedge()` returned False.

**User's bench notes for the next attempt:** patterns that *have* triggered it in their experience are write-then-immediately-wipe, manual host-side write+delete-sentinel, and write-then-immediately-reboot.  All have the shape "FAT volume in flux + a destructive op landing on it before the host catches up."  Tighter/concurrent variants of those — host write racing a `storage.erase_filesystem()`, or a host write racing `microcontroller.reset()` — would be the next things to try if a deliberate trigger is needed before the next natural occurrence.  Don't sink another full session into reproducing it deliberately; the wedge has surfaced naturally twice in this codebase's history and will again.

**Checklist for when the wedge surfaces naturally**

When `chumicro-workspace doctor` next reports `MACOS FSKIT ✗ wedged`, or any flash-mode deploy hangs / fails with the wedge symptoms (CIRCUITPY drive missing, `diskutil list` hangs):

1. **Confirm the wedge.**  Any of:
   ```
   chumicro-workspace doctor                  # MACOS FSKIT row → ERROR
   ps -o state= -p $(pgrep diskarbitrationd)  # contains "U"
   .venv/bin/python -c "from chumicro_deploy.macos_fskit import detect_fskit_wedge; print(detect_fskit_wedge())"  # True
   ```

2. **Capture state for the post-validation note.**  Before clearing — record what was running when it wedged (which deploy / test / manual op), and which commit is checked out.  This is the bench evidence the workstream needs to retire.

3. **Clear via the wrapper.**  In a real Terminal.app tab (NOT through Claude Code's `!` prefix — no TTY for the sudo password):
   ```
   chumicro-workspace doctor --fix-fskit-wedge
   ```
   Equivalent manual paste: `sudo killall -9 com.apple.fskit.msdos fskit_helper fskitd fskit_agent diskarbitrationd DiskArbitrationAgent`.

4. **Confirm cleared.**
   ```
   chumicro-workspace doctor                  # MACOS FSKIT row → ✓
   ls /Volumes/ | grep CIRCUITPY              # both drives back
   echo test > /Volumes/CIRCUITPY/.probe && rm /Volumes/CIRCUITPY/.probe && echo "RW"
   ```
   If drives haven't reappeared, unplug + replug the boards.

5. **Re-run the work that wedged it.**
   ```
   .venv/bin/python -m pytest workbench/deploy/functional_tests/ --no-cov
   ```
   If green: validation complete.  Edit this section to `**DONE YYYY-MM-DD**` with a one-liner ("wedge hit during X, `doctor --fix-fskit-wedge` cleared it cleanly, suite re-ran 16/16 green") and drop the checklist.

**If `doctor --fix-fskit-wedge` doesn't clear it** (the unproven-by-bench risk in commit `f9eca27` — `killall -9 DiskArbitrationAgent` may not unstick the per-user agent):
- Try a reboot — that always clears it per the macOS-circuitpy doc.
- File the failure mode here: which approach landed (or didn't), and the exit code.  The wrapper's `_FSKIT_FIX_EXIT_PERSISTS` (6) is the "killall returned but wedge stayed" path; that's the signal that the source change needs another iteration.

## Operational notes (for the next session, not for code)

- **Do not manually `diskutil unmount` CIRCUITPY drives during troubleshooting.**  User feedback during this session: that's not how to recover; let the deploy/transport path own mount state.  My `diskutil unmount` attempts during the I/O-error recovery (after the second-run damage) made things harder, not easier.
- **Verify state before committing fixes that depend on bench evidence.**  I committed the recovery-command source change (`f9eca27`) on user "done" without re-detecting the wedge state or re-running the failing test first.  Source change happened to be correct but the commit message claimed evidence I hadn't actually collected.  Re-detect → re-run → confirm green → commit is the right order.
- **Multi-board CP setups: macOS swaps bare-name vs `CIRCUITPY 1` between unmount/remount cycles.**  `devices.yml` `circuitpy_drive_path` entries go stale frequently in this layout.  Item 1's fix removes the silent-wrong-drive class of bug, but the underlying instability suggests `circuitpy_drive_path` should auto-resolve via UID lookup at every connect (not just at deploy-files time) — possibly worth its own ADR.

## Suggested order

1. ~~**Item 1**~~ — done.
2. ~~**Item 3**~~ — done.
3. **Item 4** (doc + RecoveryPlan caveat) — cheap, no bench needed.
4. **Item 2** (wedge-detection wiring) — source-side lands without bench; end-to-end validation pairs with Item 5.  Purely defensive against a real macOS FSKit wedge during a wipe, not the cause of any known failure.
5. **Item 5** (end-to-end bench validation of recovery command) — needs a deliberate FSKit wedge on a fresh boot.  Bench prerequisite to closing the workstream.

## Triggered by

User feedback during 2026-05-09 workbench-deploy-reliability session, after the 4-board sweep surfaced two functional-test failures (one of which was the FSKit wedge that drove this investigation).  The session ran out of bench-cycle budget for proper repro after the recovery-command fix; this workstream is the rollover.
