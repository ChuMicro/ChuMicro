"""Pytest plugin for routing functional tests to real hardware.

When pytest collects a file from a ``functional_tests/`` directory,
this plugin intercepts it and wraps each ``test_*`` function as a
:class:`DeviceTestItem`.  Instead of importing and running the test
locally, the item stages source code on a connected board, executes
the test via the device transport, and parses the harness output to
report pass/fail to pytest.  A ``libraries/<name>/functional_tests/``
tree is always routed; a ``projects/<name>/functional_tests/`` tree is
routed only when the invocation explicitly targets it (a bare workspace
sweep leaves project functional tests deselected).

**No environment variable setup is required.**  The plugin reads
``devices.yml`` to find the target device(s).  A top-level
``defaults:`` section controls which board(s) the IDE targets:

.. code-block:: yaml

   defaults:
     micropython: my-mp-board
     circuitpython: my-cp-board
     deploy_mode: flash      # ram | flash (flash is the default)
     ide_runtime: both       # or micropython, or circuitpython

When ``ide_runtime`` is ``both``, each test function is collected
twice, once per runtime, so the IDE shows separate pass/fail
results for MicroPython and CircuitPython.

This enables IDE play buttons (PyCharm, VS Code) to run device
tests at file and function granularity. Just click play.

Functional test files that exercise a single-runtime backend can
opt out of the wrong-runtime parametrization with a module-level
``__chumicro_runtimes__`` marker, the same convention the bundle
and deploy pipelines use for source files::

    __chumicro_runtimes__ = ("circuitpython",)
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Generator
from typing import cast

import pytest
from chumicro_deploy import (
    DEFAULT_DEPLOY_MODE,
    DeployMode,
    DeviceConfigError,
    DeviceDefaults,
    DeviceEntry,
    DeviceImplementation,
    load_device_registry,
    resolve_ide_devices,
)

from .backends import (
    _DEFAULT_EXECUTE_TIMEOUT_SECONDS,
    HEAPSIZE_FROM_CONFIG,
    UnixPortBackend,
)
from .collection import (
    DevicePrepareItem,
    DeviceRunFileItem,
    DeviceRuntimeItem,
    DeviceTestItem,
    _session_effective_deploy_mode,
    pytest_collect_file,  # noqa: F401, re-export for pytest11 entry-point discovery
    pytest_collection_modifyitems,  # noqa: F401, same
    pytest_ignore_collect,  # noqa: F401, same
    pytest_pycollect_makemodule,  # noqa: F401, same
)
from .device_backend import DeviceBackend
from .pr_summary import (
    DeviceRunResult,
    FileRunResult,
    format_duration,
    format_pr_summary_block,
)
from .result_parser import TestResult
from .session import (
    _session_cache,
    _session_pr_summary,
    _target_is_unix_port,
    _workspace_root,
)
from .transport_cache import _TransportCache

# Sub-plugin: registers device_bootstrap_runner + http_client_against_board
# fixtures so Category 1 host-driver tests can pick them up without each
# consumer wiring a conftest import.
pytest_plugins = ("chumicro_pytest_device.fixtures.host_driver",)


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register ChuMicro command-line options on the pytest CLI.

    Each option overrides the corresponding ``defaults:`` entry in
    ``devices.yml`` when supplied. When omitted, ``devices.yml``
    defaults still drive selection so IDE play-button runs keep
    working with zero configuration.

    Options:

    - ``--runtime`` (``micropython`` / ``circuitpython`` / ``both``):
      overrides ``defaults.ide_runtime``.
    - ``--micropython-device`` / ``--circuitpython-device``:
      per-runtime device-ID overrides.
    - ``--deploy-mode`` (``ram`` / ``flash``): overrides the
      per-device ``deploy_mode`` and ``defaults.deploy_mode``.
    - ``--pr-summary``: when set, prints a Markdown device-testing
      block at session end. Opt-in so IDE play-button runs stay quiet.
    - ``--pr-summary-command``: literal command string to render in
      the ``- Command:`` line of the PR block.  The calling
      orchestrator passes the reconstructed invocation. Direct pytest
      runs can omit it and get the raw ``pytest ...``.
    """
    group = parser.getgroup("chumicro", "ChuMicro device-test plugin")
    group.addoption(
        "--target",
        choices=("device", "device-unit", "unix-port"),
        default="device",
        help=(
            "execution backend: 'device' (functional_tests on a board "
            "via the chumicro-deploy transport), 'device-unit' (the "
            "cross-runtime libraries/<name>/tests suite on a board, "
            "the on-device unit sweep), or 'unix-port' (that same unit "
            "suite in a MicroPython / CircuitPython unix-port "
            "subprocess)"
        ),
    )
    group.addoption(
        "--runtime",
        choices=("micropython", "circuitpython", "both"),
        default=None,
        help="override devices.yml defaults.ide_runtime",
    )
    group.addoption(
        "--micropython-device",
        default=None,
        help="override devices.yml defaults.micropython device ID",
    )
    group.addoption(
        "--circuitpython-device",
        default=None,
        help="override devices.yml defaults.circuitpython device ID",
    )
    group.addoption(
        "--micropython-binary",
        default=None,
        help=(
            "unix-port MicroPython binary path "
            "(overrides .tools/micropython.path and PATH lookup)"
        ),
    )
    group.addoption(
        "--circuitpython-binary",
        default=None,
        help=(
            "unix-port CircuitPython binary path "
            "(overrides .tools/circuitpython.path and PATH lookup)"
        ),
    )
    group.addoption(
        "--unix-port-timeout",
        type=float,
        default=_DEFAULT_EXECUTE_TIMEOUT_SECONDS,
        help=(
            "per-file wall-clock ceiling (seconds) for a unix-port "
            "worker subprocess; a file that exceeds it is killed and "
            f"fails cleanly (default {_DEFAULT_EXECUTE_TIMEOUT_SECONDS:g})"
        ),
    )
    group.addoption(
        "--unix-port-heapsize",
        default=HEAPSIZE_FROM_CONFIG,
        help=(
            "heap ceiling for unix-port workers (e.g. 192K); default "
            "reads per-runtime budgets from target-runtimes.toml "
            "[heap]; pass 0 or off to spawn with the port's native "
            "multi-MB heap"
        ),
    )
    group.addoption(
        "--deploy-mode",
        choices=tuple(mode.value for mode in DeployMode),
        default=None,
        help="override per-device deploy_mode (ram / flash)",
    )
    group.addoption(
        "--pr-summary",
        action="store_true",
        default=False,
        help="print a Markdown PR block at session end",
    )
    group.addoption(
        "--pr-summary-command",
        default=None,
        help="command string to render inside the PR block",
    )
    group.addoption(
        "--per-file",
        action="store_true",
        default=False,
        help=(
            "flash/copy device-unit only: soft-reset before each test "
            "*file* (not just each library), so a large class-organized "
            "module runs on a fresh interpreter.  Opt-in: the default "
            "per-library reset is faster and enough for PSRAM boards / "
            "small libraries. Use this for large suites on a 256 KB board"
        ),
    )


