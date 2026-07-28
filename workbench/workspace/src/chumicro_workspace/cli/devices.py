"""Device + registry subcommands.

``probe`` reports the runtime identity of one board.  ``discover``
lists serial ports the host can see.  ``devices`` prints
``devices.yml`` entries.  ``add-device`` probes a fresh board and
writes a new entry.  ``rename`` rewrites a project directory name or
a ``devices.yml`` entry id.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable
from typing import TYPE_CHECKING

import chumicro_deploy
from chumicro_deploy import Device
from chumicro_deploy.config.default import (
    DeviceConfigError,
)
from chumicro_deploy.config.default import (
    load_devices as load_validated_devices,
)
from chumicro_deploy.config.devices_yaml import (
    DeviceAlreadyExistsError,
    DeviceNotFoundError,
    HardwareOverwriteError,
    add_device,
    dump_devices,
    find_device,
    list_device_ids,
    load_devices,
    remove_device,
    rename_device,
    update_device_address,
    update_device_firmware_version,
    update_device_hardware,
)
from serial.tools import list_ports

from chumicro_workspace.cli._common import (
    _add_device_selector,
    _add_non_interactive_arg,
    _add_workspace_arg,
    _emit_probe_failure,
    _hardware_from_probe_info,
    _resolve_device,
    _resolve_project_name,
    _resolve_serial_port,
    _resolve_workspace,
    _stdin_prompt,
)
from chumicro_workspace.cli.setup import (
    _ensure_namespace_parents,
    _validate_project_name,
)
from chumicro_workspace.firmware_support import (
    FirmwareSupportStatus,
    check_firmware_supported,
)
from chumicro_workspace.firmware_support import (
    explain as explain_firmware_support,
)
from chumicro_workspace.onboarding import (
    BoardState,
    detect_board_state,
    probe_with_runtime_inference,
)

if TYPE_CHECKING:  # pragma: no cover - type-only
    from chumicro_deploy import DeviceImplementation


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _cmd_probe(args: argparse.Namespace) -> int:
    """Probe a board's runtime identity (delegates to chumicro-deploy)."""
    workspace = _resolve_workspace(args)
    device = _resolve_device(workspace, args)
    info = chumicro_deploy.probe_device(device)
    if info.implementation is None:
        print("probe: no implementation marker", file=sys.stderr)
        return 1
    print(f"runtime: {info.implementation.name}")
    print(f"version: {info.implementation.version}")
    print(f"machine: {info.implementation.machine}")
    if info.uid:
        print(f"uid: {info.uid}")
    return 0


def _cmd_discover(args: argparse.Namespace) -> int:  # noqa: ARG001
    """List serial ports the host can see (pyserial-backed)."""
    ports = sorted(list_ports.comports(), key=lambda port: port.device)
    if not ports:
        print("discover: no serial ports detected")
        return 0
    for port in ports:
        description = port.description or "(no description)"
        print(f"{port.device}\t{description}")
    return 0


def _cmd_devices(args: argparse.Namespace) -> int:
    """Print the entries in ``devices.yml`` (one per line)."""
    workspace = _resolve_workspace(args)
    if not workspace.devices_yaml.is_file():
        print(f"devices: {workspace.devices_yaml} does not exist yet")
        return 0
    try:
        entries = load_validated_devices(workspace.devices_yaml)
    except DeviceConfigError as exception:
        print(f"devices: {exception}", file=sys.stderr)
        return 1
    if not entries:
        print("devices: no entries")
        return 0
    for entry in entries:
        print(f"{entry.identifier}\t{entry.runtime}\t{entry.address}")
    return 0


# ---------------------------------------------------------------------------
# Device-id suggestion helpers
# ---------------------------------------------------------------------------


