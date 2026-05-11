"""Plugin-internal device-test helpers.

Owns the primitives that actually touch device hardware — bootstrap
generation, transport construction, and the workspace-source
discovery that staging depends on.  Orchestration (test selection,
per-device loops, PR-summary rendering) lives in :mod:`plugin`.

:func:`resolve_library_source_dirs` accepts a ``libraries_root``
parameter so any pytest invocation can supply its own workspace
layout via ``pytest.Config.rootpath``.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path
from typing import Any, cast

from chumicro_deploy import (
    DEFAULT_DEPLOY_MODE,
    Device,
    DeviceEntry,
    ExtendedTransportProtocol,
    TransportProtocol,
)

#: PEP 508 version specifiers, environment markers, and extras.
_DEPENDENCY_VERSION_SPLITTER = re.compile(r"[><=!;~\[]")


def _strip_pip_dependency_version(dependency: str) -> str:
    """``"chumicro-timing>=0.1"`` -> ``"chumicro-timing"``."""
    return _DEPENDENCY_VERSION_SPLITTER.split(dependency, maxsplit=1)[0].strip()


def _library_name_from_pip_dependency(dependency: str) -> str | None:
    """Map a ``chumicro-*`` pip dep to its workspace library directory name."""
    name = _strip_pip_dependency_version(dependency)
    if not name.startswith("chumicro-"):
        return None
    return name[len("chumicro-"):]


def _library_name_from_module(module_name: str) -> str | None:
    """Map a ``chumicro_*`` Python module to its workspace library name."""
    if not module_name.startswith("chumicro_"):
        return None
    return module_name.removeprefix("chumicro_").split(".", 1)[0]


def build_bootstrap(
    test_filename: str,
    name_filter: str | None = None,
) -> str:
    """Generate a bootstrap script for the on-device test harness.

    The bootstrap imports the test file via the harness discovery
    module and runs it through ``run_module``.

    Args:
        test_filename: Name of the test file (e.g.
            ``test_heartbeat_ticks.py``).
        name_filter: Optional name filter to pass to ``run_module``.

    Returns:
        Python source code string for the bootstrap script.
    """
    filter_repr = repr(name_filter) if name_filter else "None"
    return (
        "from chumicro_test_harness.runner import run_module\n"
        "from chumicro_test_harness.discovery import _exec_as_namespace\n"
        f"module = _exec_as_namespace('{test_filename}')\n"
        f"run_module(module, name_filter={filter_repr})\n"
    )


def _resolve_test_imported_library_names(test_files: list[Path]) -> list[str]:
    """Return workspace library names imported by functional test files."""
    imported_library_names: set[str] = set()

    for test_file in test_files:
        source_text = test_file.read_text(encoding="utf-8")
        syntax_tree = ast.parse(source_text, filename=str(test_file))

        for node in ast.walk(syntax_tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    library_name = _library_name_from_module(alias.name)
                    if library_name is not None:
                        imported_library_names.add(library_name)
            elif isinstance(node, ast.ImportFrom):
                if node.module is None:
                    continue
                library_name = _library_name_from_module(node.module)
                if library_name is not None:
                    imported_library_names.add(library_name)

    return sorted(imported_library_names)


def resolve_library_source_dirs(
    library_dir: Path,
    *,
    libraries_root: Path,
    test_files: list[Path] | None = None,
    visited_library_names: set[str] | None = None,
) -> list[Path]:
    """Return source dirs for a library and its intra-workspace dependencies.

    Reads ``project.dependencies`` from the library's ``pyproject.toml``
    and resolves any ``chumicro-*`` entries to their ``src/``
    directories.  Critical for RAM-mode deploys where every source
    file is sent inline through the serial REPL.

    Functional tests may also import additional ChuMicro libraries
    directly without making them install-time dependencies; when
    *test_files* is provided, those imports are resolved and staged
    too.

    Args:
        library_dir: Root directory of the library (e.g.
            ``libraries/runner``).
        libraries_root: The workspace's libraries directory — typically
            ``pytest.Config.rootpath / "libraries"`` inside the chumicro
            mono-repo, or any equivalent layout.
        test_files: Optional functional test files whose ChuMicro
            imports should also be staged.
        visited_library_names: Internal cycle guard.

    Returns:
        Dependency-first ordered list of ``src/`` directories.
    """
    if not library_dir.is_dir():
        return []

    if visited_library_names is None:
        visited_library_names = set()
    library_name = library_dir.name
    if library_name in visited_library_names:
        return []
    visited_library_names.add(library_name)

    pyproject_file = library_dir / "pyproject.toml"
    dependency_dirs: list[Path] = []
    dependency_library_names: list[str] = []
    if pyproject_file.exists():
        with pyproject_file.open("rb") as toml_file:
            data: dict[str, Any] = tomllib.load(toml_file)
        dependencies: list[str] = data.get("project", {}).get("dependencies", [])
        for dependency in dependencies:
            dep_library = _library_name_from_pip_dependency(dependency)
            if dep_library is not None:
                dependency_library_names.append(dep_library)

    if test_files:
        for imported_library_name in _resolve_test_imported_library_names(
            test_files,
        ):
            if imported_library_name not in dependency_library_names:
                dependency_library_names.append(imported_library_name)

    for dependency_library_name in dependency_library_names:
        dependency_library_dir = libraries_root / dependency_library_name
        for transitive_dir in resolve_library_source_dirs(
            dependency_library_dir,
            libraries_root=libraries_root,
            visited_library_names=visited_library_names,
        ):
            if transitive_dir not in dependency_dirs:
                dependency_dirs.append(transitive_dir)

    own_source = library_dir / "src"
    if own_source.is_dir() and own_source not in dependency_dirs:
        dependency_dirs.append(own_source)

    return dependency_dirs


def resolve_effective_deploy_mode(
    device_entry: DeviceEntry,
    deploy_mode_override: str | None,
) -> str:
    """Return the effective deploy mode for a device.

    Resolution order:

    1. CLI ``--deploy-mode`` override (highest precedence).
    2. Per-device ``deploy_mode`` from ``devices.yml``.
    3. Global ``defaults.deploy_mode`` (folded into the entry by the loader).
    4. ``DEFAULT_DEPLOY_MODE`` as the last-resort default — flash is
       the production-shaped path; RAM mode is opt-in for unit-style
       tests.
    """
    return deploy_mode_override or device_entry.deploy_mode or DEFAULT_DEPLOY_MODE


def create_transport(
    device_entry: DeviceEntry,
    deploy_mode: str | None = None,
) -> TransportProtocol:
    """Build a transport instance for a device entry.

    Thin wrapper around :meth:`chumicro_deploy.Device.create_transport`
    — translates the registry-shaped ``DeviceEntry`` into a
    ``Device`` and delegates runtime branching.
    """
    effective_mode = resolve_effective_deploy_mode(device_entry, deploy_mode)
    device = Device(
        transport=device_entry.runtime,
        address=device_entry.address,
        baudrate=device_entry.serial_baudrate,
        deploy_mode=effective_mode,
    )
    return device.create_transport()


def build_device_bootstrap(
    device_entry: DeviceEntry,
    transport: TransportProtocol,
    test_file: Path,
    function_filter: str | None,
) -> str | list[str]:
    """Build the bootstrap script(s) for the given device + test file.

    MicroPython uses the standard import-based bootstrap.
    CircuitPython in RAM mode uses an inline bootstrap with module
    injection (returns a list of chunked raw-REPL scripts).
    CircuitPython in flash mode uses the standard import-based path
    since files are on the device.
    """
    if device_entry.runtime == "circuitpython" and transport.mode == "ram":
        from chumicro_deploy import build_circuitpython_bootstrap_scripts

        cp_transport = cast(ExtendedTransportProtocol, transport)
        staged_sources = cp_transport.staged_sources
        assert staged_sources is not None, (
            "stage() must be called before build_device_bootstrap on the "
            "CircuitPython RAM path"
        )
        return build_circuitpython_bootstrap_scripts(
            staged_sources,
            test_file,
            name_filter=function_filter,
            max_chunk_size_bytes=cp_transport.inline_script_budget_bytes(),
        )

    return build_bootstrap(
        test_file.name,
        name_filter=function_filter,
    )


def execute_device_bootstrap(
    transport: TransportProtocol,
    bootstrap: str | list[str],
) -> str:
    """Execute either a single bootstrap script or a chunked sequence.

    A list bootstrap is only produced for the CircuitPython RAM path,
    where the transport implements
    :class:`chumicro_deploy.ExtendedTransportProtocol` and exposes
    ``execute_scripts``.  Calling it directly (instead of guarding
    with ``hasattr``) surfaces a clear ``AttributeError`` if a future
    code path passes a list bootstrap to a transport that doesn't
    support chunking.
    """
    if isinstance(bootstrap, list):
        return cast(ExtendedTransportProtocol, transport).execute_scripts(bootstrap)
    return transport.execute(bootstrap)
