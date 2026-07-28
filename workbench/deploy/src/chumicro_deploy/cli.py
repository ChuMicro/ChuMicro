"""``chumicro-deploy`` command-line interface.

Thin wrapper over the public Python API.  Every CLI action maps to a
single :mod:`chumicro_deploy` function, no logic beyond argument
translation.  Third parties who prefer the programmatic API don't
need the CLI.  The CLI exists for quick one-off flashes, probes, and
URL lookups without writing a Python script.

Invoked via ``python -m chumicro_deploy <command> ...`` or, after
:mod:`chumicro-deploy` is installed, the ``chumicro-deploy`` console
script.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .circuitpython_transport import CircuitpythonTransportError
from .config.default import DeviceConfigError
from .device import Device
from .firmware import FlashFirmwareError, flash_firmware, resolve_firmware_url
from .firmware_url import UnresolvedFirmwareError
from .micropython_transport import MicropythonTransportError
from .probe import probe_device
from .protocol import DeployMode, ReflashMethod, Runtime
from .sources import DirectorySource, FileMapSource

#: Exceptions ``main()`` converts into a one-line ``error: <message>``
#: + exit 1.  Everything else propagates and gets the default Python
#: traceback, since those are bugs, not user-facing failures.
_FRIENDLY_ERRORS: tuple[type[Exception], ...] = (
    CircuitpythonTransportError,
    DeviceConfigError,
    FileNotFoundError,
    FlashFirmwareError,
    MicropythonTransportError,
    UnresolvedFirmwareError,
    ValueError,
)

_RUNTIME_CHOICES = tuple(runtime.value for runtime in Runtime)
_DEPLOY_MODE_CHOICES = tuple(mode.value for mode in DeployMode)
_REFLASH_METHOD_CHOICES = tuple(method.value for method in ReflashMethod)


def _add_device_args(parser: argparse.ArgumentParser) -> None:
    """Attach the shared Device construction flags.

    Two mutually-exclusive ways to specify the target:

    - Explicit: ``--transport`` + ``--address`` plus optional
      ``--baudrate``, ``--deploy-mode``, ``--drive``.
    - Chumicro ``devices.yml``: ``--devices-file PATH`` +
      ``--device ID`` reads the entry and fills in every field.
      ``--devices-file PATH`` with no ``--device`` picks the
      single runtime default from the ``defaults:`` block.
    """
    parser.add_argument(
        "--transport",
        choices=_RUNTIME_CHOICES,
        help="Runtime target identifier (required without --devices-file).",
    )
    parser.add_argument(
        "--address",
        help="Serial port path (required without --devices-file).",
    )
    parser.add_argument(
        "--baudrate",
        type=int,
        default=115200,
        help="Serial baudrate (CircuitPython only; default 115200).",
    )
    parser.add_argument(
        "--deploy-mode",
        choices=_DEPLOY_MODE_CHOICES,
        default=DeployMode.RAM.value,
        help="Deploy mode: ram (no-flash) or flash (persistent).",
    )
    parser.add_argument(
        "--devices-file",
        type=Path,
        default=None,
        help=(
            "Path to a device-config file.  When set, --transport / "
            "--address / --baudrate / --deploy-mode are filled from "
            "the entry selected by --device (or the single runtime "
            "default if --device is omitted)."
        ),
    )
    parser.add_argument(
        "--device",
        dest="device_id",
        default=None,
        help="Device id within --devices-file.",
    )
    parser.add_argument(
        "--devices-format",
        default="default",
        help=(
            "Config-file format name.  Built-in: 'default' (reads "
            "the devices.yml schema defined by "
            "chumicro_deploy.config.default).  Third parties "
            "register custom loaders via the "
            "'chumicro_deploy.config_loaders' entry-point group."
        ),
    )


def _device_from_args(args: argparse.Namespace) -> Device:
    """Build a :class:`Device` from a parsed subcommand namespace.

    Routes through :func:`chumicro_deploy.config.default.load_devices_yml`
    when ``--devices-file`` is supplied.  Otherwise falls back to the
    explicit ``--transport`` + ``--address`` path.
    """
    if args.devices_file is not None:
        # Lazy-import the loader registry so runs that don't touch
        # device configs don't pay the discovery cost.
        from .config import discover_config_loaders

        loaders = discover_config_loaders()
        loader_name = args.devices_format
        if loader_name not in loaders:
            raise SystemExit(
                f"error: unknown --devices-format: {loader_name!r}.  "
                f"Registered: {sorted(loaders.keys())!r}"
            )
        return loaders[loader_name](
            args.devices_file, device_id=args.device_id,
        )

    if args.transport is None or args.address is None:
        raise SystemExit(
            "error: --transport and --address are required unless "
            "--devices-file is supplied"
        )

    return Device(
        transport=args.transport,
        address=args.address,
        baudrate=args.baudrate,
        deploy_mode=args.deploy_mode,
    )


def _stderr_progress(fraction: float, message: str) -> None:
    """Progress callback that prints one line per event on stderr."""
    print(f"[{fraction:5.1%}] {message}", file=sys.stderr, flush=True)


def _cmd_probe(args: argparse.Namespace) -> int:
    """Probe a connected board and print its identity."""
    probe_fn = args._env.probe_device_fn or probe_device
    info = probe_fn(_device_from_args(args))
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


def _cmd_flash_firmware(args: argparse.Namespace) -> int:
    """Download + apply firmware to a connected board."""
    flash_fn = args._env.flash_firmware_fn or flash_firmware
    flash_fn(
        args.url,
        _device_from_args(args),
        reflash_method=args.method,
        bootloader_drive_path=args.bootloader_drive_path,
        interactive=not args.non_interactive,
        erase_flash=args.erase_flash,
        flash_offset=args.offset,
        on_progress=_stderr_progress,
    )
    return 0


def _cmd_resolve_firmware_url(args: argparse.Namespace) -> int:
    """Print the firmware download URL for a board + version."""
    url = resolve_firmware_url(
        args.board_id, args.runtime, args.version, language=args.language,
    )
    print(url)
    return 0


def _cmd_deploy(args: argparse.Namespace) -> int:
    """Push a file set onto a connected board and run the entrypoint."""
    from .deployer import Deployer
    from .recovery import RecoveringDeployer

    if args.directory is not None and args.file_map is not None:
        print(
            "error: --directory and --file-map are mutually exclusive",
            file=sys.stderr,
        )
        return 2

    # Build the device first so we can derive the deploy-time runtime
    # filter: unless --target-runtime overrides, the filter is the
    # device's configured runtime (--transport / --devices-file).
    device = _device_from_args(args)
    target_runtime = args.target_runtime or device.transport

    source: DirectorySource | FileMapSource
    if args.directory is not None:
        source = DirectorySource(
            args.directory,
            entrypoint=args.entrypoint,
            resource_prefix=args.resource_prefix,
            target_runtime=target_runtime,
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
        # FileMapSource is bytes-already-chosen by the caller, so
        # there is no filesystem walk to filter.  --target-runtime is
        # silently ignored for this source.
        source = FileMapSource(file_map_data, entrypoint=args.entrypoint)
    else:
        print(
            "error: either --directory or --file-map must be supplied",
            file=sys.stderr,
        )
        return 2

    deployer = Deployer(device)
    runner = RecoveringDeployer(
        deployer, prompt=None if args.non_interactive else input,
    )
    deleted: list[str] = []
    result = runner.deploy_diff(
        source,
        clean=args.clean,
        wipe=args.wipe,
        on_progress=_stderr_progress,
        on_file_deleted=deleted.append,
        tail_seconds=args.tail_seconds,
    )
    for stale_path in deleted:
        print(f"removed stale {stale_path}", file=sys.stderr)
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
        "flash-firmware",
        help="Download a firmware URL and flash it onto the board.",
    )
    _add_device_args(flash_parser)
    flash_parser.add_argument(
        "--url", required=True, help="Firmware download URL.",
    )
    flash_parser.add_argument(
        "--method",
        choices=_REFLASH_METHOD_CHOICES,
        default=None,
        help=(
            "Reflash method: uf2 for RP2040 / RP2350 / TinyUF2-flashed "
            "boards; esptool for ESP32 family.  When omitted, inferred "
            "from the --url extension (.uf2 → uf2, .bin → esptool)."
        ),
    )
    flash_parser.add_argument(
        "--no-erase",
        dest="erase_flash",
        action="store_false",
        default=True,
        help=(
            "esptool path only: skip the erase-flash step before "
            "write-flash.  Default erases first, wiping every user "
            "partition (CIRCUITPY drive, NVS, wifi credentials) so a "
            "fresh reflash doesn't inherit leftover sectors from a "
            "previous build.  Pass --no-erase to preserve user data "
            "on an in-place upgrade."
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
    flash_parser.set_defaults(func=_cmd_flash_firmware)

    firmware_url_parser = subparsers.add_parser(
        "resolve-firmware-url",
        help="Print the firmware URL for a board + version.",
    )
    firmware_url_parser.add_argument(
        "--board-id", required=True,
        help="Board identifier (e.g. raspberry_pi_pico_w).",
    )
    firmware_url_parser.add_argument(
        "--runtime",
        choices=_RUNTIME_CHOICES,
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
    deploy_parser.add_argument(
        "--no-wipe",
        dest="clean",
        action="store_false",
        default=True,
        help=(
            "Additive deploy: reconcile only the entrypoint / "
            "state files + /lib, leaving every other board file in "
            "place.  The default is clean-slate: the deploy removes "
            "anything that isn't the new payload or a device-required "
            "keep-set file (boot.py, boot_out.txt, _chu_kv.msgpack); a "
            "board-resident settings.toml is evicted.  Use --no-wipe "
            "only when you deliberately hand-manage board files."
        ),
    )
    deploy_parser.add_argument(
        "--wipe",
        action="store_true",
        help=(
            "Erase the *entire* device filesystem before deploying, "
            "the keep set (boot.py, boot_out.txt, _chu_kv.msgpack) "
            "included.  Stricter than the clean-slate default; for "
            "corruption recovery.  No-op in RAM mode."
        ),
    )
    deploy_parser.add_argument(
        "--target-runtime",
        choices=_RUNTIME_CHOICES,
        default=None,
        help=(
            "Override which runtime's files are deployed.  Defaults to "
            "the device's configured runtime (--transport / "
            "--devices-file).  Files marked for a different runtime "
            "via __chumicro_runtimes__ are filtered out.  Set "
            "explicitly to override the auto-derived value."
        ),
    )
    deploy_parser.add_argument(
        "--non-interactive",
        action="store_true",
        help=(
            "Run once, print the classified failure + ordered fix "
            "steps (and lsof PID/command for port-busy errors), then "
            "re-raise.  No retry loop, no user prompt.  Use in CI / "
            "scripted flows that don't have stdin.  Interactive "
            "coaching with a retry loop is on by default."
        ),
    )
    deploy_parser.add_argument(
        "--tail-seconds",
        type=float,
        default=None,
        help=(
            "How long to capture serial output after the entrypoint's "
            "soft-reboot (CircuitPython flash mode only).  Default uses "
            "the transport's built-in timeout (10 s).  Set higher when "
            "the entrypoint's first print lands beyond that window "
            "(MQTT connect, blocking recv, etc.).  Set to 0 to skip the "
            "capture entirely and return as soon as the soft-reboot "
            "has been triggered, leaving the board running."
        ),
    )
    deploy_parser.set_defaults(func=_cmd_deploy)

    return parser


@dataclass(frozen=True)
class CliEnv:
    """Injectable seams for :func:`main`.

    :func:`main` defaults to a no-override :class:`CliEnv` that uses
    the module-level implementations everywhere.  Pass a custom env
    to swap one seam for the duration of the call without
    monkeypatching module internals.  Sub-commands read the values
    off ``args._env``.

    Attributes:
        flash_firmware_fn: Override the firmware-flash callable.
            ``None`` means use the module-level
            :func:`chumicro_deploy.firmware.flash_firmware`.
        probe_device_fn: Override the probe callable.  ``None`` means
            use :func:`chumicro_deploy.probe.probe_device`.
    """

    flash_firmware_fn: Callable[..., None] | None = None
    probe_device_fn: Callable[..., object] | None = None


_DEFAULT_ENV = CliEnv()


def main(
    argv: list[str] | None = None,
    *,
    env: CliEnv | None = None,  # noqa: CHU001 - matches subprocess.run(env=...) convention
) -> int:
    """CLI entry point.  Returns the process exit code.

    Wraps the subcommand dispatch in a friendly-error catch so users
    see a one-line ``error: <message>`` for the documented exception
    types instead of a Python traceback.  Recovery output (e.g. the
    coaching block from :class:`RecoveringDeployer`) still prints
    before the catch fires.  Unrecognized exceptions propagate, since
    a traceback there is a bug, not a UX defect.

    Args:
        argv: Command-line arguments (``None`` reads from ``sys.argv``).
        env: Injectable seams.  Defaults to a no-override
            :class:`CliEnv` that uses the module-level implementations
            everywhere.  Stashed on ``args._env`` so sub-commands can
            read it.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    args._env = env if env is not None else _DEFAULT_ENV
    try:
        return args.func(args)
    except _FRIENDLY_ERRORS as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