def _suggest_device_id(implementation: DeviceImplementation) -> str:
    """Suggest a device id from the probed machine string.

    Strips the ``" with <chip>"`` SoC suffix and slugifies the
    leading board identifier:

    * ``"Raspberry Pi Pico W with rp2040"``     → ``"raspberry-pi-pico-w"``
    * ``"S2Mini with ESP32S2-S2FN4R2"``         → ``"s2mini"``
    * ``"LOLIN_S2_MINI with ESP32-S2FN4R2"``    → ``"lolin-s2-mini"``

    The strip pattern is ``" with <anything-to-end-of-string>"``
    rather than ``\\w+$``, because chip variants like ``ESP32S2-S2FN4R2``
    contain hyphens and would otherwise survive into the slug as
    ``s2mini-with-esp32s2-s2fn4r2``.

    Falls back to ``"board"`` when ``machine`` is empty (older
    firmware) or sanitises to nothing.  Neutral default that the
    user can rename via ``rename --device``.
    """
    machine = implementation.machine or ""
    # Trim the trailing " with <chip>" tail at end-of-string.  Anchored
    # at $ so a board with the word "with" mid-name doesn't lose its tail.
    cleaned = re.sub(r"\s+with\s+.*$", "", machine, flags=re.IGNORECASE)
    # Replace non-identifier runs with single hyphens, lowercase.
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", cleaned).strip("-").lower()
    return slug or "board"


def _suggest_add_device_id(
    *,
    implementation: DeviceImplementation,
    existing_ids: set[str],
) -> str:
    """Default ``add-device`` id when the user omits the positional.

    :func:`_suggest_device_id`'s machine-string slug plus a runtime
    suffix (``-cp`` / ``-mp``):

    * ``"Raspberry Pi Pico W with rp2040"`` + circuitpython
      → ``"raspberry-pi-pico-w-cp"``
    * ``"LOLIN_S2_MINI with ESP32-S2FN4R2"`` + micropython
      → ``"lolin-s2-mini-mp"``
    * Empty machine string → ``"circuitpython-cp"`` (slug-helper
      fallback, rare, only fires when the probe returned no machine
      identifier).

    On collision with *existing_ids*, append ``"-2"``, ``"-3"``, etc.
    The user can ``rename --device <old> <new>`` afterwards.

    Args:
        implementation: Probe's :class:`DeviceImplementation` (carries
            the ``machine`` string + runtime ``name``).
        existing_ids: All ids already in ``devices.yml``, for
            collision resolution.
    """
    base_slug = _suggest_device_id(implementation)
    runtime_suffix_map = {"circuitpython": "cp", "micropython": "mp"}
    suffix = runtime_suffix_map.get(
        implementation.name, implementation.name.lower(),
    )
    base_id = f"{base_slug}-{suffix}"

    if base_id not in existing_ids:
        return base_id
    counter = 2
    while f"{base_id}-{counter}" in existing_ids:
        counter += 1
    return f"{base_id}-{counter}"


# ---------------------------------------------------------------------------
# Registry mutation handlers (add-device, rename)
# ---------------------------------------------------------------------------


