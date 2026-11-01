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
        help=(
            "Firmware the board runs.  Required unless --devices-file "
            "names the board."
        ),
    )
    parser.add_argument(
        "--address",
        help=(
            "Serial port of the board, such as /dev/cu.usbmodem1101 on "
            "macOS or /dev/ttyACM0 on Linux.  Required unless "
            "--devices-file names the board."
        ),
    )
    parser.add_argument(
        "--baudrate",
        type=int,
        default=115200,
        help="Serial speed in baud (default: 115200).",
    )
    parser.add_argument(
        "--deploy-mode",
        choices=_DEPLOY_MODE_CHOICES,
        default=DeployMode.RAM.value,
        help=(
            "Where the deploy command puts the files.  ram (default) "
            "runs them from the board's memory and leaves the files "
            "stored on the board alone.  flash writes them to the "
            "board, so the code runs again after a reset."
        ),
    )
    parser.add_argument(
        "--devices-file",
        type=Path,
        default=None,
        help=(
            "Path to a devices.yml file.  The board's runtime, port, "
            "baud rate, and deploy mode come from the entry --device "
            "names, and --transport, --address, --baudrate, and "
            "--deploy-mode are ignored."
        ),
    )
    parser.add_argument(
        "--device",
        dest="device_id",
        default=None,
        help=(
            "Id of a board entry in --devices-file.  When omitted, the "
            "file's defaults: block picks the board, which works when "
            "it names a default for one runtime only."
        ),
    )
    parser.add_argument(
        "--devices-format",
        default="default",
        help=(
            "Format of --devices-file.  The built-in format, default, "
            "reads devices.yml.  Other packages add formats through "
            "the chumicro_deploy.config_loaders entry-point group."
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
            "Copy Python files to a CircuitPython or MicroPython board "
            "and run them, install new firmware, or ask a board which "
            "firmware it runs.  Inside a ChuMicro workspace, "
            "chumicro-workspace runs the same steps and finds each "
            "board by its name in devices.yml."
        ),
        epilog=(
            "Run chumicro-deploy COMMAND --help to list the options "
            "of one command."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    probe_parser = subparsers.add_parser(
        "probe",
        help="Print which firmware and version a connected board runs.",
        description=(
            "Connect to a board and print the runtime, version, and "
            "machine name it reports, plus its unique id when the "
            "board has one."
        ),
    )
    _add_device_args(probe_parser)
    probe_parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Print the result as one JSON object.",
    )
    probe_parser.set_defaults(func=_cmd_probe)

    flash_parser = subparsers.add_parser(
        "flash-firmware",
        help="Download firmware and install it on a board.",
        description=(
            "Download a firmware file and install it on a connected "
            "board, replacing the firmware it runs now.  The command "
            "puts the board into its bootloader itself and asks for a "
            "button press only when that fails."
        ),
    )
    _add_device_args(flash_parser)
    flash_parser.add_argument(
        "--url", required=True,
        help=(
            "Download link for the firmware file, ending in .uf2 or "
            ".bin.  For CircuitPython, resolve-firmware-url prints one."
        ),
    )
    flash_parser.add_argument(
        "--method",
        choices=_REFLASH_METHOD_CHOICES,
        default=None,
        help=(
            "How to install the firmware.  uf2 copies it to the "
            "board's bootloader drive, for the Raspberry Pi Pico "
            "family and other UF2 boards.  esptool writes it over "
            "serial, for the ESP32 family.  Default: uf2 for a .uf2 "
            "link, esptool for a .bin link."
        ),
    )
    flash_parser.add_argument(
        "--no-erase",
        dest="erase_flash",
        action="store_false",
        default=True,
        help=(
            "esptool only.  Keep the board's files and stored data, "
            "saved wifi credentials included, during an in-place "
            "upgrade.  By default esptool erases the whole flash "
            "first, which empties the CIRCUITPY drive."
        ),
    )
    flash_parser.add_argument(
        "--offset",
        default="0x0",
        help=(
            "esptool only.  Flash address where the firmware image "
            "starts (default: 0x0, right for CircuitPython .bin "
            "files).  MicroPython on ESP32 and ESP32-S2 needs 0x1000.  "
            "The micropython.org download page for each board lists "
            "its offset."
        ),
    )
    flash_parser.add_argument(
        "--bootloader-drive",
        dest="bootloader_drive_path",
        type=Path,
        default=None,
        help=(
            "uf2 only.  Folder where the board's bootloader drive is "
            "mounted, such as /Volumes/RPI-RP2.  Skips the automatic "
            "search."
        ),
    )
    flash_parser.add_argument(
        "--non-interactive",
        action="store_true",
        help=(
            "Exit with an error instead of asking for a button press "
            "when the command cannot put the board into its "
            "bootloader.  Use it in scripts and CI."
        ),
    )
    flash_parser.set_defaults(func=_cmd_flash_firmware)

    firmware_url_parser = subparsers.add_parser(
        "resolve-firmware-url",
        help="Print the CircuitPython download link for a board.",
        description=(
            "Print the CircuitPython firmware download link for a "
            "board and version.  The command needs no board plugged "
            "in and makes no network request."
        ),
    )
    firmware_url_parser.add_argument(
        "--board-id", required=True,
        help=(
            "Board id as circuitpython.org spells it, such as "
            "raspberry_pi_pico_w."
        ),
    )
    firmware_url_parser.add_argument(
        "--runtime",
        choices=_RUNTIME_CHOICES,
        required=True,
        help=(
            "Pass circuitpython.  A MicroPython download link carries "
            "a build date the command cannot know, so micropython "
            "exits with an error."
        ),
    )
    firmware_url_parser.add_argument(
        "--version", required=True,
        help="CircuitPython release, such as 10.1.4 or 10.2.0-rc.0.",
    )
    firmware_url_parser.add_argument(
        "--language",
        default="en_US",
        help="CircuitPython language code (default: en_US).",
    )
    firmware_url_parser.set_defaults(func=_cmd_resolve_firmware_url)

    deploy_parser = subparsers.add_parser(
        "deploy",
        help="Copy files to a board and run the entry file.",
        description=(
            "Copy a folder or a JSON file map to a board, run the "
            "entry file, and print its output.  When a step fails, "
            "the command names the cause, lists the steps that fix "
            "it, and offers a retry."
        ),
    )
    _add_device_args(deploy_parser)
    source_group = deploy_parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--directory",
        type=Path,
        help="Folder on this computer to copy, subfolders included.",
    )
    source_group.add_argument(
        "--file-map",
        type=Path,
        help=(
            "JSON file that maps board paths to file contents, such "
            "as {\"/code.py\": \"print('hi')\"}."
        ),
    )
    deploy_parser.add_argument(
        "--entrypoint", required=True,
        help=(
            "Board path of the file to run after the copy, such as "
            "/code.py on CircuitPython or /main.py on MicroPython.  It "
            "must be one of the copied files."
        ),
    )
    deploy_parser.add_argument(
        "--resource-prefix",
        default="/",
        help=(
            "--directory only.  Board folder the copied files land in "
            "(default: /, the top of the board's filesystem).  "
            "--entrypoint must start with this folder."
        ),
    )
    deploy_parser.add_argument(
        "--no-wipe",
        dest="clean",
        action="store_false",
        default=True,
        help=(
            "flash mode only.  Keep board files the deploy did not "
            "send.  By default a flash deploy deletes every board "
            "file outside the new payload, settings.toml included, "
            "and keeps only boot.py, boot_out.txt, and "
            "_chu_kv.msgpack.  With --no-wipe, it deletes old files "
            "only from /lib and from code.py, main.py, active.py, and "
            "runtime_config.msgpack."
        ),
    )
    deploy_parser.add_argument(
        "--wipe",
        action="store_true",
        help=(
            "Erase every file on the board before copying, boot.py, "
            "boot_out.txt, and _chu_kv.msgpack included.  Use it to "
            "recover a board whose filesystem is corrupt.  Has no "
            "effect in ram mode."
        ),
    )
    deploy_parser.add_argument(
        "--target-runtime",
        choices=_RUNTIME_CHOICES,
        default=None,
        help=(
            "--directory only.  Skip .py files whose "
            "__chumicro_runtimes__ marker leaves out this runtime "
            "(default: the board's runtime)."
        ),
    )
    deploy_parser.add_argument(
        "--non-interactive",
        action="store_true",
        help=(
            "Make one attempt with no prompts, for scripts and CI.  A "
            "failure prints its cause and fix steps, then exits 1.  "
            "By default a fixable failure waits for Enter and "
            "retries, up to three attempts."
        ),
    )
    deploy_parser.add_argument(
        "--tail-seconds",
        type=float,
        default=None,
        help=(
            "CircuitPython flash mode only.  Seconds to keep printing "
            "the board's output after it restarts into the new code "
            "(default: 10).  Raise it when the code prints its first "
            "line late, such as after a wifi connect.  0 returns as "
            "soon as the board restarts and leaves the code running."
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
