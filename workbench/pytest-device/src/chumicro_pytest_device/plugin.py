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
     deploy_mode: flash      # ram | flash; flash is the default
     ide_runtime: both       # or micropython, or circuitpython

When ``ide_runtime`` is ``both``, each test function is collected
twice — once per runtime — so the IDE shows separate pass/fail
results for MicroPython and CircuitPython.

This enables IDE play buttons (PyCharm, VS Code) to run device
tests at file and function granularity — just click play.

Functional test files that exercise a single-runtime backend can
opt out of the wrong-runtime parametrization with a module-level
``__chumicro_runtimes__`` marker — same convention the bundle and
deploy pipelines use for source files::

    __chumicro_runtimes__ = ("circuitpython",)
"""

from __future__ import annotations

import ast
import time
from collections import defaultdict
from collections.abc import Generator, Iterable, Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from chumicro_deploy import (
    DEFAULT_DEPLOY_MODE,
    DeployMode,
    DeviceConfigError,
    DeviceDefaults,
    DeviceEntry,
    DeviceImplementation,
    TransportProtocol,
    load_device_registry,
    resolve_ide_devices,
)
from chumicro_deploy.runtime_marker import read_runtime_marker

from ._test_runner import (
    build_device_bootstrap,
    create_transport,
    execute_device_bootstrap,
    resolve_effective_deploy_mode,
    resolve_library_source_dirs,
)
from .pr_summary import (
    DeviceRunResult,
    FileRunResult,
    format_pr_summary_block,
)
from .result_parser import RunResult, TestResult, parse_output
from .runtime_config import get_runtime_config

#: Canonical on-device path for the staged runtime-config payload —
#: matches :data:`chumicro_config.runtime.DEFAULT_RUNTIME_CONFIG_PATH`.
#: Hard-coded here rather than imported because workbench packages
#: don't import device libraries (they ship to host-side users via
#: PyPI, libraries ship to boards via circup / mip).
_RUNTIME_CONFIG_DEVICE_PATH = "/runtime_config.msgpack"


def _encode_runtime_config_extra_files(
    config: pytest.Config,
) -> dict[str, bytes] | None:
    """Return the ``extra_files`` dict to pass to ``transport.stage()``.

    Returns ``None`` when no conftest registered a payload (default
    state for libraries with no runtime-config requirements, plus the
    silent-skip path when credentials aren't configured).  Returns a
    one-entry dict mapping :data:`_RUNTIME_CONFIG_DEVICE_PATH` to the
    msgpack-encoded payload otherwise.

    Encoding uses ``use_single_float=True`` so float values round-trip
    through CircuitPython's native ``msgpack`` decoder (CP doesn't
    support float64).  Mirrors :func:`chumicro_workspace.writer.write_runtime_config`'s
    encoding contract.
    """
    payload = get_runtime_config(config)
    if payload is None:
        return None
    from msgpack import packb  # noqa: PLC0415 — defer until first stage call

    return {
        _RUNTIME_CONFIG_DEVICE_PATH: packb(payload, use_single_float=True),
    }


def _workspace_root(session: pytest.Session) -> Path:
    """Return the root of the workspace pytest was invoked against.

    Derived from ``pytest.Config.rootpath`` so the plugin works inside
    any workspace, not just one specific layout.
    """
    return Path(session.config.rootpath)


def _harness_source_dir(session: pytest.Session) -> Path:
    """Return ``support/test_harness/src`` for the on-device test harness.

    The plugin stages a lightweight test harness alongside library
    sources so ``import chumicro_test_harness`` resolves on the device.
    Workspaces without this directory won't run harness-shaped
    functional tests.
    """
    return _workspace_root(session) / "support" / "test_harness" / "src"


def _libraries_root(session: pytest.Session) -> Path:
    """Return ``libraries/`` for dependency-resolution staging."""
    return _workspace_root(session) / "libraries"


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register ``--chumicro-*`` command-line options on the pytest CLI.

    Each option overrides the corresponding ``defaults:`` entry in
    ``devices.yml`` when supplied; when omitted, ``devices.yml``
    defaults still drive selection so IDE play-button runs keep
    working with zero configuration.

    Options:

    - ``--chumicro-runtime`` (``micropython`` / ``circuitpython`` /
      ``both``) — overrides ``defaults.ide_runtime``.
    - ``--chumicro-micropython-device`` / ``--chumicro-circuitpython-device``
      — per-runtime device-ID overrides.
    - ``--chumicro-deploy-mode`` (``ram`` / ``flash``) — overrides
      the per-device ``deploy_mode`` and ``defaults.deploy_mode``.
    - ``--chumicro-pr-summary`` — when set, prints a Markdown
      device-testing block at session end (the same block the
      ``test-libraries-functional`` task used to print directly).  Opt-in so IDE
      play-button runs stay quiet.
    - ``--chumicro-pr-summary-command`` — literal command string to
      render in the ``- Command:`` line of the PR block.  The
      ``test-libraries-functional`` wrapper passes the reconstructed invocation;
      direct pytest runs can omit it and get the raw ``pytest ...``.
    """
    group = parser.getgroup("chumicro", "ChuMicro device-test plugin")
    group.addoption(
        "--chumicro-runtime",
        choices=("micropython", "circuitpython", "both"),
        default=None,
        help="override devices.yml defaults.ide_runtime",
    )
    group.addoption(
        "--chumicro-micropython-device",
        default=None,
        help="override devices.yml defaults.micropython device ID",
    )
    group.addoption(
        "--chumicro-circuitpython-device",
        default=None,
        help="override devices.yml defaults.circuitpython device ID",
    )
    group.addoption(
        "--chumicro-deploy-mode",
        choices=tuple(mode.value for mode in DeployMode),
        default=None,
        help="override per-device deploy_mode (ram / flash)",
    )
    group.addoption(
        "--chumicro-pr-summary",
        action="store_true",
        default=False,
        help="print a Markdown PR block at session end",
    )
    group.addoption(
        "--chumicro-pr-summary-command",
        default=None,
        help="command string to render inside the PR block",
    )


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


