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
    """Session-scoped cache for device transports and batch results.

    Avoids reconnecting for every test item.  Stores one transport
    per device ID and tracks the last-staged library *and test file*
    to avoid redundant staging while ensuring re-staging when the
    test file changes (critical for RAM mode where test file content
    is part of the staged sources).

    Also caches batch execution results: the first test item for a
    given ``(device, library, file)`` combo runs *all* tests in the
    file at once and caches the parsed output.  Subsequent items
    look up their result from the cache.  This amortizes the per-
    invocation overhead of transports like ``mpremote`` that spawn
    a fresh subprocess per ``execute()`` call.
    """

    def __init__(self) -> None:
        self._transports: dict[str, object] = {}
        self._last_staged: dict[str, tuple[str, str]] = {}
        #: Device IDs that have been bulk-staged (flash/copy modes).
        self._fully_staged: set[str] = set()
        #: Cached batch results keyed by (device_id, library, file).
        #: Value is (parsed_result_or_None, raw_output_or_error).
        self._batch_results: dict[
            tuple[str, str, str], tuple[object | None, str]
        ] = {}

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

    def get_batch_result(
        self,
        device_id: str,
        library_name: str,
        test_file_name: str,
    ) -> tuple[object | None, str] | None:
        """Return cached batch result, or ``None`` if not yet executed.

        Args:
            device_id: Device identifier.
            library_name: Library name.
            test_file_name: Name of the test file.

        Returns:
            Tuple of ``(parsed_result, raw_output)`` if cached, else
            ``None``.  When the batch execution failed,
            ``parsed_result`` is ``None`` and ``raw_output`` contains
            the error message.
        """
        return self._batch_results.get((device_id, library_name, test_file_name))

    def cache_batch_result(
        self,
        device_id: str,
        library_name: str,
        test_file_name: str,
        parsed_result: object | None,
        raw_output: str,
    ) -> None:
        """Store a batch execution result.

        Args:
            device_id: Device identifier.
            library_name: Library name.
            test_file_name: Name of the test file.
            parsed_result: Parsed harness output, or ``None`` on failure.
            raw_output: Raw device output or error message.
        """
        self._batch_results[
            (device_id, library_name, test_file_name)
        ] = (parsed_result, raw_output)

    def is_fully_staged(self, device_id: str) -> bool:
        """Check whether a device has been bulk-staged.

        In flash/copy modes, all sources and test files are staged in
        one pass.  Once bulk-staged, per-file re-staging is skipped.

        Args:
            device_id: Device identifier.

        Returns:
            ``True`` if the device has been bulk-staged.
        """
        return device_id in self._fully_staged

    def mark_fully_staged(self, device_id: str) -> None:
        """Record that a device has been bulk-staged.

        Args:
            device_id: Device identifier.
        """
        self._fully_staged.add(device_id)

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
        self._fully_staged.clear()
        self._batch_results.clear()


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

    Preparation (connecting and staging) happens in :meth:`setup` so
    the IDE shows it as a distinct setup phase.  :meth:`runtest` only
    handles execution and result lookup.

    Uses batch execution: the first item for a given
    ``(device, library, file)`` combo runs *all* test functions in
    the file at once (no ``name_filter``) and caches the parsed
    output.  Subsequent items look up their result from the cache.
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

    def setup(self) -> None:
        """Connect to the device and stage source files.

        This runs before :meth:`runtest` and appears as a separate
        setup phase in IDE test runners (PyCharm, VS Code).

        Flash/copy modes bulk-stage all sources and test files in one
        pass on first use.  RAM mode re-stages per file since the
        source content is embedded inline.
        """
        device_entry = self._target_device
        if device_entry is None:
            device_entry = _load_fallback_device()
            self._target_device = device_entry

        cache: _TransportCache = self.session._device_transport_cache  # type: ignore[attr-defined]

        try:
            transport = cache.get_transport(device_entry, None)
        except Exception as error:
            batch_key = (
                device_entry.identifier,
                self._library_name,
                self.test_file.name,
            )
            cache.cache_batch_result(
                *batch_key, None, f"Transport connection failed: {error}",
            )
            pytest.fail(f"Transport connection failed: {error}")

        # Flash/copy modes persist files on the device filesystem,
        # so we bulk-stage ALL sources + ALL test files in one pass
        # (one rsync) on first use.  RAM mode embeds source inline,
        # so it re-stages per file.
        is_filesystem_mode = (
            hasattr(transport, "mode") and transport.mode not in ("ram", "mount")
        )
        if is_filesystem_mode and not cache.is_fully_staged(device_entry.identifier):
            _bulk_stage_for_device(self.session, device_entry, transport)
            cache.mark_fully_staged(device_entry.identifier)
        elif not is_filesystem_mode:
            staging_key = (
                device_entry.identifier,
                self._library_name,
                self.test_file.name,
            )
            if cache.needs_staging(*staging_key):
                source_dirs = _resolve_library_source_dirs(self._library_dir)
                transport.stage(
                    source_dirs, [self.test_file], HARNESS_SOURCE,
                )
                cache.mark_staged(*staging_key)

    def runtest(self) -> None:
        """Execute the test on the connected device.

        The first item for a given ``(device, library, file)`` combo
        runs *all* test functions in the file at once and caches the
        parsed results.  Subsequent items look up their result from
        the cache.
        """
        device_entry = self._target_device
        if device_entry is None:
            # setup() should have resolved this, but guard anyway.
            device_entry = _load_fallback_device()

        cache: _TransportCache = self.session._device_transport_cache  # type: ignore[attr-defined]
        batch_key = (
            device_entry.identifier,
            self._library_name,
            self.test_file.name,
        )

        # Check for cached batch result from a previous item.
        batch = cache.get_batch_result(*batch_key)

        if batch is None:
            # First item for this (device, file) — run all tests.
            transport = cache.get_transport(device_entry, None)

            # Run ALL tests in the file (no name_filter) to amortize
            # the per-invocation overhead.
            bootstrap = _build_device_bootstrap(
                device_entry, transport, self.test_file, None,
            )
            try:
                raw_output = transport.execute(bootstrap)
            except Exception as error:
                cache.cache_batch_result(
                    *batch_key, None, f"Device execution failed: {error}",
                )
                pytest.fail(f"Device execution failed: {error}")

            result = parse_output(raw_output)
            cache.cache_batch_result(*batch_key, result, raw_output)
        else:
            result, raw_output = batch

        # If the batch failed, all items from it fail.
        if result is None:
            pytest.fail(raw_output)

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


