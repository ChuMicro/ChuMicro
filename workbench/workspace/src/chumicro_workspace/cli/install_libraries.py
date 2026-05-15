"""``install-libraries`` subcommand — circup (CP) / mip (MP) bundle install."""

from __future__ import annotations

import argparse
import sys

from chumicro_workspace.cli._common import (
    _add_device_selector,
    _add_workspace_arg,
    _resolve_device,
    _resolve_project_name,
    _resolve_workspace,
)
from chumicro_workspace.install_libraries import (
    EXPERIMENTAL_BUNDLE_REPO,
    STABLE_BUNDLE_REPO,
    build_circup_command,
    build_mip_commands,
    discover_chumicro_imports,
    import_name_to_package,
)


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
