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
from collections.abc import Generator, Iterable, Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from chumicro_deploy import TransportProtocol
from device_config import (
    DeviceConfigError,
    DeviceEntry,
    load_device_registry,
    resolve_ide_devices,
)
from device_testing import (
    build_device_bootstrap,
    create_transport,
    execute_device_bootstrap,
    resolve_library_source_dirs,
)
from result_parser import RunResult, TestResult, parse_output
from workspace import ROOT


def _session_cache(session: pytest.Session) -> _TransportCache:
    """Return the session-scoped ``_TransportCache``, asserting it exists.

    ``pytest_sessionstart`` populates the dynamic attribute; any code
    path that uses the cache runs strictly after that hook.  The cast
    keeps the rest of the module free of ``# type: ignore`` noise from
    pytest's dynamic ``session`` attributes.
    """
    cache = getattr(session, "_device_transport_cache", None)
    assert cache is not None, "pytest_sessionstart must run before cache access"
    return cast("_TransportCache", cache)


def _session_targets(session: pytest.Session) -> list[DeviceEntry] | None:
    """Return the resolved target devices from ``pytest_sessionstart``."""
    targets = getattr(session, "_device_targets", None)
    if targets is None:
        return None
    return cast("list[DeviceEntry]", targets)

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


def _iter_runtime_variants(
    function_names: list[str],
    targets: list[DeviceEntry],
) -> Iterator[tuple[str, DeviceEntry]]:
    """Yield ``(function_name, device)`` pairs in IDE-friendly order.

    When collecting a whole file for both runtimes, keep the runtime
    variants of each function adjacent.  Some IDE test explorers build
    parameterized-test groups from the incoming item stream, and a
    runtime-first order can produce duplicate parent nodes when the two
    variants of the same base function are far apart.

    Args:
        function_names: Sorted test function names from the file.
        targets: Device targets selected for the session.

    Yields:
        Tuples of ``(function_name, device_entry)``.
    """
    for function_name in function_names:
        for device in targets:
            yield function_name, device


def _runtime_display_name(runtime_name: str) -> str:
    """Return a UI-friendly runtime label.

    Args:
        runtime_name: Internal runtime identifier from device config.

    Returns:
        Human-friendly runtime label for IDE test trees.
    """
    return {
        "micropython": "MicroPython",
        "circuitpython": "CircuitPython",
    }.get(runtime_name, runtime_name)


def _runtime_prepare_name(device_entry: DeviceEntry) -> str:
    """Return the synthetic pytest item name for a runtime prepare step."""
    return f"Setup — {_runtime_display_name(device_entry.runtime)}"


def _runtime_run_file_name(device_entry: DeviceEntry) -> str:
    """Return the synthetic pytest item name for a runtime file-run step."""
    return f"Run overhead — {_runtime_display_name(device_entry.runtime)}"


def _sum_reported_test_durations(test_results: Iterable[TestResult]) -> float:
    """Return the total device-reported duration across parsed tests.

    Args:
        test_results: Iterable of parsed result objects with optional
            ``duration`` attributes.

    Returns:
        Sum of all non-``None`` durations.
    """
    total_duration = 0.0
    for test_result in test_results:
        if test_result.duration is not None:
            total_duration += test_result.duration
    return total_duration


