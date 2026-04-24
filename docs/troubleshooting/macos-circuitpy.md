# macOS CIRCUITPY deploy troubleshooting

Covers the macOS-specific failure modes `chumicro-deploy` hits when writing to the CIRCUITPY USB drive.  The decision rationale — *why* the deploy code works the way it does — lives in [Decision 0033](../../plans/decisions/0033-macos-circuitpy-deploy-hardening.md); this page is the operational how-to for when something has gone wrong and you need to get unstuck.

Linux deploys don't hit any of this.  Windows isn't currently supported.

## The FSKit wedge — `/Volumes/CIRCUITPY` never appears

**Symptoms**

- You unplug and replug the board; `/Volumes/CIRCUITPY` does not appear.
- `diskutil list` hangs indefinitely without printing output.
- Every flash-mode deploy fails with `CIRCUITPY drive not found or not writable`, even when the board is clearly running CircuitPython and enumerates on USB.
- `ls /Volumes` shows other drives normally but not CIRCUITPY.
- The `InteractiveDeployer` CLI promotes the failure kind to `MACOS_FSKIT_WEDGED` and prints the recovery command.

**What's happening**

Recent macOS releases replaced the in-kernel `msdosfs` driver with a user-space FSKit extension, `com.apple.fskit.msdos.appex`.  When that extension errors out mid-probe on a small FAT12 volume — CIRCUITPY is tiny, and this seems to trigger the bug reliably — `diskarbitrationd` gets stuck in an uninterruptible kernel wait (`ps` state `Us`).  Every subsequent DiskArbitration call queues behind the stuck one, including the "new volume appeared" callback that would normally mount your board's CIRCUITPY drive.  Unplug/replug does nothing because the daemon can never process the insertion event.

**Recovery**

Run this in another terminal.  It needs `sudo`:

```bash
sudo killall -9 com.apple.fskit.msdos fskit_helper fskitd fskit_agent diskarbitrationd && \
launchctl kickstart -k gui/$(id -u)/com.apple.DiskArbitrationAgent
```

Why each piece:

- **`killall -9` for the system daemons** — the `fskit_*` processes and `diskarbitrationd` all respawn via launchd's `KeepAlive=true` plists.  Kill them and they come back a moment later in a clean state.  `-9` is required because they're stuck in kernel wait and can't handle a normal signal.
- **`launchctl kickstart -k` for the per-user `DiskArbitrationAgent`** — this one is different.  Its plist has `KeepAlive=false`, so a plain `killall` leaves it dead.  Without the per-user agent, CIRCUITPY drives *will* mount at `/Volumes/` after the system daemons recover, but macOS's Finder won't see them.  `launchctl kickstart -k` stops and restarts the service via launchd; the agent comes back and Finder picks up the drives.

After the command:

1. Wait 1–2 seconds for the daemons to respawn.
2. Unplug and replug the board if its CIRCUITPY hasn't reappeared yet.
3. `/Volumes/CIRCUITPY` should now be mounted, readable, and writable.
4. Retry the deploy.  If you were in the `InteractiveDeployer` retry loop, press Enter at the prompt.

**`chumicro-deploy` does not auto-run this command.**  Auto-escalating to `sudo` is a blast-radius decision the tool should not take without an explicit opt-in — detection is automatic (via `detect_fskit_wedge()`), but the paste-this-command step is kept human-in-the-loop on purpose.

### Finder sidebar regression (unrelated caveat)

After the recovery command, your drives are fully functional — mounted at `/Volumes/`, readable, writable, and `chumicro-deploy` works against them.  But on recent macOS they may **not** appear in Finder's Locations sidebar.  That is a separate Apple FSKit-Finder bug, not something the recovery command should fix:

- Finder's Computer view (`Shift`+`⌘`+`C`) sees the volumes normally.
- AppleScript, `ls`, `rsync`, and the deploy tool all see them.
- The sidebar's classifier just filters them out.

Workarounds: reach drives via the Computer view with `Shift`+`⌘`+`C`, or drag one into the Favorites section of the sidebar manually.  No terminal command fixes it from userspace.  **A reboot clears it** — and also clears the FSKit wedge itself if somehow the recovery command above didn't.

### If the wedge persists

In the observed cases so far the command chain always worked.  If it doesn't:

- Reboot.  That always clears the wedge (and the sidebar regression together).
- File a report against `chumicro-deploy` with the macOS version (`sw_vers -productVersion`), the board model, and the output of `ps -o state= -p $(pgrep diskarbitrationd)`.  We'd like to know about reproductions.

## Stale `/Volumes/CIRCUITPY` after Finder eject

**Symptom**

The deploy fails with `CIRCUITPY drive not found or not writable: /Volumes/CIRCUITPY (PermissionError: [Errno 13] Permission denied ...)`.  The path *exists* (it's a directory, `ls` on it returns something), but writes fail with EACCES.

**What's happening**

If you ejected CIRCUITPY from Finder — or the FSKit wedge partially cleared leaving a placeholder — the mount point stays around as an inaccessible stub.  `is_dir()` returns True; `open(..., "wb")` fails with EACCES.  `chumicro-deploy` catches this up-front by writing a `.chu-probe` marker to the drive before any real copy starts, so you fail fast instead of halfway through an rsync.

**Recovery**

- Unplug and replug the board.  A full disconnect clears the stale mount; the fresh insertion goes through the FSKit + DiskArbitration path cleanly.
- If unplug/replug doesn't work, you probably hit the FSKit wedge — run the recovery command above.
- Do **not** `rm -rf /Volumes/CIRCUITPY` or `diskutil unmount` — those can leave FSKit in a worse state than they started.

## Drives mount but `chumicro-deploy` picks the wrong one

**Symptom**

Two CircuitPython boards are connected.  `chumicro-deploy` deploys to the wrong one, or `devices.yml` has `circuitpy_drive_path: /Volumes/CIRCUITPY` but macOS has the board mounted at `/Volumes/CIRCUITPY 1` (or vice versa).

**What's happening**

macOS assigns `/Volumes/CIRCUITPY` in mount order — the first CircuitPython drive to enumerate gets the base name; the next one gets `CIRCUITPY 1`, and so on.  Pinning `circuitpy_drive_path` in `devices.yml` can therefore silently refer to the *other* board when two are attached.

**Recovery**

`chumicro-deploy` already detects this: `CircuitpythonTransport._verify_drive_for_board` probes the connected board's UID (`microcontroller.cpu.uid`) and compares it against the `UID:...` line in the drive's `boot_out.txt`.  On mismatch it scans every mounted `CIRCUITPY*` volume for the matching UID and auto-corrects, printing a `WARNING` that names both paths.  When the auto-correction succeeds the deploy continues; when no match is found it raises with a clear `"no other mounted CIRCUITPY* volume matches"` message.

The clean long-term fix: **remove `circuitpy_drive_path` from `devices.yml`** and let auto-detection work.  UID-based matching is more reliable than mount-order-dependent paths.

## See also

- [`chumicro-deploy` guide](../../workbench/deploy/docs/guide.md) — full user guide for the deploy tool, including `InteractiveDeployer`.
- [Decision 0033](../../plans/decisions/0033-macos-circuitpy-deploy-hardening.md) — *why* the deploy code handles each of these cases the way it does (FAT32 hygiene, `os.sync` + settle, board-side stat poll, FSKit detection).
- [Device testing guide](../contributing/device-testing.md) — running `functional_tests/` against real boards via `devices.yml`.
