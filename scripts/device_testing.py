"""Device testing orchestration for the test-device command.

Discovers functional tests, stages them on connected devices via the
appropriate transport, and reports results.  Extracted from ``run.py``
to keep the task runner thin and make orchestration logic independently
testable.

See Decision 0027 for the transport protocol and config schema.
"""

from __future__ import annotations

import sys
from pathlib import Path

from device_config import DeviceConfigError, filter_devices, load_devices
from result_parser import parse_output
from workspace import ROOT


def _ensure_support_importable() -> None:
    """Add support package source roots to sys.path if not already present.

    Support packages are not installed via pip — they rely on PYTHONPATH
    or sys.path manipulation.  This mirrors the approach used by
    ``conftest.py`` and the IDE sync configs.
    """
    support_dir = ROOT / "support"
    if not support_dir.is_dir():
        return
    for child in sorted(support_dir.iterdir()):
        source_dir = child / "src"
        source_str = str(source_dir)
        if source_dir.is_dir() and source_str not in sys.path:
            sys.path.insert(0, source_str)


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


def collect_source_dirs(primary_source: Path) -> list[Path]:
    """Collect all library source directories, with *primary_source* first.

    Device tests may import from any library, so all ``src/`` directories
    are staged.  The primary library's source comes first.

    Args:
        primary_source: The ``src/`` directory of the library under test.

    Returns:
        Ordered list of source directories.
    """
    libraries_root = ROOT / "libraries"
    source_dirs = [primary_source]
    for dependency_dir in sorted(libraries_root.iterdir()):
        dependency_source = dependency_dir / "src"
        if dependency_source.is_dir() and dependency_source != primary_source:
            source_dirs.append(dependency_source)
    return source_dirs


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
        "import sys\n"
        "from chumicro_test_harness.runner import run_module\n"
        "from chumicro_test_harness.discovery import _exec_as_namespace\n"
        f"module = _exec_as_namespace('{test_filename}')\n"
        f"result = run_module(module, name_filter={filter_repr})\n"
        "sys.exit(result)\n"
    )


def _create_transport(device_entry, deploy_mode: str = "ram"):
    """Create the appropriate transport for a device entry.

    Args:
        device_entry: A DeviceEntry from the config loader.
        deploy_mode: ``"ram"`` (default) or ``"flash"``.

    Returns:
        A transport instance for the device's runtime.

    Raises:
        ValueError: If the runtime is not supported or flash mode
            is missing required configuration.
    """
    _ensure_support_importable()

    if device_entry.runtime == "micropython":
        from chumicro_device_transport import MicropythonTransport

        # Map deploy mode to MicroPython transport mode.
        transport_mode = "mount" if deploy_mode == "ram" else "copy"
        return MicropythonTransport(
            device_entry.address,
            mode=transport_mode,
        )

    if device_entry.runtime == "circuitpython":
        from chumicro_device_transport import CircuitpythonTransport

        return CircuitpythonTransport(
            device_entry.address,
            baudrate=device_entry.serial_baudrate,
            mode=deploy_mode,
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
    deploy_mode="ram",
):
    """Run all planned tests on a single device.

    Args:
        device_entry: A DeviceEntry from the config loader.
        test_plan: List of ``(library_name, source_dir, test_files)``.
        harness_source: Path to the test harness ``src/`` directory.
        test_filter: Optional name filter for ``run_module``.
        deploy_mode: ``"ram"`` or ``"flash"``.

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

    for library_name, source_dir, test_files in test_plan:
        source_dirs = collect_source_dirs(source_dir)

        for test_file in test_files:
            print(f"\n  {library_name}/{test_file.name}")

            try:
                transport.stage(source_dirs, [test_file], harness_source)
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

    try:
        transport.reset()
    except Exception:
        pass  # Best-effort reset.
    transport.disconnect()

    return passed, failed, errors


def test_device(
    runtime: str | None = None,
    device: str | None = None,
    library: str | None = None,
    test_filter: str | None = None,
    deploy_mode: str = "ram",
) -> int:
    """Run functional tests on connected devices.

    Args:
        runtime: Filter to devices matching this runtime.
        device: Filter to the device with this ID.
        library: Limit to a single library's functional tests.
        test_filter: Filter to test files or functions matching this
            substring.
        deploy_mode: ``"ram"`` (default) or ``"flash"``.

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
                "Copy devices.example.yml to devices.yml "
                "and fill in your board details."
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

