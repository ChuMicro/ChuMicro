"""Environment setup + scaffolding lanes (all heavy imports stay lazy)."""

from __future__ import annotations


def setup() -> int:
    """Install development dependencies, libraries, and IDE configuration.

    Thin CLI wrapper around :func:`shared.install_workspace`, which is the
    single source of truth shared with ``scripts/prepare_workspace.py``.
    See [Decision 0012](../plans/decisions/0012-ide-type-stubs.md) for the
    runtime-pinned type-stub policy.
    """
    from shared import install_workspace
    return install_workspace()


def sync_ide() -> int:
    """Regenerate IDE configuration files (no-op for the workspace itself)."""
    from ide_sync import sync_ide as _sync_ide
    return _sync_ide()


def prepare_micropython() -> int:
    """Build the MicroPython unix-port binary."""
    from prepare_micropython import prepare_micropython as _prepare
    return _prepare()


def prepare_circuitpython() -> int:
    """Build the CircuitPython unix-port binary."""
    from prepare_circuitpython import prepare_circuitpython as _prepare
    return _prepare()


def prepare_mpy_cross() -> int:
    """Build mpy-cross compilers for both runtimes."""
    from prepare_mpy_cross import prepare_mpy_cross as _prepare
    return _prepare()


def new_library(name: str, *, workbench: bool = False) -> int:
    """Scaffold a new device library (or host-only workbench tool)."""
    from new_library_scaffold import new_library as _new_library
    return _new_library(name, workbench=workbench)


def register(subparsers, parents):
    """Register the setup / scaffolding subcommands."""
    # No-arg tasks
    subparsers.add_parser("setup", help="install dependencies and regenerate IDE configuration")
    subparsers.add_parser("sync-ide", help="regenerate IDE configuration files")
    subparsers.add_parser("prepare-micropython", help="prepare MicroPython unix-port")
    subparsers.add_parser("prepare-circuitpython", help="prepare CircuitPython unix-port")
    subparsers.add_parser(
        "prepare-mpy-cross",
        help="build mpy-cross compilers for both runtimes (no unix-port)",
    )
    # new-library
    new_library_parser = subparsers.add_parser("new-library", help="scaffold a new library")
    new_library_parser.add_argument("name", help="library name (e.g. gpio)")
    new_library_parser.add_argument(
        "--workbench",
        action="store_true",
        help="scaffold a host-only workbench tool under workbench/ "
        "instead of a device library under libraries/",
    )