def _apply_reported_duration(
    item: DeviceRuntimeItem, report: pytest.TestReport,
) -> None:
    """Override pytest timing with parsed device timing when available.

    Real device runs batch a whole file at once. Without this adjustment,
    pytest measures each cached per-test item as ~0 ms host work and attributes
    nearly all execution time to the synthetic batch item.

    For per-test items, use the harness-reported duration directly. For the
    synthetic batch item, keep only the residual host-side overhead after
    subtracting the sum of the parsed per-test durations. This preserves a
    useful batch node without double-counting the device test times into the
    parent file total.

    Args:
        item: Pytest item with optional reported-duration attributes.
        report: Pytest report object for the item.
    """
    if report.when != "call":
        return

    reported_duration = getattr(item, "_reported_duration", None)
    if reported_duration is not None:
        report.duration = reported_duration
        return

    reported_test_total_duration = getattr(
        item, "_reported_test_total_duration", None,
    )
    if reported_test_total_duration is None:
        return

    report.duration = max(report.duration - reported_test_total_duration, 0.0)


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
        self._transports: dict[str, TransportProtocol] = {}
        self._last_staged: dict[str, tuple[str, str]] = {}
        #: Device IDs that have been bulk-staged (flash/copy modes).
        self._fully_staged: set[str] = set()
        #: Cached batch results keyed by (device_id, library, file).
        #: Value is (parsed_result_or_None, raw_output_or_error).
        self._batch_results: dict[
            tuple[str, str, str], tuple[RunResult | None, str]
        ] = {}

    def get_transport(
        self, device_entry: DeviceEntry, deploy_mode: str | None,
    ) -> TransportProtocol:
        """Get or create a connected transport for the device.

        Args:
            device_entry: A ``DeviceEntry`` from the config loader.
            deploy_mode: Deploy mode override, or ``None``.

        Returns:
            A connected transport instance.
        """
        key = device_entry.identifier
        if key not in self._transports:
            transport = create_transport(device_entry, deploy_mode=deploy_mode)
            transport.connect()
            self._transports[key] = transport
        return self._transports[key]

    def needs_staging(self, batch_key: tuple[str, str, str]) -> bool:
        """Check whether the library/test file needs to be staged.

        In RAM mode, staged sources include the test file content.
        Re-staging is needed when either the library or the test file
        changes.

        Args:
            batch_key: ``(device_id, library_name, test_file_name)``
                from ``DeviceRuntimeItem._batch_key``.

        Returns:
            ``True`` if staging is needed.
        """
        device_id, library_name, test_file_name = batch_key
        return self._last_staged.get(device_id) != (library_name, test_file_name)

    def mark_staged(self, batch_key: tuple[str, str, str]) -> None:
        """Record that a library/test file has been staged on a device.

        Args:
            batch_key: ``(device_id, library_name, test_file_name)``
                from ``DeviceRuntimeItem._batch_key``.
        """
        device_id, library_name, test_file_name = batch_key
        self._last_staged[device_id] = (library_name, test_file_name)

    def has_staged_file(self, device_id: str) -> bool:
        """Return whether the device has staged a RAM-mode file already.

        Args:
            device_id: Device identifier.

        Returns:
            ``True`` when at least one ``(library, file)`` staging record
            exists for the device.
        """
        return device_id in self._last_staged

    def get_batch_result(
        self, batch_key: tuple[str, str, str],
    ) -> tuple[RunResult | None, str] | None:
        """Return cached batch result, or ``None`` if not yet executed.

        Args:
            batch_key: ``(device_id, library_name, test_file_name)``
                from ``DeviceRuntimeItem._batch_key``.

        Returns:
            Tuple of ``(parsed_result, raw_output)`` if cached, else
            ``None``.  When the batch execution failed,
            ``parsed_result`` is ``None`` and ``raw_output`` contains
            the error message.
        """
        return self._batch_results.get(batch_key)

    def cache_batch_result(
        self,
        batch_key: tuple[str, str, str],
        parsed_result: RunResult | None,
        raw_output: str,
    ) -> None:
        """Store a batch execution result.

        Args:
            batch_key: ``(device_id, library_name, test_file_name)``
                from ``DeviceRuntimeItem._batch_key``.
            parsed_result: Parsed harness output, or ``None`` on failure.
            raw_output: Raw device output or error message.
        """
        self._batch_results[batch_key] = (parsed_result, raw_output)

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

    def invalidate_device(self, device_id: str) -> None:
        """Drop all cached state for a device after a fatal transport error.

        Called when a batch execution fails and ``transport.recover()``
        cannot guarantee the board is in a usable state.  Removes the
        transport (so the next item reconnects from scratch), the
        staging records (so the next item re-stages), and the
        fully-staged marker.  Cached batch results are kept so subsequent
        items from the same file still see the original failure rather
        than retrying and getting confusing partial output.

        Args:
            device_id: Device identifier.
        """
        transport = self._transports.pop(device_id, None)
        if transport is not None:
            try:
                transport.disconnect()
            except Exception:  # pragma: no cover - best-effort cleanup
                pass
        self._last_staged.pop(device_id, None)
        self._fully_staged.discard(device_id)

    def disconnect_all(self) -> None:
        """Reset and disconnect all cached transports."""
        for transport in self._transports.values():
            try:
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

    def collect(self) -> Iterator[pytest.Item]:
        """Yield a :class:`DeviceTestItem` for each test function and target device."""
        function_names = _parse_test_functions(self.path)
        targets = _session_targets(self.session)

        if targets is None or len(targets) <= 1:
            # No config, single target, or no devices — one item per function.
            device = targets[0] if targets else None
            if device is not None:
                # pytest.Item.from_parent accepts **kwargs, so pyright's
                # strict mode flags it as partially unknown — suppress.
                yield DevicePrepareItem.from_parent(  # pyright: ignore[reportUnknownMemberType]
                    self,
                    name=_runtime_prepare_name(device),
                    test_file=self.path,
                    target_device=device,
                )
                yield DeviceRunFileItem.from_parent(  # pyright: ignore[reportUnknownMemberType]
                    self,
                    name=_runtime_run_file_name(device),
                    test_file=self.path,
                    target_device=device,
                )
            for name in function_names:
                yield DeviceTestItem.from_parent(  # pyright: ignore[reportUnknownMemberType]
                    self,
                    name=name,
                    test_file=self.path,
                    function_name=name,
                    target_device=device,
                )
        else:
            # Multiple targets (both mode) — parametrize by runtime.
            for device in targets:
                # pytest.Item.from_parent accepts **kwargs, so pyright's
                # strict mode flags it as partially unknown — suppress.
                yield DevicePrepareItem.from_parent(  # pyright: ignore[reportUnknownMemberType]
                    self,
                    name=_runtime_prepare_name(device),
                    test_file=self.path,
                    target_device=device,
                )
                yield DeviceRunFileItem.from_parent(  # pyright: ignore[reportUnknownMemberType]
                    self,
                    name=_runtime_run_file_name(device),
                    test_file=self.path,
                    target_device=device,
                )
            for name, device in _iter_runtime_variants(function_names, targets):
                display_name = f"{name}[{_runtime_display_name(device.runtime)}]"
                yield DeviceTestItem.from_parent(  # pyright: ignore[reportUnknownMemberType]
                    self,
                    name=display_name,
                    test_file=self.path,
                    function_name=name,
                    target_device=device,
                )