def _cmd_add_device(
    args: argparse.Namespace,
    *,
    prompt_func: Callable[[str], str] = _stdin_prompt,
) -> int:
    """Probe a board and register it in devices.yml.

    The ``runtime``, ``hardware.uid``, and ``hardware.machine``
    fields come from :func:`chumicro_deploy.probe_device`; ``address``
    rides through as-is.

    ``--address`` defaults to a port picker when interactive (numbered
    list of detected serial ports, or auto-pick when only one).
    Non-interactive requires the flag and exits 2 otherwise.
    ``--runtime`` defaults to runtime inference: every candidate
    transport is tried in turn so the user can register a board
    without knowing what firmware it runs.

    Re-running with an existing id is blocked unless ``--force`` is
    passed.  The typical second invocation is "I swapped boards on
    this id" and warrants an explicit confirmation.  ``--demo``
    chains into the built-in demo deploy after a successful register.
    """
    workspace = _resolve_workspace(args)
    if args.address is None:
        if args.non_interactive:
            print(
                "add-device: --address is required in non-interactive mode.",
                file=sys.stderr,
            )
            return 2
        resolved_address = _resolve_serial_port(
            None, command_name="add-device", prompt_func=prompt_func,
        )
        if resolved_address is None:
            return 1
        args.address = resolved_address
    if args.runtime is None:
        inference = probe_with_runtime_inference(args.address)
        if inference.runtime is None or inference.info is None:
            _emit_probe_failure(
                "add-device",
                address=args.address,
                uf2_search_paths=args._env.uf2_search_paths,
                auto_detect_inference=inference,
            )
            return 1
        info = inference.info
        print(
            f"add-device: auto-detected runtime = {inference.runtime}",
        )
    else:
        probe_device_obj = Device(transport=args.runtime, address=args.address)
        try:
            info = chumicro_deploy.probe_device(probe_device_obj)
        except Exception as exception:  # noqa: BLE001 - onboarding diagnoses every failure
            _emit_probe_failure(
                "add-device",
                address=args.address,
                transport=args.runtime,
                uf2_search_paths=args._env.uf2_search_paths,
                probe_exception=exception,
            )
            return 1
        if info.implementation is None:
            diagnosis = detect_board_state(
                probe_device_obj,
                uf2_search_paths=args._env.uf2_search_paths,
            )
            if diagnosis.state is BoardState.UF2_BOOTLOADER:
                print(
                    "add-device: board is in UF2 bootloader, not REPL; "
                    "install firmware first.",
                    file=sys.stderr,
                )
            else:
                print(
                    "add-device: probe did not return implementation marker",
                    file=sys.stderr,
                )
            for line in diagnosis.next_steps:
                print(f"  {line}", file=sys.stderr)
            return 1

    firmware_version = info.implementation.version
    support = check_firmware_supported(info.implementation)

    data = load_devices(workspace.devices_yaml)
    hardware = _hardware_from_probe_info(info)

    # When the user didn't supply a positional id, derive one from the
    # probe's machine + runtime.  Suggested-id collisions resolve via
    # numeric suffix; the user can rename the entry afterwards via
    # ``rename --device``.
    if args.id is None:
        existing_ids = set(list_device_ids(data))
        args.id = _suggest_add_device_id(
            implementation=info.implementation,
            existing_ids=existing_ids,
        )
        print(f"add-device: using suggested id {args.id!r} (derived from probe)")

    try:
        add_device(
            data,
            device_id=args.id,
            runtime=info.implementation.name,
            address=args.address,
            hardware=hardware,
            description=args.description,
            firmware_version=firmware_version or None,
        )
    except DeviceAlreadyExistsError:
        if not args.force:
            print(
                f"add-device: {args.id!r} already exists; pass --force "
                "to re-probe and update the entry",
                file=sys.stderr,
            )
            return 1
        # Re-probe path: keep the existing entry's user-owned fields,
        # refresh the address silently, and update hardware-once leaves
        # under --force semantics so a board swap is reflected.
        update_device_address(data, args.id, args.address)
        if firmware_version:
            update_device_firmware_version(data, args.id, firmware_version)
        try:
            update_device_hardware(data, args.id, hardware or {}, force=True)
        except HardwareOverwriteError as exception:
            print(f"add-device: {exception}", file=sys.stderr)
            return 1

    dump_devices(data, workspace.devices_yaml)
    print(f"add-device: registered {args.id} ({info.implementation.name})")
    if support.status is not FirmwareSupportStatus.SUPPORTED:
        print(
            f"add-device: warning: {info.implementation.name} "
            f"firmware compatibility:",
            file=sys.stderr,
        )
        for line in explain_firmware_support(support):
            print(f"  {line}", file=sys.stderr)
    if getattr(args, "demo", False):
        # Local-import the demo handler so devices.py doesn't pull
        # examples.py at module-import time (the demo handler imports
        # the deploy stack).
        from chumicro_workspace.cli.examples import _cmd_demo  # noqa: PLC0415
        demo_args = argparse.Namespace(
            workspace_dir=args.workspace_dir,
            device_id=args.id,
            runtime=None,
            non_interactive=args.non_interactive,
            _env=args._env,
        )
        return _cmd_demo(demo_args)
    return 0


