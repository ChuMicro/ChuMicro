"""Device testing orchestration for the test-device command.

Discovers functional tests, stages them on connected devices via the
appropriate transport, and reports results.  Extracted from ``run.py``
to keep the task runner thin and make orchestration logic independently
testable.

See Decision 0027 for the transport protocol and config schema.
"""

from __future__ import annotations

import ast
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from chumicro_device_transport import (
    DeviceImplementation,
    ExtendedTransportProtocol,
    TransportProtocol,
)
from device_config import (
    DeviceConfigError,
    DeviceDefaults,
    DeviceEntry,
    load_device_registry,
    resolve_ide_devices,
)
from result_parser import TestResult, parse_output
from workspace import (
    ROOT,
    discover_library_dirs,
    library_name_from_module,
    library_name_from_pip_dependency,
    load_tomllib,
)


@dataclass
class FileRunResult:
    """Results captured for a single test file run on a single device.

    Populated once per ``(device, test_file)`` pair inside
    :func:`_run_tests_on_device`.  Used by the PR summary to build
    per-file sub-bullets (or per-test sub-bullets when only one file
    ran on a device).

    Attributes:
        library: Library directory name (e.g. ``"timing"``).
        file_name: Test file name without its path (e.g.
            ``"test_heartbeat.py"``).
        passed: ``summary.total - summary.failed`` from the harness.
        failed: ``summary.failed`` from the harness.
        errors: 1 if the harness produced no summary line, else 0.
        tests: Per-test results emitted by the harness — available so
            single-file runs can show method-level pass/fail.
        duration_seconds: Wall-clock time spent running this file.
    """

    library: str
    file_name: str
    passed: int
    failed: int
    errors: int
    tests: list[TestResult] = field(default_factory=list)
    duration_seconds: float = 0.0


@dataclass
class DeviceRunResult:
    """Aggregate results for one device across its whole test plan.

    Returned by :func:`_run_tests_on_device` and consumed by the PR
    summary.  ``files`` is empty when the device never reached the
    per-file loop (transport creation failure, connect failure, or
    bulk-stage failure).

    Attributes:
        device: The originating :class:`DeviceEntry`.
        passed: Total passing tests across all files.
        failed: Total failing tests across all files.
        errors: Total errors (per-file raises + missing summary lines +
            bulk-stage failures).
        implementation: Probe result, or ``None`` if the probe
            couldn't complete.
        deploy_mode: User-facing deploy mode (``"ram"`` or
            ``"flash"``).
        duration_seconds: Wall-clock time spent on this device,
            measured from transport creation through disconnect.
        files: Per-file results in test-plan order.
    """

    device: DeviceEntry
    passed: int
    failed: int
    errors: int
    implementation: DeviceImplementation | None
    deploy_mode: str
    duration_seconds: float = 0.0
    files: list[FileRunResult] = field(default_factory=list)


def discover_functional_tests(
    *,
    library: str | None = None,
    file_filter: str | None = None,
    function_filter: str | None = None,
) -> list[tuple[str, Path, list[Path]]]:
    """Discover functional test files across libraries.

    ``file_filter`` and ``function_filter`` are orthogonal substring
    filters.  A file passes when:

    - No ``file_filter`` is given, OR the filter substring appears in
      the file's name.
    - AND no ``function_filter`` is given, OR at least one ``test_*``
      function in the file has the filter substring in its name.

    The old behavior was a single ``test_filter`` that matched either
    file names OR function names — which let a file slip into the plan
    on function-name alone and surprised users who passed something
    like ``--test test_runner`` expecting only ``test_runner.py`` to
    run.  Splitting the filters makes the intent unambiguous.

    Args:
        library: Limit to a single library name.
        file_filter: Optional substring matched against test file names.
        function_filter: Optional substring matched against ``test_*``
            function names (matches only — file names are never
            considered by this filter).

    Returns:
        List of ``(library_name, source_dir, test_files)`` tuples.
    """
    libraries_root = ROOT / "libraries"
    test_plan: list[tuple[str, Path, list[Path]]] = []

    for library_dir in sorted(libraries_root.iterdir()):
        if not library_dir.is_dir():
            continue
        if library and library_dir.name != library:
            continue
        functional_dir = library_dir / "functional_tests"
        if not functional_dir.is_dir():
            continue
        test_files = sorted(
            path for path in functional_dir.iterdir()
            if path.name.startswith("test_") and path.name.endswith(".py")
        )
        if file_filter:
            test_files = [
                path for path in test_files
                if file_filter in path.name
            ]
        if function_filter:
            test_files = [
                path for path in test_files
                if _file_contains_matching_function(path, function_filter)
            ]
        if test_files:
            source_dir = library_dir / "src"
            test_plan.append((library_dir.name, source_dir, test_files))

    return test_plan


