"""Device testing orchestration for the test-device command.

Discovers functional tests, stages them on connected devices via the
appropriate transport, and reports results.  Extracted from ``run.py``
to keep the task runner thin and make orchestration logic independently
testable.

See Decision 0027 for the transport protocol and config schema.
"""

from __future__ import annotations

import ast
from pathlib import Path

from device_config import (
    DeviceConfigError,
    DeviceDefaults,
    load_device_registry,
    resolve_ide_devices,
)
from result_parser import parse_output
from workspace import ROOT, discover_library_dirs, load_tomllib


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
    effective_mode = deploy_mode or device_entry.deploy_mode

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
):
    """Run all planned tests on a single device.

    Args:
        device_entry: A DeviceEntry from the config loader.
        test_plan: List of ``(library_name, source_dir, test_files)``.
        harness_source: Path to the test harness ``src/`` directory.
        test_filter: Optional name filter for ``run_module``.
        deploy_mode: ``"ram"`` or ``"flash"``.  When ``None``, uses the
            device entry's ``deploy_mode`` field.

    Returns:
        Tuple of ``(passed, failed, errors, implementation)`` counts
        plus a :class:`DeviceImplementation` (or ``None`` if the probe
        could not complete).  The probe runs once right after
        ``connect()``; a probe failure never blocks the test run.
    """
    passed = 0
    failed = 0
    errors = 0
    implementation = None

    try:
        transport = _create_transport(device_entry, deploy_mode=deploy_mode)
    except ValueError as runtime_error:
        print(f"  Skipping — {runtime_error}")
        return passed, failed, errors, implementation

    try:
        transport.connect()
    except Exception as connect_error:
        print(f"  Connection failed: {connect_error}")
        return 0, 0, 1, implementation

    # Probe the board's ``sys.implementation`` once per session so the
    # PR summary can show the exact firmware version and board model.
    # Never fatal — if the probe fails, the summary simply falls back
    # to the per-device metadata from ``devices.yml``.
    if hasattr(transport, "probe_implementation"):
        try:
            implementation = transport.probe_implementation()
        except Exception as probe_error:  # pragma: no cover - hardware-only
            print(f"  WARNING: Implementation probe failed: {probe_error}")
            implementation = None

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
            return 0, 0, len(all_test_files), implementation

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
                errors += len(test_files)
                continue

        for test_file in test_files:
            if abort:
                break
            print(f"\n  {library_name}/{test_file.name}")

            try:
                bootstrap = _build_device_bootstrap(
                    device_entry, transport, test_file, test_filter,
                )
                raw_output = _execute_device_bootstrap(transport, bootstrap)
                print(raw_output)

                result = parse_output(raw_output)
                if result.summary:
                    passed += result.summary.total - result.summary.failed
                    failed += result.summary.failed
                else:
                    print("  WARNING: No summary line in output.")
                    errors += 1

            except Exception as run_error:
                print(f"  ERROR: {run_error}")
                errors += 1
                # Try to recover raw REPL so the next test can run.
                try:
                    transport.recover()
                except Exception as recover_error:
                    print(f"  FATAL: Cannot recover board state: {recover_error}")
                    print("  Aborting remaining tests on this device.")
                    abort = True

        previous_library_ran = True

    try:
        transport.reset()
    except Exception as reset_error:
        print(f"  WARNING: Failed to reset device after test run: {reset_error}")
    transport.disconnect()

    return passed, failed, errors, implementation


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


def _format_pr_summary_block(
    command: str,
    per_device_results: list[tuple[object, int, int, int, object]],
) -> str:
    """Render a markdown block for the PR template's Device testing section.

    Drop-in paste for the ``## Device testing`` section of
    ``.github/PULL_REQUEST_TEMPLATE.md``.  Each line is one bullet; the
    command goes first, each device gets its own line, and the bold
    total is last.

    When the device's ``probe_implementation`` succeeded, the bullet
    includes the firmware version and board model reported by
    ``sys.implementation`` — reviewers no longer have to cross-reference
    ``devices.yml`` to learn what actually ran.

    Args:
        command: Reconstructed ``test-device`` invocation string.
        per_device_results: Per-device tuples of
            ``(device_entry, passed, failed, errors, implementation)``
            where ``implementation`` is a
            :class:`chumicro_device_transport.DeviceImplementation` or
            ``None``.

    Returns:
        Multi-line markdown body (no trailing newline).
    """
    lines = [f"- Command: `{command}`"]
    total_passed = 0
    total_failed = 0
    total_errors = 0
    for device_entry, passed, failed, errors, implementation in per_device_results:
        runtime_label = _runtime_display_name(device_entry.runtime)
        if implementation is not None:
            firmware = f"{runtime_label} {implementation.version}"
            if implementation.machine:
                firmware += f" on {implementation.machine}"
        else:
            firmware = runtime_label
        lines.append(
            f"- `{device_entry.identifier}` ({firmware}, "
            f"`{device_entry.address}`): "
            f"{passed} passed, {failed} failed, {errors} errors"
        )
        total_passed += passed
        total_failed += failed
        total_errors += errors
    lines.append(
        f"- **Total: {total_passed} passed, {total_failed} failed, "
        f"{total_errors} errors**"
    )
    return "\n".join(lines)


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

    # Run tests on each device.
    per_device_results: list[tuple[object, int, int, int, object]] = []

    for device_entry in selected:
        print(f"\n{'=' * 60}")
        print(
            f"Device: {device_entry.identifier} "
            f"({device_entry.runtime})"
        )
        print(f"Address: {device_entry.address}")
        print(f"{'=' * 60}")

        passed, failed, errors, implementation = _run_tests_on_device(
            device_entry, test_plan, harness_source, test_filter,
            deploy_mode=deploy_mode,
        )
        per_device_results.append(
            (device_entry, passed, failed, errors, implementation),
        )

    total_passed = sum(passed for _, passed, _, _, _ in per_device_results)
    total_failed = sum(failed for _, _, failed, _, _ in per_device_results)
    total_errors = sum(errors for _, _, _, errors, _ in per_device_results)

    # Final summary.
    print(f"\n{'=' * 60}")
    print(
        f"Device test summary: {total_passed} passed, "
        f"{total_failed} failed, {total_errors} errors"
    )
    print(f"{'=' * 60}")

    # Paste-ready block for the PR template's ``## Device testing``
    # section.  Reviewers ask for board, runtime, command, and counts;
    # this renders all four in markdown so contributors don't hand-fill
    # the section from the console log.
    command = _format_test_device_command(
        runtime, micropython_device, circuitpython_device,
        library, test_filter, deploy_mode,
    )
    pr_block = _format_pr_summary_block(command, per_device_results)
    print("\nPR summary (paste into the 'Device testing' section of your PR):")
    print("-" * 60)
    print(pr_block)
    print("-" * 60)

    return 1 if (total_failed or total_errors) else 0