def _bulk_stage_for_device(session, device_entry: DeviceEntry, transport) -> None:
    """Stage all sources and test files for a device in one pass.

    In flash/copy modes, files persist on the device filesystem so
    we can deploy everything once instead of re-staging per test file.
    This reduces rsync (CircuitPython) or ``mpremote fs cp``
    (MicroPython) invocations from N-per-file to 1-per-device.

    Collects all :class:`DeviceTestItem` instances targeting the given
    device from the session's collected items, deduplicates their
    library source directories and test files, and calls
    ``transport.stage()`` once.

    Args:
        session: The pytest session (provides ``items``).
        device_entry: The target device.
        transport: A connected transport instance.
    """
    seen_source_dirs: list[Path] = []
    seen_test_files: list[Path] = []
    seen_test_file_ids: set[str] = set()

    for item in session.items:
        if not isinstance(item, DeviceTestItem):
            continue
        target = item._target_device
        if target is None or target.identifier != device_entry.identifier:
            continue

        # Collect source dirs for this item's library.
        for source_dir in _resolve_library_source_dirs(item._library_dir):
            if source_dir not in seen_source_dirs:
                seen_source_dirs.append(source_dir)

        # Collect test file (deduplicate by path string).
        test_file_key = str(item.test_file)
        if test_file_key not in seen_test_file_ids:
            seen_test_file_ids.add(test_file_key)
            seen_test_files.append(item.test_file)

    transport.stage(seen_source_dirs, seen_test_files, HARNESS_SOURCE)


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
