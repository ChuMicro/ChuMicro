"""Pytest plugin for routing functional tests to real hardware.

When pytest collects a file from a ``functional_tests/`` directory,
this plugin intercepts it and wraps each ``test_*`` function as a
:class:`DeviceTestItem`.  Instead of importing and running the test
locally, the item stages source code on a connected board, executes
the test via the device transport, and parses the harness output to
report pass/fail to pytest.

**No environment variable setup is required.**  The plugin reads
``devices.yml`` to find the target device.  Optional env vars
(``CHUMICRO_DEVICE_RUNTIME``, ``CHUMICRO_DEVICE_ID``,
``CHUMICRO_DEPLOY_MODE``) narrow the selection when multiple boards
are configured.

This enables IDE play buttons (PyCharm, VS Code) to run device
tests at file and function granularity — just click play.

See Decision 0027 (IDE integration section).
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest
from device_config import DeviceConfigError, filter_devices, load_devices
from device_testing import (
    _build_device_bootstrap,
    _create_transport,
    _resolve_library_source_dirs,
)
from result_parser import parse_output
from workspace import ROOT

#: Optional env var to filter devices by runtime.
RUNTIME_ENV_VAR = "CHUMICRO_DEVICE_RUNTIME"
#: Optional env var to target a specific device by ID.
DEVICE_ID_ENV_VAR = "CHUMICRO_DEVICE_ID"
#: Optional env var to override deploy mode (ram/flash).
DEPLOY_MODE_ENV_VAR = "CHUMICRO_DEPLOY_MODE"

#: Path to the test harness source directory.
HARNESS_SOURCE = ROOT / "support" / "test_harness" / "src"


def _parse_test_functions(filepath: Path) -> list[str]:
    """Use AST to discover test function names without importing.

    Functional test files import device-only modules that are not
    available on the host, so we cannot import them.

    Args:
        filepath: Path to the test file.

    Returns:
        Sorted list of ``test_*`` function names defined at module
        level.
    """
    source = filepath.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(filepath))
    return sorted(
        node.name
        for node in ast.iter_child_nodes(tree)
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    )


def _resolve_library_dir(test_file: Path) -> Path:
    """Derive the library root directory from a functional test file path.

    Expects the pattern ``libraries/<name>/functional_tests/test_*.py``.

    Args:
        test_file: Path to a test file inside ``functional_tests/``.

    Returns:
        The library root directory (e.g. ``libraries/timing``).
    """
    return test_file.parent.parent


def _load_target_device():
    """Load devices.yml and return the best matching device entry.

    Uses optional environment variables to narrow the selection:

    - ``CHUMICRO_DEVICE_RUNTIME`` — filter by runtime
    - ``CHUMICRO_DEVICE_ID`` — filter by device ID

    Returns:
        A ``DeviceEntry`` from the device registry.

    Raises:
        pytest.skip: If no devices.yml exists or no devices match.
        pytest.fail: If devices.yml is malformed.
    """
    runtime = os.environ.get(RUNTIME_ENV_VAR)
    device_id = os.environ.get(DEVICE_ID_ENV_VAR)

    try:
        all_devices = load_devices()
    except DeviceConfigError as error:
        error_message = str(error)
        if "not found" in error_message:
            pytest.skip(
                "No devices.yml found.  Run 'python scripts/run.py setup' "
                "and configure your board to run functional tests on hardware."
            )
        pytest.fail(f"Device config error: {error}")

    selected = filter_devices(
        all_devices, runtime=runtime, device_id=device_id,
    )
    if not selected:
        if runtime or device_id:
            pytest.skip(
                f"No device matches runtime={runtime!r}, "
                f"device_id={device_id!r}.  "
                f"Check devices.yml or remove filter env vars."
            )
        pytest.skip(
            "No devices configured in devices.yml.  "
            "Add your board details to run functional tests on hardware."
        )

    return selected[0]


class _TransportCache:
    """Session-scoped cache for device transports.

    Avoids reconnecting for every test item.  Stores one transport
    per device ID and tracks the last-staged library to avoid
    redundant staging.
    """

    def __init__(self) -> None:
        self._transports: dict[str, object] = {}
        self._last_staged_library: dict[str, str] = {}

    def get_transport(self, device_entry, deploy_mode: str | None):
        """Get or create a connected transport for the device.

        Args:
            device_entry: A ``DeviceEntry`` from the config loader.
            deploy_mode: Deploy mode override, or ``None``.

        Returns:
            A connected transport instance.
        """
        key = device_entry.identifier
        if key not in self._transports:
            transport = _create_transport(device_entry, deploy_mode=deploy_mode)
            transport.connect()
            self._transports[key] = transport
        return self._transports[key]

    def needs_staging(self, device_id: str, library_name: str) -> bool:
        """Check whether the library needs to be staged on this device.

        Args:
            device_id: Device identifier.
            library_name: Library name.

        Returns:
            ``True`` if the library has not been staged yet.
        """
        return self._last_staged_library.get(device_id) != library_name

    def mark_staged(self, device_id: str, library_name: str) -> None:
        """Record that a library has been staged on a device.

        Args:
            device_id: Device identifier.
            library_name: Library name.
        """
        self._last_staged_library[device_id] = library_name

    def disconnect_all(self) -> None:
        """Reset and disconnect all cached transports."""
        for transport in self._transports.values():
            try:
                if hasattr(transport, "reset"):
                    transport.reset()
            except Exception:  # pragma: no cover
                pass
            try:
                transport.disconnect()
            except Exception:  # pragma: no cover
                pass
        self._transports.clear()
        self._last_staged_library.clear()


class DeviceTestFile(pytest.File):
    """Collector that discovers ``test_*`` functions via AST parsing."""

    def collect(self):
        """Yield a :class:`DeviceTestItem` for each ``test_*`` function."""
        function_names = _parse_test_functions(self.path)
        for name in function_names:
            yield DeviceTestItem.from_parent(
                self,
                name=name,
                test_file=self.path,
            )


class DeviceTestItem(pytest.Item):
    """A single test function that runs on a real device.

    Stages library source to the device, sends a bootstrap script
    that invokes the test harness with ``name_filter`` set to this
    test function, parses the structured output, and reports
    pass/fail to pytest.
    """

    def __init__(self, *, test_file: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self.test_file = test_file
        self._library_dir = _resolve_library_dir(test_file)
        self._library_name = self._library_dir.name

    def runtest(self) -> None:
        """Execute the test on a connected device."""
        deploy_mode = os.environ.get(DEPLOY_MODE_ENV_VAR)
        device_entry = _load_target_device()

        cache: _TransportCache = self.session._device_transport_cache  # type: ignore[attr-defined]

        try:
            transport = cache.get_transport(device_entry, deploy_mode)
        except Exception as error:
            pytest.fail(f"Transport connection failed: {error}")

        # Stage library source if needed.
        if cache.needs_staging(device_entry.identifier, self._library_name):
            source_dirs = _resolve_library_source_dirs(self._library_dir)
            transport.stage(
                source_dirs, [self.test_file], HARNESS_SOURCE,
            )
            cache.mark_staged(device_entry.identifier, self._library_name)

        # Build and execute bootstrap with name_filter for this
        # specific test function.
        bootstrap = _build_device_bootstrap(
            device_entry, transport, self.test_file, self.name,
        )
        raw_output = transport.execute(bootstrap)

        # Parse harness output.
        result = parse_output(raw_output)

        if not result.tests:
            pytest.fail(
                f"No test results in device output:\n{raw_output}"
            )

        # Find this specific test in the results.
        for test_result in result.tests:
            if test_result.name == self.name:
                if test_result.status == "FAIL":
                    pytest.fail(
                        f"Device test FAIL: {self.name}\n{raw_output}"
                    )
                if test_result.status == "SKIP":
                    pytest.skip(test_result.message or "Skipped on device")
                return

        # Test name not found in output — may have been filtered or
        # errored before reaching the harness.
        pytest.fail(
            f"Test {self.name!r} not found in device output:\n{raw_output}"
        )

    def repr_failure(self, excinfo, style=None):
        """Produce a readable failure representation."""
        return str(excinfo.value)

    def reportinfo(self):
        """Return location info for test reporting."""
        return self.path, None, f"[device] {self._library_name}::{self.name}"


# ---------------------------------------------------------------------------
# Pytest hooks
# ---------------------------------------------------------------------------


def pytest_collect_file(parent, file_path):
    """Collect functional test files as device test items.

    Activates for any ``test_*.py`` file inside a ``functional_tests/``
    directory.  No environment variable required — ``devices.yml``
    is the gate (checked at run time, not collection time).
    """

    if (
        file_path.suffix == ".py"
        and file_path.name.startswith("test_")
        and "functional_tests" in file_path.parts
    ):
        return DeviceTestFile.from_parent(parent, path=file_path)

    return None


def pytest_collection_modifyitems(config, items):
    """Remove normal pytest items for functional test files.

    ``pytest_collect_file`` adds DeviceTestItems but does not suppress
    the default Module collector, which also creates regular Function
    items for the same file.  This hook deselects those duplicates so
    functional tests only run through the device transport — never
    locally on CPython.
    """
    deselected = []
    selected = []
    for item in items:
        if "functional_tests" in item.nodeid and not isinstance(item, DeviceTestItem):
            deselected.append(item)
        else:
            selected.append(item)
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = selected


def pytest_sessionstart(session):
    """Initialize the transport cache on the session object."""
    session._device_transport_cache = _TransportCache()


def pytest_sessionfinish(session, exitstatus):
    """Disconnect all cached transports at session end."""
    cache = getattr(session, "_device_transport_cache", None)
    if cache is not None:
        cache.disconnect_all()