class DeviceRuntimeItem(pytest.Item):
    """Base class for synthetic and per-test device pytest items.

    All leaf items for a ``functional_tests/`` file share the same device
    preparation and batch-execution helpers.  Those helpers are idempotent,
    so synthetic control items can perform the expensive work during full-file
    runs while direct single-test targeting still works.
    """

    def __init__(
        self,
        *,
        test_file: Path,
        target_device: DeviceEntry | None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)  # pyright: ignore[reportUnknownMemberType]
        self.test_file = test_file
        self.target_device: DeviceEntry | None = target_device
        self.library_dir: Path = _resolve_library_dir(test_file)
        self._library_name = self.library_dir.name
        self._reported_duration: float | None = None
        self._reported_test_total_duration: float | None = None

    def _resolve_device_entry(self) -> DeviceEntry:
        """Return the resolved target device for this item."""
        device_entry = self.target_device
        if device_entry is None:
            device_entry = _load_fallback_device()
            self.target_device = device_entry
        return device_entry

    def _batch_key(self, device_entry: DeviceEntry) -> tuple[str, str, str]:
        """Return the cache key for this item's file/runtime batch."""
        return (
            device_entry.identifier,
            self._library_name,
            self.test_file.name,
        )

    def _ensure_prepared(self, device_entry: DeviceEntry) -> None:
        """Connect to the device and stage source files if needed."""

        cache = _session_cache(self.session)

        try:
            transport = cache.get_transport(device_entry, None)
        except Exception as error:
            cache.cache_batch_result(
                self._batch_key(device_entry),
                None,
                f"Transport connection failed: {error}",
            )
            pytest.fail(f"Transport connection failed: {error}")

        # Flash/copy modes persist files on the device filesystem,
        # so we bulk-stage ALL sources + ALL test files in one pass
        # (one rsync) on first use.  RAM mode embeds source inline,
        # so it re-stages per file.
        is_filesystem_mode = transport.mode not in ("ram", "mount")
        if is_filesystem_mode and not cache.is_fully_staged(device_entry.identifier):
            _bulk_stage_for_device(self.session, device_entry, transport)
            cache.mark_fully_staged(device_entry.identifier)
        elif not is_filesystem_mode:
            staging_key = self._batch_key(device_entry)
            if cache.needs_staging(staging_key):
                if _should_soft_reset_before_stage(
                    cache, device_entry, transport, self._library_name, self.test_file.name,
                ):
                    try:
                        transport.soft_reset()
                    except Exception as error:
                        pytest.fail(f"Device reset failed between test files: {error}")
                source_dirs = resolve_library_source_dirs(
                    self.library_dir, test_files=[self.test_file],
                )
                transport.stage(
                    source_dirs, [self.test_file], HARNESS_SOURCE,
                )
                cache.mark_staged(staging_key)

    def _ensure_batch_result(
        self,
        device_entry: DeviceEntry,
    ) -> tuple[RunResult | None, str]:
        """Run the file batch once if needed and return its cached result."""
        cache = _session_cache(self.session)
        batch_key = self._batch_key(device_entry)

        # Check for cached batch result from a previous item.
        batch = cache.get_batch_result(batch_key)

        if batch is None:
            # First item for this (device, file) — run all tests.
            self._ensure_prepared(device_entry)
            transport = cache.get_transport(device_entry, None)

            # Run ALL tests in the file (no name_filter) to amortize
            # the per-invocation overhead.
            bootstrap = build_device_bootstrap(
                device_entry, transport, self.test_file, None,
            )
            try:
                raw_output = execute_device_bootstrap(transport, bootstrap)
            except Exception as error:
                # Try to recover the board so the next file can run
                # independently of this failure; if recovery itself
                # fails, evict the transport so the next item reconnects
                # from scratch.  Without this, every subsequent file
                # cascade-failed because the cached transport was stuck
                # mid-raw-REPL or mid-mpremote.
                error_message = f"Device execution failed: {error}"
                recovery_failed = False
                try:
                    transport.recover()
                except Exception as recover_error:  # pragma: no cover - hardware-only
                    recovery_failed = True
                    error_message = (
                        f"{error_message}\n"
                        f"Recovery failed: {recover_error}; "
                        f"evicting transport for {device_entry.identifier}"
                    )
                if recovery_failed:
                    cache.invalidate_device(device_entry.identifier)
                cache.cache_batch_result(batch_key, None, error_message)
                pytest.fail(error_message)

            result = parse_output(raw_output)
            cache.cache_batch_result(batch_key, result, raw_output)
            return result, raw_output

        return batch

    def repr_failure(
        self,
        excinfo: pytest.ExceptionInfo[BaseException],
        style: str | None = None,
    ) -> str:
        """Produce a readable failure representation."""
        return str(excinfo.value)

    def reportinfo(self) -> tuple[Path, int | None, str]:
        """Return location info for test reporting."""
        return self.path, None, f"[device] {self._library_name}::{self.name}"


