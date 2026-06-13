"""Coverage-closing tests for chumicro_pytest_device.collection internals.

Exercises the collection-layer helpers the IDE-path tests in
``test_plugin.py`` leave uncovered: the ``_device_items`` /
``_device_closure_source_dirs`` walks, the ``DeviceRuntimeItem`` failure
guards (``_require_batch_result``, ``repr_failure``) and the SKIP branch
of ``DeviceTestItem.runtest``, the ``_load_fallback_device`` malformed
path, the collect-hook routing (``pytest_pycollect_makemodule`` /
``pytest_collect_file`` via a monkeypatched ``from_parent``), the
unix-port platform deselect, the sibling-helper glob, and the real
``_bulk_stage_for_device`` staging body that ``test_plugin.py`` stubs out.

All paths run on CPython with FakeSession / FakeTransport / the
``make_*_item`` builders; none reach real hardware.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from chumicro_deploy import DeviceEntry
from chumicro_deploy.testing import FakeTransport
from chumicro_pytest_device import collection
from chumicro_pytest_device import plugin as pytest_device
from chumicro_pytest_device.result_parser import RunResult, SummaryResult
from chumicro_pytest_device.result_parser import TestResult as ParsedTestResult
from chumicro_pytest_device.testing import (
    FakeSession,
    hot_path_device,
    make_prepare_item,
    make_run_file_item,
    make_test_item,
)


def _functional_file(tmp_path: Path, library: str = "alpha", name: str = "test_x.py") -> Path:
    """Create an <library>/functional_tests/<name> layout under tmp_path.

    No ``libraries/`` ancestor — used where only ``library_dir`` /
    ``target_device`` matter, not the path-shape predicates.
    """
    test_file = tmp_path / library / "functional_tests" / name
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text("def test_one(): pass\n")
    return test_file


def _library_functional_file(tmp_path: Path, library: str = "alpha") -> Path:
    """Create a libraries/<library>/functional_tests/test_x.py the path predicates accept."""
    test_file = tmp_path / "libraries" / library / "functional_tests" / "test_x.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text("def test_one(): pass\n")
    return test_file


def _library_unit_file(tmp_path: Path, library: str = "alpha") -> Path:
    """Create a libraries/<library>/tests/test_x.py the unit-path predicate accepts."""
    test_file = tmp_path / "libraries" / library / "tests" / "test_x.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text("def test_one(): pass\n")
    return test_file


class TestDeviceItemsFilter:
    """Tests for _device_items target-matching filters."""

    def test_yields_only_items_matching_the_device(self, tmp_path: Path) -> None:
        """Non-DeviceTestItems, None-device items, and other-device items are all skipped."""
        session = FakeSession(pytest_device._TransportCache(), rootpath=tmp_path)
        device = hot_path_device("micropython")
        other_device = hot_path_device("circuitpython")
        test_file = _functional_file(tmp_path)

        matching = make_test_item(session, device, test_file, "test_one")
        none_device = make_test_item(session, device, test_file, "test_two")
        none_device.target_device = None
        wrong_device = make_test_item(session, other_device, test_file, "test_three")
        not_a_device_item = Mock(spec=pytest.Item)

        session.items = [not_a_device_item, none_device, wrong_device, matching]

        yielded = list(collection._device_items(session, device))
        assert yielded == [matching]


class TestDeviceClosureSourceDirsLoop:
    """Tests for the _device_closure_source_dirs accumulation loop."""

    def test_dedupes_overlapping_source_dirs_across_items(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        """Two items resolving to the same source dir contribute it once."""
        session = FakeSession(pytest_device._TransportCache(), rootpath=tmp_path)
        device = hot_path_device()
        first = _functional_file(tmp_path, name="test_a.py")
        second = _functional_file(tmp_path, name="test_b.py")
        shared_source_dir = tmp_path / "alpha" / "src"

        monkeypatch.setattr(
            collection,
            "resolve_library_source_dirs",
            lambda library_dir, *, libraries_root=None, test_files=None: [
                shared_source_dir,
            ],
        )
        session.items = [
            make_test_item(session, device, first, "test_one"),
            make_test_item(session, device, second, "test_one"),
        ]

        closure = collection._device_closure_source_dirs(session, device)
        assert closure == [shared_source_dir]


class TestResolveDeviceEntryFallback:
    """Tests for DeviceRuntimeItem._resolve_device_entry's None-target path."""

    def test_loads_fallback_device_when_target_is_none(self, tmp_path: Path) -> None:
        """A None target_device resolves through the registry and memoizes the result."""
        (tmp_path / "devices.yml").write_text(
            "defaults:\n"
            "  micropython: mp-board\n"
            "  ide_runtime: micropython\n"
            "devices:\n"
            "  - id: mp-board\n"
            "    runtime: micropython\n"
            "    address: /dev/ttyUSB-mp\n",
        )
        session = FakeSession(pytest_device._TransportCache(), rootpath=tmp_path)
        test_file = _functional_file(tmp_path)
        item = make_prepare_item(session, hot_path_device(), test_file)
        item.target_device = None

        resolved = item._resolve_device_entry()
        assert resolved.identifier == "mp-board"
        assert item.target_device is resolved


