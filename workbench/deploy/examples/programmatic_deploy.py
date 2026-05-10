"""Minimal programmatic deploy with a `DirectorySource`.

The smallest end-to-end example: pick a board from `devices.yml`, point
:class:`~chumicro_deploy.DirectorySource` at a local directory of files
on disk, and ship them to the board with
:class:`~chumicro_deploy.Deployer`.

Run from the repo root with a board plugged in::

    .venv/bin/python workbench/deploy/examples/programmatic_deploy.py

The script materialises a tiny "hello, world" program in a temporary
directory, deploys it, prints the captured execute output, then exits
zero on success.

What this is *not*: a wifi / mqtt / sensor demo, a multi-thing
workspace, or a CircuitPython flash-mode walk-through.  See
``demo_recovery_hand_holding.py`` for the failure-coaching surface.
For workspace-shaped projects use ``chumicro-workspace`` directly.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from chumicro_deploy import (
    Deployer,
    Device,
    DeviceConfigError,
    DeviceEntry,
    DirectorySource,
    Runtime,
    load_device_registry,
)


def _pick_micropython_board(entries: list[DeviceEntry]) -> DeviceEntry | None:
    """Return the first MicroPython board in *entries*, or ``None``.

    MicroPython is the simplest target for this example because RAM mode
    drives over `mpremote` and never touches the host filesystem (no
    USB-drive sentinels, no FAT cleanup, no flash wear).  Adapt to
    CircuitPython by picking a CP entry and switching to flash mode;
    the transport resolves the CIRCUITPY mount at deploy time by
    scanning mounted ``CIRCUITPY*`` volumes and UID-matching the
    connected board against each ``boot_out.txt``.
    """
    for entry in entries:
        if entry.runtime == Runtime.MICROPYTHON.value:
            return entry
    return None


def _device_from_entry(entry: DeviceEntry) -> Device:
    """Build a RAM-mode :class:`Device` from a `devices.yml` entry."""
    return Device(
        transport=entry.runtime,
        address=entry.address,
        baudrate=entry.serial_baudrate,
        deploy_mode="ram",
    )


def _materialise_hello_world(parent: Path) -> Path:
    """Write a tiny app to *parent* and return the directory."""
    source_dir = parent / "hello_app"
    source_dir.mkdir()
    (source_dir / "main.py").write_text(
        "import sys\n"
        "print('hello from chumicro-deploy on', sys.implementation.name)\n",
    )
    return source_dir


def main() -> int:
    try:
        entries, _defaults = load_device_registry()
    except (DeviceConfigError, FileNotFoundError, OSError) as error:
        print(f"error: failed to load devices.yml: {error}", file=sys.stderr)
        return 1

    board = _pick_micropython_board(entries)
    if board is None:
        print(
            "error: no MicroPython board in devices.yml.  Add one with "
            "`chumicro-workspace add-device` or hand-edit the file.",
            file=sys.stderr,
        )
        return 1

    print(f"deploying to {board.description or board.identifier} ({board.address})")

    with tempfile.TemporaryDirectory(prefix="chumicro-example-") as tmp:
        source_dir = _materialise_hello_world(Path(tmp))
        source = DirectorySource(
            source_dir, entrypoint="/main.py", resource_prefix="/",
        )
        # Programmatic deploys typically want non-interactive behaviour
        # — surface failures as exceptions for the surrounding script
        # to handle, rather than coaching a human through retries.
        result = Deployer(_device_from_entry(board)).deploy(source)

    if result.execute_output:
        print("--- board output ---")
        print(result.execute_output, end="")
    if not result.success:
        print(f"--- traceback ---\n{result.traceback}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
