"""``chumicro-deploy`` command-line interface.

Thin wrapper over the public Python API — every CLI action maps to a
single :mod:`chumicro_deploy` function, no logic beyond argument
translation.  Third parties who prefer the programmatic API don't
need the CLI; the CLI exists for quick one-off flashes, probes, and
URL lookups without writing a Python script.

Invoked via ``python -m chumicro_deploy <command> ...`` or, after
:mod:`chumicro-deploy` is installed, the ``chumicro-deploy`` console
script.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .device import Device
from .firmware import flash_firmware, resolve_firmware_url
from .probe import probe_device
from .sources import DirectorySource, FileMapSource


def _add_device_args(parser: argparse.ArgumentParser) -> None:
    """Attach the shared Device construction flags."""
    parser.add_argument(
        "--transport",
        choices=("circuitpython", "micropython"),
        required=True,
        help="Runtime target identifier.",
    )
    parser.add_argument(
        "--address",
        required=True,
        help="Serial port path (e.g. /dev/cu.usbmodem1101).",
    )
    parser.add_argument(
        "--baudrate",
        type=int,
        default=115200,
        help="Serial baudrate (CircuitPython only; default 115200).",
    )
    parser.add_argument(
        "--deploy-mode",
        choices=("ram", "flash"),
        default="ram",
        help="Deploy mode: ram (no-flash) or flash (persistent).",
    )
    parser.add_argument(
        "--drive",
        dest="circuitpy_drive_path",
        type=Path,
        default=None,
        help="CIRCUITPY drive mount path (CP flash mode).",
    )


def _device_from_args(args: argparse.Namespace) -> Device:
    """Build a :class:`Device` from a parsed subcommand namespace."""
    return Device(
        transport=args.transport,
        address=args.address,
        baudrate=args.baudrate,
        deploy_mode=args.deploy_mode,
        circuitpy_drive_path=args.circuitpy_drive_path,
    )


def _stderr_progress(fraction: float, message: str) -> None:
    """Progress callback — one line per event on stderr."""
    print(f"[{fraction:5.1%}] {message}", file=sys.stderr, flush=True)


def _cmd_probe(args: argparse.Namespace) -> int:
    """Probe a connected board and print its identity."""
    info = probe_device(_device_from_args(args))
    if info.implementation is None:
        print("probe did not return implementation marker", file=sys.stderr)
        return 1
    if args.json_output:
        print(
            json.dumps(
                {
                    "runtime": info.implementation.name,
                    "version": info.implementation.version,
                    "machine": info.implementation.machine,
                    "board_id": info.board_id,
                    "uid": info.uid,
                },
                indent=2,
            )
        )
    else:
        print(f"runtime: {info.implementation.name}")
        print(f"version: {info.implementation.version}")
        print(f"machine: {info.implementation.machine}")
        if info.board_id:
            print(f"board_id: {info.board_id}")
        if info.uid:
            print(f"uid: {info.uid}")
    return 0


def _cmd_flash(args: argparse.Namespace) -> int:
    """Download + apply firmware to a connected board."""
    flash_firmware(
        args.url,
        _device_from_args(args),
        reflash_method=args.method,
        bootloader_drive_path=args.bootloader_drive_path,
        interactive=not args.non_interactive,
        erase_flash=args.erase,
        flash_offset=args.offset,
        on_progress=_stderr_progress,
    )
    return 0


def _cmd_resolve_firmware_url(args: argparse.Namespace) -> int:
    """Print the canonical firmware download URL for a board + version."""
    url = resolve_firmware_url(
        args.board_id, args.runtime, args.version, language=args.language,
    )
    print(url)
    return 0


def _cmd_deploy(args: argparse.Namespace) -> int:
    """Push a file set onto a connected board and run the entrypoint."""
    # Import here so the top-level CLI stays lightweight — deployer
    # pulls in transport machinery that is irrelevant for probe /
    # resolve-firmware-url invocations.
    from .deployer import Deployer

    if args.directory is not None and args.file_map is not None:
        print(
            "error: --directory and --file-map are mutually exclusive",
            file=sys.stderr,
        )
        return 2

    source: DirectorySource | FileMapSource
    if args.directory is not None:
        source = DirectorySource(
            args.directory,
            entrypoint=args.entrypoint,
            resource_prefix=args.resource_prefix,
        )
    elif args.file_map is not None:
        file_map_data = json.loads(args.file_map.read_text())
        if not isinstance(file_map_data, dict):
            print(
                "error: --file-map JSON must be an object mapping "
                "on-device paths to file contents",
                file=sys.stderr,
            )
            return 2
        source = FileMapSource(file_map_data, entrypoint=args.entrypoint)
    else:
        print(
            "error: either --directory or --file-map must be supplied",
            file=sys.stderr,
        )
        return 2

    result = Deployer(_device_from_args(args)).deploy(
        source, on_progress=_stderr_progress,
    )
    if result.execute_output:
        print(result.execute_output, end="")
    if not result.success:
        if result.traceback:
            print(f"\n--- traceback ---\n{result.traceback}", file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level ``chumicro-deploy`` argument parser."""
    parser = argparse.ArgumentParser(
        prog="chumicro-deploy",
        description=(
            "Host-side device transports and deploy tooling for "
            "CircuitPython and MicroPython boards."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    probe_parser = subparsers.add_parser(
        "probe", help="Probe a connected board's runtime identity.",
    )
    _add_device_args(probe_parser)
    probe_parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit probe result as JSON instead of key: value lines.",
    )
    probe_parser.set_defaults(func=_cmd_probe)

    flash_parser = subparsers.add_parser(
        "flash",
        help="Download a firmware URL and flash it onto the board.",
    )
    _add_device_args(flash_parser)
    flash_parser.add_argument(
        "--url", required=True, help="Firmware download URL.",
    )
    flash_parser.add_argument(
        "--method",
        choices=("uf2", "esptool"),
        required=True,
        help=(
            "Reflash method: uf2 for RP2040 / RP2350 / TinyUF2-flashed "
            "boards; esptool for ESP32 family."
        ),
    )
    flash_parser.add_argument(
        "--erase",
        action="store_true",
        help=(
            "esptool path only: run erase-flash before write-flash.  "
            "Wipes every user partition (CIRCUITPY drive, NVS, wifi "
            "credentials).  Recommended for first-install and recovery."
        ),
    )
    flash_parser.add_argument(
        "--offset",
        default="0x0",
        help=(
            "esptool path only: write-flash offset.  0x0 for "
            "CircuitPython combined .bin (default); 0x1000 for "
            "MicroPython ESP32 / S2 / S3 .bin."
        ),
    )
    flash_parser.add_argument(
        "--bootloader-drive",
        dest="bootloader_drive_path",
        type=Path,
        default=None,
        help=(
            "uf2 path only: explicit bootloader drive mount.  "
            "Skips auto-detection."
        ),
    )
    flash_parser.add_argument(
        "--non-interactive",
        action="store_true",
        help=(
            "Fail instead of prompting when programmatic bootloader "
            "entry does not produce a bootloader port or UF2 drive.  "
            "Use in automated flows that don't have stdin."
        ),
    )
    flash_parser.set_defaults(func=_cmd_flash)

    firmware_url_parser = subparsers.add_parser(
        "resolve-firmware-url",
        help="Print the canonical firmware URL for a board + version.",
    )
    firmware_url_parser.add_argument(
        "--board-id", required=True,
        help="Board identifier (e.g. raspberry_pi_pico_w).",
    )
    firmware_url_parser.add_argument(
        "--runtime",
        choices=("circuitpython", "micropython"),
        required=True,
    )
    firmware_url_parser.add_argument(
        "--version", required=True,
        help="Firmware version (e.g. 10.1.4, 10.2.0-rc.0).",
    )
    firmware_url_parser.add_argument(
        "--language",
        default="en_US",
        help="Adafruit language code for CircuitPython (default en_US).",
    )
    firmware_url_parser.set_defaults(func=_cmd_resolve_firmware_url)

    deploy_parser = subparsers.add_parser(
        "deploy",
        help="Push files onto the board and run the entrypoint.",
    )
    _add_device_args(deploy_parser)
    source_group = deploy_parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--directory",
        type=Path,
        help="Directory tree to deploy (DirectorySource).",
    )
    source_group.add_argument(
        "--file-map",
        type=Path,
        help=(
            "Path to a JSON file mapping on-device paths to file "
            "contents (FileMapSource)."
        ),
    )
    deploy_parser.add_argument(
        "--entrypoint", required=True,
        help="On-device path of the entrypoint file (e.g. /code.py).",
    )
    deploy_parser.add_argument(
        "--resource-prefix",
        default="/",
        help="On-device prefix for non-entrypoint files (default /).",
    )
    deploy_parser.set_defaults(func=_cmd_deploy)

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.  Returns the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