class DevicePrepareItem(DeviceRuntimeItem):
    """Synthetic item that owns transport connect/stage time for a runtime."""

    def runtest(self) -> None:
        """Prepare the runtime for a file batch."""
        device_entry = self._resolve_device_entry()
        self._ensure_prepared(device_entry)


class DeviceRunFileItem(DeviceRuntimeItem):
    """Synthetic item that owns file-batch execution time for a runtime."""

    def runtest(self) -> None:
        """Run the file batch once and validate the harness-level result."""
        device_entry = self._resolve_device_entry()
        result, raw_output = self._ensure_batch_result(device_entry)

        if result is None:
            pytest.fail(raw_output)
        if not result.tests:
            pytest.fail(f"No test results in device output:\n{raw_output}")
        self._reported_test_total_duration = _sum_reported_test_durations(result.tests)


class DeviceTestItem(DeviceRuntimeItem):
    """A single parsed test result from a batched file run on device."""

    def __init__(
        self,
        *,
        test_file: Path,
        function_name: str,
        target_device: DeviceEntry | None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            test_file=test_file,
            target_device=target_device,
            **kwargs,
        )
        self._function_name = function_name

    def runtest(self) -> None:
        """Look up this test's result from the batched device run."""
        device_entry = self._resolve_device_entry()
        result, raw_output = self._ensure_batch_result(device_entry)

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
                self._reported_duration = test_result.duration
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
        devices, defaults = load_device_registry(workspace_root=ROOT)
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