def _session_deploy_mode_override(session: pytest.Session) -> str | None:
    """Return the ``--chumicro-deploy-mode`` override, if any."""
    return cast(
        "str | None",
        session.config.getoption("--chumicro-deploy-mode", default=None),
    )


def _session_pr_summary(
    session: pytest.Session,
) -> _PRSummaryCollector | None:
    """Return the PR-summary collector when ``--chumicro-pr-summary`` is set."""
    return getattr(session, "_chumicro_pr_summary", None)


class _PRSummaryCollector:
    """Accumulate per-(device, file, test) outcomes for the PR block.

    The collector receives one call per pytest report (via
    ``pytest_runtest_makereport``) and rolls the results up into the
    :class:`DeviceRunResult` shape ``pr_summary.format_pr_summary_block``
    expects.  Empty containers are populated on first encounter and
    the overall order — device declaration order, then file
    declaration order — matches the ``test-libraries-functional`` orchestrator's
    output so the Markdown is stable across the two code paths.
    """

    def __init__(self) -> None:
        self._devices: dict[str, DeviceEntry] = {}
        self._file_order: dict[str, list[tuple[str, str]]] = defaultdict(list)
        self._file_results: dict[tuple[str, str, str], FileRunResult] = {}
        self._implementations: dict[str, DeviceImplementation | None] = {}
        self._deploy_modes: dict[str, str] = {}
        self._device_duration: dict[str, float] = defaultdict(float)
        self._session_start = time.perf_counter()
        self._session_end = self._session_start
        self._bulk_stage_errors: dict[str, int] = defaultdict(int)

    def record(
        self,
        item: DeviceRuntimeItem,
        report: pytest.TestReport,
    ) -> None:
        """Fold one call-phase report into the accumulated per-device results."""
        device = item.target_device
        if device is None:
            return
        device_id = device.identifier
        self._devices.setdefault(device_id, device)
        self._device_duration[device_id] += max(report.duration or 0.0, 0.0)
        self._session_end = time.perf_counter()

        # Probe once, lazily, when the transport is live.
        if device_id not in self._implementations:
            self._deploy_modes.setdefault(
                device_id,
                resolve_effective_deploy_mode(
                    device,
                    _session_deploy_mode_override(item.session),
                ),
            )
            cache = _session_cache(item.session)
            transport = cache._transports.get(device_id)  # noqa: SLF001
            if transport is not None:
                try:
                    self._implementations[device_id] = (
                        transport.probe_implementation()
                    )
                except Exception:  # pragma: no cover — hardware-only
                    self._implementations[device_id] = None

        if isinstance(item, DevicePrepareItem):
            # A failing prepare step means bulk-stage / connect failed;
            # no per-test items will produce results for this file.
            if report.failed:
                self._bulk_stage_errors[device_id] += 1
            return

        if isinstance(item, DeviceRunFileItem):
            # A failing run-file means the batch exec failed; count one
            # error per file and keep going.
            if report.failed:
                file_result = self._ensure_file_result(
                    device_id, item.library_dir.name, item.test_file.name,
                )
                file_result.errors = 1
            return

        if not isinstance(item, DeviceTestItem):
            return

        file_result = self._ensure_file_result(
            device_id, item.library_dir.name, item.test_file.name,
        )
        status: str
        if report.passed:
            status = "PASS"
            file_result.passed += 1
        elif report.skipped:
            status = "SKIP"
        else:
            status = "FAIL"
            file_result.failed += 1

        per_test_duration = item._reported_duration  # noqa: SLF001
        if per_test_duration is not None:
            file_result.duration_seconds += per_test_duration
        file_result.tests.append(TestResult(
            name=item._function_name,  # noqa: SLF001
            status=status,
            duration=per_test_duration,
            message=None,
        ))

    def _ensure_file_result(
        self,
        device_id: str,
        library_name: str,
        file_name: str,
    ) -> FileRunResult:
        key = (device_id, library_name, file_name)
        if key not in self._file_results:
            self._file_results[key] = FileRunResult(
                library=library_name,
                file_name=file_name,
                passed=0,
                failed=0,
                errors=0,
            )
            self._file_order[device_id].append((library_name, file_name))
        return self._file_results[key]

    def render(self) -> list[DeviceRunResult]:
        """Return the accumulated per-device results in report order."""
        results: list[DeviceRunResult] = []
        for device_id, device in self._devices.items():
            files = [
                self._file_results[(device_id, library_name, file_name)]
                for library_name, file_name in self._file_order.get(device_id, [])
            ]
            total_passed = sum(file_result.passed for file_result in files)
            total_failed = sum(file_result.failed for file_result in files)
            total_errors = (
                sum(file_result.errors for file_result in files)
                + self._bulk_stage_errors.get(device_id, 0)
            )
            duration = self._device_duration.get(device_id, 0.0)
            results.append(DeviceRunResult(
                device=device,
                passed=total_passed,
                failed=total_failed,
                errors=total_errors,
                implementation=self._implementations.get(device_id),
                deploy_mode=self._deploy_modes.get(device_id, DEFAULT_DEPLOY_MODE),
                duration_seconds=duration,
                files=files,
            ))
        return results

    def session_duration(self) -> float:
        """Total wall-clock span of the session, in seconds."""
        return max(self._session_end - self._session_start, 0.0)

