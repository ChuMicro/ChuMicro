"""Collection-time machinery: AST-based test discovery and pytest items.

The pytest hooks here intercept files under
``libraries/<name>/functional_tests/`` (always),
``projects/<name>/functional_tests/`` (only when explicitly targeted;
:func:`pytest_ignore_collect` drops them on a bare sweep), and
``libraries/<name>/tests/`` (under ``--target unix-port`` /
``--target device-unit``), returning a :class:`DeviceTestFile` so
the host never imports a file that top-level imports a device-only
module.  :class:`DeviceTestFile` parses test names via AST and
yields one :class:`DeviceTestItem` per ``(test_function,
target_runtime)`` pair, plus synthetic
:class:`DevicePrepareItem` and :class:`DeviceRunFileItem` items
that own the once-per-file-batch connect / stage / execute cost.
"""

from __future__ import annotations

import ast
import warnings
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from chumicro_deploy import (
    DeviceCaps,
    DeviceConfigError,
    DeviceEntry,
    TransportProtocol,
    find_libraries_requiring_flash,
    load_device_registry,
    resolve_deploy_mode,
    resolve_ide_devices,
)
from chumicro_deploy.runtime_marker import is_host_only_test, read_runtime_marker
from chumicro_workspace.device_orchestration import (
    resolve_effective_deploy_mode,
    resolve_library_source_dirs,
    resolve_project_source_dirs,
)

from .backends import BackendExecuteError, BackendPrepareError
from .features import (
    FEATURE_PROBE_SCRIPT,
    parse_feature_probe_output,
    read_features_marker,
)
from .pr_summary import runtime_display_name
from .result_parser import RunResult, TestResult, parse_output
from .runtime_config import missing_required_keys
from .session import (
    _collect_unit_tests_on_device_backend,
    _encode_runtime_config_extra_files,
    _harness_source_dir,
    _is_library_functional_test,
    _is_library_unit_test,
    _is_project_functional_test,
    _libraries_root,
    _project_functional_test_targeted,
    _project_unit_name,
    _session_backend,
    _session_cache,
    _session_targets,
    _target_is_device_unit,
    _target_is_unix_port,
    _workspace_root,
)


def _assert_summary_reconciles(result: RunResult, raw_output: str) -> None:
    """Fail the batch on a missing SUMMARY, a dropped FAIL, or a phantom line.

    The device prints an authoritative ``SUMMARY total=N failed=M`` as the
    last line of a complete run.  Its absence means the run was truncated
    before finishing (a board that crashed mid-run, a serial drop): a
    partial transcript that reads green when the surviving lines all
    passed.  A ``failed`` count higher than the parsed FAIL lines means a
    failure result was dropped from the output, which is the dangerous
    case: a real failure silently vanishing into a pass.

    More parsed result lines than the device's own ``total`` means a
    stray line that looks like a PASS/FAIL/SKIP was injected: free-form
    board prose, print-debugging, or an exception message that happens to
    match a result pattern.  A phantom ``PASS test_b`` emitted before
    ``test_b``'s real ``FAIL`` would let the first-match per-test lookup
    report PASS, so an extra line over ``total`` fails the batch.  The
    fewer-lines direction (``total`` exceeds parsed lines) is deliberately
    left to the per-test "not found in device output" guard, which
    pinpoints the missing test instead of failing the whole batch.
    """
    summary = result.summary
    if summary is None:
        pytest.fail(
            f"Device output has no SUMMARY line; the run was truncated "
            f"before finishing (board crash or serial drop):\n{raw_output}"
        )
    parsed_failed = sum(1 for test in result.tests if test.status == "FAIL")
    if summary.failed != parsed_failed:
        pytest.fail(
            f"Device SUMMARY reports failed={summary.failed} but {parsed_failed} "
            f"FAIL line(s) were parsed; a failure result was dropped from the "
            f"output (board crash or serial glitch):\n{raw_output}"
        )
    if len(result.tests) > summary.total:
        pytest.fail(
            f"Device output parsed {len(result.tests)} result line(s) but "
            f"SUMMARY reports total={summary.total}; a stray line matching a "
            f"PASS/FAIL/SKIP pattern was injected and could mask a real "
            f"result via first-match lookup:\n{raw_output}"
        )


def _collected_test_names(
    session: pytest.Session,
    device_entry: DeviceEntry,
    test_file: Path,
) -> set[str]:
    """Return the ``function_name``s the host collected for one file batch.

    Walks ``session.items`` for ``DeviceTestItem``s that target
    *device_entry* and came from *test_file*, and returns their bare
    ``function_name``s (the same qualified form the harness prints, no
    per-runtime display suffix).
    """
    names: set[str] = set()
    for item in session.items:
        if not isinstance(item, DeviceTestItem):
            continue
        target = item.target_device
        if target is None or target.identifier != device_entry.identifier:
            continue
        if item.test_file != test_file:
            continue
        names.add(item.function_name)
    return names