def _file_contains_matching_function(test_file: Path, name_filter: str) -> bool:
    """Return whether a test file defines a ``test_*`` function matching the filter.

    Parses the file's AST (never imports it — these files target
    on-device runtimes and may reference modules CPython doesn't have)
    and checks each module-level function name against the substring
    filter.

    Args:
        test_file: Path to a ``functional_tests/test_*.py`` file.
        name_filter: Substring to match against function names.

    Returns:
        ``True`` when at least one ``test_*`` function in the file has
        the filter substring in its name.
    """
    source_text = test_file.read_text(encoding="utf-8")
    syntax_tree = ast.parse(source_text, filename=str(test_file))
    for node in ast.iter_child_nodes(syntax_tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if not node.name.startswith("test_"):
            continue
        if name_filter in node.name:
            return True
    return False


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


def _resolve_library_source_dirs(
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
            data = tomllib.load(toml_file)
        dependencies = data.get("project", {}).get("dependencies", [])
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
        for transitive_dir in _resolve_library_source_dirs(
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


def _resolve_effective_deploy_mode(
    device_entry: DeviceEntry,
    deploy_mode_override: str | None,
) -> str:
    """Return the user-facing deploy mode that will actually run for a device.

    Resolution order:

    1. CLI ``--deploy-mode`` override (highest precedence).
    2. Per-device ``deploy_mode`` from ``devices.yml``.
    3. Global ``defaults.deploy_mode`` from ``devices.yml`` (already
       folded into ``device_entry.deploy_mode`` at load time).
    4. ``"ram"`` as a last-resort default.

    Callers use the return value both to construct the transport and
    to label per-device bullets in the PR summary — reviewers ask
    "what mode ran on this board" and the CLI reconstruction alone
    cannot answer that when the user invoked bare ``test-device``.

    Args:
        device_entry: A DeviceEntry from the config loader.
        deploy_mode_override: ``--deploy-mode`` value, or ``None``.

    Returns:
        ``"ram"`` or ``"flash"``.
    """
    return deploy_mode_override or device_entry.deploy_mode or "ram"


def _create_transport(
    device_entry: DeviceEntry,
    deploy_mode: str | None = None,
) -> TransportProtocol:
    """Create the appropriate transport for a device entry.

    Args:
        device_entry: A DeviceEntry from the config loader.
        deploy_mode: ``"ram"`` or ``"flash"``.  When ``None``, uses the
            device entry's ``deploy_mode`` field (default ``"ram"``).

    Returns:
        A transport instance for the device's runtime.

    Raises:
        ValueError: If the runtime is not supported or flash mode
            is missing required configuration.
    """
    effective_mode = _resolve_effective_deploy_mode(device_entry, deploy_mode)

    if device_entry.runtime == "micropython":
        from chumicro_device_transport import MicropythonTransport

        # Map deploy mode to mpremote transport terminology.
        mpremote_mode = "mount" if effective_mode == "ram" else "copy"
        return MicropythonTransport(
            device_entry.address,
            mode=mpremote_mode,
        )

    if device_entry.runtime == "circuitpython":
        from chumicro_device_transport import CircuitpythonTransport

        return CircuitpythonTransport(
            device_entry.address,
            baudrate=device_entry.serial_baudrate,
            mode=effective_mode,
            circuitpy_drive_path=device_entry.circuitpy_drive_path,
        )

    raise ValueError(f"Unsupported runtime: {device_entry.runtime}")


def _build_device_bootstrap(
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
        from chumicro_device_transport import build_circuitpython_bootstrap_scripts

        # The CircuitPython RAM transport always exposes the chunking
        # helpers via ExtendedTransportProtocol — no need to guard.
        cp_transport = cast(ExtendedTransportProtocol, transport)
        staged_sources = cp_transport.staged_sources
        assert staged_sources is not None, (
            "stage() must be called before _build_device_bootstrap on the "
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


def _execute_device_bootstrap(
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


def _bulk_stage_test_plan(
    transport: TransportProtocol,
    test_plan: list[tuple[str, Path, list[Path]]],
    harness_source: Path,
) -> int:
    """Stage every library + test file for a non-RAM-mode device in one pass.

    Flash and MicroPython mount modes persist files on the device
    filesystem, so we can stage everything up front instead of per
    library.  On FAT32 drives that avoids N rsync passes.

    Args:
        transport: Connected transport.
        test_plan: List of ``(library_name, source_dir, test_files)``.
        harness_source: Path to the test harness ``src/`` directory.

    Returns:
        ``0`` on success; on failure, the number of test files that
        never reached the per-file loop (caller attributes these to
        ``result.errors``).
    """
    source_dirs = [
        library_dir / "src"
        for library_dir in discover_library_dirs()
        if (library_dir / "src").is_dir()
    ]
    all_test_files = [
        test_file
        for _library_name, _source_dir, test_files in test_plan
        for test_file in test_files
    ]
    try:
        transport.stage(source_dirs, all_test_files, harness_source)
    except Exception as stage_error:
        print(f"  Stage failed: {stage_error}")
        return len(all_test_files)
    return 0


def _stage_library_for_test_files(
    transport: TransportProtocol,
    library_name: str,
    source_dir: Path,
    test_files: list[Path],
    harness_source: Path,
) -> list[FileRunResult] | None:
    """Stage one library's sources + test files for RAM-mode execution.

    RAM mode sends every module source inline through the serial REPL,
    so we re-stage per library with only the source dirs that library
    actually needs — itself plus its intra-workspace dependencies.

    Args:
        transport: Connected transport.
        library_name: Library directory name (for diagnostics).
        source_dir: The library's ``src/`` directory.
        test_files: Test files to stage.
        harness_source: Path to the test harness ``src/`` directory.

    Returns:
        ``None`` on success, or a list of error-row ``FileRunResult``
        entries that the caller should append and count as errors.
    """
    library_dir = source_dir.parent
    library_source_dirs = _resolve_library_source_dirs(
        library_dir, test_files=test_files,
    )
    try:
        transport.stage(library_source_dirs, test_files, harness_source)
    except Exception as stage_error:
        print(f"  Stage failed for {library_name}: {stage_error}")
        return [
            FileRunResult(
                library=library_name,
                file_name=test_file.name,
                passed=0, failed=0, errors=1,
            )
            for test_file in test_files
        ]
    return None


def _run_single_test_file(
    device_entry: DeviceEntry,
    transport: TransportProtocol,
    library_name: str,
    test_file: Path,
    function_filter: str | None,
) -> tuple[FileRunResult, bool]:
    """Build, execute, and parse a single on-device test file.

    Args:
        device_entry: Target device.
        transport: Connected transport.
        library_name: Library directory name.
        test_file: The ``test_*.py`` file to run.
        function_filter: Optional substring filter passed to the on-device
            ``run_module`` as ``name_filter``.

    Returns:
        ``(file_result, abort)``: the ``FileRunResult`` for this file
        and a flag indicating whether the rest of the device's plan
        should be abandoned because ``recover()`` itself failed.
    """
    print(f"\n  {library_name}/{test_file.name}")
    file_start = time.perf_counter()
    file_passed = 0
    file_failed = 0
    file_errors = 0
    file_tests: list[TestResult] = []
    abort = False

    try:
        bootstrap = _build_device_bootstrap(
            device_entry, transport, test_file, function_filter,
        )
        raw_output = _execute_device_bootstrap(transport, bootstrap)
        print(raw_output)

        parsed = parse_output(raw_output)
        file_tests = list(parsed.tests)
        if parsed.summary:
            file_passed = parsed.summary.total - parsed.summary.failed
            file_failed = parsed.summary.failed
        else:
            print("  WARNING: No summary line in output.")
            file_errors = 1

    except Exception as run_error:
        print(f"  ERROR: {run_error}")
        file_errors = 1
        # Try to recover raw REPL so the next test can run.
        try:
            transport.recover()
        except Exception as recover_error:
            print(f"  FATAL: Cannot recover board state: {recover_error}")
            print("  Aborting remaining tests on this device.")
            abort = True

    file_result = FileRunResult(
        library=library_name,
        file_name=test_file.name,
        passed=file_passed,
        failed=file_failed,
        errors=file_errors,
        tests=file_tests,
        duration_seconds=time.perf_counter() - file_start,
    )
    return file_result, abort


def _teardown_transport(transport: TransportProtocol) -> None:
    """Reset and disconnect a transport, swallowing hardware-only failures.

    A disconnect raise used to propagate all the way up and skip the
    final PR summary.  Both steps are best-effort — the serial port
    will be reclaimed on process exit if something stays stuck.
    """
    try:
        transport.reset()
    except Exception as reset_error:
        print(f"  WARNING: Failed to reset device after test run: {reset_error}")
    try:
        transport.disconnect()
    except Exception as disconnect_error:  # pragma: no cover - hardware-only
        print(
            f"  WARNING: Failed to disconnect device cleanly: "
            f"{disconnect_error}"
        )


def _run_tests_on_device(
    device_entry: DeviceEntry,
    test_plan: list[tuple[str, Path, list[Path]]],
    harness_source: Path,
    function_filter: str | None,
    deploy_mode: str | None = None,
) -> DeviceRunResult:
    """Run all planned tests on a single device.

    Args:
        device_entry: A DeviceEntry from the config loader.
        test_plan: List of ``(library_name, source_dir, test_files)``.
        harness_source: Path to the test harness ``src/`` directory.
        function_filter: Optional substring filter passed to the
            on-device ``run_module`` as ``name_filter`` so only test
            functions whose names contain it actually execute.
        deploy_mode: ``"ram"`` or ``"flash"``.  When ``None``, uses the
            device entry's ``deploy_mode`` field.

    Returns:
        A :class:`DeviceRunResult` containing aggregate counts, the
        probe result, the resolved user-facing deploy mode, per-device
        wall-clock, and per-file results in test-plan order.  Early
        exits (transport creation failure, connect failure, bulk-stage
        failure) still return a populated result — ``files`` is
        whatever was completed before the exit.  The probe runs once
        right after ``connect()``; a probe failure never blocks the
        run.
    """
    result = DeviceRunResult(
        device=device_entry,
        passed=0,
        failed=0,
        errors=0,
        implementation=None,
        deploy_mode=_resolve_effective_deploy_mode(device_entry, deploy_mode),
    )
    device_start = time.perf_counter()

    def _finalize() -> DeviceRunResult:
        result.duration_seconds = time.perf_counter() - device_start
        return result

    # --- connect + probe ----------------------------------------------
    try:
        transport = _create_transport(device_entry, deploy_mode=deploy_mode)
    except ValueError as runtime_error:
        print(f"  Skipping — {runtime_error}")
        return _finalize()

    try:
        transport.connect()
    except Exception as connect_error:
        print(f"  Connection failed: {connect_error}")
        result.errors = 1
        return _finalize()

    # The probe feeds the PR summary; failure is never fatal — fall back
    # to the per-device metadata from ``devices.yml``.
    try:
        result.implementation = transport.probe_implementation()
    except Exception as probe_error:  # pragma: no cover - hardware-only
        print(f"  WARNING: Implementation probe failed: {probe_error}")

    # --- initial staging ----------------------------------------------
    use_per_library_staging = transport.mode == "ram"
    if not use_per_library_staging:
        bulk_stage_errors = _bulk_stage_test_plan(
            transport, test_plan, harness_source,
        )
        if bulk_stage_errors:
            transport.disconnect()
            result.errors = bulk_stage_errors
            return _finalize()

    # --- per-library loop ---------------------------------------------
    # Soft-reset between library groups evicts the previous library's
    # modules from the interpreter — both runtimes now hold a persistent
    # VM across files (raw REPL on CircuitPython, mpremote's persistent
    # SerialTransport on MicroPython), and without the reset ``sys.modules``
    # accumulates until low-memory boards fail their next bootstrap with
    # ``MemoryError``.
    abort = False
    previous_library_ran = False
    for library_name, source_dir, test_files in test_plan:
        if abort:
            break

        if previous_library_ran:
            try:
                transport.soft_reset()
            except Exception as reset_error:
                print(f"  WARNING: soft_reset failed between libraries: {reset_error}")

        if use_per_library_staging:
            failure_rows = _stage_library_for_test_files(
                transport, library_name, source_dir, test_files, harness_source,
            )
            if failure_rows is not None:
                result.files.extend(failure_rows)
                result.errors += len(failure_rows)
                continue

        for test_file in test_files:
            if abort:
                break
            file_result, abort = _run_single_test_file(
                device_entry, transport, library_name, test_file, function_filter,
            )
            result.files.append(file_result)
            result.passed += file_result.passed
            result.failed += file_result.failed
            result.errors += file_result.errors

        previous_library_ran = True

    _teardown_transport(transport)
    return _finalize()


def _resolve_selected_devices(
    all_devices,
    defaults: DeviceDefaults,
    runtime: str | None,
    micropython_device: str | None,
    circuitpython_device: str | None,
) -> list:
    """Resolve the device target set for the test-device CLI.

    Selection precedence:

    1. ``--runtime`` overrides which runtimes are active.
    2. ``--micropython-device`` / ``--circuitpython-device`` override the
       default board IDs for those runtimes.
    3. Remaining choices fall back to ``devices.yml`` defaults, then the first
       device of a runtime when no default ID is configured.

    Args:
        all_devices: Loaded device entries.
        defaults: Parsed ``devices.yml`` defaults section.
        runtime: Requested runtime set override.
        micropython_device: MicroPython device-ID override.
        circuitpython_device: CircuitPython device-ID override.

    Returns:
        Selected device entries in IDE/runtime order.
    """
    effective_defaults = DeviceDefaults(
        micropython=micropython_device or defaults.micropython,
        circuitpython=circuitpython_device or defaults.circuitpython,
        deploy_mode=defaults.deploy_mode,
        ide_runtime=runtime or defaults.ide_runtime,
    )
    return resolve_ide_devices(all_devices, effective_defaults)


def _format_test_device_command(
    runtime: str | None,
    micropython_device: str | None,
    circuitpython_device: str | None,
    library: str | None,
    file_filter: str | None,
    function_filter: str | None,
    deploy_mode: str | None,
) -> str:
    """Reconstruct the ``test-device`` CLI invocation from its args.

    Only includes flags the caller explicitly passed (non-``None`` values)
    so the rendered command matches what the user actually typed.

    Args:
        runtime: ``--runtime`` flag value, or ``None``.
        micropython_device: ``--micropython-device`` value, or ``None``.
        circuitpython_device: ``--circuitpython-device`` value, or ``None``.
        library: ``--library`` value, or ``None``.
        file_filter: ``--file`` value, or ``None``.
        function_filter: ``--test`` value, or ``None``.
        deploy_mode: ``--deploy-mode`` value, or ``None``.

    Returns:
        A single-line shell command, ready to drop into a PR body.
    """
    parts = ["python scripts/run.py test-device"]
    if runtime is not None:
        parts.append(f"--runtime {runtime}")
    if micropython_device is not None:
        parts.append(f"--micropython-device {micropython_device}")
    if circuitpython_device is not None:
        parts.append(f"--circuitpython-device {circuitpython_device}")
    if library is not None:
        parts.append(f"--library {library}")
    if file_filter is not None:
        parts.append(f"--file {file_filter}")
    if function_filter is not None:
        parts.append(f"--function {function_filter}")
    if deploy_mode is not None:
        parts.append(f"--deploy-mode {deploy_mode}")
    return " ".join(parts)


def _format_duration(seconds: float) -> str:
    """Format a wall-clock duration for PR summary output.

    Uses ``ms`` for sub-second values so per-test rows stay compact,
    ``s`` otherwise.  Keeps two-digit precision on seconds so readers
    can tell ``0.12s`` apart from ``1.20s``.

    Args:
        seconds: Elapsed seconds (non-negative).

    Returns:
        Short human label (e.g. ``"124ms"``, ``"3.42s"``).
    """
    if seconds < 1.0:
        return f"{int(round(seconds * 1000))}ms"
    return f"{seconds:.2f}s"


def _format_markdown_table(
    headers: list[str],
    rows: list[list[str]],
    alignments: list[str] | None = None,
) -> str:
    """Render a padded markdown table.

    Pads each cell with trailing (or leading, for right-aligned
    columns) spaces so columns align in monospace CLI output; the
    result still parses as a valid GitHub-flavored markdown table.
    The separator row gets a trailing ``:`` for right-aligned
    columns and a leading-plus-trailing ``:`` for centered ones, so
    GitHub renders the intended alignment.

    Args:
        headers: Column headers, one per column.
        rows: Data rows, each a list of strings aligned to *headers*.
        alignments: Per-column ``"left"`` / ``"right"`` / ``"center"``.
            Defaults to all-left.

    Returns:
        Multi-line markdown table string (no trailing newline).
    """
    if alignments is None:
        alignments = ["left"] * len(headers)

    # Column widths: max content width, bumped to a 3-char minimum
    # so the separator row can always render ``---``.
    widths: list[int] = []
    for column in range(len(headers)):
        cell_widths = [len(headers[column])]
        cell_widths.extend(len(row[column]) for row in rows)
        widths.append(max(max(cell_widths), 3))

    def pad(text: str, width: int, alignment: str) -> str:
        if alignment == "right":
            return text.rjust(width)
        if alignment == "center":
            return text.center(width)
        return text.ljust(width)

    def separator(width: int, alignment: str) -> str:
        if alignment == "right":
            return "-" * (width - 1) + ":"
        if alignment == "center":
            return ":" + "-" * (width - 2) + ":"
        return "-" * width

    lines = []
    header_cells = [
        pad(headers[column], widths[column], alignments[column])
        for column in range(len(headers))
    ]
    lines.append("| " + " | ".join(header_cells) + " |")
    separator_cells = [
        separator(widths[column], alignments[column])
        for column in range(len(headers))
    ]
    lines.append("| " + " | ".join(separator_cells) + " |")
    for row in rows:
        cells = [
            pad(row[column], widths[column], alignments[column])
            for column in range(len(row))
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


#: Summary table column headers, in render order.
_SUMMARY_HEADERS = [
    "Device", "Runtime", "Board", "Mode",
    "Passed", "Failed", "Errors", "Duration",
]
#: Per-column alignment for the summary table.
_SUMMARY_ALIGNMENTS = [
    "left", "left", "left", "left",
    "right", "right", "right", "right",
]
#: Per-file detail table headers.
_FILE_HEADERS = ["File", "Passed", "Failed", "Errors", "Duration"]
_FILE_ALIGNMENTS = ["left", "right", "right", "right", "right"]
#: Per-test detail table headers.
_TEST_HEADERS = ["Test", "Status", "Duration", "Notes"]
_TEST_ALIGNMENTS = ["left", "left", "right", "left"]


def _format_pr_summary_block(
    command: str,
    per_device_results: list[DeviceRunResult],
    total_duration_seconds: float | None = None,
) -> str:
    """Render a markdown block for the PR template's Device testing section.

    Layout::

        - Command: `...`
        - Duration: 12.34s

        | Device | Runtime | Board | Mode | Passed | Failed | Errors | Duration |
        | ... one row per device ...                                           |

        **Total: P passed, F failed, E errors**

        #### `<device>` — per-file breakdown (`<address>`)
        | File | Passed | Failed | Errors | Duration |
        | ... one row per file ...                    |

    Table rows are padded so the block is equally readable in a
    terminal (monospace) and on GitHub (rendered markdown).  A device
    with exactly one file gets a per-test table instead of per-file —
    the PASS / FAIL / SKIP status and duration of each method show so
    single-file runs surface method-level detail.  A device that
    crashed before running anything gets no detail section; its
    summary row is enough.

    Args:
        command: Reconstructed ``test-device`` invocation string.
        per_device_results: Per-device :class:`DeviceRunResult`
            instances in the order they ran.
        total_duration_seconds: Total wall-clock time for the whole
            invocation.  ``None`` omits the ``Duration:`` line — used
            by tests that render blocks without timing.

    Returns:
        Multi-line markdown body (no trailing newline).
    """
    lines = [f"- Command: `{command}`"]
    if total_duration_seconds is not None:
        lines.append(f"- Duration: {_format_duration(total_duration_seconds)}")

    if per_device_results:
        lines.append("")
        lines.append(_format_markdown_table(
            _SUMMARY_HEADERS,
            [_device_summary_row(device) for device in per_device_results],
            _SUMMARY_ALIGNMENTS,
        ))

    total_passed = sum(device.passed for device in per_device_results)
    total_failed = sum(device.failed for device in per_device_results)
    total_errors = sum(device.errors for device in per_device_results)
    lines.append("")
    lines.append(
        f"**Total: {total_passed} passed, {total_failed} failed, "
        f"{total_errors} errors**"
    )

    for device in per_device_results:
        detail = _format_device_detail_section(device)
        if detail:
            lines.append("")
            lines.append(detail)

    return "\n".join(lines)


def _device_summary_row(device: DeviceRunResult) -> list[str]:
    """Build one row of the device summary table."""
    entry = device.device
    runtime_label = _runtime_display_name(entry.runtime)
    implementation = device.implementation
    if implementation is not None and implementation.version:
        runtime_cell = f"{runtime_label} {implementation.version}"
    else:
        runtime_cell = runtime_label
    board_cell = implementation.machine if implementation is not None else ""
    return [
        f"`{entry.identifier}`",
        runtime_cell,
        board_cell,
        device.deploy_mode,
        str(device.passed),
        str(device.failed),
        str(device.errors),
        _format_duration(device.duration_seconds),
    ]


def _format_device_detail_section(device: DeviceRunResult) -> str:
    """Render the per-file or per-test detail section for one device.

    Decision rule (preserved from the earlier bullet format):

    - 0 files → no detail (device failed before running anything).
    - 1 file with test detail → per-test table.
    - 1 file without test detail (bulk-stage failure, unparsable
      output) → per-file table with the single row so readers see a
      placeholder instead of a missing section.
    - 2+ files → per-file table.
    """
    if not device.files:
        return ""
    heading = _detail_section_heading(device)
    if len(device.files) == 1 and device.files[0].tests:
        return (
            f"{heading}\n"
            + _format_markdown_table(
                _TEST_HEADERS,
                [_test_row(test) for test in device.files[0].tests],
                _TEST_ALIGNMENTS,
            )
        )
    return (
        f"{heading}\n"
        + _format_markdown_table(
            _FILE_HEADERS,
            [_file_row(file_result) for file_result in device.files],
            _FILE_ALIGNMENTS,
        )
    )


def _detail_section_heading(device: DeviceRunResult) -> str:
    """Return the ``#### ...`` heading line for a device's detail section."""
    entry = device.device
    subject = "per-test breakdown" if (
        len(device.files) == 1 and device.files[0].tests
    ) else "per-file breakdown"
    return f"#### `{entry.identifier}` — {subject} (`{entry.address}`)"


def _file_row(file_result: FileRunResult) -> list[str]:
    """One row of the per-file detail table."""
    return [
        f"`{file_result.library}/{file_result.file_name}`",
        str(file_result.passed),
        str(file_result.failed),
        str(file_result.errors),
        _format_duration(file_result.duration_seconds),
    ]


def _test_row(test_result: TestResult) -> list[str]:
    """One row of the per-test detail table."""
    duration_cell = (
        _format_duration(test_result.duration)
        if test_result.duration is not None else ""
    )
    return [
        f"`{test_result.name}`",
        test_result.status,
        duration_cell,
        test_result.message or "",
    ]


def _runtime_display_name(runtime_name: str) -> str:
    """Return a human-friendly runtime label for the PR summary."""
    return {
        "micropython": "MicroPython",
        "circuitpython": "CircuitPython",
    }.get(runtime_name, runtime_name)


def test_device(
    runtime: str | None = None,
    micropython_device: str | None = None,
    circuitpython_device: str | None = None,
    library: str | None = None,
    file_filter: str | None = None,
    function_filter: str | None = None,
    deploy_mode: str | None = None,
) -> int:
    """Run functional tests on connected devices.

    Args:
        runtime: Override which runtimes are active. Use ``"both"`` to
            request the MicroPython + CircuitPython target set explicitly.
        micropython_device: Override the selected MicroPython device ID.
        circuitpython_device: Override the selected CircuitPython device ID.
        library: Limit to a single library's functional tests.
        file_filter: Only run test files whose name contains this
            substring.  Matches file names only — use
            ``function_filter`` to filter by test-function name.
        function_filter: Only run test functions whose name contains
            this substring.  Used both to narrow which files are
            considered (files must define at least one matching
            function) and as the on-device ``run_module`` name filter
            so non-matching functions in kept files are skipped.
        deploy_mode: ``"ram"`` or ``"flash"``.  When ``None``, each
            device uses its own ``deploy_mode`` from ``devices.yml``
            (default ``"ram"``).

    Returns:
        0 for all-pass, 1 for any failure, 2 for configuration issues
        (no matching device, no matching test files, or unreadable
        ``devices.yml``).
    """
    # Load device registry.  Pass ROOT explicitly so device_config
    # remains decoupled from the workspace's repo layout (Decision 0028
    # extraction prep).
    try:
        all_devices, defaults = load_device_registry(workspace_root=ROOT)
    except DeviceConfigError as error:
        print(f"Device config error: {error}")
        return 2

    selected = _resolve_selected_devices(
        all_devices,
        defaults,
        runtime,
        micropython_device,
        circuitpython_device,
    )

    if not selected:
        print("No matching devices found.")
        if not all_devices:
            print(
                "Run 'python scripts/run.py setup' to generate "
                "devices.yml, then fill in your board details."
            )
        return 2

    # Discover functional tests.
    test_plan = discover_functional_tests(
        library=library,
        file_filter=file_filter,
        function_filter=function_filter,
    )
    if not test_plan:
        # When a filter was provided but yielded nothing, treat it as
        # a configuration error so CI and scripts don't silently pass.
        # Without a filter, an empty plan on a fresh project is still
        # a benign no-op.
        any_filter = bool(library or file_filter or function_filter)
        if any_filter:
            filter_parts = []
            if library:
                filter_parts.append(f"--library {library}")
            if file_filter:
                filter_parts.append(f"--file {file_filter}")
            if function_filter:
                filter_parts.append(f"--function {function_filter}")
            print(
                f"No functional tests matched: {', '.join(filter_parts)}"
            )
            return 2
        print("No functional test files found.")
        return 0

    harness_source = ROOT / "support" / "test_harness" / "src"

    # Run tests on each device.  The per-device loop is wrapped in
    # try/finally so the summary + PR block always print as long as
    # at least one device produced a row — even if a later device's
    # transport raises something unexpected mid-run.  Contributors used
    # to lose the summary entirely in that case.
    per_device_results: list[DeviceRunResult] = []
    command = _format_test_device_command(
        runtime, micropython_device, circuitpython_device,
        library, file_filter, function_filter, deploy_mode,
    )
    total_start = time.perf_counter()
    total_duration = 0.0

    try:
        for device_entry in selected:
            effective_deploy_mode = _resolve_effective_deploy_mode(
                device_entry, deploy_mode,
            )
            print(f"\n{'=' * 60}")
            print(
                f"Device: {device_entry.identifier} "
                f"({device_entry.runtime}, {effective_deploy_mode} mode)"
            )
            print(f"Address: {device_entry.address}")
            print(f"{'=' * 60}")

            try:
                device_result = _run_tests_on_device(
                    device_entry, test_plan, harness_source,
                    function_filter,
                    deploy_mode=deploy_mode,
                )
            except Exception as device_error:
                # One device crashing must not hide passing results from
                # other devices.  Record the crash as an error row and
                # move on.
                print(f"  FATAL: Device run raised: {device_error}")
                per_device_results.append(DeviceRunResult(
                    device=device_entry,
                    passed=0, failed=0, errors=1,
                    implementation=None,
                    deploy_mode=effective_deploy_mode,
                ))
                continue

            per_device_results.append(device_result)
    finally:
        total_duration = time.perf_counter() - total_start
        if per_device_results:
            _print_device_test_summary(
                command, per_device_results, total_duration,
            )

    total_failed = sum(device.failed for device in per_device_results)
    total_errors = sum(device.errors for device in per_device_results)
    return 1 if (total_failed or total_errors) else 0


def _print_device_test_summary(
    command: str,
    per_device_results: list[DeviceRunResult],
    total_duration_seconds: float,
) -> None:
    """Print the end-of-run totals banner and the paste-ready PR block.

    Always emits both — the banner for quick at-a-glance results and
    the PR block for dropping into the template.  Called from a
    ``finally`` in :func:`test_device` so partial results still
    surface when a later device run raises unexpectedly.

    Args:
        command: Reconstructed ``test-device`` CLI invocation.
        per_device_results: Per-device :class:`DeviceRunResult` rows.
        total_duration_seconds: Wall-clock time for the whole
            ``test-device`` invocation.
    """
    total_passed = sum(device.passed for device in per_device_results)
    total_failed = sum(device.failed for device in per_device_results)
    total_errors = sum(device.errors for device in per_device_results)

    print(f"\n{'=' * 60}")
    print(
        f"Device test summary: {total_passed} passed, "
        f"{total_failed} failed, {total_errors} errors "
        f"in {_format_duration(total_duration_seconds)}"
    )
    print(f"{'=' * 60}")

    pr_block = _format_pr_summary_block(
        command, per_device_results, total_duration_seconds,
    )
    print("\nPR summary (paste into the 'Device testing' section of your PR):")
    print("-" * 60)
    print(pr_block)
    print("-" * 60)
