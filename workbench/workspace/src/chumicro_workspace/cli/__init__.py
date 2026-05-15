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
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from chumicro_workspace.cli._common import (
    _add_device_selector,
    _add_workspace_arg,
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
from chumicro_workspace.cli.config import _add_config_parsers
from chumicro_workspace.cli.deploy import (
    _add_deploy_parser,
    _add_projects_parser,
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
from chumicro_workspace.cli.firmware import (
    _add_firmware_parsers,
    _add_upgrade_firmware_parser,
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
from chumicro_workspace.cli.repl import (
    _add_repl_parser,
)
from chumicro_workspace.cli.repl import (
    _resolve_repl_mode as _resolve_repl_mode,
)
from chumicro_workspace.cli.setup import _add_setup_parsers
from chumicro_workspace.install_libraries import (
    EXPERIMENTAL_BUNDLE_REPO,
    STABLE_BUNDLE_REPO,
    build_circup_command,
    build_mip_commands,
    discover_chumicro_imports,
    import_name_to_package,
)

# ---------------------------------------------------------------------------
# Implemented commands
# ---------------------------------------------------------------------------


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
    _add_config_parsers(subparsers)

    _add_repl_parser(subparsers)
    _add_rename_parser(subparsers)

    _add_firmware_parsers(subparsers)
    _add_install_libraries_parser(subparsers)
    _add_upgrade_firmware_parser(subparsers)

    return parser


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