class TestRequireBatchResultGuards:
    """Tests for _require_batch_result's None and zero-tests guards."""

    def test_zero_tests_result_fails_loudly(self, tmp_path: Path) -> None:
        """A batch that parsed no test results fails with the raw device output."""
        cache = pytest_device._TransportCache()
        session = FakeSession(cache, rootpath=tmp_path)
        device = hot_path_device()
        test_file = _functional_file(tmp_path)
        item = make_run_file_item(session, device, test_file)
        empty_result = RunResult(tests=[])
        cache.cache_batch_result(
            (device.identifier, "alpha", test_file.name),
            empty_result,
            "raw harness chatter",
        )

        with pytest.raises(pytest.fail.Exception, match="No test results in device output"):
            item._require_batch_result(device)


class TestReprFailure:
    """Tests for DeviceRuntimeItem.repr_failure."""

    def test_returns_string_of_exception_value(self, tmp_path: Path) -> None:
        """repr_failure renders the exception's str(), not pytest's default traceback."""
        session = FakeSession(pytest_device._TransportCache(), rootpath=tmp_path)
        item = make_prepare_item(session, hot_path_device(), _functional_file(tmp_path))
        try:
            raise RuntimeError("device went away")
        except RuntimeError:
            excinfo = pytest.ExceptionInfo.from_current()

        assert item.repr_failure(excinfo) == "device went away"


class TestDeviceTestItemRuntestSkip:
    """Tests for the SKIP branch of DeviceTestItem.runtest."""

    def test_skip_result_raises_pytest_skip_with_device_message(
        self, tmp_path: Path,
    ) -> None:
        """A SKIP test result raises pytest.skip carrying the device-reported reason."""
        cache = pytest_device._TransportCache()
        session = FakeSession(cache, rootpath=tmp_path)
        device = hot_path_device()
        test_file = _functional_file(tmp_path)
        skip_result = RunResult(
            tests=[
                ParsedTestResult(
                    name="test_one",
                    status="SKIP",
                    duration=0.0,
                    message="no wifi on this board",
                ),
            ],
            summary=SummaryResult(total=1, failed=0, duration=0.0),
        )
        cache.cache_batch_result(
            (device.identifier, "alpha", test_file.name), skip_result, "raw",
        )
        item = make_test_item(session, device, test_file, "test_one")

        with pytest.raises(pytest.skip.Exception, match="no wifi on this board"):
            item.runtest()


