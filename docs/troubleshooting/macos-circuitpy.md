# CIRCUITPY on macOS

A CircuitPython board shows up on a Mac as a USB drive named `CIRCUITPY`, and a deploy copies your files onto that drive. A board that fails to connect over its serial port belongs on [Board not found](board-not-found.md).

## `CIRCUITPY` never appears, and deploys fail with `CIRCUITPY drive not found or not writable`

Tap the board's RESET button. When the drive stays missing, unplug the board and plug it back in.

When the drive still stays missing, run `doctor`:

```bash
python3 run.py doctor
```

A `MACOS FSKIT` line reading `diskarbitrationd is wedged in uninterruptible wait` means macOS itself has stopped mounting drives. The same fault makes `diskutil list` hang without printing, leaves replugging without effect, and makes the deploy report `MACOS_FSKIT_WEDGED`. Drives already mounted keep working.

Clear it with:

```bash
python3 run.py doctor --fix-fskit-wedge
```

`--fix-fskit-wedge` checks for the fault again, runs the recovery command with `sudo`, which asks for your Mac password, waits two seconds, and checks once more. It refuses to run when nothing is stuck, because the same command on a healthy Mac breaks the drives that are mounted.

To run the recovery command yourself instead, paste it into a Terminal window:

```bash
sudo killall -9 com.apple.fskit.msdos fskit_helper fskitd fskit_agent diskarbitrationd DiskArbitrationAgent
```

Run it once per occurrence. A second run, after the first has already fixed things, interrupts the drives that just came back and leaves them answering `Input/output error`. Unplugging and replugging the board clears that.

Afterwards:

1. Wait a second or two.
2. Unplug and replug the board if `CIRCUITPY` hasn't appeared.
3. Deploy again. If a deploy was waiting at its retry prompt, press Enter.

When the drive still stays missing, restart the Mac, which always clears the fault.

### Why it happens

A Mac with this fault reads FAT drives such as `CIRCUITPY` through FSKit, a driver that runs as an ordinary program instead of inside the system core. Sometimes that driver fails halfway through reading a small FAT drive, and `diskarbitrationd`, the service that mounts drives, waits on it forever. Every later mount, including your board's next one, queues behind that wait. `killall -9` stops the stuck services, with `-9` because a stuck process ignores a polite request to quit, and macOS starts fresh copies right away. `DiskArbitrationAgent` is your user account's helper for Finder, and it restarts the moment the mount service comes back.

The deploy tool detects the fault and prints the command. It runs `sudo` only when `--fix-fskit-wedge` asks it to.

### The drive works but is missing from Finder's sidebar

After the recovery, `CIRCUITPY` mounts, reads, writes, and takes deploys, and Finder may still leave it out of the sidebar. Open the Computer view with Shift-Command-C to see the drive, or drag it into the sidebar's Favorites. Restarting the Mac puts it back. A separate macOS bug causes this, and the recovery leaves it in place.

## `CIRCUITPY` mounts, but deploys fail with `Read-only file system`

The drive opens and its files read, and every deploy fails with an error such as `mkpathat: Read-only file system`.

Check the board for a `boot.py` that calls `storage.remount("/", readonly=False)`. That line hands write access to the program on the board, and CircuitPython then shows `CIRCUITPY` to the Mac as read-only. Deploys keep `boot.py`, so the drive stays read-only until you remove that file. [Persisting data](persisting-data.md#runtimeerror-cannot-remount-path-when-visible-via-usb) shows how to get write access back.

With no such `boot.py`, the board's filesystem is damaged and CircuitPython has locked it. Erase it:

```bash
python3 run.py reset-board --device <id> --yes
```

`reset-board` deletes every file on the board, so copy off anything that exists only there first. CircuitPython builds a fresh, writable filesystem when the board restarts.

## Deploys fail with `PermissionError: [Errno 13] Permission denied` on `/Volumes/CIRCUITPY`

Unplug the board and plug it back in. When the drive fails to come back properly, follow [`CIRCUITPY` never appears](#circuitpy-never-appears-and-deploys-fail-with-circuitpy-drive-not-found-or-not-writable). Leave the placeholder folder alone: `rm -rf /Volumes/CIRCUITPY` and `diskutil unmount` can leave the mount service worse off than before.

The folder `/Volumes/CIRCUITPY` exists, and nothing can write to it. Ejecting `CIRCUITPY` in Finder leaves this empty placeholder behind, and so can the stuck mount described above. The deploy tries a test write before copying anything, so it stops before changing the board.

## Deploys fail with `Invalid argument` on particular files

The deploy stops with `FAT directory entries on /Volumes/CIRCUITPY are torn`, or rsync reports `fstatat: Invalid argument` naming a file such as `lib/chumicro_config/section.py`. `ls` lists the file, and nothing can open or delete it.

Erase the board's filesystem, the only repair, then deploy again:

```bash
python3 run.py reset-board --device <id> --yes
python3 run.py deploy <project>
```

The board restarted while the Mac was still writing to the drive, and left a half-written directory entry that can be neither read nor removed. Copying files onto `CIRCUITPY` by hand causes this most often: CircuitPython restarts your program every time a file on the drive changes, so the board and the Mac rewrite the same filesystem at once.

From then on, send files with `python3 run.py deploy`. It stops the program on the board before copying, and makes macOS finish writing before the board restarts.

## Two CircuitPython boards, and the deploy picks the wrong drive

When the deploy stops with `no other mounted CIRCUITPY* volume matches either`, it names the drives it checked. Press RESET on each board, wait for both drives to appear, and deploy again. Deploy to one board at a time, because two deploys running together race for the drives.

With two boards plugged in, macOS names the first drive to arrive `CIRCUITPY` and the second `CIRCUITPY 1`. The order can change on every replug. The deploy asks the board, over its serial port, for the chip's unique ID, compares it with the `UID:` line in each drive's `boot_out.txt`, and copies to the drive that matches. CircuitPython rewrites `boot_out.txt` when it restarts from RESET, which refreshes that line.
