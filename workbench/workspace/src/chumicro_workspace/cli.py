"""``chumicro-workspace`` command dispatch.

Thin wrapper over the public ``chumicro_workspace`` /
``chumicro_deploy`` / ``chumicro_repl`` APIs.  Workspace template
repos vendor a tiny ``run.py`` shim that simply calls
:func:`main`; every command the workspace user invokes
(``python run.py deploy back-porch``, ``python run.py repl``, etc.)
routes through this dispatcher.

The full command set is documented in
``plans/workstreams/project-workspace.md`` Phase 4a.  Commands are
shipped at three depths:

* **Implemented** — full behaviour wired to the underlying library
  (``deploy``, ``probe``, ``devices``, ``repl``, ``new``,
  ``install-firmware`` / ``upgrade-firmware``, ``discover``,
  ``test``, ``setup``).
* **Stubbed for a planned slice** — registered with help text and a
  clear "implemented in Slice X" error so the dispatcher contract is
  stable before the implementation lands (``add-device``, ``rename``,
  ``sim``, ``env``, ``use``, ``sync``, ``upgrade``).

Stubs raise :exc:`NotImplementedError` carrying a one-line pointer to
the slice or workstream phase that will land them.  CLI invocation
catches the exception and exits 2 with a descriptive message — the
test suite asserts on that exit code so the rollout sequence stays
visible.
"""

from __future__ import annotations

import argparse
import keyword
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from chumicro_workspace.boot_shim import (
    multi_thing_boot_source,
    switch_source,
    thing_boot_source,
)
from chumicro_workspace.deploy_source import thing_directory_source
from chumicro_workspace.devices_yaml import (
    DeviceAlreadyExistsError,
    DeviceNotFoundError,
    HardwareOverwriteError,
    add_device,
    dump_devices,
    find_device,
    load_devices,
    rename_device,
    update_device_address,
    update_device_firmware_version,
    update_device_hardware,
)
from chumicro_workspace.firmware_support import (
    FirmwareSupportStatus,
    check_firmware_supported,
)
from chumicro_workspace.firmware_support import (
    explain as explain_firmware_support,
)
from chumicro_workspace.firmware_url import (
    UnresolvableFirmwareError,
    derive_firmware_url,
)
from chumicro_workspace.import_graph import thing_import_graph_source
from chumicro_workspace.onboarding import (
    BoardState,
    detect_board_state,
)
from chumicro_workspace.workspace import (
    WorkspaceLayout,
    WorkspaceNotFoundError,
)

if TYPE_CHECKING:  # pragma: no cover — type-only
    from chumicro_deploy import Device


# ---------------------------------------------------------------------------
# Common argparse helpers
# ---------------------------------------------------------------------------


def _add_workspace_arg(parser: argparse.ArgumentParser) -> None:
    """Attach the shared ``--workspace-dir`` flag.

    Defaults to walking up from the current working directory until a
    ``workspace.yml`` is found (mirrors ``git`` discovery).  Override
    when running multiple workspaces in parallel or when the user
    invokes the CLI from outside the tree (CI runners, IDE tasks).
    """
    parser.add_argument(
        "--workspace-dir",
        type=Path,
        default=None,
        help=(
            "Workspace root.  Defaults to walking up from the current "
            "directory until a workspace.yml is found."
        ),
    )


def _add_device_selector(parser: argparse.ArgumentParser) -> None:
    """Attach the shared ``--device`` / ``--runtime`` selectors.

    Resolved against ``<workspace>/devices.yml`` via
    :mod:`chumicro_deploy.config.default`.  Mutually-exclusive at
    runtime (the loader raises if both are passed alongside two
    runtime defaults).
    """
    parser.add_argument(
        "--device",
        dest="device_id",
        default=None,
        help="Pick a specific entry from devices.yml by id.",
    )
    parser.add_argument(
        "--runtime",
        choices=("circuitpython", "micropython"),
        default=None,
        help="Pick the default device for the named runtime.",
    )


def _resolve_workspace(args: argparse.Namespace) -> WorkspaceLayout:
    """Locate the workspace root for *args*.

    Wraps :class:`WorkspaceLayout.from_dir` so missing workspaces
    surface as a uniform ``SystemExit`` with a helpful message
    instead of a stack trace.
    """
    try:
        return WorkspaceLayout.from_dir(args.workspace_dir)
    except WorkspaceNotFoundError as exception:
        raise SystemExit(f"error: {exception}") from exception


