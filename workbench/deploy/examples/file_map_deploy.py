"""Programmatic deploy from an in-memory file map.

Demonstrates :class:`~chumicro_deploy.FileMapSource` — the source you
reach for when the files you want to ship don't already live in a
directory on disk.  Common cases: code generated from a template,
config materialized at deploy time from environment variables, a
small one-off blink shipped without writing a directory tree first.

Run from the repo root with a board plugged in::

    .venv/bin/python workbench/deploy/examples/file_map_deploy.py

The script builds a tiny multi-file payload (entrypoint + a helper
module) entirely in Python, deploys it, prints the execute output,
exits zero on success.

For the simpler "just point at a directory" case see
``programmatic_deploy.py``.  For walking the import graph from a
single entrypoint see ``import_graph_deploy.py``.
"""

from __future__ import annotations

import sys

from chumicro_deploy import (
    Deployer,
    Device,
    DeviceConfigError,
    DeviceEntry,
    FileMapSource,
    Runtime,
    load_device_registry,
)

# Two-file payload: an entrypoint that imports a helper module.  The
# leading slash on each key is the on-device absolute path; the
# entrypoint key must exactly match `entrypoint=` below.  Values are
# the file contents (`str` or `bytes`).
_ENTRYPOINT = "/main.py"
_PAYLOAD: dict[str, str | bytes] = {
    _ENTRYPOINT: (
        "import sys\n"
        "from greet import shout\n"
        "shout(f'hello from {sys.implementation.name}')\n"
    ),
    "/greet.py": (
        "def shout(message):\n"
        "    print(message.upper())\n"
    ),
}


def _pick_micropython_board(entries: list[DeviceEntry]) -> DeviceEntry | None:
    for entry in entries:
        if entry.runtime == Runtime.MICROPYTHON.value:
            return entry
    return None


def _device_from_entry(entry: DeviceEntry) -> Device:
    return Device(
        transport=entry.runtime,
        address=entry.address,
        baudrate=entry.serial_baudrate,
        deploy_mode="ram",
    )


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

    print(f"deploying {len(_PAYLOAD)} files to {board.address}")

    source = FileMapSource(_PAYLOAD, entrypoint=_ENTRYPOINT)
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
