# macOS CIRCUITPY deploy troubleshooting

Covers the macOS-specific failure modes `chumicro-deploy` hits when writing to the CIRCUITPY USB drive.  The decision rationale (*why* the deploy code works the way it does) lives in [Decision 0033](../../plans/decisions/0033-macos-circuitpy-deploy-hardening.md); this page is the operational how-to for when something has gone wrong and you need to get unstuck.

Linux deploys don't hit any of this.  Windows isn't currently supported.

## The FSKit wedge: `/Volumes/CIRCUITPY` never appears

**Symptoms**

- You unplug and replug the board; `/Volumes/CIRCUITPY` does not appear.
- `diskutil list` hangs indefinitely without printing output.
- Every flash-mode deploy fails with `CIRCUITPY drive not found or not writable`, even when the board is clearly running CircuitPython and enumerates on USB.
- `ls /Volumes` shows other drives normally but not CIRCUITPY.
- `chumicro-deploy` (via `RecoveringDeployer`) promotes the failure kind to `MACOS_FSKIT_WEDGED` and prints the recovery command.

**What's happening**

Recent macOS releases replaced the in-kernel `msdosfs` driver with a user-space FSKit extension, `com.apple.fskit.msdos.appex`.  When that extension errors out mid-probe on a small FAT12 volume (CIRCUITPY is tiny, and this seems to trigger the bug reliably), `diskarbitrationd` gets stuck in an uninterruptible kernel wait (`ps` state `Us`).  Every subsequent DiskArbitration call queues behind the stuck one, including the "new volume appeared" callback that would normally mount your board's CIRCUITPY drive.  Unplug/replug does nothing because the daemon can never process the insertion event.

**Recovery**

Only run this command when the system is actually wedged: `chumicro_deploy.macos_fskit.detect_fskit_wedge()` returns True, or `ps -o state= -p $(pgrep diskarbitrationd)` shows `Us`.  Running it on a healthy system (including a second time after the first run already cleared the wedge) cuts off in-flight FAT operations on the just-remounted volumes, leaving them in an I/O-error state where `ls /Volumes/CIRCUITPY` fails with `Input/output error` while the drive is still mounted.  Recovering from that state needs a physical unplug + replug of the board.  Soft-reboot via raw REPL is not enough because the USB-MSC interface stays attached across it.

Run this in another terminal.  It needs `sudo`:

```bash
sudo killall -9 com.apple.fskit.msdos fskit_helper fskitd fskit_agent diskarbitrationd DiskArbitrationAgent
```

This string is also exposed as `chumicro_deploy.macos_fskit.MACOS_FSKIT_RECOVERY_COMMAND`.  The constant is the source of truth and a test asserts this doc page contains it verbatim, so they cannot drift.

Why each piece:

- **`killall -9` for the FSKit system daemons**: `com.apple.fskit.msdos`, `fskit_helper`, `fskitd`, `fskit_agent`, and `diskarbitrationd` all respawn via launchd's `KeepAlive=true` plists.  Kill them and they come back a moment later in a clean state.  `-9` is required because they're stuck in kernel wait and can't handle a normal signal.
- **`killall -9` for the per-user `DiskArbitrationAgent`**: this is the agent that registers volumes with Finder's Locations sidebar.  `launchctl kickstart` is SIP-blocked here; `killall -9` works because even though its launchd plist has `KeepAlive=false`, the per-user launchd respawns it on demand the next time a client opens an XPC connection (which happens immediately when the system-side `diskarbitrationd` comes back up).

After the command:

1. Wait 1 to 2 seconds for the daemons to respawn.
2. Unplug and replug the board if its CIRCUITPY hasn't reappeared yet.
3. `/Volumes/CIRCUITPY` should now be mounted, readable, and writable.
4. Retry the deploy.  If you were in the `RecoveringDeployer` retry loop, press Enter at the prompt.

