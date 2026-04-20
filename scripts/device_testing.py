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

from device_config import (
    DeviceConfigError,
    DeviceDefaults,
    load_device_registry,
    resolve_ide_devices,
)
from result_parser import TestResult, parse_output
from workspace import ROOT, discover_library_dirs, load_tomllib


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

    device: object
    passed: int
    failed: int
    errors: int
    implementation: object | None
    deploy_mode: str
    duration_seconds: float = 0.0
    files: list[FileRunResult] = field(default_factory=list)


def discover_functional_tests(
    *,
    library: str | None = None,
    test_filter: str | None = None,
) -> list[tuple[str, Path, list[Path]]]:
    """Discover functional test files across libraries.

    Args:
        library: Limit to a single library name.
        test_filter: Only include test files whose filename or ``test_*``
            function names contain this substring.

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
        if test_filter:
            test_files = [
                path for path in test_files
                if _functional_test_matches_filter(path, test_filter)
            ]
        if test_files:
            source_dir = library_dir / "src"
            test_plan.append((library_dir.name, source_dir, test_files))

    return test_plan


def _functional_test_matches_filter(test_file: Path, test_filter: str) -> bool:
    """Return whether a functional test file matches a CLI filter.

    Args:
        test_file: Path to a ``functional_tests/test_*.py`` file.
        test_filter: User-provided substring filter.

    Returns:
        ``True`` when the filename or any module-level ``test_*`` function
        name contains the filter substring.
    """
    if test_filter in test_file.name:
        return True

    source_text = test_file.read_text(encoding="utf-8")
    syntax_tree = ast.parse(source_text, filename=str(test_file))
    for node in ast.iter_child_nodes(syntax_tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if not node.name.startswith("test_"):
            continue
        if test_filter in node.name:
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


def _library_name_for_chumicro_module(module_name: str) -> str | None:
    """Return the workspace library name for a `chumicro_*` module.

    Args:
        module_name: Imported module name.

    Returns:
        The library directory name, or ``None`` for non-ChuMicro modules.
    """
    if not module_name.startswith("chumicro_"):
        return None
    suffix = module_name.removeprefix("chumicro_")
    return suffix.split(".", 1)[0]


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
                    library_name = _library_name_for_chumicro_module(alias.name)
                    if library_name is not None:
                        imported_library_names.add(library_name)
            elif isinstance(node, ast.ImportFrom):
                if node.module is None:
                    continue
                library_name = _library_name_for_chumicro_module(node.module)
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
            dependency_name = dependency.strip()
            if not dependency_name.startswith("chumicro-"):
                continue
            # "chumicro-timing>=0.1" → "timing"
            bare_name = dependency_name.split(">")[0].split("<")[0]
            bare_name = bare_name.split("=")[0].split("!")[0].strip()
            dependency_library_names.append(
                bare_name.removeprefix("chumicro-")
            )

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
    device_entry,
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


def _create_transport(device_entry, deploy_mode: str | None = None):
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
    device_entry,
    transport,
    test_file,
    test_filter,
):
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
        test_filter: Optional name filter for ``run_module``.

    Returns:
        Python source code string, or a list of chunked raw-REPL scripts for
        CircuitPython RAM mode.
    """
    if device_entry.runtime == "circuitpython" and transport.mode == "ram":
        from chumicro_device_transport import build_circuitpython_bootstrap_scripts

        max_chunk_size_bytes = None
        if hasattr(transport, "inline_script_budget_bytes"):
            max_chunk_size_bytes = transport.inline_script_budget_bytes()

        if max_chunk_size_bytes is None:
            return build_circuitpython_bootstrap_scripts(
                transport.staged_sources,
                test_file,
                name_filter=test_filter,
            )

        return build_circuitpython_bootstrap_scripts(
            transport.staged_sources,
            test_file,
            name_filter=test_filter,
            max_chunk_size_bytes=max_chunk_size_bytes,
        )

    return build_bootstrap(
        test_file.name,
        name_filter=test_filter,
    )


def _execute_device_bootstrap(transport, bootstrap):
    """Execute either a single bootstrap script or a chunked script sequence."""
    if isinstance(bootstrap, list):
        if hasattr(transport, "execute_scripts"):
            return transport.execute_scripts(bootstrap)

        last_output = ""
        for bootstrap_script in bootstrap:
            last_output = transport.execute(bootstrap_script)
        return last_output

    return transport.execute(bootstrap)