def _assert_collected_reconciles(
    result: RunResult,
    raw_output: str,
    collected_names: set[str],
    test_file: Path,
) -> None:
    """Fail the batch when the device ran tests the host never collected.

    Host-side collection walks the file's AST
    (:func:`_parse_test_functions`): module-level ``def test_*`` and the
    direct ``test_*`` children of a ``class Test*``.  The on-device runner
    discovers tests at runtime via ``dir()``, which also surfaces
    ``test_*`` methods *inherited* from a base class and module-level
    ``test_name = _factory()`` bindings, tests with no ``DeviceTestItem``
    to map their result onto.  A FAIL among them reconciles symmetrically
    against SUMMARY (the orphan FAIL inflates both the parsed and reported
    counts) and the session exits green.  Cross-checking the device-run
    names against the collected set surfaces the orphan instead of
    dropping it, and a device ``total`` that differs from the collected
    count catches the same divergence by cardinality.
    """
    orphans = sorted(
        {test.name for test in result.tests if test.name not in collected_names}
    )
    if orphans:
        pytest.fail(
            f"Device ran test(s) the host never collected for {test_file.name}: "
            f"{', '.join(orphans)}; these have no pytest item, so a FAIL among "
            f"them would reconcile against SUMMARY and vanish into a green "
            f"run:\n{raw_output}"
        )
    if result.summary is not None and result.summary.total != len(collected_names):
        pytest.fail(
            f"Device SUMMARY reports total={result.summary.total} but the host "
            f"collected {len(collected_names)} test(s) for {test_file.name}; the "
            f"device ran a different set than was collected:\n{raw_output}"
        )


def _parse_test_functions(filepath: Path) -> list[str]:
    """Use AST to discover test names without importing.

    Functional test files import device-only modules that are not
    available on the host, so we cannot import them.

    Mirrors the on-device runner's discovery rules
    (:func:`chumicro_test_harness.runner._iter_test_functions`):
    module-level ``def test_*`` functions, plus ``test_*`` methods on
    ``class Test*`` classes reported as ``ClassName.test_method``. That is the
    exact qualified-name format the runner produces, so single-test
    name filters and per-item reporting line up between collection and
    execution.

    ``async def test_*`` is collected too, at module level and as a
    ``Test*`` method.  The runner discovers it via ``dir()`` and fails it
    (an ``async def`` body never runs; calling it only builds an
    un-awaited coroutine).  Collecting it here gives that FAIL a pytest
    item to land on: without it the device-run name is an orphan that
    fails the whole file's reconcile instead of just that one test.  A
    generator-bodied ``def test_*`` (a stray ``yield``) needs no special
    case: its AST node is a plain ``FunctionDef`` already matched below,
    and the runner fails it the same way.

    Args:
        filepath: Path to the test file.

    Returns:
        Sorted list of test names: bare ``test_*`` for module-level
        functions, ``ClassName.test_method`` for class methods.
    """
    source = filepath.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(filepath))
    function_defs = (ast.FunctionDef, ast.AsyncFunctionDef)
    names: list[str] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, function_defs) and node.name.startswith("test_"):
            names.append(node.name)
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            names.extend(
                f"{node.name}.{method.name}"
                for method in ast.iter_child_nodes(node)
                if isinstance(method, function_defs)
                and method.name.startswith("test_")
            )
    return sorted(names)


