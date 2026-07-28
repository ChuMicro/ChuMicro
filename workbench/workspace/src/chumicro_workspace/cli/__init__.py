"""``chumicro-workspace`` command dispatch.

Thin wrapper over the public ``chumicro_workspace`` /
``chumicro_deploy`` / ``chumicro_repl`` APIs.  Workspace template
repos vendor a tiny ``run.py`` shim that simply calls
:func:`main`; every command the workspace user invokes
(``python3 run.py deploy back-porch``, ``python3 run.py repl``, etc.)
routes through this dispatcher.

Every subcommand is registered on a single argparse dispatcher and
wired straight to the underlying ``chumicro_workspace`` /
``chumicro_deploy`` / ``chumicro_repl`` API.  There are no stub
tiers.  ``chumicro-workspace --help`` is the authoritative command
list.  This module only assembles the parser and routes each
subcommand to its handler.
"""

from __future__ import annotations

import argparse
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from chumicro_workspace.cli.bootstrap import _add_bootstrap_parser
from chumicro_workspace.cli.config import _add_config_parsers
from chumicro_workspace.cli.deploy import (
    _add_deploy_parser,
    _add_projects_parser,
)
from chumicro_workspace.cli.devices import (
    _add_devices_parsers,
    _add_rename_parser,
)
from chumicro_workspace.cli.examples import (
    _add_demo_parser,
    _add_deploy_example_parser,
)
from chumicro_workspace.cli.firmware import (
    _add_firmware_parsers,
    _add_upgrade_firmware_parser,
)
from chumicro_workspace.cli.health import _add_health_parsers
from chumicro_workspace.cli.library import _add_library_parsers
from chumicro_workspace.cli.quality import _add_quality_parsers
from chumicro_workspace.cli.repl import _add_repl_parser
from chumicro_workspace.cli.setup import _add_setup_parsers
from chumicro_workspace.library import _real_http_get

# ---------------------------------------------------------------------------
# Parser construction
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser with every command registered."""
    parser = argparse.ArgumentParser(
        prog="chumicro-workspace",
        description=(
            "Host-side dispatcher for ChuMicro project workspaces: "
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
    _add_library_parsers(subparsers)
    _add_upgrade_firmware_parser(subparsers)

    return parser


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
    #: HTTP GET callable.  Returns the response body bytes.  Tests
    #: pass a fixture that serves in-memory snapshot tarballs /
    #: ``index.json`` so no sockets open.
    http_get: Callable[[str], bytes] = _real_http_get
    #: Override the firmware-flash callable.  ``None`` means use
    #: :func:`chumicro_deploy.flash_firmware`.  Tests pass a recording
    #: stub to assert on the URL / device / kwargs the CLI forwards.
    flash_firmware_fn: Callable[..., None] | None = None


_DEFAULT_ENV = CliEnv()


def main(
    argv: Sequence[str] | None = None,
    *,
    env: CliEnv | None = None,  # noqa: CHU001 - matches subprocess.run(env=...) convention
) -> int:
    """Parse *argv* and dispatch to the selected command.

    Returns the process exit code from the dispatched subcommand handler
    (0 success; 1 runtime failure; 2 usage / precheck failure, per the
    subcommand's own contract).

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
