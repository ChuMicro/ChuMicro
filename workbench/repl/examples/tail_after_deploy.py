"""Tail a board after a fresh deploy and exit on the first traceback.

Walks through the typical "deploy then watch" flow:

1. Construct a :class:`chumicro_deploy.Device` for the target board.
2. Run :func:`chumicro_repl.tail` against it for ten seconds.
3. Exit non-zero when a traceback is detected on the wire.

Run with the board's serial path::

    python tail_after_deploy.py /dev/cu.usbmodem14101 circuitpython

This example is import-checked but not auto-executed by tests (it
requires a connected board), so it is a runnable illustration
rather than a host-side test.
"""

from __future__ import annotations

import sys

from chumicro_deploy import Device
from chumicro_repl import ExitCode, tail


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(
            f"usage: {argv[0]} <serial-port> <circuitpython|micropython>",
            file=sys.stderr,
        )
        return 2
    address, transport = argv[1], argv[2]
    device = Device(transport=transport, address=address)
    result = tail(device, seconds=10.0, fail_on_traceback=True)
    if result is ExitCode.TRACEBACK_DETECTED:
        print("traceback detected on board — exiting non-zero", file=sys.stderr)
        return 1
    if result is ExitCode.INTERRUPTED:
        print("tail interrupted", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