def _resolve_library_dir(test_file: Path) -> Path:
    """Derive the owning root directory from a functional test file path.

    Expects the pattern ``libraries/<name>/functional_tests/test_*.py``.
    The same ``parent.parent`` shape holds for a project functional test
    (``projects/<name>/functional_tests/test_*.py``), where it yields the
    project directory instead of a library root.

    Args:
        test_file: Path to a test file inside ``functional_tests/``.

    Returns:
        The library root directory (e.g. ``libraries/timing``), or the
        project directory for a project functional test.
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
    set in ``devices.yml``, and the wrong-runtime parametrization
    fails at import time because the per-runtime source module
    (e.g. ``chumicro_kvstore._backends.cp_nvm``) was never staged on
    the wrong-runtime device.

    The marker is read via :func:`read_runtime_marker` (AST-only,
    same path the deploy pipeline uses).  Sub-runtime names like
    ``micropython_esp32`` fold into their base (``micropython``),
    matching :func:`chumicro_deploy.runtime_marker.file_targets_runtime`.

    Files without a marker keep every target: the default-safe path
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


def _runtime_prepare_name(device_entry: DeviceEntry) -> str:
    """Return the synthetic pytest item name for a runtime prepare step."""
    return f"Setup: {runtime_display_name(device_entry.runtime)}"


def _runtime_run_file_name(device_entry: DeviceEntry) -> str:
    """Return the synthetic pytest item name for a runtime file-run step."""
    return f"Run overhead: {runtime_display_name(device_entry.runtime)}"


def _sum_reported_test_durations(test_results: list[TestResult]) -> float:
    """Return the total device-reported duration across parsed tests."""
    total_duration = 0.0
    for test_result in test_results:
        if test_result.duration is not None:
            total_duration += test_result.duration
    return total_duration


def _device_items(
    session: pytest.Session, device_entry: DeviceEntry,
) -> Iterator[DeviceTestItem]:
    """Yield every collected ``DeviceTestItem`` that targets *device_entry*.

    Skips items with no resolved target and items pointing at a
    different device by ``identifier``.
    """
    for item in session.items:
        if not isinstance(item, DeviceTestItem):
            continue
        target = item.target_device
        if target is None or target.identifier != device_entry.identifier:
            continue
        yield item


def _item_source_dirs(
    session: pytest.Session, item: DeviceRuntimeItem,
) -> list[Path]:
    """Source-dir closure for one item: the project-aware split point.

    Project functional tests resolve through the workspace's
    acquisition surfaces (:func:`resolve_project_source_dirs`:
    ``workspace.yml`` ``library_sources:`` overrides plus
    ``libraries/<name>/src`` trees); library tests keep the
    libraries-root dependency walk
    (:func:`resolve_library_source_dirs`).  Every consumer of an
    item's closure (deploy-mode resolution and both staging paths)
    must route through here so the two lanes can't drift apart.
    """
    if _is_project_functional_test(item.test_file):
        return resolve_project_source_dirs(
            item.library_dir,
            workspace_root=_workspace_root(session),
            test_files=[item.test_file],
        )
    return resolve_library_source_dirs(
        item.library_dir,
        libraries_root=_libraries_root(session),
        test_files=[item.test_file],
    )


def _device_closure_source_dirs(
    session: pytest.Session, device_entry: DeviceEntry,
) -> list[Path]:
    """Union of every test's library source closure for one device.

    Walks the same dependency closure the staging path uses
    (:func:`_item_source_dirs`) for every ``DeviceTestItem``
    targeting *device_entry*, deduplicated.  Deploy mode is
    session-scoped (one cached transport per device), so the resolver
    must see the whole device's closure up front. A functional test
    that pulls a dependency's data file has to force the session to
    flash *before* a RAM-mode transport gets cached.
    """
    closure: list[Path] = []
    for item in _device_items(session, device_entry):
        for source_dir in _item_source_dirs(session, item):
            if source_dir not in closure:
                closure.append(source_dir)
    return closure


def _device_is_unit_sweep(
    session: pytest.Session, device_entry: DeviceEntry,
) -> bool:
    """True when every test targeting *device_entry* is a unit test.

    The cross-runtime *unit* suite (``libraries/<name>/tests``) and a
    *functional* run (``libraries/<name>/functional_tests``) scope
    ``staged_files`` differently: functional needs the full
    dependency closure (it exercises a dependency's data-file code
    path for real), the unit sweep needs the library's own ``src``
    only (a pure unit test cannot reach a dependency's data file by the
    runtime-boundary contract, so a dependency's data file must not
    poison every dependent suite into flash).  A run is unit-scoped
    only when *all* of the device's items are unit tests. Any
    functional item makes it closure-scoped (the safe direction).
    """
    items = list(_device_items(session, device_entry))
    return bool(items) and all(
        _is_library_unit_test(item.test_file) for item in items
    )


def _device_own_source_dirs(
    session: pytest.Session, device_entry: DeviceEntry,
) -> list[Path]:
    """Each tested library's *own* ``src`` dir (no dependency closure).

    The unit-sweep ``staged_files`` scope: only ``chumicro_sockets``'s
    own suite sees its ``_ca_bundle.der``. A light sockets *user*
    (``ntp``) does not, so the data file does not flip it to flash.
    """
    own: list[Path] = []
    for item in _device_items(session, device_entry):
        source_dir = item.library_dir / "src"
        if source_dir.is_dir() and source_dir not in own:
            own.append(source_dir)
    return own


def _staged_file_names(source_dirs: list[Path]) -> list[str]:
    """Every file the closure would stage, by name.

    ``transport.stage`` copies whole ``src`` trees, so the resolver's
    "any non-``.py`` data file" check must see them all.
    ``__pycache__`` is build cruft the staging rsync never carries.
    Excluding it stops a stray ``.pyc`` being misread as a shipped
    asset and wrongly forcing flash.
    """
    names: list[str] = []
    for source_dir in source_dirs:
        for path in source_dir.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                names.append(path.name)
    return names


def _session_effective_deploy_mode(
    session: pytest.Session, device_entry: DeviceEntry,
) -> str:
    """Return the deploy mode (``flash`` / ``ram`` / ...) for one device.

    Reads the CLI override and the device entry to get the configured
    starting point, then asks :func:`resolve_deploy_mode` to apply
    policy: a flash-only dependency forces flash, a data-file
    dependency may force flash, and so on.  The result is memoized on
    the session cache and any policy-driven mode change is surfaced
    via ``warnings.warn`` exactly once per device.

    Policy inputs scope differently.  ``requires_flash_libs`` always
    walks the full transitive closure: a flash-only dependency OOMs
    on import no matter what shape the test takes.  ``staged_files``
    is caller-scoped: the full closure for a functional run that
    really exercises a dependency's data file, but each library's own
    ``src`` only for the unit sweep, so ``sockets``'s
    ``_ca_bundle.der`` does not flip every sockets-dependent suite
    into flash.
    """
    cache = _session_cache(session)
    device_id = device_entry.identifier
    memoized = cache.resolved_deploy_mode(device_id)
    if memoized is not None:
        return memoized

    deploy_mode_override = cast(
        "str | None",
        session.config.getoption("--deploy-mode", default=None),
    )
    configured = resolve_effective_deploy_mode(
        device_entry, deploy_mode_override,
    )
    closure = _device_closure_source_dirs(session, device_entry)
    staged_dirs = (
        _device_own_source_dirs(session, device_entry)
        if _device_is_unit_sweep(session, device_entry)
        else closure
    )
    mode, message = resolve_deploy_mode(
        configured,
        staged_files=_staged_file_names(staged_dirs),
        device_caps=DeviceCaps(
            supports_ram_mode=device_entry.supports_ram_mode,
        ),
        requires_flash_libs=find_libraries_requiring_flash(closure),
        resolution_unit=None,
        force=None,
    )
    if message is not None:
        warnings.warn(f"Device {device_id!r}: {message}", stacklevel=2)
    cache.set_resolved_deploy_mode(device_id, mode)
    return mode


class DeviceTestFile(pytest.File):
    """Collector that discovers ``test_*`` functions via AST parsing.

    When ``ide_runtime`` is ``both`` in the ``defaults:`` section,
    each test function is collected twice (once per runtime) so
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

        if not function_names:
            # Reached here only when the file is NOT marker-excluded
            # (the ``not targets`` branch above already handled
            # ``__chumicro_runtimes__`` / host-only opt-outs): the file
            # is meant to run on these targets, yet AST finds zero
            # ``test_*`` functions or ``Test*`` class methods.  The
            # harness discovers both shapes, so a zero here means the
            # file is pytest-style (fixtures / parametrize / bare
            # ``import pytest``) the cross-runtime harness cannot run.
            # Fail loudly instead of yielding a silent no-op, so the
            # gap can't hide.
            if _is_library_unit_test(self.path):
                raise pytest.Collector.CollectError(
                    f"{self.path} is collected for the cross-runtime / "
                    "on-device lane but defines no discoverable tests "
                    "(no module-level 'def test_*' and no 'class Test*' "
                    "with 'test_*' methods; its tests are pytest-style, "
                    "which the cross-runtime harness does not run).  "
                    "Either rewrite the tests as plain functions or "
                    "'class Test*' methods, or declare "
                    "'__chumicro_runtimes__ = (\"cpython\",)' to make the "
                    "CPython-only lane explicit.  A silent zero-test "
                    "file is not allowed."
                )
            # Functional-test files (the other DeviceTestFile user)
            # keep the prior no-op behaviour, out of scope here.
            return

        # Preserve the suffix-name convention even when the marker filters
        # down to a single target: when the session has both runtimes, test
        # names carry a per-runtime suffix.  That keeps the IDE display
        # consistent across runtime-agnostic and runtime-restricted files
        # when ``defaults.ide_runtime: both``.
        session_has_both_runtimes = (
            raw_targets is not None and len(raw_targets) > 1
        )

        if targets is None or (len(targets) <= 1 and not session_has_both_runtimes):
            # No config, single target, or no devices: one item per function.
            device = targets[0] if targets else None
            if device is not None:
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
            # Multiple targets (both mode): parametrize by runtime.
            for device in targets:
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
            # Function-then-runtime order keeps the two runtime variants
            # of each base function adjacent in the item stream. Some IDE
            # test explorers build parameterized groups from incoming
            # order and produce duplicate parent nodes when variants are
            # split apart.
            for name in function_names:
                for device in targets:
                    display_name = f"{name}[{runtime_display_name(device.runtime)}]"
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
    preparation and batch-execution helpers.  Those helpers fire once per
    file batch (subsequent calls are no-ops), so synthetic control items
    can perform the expensive work during full-file runs while direct
    single-test targeting still works.
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
        # A project functional test scopes by its slash-form project name
        # (``garage/heater``) so same-named nested projects keep distinct
        # batch cache keys and runtime-config scopes; a library test keeps
        # its directory name.
        self.library_name = (
            _project_unit_name(test_file)
            if _is_project_functional_test(test_file)
            else self.library_dir.name
        )
        self.reported_duration: float | None = None
        self.reported_test_total_duration: float | None = None

    def _resolve_device_entry(self) -> DeviceEntry:
        """Return the resolved target device for this item."""
        device_entry = self.target_device
        if device_entry is None:
            device_entry = _load_fallback_device(self.session)
            self.target_device = device_entry
        return device_entry

    def batch_key(self, device_entry: DeviceEntry) -> tuple[str, str, str]:
        """Return the cache key for this item's file/runtime batch."""
        return (
            device_entry.identifier,
            self.library_name,
            self.test_file.name,
        )

    def _ensure_prepared(self, device_entry: DeviceEntry) -> None:
        """Run the backend's prepare step for this item.

        Connection-style failures (transport-level on device, binary
        not found on unix-port) raise :class:`BackendPrepareError`,
        which we cache as a batch failure so subsequent items for the
        same file fail fast without re-attempting.  Other prepare
        failures (staging exceptions) propagate naturally: they
        either match the previous "uncaught exception during prepare"
        behavior or get caught by ``_ensure_batch_result`` when
        prepare runs as part of execute.
        """
        backend = _session_backend(self.session)
        try:
            backend.prepare(self, device_entry)
        except BackendPrepareError as error:
            cache = _session_cache(self.session)
            cache.cache_batch_result(
                self.batch_key(device_entry),
                None,
                str(error),
            )
            pytest.fail(str(error))

    def _ensure_batch_result(
        self,
        device_entry: DeviceEntry,
    ) -> tuple[RunResult | None, str]:
        """Run the file batch once if needed and return its cached result."""
        cache = _session_cache(self.session)
        batch_key = self.batch_key(device_entry)

        # Check for cached batch result from a previous item.
        batch = cache.get_batch_result(batch_key)

        if batch is None:
            # First item for this (device, file): run all tests.
            self._ensure_prepared(device_entry)
            backend = _session_backend(self.session)
            try:
                raw_output = backend.execute(self, device_entry)
            except BackendExecuteError as error:
                cache.cache_batch_result(batch_key, None, str(error))
                pytest.fail(str(error))

            result = parse_output(raw_output)
            cache.cache_batch_result(batch_key, result, raw_output)
            return result, raw_output

        return batch

    def _require_batch_result(
        self,
        device_entry: DeviceEntry,
    ) -> tuple[RunResult, str]:
        """Run the file batch and return a result guaranteed to hold tests.

        Wraps :meth:`_ensure_batch_result` with the two failure guards
        every ``runtest`` shares: a ``None`` result (the batch failed to
        prepare or execute) fails the item with the raw device output; a
        result that parsed zero tests fails with the raw output too,
        since a file that ran but reported nothing is a harness error,
        not a pass.  Returns the parsed result and the raw output the
        caller still needs for per-test lookup.
        """
        result, raw_output = self._ensure_batch_result(device_entry)
        if result is None:
            pytest.fail(raw_output)
        if not result.tests:
            pytest.fail(f"No test results in device output:\n{raw_output}")
        _assert_summary_reconciles(result, raw_output)
        collected_names = _collected_test_names(
            self.session, device_entry, self.test_file,
        )
        _assert_collected_reconciles(
            result, raw_output, collected_names, self.test_file,
        )
        return result, raw_output

    def repr_failure(
        self,
        excinfo: pytest.ExceptionInfo[BaseException],
        style: str | None = None,
    ) -> str:
        """Produce a readable failure representation."""
        return str(excinfo.value)

    def reportinfo(self) -> tuple[Path, int | None, str]:
        """Return location info for test reporting."""
        return self.path, None, f"[device] {self.library_name}::{self.name}"


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
        result, _raw_output = self._require_batch_result(device_entry)
        self.reported_test_total_duration = _sum_reported_test_durations(result.tests)


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
        self.function_name = function_name

    def runtest(self) -> None:
        """Look up this test's result from the batched device run."""
        device_entry = self._resolve_device_entry()
        result, raw_output = self._require_batch_result(device_entry)

        # Find this specific test in the results.
        matches = [
            test_result
            for test_result in result.tests
            if test_result.name == self.function_name
        ]
        if len(matches) > 1:
            # Two result lines carry this name: the output is ambiguous,
            # so first-match promotion could report an earlier PASS while
            # a later line is the real FAIL.  Refuse to guess.
            pytest.fail(
                f"Device output has {len(matches)} result lines for "
                f"{self.function_name!r}; the result is ambiguous and an "
                f"earlier PASS must not shadow a later FAIL:\n{raw_output}"
            )
        if matches:
            test_result = matches[0]
            self.reported_duration = test_result.duration
            if test_result.status == "FAIL":
                pytest.fail(
                    f"Device test FAIL: {self.function_name}\n{raw_output}"
                )
            if test_result.status == "SKIP":
                pytest.skip(test_result.message or "Skipped on device")
            return

        # Test name not found in output. May have been filtered or
        # errored before reaching the harness.
        pytest.fail(
            f"Test {self.function_name!r} not found in device output:\n{raw_output}"
        )