class _PRSummaryCollector:
    """Accumulate per-(device, file, test) outcomes for the PR block.

    The collector receives one call per pytest report (via
    ``pytest_runtest_makereport``) and rolls the results up into the
    :class:`DeviceRunResult` shape ``pr_summary.format_pr_summary_block``
    expects.  Empty containers are populated on first encounter and
    the overall order (device declaration order, then file declaration
    order) matches the calling orchestrator's output so the Markdown is
    stable across the two code paths.
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
                _session_effective_deploy_mode(item.session, device),
            )
            cache = _session_cache(item.session)
            transport = cache.peek_transport(device_id)
            if transport is not None:
                try:
                    self._implementations[device_id] = (
                        transport.probe_implementation()
                    )
                except Exception:  # pragma: no cover, hardware-only
                    self._implementations[device_id] = None

        if isinstance(item, DevicePrepareItem):
            # A failing prepare step means bulk-stage / connect failed.
            # No per-test items will produce results for this file.
            if report.failed:
                self._bulk_stage_errors[device_id] += 1
            return

        if isinstance(item, DeviceRunFileItem):
            # A failing run-file means the batch exec failed. Count one
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

        per_test_duration = item.reported_duration
        if per_test_duration is not None:
            file_result.duration_seconds += per_test_duration
        file_result.tests.append(TestResult(
            name=item.function_name,
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

    reported_duration = getattr(item, "reported_duration", None)
    if reported_duration is not None:
        report.duration = reported_duration
        return

    reported_test_total_duration = getattr(
        item, "reported_test_total_duration", None,
    )
    if reported_test_total_duration is None:
        return

    report.duration = max(report.duration - reported_test_total_duration, 0.0)


def pytest_configure(config: pytest.Config) -> None:
    """Register pytest markers this plugin recognises.

    Required under ``--strict-markers`` (set in the workspace's
    ``pyproject.toml``); without registration, a test that uses
    ``@pytest.mark.device_bootstrap(...)`` would fail to collect.
    """
    config.addinivalue_line(
        "markers",
        "device_bootstrap(board_file): override the sibling-name rule for "
        "device_bootstrap_runner: name the board-side bootstrap file "
        "(resolved relative to the host test file's directory).",
    )


def pytest_sessionstart(session: pytest.Session) -> None:
    """Initialize the transport cache, pick a backend, and resolve targets.

    Two branches:

    - Default (``--target device``): install :class:`DeviceBackend`,
      load ``devices.yml``, apply ``--runtime`` / ``--micropython-device``
      / ``--circuitpython-device`` overrides on top of the
      ``defaults:`` block.  Omitted options preserve ``devices.yml``
      behavior, so IDE play-button runs work with zero flags.
    - ``--target unix-port``: install :class:`UnixPortBackend`,
      synthesize one or two ``DeviceEntry`` records driven by
      ``--runtime`` (defaults to ``both``).  ``devices.yml`` is not
      consulted, since the unix-port subprocess needs no per-device config.
    """
    session._device_transport_cache = _TransportCache()  # type: ignore[attr-defined]

    runtime_override = cast(
        "str | None",
        session.config.getoption("--runtime", default=None),
    )

    if _target_is_unix_port(session.config):
        mp_binary = cast(
            "str | None",
            session.config.getoption("--micropython-binary", default=None),
        )
        cp_binary = cast(
            "str | None",
            session.config.getoption("--circuitpython-binary", default=None),
        )
        execute_timeout = cast(
            "float",
            session.config.getoption(
                "--unix-port-timeout",
                default=_DEFAULT_EXECUTE_TIMEOUT_SECONDS,
            ),
        )
        heapsize = cast(
            "str",
            session.config.getoption(
                "--unix-port-heapsize",
                default=HEAPSIZE_FROM_CONFIG,
            ),
        )
        session._backend = UnixPortBackend(  # type: ignore[attr-defined]
            _workspace_root(session),
            binaries={
                "micropython": mp_binary,
                "circuitpython": cp_binary,
            },
            execute_timeout_seconds=execute_timeout,
            heapsize=heapsize,
        )
        session._device_targets = _synthesize_unix_port_targets(  # type: ignore[attr-defined]
            runtime_override or "both",
        )
    else:
        session._backend = DeviceBackend()  # type: ignore[attr-defined]
        mp_override = cast(
            "str | None",
            session.config.getoption("--micropython-device", default=None),
        )
        cp_override = cast(
            "str | None",
            session.config.getoption("--circuitpython-device", default=None),
        )
        deploy_mode_override = cast(
            "str | None",
            session.config.getoption("--deploy-mode", default=None),
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

    if session.config.getoption("--pr-summary", default=False):
        session._pr_summary = _PRSummaryCollector()  # type: ignore[attr-defined]


def _synthesize_unix_port_targets(runtime_selection: str) -> list[DeviceEntry]:
    """Build synthetic ``DeviceEntry`` records for the unix-port path.

    Unix-port runs don't have a real device registry: the "target"
    is the (runtime, binary path) pair.  We reuse :class:`DeviceEntry`
    so collection / parametrization / PR-summary code stays uniform;
    ``address="unix-port"`` is the sentinel that flags a synthetic
    entry for any device-aware code path that ever wants to discriminate.
    """
    if runtime_selection == "micropython":
        runtimes = ("micropython",)
    elif runtime_selection == "circuitpython":
        runtimes = ("circuitpython",)
    else:
        runtimes = ("micropython", "circuitpython")
    return [
        DeviceEntry(
            identifier=f"{runtime}-unix-port",
            runtime=runtime,
            address="unix-port",
        )
        for runtime in runtimes
    ]


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Disconnect transports at session end, and emit the PR block when requested."""
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
        session.config.getoption("--pr-summary-command", default=None),
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
        f"in {format_duration(total_duration)}"
    )
    print(f"{'=' * 60}")

    pr_block = format_pr_summary_block(
        command, per_device_results, total_duration,
    )
    print("\nPR summary (paste into the 'Device testing' section of your PR):")
    print("-" * 60)
    print(pr_block)
    print("-" * 60)


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