def _cmd_rename(args: argparse.Namespace) -> int:
    """Rename a project directory or a device id.

    Two modes (mutually exclusive): ``--project OLD NEW`` moves the
    project directory under ``projects/`` (both names accept bare /
    slash / dotted forms, intermediate namespace dirs are auto-
    created when the new path is in a fresh namespace);
    ``--device OLD NEW`` rewrites the devices.yml entry id + every
    reference to it under ``defaults:``.

    A project rename does NOT touch already-deployed devices.
    Re-deploy under the new name to ship the project's files to the
    board.
    """
    workspace = _resolve_workspace(args)

    if (args.project is None) == (args.device is None):
        print(
            "rename: pass exactly one of --project OLD NEW or --device OLD NEW",
            file=sys.stderr,
        )
        return 2

    if args.project is not None:
        old_input, new_input = args.project
        _validate_project_name(old_input)
        _validate_project_name(new_input)
        # Old name accepts bare-name disambiguation against the live
        # tree, matching the deploy / switch shape.  New name is just
        # normalized.  It doesn't exist yet so disambiguation doesn't apply.
        resolved_old = _resolve_project_name(workspace, old_input)
        resolved_new = new_input.replace(".", "/")
        old_path = workspace.project_dir(resolved_old)
        new_path = workspace.project_dir(resolved_new)
        if not old_path.is_dir():
            print(f"rename: project {old_path} not found", file=sys.stderr)
            return 1
        if new_path.exists():
            print(f"rename: {new_path} already exists", file=sys.stderr)
            return 1
        created_namespaces = _ensure_namespace_parents(workspace, new_path)
        for namespace_dir in created_namespaces:
            print(
                f"rename: creating namespace "
                f"{namespace_dir.relative_to(workspace.root)}/",
            )
        old_path.rename(new_path)
        print(f"rename: {resolved_old} → {resolved_new}")
        return 0

    old_id, new_id = args.device
    data = load_devices(workspace.devices_yaml)
    try:
        rename_device(data, old_id, new_id)
    except DeviceNotFoundError:
        print(f"rename: device {old_id!r} not found in devices.yml", file=sys.stderr)
        return 1
    except DeviceAlreadyExistsError as exception:
        print(f"rename: {exception}", file=sys.stderr)
        return 1
    dump_devices(data, workspace.devices_yaml)
    print(f"rename: device {old_id} → {new_id}")
    return 0


def _cmd_remove_device(args: argparse.Namespace) -> int:
    """Delete a device entry from devices.yml.

    Destructive: drops the user-owned metadata (description,
    deploy_mode, ...) that no probe can regenerate, so it is gated
    behind ``--yes`` exactly like ``reset-board``.  Any ``defaults:``
    reference to the id is nulled so the file stays loadable.
    """
    workspace = _resolve_workspace(args)
    if not workspace.devices_yaml.is_file():
        print(
            f"remove-device: {workspace.devices_yaml} does not exist yet",
            file=sys.stderr,
        )
        return 1
    if not args.yes:
        print(
            f"remove-device: refusing to delete {args.id!r} without "
            "--yes.  This drops the entry's user-owned metadata "
            "(description, deploy_mode, ...); a probe cannot rebuild it.",
            file=sys.stderr,
        )
        return 2
    data = load_devices(workspace.devices_yaml)
    try:
        remove_device(data, args.id)
    except DeviceNotFoundError:
        print(
            f"remove-device: {args.id!r} not found in devices.yml",
            file=sys.stderr,
        )
        return 1
    dump_devices(data, workspace.devices_yaml)
    print(f"remove-device: deleted {args.id}")
    return 0