def _load_fallback_device(session: pytest.Session) -> DeviceEntry:
    """Fallback device loading for items created without a target.

    Called when ``devices.yml`` was unavailable at collection time
    but may exist at run time.  Distinct from the silent
    ``DeviceConfigError`` handling in
    :func:`chumicro_pytest_device.plugin.pytest_sessionstart`, which
    sets ``_device_targets = None`` so collection finishes (IDE
    play-button flows on ``__chumicro_runtimes__=("cpython",)``-
    filtered files depend on that). This fallback surfaces the same
    error loudly at runtest with setup instructions.

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
            "to register a board.  That probes hardware identity and "
            "fills in defaults on first registration."
        )

    return targets[0]


class _NoImportModule(pytest.Module):
    """Stub Module that yields nothing without importing the file.

    Returned by :func:`pytest_pycollect_makemodule` for files under
    ``libraries/<name>/functional_tests/`` so the host never tries to
    import device-only modules at collection time.  The
    :class:`DeviceTestFile` collector returned by
    :func:`pytest_collect_file` handles those files via AST, no import.
    """

    def collect(self) -> Iterator[pytest.Item]:
        """Yield nothing.  The device-side collector owns these items."""
        return iter([])


def pytest_ignore_collect(
    collection_path: Path, config: pytest.Config,
) -> bool | None:
    """Ignore untargeted project functional tests entirely.

    A ``projects/<name>/functional_tests/test_*.py`` file runs on a board
    only when its ``functional_tests`` tree is explicitly named on the
    command line.  On a bare workspace sweep it is ignored here, neither
    host-imported as plain pytest nor routed to the device backend, so a
    board-facing project acceptance test never runs its assertions
    against the host's stand-in backend.

    Returns ``True`` (ignore) for a project functional test that is not a
    library functional test and whose tree wasn't targeted.  Library
    functional tests and targeted project files return ``None`` so their
    normal routing runs.  The ``not _is_library_functional_test`` guard
    is belt-and-suspenders: a checkout under a directory named
    ``projects`` that also holds ``libraries/`` already classifies as a
    library test, never a project one.
    """
    if (
        _is_project_functional_test(collection_path)
        and not _is_library_functional_test(collection_path)
        and not _project_functional_test_targeted(config, collection_path)
    ):
        return True
    return None


def pytest_pycollect_makemodule(
    module_path: Path, parent: pytest.Collector,
) -> pytest.Module | None:
    """Suppress default Module collection for plugin-owned paths.

    Always claims ``libraries/<name>/functional_tests/`` and targeted
    ``projects/<name>/functional_tests/`` files. The default Module
    factory would import them on the host, which fails for runtime-
    restricted files that ``import microcontroller`` / ``import wifi`` at
    top level.  Untargeted project functional tests never reach this
    hook: :func:`pytest_ignore_collect` drops them before collection.

    Under ``--target unix-port`` *or* ``--target device-unit`` we also
    claim ``libraries/<name>/tests/`` files so the harness backend
    (unix-port subprocess, or the device transport for the on-device
    unit sweep) gets them. Without this, pytest's default Module
    factory runs them as plain CPython tests, the lane bare ``pytest``
    already covers.  Plain ``--target device`` leaves them there.

    AST-based discovery in :class:`DeviceTestFile` means the file is
    never executed on the host.

    A ``__chumicro_host_only__`` file under ``--target device-unit``
    is still claimed here (returns the empty :class:`_NoImportModule`,
    so it yields nothing and is never imported on the host). The
    device-unit exclusion is enforced by :func:`pytest_collect_file`
    returning ``None`` for it. The net effect is zero items for that
    file on the sweep.

    A ``__chumicro_host_only__`` file under
    ``libraries/<name>/functional_tests/`` is the Category 1 host
    driver shape: it carries a regular pytest test that drives a
    paired board file via the ``device_bootstrap_runner`` fixture.
    Returning ``None`` here lets pytest's default Module factory
    import it as ordinary host-side pytest.
    """
    if (
        _is_library_functional_test(module_path)
        or _is_project_functional_test(module_path)
    ) and not is_host_only_test(module_path):
        return _NoImportModule.from_parent(  # pyright: ignore[reportUnknownMemberType]
            parent, path=module_path,
        )
    if (
        _is_library_unit_test(module_path)
        and _collect_unit_tests_on_device_backend(parent.config)
    ):
        return _NoImportModule.from_parent(  # pyright: ignore[reportUnknownMemberType]
            parent, path=module_path,
        )
    return None


def pytest_collect_file(
    parent: pytest.Collector, file_path: Path,
) -> DeviceTestFile | None:
    """Collect harness-shaped test files as runtime test items.

    Three activation paths:

    - ``libraries/<name>/functional_tests/test_*.py``: always claimed,
      runs through the device-transport backend.
    - ``projects/<name>/functional_tests/test_*.py``: claimed only when
      the tree was explicitly targeted (:func:`pytest_ignore_collect`
      drops it on a bare sweep before this hook runs, so reaching here
      means the invocation named it).  Runs through the same device-
      transport backend.
    - ``libraries/<name>/tests/test_*.py``: claimed under
      ``--target unix-port`` (unix-port subprocess backend) and
      ``--target device-unit`` (device transport backend, the
      on-device unit sweep).  Under the default ``--target device``
      these files stay in the plain-pytest CPython lane.  A file
      marked ``__chumicro_host_only__ = True`` is excluded from the
      device-unit sweep here (it drives runtime-specific source
      through host fakes and would ``ImportError`` on a board). It
      still runs on the unix-ports and CPython.  A file marked
      ``__chumicro_runtimes__ = ("cpython",)`` is collected but
      yields nothing on the device/unix-port lanes via
      :func:`_filter_targets_by_marker`.

    Workbench packages also keep hardware-gated tests under a
    ``functional_tests/`` directory, but those are plain host-side
    pytest that call ``chumicro_deploy`` against a real board. They
    must not be routed through the library test harness and are left
    to run as ordinary pytest collection.

    A library functional test file marked
    ``__chumicro_host_only__ = True`` is the Category 1 host-driver
    shape: it carries a regular pytest test that drives a paired
    board file via the ``device_bootstrap_runner`` fixture.
    Returning ``None`` for it leaves the file to ordinary pytest
    collection (the host test runs on CPython, just like a unit
    test).
    """

    if _is_library_functional_test(file_path):
        if is_host_only_test(file_path):
            return None
        return DeviceTestFile.from_parent(parent, path=file_path)  # pyright: ignore[reportUnknownMemberType]
    if _is_project_functional_test(file_path):
        if is_host_only_test(file_path):
            return None
        return DeviceTestFile.from_parent(parent, path=file_path)  # pyright: ignore[reportUnknownMemberType]
    if (
        _is_library_unit_test(file_path)
        and _collect_unit_tests_on_device_backend(parent.config)
        and not (
            _target_is_device_unit(parent.config)
            and is_host_only_test(file_path)
        )
    ):
        return DeviceTestFile.from_parent(parent, path=file_path)  # pyright: ignore[reportUnknownMemberType]
    return None


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item],
) -> None:
    """Three passes:

    1. Belt-and-suspenders: deselect any non-device items under
       library or project functional tests UNLESS the file is marked
       ``__chumicro_host_only__ = True`` (the Category 1 host-driver
       shape).  The :func:`pytest_pycollect_makemodule` hook already
       prevents the default Module factory from importing
       device-target files under ``libraries/<name>/functional_tests/``
       and targeted ``projects/<name>/functional_tests/``, so duplicate
       items for those should never be produced in practice.  A host-only
       file is a regular pytest test that
       drives a paired board file via fixtures, so its
       :class:`pytest.Function` items are exactly the right shape and
       must survive this sweep.
    2. Deselect every :class:`DeviceRuntimeItem` whose test file
       declares :data:`__chumicro_features__` requirements that the
       target device doesn't satisfy.  Lazy-probes each device only
       when at least one feature-marked item targets it.  A successful
       probe that lacks the feature *deselects* the item (the test
       genuinely shouldn't run there, not that it's pending).  A probe
       that *errors* (offline board, transport glitch) instead *skips*
       the item with a reason naming the error, so a flaky probe surfaces
       in the tally rather than quietly shrinking the run.
    3. Apply a skip marker to each :class:`DeviceRuntimeItem` whose
       library's conftest declared required runtime-config keys via
       :func:`set_runtime_config(..., required_keys=...)` with one or
       more absent from that library's staged payload.  Keyed per
       library scope so two libraries' conftests don't cross-skip:
       library A's missing key can't skip library B's tests.  Catches
       "I forgot to populate ``mqtt.broker.host`` in ``secrets.toml``"
       before the device boots and crashes with a cryptic
       ``MissingConfigKey``.
    """
    deselected: list[pytest.Item] = []
    selected: list[pytest.Item] = []
    for item in items:
        item_path = Path(str(item.fspath))
        if (
            (
                _is_library_functional_test(item_path)
                or _is_project_functional_test(item_path)
            )
            and not isinstance(item, DeviceRuntimeItem)
            and not is_host_only_test(item_path)
        ):
            deselected.append(item)
        else:
            selected.append(item)
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = selected

    if _target_is_unix_port(config):
        platform_deselected = _deselect_items_for_non_targeting_libraries(items)
        if platform_deselected:
            config.hook.pytest_deselected(items=platform_deselected)
            platform_dropped = set(map(id, platform_deselected))
            items[:] = [
                item for item in items if id(item) not in platform_dropped
            ]
    else:
        feature_deselected = _deselect_items_missing_required_features(items)
        if feature_deselected:
            config.hook.pytest_deselected(items=feature_deselected)
            feature_dropped = set(map(id, feature_deselected))
            items[:] = [
                item for item in items if id(item) not in feature_dropped
            ]

    for item in items:
        if not isinstance(item, DeviceRuntimeItem):
            continue
        missing = missing_required_keys(config, scope=item.library_name)
        if not missing:
            continue
        skip_reason = (
            "Functional tests require runtime-config keys not present "
            f"in the staged payload: {', '.join(missing)}.  Populate "
            "them in your secrets.toml (or the per-project config) and "
            "re-run."
        )
        item.add_marker(pytest.mark.skip(reason=skip_reason))


def _read_library_platforms(library_dir: Path) -> tuple[str, ...] | None:
    """Return ``[tool.chumicro].platforms`` for a library, or ``None``.

    ``None`` means "no explicit declaration, library targets every
    runtime" (the same default the workspace-wide
    :mod:`scripts.repo_layout` enforces).  An explicit empty tuple
    means "no runtimes", never seen in practice but valid input.
    """
    pyproject = library_dir / "pyproject.toml"
    if not pyproject.exists():
        return None
    import tomllib  # noqa: PLC0415

    with pyproject.open("rb") as toml_file:
        data = tomllib.load(toml_file)
    platforms = data.get("tool", {}).get("chumicro", {}).get("platforms")
    if platforms is None:
        return None
    return tuple(platforms)


def _deselect_items_for_non_targeting_libraries(
    items: list[pytest.Item],
) -> list[pytest.Item]:
    """Drop items whose library doesn't target the item's runtime.

    For each :class:`DeviceRuntimeItem`, read its library's
    ``[tool.chumicro].platforms``. If present and the target
    runtime isn't in the list, the item is deselected.  Libraries
    without an explicit ``platforms`` key target all three runtimes
    and are always kept.
    """
    deselected: list[pytest.Item] = []
    platforms_cache: dict[Path, tuple[str, ...] | None] = {}
    for item in items:
        if not isinstance(item, DeviceRuntimeItem):
            continue
        device = item.target_device
        if device is None:
            continue
        library_dir = item.library_dir
        if library_dir not in platforms_cache:
            platforms_cache[library_dir] = _read_library_platforms(library_dir)
        platforms = platforms_cache[library_dir]
        if platforms is None:
            continue
        if device.runtime not in platforms:
            deselected.append(item)
    return deselected


def _deselect_items_missing_required_features(
    items: list[pytest.Item],
) -> list[pytest.Item]:
    """Return items to deselect because their device lacks a declared feature.

    Reads :data:`__chumicro_features__` from each ``DeviceRuntimeItem``'s
    test file via AST.  When at least one item declares features, lazy-
    probes each unique target device once via the existing transport
    cache, parses :data:`FEATURE_PROBE_SCRIPT` output, and caches the
    result on the session's ``_device_features_cache``.

    Two outcomes for a feature-gated item.  A device that probed
    successfully but lacks the required feature contributes its item to
    the returned deselect list.  A device whose probe *raised* (offline,
    transport error) is a different case: a warning is emitted and the
    item is marked skip in place (reason names the error) rather than
    deselected, so the flaky probe stays visible instead of silently
    dropping the item.  Applying the skip marker is a side effect; only
    deselect candidates are returned.

    Args:
        items: The current item list.  Items reach back to their
            session via ``item.session``, which we use to share the
            transport cache and stash the feature cache.
    """
    feature_targets: list[tuple[pytest.Item, DeviceEntry, frozenset[str]]] = []
    session: pytest.Session | None = None
    for item in items:
        if not isinstance(item, DeviceRuntimeItem):
            continue
        # ``target_device`` is ``None`` until a device resolves for the
        # item; a feature marker can't be evaluated without a target to
        # probe, so skip those.
        device = item.target_device
        if device is None:
            continue
        test_file = item.test_file
        marker = read_features_marker(test_file)
        if not marker:
            continue
        feature_targets.append((item, device, marker))
        if session is None:
            session = getattr(item, "session", None)

    if not feature_targets or session is None:
        return []

    cache: dict[str, frozenset[str]] = cast(
        "dict[str, frozenset[str]]",
        getattr(session, "_device_features_cache", None) or {},
    )
    session._device_features_cache = cache  # type: ignore[attr-defined]

    # Devices whose probe raised, mapped to the error text.  A probe
    # failure ("device unreachable") is a different condition from a
    # successful probe that lacks the feature ("feature absent"), so the
    # two get different treatments below.
    probe_errors: dict[str, str] = cast(
        "dict[str, str]",
        getattr(session, "_device_feature_probe_errors", None) or {},
    )
    session._device_feature_probe_errors = probe_errors  # type: ignore[attr-defined]

    devices_to_probe: dict[str, DeviceEntry] = {
        device.identifier: device
        for _, device, _ in feature_targets
        if device.identifier not in cache
    }
    if devices_to_probe:
        transport_cache = _session_cache(session)
        for device_id, device_entry in devices_to_probe.items():
            try:
                transport = transport_cache.get_transport(
                    device_entry,
                    _session_effective_deploy_mode(session, device_entry),
                )
                output = transport.run_script(FEATURE_PROBE_SCRIPT)
            except Exception as error:  # noqa: BLE001, graceful per-device fallback
                warnings.warn(
                    f"Feature probe failed for device {device_id!r}: "
                    f"{error}.  Tests declaring "
                    f"`__chumicro_features__` will be skipped for "
                    f"this device.",
                    stacklevel=3,
                )
                cache[device_id] = frozenset()
                probe_errors[device_id] = str(error)
            else:
                cache[device_id] = parse_feature_probe_output(output)

    # A probe *error* skips the device's feature-gated items (visible in
    # the pass/skip tally, reason names the error) rather than deselecting
    # them, so a flaky probe doesn't quietly shrink the run to a green
    # subset.  Silent deselection is reserved for a *successful* probe
    # that genuinely lacks the required feature.
    deselected: list[pytest.Item] = []
    for item, device, required in feature_targets:
        device_id = device.identifier
        probe_error = probe_errors.get(device_id)
        if probe_error is not None:
            item.add_marker(pytest.mark.skip(
                reason=(
                    f"Feature probe failed for device {device_id!r}: "
                    f"{probe_error}"
                ),
            ))
            continue
        if not required.issubset(cache[device_id]):
            deselected.append(item)
    return deselected

def _sibling_extra_modules(test_files: list[Path]) -> list[Path]:
    """Return underscore-prefixed sibling ``.py`` modules of *test_files*.

    Convention: a test file may import a shared helper module that sits
    next to it in the same ``tests/`` directory, named with a leading
    underscore (``_swap_helpers.py``).  ``test_*.py`` files and
    ``conftest.py`` don't start with an underscore, so the ``_*.py``
    glob excludes them by construction: it picks up only the shared
    helpers, which neither the normal source closure nor the test-file
    list otherwise stages.  The caller passes the result to
    ``transport.stage(extra_modules=...)``, which lands each helper on
    the device next to the test files, where the test source's
    ``from _swap_helpers import ...`` resolves.

    The result is deduplicated by filename and sorted for deterministic
    staging across the directories holding *test_files*.
    """
    found: dict[str, Path] = {}
    seen_dirs: set[Path] = set()
    for test_file in test_files:
        parent = test_file.parent
        if parent in seen_dirs:
            continue
        seen_dirs.add(parent)
        for candidate in sorted(parent.glob("_*.py")):
            found[candidate.name] = candidate
    return [found[name] for name in sorted(found)]


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
    invocations from N-per-file to 1-per-library, and per-library
    scope keeps the drive working-set bounded, since a 491 KB Pi
    Pico W CIRCUITPY drive can't hold every library's source + every
    library's test files at once.  Switching libraries triggers a
    fresh stage. Rsync ``--delete`` cleans the prior library off.

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
            filesystem-mode staging. ``None`` collects every library
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
        # Match on ``library_name`` (not ``library_dir.name``): the two
        # are identical for library items, but a nested project's name
        # is slash-form (``garage/heater``) while its dir name is just
        # the leaf, and the caller passes ``item.library_name``.
        if library_filter is not None and item.library_name != library_filter:
            continue

        # Collect source dirs for this item's tested unit
        # (project-aware; see _item_source_dirs).
        for source_dir in _item_source_dirs(session, item):
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
        extra_modules=_sibling_extra_modules(seen_test_files),
        extra_files=_encode_runtime_config_extra_files(
            session.config, scope=library_filter,
        ),
        # Fakes stage for every device session, not just the unit
        # sweep: functional tests import them too (e.g. timing's
        # sleep_ms), and gating on device-unit silently dropped
        # testing.py from functional deploys for over a month.
        include_test_support=True,
    )