class TestAssertSummaryReconciles:
    """The device SUMMARY must be present and its failed-count must match."""

    def test_missing_summary_fails(self) -> None:
        result = RunResult(
            tests=[ParsedTestResult(name="t", status="PASS", duration=0.0)],
        )
        with pytest.raises(pytest.fail.Exception, match="no SUMMARY"):
            collection._assert_summary_reconciles(result, "raw")

    def test_dropped_fail_line_fails(self) -> None:
        # SUMMARY claims a failure but no FAIL line parsed: a failure
        # silently vanished from the transcript.
        result = RunResult(
            tests=[ParsedTestResult(name="t", status="PASS", duration=0.0)],
            summary=SummaryResult(total=1, failed=1, duration=0.0),
        )
        with pytest.raises(pytest.fail.Exception, match="failure result was dropped"):
            collection._assert_summary_reconciles(result, "raw")

    def test_consistent_summary_passes(self) -> None:
        result = RunResult(
            tests=[
                ParsedTestResult(name="a", status="PASS", duration=0.0),
                ParsedTestResult(name="b", status="FAIL", duration=0.0),
            ],
            summary=SummaryResult(total=2, failed=1, duration=0.0),
        )
        collection._assert_summary_reconciles(result, "raw")

    def test_total_higher_than_parsed_does_not_fail(self) -> None:
        # A vanished PASS/SKIP (SUMMARY total exceeds parsed lines) is
        # handled per-test as "not found", so reconciliation must not fail.
        result = RunResult(
            tests=[ParsedTestResult(name="a", status="PASS", duration=0.0)],
            summary=SummaryResult(total=3, failed=0, duration=0.0),
        )
        collection._assert_summary_reconciles(result, "raw")


class TestLoadFallbackDeviceMalformed:
    """Tests for _load_fallback_device's malformed-config failure branch."""

    def test_malformed_devices_yml_fails_not_skips(self, tmp_path: Path) -> None:
        """A devices.yml that won't parse fails loudly rather than skipping."""
        (tmp_path / "devices.yml").write_text("devices: [broken: flow sequence\n")
        session = FakeSession(pytest_device._TransportCache(), rootpath=tmp_path)

        with pytest.raises(pytest.fail.Exception, match="Device config error"):
            collection._load_fallback_device(session)


class TestNoImportModuleCollect:
    """Tests for the _NoImportModule stub collector."""

    def test_collect_yields_nothing(self) -> None:
        """_NoImportModule.collect returns an empty iterator without importing the file."""
        stub = collection._NoImportModule.__new__(collection._NoImportModule)
        assert list(stub.collect()) == []


