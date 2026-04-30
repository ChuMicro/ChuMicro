"""Plugin-internal device-test helpers.

Owns the primitives that actually touch device hardware — bootstrap
generation, transport construction, and the workspace-source
discovery that staging depends on.  Orchestration (test selection,
per-device loops, PR-summary rendering) lives in :mod:`plugin`.

Migrated from ``scripts/device_testing.py`` (Decision 0032 §Rule 8)
when the pytest plugin moved out of the chumicro mono-repo's
``scripts/`` and into a publishable workbench package.

The mono-repo-only ``ROOT`` constant was replaced with a
``libraries_root`` parameter on :func:`resolve_library_source_dirs`
so any pytest invocation can supply its own workspace layout via
``pytest.Config.rootpath``.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path
from typing import Any, cast

from chumicro_deploy import (
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


#: Filenames the plugin auto-stages alongside any functional test
#: that imports them.  ``_test_creds.py`` is materialized by each
#: library's functional-tests ``conftest.py`` from
#: ``chumicro-dev-config.toml`` and carries wifi creds plus any
#: per-library secrets (host echo IPs, broker addresses, etc.) the
#: tests need at runtime.  Listed by exact basename so the heuristic
#: stays predictable — extending the list is a deliberate change.
_KNOWN_TEST_SIBLING_MODULES = ("_test_creds.py",)


def resolve_test_sibling_modules(test_file: Path) -> list[Path]:
    """Return helper modules that live next to *test_file* and should be staged.

    Today's only entry is ``_test_creds.py`` — a gitignored shim each
    library's ``conftest.py`` materializes from the dev config.  Without
    this staging hook the test source's ``from _test_creds import …``
    fails on the device with ``ImportError``, the test catches it, sets
    ``_HAS_CREDS = False``, and returns silently — appearing to PASS
    while never exercising any real hardware.  The deploy graph
    walker can't pick this up via AST because ``_test_creds`` isn't a
    chumicro module.

    Args:
        test_file: Functional test file under ``functional_tests/``.

    Returns:
        Sorted list of sibling Python files that exist on disk.  Empty
        when the conftest hasn't materialized them (e.g. a CI run
        without dev creds).
    """
    candidates = [test_file.parent / name for name in _KNOWN_TEST_SIBLING_MODULES]
    return [path for path in candidates if path.is_file()]


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


#: Known (library, device-runtime, board-fingerprint) combinations
#: whose RAM-mode bootstrap exceeds the device's heap.  RAM mode
#: chunks the source + AST-builds it inline, which costs 10-20 KB of
#: heap *on top of* the chunk's own size; on a 264 KB-SRAM target the
#: combined library + transitive deps + harness blow past the budget.
#: Flash mode mpy-compiles off-device, sidestepping the parse pressure
#: entirely.
#:
#: Each entry: ``(library_name, runtime, board_fingerprint)`` where
#: *board_fingerprint* is matched against ``device.identifier`` (lower-cased
#: substring) and against ``extra.hardware.machine`` when set.  Add a
#: row when a (library, board) combination is empirically confirmed
#: to OOM in RAM mode.
_RAM_MODE_TOO_CONSTRAINED: tuple[tuple[str, str, str], ...] = (
    # chumicro-mqtt + Pi Pico W CP — `MemoryError: memory allocation
    # failed, allocating 14034 bytes` during inline-bootstrap chunk 4/6
    # of mqtt + sockets + wifi + harness (commit ff6f1ec investigation).
    ("mqtt", "circuitpython", "pi-pico-w"),
)


def _normalise_for_fingerprint(value: str) -> str:
    """Collapse runs of dashes / underscores / whitespace to single spaces.

    Lets a fingerprint like ``"pi-pico-w"`` match either
    ``"pi-pico-w-circuitpython-board"`` (the canonical device-id shape)
    or ``"Raspberry Pi Pico W"`` (the canonical
    ``sys.implementation.machine`` form on the rp2 port) without
    listing both in the constraint table.
    """
    return re.sub(r"[-_\s]+", " ", value).strip().lower()


def _matches_board_fingerprint(
    device_entry: DeviceEntry, fingerprint: str,
) -> bool:
    """Test *fingerprint* against a device's identifier or hardware machine."""
    needle = _normalise_for_fingerprint(fingerprint)
    if needle in _normalise_for_fingerprint(device_entry.identifier):
        return True
    hardware = (
        device_entry.extra.get("hardware")
        if isinstance(device_entry.extra, dict)
        else None
    )
    if isinstance(hardware, dict):
        machine = _normalise_for_fingerprint(str(hardware.get("machine", "")))
        if machine and needle in machine:
            return True
    return False


def ram_mode_too_constrained(
    library_name: str | None,
    device_entry: DeviceEntry,
) -> bool:
    """Return ``True`` when (library, device) is known to OOM in RAM mode.

    Consulted by :func:`resolve_effective_deploy_mode` to auto-upgrade
    a ``defaults.deploy_mode: ram`` entry to flash for known-bad
    combinations.  An explicit ``--chumicro-deploy-mode ram`` CLI
    override still wins (the override exists precisely to bypass these
    routings — letting the user reproduce the OOM if they want to).
    """
    if library_name is None:
        return False
    return any(
        library == library_name
        and runtime == device_entry.runtime
        and _matches_board_fingerprint(device_entry, fingerprint)
        for library, runtime, fingerprint in _RAM_MODE_TOO_CONSTRAINED
    )


def resolve_effective_deploy_mode(
    device_entry: DeviceEntry,
    deploy_mode_override: str | None,
    *,
    library_name: str | None = None,
) -> str:
    """Return the effective deploy mode for a device.

    Resolution order:

    1. CLI ``--chumicro-deploy-mode`` override (highest precedence —
       wins even when the (library, device) combination is known to
       OOM in RAM mode; the override exists for exactly that "let me
       reproduce the failure" use case).
    2. Per-device ``deploy_mode`` from ``devices.yml``.
    3. Global ``defaults.deploy_mode`` (folded into the entry by the loader).
    4. ``"ram"`` as a last-resort default.

    When *library_name* is supplied, an effective mode of ``ram`` that
    matches an entry in :data:`_RAM_MODE_TOO_CONSTRAINED` auto-upgrades
    to ``flash``.  Pass ``None`` to skip the constraint check (e.g. when
    the call site doesn't know which library is about to be tested).
    """
    if deploy_mode_override is not None:
        return deploy_mode_override
    mode = device_entry.deploy_mode or "ram"
    if mode == "ram" and ram_mode_too_constrained(library_name, device_entry):
        return "flash"
    return mode


def create_transport(
    device_entry: DeviceEntry,
    deploy_mode: str | None = None,
    *,
    library_name: str | None = None,
) -> TransportProtocol:
    """Build a transport instance for a device entry.

    Thin wrapper around :meth:`chumicro_deploy.Device.create_transport`
    — translates the registry-shaped ``DeviceEntry`` into a
    ``Device`` and delegates runtime branching.

    *library_name* is forwarded to :func:`resolve_effective_deploy_mode`
    so a (library, device) combination known to OOM in RAM mode (see
    :data:`_RAM_MODE_TOO_CONSTRAINED`) auto-upgrades to flash without
    a CLI override.  Pass ``None`` when the call site doesn't yet know
    which library is about to run on the transport.
    """
    effective_mode = resolve_effective_deploy_mode(
        device_entry, deploy_mode, library_name=library_name,
    )
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
