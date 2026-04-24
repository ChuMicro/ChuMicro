"""Device-test helpers shared by the pytest plugin and anything else.

Owns the primitives that actually touch device hardware — bootstrap
generation, transport construction, and the intra-workspace source
discovery that staging depends on.  Orchestration (test selection,
per-device loops, PR-summary rendering) lives in
:mod:`pytest_device` now; ``run.py test-libraries-functional`` is a thin wrapper
that invokes pytest with the plugin's ``--chumicro-*`` options.

See Decision 0027 for the transport protocol and config schema.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, cast

from chumicro_deploy import (
    Device,
    ExtendedTransportProtocol,
    TransportProtocol,
)
from device_config import DeviceEntry
from workspace import (
    ROOT,
    library_name_from_module,
    library_name_from_pip_dependency,
    load_tomllib,
)


def build_bootstrap(
    test_filename: str,
    name_filter: str | None = None,
) -> str:
    """Generate a bootstrap script for the test harness.

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
    """Return workspace library names imported by functional test files.

    Args:
        test_files: Functional test files to inspect.

    Returns:
        Sorted unique library names referenced through ``chumicro_*`` imports.
    """
    imported_library_names: set[str] = set()

    for test_file in test_files:
        source_text = test_file.read_text(encoding="utf-8")
        syntax_tree = ast.parse(source_text, filename=str(test_file))

        for node in ast.walk(syntax_tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    library_name = library_name_from_module(alias.name)
                    if library_name is not None:
                        imported_library_names.add(library_name)
            elif isinstance(node, ast.ImportFrom):
                if node.module is None:
                    continue
                library_name = library_name_from_module(node.module)
                if library_name is not None:
                    imported_library_names.add(library_name)

    return sorted(imported_library_names)


def resolve_library_source_dirs(
    library_dir: Path,
    *,
    test_files: list[Path] | None = None,
    visited_library_names: set[str] | None = None,
) -> list[Path]:
    """Return source dirs for a library and its intra-workspace dependencies.

    Reads ``project.dependencies`` from the library's ``pyproject.toml``
    and resolves any ``chumicro-*`` entries to their ``src/`` directories.
    This provides the minimal set of source directories needed to run
    the library's tests — critical for RAM mode where all source code
    is sent inline through the serial REPL.

    Functional tests may also import additional ChuMicro libraries directly
    without making them install-time dependencies of the library under test.
    When ``test_files`` is provided, those imports are resolved and staged too.

    Args:
        library_dir: Root directory of the library (e.g.
            ``libraries/runner``).
        test_files: Optional functional test files whose ChuMicro imports
            should also be staged.
        visited_library_names: Internal cycle guard for recursive resolution.

    Returns:
        List of ``src/`` directories: the library's own plus
        any intra-workspace dependencies, in dependency-first order.
    """
    libraries_root = ROOT / "libraries"
    tomllib = load_tomllib()

    if not library_dir.is_dir():
        return []

    if visited_library_names is None:
        visited_library_names = set()
    library_name = library_dir.name
    if library_name in visited_library_names:
        return []
    visited_library_names.add(library_name)

    # Read the library's own dependencies.
    pyproject_file = library_dir / "pyproject.toml"
    dependency_dirs: list[Path] = []
    dependency_library_names: list[str] = []
    if pyproject_file.exists():
        with pyproject_file.open("rb") as toml_file:
            data: dict[str, Any] = tomllib.load(toml_file)
        dependencies: list[str] = data.get("project", {}).get("dependencies", [])
        for dependency in dependencies:
            dep_library = library_name_from_pip_dependency(dependency)
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
            visited_library_names=visited_library_names,
        ):
            if transitive_dir not in dependency_dirs:
                dependency_dirs.append(transitive_dir)

    # The library's own src/ comes last so dependencies are registered
    # first during staging.
    own_source = library_dir / "src"
    if own_source.is_dir() and own_source not in dependency_dirs:
        dependency_dirs.append(own_source)

    return dependency_dirs