def _find_devices_yml_entry_for_args(
    workspace: WorkspaceLayout,
    args: argparse.Namespace,
) -> Mapping[str, Any] | None:
    """Locate the raw ``devices.yml`` entry matching *args*' selectors.

    Mirrors :func:`chumicro_deploy.config.default.load_devices_yml`'s
    resolution order — explicit ``--device id`` wins outright, then
    ``--runtime`` picks ``defaults.<runtime>``, finally a single
    runtime default in the file picks itself.  Returns the matching
    raw dict (with comments + key order intact since it comes from
    :func:`load_devices`) or ``None`` when nothing matches.

    Distinct from :func:`_resolve_device` because the
    ``firmware_source`` / ``hardware`` fields aren't on the
    :class:`Device` dataclass — they live in the raw entry.
    """
    if not workspace.devices_yaml.is_file():
        return None
    data = load_devices(workspace.devices_yaml)
    if args.device_id is not None:
        return find_device(data, args.device_id)
    defaults = data.get("defaults") or {}
    runtime = getattr(args, "runtime", None)
    if runtime is not None:
        default_id = defaults.get(runtime)
        if default_id is not None:
            return find_device(data, default_id)
    candidates = [
        defaults.get("micropython"),
        defaults.get("circuitpython"),
    ]
    picks = [candidate for candidate in candidates if candidate]
    if len(picks) == 1:
        return find_device(data, picks[0])
    return None


def _resolve_device(workspace: WorkspaceLayout, args: argparse.Namespace) -> Device:
    """Construct a :class:`Device` for the selected entry in devices.yml."""
    if not workspace.devices_yaml.is_file():
        raise SystemExit(
            f"error: {workspace.devices_yaml} not found — run "
            "'add-device' to register a board first.",
        )
    from chumicro_deploy.config.default import load_devices_yml  # noqa: PLC0415

    return load_devices_yml(
        workspace.devices_yaml,
        device_id=args.device_id,
        runtime=args.runtime,
    )


# ---------------------------------------------------------------------------
# Implemented commands
# ---------------------------------------------------------------------------


def _cmd_setup(args: argparse.Namespace) -> int:
    """Install workspace dependencies and materialize template files.

    Runs ``pip install -e .`` in the workspace root when a
    ``pyproject.toml`` is present, then walks ``_templates/`` and
    creates any missing files at the workspace root (Decision 0038
    §5).  Idempotent — re-running is safe.
    """
    workspace = _resolve_workspace(args)
    pyproject = workspace.root / "pyproject.toml"
    if pyproject.is_file():
        print(f"setup: installing {workspace.root} (editable)")
        completed = subprocess.run(  # noqa: S603 — args fully controlled
            [sys.executable, "-m", "pip", "install", "-e", str(workspace.root)],
            check=False,
        )
        if completed.returncode != 0:
            return completed.returncode
    else:
        print(
            f"setup: no pyproject.toml at {workspace.root} — "
            "skipping editable install.",
        )
    from chumicro_workspace.template_apply import (  # noqa: PLC0415
        ApplyAction,
        materialize_templates,
    )

    report = materialize_templates(workspace.root)
    new_files = report.count(ApplyAction.MATERIALIZED)
    if new_files:
        print(f"setup: materialized {new_files} file(s) from _templates/")
        for path, action in report:
            if action == ApplyAction.MATERIALIZED:
                print(f"  {path}")
    return 0


def _cmd_init(args: argparse.Namespace) -> int:
    """Clone the workspace template into a target directory."""
    from chumicro_workspace.template_apply import (  # noqa: PLC0415
        DEFAULT_TEMPLATE_URL,
        ApplyAction,
        init,
    )

    template_url = args.template_url or DEFAULT_TEMPLATE_URL
    try:
        report = init(
            args.target,
            template_url=template_url,
            git_reference=args.git_reference,
            force=args.force,
        )
    except FileExistsError as error:
        print(f"init: {error}", file=sys.stderr)
        print(
            "Pass --force to clear the target directory and reclone.",
            file=sys.stderr,
        )
        return 1
    except RuntimeError as error:
        print(f"init: {error}", file=sys.stderr)
        return 2
    written = report.count(ApplyAction.WRITTEN)
    print(f"init: cloned {template_url} into {args.target} ({written} files)")
    print(f"next: cd {args.target} && python3 run.py setup")
    return 0