**`chumicro-deploy` does not auto-run this command.**  Auto-escalating to `sudo` is a blast-radius decision the tool should not take without an explicit opt-in.  Detection is automatic (via `detect_fskit_wedge()`), but the paste-this-command step is kept human-in-the-loop on purpose.

If you'd rather not copy-paste, `chumicro-workspace doctor --fix-fskit-wedge` is the opt-in shortcut: detects the wedge, runs the killall via `subprocess.run` so sudo prompts you for the password inline, then re-checks and reports.  Refuses to run when no wedge is detected (running the recovery on a healthy system damages mounted volumes, see above), when stdin/stderr aren't a TTY, or when sudo isn't on PATH.  Distinct exit codes for each refuse case so scripted callers can branch.

### Finder sidebar regression (unrelated caveat)

After the recovery command, your drives are fully functional: mounted at `/Volumes/`, readable, writable, and `chumicro-deploy` works against them.  But on recent macOS they may **not** appear in Finder's Locations sidebar.  That is a separate Apple FSKit-Finder bug, not something the recovery command should fix:

- Finder's Computer view (`Shift`+`⌘`+`C`) sees the volumes normally.
- AppleScript, `ls`, `rsync`, and the deploy tool all see them.
- The sidebar's classifier just filters them out.

Workarounds: reach drives via the Computer view with `Shift`+`⌘`+`C`, or drag one into the Favorites section of the sidebar manually.  No terminal command fixes it from userspace.  **A reboot clears it**, and also clears the FSKit wedge itself if somehow the recovery command above didn't.

### If the wedge persists

In the observed cases so far the command chain always worked.  If it doesn't:

- Reboot.  That always clears the wedge (and the sidebar regression together).
- File a report against `chumicro-deploy` with the macOS version (`sw_vers -productVersion`), the board model, and the output of `ps -o state= -p $(pgrep diskarbitrationd)`.  We'd like to know about reproductions.

## CIRCUITPY drive mounts but is read-only

**Symptoms**

- `/Volumes/CIRCUITPY` exists and `ls` lists the device's files normally.
- Any deploy fails with `rsync(...): error: ...: mkpathat: Read-only file system` (or similar rsync write-side errors), even before the host has done anything destructive.
- Reading `boot_out.txt`, `lib/`, etc. works fine.  Only writes fail.

**What's happening**

Distinct symptom from the FSKit wedge above: there the drive never appears at all; here the drive is fully visible to the host and just refuses writes.  Two plausible causes:

- The device-side filesystem entered a read-only state (CircuitPython's own filesystem can flip read-only when on-device file manipulation confuses its state).
- FSKit handed the mount up with a read-only flag (the host-side daemons are healthy enough to mount but bounced writes off the FAT layer).

Either way the recovery is the same and lives on the device side: reset the board's user filesystem.

**Recovery**

- `chumicro-workspace reset-board --yes --device <id>`: wipes the device filesystem clean-slate; CircuitPython rebuilds an empty writable FS on next boot.  This destroys user files on the board; back up first if anything on the board is the only copy.
- Or unplug, hold the BOOT/RESET button if the board has one, replug.  The runtime re-initializes and the user FS comes back writable.
- The FSKit recovery `killall` from the section above is a separate flow: that one is for the drive-never-appears wedge, not for a writable-side refusal.

## CIRCUITPY mount exists but writes fail with EACCES

**Symptom**

The deploy fails with `CIRCUITPY drive not found or not writable: /Volumes/CIRCUITPY (PermissionError: [Errno 13] Permission denied ...)`.  The path *exists* (it's a directory, `ls` on it returns something), but writes fail with EACCES.

**What's happening**

If you ejected CIRCUITPY from Finder (or the FSKit wedge partially cleared leaving a placeholder), the mount point stays around as an inaccessible stub.  `is_dir()` returns True; `open(..., "wb")` fails with EACCES.  `chumicro-deploy` catches this up-front by writing a `.chu-probe` marker to the drive before any real copy starts, so you fail fast instead of halfway through an rsync.

**Recovery**

- Unplug and replug the board.  A full disconnect clears the stale mount; the fresh insertion goes through the FSKit + DiskArbitration path cleanly.
- If unplug/replug doesn't work, you probably hit the FSKit wedge.  Run the recovery command above.
- Do **not** `rm -rf /Volumes/CIRCUITPY` or `diskutil unmount`.  Those can leave FSKit in a worse state than they started.

## Deploys fail with `Invalid argument` on specific files

**Symptoms**

- rsync fails with `fstatat: Invalid argument` (or `link_stat ... failed: Invalid argument (22)`) naming specific files, e.g. `lib/chumicro_config/section.py`.
- `ls` lists the file, but `stat` and `rm` on it fail with `Invalid argument`.  `rm -rf` of the parent directory fails with `Directory not empty`.
- In a test sweep, every file in the session fails with the same repeated rsync stderr until the sweep is aborted.
- `chumicro-deploy` raises `FAT directory entries on /Volumes/CIRCUITPY are torn`, naming the corrupted paths, and `RecoveringDeployer` classifies the failure as `fat_volume_corrupt`.

**What's happening**

The volume's FAT holds torn directory entries.  `readdir` still lists them, but the OS rejects any `stat` or `unlink` on them with EINVAL, so nothing on the host can read or delete them.  An entry gets torn when a board reset (soft reboot via Ctrl-D, `storage.erase_filesystem()`, or a bootloader reset) lands while macOS still holds dirty FAT metadata in its write cache.  The user-space FSKit `msdos` extension (the same driver behind the wedge above) writes that metadata asynchronously, and a reset that remounts the board's view of the volume mid-write leaves the entry half-committed.

`chumicro-deploy` defends on two sides.  Before every reset it triggers, it flushes the volume with `F_FULLFSYNC`, which waits for the writes to reach the medium (plain `sync` only schedules them).  After every staged push, it stat-scans the volume, so fresh corruption fails the session once, loudly, with the torn paths named, instead of every subsequent test failing with rsync noise.

**Recovery**

- `chumicro-workspace reset-board --yes --device <id>`: reformats the board's filesystem.  Torn entries cannot be repaired in place; `rm`, `rsync --delete`, and Finder all fail on them the same way.  Destructive: every user file on the board is wiped.
- After the board re-enumerates, re-run the deploy.

## Drives mount but `chumicro-deploy` picks the wrong one

**Symptom**

Two CircuitPython boards are connected, and the first deploy after a replug lands on the wrong one: the mount macOS labels `/Volumes/CIRCUITPY` versus `/Volumes/CIRCUITPY 1` swapped relative to the previous boot.

**What's happening**

macOS assigns `/Volumes/CIRCUITPY` in mount order: the first CircuitPython drive to enumerate gets the base name; the next one gets `CIRCUITPY 1`, and so on.  The drive label alone is not a stable identity for a specific board across replugs.

**Recovery**

`chumicro-deploy` resolves the right drive at deploy time: `CircuitpythonTransport._verify_drive_for_board` probes the connected board's UID (`microcontroller.cpu.uid`) and compares it against the `UID:...` line in each mounted `CIRCUITPY*`'s `boot_out.txt`.  On mismatch it silently auto-corrects to the volume whose UID matches the board reachable over the serial port.  When no match is found the transport raises with a clear `"no other mounted CIRCUITPY* volume matches"` message that names both paths and points back at this fix.  There is no `circuitpy_drive_path` field to maintain.  UID-based matching is the only mechanism.

## See also

- [`chumicro-deploy` guide](../../workbench/deploy/docs/guide.md): full user guide for the deploy tool, including `RecoveringDeployer`.
- [Decision 0033](../../plans/decisions/0033-macos-circuitpy-deploy-hardening.md): *why* the deploy code handles each of these cases the way it does (FAT32 hygiene, `os.sync` + settle, board-side stat poll, FSKit detection).
- [Device testing guide](../contributing/device-testing.md): running `functional_tests/` against real boards via `devices.yml`.
