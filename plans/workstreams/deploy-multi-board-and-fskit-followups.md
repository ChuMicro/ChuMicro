# Workstream: Multi-board CP deploy + FSKit recovery follow-ups

Status: **partly shipped.**  Items 1 and 3 landed 2026-05-09 in this same investigation session — the deeper pass found both bugs reproducibly and fixed them.  Items 2, 4, and 5 remain open.  Each item below names the *evidence*, the *current thinking*, and (for the open ones) *what the next session should verify*.

This workstream exists because the deploy-reliability session ran out of cycles to test the hypotheses cleanly, and several of them touch one another (e.g. wedge recovery wiring depends on what the wipe-test failure mode actually is, which depends on the suite-state hypothesis).  Tackle them in the order below — earlier items inform later ones.

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

## Item 2 — `detect_fskit_wedge` is only wired into `InteractiveDeployer`

**Evidence:**
- `grep -rn "detect_fskit_wedge" workbench/deploy/src/` shows two call sites:
  - `recovery.py:639` — `_RecoveringDeployer.__init__` accepts a `fskit_wedge_detector` callable, defaults to `detect_fskit_wedge`.
  - `recovery.py:876` — `InteractiveDeployer` (subclass) wires it through.
- Not wired into:
  - `CircuitpythonTransport.wipe_filesystem()`'s reconnect-loop timeout (line ~1640-1652) — when the post-wipe drive doesn't remount within `_WIPE_FAT_REMOUNT_TIMEOUT_SECONDS`, the function raises a generic `CircuitpythonTransportError` with no wedge classification.
  - `_resolve_circuitpy_drive()`'s "drive not found" exception path.
  - `workbench/deploy/functional_tests/conftest.py` — tests connect to transports directly (bypassing `Deployer`), so they bypass the wedge promotion.
  - `chumicro-workspace doctor` — could detect proactively rather than waiting for a failure.

**Current thinking (NOT verified):**
- The wipe-test failure that hit during the 2026-05-09 sweep (`test_circuitpython_wipe_reformats_circuitpy_drive`) returned a generic "did not become usable within 10s" message after the fskit wedge had silently triggered.  If `wipe_filesystem`'s timeout path called `detect_fskit_wedge()` and raised a `MACOS_FSKIT_WEDGED`-classified error, the test could `pytest.skip(...)` with the actionable recovery command instead of failing.
- For the functional test conftest: a session-scoped `autouse` fixture that calls `detect_fskit_wedge()` at session start and skips the whole flash-mode suite with the recovery command would prevent every flash test from failing individually with a generic error.
- `chumicro-workspace doctor --fix-fskit-wedge` could shell out via `subprocess.run(..., check=False)` so the user gets a single password prompt instead of needing to paste.  Risk: auto-running sudo is a blast-radius decision; per `macos_fskit.py:24` the existing module deliberately doesn't auto-run.  An opt-in `--yes-please-sudo` flag (or just printing "this is what we'd run; type your password") might be the right shape.

**What to verify:**
1. What's the correct exception-type promotion path for `wipe_filesystem` to surface `MACOS_FSKIT_WEDGED`?  The transport currently raises `CircuitpythonTransportError` and the classifier in `recovery.py` maps from message strings — adding the right marker substring may be enough without restructuring.
2. Does the functional test conftest already have a wedge-detection hook somewhere that I missed?  Worth a `grep -rn "fskit\|wedge" workbench/deploy/functional_tests/`.
3. Is "auto-run sudo on user opt-in" actually wanted?  `macos_fskit.py:22-25` is opinionated against it; ADR-worthy to revisit if we're going to wire it in.

## Item 3 — Suite-state wipe failure — **DONE 2026-05-09**

Root cause was *not* the Step-1 disconnect change.  Bench-reproduced minimum repro (`test_circuitpython_diff_deploy_round_trip` then `test_circuitpython_wipe_reformats_circuitpy_drive`); volume-UUID before/after comparison proved the FAT was genuinely never reformatted (no host-view-stale issue).  User confirmed `import storage; storage.erase_filesystem()` works fine when run manually — the wipe code itself is healthy.