def _cmd_update(args: argparse.Namespace) -> int:
    """Re-flow tool-owned template files from the canonical upstream."""
    from chumicro_workspace.template_apply import (  # noqa: PLC0415
        DEFAULT_TEMPLATE_URL,
        ApplyAction,
    )
    from chumicro_workspace.template_apply import (
        update as apply_update,
    )

    workspace = _resolve_workspace(args)
    template_url = args.template_url or DEFAULT_TEMPLATE_URL
    try:
        report = apply_update(
            workspace.root,
            template_url=template_url,
            git_reference=args.git_reference,
        )
    except RuntimeError as error:
        print(f"update: {error}", file=sys.stderr)
        return 2
    refreshed = report.count(ApplyAction.REFRESHED)
    unchanged = report.count(ApplyAction.UNCHANGED)
    skipped = report.count(ApplyAction.SKIPPED)
    print(
        f"update: refreshed={refreshed} unchanged={unchanged} skipped={skipped}",
    )
    for path, action in report:
        print(f"  {action:>11}  {path}")
    return 0


def _validate_thing_name(name: str) -> None:
    """Reject thing names that won't survive ``import things.<name>.app``.

    Thing directories are imported as Python modules at deploy time
    (and inside the on-device boot shim), so the name has to be a
    valid identifier — no hyphens, no dots, no leading digits.
    Leading underscore is reserved for workspace-internal directories
    such as ``_template``; ``list_things`` filters those out, so a
    user-created ``_foo`` would be invisible to ``things``/``deploy``.
    """
    if not name:
        raise SystemExit("error: thing name must not be empty")
    if not name.isidentifier():
        raise SystemExit(
            f"error: thing name {name!r} is not a valid Python identifier "
            "— thing directories are imported as modules, so use "
            "snake_case (letters, digits, underscores; no hyphens, "
            "dots, or spaces; no leading digit).",
        )
    if name.startswith("_"):
        raise SystemExit(
            f"error: thing name {name!r} starts with '_' — leading "
            "underscore is reserved for workspace-internal directories "
            "(e.g. _template).",
        )
    if keyword.iskeyword(name):
        raise SystemExit(
            f"error: thing name {name!r} is a Python keyword.",
        )


def _cmd_new(args: argparse.Namespace) -> int:
    """Create ``things/<name>/`` by copying the ``things/_template/`` tree.

    The workstream design note is explicit (Phase 4a §"Open
    questions"): ``new`` is a ``cp -r`` convenience, not a code
    generator — no template variables, no post-copy edits.
    """
    _validate_thing_name(args.name)
    workspace = _resolve_workspace(args)
    template = workspace.things_dir / "_template"
    target = workspace.thing_dir(args.name)
    if not template.is_dir():
        raise SystemExit(
            f"error: template {template} not found — run "
            "`chumicro-workspace init` to clone the canonical template, "
            "or create `things/_template/` by hand.",
        )
    if target.exists():
        raise SystemExit(f"error: {target} already exists")
    shutil.copytree(template, target)
    print(f"new: created {target}")
    return 0


def _cmd_probe(args: argparse.Namespace) -> int:
    """Probe a board's runtime identity (delegates to chumicro-deploy)."""
    workspace = _resolve_workspace(args)
    device = _resolve_device(workspace, args)
    from chumicro_deploy import probe_device  # noqa: PLC0415

    info = probe_device(device)
    if info.implementation is None:
        print("probe: no implementation marker", file=sys.stderr)
        return 1
    print(f"runtime: {info.implementation.name}")
    print(f"version: {info.implementation.version}")
    print(f"machine: {info.implementation.machine}")
    if info.uid:
        print(f"uid: {info.uid}")
    return 0


def _cmd_discover(args: argparse.Namespace) -> int:
    """List serial ports the host can see (pyserial-backed)."""
    # pyserial ships as a chumicro-deploy dep so it's always present.
    from serial.tools import list_ports  # noqa: PLC0415

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
    import yaml  # noqa: PLC0415

    raw = yaml.safe_load(workspace.devices_yaml.read_text()) or {}
    devices = raw.get("devices", [])
    if not devices:
        print("devices: no entries")
        return 0
    for entry in devices:
        identifier = entry.get("id", "?")
        runtime = entry.get("runtime", "?")
        address = entry.get("address", "?")
        print(f"{identifier}\t{runtime}\t{address}")
    return 0