def _run_tests_on_device(
    device_entry,
    test_plan,
    harness_source,
    test_filter,
    deploy_mode=None,
) -> DeviceRunResult:
    """Run all planned tests on a single device.

    Args:
        device_entry: A DeviceEntry from the config loader.
        test_plan: List of ``(library_name, source_dir, test_files)``.
        harness_source: Path to the test harness ``src/`` directory.
        test_filter: Optional name filter for ``run_module``.
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
    effective_deploy_mode = _resolve_effective_deploy_mode(
        device_entry, deploy_mode,
    )

    result = DeviceRunResult(
        device=device_entry,
        passed=0,
        failed=0,
        errors=0,
        implementation=None,
        deploy_mode=effective_deploy_mode,
    )
    device_start = time.perf_counter()

    def _finalize() -> DeviceRunResult:
        result.duration_seconds = time.perf_counter() - device_start
        return result

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

    # Probe the board's ``sys.implementation`` once per session so the
    # PR summary can show the exact firmware version and board model.
    # Never fatal — if the probe fails, the summary simply falls back
    # to the per-device metadata from ``devices.yml``.
    if hasattr(transport, "probe_implementation"):
        try:
            result.implementation = transport.probe_implementation()
        except Exception as probe_error:  # pragma: no cover - hardware-only
            print(f"  WARNING: Implementation probe failed: {probe_error}")

    # RAM mode sends all source code inline through the serial REPL,
    # so we re-stage per library with only the source dirs that library
    # actually needs (itself + its intra-workspace dependencies).
    # Flash mode (and MicroPython mount mode) can stage everything once
    # since files live on disk, not in RAM.
    use_per_library_staging = (
        hasattr(transport, "mode") and transport.mode == "ram"
    )

    if not use_per_library_staging:
        source_dirs = [
            library_dir / "src"
            for library_dir in discover_library_dirs()
            if (library_dir / "src").is_dir()
        ]

        # Collect all test files across libraries and stage them in one
        # rsync pass.  Running stage() per test file would re-sync the
        # entire drive for each test — expensive on FAT32 USB drives.
        all_test_files = [
            test_file
            for _library_name, _source_dir, test_files in test_plan
            for test_file in test_files
        ]

        try:
            transport.stage(source_dirs, all_test_files, harness_source)
        except Exception as stage_error:
            print(f"  Stage failed: {stage_error}")
            transport.disconnect()
            result.errors = len(all_test_files)
            return _finalize()

    abort = False
    previous_library_ran = False
    for library_name, source_dir, test_files in test_plan:
        if abort:
            break

        # Soft-reset between library groups so modules from the
        # previous library are evicted from the interpreter.  This
        # ensures test isolation (no stale ``sys.modules`` from an
        # earlier library) and reclaims heap on constrained boards
        # before the next library runs.
        #
        # Both runtimes now hold a persistent interpreter across
        # files (CircuitPython via raw REPL, MicroPython via
        # ``mpremote``'s persistent ``SerialTransport``), so both
        # need this reset.  The reset is a VM-level Ctrl-D — it does
        # not toggle USB or re-enumerate the CDC.  (The older
        # ``mpremote reset`` subprocess path *did* cause USB drops;
        # the persistent-serial ``soft_reset`` does not.)
        needs_soft_reset = (
            previous_library_ran
            and hasattr(transport, "soft_reset")
        )
        if needs_soft_reset:
            try:
                transport.soft_reset()
            except Exception as reset_error:
                print(f"  WARNING: soft_reset failed between libraries: {reset_error}")

        if use_per_library_staging:
            # Resolve only the source dirs this library needs.
            library_dir = source_dir.parent
            library_source_dirs = _resolve_library_source_dirs(
                library_dir, test_files=test_files,
            )
            try:
                transport.stage(
                    library_source_dirs, test_files, harness_source,
                )
            except Exception as stage_error:
                print(f"  Stage failed for {library_name}: {stage_error}")
                for test_file in test_files:
                    result.files.append(FileRunResult(
                        library=library_name,
                        file_name=test_file.name,
                        passed=0, failed=0, errors=1,
                    ))
                result.errors += len(test_files)
                continue

        for test_file in test_files:
            if abort:
                break
            print(f"\n  {library_name}/{test_file.name}")
            file_start = time.perf_counter()
            file_passed = 0
            file_failed = 0
            file_errors = 0
            file_tests: list[TestResult] = []

            try:
                bootstrap = _build_device_bootstrap(
                    device_entry, transport, test_file, test_filter,
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

            result.files.append(FileRunResult(
                library=library_name,
                file_name=test_file.name,
                passed=file_passed,
                failed=file_failed,
                errors=file_errors,
                tests=file_tests,
                duration_seconds=time.perf_counter() - file_start,
            ))
            result.passed += file_passed
            result.failed += file_failed
            result.errors += file_errors

        previous_library_ran = True

    try:
        transport.reset()
    except Exception as reset_error:
        print(f"  WARNING: Failed to reset device after test run: {reset_error}")
    try:
        transport.disconnect()
    except Exception as disconnect_error:  # pragma: no cover - hardware-only
        # A disconnect raise used to propagate all the way up and skip
        # the final PR summary.  Swallow it — the serial port will be
        # reclaimed on process exit if nothing else.
        print(
            f"  WARNING: Failed to disconnect device cleanly: "
            f"{disconnect_error}"
        )

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
    test_filter: str | None,
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
        test_filter: ``--test`` value, or ``None``.
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
    if test_filter is not None:
        parts.append(f"--test {test_filter}")
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
    test_filter: str | None = None,
    deploy_mode: str | None = None,
) -> int:
    """Run functional tests on connected devices.

    Args:
        runtime: Override which runtimes are active. Use ``"both"`` to
            request the MicroPython + CircuitPython target set explicitly.
        micropython_device: Override the selected MicroPython device ID.
        circuitpython_device: Override the selected CircuitPython device ID.
        library: Limit to a single library's functional tests.
        test_filter: Filter to test files or functions matching this
            substring.
        deploy_mode: ``"ram"`` or ``"flash"``.  When ``None``, each
            device uses its own ``deploy_mode`` from ``devices.yml``
            (default ``"ram"``).

    Returns:
        0 for all-pass, 1 for any failure, 2 for configuration issues.
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
        library=library, test_filter=test_filter,
    )
    if not test_plan:
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
        library, test_filter, deploy_mode,
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
                    device_entry, test_plan, harness_source, test_filter,
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