class TestPytestPycollectMakemodule:
    """Tests for pytest_pycollect_makemodule routing."""

    def test_functional_test_returns_no_import_module(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        """A non-host-only functional test file is claimed by the no-import stub."""
        sentinel = object()
        monkeypatch.setattr(
            collection._NoImportModule,
            "from_parent",
            classmethod(lambda cls, parent, **kwargs: sentinel),
        )
        parent = SimpleNamespace(config=SimpleNamespace(getoption=lambda *_args, **_kwargs: "device"))
        test_file = _library_functional_file(tmp_path)
        assert collection.pytest_pycollect_makemodule(test_file, parent) is sentinel

    def test_unit_test_under_unix_port_returns_no_import_module(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        """A unit-test file under --target unix-port is claimed by the no-import stub."""
        sentinel = object()
        monkeypatch.setattr(
            collection._NoImportModule,
            "from_parent",
            classmethod(lambda cls, parent, **kwargs: sentinel),
        )
        parent = SimpleNamespace(
            config=SimpleNamespace(getoption=lambda name, default=None: "unix-port"),
        )
        unit_file = _library_unit_file(tmp_path)
        assert collection.pytest_pycollect_makemodule(unit_file, parent) is sentinel

    def test_plain_python_file_returns_none(self, tmp_path: Path) -> None:
        """A path outside the plugin's claimed trees yields None (default collection)."""
        parent = SimpleNamespace(
            config=SimpleNamespace(getoption=lambda *_args, **_kwargs: "device"),
        )
        plain = tmp_path / "test_plain.py"
        plain.write_text("def test_one(): pass\n")
        assert collection.pytest_pycollect_makemodule(plain, parent) is None


class TestPytestCollectFileRouting:
    """Tests for pytest_collect_file's from_parent activation branches."""

    def test_functional_test_collected_as_device_file(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        """A non-host-only functional test file routes to DeviceTestFile.from_parent."""
        sentinel = object()
        monkeypatch.setattr(
            collection.DeviceTestFile,
            "from_parent",
            classmethod(lambda cls, parent, **kwargs: sentinel),
        )
        parent = SimpleNamespace(config=SimpleNamespace(getoption=lambda *_args, **_kwargs: "device"))
        test_file = _library_functional_file(tmp_path)
        assert collection.pytest_collect_file(parent, test_file) is sentinel

    def test_unit_test_under_unix_port_collected_as_device_file(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        """A unit-test file under --target unix-port routes to DeviceTestFile.from_parent."""
        sentinel = object()
        monkeypatch.setattr(
            collection.DeviceTestFile,
            "from_parent",
            classmethod(lambda cls, parent, **kwargs: sentinel),
        )
        parent = SimpleNamespace(
            config=SimpleNamespace(getoption=lambda name, default=None: "unix-port"),
        )
        unit_file = _library_unit_file(tmp_path)
        assert collection.pytest_collect_file(parent, unit_file) is sentinel


class TestDeselectItemsForNonTargetingLibraries:
    """Tests for the unix-port [tool.chumicro].platforms deselect pass."""

    def _platform_item(
        self, library_dir: Path, runtime: str,
    ) -> object:
        item = Mock(spec=collection.DeviceRuntimeItem)
        item.target_device = DeviceEntry(
            identifier=f"{runtime}-1", runtime=runtime, address="/dev/x",
        )
        item.library_dir = library_dir
        return item

    def test_item_deselected_when_runtime_not_in_platforms(
        self, tmp_path: Path,
    ) -> None:
        """A library declaring only micropython deselects a circuitpython item."""
        library_dir = tmp_path / "alpha"
        library_dir.mkdir()
        (library_dir / "pyproject.toml").write_text(
            "[tool.chumicro]\nplatforms = [\"micropython\"]\n",
        )
        kept = self._platform_item(library_dir, "micropython")
        dropped = self._platform_item(library_dir, "circuitpython")

        deselected = collection._deselect_items_for_non_targeting_libraries(
            [kept, dropped],
        )
        assert deselected == [dropped]

    def test_library_without_platforms_keeps_every_item(
        self, tmp_path: Path,
    ) -> None:
        """A library with no platforms key targets all runtimes, so nothing is deselected."""
        library_dir = tmp_path / "beta"
        library_dir.mkdir()
        (library_dir / "pyproject.toml").write_text("[project]\nname = \"x\"\n")
        item = self._platform_item(library_dir, "circuitpython")

        assert collection._deselect_items_for_non_targeting_libraries([item]) == []

    def test_non_device_and_none_target_items_are_skipped(
        self, tmp_path: Path,
    ) -> None:
        """Plain items and None-device items never reach the platforms lookup."""
        plain = Mock(spec=pytest.Item)
        none_target = Mock(spec=collection.DeviceRuntimeItem)
        none_target.target_device = None

        assert collection._deselect_items_for_non_targeting_libraries(
            [plain, none_target],
        ) == []


class TestModifyItemsUnixPortPlatformDeselect:
    """Tests for the unix-port platform-deselect pass inside the modifyitems hook."""

    def test_platform_mismatch_item_is_deselected_under_unix_port(
        self, tmp_path: Path,
    ) -> None:
        """Under --target unix-port, an item whose library excludes its runtime is dropped."""
        from chumicro_pytest_device.runtime_config import set_runtime_config

        library_dir = tmp_path / "alpha"
        library_dir.mkdir()
        (library_dir / "pyproject.toml").write_text(
            "[tool.chumicro]\nplatforms = [\"micropython\"]\n",
        )

        class _Config:
            def __init__(self) -> None:
                self.stash: dict = {}
                self.deselected: list[object] = []
                self.hook = SimpleNamespace(
                    pytest_deselected=lambda items: self.deselected.extend(items),
                )

            def getoption(self, name, default=None):
                return "unix-port" if name == "--target" else default

        config = _Config()
        set_runtime_config(config, payload=None, required_keys=())

        item = Mock(spec=collection.DeviceRuntimeItem)
        item.nodeid = "alpha/tests/test_x.py::test_one"
        item.fspath = str(tmp_path / "alpha" / "tests" / "test_x.py")
        item.target_device = DeviceEntry(
            identifier="cp-1", runtime="circuitpython", address="/dev/x",
        )
        item.library_dir = library_dir

        items = [item]
        collection.pytest_collection_modifyitems(config, items)

        assert items == []
        assert config.deselected == [item]


class TestSiblingExtraModules:
    """Tests for the underscore-prefixed sibling-helper glob."""

    def test_collects_helper_and_dedupes_by_directory(self, tmp_path: Path) -> None:
        """Two test files in one dir scan it once and surface its _helper.py."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "_swap_helpers.py").write_text("X = 1\n")
        first = tests_dir / "test_a.py"
        second = tests_dir / "test_b.py"
        first.write_text("def test_one(): pass\n")
        second.write_text("def test_two(): pass\n")

        result = collection._sibling_extra_modules([first, second])
        assert result == [tests_dir / "_swap_helpers.py"]

    def test_no_helpers_yields_empty(self, tmp_path: Path) -> None:
        """A directory with no underscore-prefixed modules yields an empty list."""
        test_file = tmp_path / "test_x.py"
        test_file.write_text("def test_one(): pass\n")
        assert collection._sibling_extra_modules([test_file]) == []


class TestBulkStageForDevice:
    """Tests for the real _bulk_stage_for_device staging body."""

    def test_stages_matching_library_items_once(
        self, tmp_path: Path, monkeypatch,
    ) -> None:
        """Items matching the device + library filter are deduped and staged in one call."""
        cache = pytest_device._TransportCache()
        session = FakeSession(cache, rootpath=tmp_path)
        device = hot_path_device("micropython")
        other_device = hot_path_device("circuitpython")
        alpha_a = _functional_file(tmp_path, "alpha", "test_a.py")
        alpha_b = _functional_file(tmp_path, "alpha", "test_b.py")
        beta = _functional_file(tmp_path, "beta", "test_c.py")
        alpha_source_dir = tmp_path / "alpha" / "src"

        monkeypatch.setattr(
            collection,
            "resolve_library_source_dirs",
            lambda library_dir, *, libraries_root=None, test_files=None: [
                library_dir / "src",
            ],
        )

        not_a_device_item = Mock(spec=pytest.Item)
        none_device = make_test_item(session, device, alpha_a, "test_x")
        none_device.target_device = None
        session.items = [
            not_a_device_item,
            none_device,
            make_test_item(session, device, alpha_a, "test_one"),
            make_test_item(session, device, alpha_b, "test_two"),
            make_test_item(session, other_device, beta, "test_three"),
            make_test_item(session, device, beta, "test_four"),
        ]

        transport = FakeTransport(mode="flash")
        collection._bulk_stage_for_device(
            session, device, transport, library_filter="alpha",
        )

        stage_calls = [call for call in transport.calls if call[0] == "stage"]
        assert len(stage_calls) == 1
        staged_source_dirs = stage_calls[0][1][0]
        staged_test_files = stage_calls[0][1][1]
        assert staged_source_dirs == [alpha_source_dir]
        assert sorted(path.name for path in staged_test_files) == [
            "test_a.py", "test_b.py",
        ]