def _cmd_reset_device(args: argparse.Namespace) -> int:
    """Rebuild a device entry from a fresh probe (full replace).

    Where ``add-device --force`` *updates* (keeps the user-owned
    zone), ``reset-device`` *replaces*.  It re-probes the connected
    board and rewrites the entry from silicon, dropping accumulated
    user-owned drift (description, deploy_mode, serial_baudrate) and
    re-deriving the hardware-once zone.  The id and any ``defaults:``
    binding survive (the id is the selector).  Gated behind ``--yes``
    because the user-owned drop is unrecoverable.  Re-infers the
    runtime by default (a reset is exactly when firmware may have
    been reflashed), unless ``--runtime`` pins it.
    """
    workspace = _resolve_workspace(args)
    if not workspace.devices_yaml.is_file():
        print(
            f"reset-device: {workspace.devices_yaml} does not exist yet",
            file=sys.stderr,
        )
        return 1
    data = load_devices(workspace.devices_yaml)
    existing = find_device(data, args.id)
    if existing is None:
        print(
            f"reset-device: {args.id!r} not found; use `add-device` "
            "to register a new board.",
            file=sys.stderr,
        )
        return 1
    if not args.yes:
        print(
            f"reset-device: refusing to rebuild {args.id!r} without "
            "--yes.  This drops the entry's user-owned fields "
            "(description, deploy_mode, serial_baudrate) and re-probes "
            "from the connected board.",
            file=sys.stderr,
        )
        return 2

    address = args.address or existing.get("address")
    if not address:
        print(
            f"reset-device: {args.id!r} has no stored address, so pass "
            "--address <port>.",
            file=sys.stderr,
        )
        return 1

    steer = (
        "reset-device: probe failed: the board must be connected to "
        "rebuild the entry.  To drop a stale entry without a board use "
        "`remove-device`; to re-register use `add-device`."
    )
    if args.runtime is None:
        inference = probe_with_runtime_inference(address)
        if inference.runtime is None or inference.info is None:
            _emit_probe_failure(
                "reset-device",
                address=address,
                uf2_search_paths=args._env.uf2_search_paths,
                auto_detect_inference=inference,
            )
            print(steer, file=sys.stderr)
            return 1
        info = inference.info
        print(f"reset-device: auto-detected runtime = {inference.runtime}")
    else:
        probe_device_obj = Device(transport=args.runtime, address=address)
        try:
            info = chumicro_deploy.probe_device(probe_device_obj)
        except Exception as exception:  # noqa: BLE001 - onboarding diagnoses every failure
            _emit_probe_failure(
                "reset-device",
                address=address,
                transport=args.runtime,
                uf2_search_paths=args._env.uf2_search_paths,
                probe_exception=exception,
            )
            print(steer, file=sys.stderr)
            return 1
        if info.implementation is None:
            print(
                "reset-device: probe did not return an implementation "
                "marker, so the entry cannot be rebuilt.",
                file=sys.stderr,
            )
            return 1

    remove_device(data, args.id)
    add_device(
        data,
        device_id=args.id,
        runtime=info.implementation.name,
        address=address,
        hardware=_hardware_from_probe_info(info),
        firmware_version=info.implementation.version or None,
    )
    dump_devices(data, workspace.devices_yaml)
    print(
        f"reset-device: rebuilt {args.id} "
        f"({info.implementation.name}) from probe",
    )
    return 0


# ---------------------------------------------------------------------------
# Parser wiring
# ---------------------------------------------------------------------------


