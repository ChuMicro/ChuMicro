"""Pytest plugin for routing functional tests to real hardware.

When pytest collects a file from a ``functional_tests/`` directory,
this plugin intercepts it and wraps each ``test_*`` function as a
:class:`DeviceTestItem`.  Instead of importing and running the test
locally, the item stages source code on a connected board, executes
the test via the device transport, and parses the harness output to
report pass/fail to pytest.

**No environment variable setup is required.**  The plugin reads
``devices.yml`` to find the target device(s).  A top-level
``defaults:`` section controls which board(s) the IDE targets:

.. code-block:: yaml

   defaults:
     micropython: my-mp-board
     circuitpython: my-cp-board
     deploy_mode: ram
     ide_runtime: both       # or micropython, or circuitpython

When ``ide_runtime`` is ``both``, each test function is collected
twice — once per runtime — so the IDE shows separate pass/fail
results for MicroPython and CircuitPython.

This enables IDE play buttons (PyCharm, VS Code) to run device
tests at file and function granularity — just click play.

See Decision 0027 (IDE integration section).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from device_config import (
    DeviceConfigError,
    DeviceEntry,
    load_device_registry,
    resolve_ide_devices,
)
from device_testing import (
    _build_device_bootstrap,
    _create_transport,
    _resolve_library_source_dirs,
)
from result_parser import parse_output
from workspace import ROOT

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


class _TransportCache:
    """Session-scoped cache for device transports.

    Avoids reconnecting for every test item.  Stores one transport
    per device ID and tracks the last-staged library *and test file*
    to avoid redundant staging while ensuring re-staging when the
    test file changes (critical for RAM mode where test file content
    is part of the staged sources).
    """

    def __init__(self) -> None:
        self._transports: dict[str, object] = {}
        self._last_staged: dict[str, tuple[str, str]] = {}

    def get_transport(self, device_entry: DeviceEntry, deploy_mode: str | None):
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

    def needs_staging(
        self, device_id: str, library_name: str, test_file_name: str,
    ) -> bool:
        """Check whether the library/test file needs to be staged.

        In RAM mode, staged sources include the test file content.
        Re-staging is needed when either the library or the test file
        changes.

        Args:
            device_id: Device identifier.
            library_name: Library name.
            test_file_name: Name of the test file.

        Returns:
            ``True`` if staging is needed.
        """
        return self._last_staged.get(device_id) != (library_name, test_file_name)

    def mark_staged(
        self, device_id: str, library_name: str, test_file_name: str,
    ) -> None:
        """Record that a library/test file has been staged on a device.

        Args:
            device_id: Device identifier.
            library_name: Library name.
            test_file_name: Name of the test file.
        """
        self._last_staged[device_id] = (library_name, test_file_name)

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
        self._last_staged.clear()


class DeviceTestFile(pytest.File):
    """Collector that discovers ``test_*`` functions via AST parsing.

    When ``ide_runtime`` is ``both`` in the ``defaults:`` section,
    each test function is collected twice — once per runtime — so
    pytest shows separate results for each board.
    """

    def collect(self):
        """Yield a :class:`DeviceTestItem` for each test function and target device."""
        function_names = _parse_test_functions(self.path)
        targets = getattr(self.session, "_device_targets", None)

        if targets is None or len(targets) <= 1:
            # No config, single target, or no devices — one item per function.
            device = targets[0] if targets else None
            for name in function_names:
                yield DeviceTestItem.from_parent(
                    self,
                    name=name,
                    test_file=self.path,
                    function_name=name,
                    target_device=device,
                )
        else:
            # Multiple targets (both mode) — parametrize by runtime.
            for device in targets:
                for name in function_names:
                    display_name = f"{name}[{device.runtime}]"
                    yield DeviceTestItem.from_parent(
                        self,
                        name=display_name,
                        test_file=self.path,
                        function_name=name,
                        target_device=device,
                    )


class DeviceTestItem(pytest.Item):
    """A single test function that runs on a real device.

    Stages library source to the device, sends a bootstrap script
    that invokes the test harness with ``name_filter`` set to this
    test function, parses the structured output, and reports
    pass/fail to pytest.
    """

    def __init__(
        self,
        *,
        test_file: Path,
        function_name: str,
        target_device: DeviceEntry | None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.test_file = test_file
        self._function_name = function_name
        self._target_device = target_device
        self._library_dir = _resolve_library_dir(test_file)
        self._library_name = self._library_dir.name

    def runtest(self) -> None:
        """Execute the test on a connected device."""
        device_entry = self._target_device
        if device_entry is None:
            # No device resolved at collection time — try again.
            device_entry = _load_fallback_device()

        cache: _TransportCache = self.session._device_transport_cache  # type: ignore[attr-defined]

        try:
            transport = cache.get_transport(device_entry, None)
        except Exception as error:
            pytest.fail(f"Transport connection failed: {error}")

        # Stage library source if needed.  Track both library name
        # and test file name so we re-stage when the test file changes
        # (RAM mode includes test file content in staged sources).
        if cache.needs_staging(
            device_entry.identifier, self._library_name, self.test_file.name,
        ):
            source_dirs = _resolve_library_source_dirs(self._library_dir)
            transport.stage(
                source_dirs, [self.test_file], HARNESS_SOURCE,
            )
            cache.mark_staged(
                device_entry.identifier, self._library_name, self.test_file.name,
            )

        # Build and execute bootstrap with name_filter for this
        # specific test function.
        bootstrap = _build_device_bootstrap(
            device_entry, transport, self.test_file, self._function_name,
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
            if test_result.name == self._function_name:
                if test_result.status == "FAIL":
                    pytest.fail(
                        f"Device test FAIL: {self._function_name}\n{raw_output}"
                    )
                if test_result.status == "SKIP":
                    pytest.skip(test_result.message or "Skipped on device")
                return

        # Test name not found in output — may have been filtered or
        # errored before reaching the harness.
        pytest.fail(
            f"Test {self._function_name!r} not found in device output:\n{raw_output}"
        )

    def repr_failure(self, excinfo, style=None):
        """Produce a readable failure representation."""
        return str(excinfo.value)

    def reportinfo(self):
        """Return location info for test reporting."""
        return self.path, None, f"[device] {self._library_name}::{self.name}"


def _load_fallback_device() -> DeviceEntry:
    """Fallback device loading for items created without a target.

    Called when ``devices.yml`` was unavailable at collection time
    but may exist at run time.

    Returns:
        A ``DeviceEntry`` from the device registry.

    Raises:
        pytest.skip: If no devices.yml exists or no devices are configured.
        pytest.fail: If devices.yml is malformed.
    """
    try:
        devices, defaults = load_device_registry()
    except DeviceConfigError as error:
        error_message = str(error)
        if "not found" in error_message:
            pytest.skip(
                "No devices.yml found.  Run 'python scripts/run.py setup' "
                "and configure your board to run functional tests on hardware."
            )
        pytest.fail(f"Device config error: {error}")

    targets = resolve_ide_devices(devices, defaults)
    if not targets:
        pytest.skip(
            "No devices configured in devices.yml.  "
            "Add your board details to run functional tests on hardware."
        )

    return targets[0]


# ---------------------------------------------------------------------------
# Pytest hooks
# ---------------------------------------------------------------------------


def pytest_collect_file(parent, file_path):
    """Collect functional test files as device test items.

    Activates for any ``test_*.py`` file inside a ``functional_tests/``
    directory.  No environment variable required — ``devices.yml``
    is the gate (checked at collection/run time).
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
    """Initialize the transport cache and resolve target devices."""
    session._device_transport_cache = _TransportCache()

    # Eagerly resolve target devices so collection can parametrize
    # by runtime when ide_runtime is "both".
    try:
        devices, defaults = load_device_registry()
        session._device_targets = resolve_ide_devices(devices, defaults)
    except DeviceConfigError:
        session._device_targets = None


def pytest_sessionfinish(session, exitstatus):
    """Disconnect all cached transports at session end."""
    cache = getattr(session, "_device_transport_cache", None)
    if cache is not None:
        cache.disconnect_all()