def _cmd_deploy(args: argparse.Namespace) -> int:
    """Deploy one or more things to a device.

    Single-thing default uses :func:`thing_directory_source` — the
    flat layout where the thing's files land at the device root.
    ``--import-graph`` ships only transitively-imported modules.
    ``--boot-shim`` ships under ``/lib/things/<name>/``; with multiple
    positional names + ``--boot-shim`` the things land side-by-side
    and ``switch`` can re-point ``/active.py`` without re-flashing.
    """
    workspace = _resolve_workspace(args)
    names: list[str] = list(args.names)
    if args.import_graph and args.boot_shim:
        print(
            "deploy: --import-graph and --boot-shim are mutually exclusive.",
            file=sys.stderr,
        )
        return 2
    if len(names) > 1 and not args.boot_shim:
        print(
            "deploy: deploying multiple things at once requires --boot-shim "
            "(the boot-shim layout puts each thing under /lib/things/<name>/ "
            "where they don't collide).",
            file=sys.stderr,
        )
        return 2
    if args.active is not None and not args.boot_shim:
        print(
            "deploy: --active only applies with --boot-shim.",
            file=sys.stderr,
        )
        return 2
    thing_dirs: list[Path] = []
    for name in names:
        thing_dir = workspace.thing_dir(name)
        if not thing_dir.is_dir():
            raise SystemExit(f"error: thing {thing_dir} not found")
        thing_dirs.append(thing_dir)
    device = _resolve_device(workspace, args)
    from chumicro_deploy import Deployer  # noqa: PLC0415

    if args.boot_shim:
        if len(thing_dirs) == 1:
            source = thing_boot_source(
                thing_dirs[0],
                workspace=workspace,
                entrypoint_filename=device.effective_entrypoint,
            )
        else:
            active = args.active if args.active is not None else names[0]
            if active not in names:
                print(
                    f"deploy: --active {active!r} is not one of the deployed "
                    f"things ({names}).",
                    file=sys.stderr,
                )
                return 2
            source = multi_thing_boot_source(
                thing_dirs,
                workspace=workspace,
                active_thing_name=active,
                entrypoint_filename=device.effective_entrypoint,
            )
    elif args.import_graph:
        device_entrypoint = args.entrypoint or f"/{device.effective_entrypoint}"
        source = thing_import_graph_source(
            thing_dirs[0],
            workspace=workspace,
            entrypoint_filename=device.effective_entrypoint,
            device_entrypoint=device_entrypoint,
        )
    else:
        source = thing_directory_source(
            thing_dirs[0],
            workspace_yaml=workspace.workspace_yaml,
            secrets_yaml=workspace.secrets_yaml,
            entrypoint=args.entrypoint or f"/{device.effective_entrypoint}",
        )
    result = Deployer(device).deploy(source)
    if result.execute_output:
        print(result.execute_output, end="")
    if not result.success:
        if result.traceback:
            print(f"\n--- traceback ---\n{result.traceback}", file=sys.stderr)
        return 1
    return 0


def _cmd_switch(args: argparse.Namespace) -> int:
    """Switch which thing is active without re-shipping payloads.

    Builds the merged runtime config msgpack for the named thing on
    the host, then ships only ``/code.py`` (or ``/main.py``) +
    ``/active.py`` + ``/runtime_config.msgpack``.  The thing payloads
    under ``/lib/things/<name>/`` stay on flash from the prior
    multi-thing :func:`_cmd_deploy`.

    Fast: three small files instead of the whole stack.  Requires
    that the named thing was included in a prior multi-thing deploy —
    if not, the device boots into a thing whose payload doesn't exist
    and ``workspace_runtime.boot()`` raises ``WorkspaceBootError``.
    """
    workspace = _resolve_workspace(args)
    thing_dir = workspace.thing_dir(args.name)
    if not thing_dir.is_dir():
        raise SystemExit(f"error: thing {thing_dir} not found")
    device = _resolve_device(workspace, args)
    from chumicro_deploy import Deployer  # noqa: PLC0415

    source = switch_source(
        thing_dir,
        workspace=workspace,
        entrypoint_filename=device.effective_entrypoint,
    )
    result = Deployer(device).deploy(source)
    if result.execute_output:
        print(result.execute_output, end="")
    if not result.success:
        if result.traceback:
            print(f"\n--- traceback ---\n{result.traceback}", file=sys.stderr)
        return 1
    return 0


def _cmd_things(args: argparse.Namespace) -> int:
    """List the things defined in the workspace under ``things/``.

    Local-only: lists ``things/<name>/`` directories filtered by
    :meth:`WorkspaceLayout.list_things` (skips ``_template`` and
    leading ``.`` / ``_`` names).  An on-device variant that probes
    ``/lib/things/`` for installed payloads is a follow-on once the
    REPL one-shot pattern lands as a public helper.
    """
    workspace = _resolve_workspace(args)
    names = workspace.list_things()
    if not names:
        print("(no things in this workspace)")
        return 0
    for name in names:
        print(name)
    return 0