def resolve_effective_deploy_mode(
    device_entry: DeviceEntry,
    deploy_mode_override: str | None,
) -> str:
    """Return the user-facing deploy mode that will actually run for a device.

    Resolution order:

    1. CLI ``--chumicro-deploy-mode`` override (highest precedence).
    2. Per-device ``deploy_mode`` from ``devices.yml``.
    3. Global ``defaults.deploy_mode`` from ``devices.yml`` (already
       folded into ``device_entry.deploy_mode`` at load time).
    4. ``"ram"`` as a last-resort default.

    Callers use the return value both to construct the transport and
    to label per-device bullets in the PR summary — reviewers ask
    "what mode ran on this board" and the CLI reconstruction alone
    cannot answer that when the user invoked bare ``test-libraries-functional``.

    Args:
        device_entry: A DeviceEntry from the config loader.
        deploy_mode_override: ``--chumicro-deploy-mode`` value, or ``None``.

    Returns:
        ``"ram"`` or ``"flash"``.
    """
    return deploy_mode_override or device_entry.deploy_mode or "ram"


def create_transport(
    device_entry: DeviceEntry,
    deploy_mode: str | None = None,
) -> TransportProtocol:
    """Create the appropriate transport for a device entry.

    Thin wrapper around :meth:`chumicro_deploy.Device.create_transport`
    — builds a ``Device`` from the chumicro-shaped ``DeviceEntry`` and
    delegates runtime-branching to the package.

    Args:
        device_entry: A DeviceEntry from the config loader.
        deploy_mode: ``"ram"`` or ``"flash"``.  When ``None``, uses the
            device entry's ``deploy_mode`` field (default ``"ram"``).

    Returns:
        A transport instance for the device's runtime.

    Raises:
        ValueError: If the runtime is not supported.
    """
    effective_mode = resolve_effective_deploy_mode(device_entry, deploy_mode)
    device = Device(
        transport=device_entry.runtime,
        address=device_entry.address,
        baudrate=device_entry.serial_baudrate,
        deploy_mode=effective_mode,
        circuitpy_drive_path=device_entry.circuitpy_drive_path,
    )
    return device.create_transport()


def build_device_bootstrap(
    device_entry: DeviceEntry,
    transport: TransportProtocol,
    test_file: Path,
    function_filter: str | None,
) -> str | list[str]:
    """Build the bootstrap script for the given device and test file.

    MicroPython uses the standard import-based bootstrap.
    CircuitPython in RAM mode uses an inline bootstrap with module
    injection.  CircuitPython in flash mode uses the standard
    import-based bootstrap since files are on the device.

    Args:
        device_entry: A DeviceEntry from the config loader.
        transport: The transport instance (needed for staged sources
            on CircuitPython RAM mode).
        test_file: Path to the test file.
        function_filter: Optional substring filter for the on-device
            ``run_module`` ``name_filter``.

    Returns:
        Python source code string, or a list of chunked raw-REPL scripts for
        CircuitPython RAM mode.
    """
    if device_entry.runtime == "circuitpython" and transport.mode == "ram":
        from chumicro_deploy import build_circuitpython_bootstrap_scripts

        # The CircuitPython RAM transport always exposes the chunking
        # helpers via ExtendedTransportProtocol — no need to guard.
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
    """Execute either a single bootstrap script or a chunked script sequence.

    A list bootstrap is only produced for the CircuitPython RAM path,
    where the transport implements ExtendedTransportProtocol and
    therefore exposes ``execute_scripts``.  Calling ``execute_scripts``
    directly (instead of guarding with ``hasattr``) surfaces a clear
    AttributeError if a future code path passes a list bootstrap to a
    transport that does not support chunking.
    """
    if isinstance(bootstrap, list):
        return cast(ExtendedTransportProtocol, transport).execute_scripts(bootstrap)
    return transport.execute(bootstrap)
