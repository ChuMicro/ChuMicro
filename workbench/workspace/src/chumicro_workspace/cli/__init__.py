"""``chumicro-workspace`` command dispatch.

Thin wrapper over the public ``chumicro_workspace`` /
``chumicro_deploy`` / ``chumicro_repl`` APIs.  Workspace template
repos vendor a tiny ``run.py`` shim that simply calls
:func:`main`; every command the workspace user invokes
(``python run.py deploy back-porch``, ``python run.py repl``, etc.)
routes through this dispatcher.

Commands are shipped at three depths:

* **Implemented** — full behavior wired to the underlying library
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
import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from chumicro_deploy import flash_firmware
from chumicro_deploy.firmware_url import (
    UnresolvedFirmwareError,
    derive_firmware_url,
)

from chumicro_workspace.boot_shim import project_boot_source
from chumicro_workspace.cli._common import (
    _add_device_selector,
    _add_non_interactive_arg,
    _add_workspace_arg,
    _emit_failure_hints,
    _find_devices_yml_entry_for_args,
    _resolve_device,
    _resolve_project_name,
    _resolve_workspace,
)
from chumicro_workspace.cli.bootstrap import (
    _add_bootstrap_parser,
)
from chumicro_workspace.cli.bootstrap import (
    _cmd_bootstrap as _cmd_bootstrap,
)
from chumicro_workspace.cli.bootstrap import (
    _resolve_bootstrap_device_id as _resolve_bootstrap_device_id,
)
from chumicro_workspace.cli.bootstrap import (
    _resolve_bootstrap_port as _resolve_bootstrap_port,
)
from chumicro_workspace.cli.deploy import (
    _add_deploy_parser,
    _add_projects_parser,
    _make_deploy_runner,
)
from chumicro_workspace.cli.devices import (
    _add_devices_parsers,
    _add_rename_parser,
)
from chumicro_workspace.cli.devices import (
    _suggest_add_device_id as _suggest_add_device_id,
)
from chumicro_workspace.cli.devices import (
    _suggest_device_id as _suggest_device_id,
)
from chumicro_workspace.cli.examples import (
    DEMO_PAYLOAD as DEMO_PAYLOAD,
)
from chumicro_workspace.cli.examples import (
    DEPLOY_EXAMPLE_EXIT_DEPLOY_FAILED as DEPLOY_EXAMPLE_EXIT_DEPLOY_FAILED,
)
from chumicro_workspace.cli.examples import (
    DEPLOY_EXAMPLE_EXIT_NO_DEVICE_REGISTERED as DEPLOY_EXAMPLE_EXIT_NO_DEVICE_REGISTERED,
)
from chumicro_workspace.cli.examples import (
    DEPLOY_EXAMPLE_EXIT_NO_PYTHON_RUNTIME as DEPLOY_EXAMPLE_EXIT_NO_PYTHON_RUNTIME,
)
from chumicro_workspace.cli.examples import (
    DEPLOY_EXAMPLE_EXIT_PRECHECK_FAILED as DEPLOY_EXAMPLE_EXIT_PRECHECK_FAILED,
)
from chumicro_workspace.cli.examples import (
    DEPLOY_EXAMPLE_EXIT_WIZARD_CANCELLED as DEPLOY_EXAMPLE_EXIT_WIZARD_CANCELLED,
)
from chumicro_workspace.cli.examples import (
    _add_demo_parser,
    _add_deploy_example_parser,
)
from chumicro_workspace.cli.examples import (
    _cmd_demo as _cmd_demo,
)
from chumicro_workspace.cli.examples import (
    _resolve_deploy_example_modes as _resolve_deploy_example_modes,
)
from chumicro_workspace.cli.health import _add_health_parsers
from chumicro_workspace.cli.quality import (
    _add_quality_parsers,
)
from chumicro_workspace.cli.quality import (
    _cmd_lint as _cmd_lint,
)
from chumicro_workspace.cli.quality import (
    _cmd_test as _cmd_test,
)
from chumicro_workspace.cli.setup import _add_setup_parsers
from chumicro_workspace.config_manifest import (
    ConfigManifestError,
    aggregate_manifests,
    find_library_roots,
    read_manifest,
    validate_runtime_config,
)
from chumicro_workspace.deploy_source import find_project_config
from chumicro_workspace.import_graph import build_search_paths
from chumicro_workspace.install_libraries import (
    EXPERIMENTAL_BUNDLE_REPO,
    STABLE_BUNDLE_REPO,
    build_circup_command,
    build_mip_commands,
    discover_chumicro_imports,
    import_name_to_package,
)
from chumicro_workspace.pipeline import compose_runtime_config

# ---------------------------------------------------------------------------
# Implemented commands
# ---------------------------------------------------------------------------


def _cmd_dump_config(args: argparse.Namespace) -> int:
    """Print the merged runtime config a project would receive on deploy.

    Runs the deploy-time pipeline up to (but not through) the msgpack
    write — ``workspace.yml`` defaults + project config deep-merged —
    then pretty-prints the result.  Lets users see exactly what their
    on-device ``chumicro_config.runtime`` will read without actually
    deploying.

    Useful for: debugging which layer a key landed in after the merge,
    inspecting the shape before adding consumers on the device,
    confirming that gitignored credential overrides flowed through.

    Output format defaults to JSON (sorted keys, indent 2) for
    diffability; ``--repr`` switches to ``repr()`` for cases where
    the raw Python types matter (e.g. seeing ``bytes`` vs ``str``).
    """
    workspace = _resolve_workspace(args)
    project_dir = workspace.project_dir(_resolve_project_name(workspace, args.project))
    if not project_dir.is_dir():
        raise SystemExit(f"error: project {project_dir} not found")

    try:
        project_config_path = find_project_config(project_dir)
    except FileNotFoundError:
        project_config_path = None

    resolved = compose_runtime_config(
        secrets_toml=workspace.secrets_toml,
        project_config=project_config_path,
    )

    if args.repr:
        print(repr(resolved))
    else:
        print(json.dumps(resolved, indent=2, sort_keys=True, default=repr))
    return 0


def _cmd_config_validate(args: argparse.Namespace) -> int:
    """Validate the merged runtime config for one or more projects.

    Runs ``compose_runtime_config`` against each named project (or all
    projects when none are named), unions the manifests of every
    library reachable from the import graph, and validates the merged
    flat dict against that union.

    Exits 0 when every project validates; exits 1 with a per-project
    summary when any fail.  Designed for CI: a fast pre-deploy gate
    that surfaces missing required keys with the exact dotted name
    the runtime accessor will request.
    """
    workspace = _resolve_workspace(args)
    project_names = (
        list(args.projects) if args.projects else workspace.list_projects()
    )
    if not project_names:
        print(
            "config-validate: no projects under "
            f"{workspace.projects_dir} — nothing to validate.",
        )
        return 0

    search_paths = list(build_search_paths(workspace))
    library_roots = find_library_roots(search_paths)
    union = aggregate_manifests(read_manifest(root) for root in library_roots)
    if union is None:
        print(
            "config-validate: no library declares a "
            "[tool.chumicro.config] manifest — nothing to validate against.",
        )
        return 0

    failed: list[tuple[str, str]] = []
    passed: list[str] = []
    for raw_name in project_names:
        project_name = _resolve_project_name(workspace, raw_name)
        project_dir = workspace.project_dir(project_name)
        if not project_dir.is_dir():
            failed.append((project_name, f"project directory not found: {project_dir}"))
            continue
        try:
            project_config_path = find_project_config(project_dir)
        except FileNotFoundError:
            project_config_path = None
        try:
            resolved = compose_runtime_config(
                secrets_toml=workspace.secrets_toml,
                project_config=project_config_path,
            )
            validate_runtime_config(resolved, union)
        except ConfigManifestError as error:
            failed.append((project_name, str(error)))
            continue
        except FileNotFoundError as error:
            failed.append((project_name, f"config source missing: {error}"))
            continue
        passed.append(project_name)

    for name in passed:
        print(f"config-validate: OK {name}")
    for name, message in failed:
        print(f"config-validate: FAIL {name}")
        for line in message.splitlines():
            print(f"  {line}")
    return 1 if failed else 0


#: Default tail-window duration (seconds) when ``repl <project>`` is
#: invoked without an explicit ``--tail SECONDS`` value.  Picked to
#: cover the common "deploy a heartbeat project, watch a few cycles
#: print, exit clean" inner-loop pattern; users with long boot
#: sequences can override.
_DEFAULT_REPL_TAIL_SECONDS: float = 30.0


def _resolve_repl_mode(requested: str, *, stdin: object) -> str:
    """Pick the actual REPL mode given the user's *requested* value.

    *requested* is ``"auto"`` / ``"line"`` / ``"passthrough"``.  Auto
    picks ``line`` when stdin is a TTY (an interactive terminal) and
    ``passthrough`` otherwise — line mode requires interactive input
    (``prompt_toolkit`` reads from the terminal), so falling back to
    passthrough lets the same command work under CI / piped stdin.

    *stdin* is injected so tests can verify both branches without
    monkey-patching ``sys.stdin``.
    """
    if requested != "auto":
        return requested
    isatty = getattr(stdin, "isatty", None)
    return "line" if (callable(isatty) and isatty()) else "passthrough"


def _cmd_repl(args: argparse.Namespace) -> int:
    """Open an interactive REPL, tail output, or deploy-then-tail.

    Three modes:

    * ``repl`` — interactive REPL on the selected board.
    * ``repl --tail SECONDS`` — capture the next *SECONDS* of REPL
      output, exit cleanly.
    * ``repl <project> [--tail SECONDS]`` — deploy *project* to the
      board first, then tail.  Combines what used to be
      ``deploy <project> && repl --tail`` into one command.  When
      ``--tail`` is omitted with a positional, defaults to
      :data:`_DEFAULT_REPL_TAIL_SECONDS`.

    *project* accepts bare / slash / dotted forms — same shape as
    ``deploy``.  The deploy uses the workspace-runtime boot-shim
    layout (``project_boot_source``); for flat-layout deploys, run
    ``deploy`` and ``repl --tail`` separately.
    """
    workspace = _resolve_workspace(args)
    device = _resolve_device(workspace, args)

    if args.project is not None:
        resolved_name = _resolve_project_name(workspace, args.project)
        project_dir = workspace.project_dir(resolved_name)
        if not project_dir.is_dir():
            raise SystemExit(f"error: project {project_dir} not found")
        source = project_boot_source(
            project_dir,
            workspace=workspace,
            entrypoint_filename=device.effective_entrypoint,
        )
        print(f"repl: deploying {resolved_name} ...")
        deleted: list[str] = []
        deploy_result = _make_deploy_runner(
            device, non_interactive=args.non_interactive,
        ).deploy_diff(
            source,
            on_file_deleted=deleted.append,
        )
        for stale_path in deleted:
            print(f"repl: removed stale {stale_path}")
        if deploy_result.execute_output:
            print(deploy_result.execute_output, end="")
        if not deploy_result.success:
            _emit_failure_hints(deploy_result)
            return 1
        tail_seconds = (
            args.tail if args.tail is not None else _DEFAULT_REPL_TAIL_SECONDS
        )
        from chumicro_repl import tail  # noqa: PLC0415

        return int(tail(
            device,
            tail_seconds,
            fail_on_traceback=args.fail_on_traceback,
            output=sys.stdout,
        ))

    if args.tail is not None:
        from chumicro_repl import tail  # noqa: PLC0415

        return int(tail(
            device,
            args.tail,
            fail_on_traceback=args.fail_on_traceback,
            output=sys.stdout,
        ))

    mode = _resolve_repl_mode(args.mode, stdin=sys.stdin)
    if mode == "line":
        from chumicro_repl import interactive_line  # noqa: PLC0415

        def open_session() -> int:
            return interactive_line(device)
    else:
        from chumicro_repl import interactive  # noqa: PLC0415

        def open_session() -> int:
            return interactive(device)

    if args.non_interactive:
        return open_session()

    from chumicro_repl import coached_session_start  # noqa: PLC0415

    return coached_session_start(open_session)


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
        except UnresolvedFirmwareError as exception:
            print(f"install-firmware: {exception}", file=sys.stderr)
            return 2
        print(f"install-firmware: resolved {firmware_url}")

    flash_fn = args._env.flash_firmware_fn
    if flash_fn is None:
        flash_fn = flash_firmware

    flash_fn(
        firmware_url,
        device,
        reflash_method=args.method,
        bootloader_drive_path=args.bootloader_drive_path,
        interactive=not args.non_interactive,
        erase_flash=args.erase,
        flash_offset=args.offset,
    )
    return 0


def _cmd_reset_board(args: argparse.Namespace) -> int:
    """Erase the device's user filesystem and leave it idle.

    Standalone counterpart to ``deploy --wipe`` — same destructive
    primitive (:meth:`chumicro_deploy.TransportProtocol.wipe_filesystem`)
    without coupling the wipe to a follow-up redeploy.  Used to recover
    a board whose flash filled up with stage residue (LittleFS
    metadata + wear-leveling artifacts that ``os.remove`` cannot
    reclaim — see the :meth:`wipe_filesystem` docstring for the
    per-runtime recipe matrix).

    Destructive — every user file the runtime can see is gone after
    this returns, including out-of-scope files like ``settings.toml``,
    hand-edited ``boot.py``, and uploaded assets.  Gated behind
    ``--yes`` to avoid wiping a board on a typoed device id.

    No-op (with a printed note) when the device's effective deploy
    mode is RAM / mount — those modes never wrote to flash so there's
    nothing persistent to wipe.
    """
    workspace = _resolve_workspace(args)
    device = _resolve_device(workspace, args)

    transport = device.create_transport()
    target = f"{device.transport}@{device.address}"
    if transport.mode in ("ram", "mount"):
        print(
            f"reset-board: {target} is configured for {transport.mode} "
            "mode — nothing in flash to wipe.  Re-run on a board whose "
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
    transport.connect()
    try:
        transport.wipe_filesystem()
    finally:
        transport.disconnect()
    print(f"reset-board: {target} filesystem wiped.")
    return 0


def _cmd_install_libraries(args: argparse.Namespace) -> int:
    """Install chumicro libraries onto a device via circup (CP) / mip (MP).

    Regular-mode counterpart to dev-mode's ``library_sources:`` auto-sync
    (gap #4 of the workspace-template dev-and-regular-mode-gaps audit).
    AST-walks the project's source tree to discover every
    ``chumicro_<name>`` top-level import, then shells out to the right
    runtime tool to fetch + install those packages from the published
    bundle:

    * **CircuitPython** — one ``circup install <pkg-list>`` invocation
      against the bundle the user has already registered (pre-flight
      check warns if no chumicro bundle is in circup's bundle list).
      The CIRCUITPY drive is auto-detected; pass ``--drive-path`` to
      pin a specific mount when multiple boards share a host.
    * **MicroPython** — one ``mpremote connect <addr> mip install
      github:ChuMicro/<bundle>/<package>`` per chumicro library
      (mip doesn't take a list).

    ``--experimental`` swaps the bundle URL to
    ``ChuMicro-Bundle-Experimental`` (mip), or surfaces a hint for
    the equivalent ``circup bundle-add`` command (circup needs the
    bundle pre-registered).

    ``--dry-run`` prints the commands that would run but does not
    execute them — useful for "what would this do on my air-gapped
    rig?" inspection or for paste-into-elsewhere when host doesn't
    have circup / mpremote installed.
    """
    workspace = _resolve_workspace(args)
    project_name = _resolve_project_name(workspace, args.project)
    project_dir = workspace.project_dir(project_name)
    if not project_dir.is_dir():
        print(
            f"install-libraries: project {project_dir} not found",
            file=sys.stderr,
        )
        return 1

    imports = discover_chumicro_imports(project_dir)
    if not imports:
        print(
            f"install-libraries: no chumicro imports found in {project_name} — "
            "nothing to install.",
        )
        return 0
    packages = sorted(import_name_to_package(name) for name in imports)
    print(
        f"install-libraries: {project_name} imports "
        f"{len(packages)} chumicro libraries:",
    )
    for package in packages:
        print(f"  {package}")

    device = _resolve_device(workspace, args)
    bundle_repo = (
        EXPERIMENTAL_BUNDLE_REPO if args.experimental else STABLE_BUNDLE_REPO
    )
    transport = str(device.transport)

    if transport == "circuitpython":
        command = build_circup_command(packages, drive_path=args.drive_path)
        commands_to_run: list[list[str]] = [command]
        if args.experimental:
            print(
                "install-libraries: --experimental + CP — make sure you've run "
                f"`circup bundle-add ChuMicro/{EXPERIMENTAL_BUNDLE_REPO}` "
                "first; circup pulls from registered bundles only.",
            )
    elif transport == "micropython":
        commands_to_run = build_mip_commands(
            packages, bundle_repo=bundle_repo, address=device.address,
        )
    else:
        print(
            f"install-libraries: unsupported transport {transport!r} "
            f"on device {device.address}.",
            file=sys.stderr,
        )
        return 2

    print(
        f"install-libraries: target {transport}@{device.address} "
        f"({bundle_repo})",
    )
    for command in commands_to_run:
        print(f"  $ {' '.join(command)}")
        if args.dry_run:
            continue
        completed = args._env.subprocess_runner(command, check=False)  # noqa: S603 — args fully controlled
        if completed.returncode != 0:
            print(
                f"install-libraries: command failed (exit {completed.returncode}); "
                "fix the underlying tool error and re-run install-libraries.",
                file=sys.stderr,
            )
            return completed.returncode
    if args.dry_run:
        print("install-libraries: --dry-run — no commands executed.")
    else:
        print(f"install-libraries: installed {len(packages)} libraries.")
    return 0


# ---------------------------------------------------------------------------
# Parser construction
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser with every command registered."""
    parser = argparse.ArgumentParser(
        prog="chumicro-workspace",
        description=(
            "Host-side dispatcher for ChuMicro project workspaces — "
            "deploy projects, probe boards, open REPLs, and manage "
            "devices.yml from one CLI."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    _add_setup_parsers(subparsers)
    _add_devices_parsers(subparsers)

    _add_deploy_parser(subparsers)

    _add_projects_parser(subparsers)
    _add_health_parsers(subparsers)

    _add_demo_parser(subparsers)
    _add_deploy_example_parser(subparsers)
    _add_bootstrap_parser(subparsers)

    _add_quality_parsers(subparsers)

    # ----- dump-config ---------------------------------------------------
    dump_config_parser = subparsers.add_parser(
        "dump-config",
        help=(
            "Print the merged runtime config a project would receive on "
            "deploy (workspace.yml defaults + per-project config "
            "deep-merged), without actually deploying."
        ),
    )
    _add_workspace_arg(dump_config_parser)
    dump_config_parser.add_argument(
        "project",
        help="Project name (bare / slash / dotted).",
    )
    dump_config_parser.add_argument(
        "--repr",
        action="store_true",
        help=(
            "Use repr() instead of JSON for the dump.  Useful when the "
            "raw Python types matter (e.g. distinguishing bytes vs str)."
        ),
    )
    dump_config_parser.set_defaults(func=_cmd_dump_config)

    # ----- config-validate ----------------------------------------------
    config_validate_parser = subparsers.add_parser(
        "config-validate",
        help=(
            "Validate the merged runtime config for one or more projects "
            "against the union manifest of every library reachable from "
            "the import graph.  Exits 1 on any failure — designed as a "
            "fast pre-deploy / CI gate."
        ),
    )
    _add_workspace_arg(config_validate_parser)
    config_validate_parser.add_argument(
        "projects",
        nargs="*",
        help=(
            "Project names to validate (bare / slash / dotted).  When "
            "omitted, every project under projects/ is validated."
        ),
    )
    config_validate_parser.set_defaults(func=_cmd_config_validate)

    _add_repl_parser(subparsers)
    _add_rename_parser(subparsers)

    # ----- install-firmware ----------------------------------------------
    install_firmware_parser = subparsers.add_parser(
        "install-firmware",
        help="Download + flash firmware onto the selected board.",
    )
    _add_workspace_arg(install_firmware_parser)
    _add_device_selector(install_firmware_parser)
    _add_firmware_args(install_firmware_parser)
    install_firmware_parser.set_defaults(func=_cmd_install_firmware)

    # ----- reset-board ----------------------------------------------------
    reset_board_parser = subparsers.add_parser(
        "reset-board",
        help=(
            "Wipe the device's user filesystem (clean-slate, no redeploy)."
        ),
        description=(
            "Erase every user file the runtime can see on the selected "
            "board — including out-of-scope files like settings.toml and "
            "hand-edited boot.py — without redeploying any project.  "
            "Standalone counterpart to `deploy --wipe`.  Used to recover "
            "a board whose flash filled up with stage residue (the "
            "MicroPython path runs `os.VfsLfs2.mkfs`, which `os.remove` "
            "alone cannot match — LittleFS metadata + wear-leveling "
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

    _add_install_libraries_parser(subparsers)

    # ----- upgrade-firmware ----------------------------------------------
    upgrade_firmware_parser = subparsers.add_parser(
        "upgrade-firmware",
        help="Alias of install-firmware — same flash flow.",
    )
    _add_workspace_arg(upgrade_firmware_parser)
    _add_device_selector(upgrade_firmware_parser)
    _add_firmware_args(upgrade_firmware_parser)
    upgrade_firmware_parser.set_defaults(func=_cmd_install_firmware)

    return parser


def _add_repl_parser(subparsers: argparse._SubParsersAction) -> None:
    """``repl`` — interactive REPL, tail mode, or deploy-then-tail."""
    repl_parser = subparsers.add_parser(
        "repl",
        help=(
            "Interactive REPL on the selected board, or deploy a project "
            "and tail its output in one command."
        ),
    )
    _add_workspace_arg(repl_parser)
    _add_device_selector(repl_parser)
    repl_parser.add_argument(
        "project",
        nargs="?",
        default=None,
        help=(
            "Optional project name (bare / slash / dotted).  When given, "
            "deploys the project first then enters tail mode for "
            "--tail SECONDS (default 30)."
        ),
    )
    repl_parser.add_argument(
        "--tail",
        type=float,
        default=None,
        metavar="SECONDS",
        help=(
            "Run in tail mode for SECONDS instead of the interactive "
            "TUI.  When a positional project is given, defaults to 30s."
        ),
    )
    repl_parser.add_argument(
        "--no-fail-on-traceback",
        dest="fail_on_traceback",
        action="store_false",
        default=True,
        help="Tail mode only: do not exit non-zero on a detected traceback.",
    )
    _add_non_interactive_arg(repl_parser)
    repl_parser.add_argument(
        "--mode",
        choices=("auto", "line", "passthrough"),
        default="auto",
        help=(
            "Interactive REPL mode.  `line` (the better-featured "
            "default for terminal sessions) ships a host-side line "
            "editor with persistent history, `:edit` editor handoff, "
            "`:save`/`:load`/`:snippets`, and Tab completion against "
            "the on-device namespace.  `passthrough` forwards "
            "keystrokes byte-by-byte (mpremote-style — needed for "
            "raw REPL framing or paste mode).  `auto` (default) "
            "picks `line` when stdin is a TTY and `passthrough` "
            "otherwise.  No effect with `--tail` or with a "
            "positional project (those flows always use the tail "
            "follower)."
        ),
    )
    repl_parser.set_defaults(func=_cmd_repl)


def _add_install_libraries_parser(subparsers: argparse._SubParsersAction) -> None:
    """``install-libraries`` — circup (CP) / mip (MP) bundle install per project."""
    install_libraries_parser = subparsers.add_parser(
        "install-libraries",
        help=(
            "Install chumicro libraries the project imports onto the "
            "device via circup (CP) / mip (MP)."
        ),
        description=(
            "AST-walks PROJECT for chumicro_<name> imports and shells "
            "out to circup (CP) or mpremote-mip (MP) per device's "
            "runtime.  Regular-mode counterpart to dev-mode's "
            "library_sources auto-sync.  Use --dry-run to preview the "
            "exact commands without executing them."
        ),
    )
    _add_workspace_arg(install_libraries_parser)
    _add_device_selector(install_libraries_parser)
    install_libraries_parser.add_argument(
        "project",
        help=(
            "Project name (bare, slash, or dotted form).  Looked up "
            "across the workspace's projects/ tree."
        ),
    )
    install_libraries_parser.add_argument(
        "--experimental",
        action="store_true",
        help=(
            "Install from ChuMicro-Bundle-Experimental instead of "
            "ChuMicro-Bundle (stable, default)."
        ),
    )
    install_libraries_parser.add_argument(
        "--drive-path",
        default=None,
        help=(
            "CP only — explicit CIRCUITPY mount.  Pass when multiple "
            "CIRCUITPY drives are mounted so circup knows which one "
            "to install onto.  Ignored on MP."
        ),
    )
    install_libraries_parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Print the commands that would run without executing them. "
            "Useful for air-gapped hosts or when reviewing what gets "
            "fetched before committing to the install."
        ),
    )
    install_libraries_parser.set_defaults(func=_cmd_install_libraries)


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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CliEnv:
    """Test-injectable seams for :func:`main`.

    Every field defaults to a real-production callable / ``None`` for
    "use platform default".  Tests pass a custom ``CliEnv`` to
    :func:`main` to swap one seam for the duration of the call
    without monkeypatching module internals.  Production code reads
    the values off the env via ``args._env`` inside CLI sub-commands.

    Attributes:
        uf2_search_paths: Override the UF2 mount-root list that
            :func:`~chumicro_workspace.onboarding.detect_board_state`
            forwards to :func:`~chumicro_workspace.onboarding.find_uf2_drive`.
            ``None`` means use the platform default from
            ``onboarding._UF2_MOUNT_SEARCH_PATHS``.  Tests pass ``[]``
            to force "no UF2 drive found" or ``[tmp_path]`` to point
            at a fixture layout.
        subprocess_runner: Callable used for every external-process
            invocation in CLI sub-commands (``pip install -e``,
            ``ruff check``, ``pytest``, ``mpremote mip install``,
            etc.).  Must satisfy :func:`subprocess.run`'s signature
            and return a :class:`subprocess.CompletedProcess`.  Tests
            pass :class:`chumicro_workspace.testing.FakeSubprocessRunner`.
    """

    uf2_search_paths: list[Path] | None = None
    subprocess_runner: Callable[..., subprocess.CompletedProcess] = (
        subprocess.run
    )
    #: Override the firmware-flash callable.  ``None`` means use
    #: :func:`chumicro_deploy.flash_firmware`.  Tests pass a recording
    #: stub to assert on the URL / device / kwargs the CLI forwards.
    flash_firmware_fn: Callable[..., None] | None = None


_DEFAULT_ENV = CliEnv()


def main(
    argv: Sequence[str] | None = None,
    *,
    env: CliEnv | None = None,  # noqa: CHU001 — matches subprocess.run(env=...) convention
) -> int:
    """Parse *argv* and dispatch to the selected command.

    Returns the process exit code.  Stub commands return 2 so CI /
    scripts can distinguish "not implemented yet" from runtime errors.

    Args:
        argv: Command-line arguments (``None`` reads from ``sys.argv``).
        env: Test-injectable seams.  Defaults to a no-override
            :class:`CliEnv` that uses production behavior everywhere.
            Stashed on ``args._env`` so sub-commands can read it.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    args._env = env if env is not None else _DEFAULT_ENV
    return args.func(args)