# Note: ``HARNESS_SOURCE`` and ``LIBRARIES_ROOT`` were module-level
# constants pre-extraction; both are now session-scoped via
# :func:`_harness_source_dir` and :func:`_libraries_root` so the
# plugin works inside any workspace.


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


def _filter_targets_by_marker(
    targets: list[DeviceEntry] | None,
    test_file: Path,
) -> list[DeviceEntry] | None:
    """Drop targets the file's ``__chumicro_runtimes__`` marker excludes.

    Functional test files that exercise a single-runtime backend
    (``test_cp_nvm_backend.py``, ``test_mp_adapter_on_device.py``)
    declare a module-level marker matching the source-file convention::

        __chumicro_runtimes__ = ("circuitpython",)

    Without this filter, the plugin parametrizes every test in the
    file with both runtimes when ``defaults.ide_runtime: both`` is
    set in ``devices.yml`` — and the wrong-runtime parametrization
    fails at import time because the per-runtime source module
    (e.g. ``chumicro_kvstore._backends.cp_nvm``) was never staged on
    the wrong-runtime device.

    The marker is read via :func:`read_runtime_marker` (AST-only,
    same path the deploy pipeline uses).  Sub-runtime names like
    ``micropython_esp32`` fold into their base (``micropython``),
    matching :func:`chumicro_deploy.runtime_marker.file_targets_runtime`.

    Files without a marker keep every target — the default-safe path
    for runtime-agnostic tests.
    """
    if targets is None:
        return None
    marker = read_runtime_marker(test_file)
    if marker is None:
        return targets
    folded = {
        name.split("_", 1)[0] if name.startswith("micropython_") else name
        for name in marker
    }
    return [device for device in targets if device.runtime in folded]


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
        #: Library currently staged on each device (flash/copy modes).
        #: Bulk staging is scoped to ONE library at a time so the
        #: drive working-set stays bounded — a 491 KB Pi Pico W
        #: CIRCUITPY drive can't hold every library's source +
        #: every library's test files at once.  When a test for a
        #: different library runs, the next stage rsync uses
        #: ``--delete`` to clean the prior library off the drive.
        self._staged_library: dict[str, str] = {}
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

    def current_staged_library(self, device_id: str) -> str | None:
        """Return the library currently bulk-staged on a device.

        In flash/copy modes, staging is scoped to ONE library at a
        time — the rsync payload (library src + that library's test
        files) plus boot files must fit on the drive.  Pi Pico W
        CIRCUITPY drives are 491 KB; staging every library at once
        overflows.  Per-library staging keeps the drive working-set
        bounded; rsync ``--delete`` cleans the prior library when
        switching.

        Args:
            device_id: Device identifier.

        Returns:
            The library name currently staged, or ``None`` when no
            library is staged yet (i.e. fresh transport).
        """
        return self._staged_library.get(device_id)

    def mark_library_staged(self, device_id: str, library_name: str) -> None:
        """Record that a library has been bulk-staged onto a device.

        Args:
            device_id: Device identifier.
            library_name: The library whose source + test files now
                live on the device.  Replaces any previously-staged
                library marker.
        """
        self._staged_library[device_id] = library_name

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
        self._staged_library.pop(device_id, None)

    def disconnect_all(self) -> None:
        """Disconnect all cached transports.

        ``disconnect()`` is pure teardown — exits raw REPL (Ctrl-B)
        and closes the serial port.  It deliberately does NOT touch
        ``supervisor.runtime.autoreload`` or fire an explicit Ctrl-D
        soft-reboot; both were removed in the deploy-audit pass after
        the ESP32-S2 USB-CDC double-reboot wedge (2026-05-03 Lolin S2
        bake).

        Net effect at session end: each board is left in friendly
        REPL with the serial port closed.  On the ``deploy_files``
        path autoreload is already back to default-on (the deploy
        soft-reboot reset it); on the functional-test path autoreload
        stays off until the user resets / power-cycles the board,
        which is acceptable because tests drive the raw REPL directly
        and never depend on ``code.py``-style reload-on-edit.
        """
        for transport in self._transports.values():
            try:
                transport.disconnect()
            except Exception:  # pragma: no cover
                pass
        self._transports.clear()
        self._last_staged.clear()
        self._staged_library.clear()
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
        raw_targets = _session_targets(self.session)
        targets = _filter_targets_by_marker(raw_targets, self.path)

        if targets is not None and not targets:
            # File's ``__chumicro_runtimes__`` marker excludes every
            # configured target.  Yield nothing so the IDE / pytest
            # collection shows zero items for this file rather than
            # generating wrong-runtime ImportError items.
            return

        # Preserve the original "session has both runtimes ⇒ suffix names"
        # convention even when the marker filters down to a single target.
        # That keeps the IDE display consistent across runtime-agnostic and
        # runtime-restricted files when ``defaults.ide_runtime: both``.
        session_has_both_runtimes = (
            raw_targets is not None and len(raw_targets) > 1
        )

        if targets is None or (len(targets) <= 1 and not session_has_both_runtimes):
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
            device_entry = _load_fallback_device(self.session)
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
        deploy_mode = _session_deploy_mode_override(self.session)

        try:
            transport = cache.get_transport(device_entry, deploy_mode)
        except Exception as error:
            cache.cache_batch_result(
                self._batch_key(device_entry),
                None,
                f"Transport connection failed: {error}",
            )
            pytest.fail(f"Transport connection failed: {error}")

        # Flash/copy modes persist files on the device filesystem,
        # so we bulk-stage one library's sources + test files per
        # rsync.  Per-library scope keeps the drive working-set
        # bounded — Pi Pico W CIRCUITPY drives are 491 KB; staging
        # every library at once overflows.  When switching libraries
        # the next rsync ``--delete`` cleans the prior library off.
        # RAM mode embeds source inline, so it re-stages per file.
        is_filesystem_mode = transport.mode not in ("ram", "mount")
        if is_filesystem_mode:
            current_library = cache.current_staged_library(
                device_entry.identifier,
            )
            if current_library != self._library_name:
                _bulk_stage_for_device(
                    self.session,
                    device_entry,
                    transport,
                    library_filter=self._library_name,
                )
                cache.mark_library_staged(
                    device_entry.identifier, self._library_name,
                )
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
                    self.library_dir,
                    libraries_root=_libraries_root(self.session),
                    test_files=[self.test_file],
                )
                transport.stage(
                    source_dirs,
                    [self.test_file],
                    _harness_source_dir(self.session),
                    extra_files=_encode_runtime_config_extra_files(
                        self.session.config,
                    ),
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
            transport = cache.get_transport(
                device_entry, _session_deploy_mode_override(self.session),
            )

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


def _load_fallback_device(session: pytest.Session) -> DeviceEntry:
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
        devices, defaults = load_device_registry(
            workspace_root=_workspace_root(session),
        )
    except DeviceConfigError as error:
        error_message = str(error)
        if "not found" in error_message:
            pytest.skip(
                "No devices.yml found.  Run "
                "`chumicro-workspace add-device <id> --address <port>` "
                "to register a board for functional tests."
            )
        pytest.fail(f"Device config error: {error}")

    targets = resolve_ide_devices(devices, defaults)
    if not targets:
        pytest.skip(
            "No devices registered in devices.yml.  Run "
            "`chumicro-workspace add-device <id> --address <port>` "
            "to register a board — probes hardware identity + fills in "
            "defaults on first registration."
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
    *,
    library_filter: str | None = None,
) -> None:
    """Stage one library's sources and test files for a device in one pass.

    In flash/copy modes, files persist on the device filesystem so
    we deploy a library's full source + every test file for that
    library in one rsync (or ``mpremote fs cp``).  This reduces
    invocations from N-per-file to 1-per-library — and per-library
    scope keeps the drive working-set bounded, since a 491 KB Pi
    Pico W CIRCUITPY drive can't hold every library's source + every
    library's test files at once.  Switching libraries triggers a
    fresh stage; rsync ``--delete`` cleans the prior library off.

    Collects all :class:`DeviceTestItem` instances targeting the
    given device + library from the session's collected items,
    deduplicates their library source directories and test files,
    and calls ``transport.stage()`` once.

    Args:
        session: The pytest session (provides ``items``).
        device_entry: The target device.
        transport: A connected transport instance.
        library_filter: When set, only items whose ``library_dir.name``
            matches are included.  Required in practice for
            filesystem-mode staging — ``None`` collects every library
            in the session, which only fits on devices with ample
            spare flash.
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
        if library_filter is not None and item.library_dir.name != library_filter:
            continue

        # Collect source dirs for this item's library.
        for source_dir in resolve_library_source_dirs(
            item.library_dir,
            libraries_root=_libraries_root(session),
            test_files=[item.test_file],
        ):
            if source_dir not in seen_source_dirs:
                seen_source_dirs.append(source_dir)

        # Collect test file (deduplicate by path string).
        test_file_key = str(item.test_file)
        if test_file_key not in seen_test_file_ids:
            seen_test_file_ids.add(test_file_key)
            seen_test_files.append(item.test_file)

    transport.stage(
        seen_source_dirs,
        seen_test_files,
        _harness_source_dir(session),
        extra_files=_encode_runtime_config_extra_files(session.config),
    )


# ---------------------------------------------------------------------------
# Pytest hooks
# ---------------------------------------------------------------------------


def _is_library_functional_test(file_path: Path) -> bool:
    """Return ``True`` for ``libraries/<name>/functional_tests/test_*.py`` paths."""
    if not (
        file_path.suffix == ".py"
        and file_path.name.startswith("test_")
        and "functional_tests" in file_path.parts
    ):
        return False
    functional_index = file_path.parts.index("functional_tests")
    return (
        functional_index >= 2
        and file_path.parts[functional_index - 2] == "libraries"
    )


class _NoImportModule(pytest.Module):
    """Stub Module that yields nothing without importing the file.

    Returned by :func:`pytest_pycollect_makemodule` for files under
    ``libraries/<name>/functional_tests/`` so the host never tries to
    import device-only modules at collection time.  The
    :class:`DeviceTestFile` collector returned by
    :func:`pytest_collect_file` handles those files via AST — no import.
    """

    def collect(self) -> Iterator[pytest.Item]:
        """Yield nothing.  The device-side collector owns these items."""
        return iter([])


def pytest_pycollect_makemodule(
    module_path: Path, parent: pytest.Collector,
) -> pytest.Module | None:
    """Suppress default Module collection for library functional tests.

    Without this, pytest's default Module factory imports the file
    during collection, which fails for runtime-restricted files
    declaring ``__chumicro_runtimes__`` since they import device-only
    modules at top level (``import microcontroller``, ``import wifi``).

    Returning a no-import stub keeps the device-side collector
    (:class:`DeviceTestFile`) as the sole owner of these files;
    AST-based discovery means the file is never executed on the host.
    """
    if _is_library_functional_test(module_path):
        return _NoImportModule.from_parent(  # pyright: ignore[reportUnknownMemberType]
            parent, path=module_path,
        )
    return None


def pytest_collect_file(
    parent: pytest.Collector, file_path: Path,
) -> DeviceTestFile | None:
    """Collect library functional test files as device test items.

    Activates only for ``test_*.py`` under
    ``libraries/<name>/functional_tests/`` — the test-harness-based
    on-device flow (stage/execute, result_parser).  Workbench
    packages also keep hardware-gated tests under a
    ``functional_tests/`` directory, but those are plain host-side
    pytest that call ``chumicro_deploy`` against a real board; they
    must not be routed through the library test harness and are left
    to run as ordinary pytest collection.

    No environment variable required — ``devices.yml`` is the gate
    (checked at collection/run time).
    """

    if not _is_library_functional_test(file_path):
        return None

    return DeviceTestFile.from_parent(parent, path=file_path)  # pyright: ignore[reportUnknownMemberType]


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item],
) -> None:
    """Belt-and-suspenders: deselect any non-device items under functional tests.

    The :func:`pytest_pycollect_makemodule` hook already prevents the
    default Module factory from importing files under
    ``libraries/<name>/functional_tests/``, so duplicate items should
    never be produced in practice.  This sweep exists as a safety net
    in case another plugin re-introduces a non-:class:`DeviceTestItem`
    item for one of these paths — the device transport remains the
    sole execution surface.
    """
    deselected: list[pytest.Item] = []
    selected: list[pytest.Item] = []
    for item in items:
        if (
            "functional_tests" in item.nodeid
            and "libraries/" in item.nodeid
            and not isinstance(item, DeviceRuntimeItem)
        ):
            deselected.append(item)
        else:
            selected.append(item)
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = selected


def pytest_sessionstart(session: pytest.Session) -> None:
    """Initialize the transport cache and resolve target devices.

    Applies ``--chumicro-runtime`` / ``--chumicro-micropython-device`` /
    ``--chumicro-circuitpython-device`` overrides on top of the
    ``devices.yml`` defaults before picking target devices, so the
    pytest invocation mirrors what the ``test-libraries-functional`` CLI used to do
    in its own orchestrator.  Omitted options leave the defaults
    untouched, so IDE play-button runs continue to use
    ``devices.yml`` defaults with no explicit flags.
    """
    session._device_transport_cache = _TransportCache()  # type: ignore[attr-defined]

    runtime_override = cast(
        "str | None",
        session.config.getoption("--chumicro-runtime", default=None),
    )
    mp_override = cast(
        "str | None",
        session.config.getoption("--chumicro-micropython-device", default=None),
    )
    cp_override = cast(
        "str | None",
        session.config.getoption("--chumicro-circuitpython-device", default=None),
    )
    deploy_mode_override = cast(
        "str | None",
        session.config.getoption("--chumicro-deploy-mode", default=None),
    )

    # Eagerly resolve target devices so collection can parametrize
    # by runtime when ide_runtime is "both".
    try:
        devices, defaults = load_device_registry(
            workspace_root=_workspace_root(session),
        )
    except DeviceConfigError:
        session._device_targets = None  # type: ignore[attr-defined]
    else:
        effective_defaults = DeviceDefaults(
            micropython=mp_override or defaults.micropython,
            circuitpython=cp_override or defaults.circuitpython,
            deploy_mode=deploy_mode_override or defaults.deploy_mode,
            ide_runtime=runtime_override or defaults.ide_runtime,
        )
        session._device_targets = resolve_ide_devices(  # type: ignore[attr-defined]
            devices, effective_defaults,
        )

    if session.config.getoption("--chumicro-pr-summary", default=False):
        session._chumicro_pr_summary = _PRSummaryCollector()  # type: ignore[attr-defined]


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Disconnect transports at session end; emit the PR block when requested."""
    cache = getattr(session, "_device_transport_cache", None)
    if cache is not None:
        cast("_TransportCache", cache).disconnect_all()

    collector = _session_pr_summary(session)
    if collector is None:
        return
    per_device_results = collector.render()
    if not per_device_results:
        return
    command = cast(
        "str | None",
        session.config.getoption("--chumicro-pr-summary-command", default=None),
    )
    if not command:
        command = "pytest"
    total_duration = collector.session_duration()

    total_passed = sum(device.passed for device in per_device_results)
    total_failed = sum(device.failed for device in per_device_results)
    total_errors = sum(device.errors for device in per_device_results)

    print(f"\n{'=' * 60}")
    print(
        f"Device test summary: {total_passed} passed, "
        f"{total_failed} failed, {total_errors} errors "
        f"in {_format_seconds(total_duration)}"
    )
    print(f"{'=' * 60}")

    pr_block = format_pr_summary_block(
        command, per_device_results, total_duration,
    )
    print("\nPR summary (paste into the 'Device testing' section of your PR):")
    print("-" * 60)
    print(pr_block)
    print("-" * 60)


def _format_seconds(seconds: float) -> str:
    """Format a wall-clock span for the top-of-summary banner."""
    if seconds < 1.0:
        return f"{int(round(seconds * 1000))}ms"
    return f"{seconds:.2f}s"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None],
) -> Generator[None, None, None]:
    """Inject device durations into reports and feed the PR-summary collector."""
    outcome = yield
    report = cast(pytest.TestReport, outcome.get_result())  # type: ignore[attr-defined]
    if isinstance(item, DeviceRuntimeItem):
        _apply_reported_duration(item, report)
        if report.when == "call":
            collector = _session_pr_summary(item.session)
            if collector is not None:
                collector.record(item, report)
