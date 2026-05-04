# Decision 0033: macOS CIRCUITPY deploy hardening

Status: `accepted`
Date: `2026-04-24`
Related: Decision 0028 (deploy modes), Decision 0029 (project workspace).

## Context

`chumicro-deploy`'s CircuitPython flash mode copies files to a
FAT32 volume mounted by macOS, then soft-reboots the board to pick
up the new code.  Every step of that sequence runs into a
different macOS quirk, and each was discovered the hard way during
hardware bring-up.  The fixes are scattered across
`workbench/deploy/src/chumicro_deploy/flash_drive.py` and
`circuitpython_transport.py`; this ADR is the single place the
reasoning lives so future contributors (and third-party consumers
who hit the same surface) do not have to reconstruct it from
commit messages.

The hardenings described here are all **host-side macOS-only**.
Linux FAT32 writes via `rsync` are uneventful.  Windows is not
currently supported but would need its own companion ADR if it
were.

## Decisions

### 1. Strip macOS metadata before writing to CIRCUITPY

Commit `214b361`.  Three host-side cleanups run automatically
around every flash-mode deploy:

- **`xattr -cr <staging>`** before `rsync`.  macOS writes
  extended attributes (`com.apple.FinderInfo`, quarantine flags,
  tags) onto files in the user's home directory as a matter of
  course.  Rsync's default behavior is to try to preserve those
  xattrs on the destination, which on FAT32 produces a `._`
  resource-fork shadow file *per* source file.  On a ~1 MiB
  CIRCUITPY drive with `.py` library files this is the difference
  between a fast copy and a drive full of garbage.
- **`dot_clean <drive>`** after `rsync`.  Even with xattrs
  stripped on the staging side, macOS itself creates `._` files
  when users browse the CIRCUITPY drive in Finder.  `dot_clean`
  either merges the `._X` data back into `X` (if `X` exists) or
  removes `._X` (if not).  Either way the volume stops carrying
  resource-fork baggage.
- **`mdutil -i off <drive>`** before writes.  macOS Spotlight
  will index any mounted volume by default, creating
  `.Spotlight-V100/` metadata trees and holding a read lock that
  dramatically slows concurrent FAT32 writes.  Turning indexing
  off on the volume takes one call.

All three are best-effort: missing tool, permission error, or
non-zero exit is logged at WARNING (no silent swallowing) and
the deploy continues.

### 2. Call `os.sync()` / `sync` and wait before reading back

Commit `96197f2`.  macOS buffers writes to FAT32 USB volumes
in the block cache.  `rsync` returns successfully long before
the bytes hit the physical media, and a device that reads the
file immediately after sees stale (or empty) content.  This is
the "NO TESTS FOUND after the first one" symptom — the board's
`open(test_file).read()` returned the bytes from last session's
file because the new bytes hadn't actually landed yet.

The transport always calls `sync` (or `os.sync()` as fallback)
after the rsync and then sleeps `FLUSH_SETTLE_DELAY` (default
0.5 s) to let the USB-MSC controller quiesce.  The delay is
configurable because some boards' controllers are slower than
others.

### 3. Poll device-side visibility; synchronise capture on soft-reboot

Commit `3f1de8e`.  Even after host-side `sync` + settle, the
*board*'s view of the volume can lag.  CircuitPython's FatFs
layer processes USB-MSC block-write callbacks asynchronously —
the block may be on disk but FatFs still shows the old directory
entry.  Ctrl-D then soft-reboots against that stale view and
re-runs the previous `code.py`, producing a one-cycle-delayed
capture.

Two changes pin the sync point to the board side:

- After the host-side `sync` + settle, poll `os.stat(code.py)`
  **on the board** via raw REPL until the reported size matches
  the host-written size (or the poll budget exhausts).  Proves
  FatFs has seen the new directory entry before we kick the VM.
- When capturing the post-reboot output, discard everything
  before the `soft reboot` marker in the raw REPL stream.
  Pre-reboot bytes still in the kernel/USB-CDC buffer from the
  *previous* run (a complete `code.py output: …` block with
  title-bar escapes) can otherwise land inside this cycle's
  capture window.

Polling has a ceiling (`_BOARD_FILE_VISIBLE_POLL_ATTEMPTS` ×
`_BOARD_FILE_VISIBLE_POLL_INTERVAL`); if the board never sees
the new size the deploy fails loudly rather than silently
capturing last cycle's output.  A belt-and-suspenders
`_BOARD_FILE_VISIBLE_POST_SETTLE` sleep after the poll lets the
board's in-flight flash program/erase and FAT bookkeeping
quiesce before Ctrl-D — hardware-level races the polling
layer can't observe.

### 4. Detect and recover from the FSKit wedge

Commit `6fdc132`.  Recent macOS replaced the in-kernel `msdosfs` driver with a user-space FSKit extension; it can wedge `diskarbitrationd` in uninterruptible kernel wait when a small CIRCUITPY FAT12 volume trips it, and every subsequent DiskArbitration call queues behind the stuck one.  The symptoms, the exact `sudo killall … && launchctl kickstart -k …` recovery chain, and the operational how-to live in [`docs/troubleshooting/macos-circuitpy.md`](../../docs/troubleshooting/macos-circuitpy.md); this decision section covers *why* `chumicro-deploy` handles the wedge the way it does.

