"""``install-firmware`` / ``upgrade-firmware`` / ``reset-board`` subcommands."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from chumicro_deploy import (
    CircuitpythonTransportError,
    FlashFirmwareError,
    MicropythonTransportError,
    flash_firmware,
)
from chumicro_deploy.firmware_url import (
    UnresolvedFirmwareError,
    derive_firmware_url,
)

from chumicro_workspace.cli._common import (
    _add_device_selector,
    _add_non_interactive_arg,
    _add_workspace_arg,
    _find_devices_yml_entry_for_args,
    _resolve_device,
    _resolve_workspace,
)


def _cmd_install_firmware(args: argparse.Namespace) -> int:
    """Download + flash firmware onto the selected board.

    ``upgrade-firmware`` is registered as an alias of this command.
    Flashing the same URL onto a board that already has firmware *is*
    an upgrade, so the implementation does not branch.

    ``--url`` is optional.  When omitted, the URL is derived via
    :func:`chumicro_deploy.firmware_url.derive_firmware_url` from the
    device entry's ``hardware.firmware_source`` (custom),
    ``hardware.board_id`` (CP S3 listing → latest stable), or
    ``hardware.machine`` (MP curated map).  Unresolvable cases surface
    a precise message and exit 2 so the user can paste an explicit URL
    into ``--url`` (or the entry's ``hardware.firmware_source``).
    """
    workspace = _resolve_workspace(args)
    device = _resolve_device(workspace, args)

    if args.url is not None:
        firmware_url = args.url
    else:
        entry = _find_devices_yml_entry_for_args(workspace, args)
        if entry is None:
            print(
                "install-firmware: --url omitted and no device entry "
                "to derive from.  Pass --url explicitly or register "
                "the device with `add-device` first.",
                file=sys.stderr,
            )
            return 2
        try:
            firmware_url = derive_firmware_url(entry, allow_prerelease=args.allow_prerelease)
        except UnresolvedFirmwareError as exception:
            print(f"install-firmware: {exception}", file=sys.stderr)
            return 2
        print(f"install-firmware: resolved {firmware_url}")

    # Auto-detect non-interactive from stdin TTY so a piped / CI run skips
    # any flash-time prompts; an explicit --non-interactive always wins.
    non_interactive = args.non_interactive or not sys.stdin.isatty()
    flash_fn = args._env.flash_firmware_fn
    if flash_fn is None:
        flash_fn = flash_firmware

    def _report_progress(fraction: float, message: str) -> None:
        # A multi-MB download plus flash is otherwise a silent terminal for
        # up to a minute; print each milestone so the user sees the board
        # making progress instead of wondering whether it hung.
        print(f"install-firmware: [{int(fraction * 100):3d}%] {message}")

    try:
        flash_fn(
            firmware_url,
            device,
            reflash_method=args.method,
            bootloader_drive_path=args.bootloader_drive_path,
            interactive=not non_interactive,
            erase_flash=args.erase,
            flash_offset=args.offset,
            on_progress=_report_progress,
        )
    except FlashFirmwareError as flash_error:
        # FlashFirmwareError messages carry their own recovery guidance
        # (bootloader-mode steps, "install esptool", a download 404 wrapped
        # from URLError).  Surface the message and exit non-zero instead of
        # dumping a traceback at the user.
        print(f"install-firmware: {flash_error}", file=sys.stderr)
        return 1
    return 0


def _cmd_reset_board(args: argparse.Namespace) -> int:
    """Wipe the device's user filesystem and leave the board idle.

    Standalone counterpart to ``deploy --wipe``.  See the
    ``reset-board`` argparse description in
    :func:`_add_firmware_parsers` for the destructive-recovery and
    RAM-mode caveats.
    """
    workspace = _resolve_workspace(args)
    device = _resolve_device(workspace, args)

    transport = device.create_transport()
    target = f"{device.transport}@{device.address}"
    if transport.mode in ("ram", "mount"):
        print(
            f"reset-board: {target} is configured for {transport.mode} "
            "mode, so there is nothing in flash to wipe.  Re-run on a board whose "
            "deploy_mode is flash / copy if you intended to clear "
            "persistent state.",
        )
        return 0

    if not args.yes:
        print(
            f"reset-board: refusing to wipe {target} without --yes.  "
            "This destroys every user file on the board, including "
            "settings.toml and any hand-edited boot.py.",
            file=sys.stderr,
        )
        return 2

    print(f"reset-board: wiping filesystem on {target}")
    try:
        transport.connect()
        try:
            transport.wipe_filesystem()
        finally:
            transport.disconnect()
    except (CircuitpythonTransportError, MicropythonTransportError) as reset_error:
        # A wedged board (FAT remount timeout, dropped USB) raises a
        # transport error here.  reset-board is itself the destructive
        # remediation, so the next move on failure is a physical replug;
        # surface that instead of a traceback.
        print(
            f"reset-board: {reset_error}\n"
            "  Replug the board and re-run; if it stays wedged, see "
            "docs/troubleshooting/.",
            file=sys.stderr,
        )
        return 1
    print(f"reset-board: {target} filesystem wiped.")
    return 0


def _add_firmware_args(parser: argparse.ArgumentParser) -> None:
    """Attach the shared firmware-flash flags."""
    parser.add_argument(
        "--url",
        default=None,
        help=(
            "Firmware download URL.  When omitted, the URL is "
            "derived from the device entry's hardware fields (CP: "
            "S3-bucket lookup; MP: curated machine→BOARD map; or "
            "hardware.firmware_source override)."
        ),
    )
    parser.add_argument(
        "--allow-prerelease",
        action="store_true",
        help=(
            "CP-only: include pre-release versions (-rc.0, -beta.1) "
            "when deriving the latest URL.  Stable-only by default."
        ),
    )
    parser.add_argument(
        "--method",
        choices=("uf2", "esptool"),
        required=True,
        help="Flash backend: uf2 for RP2040/RP2350, esptool for ESP32 family.",
    )
    parser.add_argument(
        "--bootloader-drive",
        dest="bootloader_drive_path",
        type=Path,
        default=None,
        help="uf2 path only: explicit bootloader drive mount.",
    )
    parser.add_argument(
        "--erase",
        action="store_true",
        help="esptool path only: erase-flash before write-flash.",
    )
    parser.add_argument(
        "--offset",
        default="0x0",
        help="esptool path only: write-flash offset (default 0x0).",
    )
    _add_non_interactive_arg(parser)


def _add_firmware_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Register ``install-firmware`` / ``upgrade-firmware`` / ``reset-board``."""
    install_firmware_parser = subparsers.add_parser(
        "install-firmware",
        help="Download + flash firmware onto the selected board.",
    )
    _add_workspace_arg(install_firmware_parser)
    _add_device_selector(install_firmware_parser)
    _add_firmware_args(install_firmware_parser)
    install_firmware_parser.set_defaults(func=_cmd_install_firmware)

    reset_board_parser = subparsers.add_parser(
        "reset-board",
        help=(
            "Wipe the device's user filesystem (clean-slate, no redeploy)."
        ),
        description=(
            "Erase every user file the runtime can see on the selected "
            "board, including out-of-scope files like settings.toml and "
            "hand-edited boot.py, without redeploying any project.  "
            "Standalone counterpart to `deploy --wipe`.  Used to recover "
            "a board whose flash filled up with stage residue (the "
            "MicroPython path runs `os.VfsLfs2.mkfs`, which `os.remove` "
            "alone cannot match: LittleFS metadata + wear-leveling "
            "artifacts survive a file-walk).  No-op in RAM / mount mode."
        ),
    )
    _add_workspace_arg(reset_board_parser)
    _add_device_selector(reset_board_parser)
    reset_board_parser.add_argument(
        "--yes",
        action="store_true",
        help=(
            "Confirm the destructive wipe.  Without this flag, the "
            "command exits 2 without touching the board so a typoed "
            "device id cannot accidentally erase production state."
        ),
    )
    reset_board_parser.set_defaults(func=_cmd_reset_board)


def _add_upgrade_firmware_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``upgrade-firmware`` alias of ``install-firmware``."""
    upgrade_firmware_parser = subparsers.add_parser(
        "upgrade-firmware",
        help="Alias of install-firmware: same flash flow.",
    )
    _add_workspace_arg(upgrade_firmware_parser)
    _add_device_selector(upgrade_firmware_parser)
    _add_firmware_args(upgrade_firmware_parser)
    upgrade_firmware_parser.set_defaults(func=_cmd_install_firmware)
