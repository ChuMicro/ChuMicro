"""Host-side device-orchestration primitives.

Owns the primitives that bridge a `DeviceEntry` (registry record) and
a board running its bootstrap: transport construction with deploy-mode
resolution, library-source-dir walking, bootstrap-script generation
(single-script flash / chunked CP RAM), and execute-with-marker-dispatch.

Consumed by `chumicro_workspace.deploy_api` (the programmatic
deploy + marker-orchestration entry point for demos and host tooling)
and by `chumicro_pytest_device` (the pytest collection layer that
runs cross-runtime tests on real boards).  The split: this module owns
"deploy + run on a board with stdout markers"; pytest-device owns
"collect tests, pick devices per session, render PR summaries."
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

from .markers import MarkerQueue, parse_marker

#: PEP 508 version specifiers, environment markers, and extras.
_DEPENDENCY_VERSION_SPLITTER = re.compile(r"[><=!;~\[]")


def _strip_pip_dependency_version(dependency: str) -> str:
    """Strip version, extras, and environment markers from a pip dependency string.

    ``"chumicro-timing>=0.1"`` returns ``"chumicro-timing"``.
    """
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


def chunk_boundaries_for(source_path: Path) -> list[int] | None:
    """Return 1-based top-level statement start lines, or ``None``.

    Computed host-side (CPython has ``ast`` and the boards do not) so the
    device can exec a large test module in per-statement chunks and
    keep its compile transient bounded.  Decorator-aware: a decorated
    class/def starts at its first decorator, so the decorator and the
    statement it decorates land in the same chunk.

    Returns ``None`` (keep the single whole-file ``exec``) when
    chunking would be unsafe or pointless: a ``from __future__`` import
    (each chunk compiles independently, so a future statement cannot
    govern later chunks) or fewer than two top-level statements
    (nothing to split).
    """
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    starts: list[int] = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            return None
        start = node.lineno
        decorators = getattr(node, "decorator_list", [])
        if decorators:
            start = min(start, decorators[0].lineno)
        starts.append(start)
    if len(starts) < 2:
        return None
    return sorted(starts)


def build_bootstrap(
    test_filename: str,
    name_filter: str | None = None,
    chunk_boundaries: list[int] | None = None,
) -> str:
    """Generate a bootstrap script for the on-device test harness.

    The bootstrap imports the test file via the harness discovery
    module and runs it through ``run_module``.

    Args:
        test_filename: Name of the test file (e.g.
            ``test_heartbeat_ticks.py``).
        name_filter: Optional name filter to pass to ``run_module``.
        chunk_boundaries: Optional top-level statement start lines.  When
            set, the device exec's the file in chunks (RAM-constrained
            boards).  ``None`` keeps the single whole-file exec.

    Returns:
        Python source code string for the bootstrap script.
    """
    filter_repr = repr(name_filter) if name_filter else "None"
    boundaries_repr = repr(chunk_boundaries) if chunk_boundaries else "None"
    return (
        "from chumicro_test_harness.runner import run_module\n"
        "from chumicro_test_harness.discovery import _exec_as_namespace\n"
        f"module = _exec_as_namespace('{test_filename}', "
        f"chunk_boundaries={boundaries_repr})\n"
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
    directly without making them install-time dependencies.  When
    *test_files* is provided, those imports are resolved and staged
    too.

    Args:
        library_dir: Root directory of the library (e.g.
            ``libraries/runner``).
        libraries_root: The workspace's libraries directory, typically
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
    4. ``DEFAULT_DEPLOY_MODE`` as the last-resort default.  Flash is
       the production-shaped path, and RAM mode is opt-in for unit-style
       tests.
    """
    return deploy_mode_override or device_entry.deploy_mode or DEFAULT_DEPLOY_MODE


def build_transport_for_entry(
    device_entry: DeviceEntry,
    deploy_mode: str | None = None,
) -> TransportProtocol:
    """Build a transport instance for a device entry.

    Thin wrapper around :meth:`chumicro_deploy.Device.create_transport`
    that translates the registry-shaped ``DeviceEntry`` into a
    ``Device`` and delegates runtime branching.  Named to disambiguate
    from ``Device.create_transport`` itself: this one takes the
    registry record, that one takes the constructed Device.
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
    """Build the bootstrap script(s) that drive *test_file* on the device.

    Returns a single script string for MicroPython and CircuitPython-
    flash (files live on-device and import normally), or a list of
    chunked raw-REPL scripts for CircuitPython-RAM (sources have to
    be injected inline because there's no writable filesystem).
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
        chunk_boundaries=chunk_boundaries_for(test_file),
    )


def execute_device_bootstrap(
    transport: TransportProtocol,
    bootstrap: str | list[str],
    *,
    marker_queue: MarkerQueue | None = None,
) -> str:
    """Execute either a single bootstrap script or a chunked sequence.

    A list bootstrap is only produced for the CircuitPython RAM path,
    where the transport implements
    :class:`chumicro_deploy.ExtendedTransportProtocol` and exposes
    ``execute_scripts``.  Calling it directly (instead of guarding
    with ``hasattr``) surfaces a clear ``AttributeError`` if a future
    code path passes a list bootstrap to a transport that doesn't
    support chunking.

    When *marker_queue* is provided, captured stdout is dispatched
    line-by-line through :func:`markers.parse_marker`; any matching
    markers are pushed onto the queue as they arrive over the serial
    link.  Lines that aren't markers (free-form board prose,
    result-parser ``PASS`` / ``FAIL`` / ``SUMMARY`` lines) are ignored
    by the marker layer — they still ride the captured-stdout return
    value, so the existing result-parser path consumes them unchanged.

    When *marker_queue* is :data:`None` (the default), no streaming
    hook is wired and the call shape is identical to the previous
    request/response behaviour.
    """
    transport_kwargs: dict[str, Any] = {}
    if marker_queue is not None:

        def push_marker_if_present(line: str) -> None:
            marker = parse_marker(line)
            if marker is not None:
                marker_queue.push(marker)

        transport_kwargs["on_line"] = push_marker_if_present
    if isinstance(bootstrap, list):
        return cast(ExtendedTransportProtocol, transport).execute_scripts(
            bootstrap, **transport_kwargs,
        )
    return transport.execute(bootstrap, **transport_kwargs)
