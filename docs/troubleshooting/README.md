# Troubleshooting

Start from what you're seeing.  Each page below opens with the symptom
(the error text, the hang, the missing drive) and walks to the fix.

Not everything lands here.  A lot of ChuMicro troubleshooting is inline
where it's needed: the `chumicro-deploy` CLI coaches you through
`PORT_UNAVAILABLE`, `RAW_REPL_UNRESPONSIVE`, `CIRCUITPY_DRIVE_MISSING`,
and most other failure kinds with two or three fix steps at the point of
failure, and lint, test, and coverage errors do the same in their own
messages.  These pages cover what an inline message can't: multi-step
recoveries, and symptoms whose proximate error doesn't name the root
cause.

The commands on these pages are the `chumicro-workspace` CLI, which is on
your PATH once the workspace's Python environment is active.  Inside a
cloned workspace template, `python3 run.py <cmd>` reaches the same
commands through a bootstrap wrapper, so `python3 run.py deploy` and
`chumicro-workspace deploy` do the same thing.

The deploy and board tooling runs on macOS and Linux.  Windows hosts
aren't supported for it, and WSL2 on its own isn't a way around that:
WSL2 has no USB passthrough, so the board's serial port never appears
inside it without `usbipd-win` (the USB/IP bridge you install on the
Windows side) attaching the device first.  Editing, linting, and unit
tests do run natively on Windows; [CONTRIBUTING](../../CONTRIBUTING.md#prerequisites)
covers what each platform gets.

## Getting a board working

- [**Board not found**](board-not-found.md): nothing shows up in
  `discover`, the serial port is busy or permission-denied (the Linux
  `dialout` trap), the REPL won't respond, or the board keeps moving
  between ports.
- [**Getting firmware onto a new board**](firmware-onto-a-new-board.md):
  the board isn't running CircuitPython or MicroPython yet, shipped
  with ancient firmware, or won't enter its bootloader.
- [**Known board quirks**](board-quirks.md): per-board table of the
  hardware oddities the bench has hit, and what to do about each.

## Deploying

- [**Deploys and file persistence**](deploys-and-file-persistence.md):
  a deploy wiped files you installed by hand, your boot counter never
  increments, or RAM mode runs out of memory.
- [**Deploy refused or ImportError on boot**](deploy-refused-importerror.md):
  the import walker can't resolve a module, `shared/` imports fail, a
  project name is rejected, or `from_config` raises about a missing
  sockets factory.
- [**macOS CIRCUITPY deploy troubleshooting**](macos-circuitpy.md): the
  FSKit / DiskArbitration wedge, stale-mount `EACCES` after a Finder
  eject, and multi-board drive disambiguation.

## Network

- [**WiFi won't connect**](wifi-wont-connect.md): credentials that never
  left `secrets.toml`, silent drops with no error, CircuitPython's
  blocking connect, weak-antenna boards, and the board-resident
  `settings.toml` fighting your config.
- [**TLS and HTTPS failures**](tls-https-failures.md): certificate
  validity errors on a board whose clock is unset, handshake
  out-of-memory, custom CA wiring, and the platform limits.

## Memory and data

- [**Running out of memory**](out-of-memory.md): `MemoryError` and
  `OSError` 12 at import or connect time, and how deploy mode and
  import order change the numbers.
- [**Persisting data**](persisting-data.md): the KV store's capacity
  and corruption behavior, and why writes need `commit()`.

## Contributor-side

- [**CircuitPython unix-port RingIO build failure**](circuitpython-ringio.md):
  why a `VARIANT=standard` build fails, and why CircuitPython's own CI
  never catches it.

## Related

- [`docs/contributing/cheat-sheet.md`](../contributing/cheat-sheet.md):
  one-line fixes for common lint / test / coverage / device-setup
  failures.
- [Device testing guide](../contributing/device-testing.md): configuring
  `devices.yml` and running `functional_tests/`.