The trigger is the test's host-side `sentinel.write_bytes(b"marker")` directly to `/Volumes/CIRCUITPY` — outside the rsync/autoreload-protected path the rest of the deploy machinery uses.  After that direct write, the next raw-REPL `storage.erase_filesystem()` silently no-ops on the device side; the host never sees USB-CDC drop, the drive stays mounted with its old contents, `wipe_filesystem` returns "successfully" because reconnect is instant and `_wait_for_circuitpy_remount` sees a writable directory immediately, and the test's `assert not sentinel.exists()` then fails.  A 2.0 s sleep between the host write and `transport.connect()` makes it succeed reliably; setting `supervisor.runtime.autoreload = False` inside the wipe path *does not* (the byte trace confirms autoreload-off succeeds and the next `erase_filesystem` still no-ops, so the underlying CP-internal mechanism — USB-MSC mount-lock state, autoreload-pending exception already queued, or something else — is not reached by the user-toggleable autoreload flag).

Fix: rewrite `test_circuitpython_wipe_reformats_circuitpy_drive` to plant the sentinel via `Deployer.deploy(FileMapSource({"/code.py": noop, "/wipe_test_sentinel.txt": b"marker"}, ...))`.  The deploy mechanism's existing rsync + autoreload-disable + post-soft-reboot settle dance leaves the board in a quiet known state when the wipe runs.  Full 16-test functional suite green.

A latent issue surfaced during the investigation that's filed as a follow-up: `wipe_filesystem` has no proof-of-life check for the wipe itself.  When the wipe is a no-op, USB-CDC and the drive both stay alive, so `_wait_for_circuitpy_remount` and the reconnect loop both fast-succeed on stale state.  Any future cause of erase_filesystem-no-op (different test sequence, different runtime version, future hardware) would silently slip through the same way.  The right defense — proof-of-life via volume-UUID comparison or by surfacing the actual raw-REPL response when the script didn't drop USB — is not in this fix.  See `## Item 6` below.

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

## Item 4 — "Don't run the FSKit recovery command twice" — doc note

**Evidence:**
- During the 2026-05-09 session, the user ran the (corrected) `MACOS_FSKIT_RECOVERY_COMMAND` twice: first time cleared the wedge cleanly + remounted both CIRCUITPY drives; second run cut off in-flight FAT operations on the just-remounted volumes, leaving them in I/O-error state (`ls: /Volumes/CIRCUITPY: Input/output error`) while still mounted.
- Recovery from the I/O-error state required physical replug of both boards (not unmount/remount, not soft-reboot via raw REPL — the boards' USB-MSC interface stays attached across soft-reboot, so re-enumeration didn't re-present the volumes).

**Current thinking (NOT verified):**
- `docs/troubleshooting/macos-circuitpy.md` should add a one-liner above the recovery command saying "only run this when `detect_fskit_wedge()` returns True (or `ps -o state= -p $(pgrep diskarbitrationd)` shows `Us`).  Running it on a healthy system damages mounted volumes."
- A future `chumicro-workspace doctor --fix-fskit-wedge` wrapper (Item 2) should call `detect_fskit_wedge()` first and refuse to run if not wedged.
- The `RecoveryPlan` for `MACOS_FSKIT_WEDGED` could include the "only when wedged" caveat in its fix-steps too.

**What to verify:**
- Is there a less-destructive recovery if the second-run I/O-error state happens?  Soft-reboot via raw REPL didn't work; `microcontroller.reset()` (full hardware reset, USB re-enumerates) was not tried but might recover without physical replug.

## Item 5 — End-to-end bench validation of the corrected `MACOS_FSKIT_RECOVERY_COMMAND`

