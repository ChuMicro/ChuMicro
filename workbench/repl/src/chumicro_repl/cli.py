"""``chumicro-repl`` command-line interface.

Thin wrapper over :func:`chumicro_repl.tui.interactive` and
:func:`chumicro_repl.tail.tail`.  No logic beyond argument
translation — the CLI exists so the common cases ("connect to my
board", "tail my deploy") don't require a Python script.

Invoked via ``python -m chumicro_repl ...`` or, after installation,
the ``chumicro-repl`` console script.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from chumicro_deploy import Device


def _device_from_args(args: argparse.Namespace) -> Device | str:
    """Build a ``Device`` (or fall back to the bare port path).

    Mirrors :mod:`chumicro_deploy.cli` — callers can either point
    at a ``devices.yml`` entry or pass ``--transport`` + ``--address``
    explicitly.  The bare-string path is supported for the trivial
    case where the user has neither chumicro-deploy installed nor a
    devices.yml: ``chumicro-repl --address /dev/cu.usbmodem...``.

    devices.yml resolution precedence (when ``--devices-file`` is
    supplied):

    1. ``--device <id>`` wins outright.
    2. ``--runtime <circuitpython|micropython>`` picks
       ``defaults.<runtime>`` from the file.  Only honored by the
       built-in ``default`` loader; third-party loaders that don't
       accept a ``runtime`` kwarg are called without it.
    3. Neither flag — the loader's single-runtime fallback applies
       (one runtime default in the file picks itself; both set
       raises so the caller picks).
    """
    if args.devices_file is not None:
        from chumicro_deploy.config import discover_config_loaders  # noqa: PLC0415

        loaders = discover_config_loaders()
        loader_name = args.devices_format
        if loader_name not in loaders:
            raise SystemExit(
                f"error: unknown --devices-format: {loader_name!r}.  "
                f"Registered: {sorted(loaders.keys())!r}"
            )
        if args.device_id is not None and args.runtime is not None:
            raise SystemExit(
                "error: --device and --runtime are mutually exclusive"
            )
        loader = loaders[loader_name]
        loader_kwargs: dict[str, object] = {"device_id": args.device_id}
        if args.runtime is not None:
            # Only the built-in 'default' loader accepts ``runtime``.
            # Third-party loaders that don't accept the kwarg would
            # raise TypeError on the call — so we gate the kwarg on
            # the registered name.
            if loader_name != "default":
                raise SystemExit(
                    f"error: --runtime only works with --devices-format "
                    f"default; got {loader_name!r}"
                )
            loader_kwargs["runtime"] = args.runtime
        return loader(args.devices_file, **loader_kwargs)

    if args.address is None:
        raise SystemExit(
            "error: --address is required unless --devices-file is supplied"
        )

    if args.transport is None:
        # Bare-path mode — no Device construction, hand the address
        # straight to the TUI / tail surface.  Skips the
        # chumicro-deploy import entirely so a user who only wants
        # the REPL doesn't need the full deploy stack installed.
        return args.address

    from chumicro_deploy import Device  # noqa: PLC0415

    return Device(
        transport=args.transport,
        address=args.address,
        baudrate=args.baudrate,
    )


def _add_device_args(parser: argparse.ArgumentParser) -> None:
    """Attach the shared device-selection flags."""
    parser.add_argument(
        "--transport",
        choices=("circuitpython", "micropython"),
        help=(
            "Runtime target identifier.  Optional — when omitted "
            "(and --devices-file is not supplied), --address is "
            "used as a bare serial path with no chumicro-deploy "
            "Device construction."
        ),
    )
    parser.add_argument(
        "--address",
        help="Serial port path.",
    )
    parser.add_argument(
        "--baudrate",
        type=int,
        default=115200,
        help="Serial baudrate (CircuitPython only; default 115200).",
    )
    parser.add_argument(
        "--devices-file",
        type=Path,
        default=None,
        help=(
            "Path to a devices.yml.  When set, --transport / "
            "--address / --baudrate are filled from the entry "
            "selected by --device, --runtime, or the single "
            "runtime default."
        ),
    )
    parser.add_argument(
        "--device",
        dest="device_id",
        default=None,
        help="Device id within --devices-file.",
    )
    parser.add_argument(
        "--runtime",
        choices=("circuitpython", "micropython"),
        default=None,
        help=(
            "When --devices-file is set and --device is not, pick "
            "defaults.<runtime> from the file.  Lets a workspace "
            "with both runtime defaults configured open the REPL "
            "without naming the device id."
        ),
    )
    parser.add_argument(
        "--devices-format",
        default="default",
        help=(
            "Config-file format name.  Built-in: 'default' "
            "(chumicro-deploy's devices.yml schema)."
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level ``chumicro-repl`` argument parser."""
    parser = argparse.ArgumentParser(
        prog="chumicro-repl",
        description=(
            "Interactive serial REPL for CircuitPython and MicroPython "
            "boards, with traceback highlighting and a follow-mode "
            "tail() for deploy orchestration."
        ),
    )
    _add_device_args(parser)
    parser.add_argument(
        "--tail",
        type=float,
        default=None,
        metavar="SECONDS",
        help=(
            "Run in tail mode: stream output for SECONDS, "
            "highlight tracebacks, exit non-zero on a detected "
            "traceback (unless --no-fail-on-traceback)."
        ),
    )
    parser.add_argument(
        "--no-fail-on-traceback",
        dest="fail_on_traceback",
        action="store_false",
        default=True,
        help=(
            "Tail mode only: stream the full window even when a "
            "traceback or safe-mode banner is detected."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=("line", "passthrough"),
        default="passthrough",
        help=(
            "Interactive input mode.  `passthrough` (default — today's "
            "TUI) forwards every keystroke to the device; `line` "
            "interposes a host-side line editor with persistent "
            "per-device history, cursor edit, and Ctrl-R reverse "
            "search.  The default flips to `line` once raw-REPL "
            "auto-detection lands."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point — parse *argv* and route to interactive / tail."""
    parser = build_parser()
    args = parser.parse_args(argv)
    device = _device_from_args(args)
    if args.tail is not None:
        # Lazy-import so a plain ``--help`` doesn't pay tail's pyserial
        # dependency.  ExitCode is an IntEnum; returning it directly
        # gives the shell the right exit status.
        from ._follow import tail  # noqa: PLC0415

        return int(tail(
            device,
            args.tail,
            fail_on_traceback=args.fail_on_traceback,
            output=sys.stdout,
        ))
    if args.mode == "line":
        from .tui import interactive_line  # noqa: PLC0415

        return interactive_line(device)
    from .tui import interactive  # noqa: PLC0415

    return interactive(device)