def _add_devices_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Register the devices subcommands.

    ``add-device`` / ``probe`` / ``discover`` / ``devices`` /
    ``remove-device`` / ``reset-device`` (``rename`` is wired
    separately by :func:`_add_rename_parser`).
    """
    add_device_parser = subparsers.add_parser(
        "add-device",
        help="Probe a board and register it in devices.yml.",
    )
    _add_workspace_arg(add_device_parser)
    add_device_parser.add_argument(
        "id",
        nargs="?",
        default=None,
        help=(
            "User-friendly device id (e.g. 'back-porch-mp').  Optional: "
            "when omitted, a default is derived from the probe's "
            "machine string + runtime suffix (e.g. "
            "'raspberry-pi-pico-w-cp').  When the suggested id collides "
            "with an existing entry in devices.yml, a numeric suffix "
            "is appended (e.g. 'raspberry-pi-pico-w-cp-2')."
        ),
    )
    add_device_parser.add_argument(
        "--address",
        default=None,
        help=(
            "Serial port path of the connected board.  Optional: when "
            "omitted in interactive mode, the wizard auto-picks the "
            "only detected port or prompts with a numbered list when "
            "multiple are present.  Required under --non-interactive."
        ),
    )
    add_device_parser.add_argument(
        "--runtime",
        choices=("circuitpython", "micropython"),
        default=None,
        help=(
            "Runtime to probe: picks the right Device facade for "
            "probe_device.  Optional: when omitted, the runtime is "
            "auto-detected by trying both transports against the "
            "given address."
        ),
    )
    add_device_parser.add_argument(
        "--description",
        default=None,
        help="Free-form note recorded under 'description:' (user-owned zone).",
    )
    add_device_parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Overwrite an existing entry with this id: refreshes the "
            "address and hardware-once fields from the live probe."
        ),
    )
    add_device_parser.add_argument(
        "--demo",
        action="store_true",
        help=(
            "After registering, chain into the built-in demo deploy "
            "so a freshly registered board ships *something* in one "
            "command.  Equivalent to running `demo --device <id>` "
            "next."
        ),
    )
    _add_non_interactive_arg(add_device_parser)
    add_device_parser.set_defaults(func=_cmd_add_device)

    probe_parser = subparsers.add_parser(
        "probe",
        help="Print the runtime identity reported by the selected board.",
    )
    _add_workspace_arg(probe_parser)
    _add_device_selector(probe_parser)
    probe_parser.set_defaults(func=_cmd_probe)

    discover_parser = subparsers.add_parser(
        "discover",
        help="List the serial ports the host currently sees.",
    )
    discover_parser.set_defaults(func=_cmd_discover)

    devices_parser = subparsers.add_parser(
        "devices",
        help="Print every entry in devices.yml.",
    )
    _add_workspace_arg(devices_parser)
    devices_parser.set_defaults(func=_cmd_devices)

    remove_device_parser = subparsers.add_parser(
        "remove-device",
        help="Delete a device entry from devices.yml.",
        description=(
            "Delete one entry by id and null any defaults: reference "
            "to it so the file stays loadable.  Destructive: it drops "
            "user-owned metadata (description, deploy_mode, ...) that "
            "no probe can rebuild, so it is gated behind --yes.  No "
            "board needs to be connected."
        ),
    )
    _add_workspace_arg(remove_device_parser)
    remove_device_parser.add_argument(
        "id", help="Device id to delete (must match an entry in devices.yml).",
    )
    remove_device_parser.add_argument(
        "--yes",
        action="store_true",
        help=(
            "Confirm the deletion.  Without this flag the command "
            "exits 2 without touching the file so a typoed id cannot "
            "accidentally drop an entry."
        ),
    )
    _add_non_interactive_arg(remove_device_parser)
    remove_device_parser.set_defaults(func=_cmd_remove_device)

    reset_device_parser = subparsers.add_parser(
        "reset-device",
        help="Rebuild a device entry from a fresh probe (full replace).",
        description=(
            "Re-probe the connected board and rewrite the entry from "
            "silicon, keeping the id (and its defaults: binding) but "
            "dropping accumulated user-owned drift (description, "
            "deploy_mode, serial_baudrate) and re-deriving the "
            "hardware-once zone.  The replace counterpart to "
            "`add-device --force` (which updates in place).  Gated "
            "behind --yes; the board must be connected (probe failure "
            "steers to `remove-device` / `add-device`)."
        ),
    )
    _add_workspace_arg(reset_device_parser)
    reset_device_parser.add_argument(
        "id", help="Device id to rebuild (must match an entry in devices.yml).",
    )
    reset_device_parser.add_argument(
        "--address",
        default=None,
        help=(
            "Serial port to probe.  Optional: defaults to the entry's "
            "stored address (pass this when the board moved ports)."
        ),
    )
    reset_device_parser.add_argument(
        "--runtime",
        choices=("circuitpython", "micropython"),
        default=None,
        help=(
            "Pin the runtime to probe.  Optional: when omitted the "
            "runtime is re-inferred by trying both transports, because a "
            "reset is exactly when firmware may have been reflashed."
        ),
    )
    reset_device_parser.add_argument(
        "--yes",
        action="store_true",
        help=(
            "Confirm the rebuild.  Without this flag the command exits "
            "2 without touching the file or the board."
        ),
    )
    _add_non_interactive_arg(reset_device_parser)
    reset_device_parser.set_defaults(func=_cmd_reset_device)


def _add_rename_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``rename`` subparser.

    Split from ``_add_devices_parsers`` so it can be wired in alongside
    the other late-in-the-list commands without disturbing the
    visible ``--help`` ordering.
    """
    rename_parser = subparsers.add_parser(
        "rename",
        help="Rename a project directory or a device id.",
    )
    _add_workspace_arg(rename_parser)
    rename_target = rename_parser.add_mutually_exclusive_group(required=True)
    rename_target.add_argument(
        "--project",
        nargs=2,
        metavar=("OLD", "NEW"),
        default=None,
        help="Rename projects/OLD/ to projects/NEW/.",
    )
    rename_target.add_argument(
        "--device",
        nargs=2,
        metavar=("OLD", "NEW"),
        default=None,
        help="Rename a devices.yml entry id (also rewrites defaults: references).",
    )
    rename_parser.set_defaults(func=_cmd_rename)