**Evidence:**
- The 2026-05-09 source change (commit `f9eca27`) replaced the SIP-blocked `launchctl kickstart` step with a direct `killall -9 DiskArbitrationAgent`.  Source-side validation: 843 unit tests pass + the new `test_doc_recovery_block_matches_constant` drift guard.
- Bench validation of the full clear-wedge-then-recover-test cycle did not complete:
  - The Claude Code `!` shell prefix runs commands without a TTY, so sudo can't read a password through it.
  - The user ran the command outside of Terminal.app (in their main shell) once successfully and once accidentally a second time, leading to Item 4's I/O-error state.
  - After physical replug, isolation-mode wipe test passed — but suite-mode wipe test failed (Item 3, not the recovery command's fault).

**What to verify:**
1. Trigger the wedge deliberately (small FAT12 volume + heavy concurrent probe?) on a fresh boot, confirm `detect_fskit_wedge()` reports True, run the corrected command, confirm `detect_fskit_wedge()` reports False, confirm CIRCUITPY drives remount RW.  This is the missing end-to-end evidence the source change claims but didn't bench-prove.
2. The original wipe-test failure that triggered this whole investigation — re-run after Item 3's reproducer + fix lands, confirm it's stable across consecutive full-suite runs.

## Operational notes (for the next session, not for code)

- **Do not manually `diskutil unmount` CIRCUITPY drives during troubleshooting.**  User feedback during this session: that's not how to recover; let the deploy/transport path own mount state.  My `diskutil unmount` attempts during the I/O-error recovery (after the second-run damage) made things harder, not easier.
- **Verify state before committing fixes that depend on bench evidence.**  I committed the recovery-command source change (`f9eca27`) on user "done" without re-detecting the wedge state or re-running the failing test first.  Source change happened to be correct but the commit message claimed evidence I hadn't actually collected.  Re-detect → re-run → confirm green → commit is the right order.
- **Multi-board CP setups: macOS swaps bare-name vs `CIRCUITPY 1` between unmount/remount cycles.**  `devices.yml` `circuitpy_drive_path` entries go stale frequently in this layout.  Item 1's fix removes the silent-wrong-drive class of bug, but the underlying instability suggests `circuitpy_drive_path` should auto-resolve via UID lookup at every connect (not just at deploy-files time) — possibly worth its own ADR.

## Item 6 — `wipe_filesystem` has no proof-of-life for the wipe itself — **NEW, surfaced during Item 3**

When `storage.erase_filesystem()` runs successfully, USB-CDC drops and the drive remounts with a new volume UUID.  When it's a no-op (the failure mode Item 3 hit), USB-CDC and the drive both stay alive with the *old* contents.  `wipe_filesystem`'s wait-for-reconnect (30 s budget) and `_wait_for_circuitpy_remount` (10 s budget for the configured drive path being a writable directory) both fast-succeed in the no-op case because their conditions are met instantly by the unchanged state.  Result: `wipe_filesystem` returns "successfully" while the FAT is intact.

Two reasonable defenses:

- Compare volume UUID before / after.  Definitive signal — UUID changes iff the FAT was reformatted.  macOS-aware (`diskutil info Volume\ UUID`); other OSes need an alternate path.
- Stop swallowing `_send_repl_command` exceptions.  Surface the actual raw-REPL response when the wipe didn't run, so callers see *what* the device returned.  More general but noisier; needs care because the *successful* erase_filesystem path also raises (USB-CDC drops mid-call before the response arrives).  User's preferred direction during the Item 3 investigation.

Either fix converts a silent no-op-wipe into a loud error so future causes can't hide the same way.  Out of scope for the Item 3 fix that landed; tracked here for a follow-up.

## Suggested order

1. ~~**Item 1**~~ — done.
2. ~~**Item 3**~~ — done.
3. **Item 2** (wedge-detection wiring) — scope is now clearer: Item 3 disproved that the wipe-failure was wedge-related, so the wedge-detection wiring is purely defensive (catches a real macOS FSKit wedge that happens during a wipe, separate failure class).
4. **Item 4** (doc note) — cheap, lands once we're confident about Item 5.
5. **Item 5** (end-to-end bench validation) — should happen alongside any of the above that need a wedge-induced repro.
6. **Item 6** (proof-of-life in `wipe_filesystem`) — durable defense against future no-op-wipe causes.

## Triggered by

User feedback during 2026-05-09 workbench-deploy-reliability session, after the 4-board sweep surfaced two functional-test failures (one of which was the FSKit wedge that drove this investigation).  The session ran out of bench-cycle budget for proper repro after the recovery-command fix; this workstream is the rollover.
