# CIRCUITPY on macOS

A CircuitPython board shows up on your Mac as a USB drive named `CIRCUITPY`, and a deploy copies your files onto that drive. This page covers the ways the drive goes wrong on macOS. Linux has none of these problems; boards on Linux that can't reach their serial port belong on [Board not found](board-not-found.md).

## `CIRCUITPY` never appears, and deploys fail with `CIRCUITPY drive not found or not writable`

First tap the board's RESET button, and if the drive still doesn't appear, unplug the board and plug it back in. If that brings the drive back, you're done.

If it doesn't, ask the doctor:

```bash
python3 run.py doctor
```

A `MACOS FSKIT` line reading `diskarbitrationd is wedged in uninterruptible wait` means macOS itself has stopped mounting drives. Other signs of the same problem: `diskutil list` hangs without printing, replugging the board changes nothing, and the deploy reports `MACOS_FSKIT_WEDGED`. Your other drives keep working.

Clear it with:

```bash
python3 run.py doctor --fix-fskit-wedge
```

`--fix-fskit-wedge` checks for the problem again, runs the recovery command with `sudo` (type your Mac password when asked), waits two seconds, and checks once more. It refuses to run when nothing is stuck, because the same command on a healthy Mac breaks the drives that are mounted.

To run the recovery command yourself instead, paste it into a Terminal window:

```bash
sudo killall -9 com.apple.fskit.msdos fskit_helper fskitd fskit_agent diskarbitrationd DiskArbitrationAgent
```

Run it once per occurrence. A second run, after the first has already fixed things, interrupts the drives that just came back and leaves them answering `Input/output error`; unplugging and replugging the board clears that.

Afterwards:

1. Wait a second or two.
2. Unplug and replug the board if `CIRCUITPY` hasn't appeared.
3. Deploy again. If a deploy was waiting at its retry prompt, press Enter.

If the drive still won't appear, restart the Mac, which always clears it.

### The drive works but is missing from Finder's sidebar

After the recovery, `CIRCUITPY` mounts, reads, writes, and takes deploys, but Finder may leave it out of the sidebar. That is a separate macOS bug, and the recovery can't fix it. Open the Computer view with Shift-Command-C to see the drive, or drag it into the sidebar's Favorites. Restarting the Mac puts it back.

### Why it happens

Recent macOS versions read FAT drives such as `CIRCUITPY` through a driver that runs as an ordinary program (FSKit) instead of inside the system core. Sometimes that driver fails halfway through reading a small FAT drive, and `diskarbitrationd`, the service that mounts drives, waits on it forever. Every later mount, including your board's next one, queues behind that wait. `killall -9` stops the stuck services (`-9` because a stuck process ignores a polite request to quit), and macOS starts fresh copies right away. `DiskArbitrationAgent` is your user account's helper for Finder, and it restarts the moment the mount service comes back.

The deploy tool detects the problem and prints the command, but never runs `sudo` on its own; `--fix-fskit-wedge` is how you ask it to.

## `CIRCUITPY` mounts, but deploys fail with `Read-only file system`

You can open the drive and read its files, but every deploy fails with an error such as `mkpathat: Read-only file system`.

Check the board for a `boot.py` that calls `storage.remount("/", readonly=False)`. That line hands write access to the program on the board, and CircuitPython then shows `CIRCUITPY` to your Mac as read-only. Deploys never delete `boot.py`, so it keeps doing this until you remove it. [Persisting data](persisting-data.md#runtimeerror-cannot-remount-path-when-visible-via-usb) shows how to get write access back.

With no such `boot.py`, the board's filesystem is damaged and CircuitPython has locked it. Erase it:

```bash
python3 run.py reset-board --device <id> --yes
```

`reset-board` deletes every file on the board, so copy off anything that exists only there first. CircuitPython builds a fresh, writable filesystem when the board restarts.

## Deploys fail with `PermissionError: [Errno 13] Permission denied` on `/Volumes/CIRCUITPY`

The folder `/Volumes/CIRCUITPY` exists, but nothing can be written to it. Ejecting `CIRCUITPY` in Finder leaves this empty placeholder behind, and so can the stuck-mount problem above. The deploy tries a test write before copying anything, so it stops before changing the board.

Unplug the board and plug it back in. If the drive doesn't come back properly, follow the section on `CIRCUITPY` never appearing. Leave the placeholder alone: `rm -rf /Volumes/CIRCUITPY` and `diskutil unmount` can leave the mount service worse off than before.

## Deploys fail with `Invalid argument` on particular files

The deploy stops with `FAT directory entries on /Volumes/CIRCUITPY are torn`, or rsync reports `fstatat: Invalid argument` naming a file such as `lib/chumicro_config/section.py`. `ls` lists the file, but nothing can open or delete it.

The board restarted while your Mac was still writing to the drive, and the half-written directory entry can't be read or removed. Copying files onto `CIRCUITPY` by hand causes this most often: CircuitPython restarts your program every time a file on the drive changes, so the board and the Mac rewrite the same filesystem at once.

Erase the board's filesystem, which is the only repair, then deploy again:

```bash
python3 run.py reset-board --device <id> --yes
python3 run.py deploy <project>
```

From then on, send files with `python3 run.py deploy`. It stops the program on the board before copying, and makes macOS finish writing before the board restarts.

## Two CircuitPython boards, and the deploy picks the wrong drive

With two boards plugged in, macOS names the first drive to arrive `CIRCUITPY` and the second `CIRCUITPY 1`, and the order can change every time you replug. That is normal.

The deploy sorts this out by itself. It asks the board, over its serial port, for the chip's unique ID, and compares that with the `UID:` line in each drive's `boot_out.txt`, then copies to the drive that matches. When no drive matches, it stops with `no other mounted CIRCUITPY* volume matches either`, and names the drives it checked.

If you see that message, press RESET on each board (CircuitPython rewrites `boot_out.txt` when it restarts from RESET), wait for both drives to appear, and deploy again. Deploy to one board at a time: two deploys running together race for the drives.