def _cmd_test(args: argparse.Namespace) -> int:
    """Run the workspace's pytest suite.

    Shells out to ``pytest`` so users get the standard pytest UX
    (``-k``, ``-x``, ``-v``, etc.) without re-implementing argument
    forwarding.  Extra args after ``--`` are passed through verbatim.
    """
    workspace = _resolve_workspace(args)
    completed = subprocess.run(  # noqa: S603 — args fully controlled
        [sys.executable, "-m", "pytest", *args.pytest_args],
        cwd=workspace.root,
        check=False,
    )
    return completed.returncode


def _cmd_repl(args: argparse.Namespace) -> int:
    """Open an interactive REPL on the selected board."""
    workspace = _resolve_workspace(args)
    device = _resolve_device(workspace, args)
    if args.tail is not None:
        from chumicro_repl import tail  # noqa: PLC0415

        return int(tail(
            device,
            args.tail,
            fail_on_traceback=args.fail_on_traceback,
            output=sys.stdout,
        ))
    from chumicro_repl import interactive  # noqa: PLC0415

    return interactive(device)


def _cmd_install_firmware(args: argparse.Namespace) -> int:
    """Download + flash firmware onto the selected board.

    ``upgrade-firmware`` is registered as an alias of this command —
    flashing the same URL onto a board that already has firmware *is*
    an upgrade, so the implementation does not branch.

    ``--url`` is optional: when omitted, the URL is derived via
    :func:`chumicro_workspace.derive_firmware_url` from the device
    entry's ``hardware.firmware_source`` (custom), ``hardware.board_id``
    (CP S3 listing → latest stable), or ``hardware.machine`` (MP
    curated map).  Unresolvable cases surface a precise message + exit
    2 so the user can paste an explicit URL into ``--url`` (or the
    entry's ``hardware.firmware_source``).
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
        except UnresolvableFirmwareError as exception:
            print(f"install-firmware: {exception}", file=sys.stderr)
            return 2
        print(f"install-firmware: resolved {firmware_url}")

    from chumicro_deploy import flash_firmware  # noqa: PLC0415

    flash_firmware(
        firmware_url,
        device,
        reflash_method=args.method,
        bootloader_drive_path=args.bootloader_drive_path,
        interactive=not args.non_interactive,
        erase_flash=args.erase,
        flash_offset=args.offset,
    )
    return 0


# ---------------------------------------------------------------------------
# Stubs — register the surface; implementation lands in a later slice
# ---------------------------------------------------------------------------


def _stub(slice_or_phase: str) -> int:
    """Emit a uniform "not implemented yet" message and return exit-code 2."""
    print(
        f"not implemented yet — landing in {slice_or_phase}.  "
        "See plans/workstreams/project-workspace.md.",
        file=sys.stderr,
    )
    return 2


def _cmd_add_device(args: argparse.Namespace) -> int:
    """Probe a board + register it in devices.yml.

    Builds a fresh entry by probing the supplied address: ``runtime``
    + ``hardware.uid`` + ``hardware.machine`` come from
    :func:`chumicro_deploy.probe_device`; ``address`` rides through
    as-is.  Re-running with the same id triggers a re-probe and is
    blocked unless ``--force`` is passed (the typical second invocation
    is "I swapped boards on this id" — make the user confirm).
    """
    workspace = _resolve_workspace(args)
    from chumicro_deploy import Device, probe_device  # noqa: PLC0415

    probe_device_obj = Device(transport=args.runtime, address=args.address)
    try:
        info = probe_device(probe_device_obj)
    except Exception as exception:  # noqa: BLE001 — onboarding diagnoses every failure
        diagnosis = detect_board_state(probe_device_obj)
        print(
            f"add-device: probe failed ({type(exception).__name__}: {exception}).",
            file=sys.stderr,
        )
        for line in diagnosis.next_steps:
            print(f"  {line}", file=sys.stderr)
        return 1
    if info.implementation is None:
        diagnosis = detect_board_state(probe_device_obj)
        if diagnosis.state is BoardState.UF2_BOOTLOADER:
            print(
                "add-device: board is in UF2 bootloader, not REPL — "
                "install firmware first.",
                file=sys.stderr,
            )
        else:
            print("add-device: probe did not return implementation marker", file=sys.stderr)
        for line in diagnosis.next_steps:
            print(f"  {line}", file=sys.stderr)
        return 1

    firmware_version = info.implementation.version
    support = check_firmware_supported(info.implementation)

    data = load_devices(workspace.devices_yaml)
    hardware: dict[str, str] = {}
    if info.uid:
        hardware["uid"] = info.uid
    if info.implementation.machine:
        hardware["machine"] = info.implementation.machine
    if info.board_id:
        hardware["board_id"] = info.board_id

    try:
        add_device(
            data,
            device_id=args.id,
            runtime=info.implementation.name,
            address=args.address,
            hardware=hardware or None,
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
            update_device_hardware(data, args.id, hardware, force=True)
        except HardwareOverwriteError as exception:
            print(f"add-device: {exception}", file=sys.stderr)
            return 1

    dump_devices(data, workspace.devices_yaml)
    print(f"add-device: registered {args.id} ({info.implementation.name})")
    if support.status is not FirmwareSupportStatus.SUPPORTED:
        print(
            f"add-device: warning — {info.implementation.name} "
            f"firmware compatibility:",
            file=sys.stderr,
        )
        for line in explain_firmware_support(support):
            print(f"  {line}", file=sys.stderr)
    return 0


def _cmd_rename(args: argparse.Namespace) -> int:
    """Rename a thing directory or a device id.

    Two modes (mutually exclusive): ``--thing OLD NEW`` does a
    ``mv things/OLD things/NEW``; ``--device OLD NEW`` rewrites the
    devices.yml entry id + every reference to it under ``defaults:``.
    """
    workspace = _resolve_workspace(args)

    if (args.thing is None) == (args.device is None):
        print(
            "rename: pass exactly one of --thing OLD NEW or --device OLD NEW",
            file=sys.stderr,
        )
        return 2

    if args.thing is not None:
        old_name, new_name = args.thing
        old_path = workspace.thing_dir(old_name)
        new_path = workspace.thing_dir(new_name)
        if not old_path.is_dir():
            print(f"rename: thing {old_path} not found", file=sys.stderr)
            return 1
        if new_path.exists():
            print(f"rename: {new_path} already exists", file=sys.stderr)
            return 1
        old_path.rename(new_path)
        print(f"rename: {old_name} → {new_name}")
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


def _cmd_sim(_args: argparse.Namespace) -> int:
    """Run a thing in CPython simulation."""
    return _stub("Phase 4a (sim runner — slice TBD after Slices 3-7)")


def _cmd_env(_args: argparse.Namespace) -> int:  # noqa: CHU001 — workstream-spec command name
    """List / show workspace environments."""
    return _stub("Phase 4a (environments — slice TBD after Slices 3-7)")


def _cmd_use(_args: argparse.Namespace) -> int:
    """Switch the active workspace environment."""
    return _stub("environments — not implemented yet")


def _cmd_sync(_args: argparse.Namespace) -> int:
    """Re-apply the workspace template (superseded by `update`)."""
    return _stub("superseded by `chumicro-workspace update` (Decision 0038)")


def _cmd_upgrade(_args: argparse.Namespace) -> int:
    """Pin to a newer workspace template version (superseded by `update --ref`)."""
    return _stub(
        "superseded by `chumicro-workspace update --ref <ref>` (Decision 0038)",
    )


# ---------------------------------------------------------------------------
# Parser construction
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser with every command registered."""
    parser = argparse.ArgumentParser(
        prog="chumicro-workspace",
        description=(
            "Host-side dispatcher for ChuMicro project workspaces — "
            "deploy things, probe boards, open REPLs, and manage "
            "devices.yml from one CLI."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ----- setup ---------------------------------------------------------
    setup_parser = subparsers.add_parser(
        "setup",
        help="Install dependencies and materialize template files.",
    )
    _add_workspace_arg(setup_parser)
    setup_parser.set_defaults(func=_cmd_setup)

    # ----- init ----------------------------------------------------------
    init_parser = subparsers.add_parser(
        "init",
        help="Clone the workspace template into a target directory.",
    )
    init_parser.add_argument(
        "target",
        type=Path,
        help="Workspace directory to create.",
    )
    init_parser.add_argument(
        "--from",
        dest="template_url",
        default=None,
        help="Template git URL (defaults to the canonical ChuMicro template).",
    )
    init_parser.add_argument(
        "--ref",
        dest="git_reference",
        default=None,
        help="Branch or tag to clone (defaults to the remote's HEAD).",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Clear the target before cloning if non-empty.",
    )
    init_parser.set_defaults(func=_cmd_init)

    # ----- update --------------------------------------------------------
    update_parser = subparsers.add_parser(
        "update",
        help=(
            "Re-flow tool-owned template files from upstream. "
            "User-owned files are skipped."
        ),
    )
    _add_workspace_arg(update_parser)
    update_parser.add_argument(
        "--from",
        dest="template_url",
        default=None,
        help="Template git URL (defaults to the canonical ChuMicro template).",
    )
    update_parser.add_argument(
        "--ref",
        dest="git_reference",
        default=None,
        help="Branch or tag to fetch (defaults to the remote's HEAD).",
    )
    update_parser.set_defaults(func=_cmd_update)

    # ----- new -----------------------------------------------------------
    new_parser = subparsers.add_parser(
        "new",
        help="Create things/<name>/ by copying the _template tree.",
    )
    _add_workspace_arg(new_parser)
    new_parser.add_argument(
        "name",
        help="Name of the new thing (becomes things/<name>/).",
    )
    new_parser.set_defaults(func=_cmd_new)

    # ----- add-device ----------------------------------------------------
    add_device_parser = subparsers.add_parser(
        "add-device",
        help="Probe a board and register it in devices.yml.",
    )
    _add_workspace_arg(add_device_parser)
    add_device_parser.add_argument(
        "id",
        help="User-friendly device id (e.g. 'back-porch-mp').",
    )
    add_device_parser.add_argument(
        "--address",
        required=True,
        help="Serial port path of the connected board.",
    )
    add_device_parser.add_argument(
        "--runtime",
        choices=("circuitpython", "micropython"),
        required=True,
        help="Runtime to probe — picks the right Device facade for probe_device.",
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
            "Overwrite an existing entry with this id — refreshes the "
            "address and hardware-once fields from the live probe."
        ),
    )
    add_device_parser.set_defaults(func=_cmd_add_device)

    # ----- probe ---------------------------------------------------------
    probe_parser = subparsers.add_parser(
        "probe",
        help="Print the runtime identity reported by the selected board.",
    )
    _add_workspace_arg(probe_parser)
    _add_device_selector(probe_parser)
    probe_parser.set_defaults(func=_cmd_probe)

    # ----- discover ------------------------------------------------------
    discover_parser = subparsers.add_parser(
        "discover",
        help="List the serial ports the host currently sees.",
    )
    discover_parser.set_defaults(func=_cmd_discover)

    # ----- devices -------------------------------------------------------
    devices_parser = subparsers.add_parser(
        "devices",
        help="Print every entry in devices.yml.",
    )
    _add_workspace_arg(devices_parser)
    devices_parser.set_defaults(func=_cmd_devices)

    # ----- deploy --------------------------------------------------------
    deploy_parser = subparsers.add_parser(
        "deploy",
        help="Deploy one or more things — app code + merged runtime config msgpack.",
    )
    _add_workspace_arg(deploy_parser)
    _add_device_selector(deploy_parser)
    deploy_parser.add_argument(
        "names",
        nargs="+",
        metavar="name",
        help=(
            "Name(s) of things under things/ to deploy.  Multiple names "
            "require --boot-shim (the layout that puts each thing under "
            "/lib/things/<name>/)."
        ),
    )
    deploy_parser.add_argument(
        "--active",
        default=None,
        help=(
            "Multi-thing only: which deployed thing /active.py points "
            "at (defaults to the first positional name).  Use `switch` "
            "later to re-point without re-flashing."
        ),
    )
    deploy_parser.add_argument(
        "--entrypoint",
        default=None,
        help=(
            "Override the on-device entrypoint path.  Defaults to "
            "/code.py on CircuitPython and /main.py on MicroPython."
        ),
    )
    deploy_parser.add_argument(
        "--import-graph",
        action="store_true",
        help=(
            "AST-walk the entrypoint and ship only transitively-"
            "imported modules instead of the full thing directory.  "
            "Reads workspace.yml's library_sources: for overrides."
        ),
    )
    deploy_parser.add_argument(
        "--boot-shim",
        action="store_true",
        help=(
            "Ship the thing under /lib/things/<name>/ + write a "
            "fixed code.py shim + active.py + workspace_runtime "
            "payload (Decision 0029 §3).  app.py must export run().  "
            "Multiple positional names land side-by-side; use `switch` "
            "to re-point /active.py later without re-flashing."
        ),
    )
    deploy_parser.set_defaults(func=_cmd_deploy)

    # ----- switch --------------------------------------------------------
    switch_parser = subparsers.add_parser(
        "switch",
        help=(
            "Re-point /active.py at a different thing already deployed "
            "via `deploy --boot-shim a b c` (no payload re-flash)."
        ),
    )
    _add_workspace_arg(switch_parser)
    _add_device_selector(switch_parser)
    switch_parser.add_argument(
        "name",
        help="Name of the installed thing to make active.",
    )
    switch_parser.set_defaults(func=_cmd_switch)

    # ----- things --------------------------------------------------------
    things_parser = subparsers.add_parser(
        "things",
        help="List the things defined under the workspace's things/ tree.",
    )
    _add_workspace_arg(things_parser)
    things_parser.set_defaults(func=_cmd_things)

    # ----- sim -----------------------------------------------------------
    sim_parser = subparsers.add_parser(
        "sim",
        help="Run a thing in CPython simulation (planned, not yet shipped).",
    )
    _add_workspace_arg(sim_parser)
    sim_parser.set_defaults(func=_cmd_sim)

    # ----- test ----------------------------------------------------------
    test_parser = subparsers.add_parser(
        "test",
        help="Run pytest in the workspace root.  Extra args pass through.",
    )
    _add_workspace_arg(test_parser)
    test_parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Args forwarded verbatim to pytest (place after `--`).",
    )
    test_parser.set_defaults(func=_cmd_test)

    # ----- repl ----------------------------------------------------------
    repl_parser = subparsers.add_parser(
        "repl",
        help="Open an interactive REPL on the selected board.",
    )
    _add_workspace_arg(repl_parser)
    _add_device_selector(repl_parser)
    repl_parser.add_argument(
        "--tail",
        type=float,
        default=None,
        metavar="SECONDS",
        help="Run in tail mode for SECONDS instead of the interactive TUI.",
    )
    repl_parser.add_argument(
        "--no-fail-on-traceback",
        dest="fail_on_traceback",
        action="store_false",
        default=True,
        help="Tail mode only: do not exit non-zero on a detected traceback.",
    )
    repl_parser.set_defaults(func=_cmd_repl)

    # ----- env -----------------------------------------------------------
    env_parser = subparsers.add_parser(
        "env",
        help="List / show workspace environments (planned).",
    )
    _add_workspace_arg(env_parser)
    env_parser.set_defaults(func=_cmd_env)

    # ----- use -----------------------------------------------------------
    use_parser = subparsers.add_parser(
        "use",
        help="Switch the active workspace environment (planned).",
    )
    _add_workspace_arg(use_parser)
    use_parser.set_defaults(func=_cmd_use)

    # ----- rename --------------------------------------------------------
    rename_parser = subparsers.add_parser(
        "rename",
        help="Rename a thing directory or a device id.",
    )
    _add_workspace_arg(rename_parser)
    rename_target = rename_parser.add_mutually_exclusive_group(required=True)
    rename_target.add_argument(
        "--thing",
        nargs=2,
        metavar=("OLD", "NEW"),
        default=None,
        help="Rename things/OLD/ to things/NEW/.",
    )
    rename_target.add_argument(
        "--device",
        nargs=2,
        metavar=("OLD", "NEW"),
        default=None,
        help="Rename a devices.yml entry id (also rewrites defaults: references).",
    )
    rename_parser.set_defaults(func=_cmd_rename)

    # ----- install-firmware ----------------------------------------------
    install_firmware_parser = subparsers.add_parser(
        "install-firmware",
        help="Download + flash firmware onto the selected board.",
    )
    _add_workspace_arg(install_firmware_parser)
    _add_device_selector(install_firmware_parser)
    _add_firmware_args(install_firmware_parser)
    install_firmware_parser.set_defaults(func=_cmd_install_firmware)

    # ----- upgrade-firmware ----------------------------------------------
    upgrade_firmware_parser = subparsers.add_parser(
        "upgrade-firmware",
        help="Alias of install-firmware — same flash flow.",
    )
    _add_workspace_arg(upgrade_firmware_parser)
    _add_device_selector(upgrade_firmware_parser)
    _add_firmware_args(upgrade_firmware_parser)
    upgrade_firmware_parser.set_defaults(func=_cmd_install_firmware)

    # ----- sync ----------------------------------------------------------
    sync_parser = subparsers.add_parser(
        "sync",
        help="Deprecated — superseded by `update`.",
    )
    _add_workspace_arg(sync_parser)
    sync_parser.set_defaults(func=_cmd_sync)

    # ----- upgrade -------------------------------------------------------
    upgrade_parser = subparsers.add_parser(
        "upgrade",
        help="Deprecated — superseded by `update --ref <ref>`.",
    )
    _add_workspace_arg(upgrade_parser)
    upgrade_parser.set_defaults(func=_cmd_upgrade)

    return parser


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
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Fail instead of prompting when bootloader entry needs help.",
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    """Parse *argv* and dispatch to the selected command.

    Returns the process exit code.  Stub commands return 2 so CI /
    scripts can distinguish "not implemented yet" from runtime errors.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