- **Detect automatically.** `chumicro_deploy.macos_fskit.detect_fskit_wedge()` probes `ps -o state= -p $(pgrep diskarbitrationd)` with short timeouts and returns `True` when the state contains `U` (uninterruptible kernel wait).  Fails open on every subprocess error — a missing `pgrep` / `ps` binary, a permission issue, or a timeout all return `False` rather than blocking a legitimate `CIRCUITPY_DRIVE_MISSING` retry.
- **Promote the failure kind.** `InteractiveDeployer` takes an injected `fskit_wedge_detector` and, on a `CIRCUITPY_DRIVE_MISSING` failure, promotes the kind to `MACOS_FSKIT_WEDGED` when the detector matches.  The promoted kind carries a different recovery plan that prints the paste-this-command block instead of the generic "tap RESET" steps.
- **Do not auto-run `sudo`.**  Auto-escalating privileges is a blast-radius decision the tool should not take without an explicit opt-in.  Detect + surface + paste keeps the human in the loop.  A future `--auto-fix-fskit-wedge` flag could opt into running the command for CI or scripted use, but that is not the default.
- **Kill the per-user agent via `launchctl kickstart -k`, not `killall`.**  The per-user `DiskArbitrationAgent` has `KeepAlive=false` in its plist — a plain kill leaves it dead and drives mount but do not register with Finder.  `launchctl kickstart -k` stops and restarts the service via launchd, matching the recovery chain's intent.

### 5. Probe the mount before staging; re-raise uniformly

Also commit `6fdc132` (transport side) and classifier
reordering in the same commit.  `/Volumes/CIRCUITPY` can
exist as a directory (`is_dir()` returns `True`) but be
unwritable — the classic Finder-eject-leaves-placeholder case
and the FSKit-wedge case both produce this state.  Rather
than letting the rsync halfway through the copy hit
`EACCES` on the first file and leave a partial state on the
drive, `_resolve_circuitpy_drive()` writes a small
`.chu-probe` marker up-front:

```python
probe = drive_path / ".chu-probe"
try:
    probe.write_bytes(b"")
    probe.unlink()
except OSError as error:
    raise CircuitpythonTransportError(
        f"CIRCUITPY drive not found or not writable: "
        f"{drive_path} ({error.__class__.__name__}: {error})"
    ) from error
```

The classifier routes this message to `CIRCUITPY_DRIVE_MISSING`
(not `PORT_UNAVAILABLE`, despite the nested `"permission
denied"` string — see the classifier ordering fix in the
same commit).  `CIRCUITPY_DRIVE_MISSING` then gets promoted to
`MACOS_FSKIT_WEDGED` on a match per §4.  End-to-end, the user
sees the right coaching regardless of which layer first
detected the problem.

A belt-and-suspenders `try/except OSError` wraps the actual
file-copy loop too — the drive can eject between the probe
and the copy (user hits eject mid-deploy, board reboots
mid-rsync), and raising with the same message keeps the
classifier's hook wired.

## Alternatives considered

- **Linux-only development workaround.** "Just use Linux."
  Rejected — users will use macOS, and the tool is published.
- **Bundle these into the `--fix-mode` flag of a separate
  `chumicro-doctor` CLI.** Considered.  Rejected — users would
  not discover it before hitting the symptoms.  Every hardening
  here except §4 is automatic and transparent; §4 is
  interactive but triggered by normal deploy flow.
- **Auto-run the `sudo killall` chain when the wedge is
  detected.** Rejected — auto-escalating privileges is a
  blast-radius decision the tool should not take without an
  explicit opt-in flag.  Detection + paste-this-command is
  safer and gives the user room to bail.

## Consequences

- Every macOS-specific hardening lives in
  `chumicro_deploy/flash_drive.py` or
  `chumicro_deploy/macos_fskit.py` (new module).  The transport
  composes them; nothing bleeds into the CP/MP library code
  deployed to the board.
- The FAT32 hardenings (§1–§3) are best-effort and log at
  WARNING on failure.  A fresh macOS system without Spotlight
  or a headless user account without `xattr` still deploys; it
  just logs that the optimisation was skipped.
- The wedge detector (§4) fails open: missing `pgrep`/`ps`,
  subprocess timeout, or non-zero exit all return `False`
  (not wedged).  A false positive would silently block
  legitimate `CIRCUITPY_DRIVE_MISSING` retries, which is the
  worse failure mode.
- The probe-marker approach (§5) leaves a transient
  `.chu-probe` on the drive for the duration of the
  `write_bytes()` call; the `unlink()` in the same try-block
  cleans it up on success.  On EACCES the file never got
  created, so there is nothing to clean up.
- Windows support, when it lands, will need a companion
  hardening pass and probably its own ADR.  Nothing in this
  decision assumes darwin except inside `sys.platform ==
  "darwin"` guards, so the Linux fast path is unaffected.