#: Transport modes that hold a persistent interpreter across test files.
#: Both CircuitPython ``"ram"`` (inline bootstrap) and MicroPython
#: ``"mount"`` (mpremote ``mount_local``) reuse the same live VM from
#: one file to the next, so ``sys.modules`` accumulates until a soft
#: reset clears it.  Other modes copy files to flash and import fresh
#: per call, so they don't need the inter-file reset.
_IN_MEMORY_MODES = ("ram", "mount")


def _should_soft_reset_before_stage(
    cache: _TransportCache,
    device_entry: DeviceEntry,
    transport: TransportProtocol,
    library_name: str,
    test_file_name: str,
) -> bool:
    """Return whether in-memory re-staging should soft-reset first.

    Both CircuitPython RAM mode and MicroPython mount mode keep the same
    interpreter across test files (raw REPL or persistent serial via
    mpremote).  Without a soft reset between files the previous file's
    modules stay in ``sys.modules`` and consume heap; on Tier-2 boards
    (RP2040 class, 264 KB SRAM) that can exhaust RAM after a handful
    of libraries and fail the next bootstrap with ``MemoryError`` before
    execution even begins.

    The soft reset is a VM-level Ctrl-D via raw REPL — it does not
    toggle USB or re-enumerate the CDC, so it is safe to run between
    every file.

    To preserve batching within a file while reclaiming memory across
    files, soft-reset only when all of the following are true:

    - the transport is in an in-memory mode (``ram`` or ``mount``),
    - the device previously staged a file in this session, and
    - the current staging target differs from the last one.

    Args:
        cache: Session transport cache.
        device_entry: Target device.
        transport: Connected transport instance.
        library_name: Library for the current item.
        test_file_name: Test file for the current item.

    Returns:
        ``True`` when a soft reset should run before ``stage()``.
    """
    if transport.mode not in _IN_MEMORY_MODES:
        return False
    if not cache.has_staged_file(device_entry.identifier):
        return False
    return cache.needs_staging(
        (device_entry.identifier, library_name, test_file_name),
    )


def _bulk_stage_for_device(
    session: pytest.Session,
    device_entry: DeviceEntry,
    transport: TransportProtocol,
) -> None:
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
        target = item.target_device
        if target is None or target.identifier != device_entry.identifier:
            continue

        # Collect source dirs for this item's library.
        for source_dir in resolve_library_source_dirs(
            item.library_dir, test_files=[item.test_file],
        ):
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


def pytest_collect_file(
    parent: pytest.Collector, file_path: Path,
) -> DeviceTestFile | None:
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
        return DeviceTestFile.from_parent(parent, path=file_path)  # pyright: ignore[reportUnknownMemberType]

    return None


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item],
) -> None:
    """Remove normal pytest items for functional test files.

    ``pytest_collect_file`` adds DeviceTestItems but does not suppress
    the default Module collector, which also creates regular Function
    items for the same file.  This hook deselects those duplicates so
    functional tests only run through the device transport — never
    locally on CPython.
    """
    deselected: list[pytest.Item] = []
    selected: list[pytest.Item] = []
    for item in items:
        if "functional_tests" in item.nodeid and not isinstance(item, DeviceRuntimeItem):
            deselected.append(item)
        else:
            selected.append(item)
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = selected


def pytest_sessionstart(session: pytest.Session) -> None:
    """Initialize the transport cache and resolve target devices."""
    session._device_transport_cache = _TransportCache()  # type: ignore[attr-defined]

    # Eagerly resolve target devices so collection can parametrize
    # by runtime when ide_runtime is "both".
    try:
        devices, defaults = load_device_registry(workspace_root=ROOT)
        session._device_targets = resolve_ide_devices(devices, defaults)  # type: ignore[attr-defined]
    except DeviceConfigError:
        session._device_targets = None  # type: ignore[attr-defined]


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Disconnect all cached transports at session end."""
    cache = getattr(session, "_device_transport_cache", None)
    if cache is not None:
        cast("_TransportCache", cache).disconnect_all()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None],
) -> Generator[None, None, None]:
    """Inject parsed device durations into call-phase pytest reports."""
    outcome = yield
    report = cast(pytest.TestReport, outcome.get_result())  # type: ignore[attr-defined]
    if isinstance(item, DeviceRuntimeItem):
        _apply_reported_duration(item, report)
