"""Device testing orchestration for the test-device command.

Discovers functional tests, stages them on connected devices via the
appropriate transport, and reports results.  Extracted from ``run.py``
to keep the task runner thin and make orchestration logic independently
testable.

See Decision 0027 for the transport protocol and config schema.
"""

from __future__ import annotations

from pathlib import Path

from device_config import DeviceConfigError, filter_devices, load_devices
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
        test_filter: Only include test files whose name contains this
            substring.

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
                if test_filter in path.name
            ]
        if test_files:
            source_dir = library_dir / "src"
            test_plan.append((library_dir.name, source_dir, test_files))

    return test_plan


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


def _resolve_library_source_dirs(library_dir: Path) -> list[Path]:
    """Return source dirs for a library and its intra-workspace dependencies.

    Reads ``project.dependencies`` from the library's ``pyproject.toml``
    and resolves any ``chumicro-*`` entries to their ``src/`` directories.
    This provides the minimal set of source directories needed to run
    the library's tests — critical for RAM mode where all source code
    is sent inline through the serial REPL.

    Args:
        library_dir: Root directory of the library (e.g.
            ``libraries/runner``).

    Returns:
        List of ``src/`` directories: the library's own plus
        any intra-workspace dependencies, in dependency-first order.
    """
    libraries_root = ROOT / "libraries"
    tomllib = load_tomllib()

    # Read the library's own dependencies.
    pyproject_file = library_dir / "pyproject.toml"
    dependency_dirs: list[Path] = []
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
            library_name = bare_name.removeprefix("chumicro-")
            dependency_source = libraries_root / library_name / "src"
            if dependency_source.is_dir():
                # Recurse to pick up transitive dependencies.
                for transitive_dir in _resolve_library_source_dirs(
                    libraries_root / library_name,
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
        Python source code string for the bootstrap script.
    """
    if device_entry.runtime == "circuitpython" and transport.mode == "ram":
        from chumicro_device_transport import build_circuitpython_bootstrap

        return build_circuitpython_bootstrap(
            transport.staged_sources,
            test_file,
            name_filter=test_filter,
        )

    return build_bootstrap(
        test_file.name,
        name_filter=test_filter,
    )


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
        Tuple of ``(passed, failed, errors)`` counts.
    """
    passed = 0
    failed = 0
    errors = 0

    try:
        transport = _create_transport(device_entry, deploy_mode=deploy_mode)
    except ValueError as runtime_error:
        print(f"  Skipping — {runtime_error}")
        return passed, failed, errors

    try:
        transport.connect()
    except Exception as connect_error:
        print(f"  Connection failed: {connect_error}")
        return 0, 0, 1

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
            return 0, 0, len(all_test_files)

    abort = False
    previous_library_ran = False
    for library_name, source_dir, test_files in test_plan:
        if abort:
            break

        if use_per_library_staging:
            # Soft-reset between library groups so modules from the
            # previous library are evicted from the interpreter.  This
            # prevents RAM accumulation and ensures test isolation.
            if previous_library_ran:
                try:
                    transport.soft_reset()
                except Exception as reset_error:
                    print(f"  WARNING: soft_reset failed between libraries: {reset_error}")

            # Resolve only the source dirs this library needs.
            library_dir = source_dir.parent
            library_source_dirs = _resolve_library_source_dirs(library_dir)
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
                raw_output = transport.execute(bootstrap)
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

        if use_per_library_staging:
            previous_library_ran = True

    try:
        transport.reset()
    except Exception as reset_error:
        print(f"  WARNING: Failed to reset device after test run: {reset_error}")
    transport.disconnect()

    return passed, failed, errors


def test_device(
    runtime: str | None = None,
    device: str | None = None,
    library: str | None = None,
    test_filter: str | None = None,
    deploy_mode: str | None = None,
) -> int:
    """Run functional tests on connected devices.

    Args:
        runtime: Filter to devices matching this runtime.
        device: Filter to the device with this ID.
        library: Limit to a single library's functional tests.
        test_filter: Filter to test files or functions matching this
            substring.
        deploy_mode: ``"ram"`` or ``"flash"``.  When ``None``, each
            device uses its own ``deploy_mode`` from ``devices.yml``
            (default ``"ram"``).

    Returns:
        0 for all-pass, 1 for any failure, 2 for configuration issues.
    """
    # Load device registry.
    try:
        all_devices = load_devices()
    except DeviceConfigError as error:
        print(f"Device config error: {error}")
        return 2

    # Filter devices.
    selected = filter_devices(all_devices, runtime=runtime, device_id=device)
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
    total_passed = 0
    total_failed = 0
    total_errors = 0

    for device_entry in selected:
        print(f"\n{'=' * 60}")
        print(
            f"Device: {device_entry.identifier} "
            f"({device_entry.runtime})"
        )
        print(f"Address: {device_entry.address}")
        print(f"{'=' * 60}")

        passed, failed, errors = _run_tests_on_device(
            device_entry, test_plan, harness_source, test_filter,
            deploy_mode=deploy_mode,
        )
        total_passed += passed
        total_failed += failed
        total_errors += errors

    # Final summary.
    print(f"\n{'=' * 60}")
    print(
        f"Device test summary: {total_passed} passed, "
        f"{total_failed} failed, {total_errors} errors"
    )
    print(f"{'=' * 60}")

    return 1 if (total_failed or total_errors) else 0
