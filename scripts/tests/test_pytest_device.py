"""Tests for pytest_device — the pytest plugin for device functional tests.

Tests AST-based test discovery, DeviceTestItem behavior with faked
transports, device config loading, and collection hook behavior.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_device
from device_config import DeviceEntry
from result_parser import TestResult as ParsedTestResult


class TestParseTestFunctions:
    """Tests for _parse_test_functions (AST-based discovery)."""

    def test_finds_test_functions(self, tmp_path: Path) -> None:
        """Should discover all test_* functions at module level."""
        source = textwrap.dedent("""\
            def helper():
                pass

            def test_alpha():
                pass

            def test_beta():
                pass

            def _private():
                pass
        """)
        test_file = tmp_path / "test_example.py"
        test_file.write_text(source)

        names = pytest_device._parse_test_functions(test_file)
        assert names == ["test_alpha", "test_beta"]

    def test_skips_non_test_functions(self, tmp_path: Path) -> None:
        """Should not include functions that don't start with test_."""
        source = textwrap.dedent("""\
            def setup():
                pass

            def _sleep_ms(duration):
                pass
        """)
        test_file = tmp_path / "test_helpers.py"
        test_file.write_text(source)

        names = pytest_device._parse_test_functions(test_file)
        assert names == []

    def test_skips_class_methods(self, tmp_path: Path) -> None:
        """Should not include test_* methods inside classes."""
        source = textwrap.dedent("""\
            class TestSomething:
                def test_inside_class(self):
                    pass

            def test_top_level():
                pass
        """)
        test_file = tmp_path / "test_mixed.py"
        test_file.write_text(source)

        names = pytest_device._parse_test_functions(test_file)
        assert names == ["test_top_level"]

    def test_empty_file(self, tmp_path: Path) -> None:
        """An empty file should return no test functions."""
        test_file = tmp_path / "test_empty.py"
        test_file.write_text("")

        names = pytest_device._parse_test_functions(test_file)
        assert names == []


class TestResolveLibraryDir:
    """Tests for _resolve_library_dir."""

    def test_derives_library_root(self, tmp_path: Path) -> None:
        """Should return the parent of functional_tests/."""
        library_dir = tmp_path / "libraries" / "timing"
        functional_dir = library_dir / "functional_tests"
        functional_dir.mkdir(parents=True)
        test_file = functional_dir / "test_example.py"
        test_file.touch()

        result = pytest_device._resolve_library_dir(test_file)
        assert result == library_dir


class TestIterRuntimeVariants:
    """Tests for _iter_runtime_variants ordering."""

    def test_groups_runtime_variants_per_function(self) -> None:
        """Each function should appear adjacent across runtimes."""
        devices = [
            DeviceEntry(
                identifier="mp-board",
                runtime="micropython",
                address="/dev/ttyUSB0",
            ),
            DeviceEntry(
                identifier="cp-board",
                runtime="circuitpython",
                address="/dev/cu.usbmodem1",
            ),
        ]

        variants = list(pytest_device._iter_runtime_variants(
            ["test_alpha", "test_beta"], devices,
        ))

        assert [
            (function_name, device.runtime)
            for function_name, device in variants
        ] == [
            ("test_alpha", "micropython"),
            ("test_alpha", "circuitpython"),
            ("test_beta", "micropython"),
            ("test_beta", "circuitpython"),
        ]


class TestRuntimeControlNames:
    """Tests for synthetic runtime control item names."""

    def test_runtime_display_name(self) -> None:
        """Runtime labels should be human-friendly in the IDE tree."""
        assert pytest_device._runtime_display_name("micropython") == "MicroPython"
        assert pytest_device._runtime_display_name("circuitpython") == "CircuitPython"

    def test_runtime_prepare_name(self) -> None:
        """Prepare items should include the runtime in a stable label."""
        device = DeviceEntry(
            identifier="cp-board",
            runtime="circuitpython",
            address="/dev/cu.usbmodem1",
        )

        assert pytest_device._runtime_prepare_name(device) == "Setup — CircuitPython"

    def test_runtime_run_file_name(self) -> None:
        """Run-file items should include the runtime in a stable label."""
        device = DeviceEntry(
            identifier="mp-board",
            runtime="micropython",
            address="/dev/ttyUSB0",
        )

        assert pytest_device._runtime_run_file_name(device) == "Run overhead — MicroPython"


class TestReportedDurations:
    """Tests for propagating parsed device timing into pytest reports."""

    def test_sum_reported_test_durations_ignores_missing_values(self) -> None:
        """Only tests with parsed durations should contribute to the total."""
        test_results = [
            ParsedTestResult(name="test_alpha", status="PASS", duration=0.125),
            ParsedTestResult(name="test_beta", status="SKIP", duration=None),
            ParsedTestResult(name="test_gamma", status="FAIL", duration=0.5),
        ]

        total_duration = pytest_device._sum_reported_test_durations(test_results)

        assert total_duration == pytest.approx(0.625)

    def test_apply_reported_duration_uses_per_test_value(self) -> None:
        """Per-test items should show the parsed device runtime in pytest."""
        item = SimpleNamespace(
            _reported_duration=0.321,
            _reported_test_total_duration=None,
        )
        report = SimpleNamespace(when="call", duration=1.5)

        pytest_device._apply_reported_duration(item, report)

        assert report.duration == pytest.approx(0.321)

    def test_apply_reported_duration_keeps_only_batch_overhead(self) -> None:
        """Batch items should retain only residual host-side overhead."""
        item = SimpleNamespace(
            _reported_duration=None,
            _reported_test_total_duration=1.2,
        )
        report = SimpleNamespace(when="call", duration=1.75)

        pytest_device._apply_reported_duration(item, report)

        assert report.duration == pytest.approx(0.55)

    def test_apply_reported_duration_never_goes_negative(self) -> None:
        """Rounded device timings should not produce negative batch durations."""
        item = SimpleNamespace(
            _reported_duration=None,
            _reported_test_total_duration=1.8,
        )
        report = SimpleNamespace(when="call", duration=1.2)

        pytest_device._apply_reported_duration(item, report)

        assert report.duration == 0.0

    def test_apply_reported_duration_ignores_non_call_phase(self) -> None:
        """Setup and teardown timings should keep their original values."""
        item = SimpleNamespace(
            _reported_duration=0.321,
            _reported_test_total_duration=0.654,
        )
        report = SimpleNamespace(when="setup", duration=1.5)

        pytest_device._apply_reported_duration(item, report)

        assert report.duration == pytest.approx(1.5)


class TestTransportCache:
    """Tests for the _TransportCache helper."""

    def test_needs_staging_initially(self) -> None:
        """A fresh cache should report staging needed."""
        cache = pytest_device._TransportCache()
        assert cache.needs_staging(("dev1", "timing", "test_ticks.py")) is True

    def test_mark_staged_clears_need(self) -> None:
        """After marking staged, needs_staging returns False."""
        cache = pytest_device._TransportCache()
        cache.mark_staged(("dev1", "timing", "test_ticks.py"))
        assert cache.needs_staging(("dev1", "timing", "test_ticks.py")) is False

    def test_has_staged_file_false_initially(self) -> None:
        """A fresh cache should report no prior staged files."""
        cache = pytest_device._TransportCache()
        assert cache.has_staged_file("dev1") is False

    def test_has_staged_file_true_after_mark_staged(self) -> None:
        """mark_staged should record that the device has staged a file."""
        cache = pytest_device._TransportCache()
        cache.mark_staged(("dev1", "timing", "test_ticks.py"))
        assert cache.has_staged_file("dev1") is True

    def test_different_library_needs_staging(self) -> None:
        """A different library should still need staging."""
        cache = pytest_device._TransportCache()
        cache.mark_staged(("dev1", "timing", "test_ticks.py"))
        assert cache.needs_staging(("dev1", "runner", "test_ticks.py")) is True

    def test_different_test_file_needs_staging(self) -> None:
        """A different test file in the same library should need staging."""
        cache = pytest_device._TransportCache()
        cache.mark_staged(("dev1", "timing", "test_ticks.py"))
        assert cache.needs_staging(("dev1", "timing", "test_heartbeat.py")) is True

    def test_different_device_needs_staging(self) -> None:
        """A different device should still need staging."""
        cache = pytest_device._TransportCache()
        cache.mark_staged(("dev1", "timing", "test_ticks.py"))
        assert cache.needs_staging(("dev2", "timing", "test_ticks.py")) is True

    def test_disconnect_all_clears_state(self) -> None:
        """disconnect_all should clear all cached state including batch results."""
        cache = pytest_device._TransportCache()
        cache.mark_staged(("dev1", "timing", "test_ticks.py"))
        cache.cache_batch_result(("dev1", "timing", "test_ticks.py"), "result", "output")
        cache.mark_fully_staged("dev1")
        cache.disconnect_all()
        assert cache.needs_staging(("dev1", "timing", "test_ticks.py")) is True
        assert cache.get_batch_result(("dev1", "timing", "test_ticks.py")) is None
        assert cache.is_fully_staged("dev1") is False

    def test_batch_result_not_cached_initially(self) -> None:
        """A fresh cache should have no batch results."""
        cache = pytest_device._TransportCache()
        assert cache.get_batch_result(("dev1", "timing", "test_ticks.py")) is None

    def test_cache_and_retrieve_batch_result(self) -> None:
        """Cached batch results should be retrievable."""
        cache = pytest_device._TransportCache()
        cache.cache_batch_result(("dev1", "timing", "test_ticks.py"), "parsed", "raw output",
        )
        result = cache.get_batch_result(("dev1", "timing", "test_ticks.py"))
        assert result == ("parsed", "raw output")

    def test_batch_result_separate_per_device(self) -> None:
        """Batch results should be keyed per device."""
        cache = pytest_device._TransportCache()
        cache.cache_batch_result(("dev1", "timing", "test_ticks.py"), "result_1", "output_1",
        )
        assert cache.get_batch_result(("dev2", "timing", "test_ticks.py")) is None

    def test_batch_result_separate_per_file(self) -> None:
        """Batch results should be keyed per test file."""
        cache = pytest_device._TransportCache()
        cache.cache_batch_result(("dev1", "timing", "test_ticks.py"), "result_1", "output_1",
        )
        assert cache.get_batch_result(("dev1", "timing", "test_heartbeat.py")) is None

    def test_batch_result_caches_failure(self) -> None:
        """A None parsed result (failure) should be cached and retrievable."""
        cache = pytest_device._TransportCache()
        cache.cache_batch_result(("dev1", "timing", "test_ticks.py"), None, "connection error",
        )
        result = cache.get_batch_result(("dev1", "timing", "test_ticks.py"))
        assert result == (None, "connection error")

    def test_get_transport_creates_and_caches(self) -> None:
        """get_transport should create a transport and reuse it."""
        from chumicro_deploy.testing import FakeTransport

        calls: list[str] = []

        def fake_create(device_entry, deploy_mode=None):
            transport = FakeTransport()
            calls.append("created")
            return transport

        cache = pytest_device._TransportCache()
        device = DeviceEntry(
            identifier="test_dev",
            runtime="micropython",
            address="/dev/ttyUSB0",
        )

        # Monkey-patch create_transport to avoid real hardware.
        original = pytest_device.create_transport
        pytest_device.create_transport = fake_create
        try:
            transport_a = cache.get_transport(device, None)
            transport_b = cache.get_transport(device, None)
            assert transport_a is transport_b
            assert len(calls) == 1
        finally:
            pytest_device.create_transport = original

    def test_fully_staged_not_set_initially(self) -> None:
        """A fresh cache should not report any device as fully staged."""
        cache = pytest_device._TransportCache()
        assert cache.is_fully_staged("dev1") is False

    def test_mark_fully_staged(self) -> None:
        """After marking fully staged, is_fully_staged returns True."""
        cache = pytest_device._TransportCache()
        cache.mark_fully_staged("dev1")
        assert cache.is_fully_staged("dev1") is True

    def test_fully_staged_separate_per_device(self) -> None:
        """Fully-staged state should be per-device."""
        cache = pytest_device._TransportCache()
        cache.mark_fully_staged("dev1")
        assert cache.is_fully_staged("dev2") is False

    def test_invalidate_device_disconnects_and_drops_state(self) -> None:
        """invalidate_device should disconnect the cached transport and drop staging."""
        from chumicro_deploy.testing import FakeTransport

        cache = pytest_device._TransportCache()
        device = DeviceEntry(
            identifier="dev1",
            runtime="micropython",
            address="/dev/ttyUSB0",
        )
        original = pytest_device.create_transport
        pytest_device.create_transport = lambda device_entry, deploy_mode=None: FakeTransport()
        try:
            transport = cache.get_transport(device, None)
            cache.mark_staged(("dev1", "timing", "test_ticks.py"))
            cache.mark_fully_staged("dev1")
            assert cache.is_fully_staged("dev1") is True
            assert "dev1" in cache._transports

            cache.invalidate_device("dev1")

            # Transport gone, staging cleared.
            assert "dev1" not in cache._transports
            assert cache.has_staged_file("dev1") is False
            assert cache.is_fully_staged("dev1") is False
            # Disconnect was called on the transport.
            assert transport.calls[-1] == ("disconnect", ())
        finally:
            pytest_device.create_transport = original

    def test_invalidate_device_keeps_batch_results(self) -> None:
        """Cached batch results survive invalidate_device.

        Subsequent items from the same file should report the original
        failure rather than retry and get partial output.
        """
        cache = pytest_device._TransportCache()
        cache.cache_batch_result(("dev1", "timing", "test_ticks.py"), None, "boom")

        cache.invalidate_device("dev1")

        assert cache.get_batch_result(("dev1", "timing", "test_ticks.py")) == (None, "boom")

    def test_invalidate_device_safe_when_not_cached(self) -> None:
        """invalidate_device on a never-seen device is a no-op."""
        cache = pytest_device._TransportCache()
        cache.invalidate_device("never_seen")  # should not raise


class TestLoadFallbackDevice:
    """Tests for _load_fallback_device."""

    def test_skips_when_no_devices_file(self, monkeypatch, tmp_path) -> None:
        """Should skip with setup instructions when devices.yml is missing."""
        monkeypatch.setenv("CHUMICRO_DEVICES", str(tmp_path / "nope.yml"))
        with pytest.raises(pytest.skip.Exception, match="No devices.yml found"):
            pytest_device._load_fallback_device()

    def test_skips_when_no_devices_configured(self, monkeypatch, tmp_path) -> None:
        """Should skip when no devices match the ide_runtime."""
        devices_file = tmp_path / "devices.yml"
        devices_file.write_text(
            "defaults:\n"
            "  ide_runtime: circuitpython\n"
            "devices:\n"
            "  - id: mp-only\n"
            "    runtime: micropython\n"
            "    address: /dev/ttyUSB0\n"
        )
        monkeypatch.setenv("CHUMICRO_DEVICES", str(devices_file))
        with pytest.raises(pytest.skip.Exception, match="No devices configured"):
            pytest_device._load_fallback_device()

    def test_returns_target_device(self, monkeypatch, tmp_path) -> None:
        """Should return the device matching ide_runtime defaults."""
        devices_file = tmp_path / "devices.yml"
        devices_file.write_text(
            "defaults:\n"
            "  micropython: board2\n"
            "  ide_runtime: micropython\n"
            "devices:\n"
            "  - id: board1\n"
            "    runtime: micropython\n"
            "    address: /dev/ttyUSB0\n"
            "  - id: board2\n"
            "    runtime: micropython\n"
            "    address: /dev/ttyUSB1\n"
        )
        monkeypatch.setenv("CHUMICRO_DEVICES", str(devices_file))
        device = pytest_device._load_fallback_device()
        assert device.identifier == "board2"


class TestShouldSoftResetBeforeStage:
    """Tests for _should_soft_reset_before_stage."""

    def test_false_for_first_file_on_device(self) -> None:
        """The first RAM-mode file should not soft-reset before staging."""
        from chumicro_deploy.testing import FakeTransport

        cache = pytest_device._TransportCache()
        device = DeviceEntry(
            identifier="cp_dev",
            runtime="circuitpython",
            address="/dev/cu.usbmodem1",
        )
        transport = FakeTransport(mode="ram")

        should_reset = pytest_device._should_soft_reset_before_stage(
            cache, device, transport, "timing", "test_heartbeat.py",
        )

        assert should_reset is False

    def test_true_when_switching_files_in_circuitpython_ram_mode(self) -> None:
        """A new RAM-mode file should soft-reset to reclaim interpreter heap."""
        from chumicro_deploy.testing import FakeTransport

        cache = pytest_device._TransportCache()
        cache.mark_staged(("cp_dev", "timing", "test_heartbeat.py"))
        device = DeviceEntry(
            identifier="cp_dev",
            runtime="circuitpython",
            address="/dev/cu.usbmodem1",
        )
        transport = FakeTransport(mode="ram")

        should_reset = pytest_device._should_soft_reset_before_stage(
            cache, device, transport, "timing", "test_heartbeat_ticks.py",
        )

        assert should_reset is True

    def test_false_for_same_file_in_circuitpython_ram_mode(self) -> None:
        """Repeated items from the same file should keep the current batch alive."""
        from chumicro_deploy.testing import FakeTransport

        cache = pytest_device._TransportCache()
        cache.mark_staged(("cp_dev", "timing", "test_heartbeat.py"))
        device = DeviceEntry(
            identifier="cp_dev",
            runtime="circuitpython",
            address="/dev/cu.usbmodem1",
        )
        transport = FakeTransport(mode="ram")

        should_reset = pytest_device._should_soft_reset_before_stage(
            cache, device, transport, "timing", "test_heartbeat.py",
        )

        assert should_reset is False

    def test_false_for_circuitpython_flash_mode(self) -> None:
        """Flash mode should not use the RAM-mode per-file reset rule."""
        from chumicro_deploy.testing import FakeTransport

        cache = pytest_device._TransportCache()
        cache.mark_staged(("cp_dev", "timing", "test_heartbeat.py"))
        device = DeviceEntry(
            identifier="cp_dev",
            runtime="circuitpython",
            address="/dev/cu.usbmodem1",
        )
        transport = FakeTransport(mode="flash")

        should_reset = pytest_device._should_soft_reset_before_stage(
            cache, device, transport, "timing", "test_heartbeat_ticks.py",
        )

        assert should_reset is False

    def test_true_when_switching_files_in_micropython_mount_mode(self) -> None:
        """A new mount-mode file should soft-reset to reclaim interpreter heap.

        Persistent-serial ``mpremote`` keeps one VM across files, so
        ``sys.modules`` accumulates until a soft reset evicts it.  The
        reset is Ctrl-D via raw REPL — no USB re-enumeration.
        """
        from chumicro_deploy.testing import FakeTransport

        cache = pytest_device._TransportCache()
        cache.mark_staged(("mp_dev", "timing", "test_heartbeat.py"))
        device = DeviceEntry(
            identifier="mp_dev",
            runtime="micropython",
            address="/dev/ttyUSB0",
        )
        transport = FakeTransport(mode="mount")

        should_reset = pytest_device._should_soft_reset_before_stage(
            cache, device, transport, "timing", "test_heartbeat_ticks.py",
        )

        assert should_reset is True

    def test_false_for_micropython_copy_mode(self) -> None:
        """Copy mode stages to flash and imports fresh per call — no per-file reset needed."""
        from chumicro_deploy.testing import FakeTransport

        cache = pytest_device._TransportCache()
        cache.mark_staged(("mp_dev", "timing", "test_heartbeat.py"))
        device = DeviceEntry(
            identifier="mp_dev",
            runtime="micropython",
            address="/dev/ttyUSB0",
        )
        transport = FakeTransport(mode="copy")

        should_reset = pytest_device._should_soft_reset_before_stage(
            cache, device, transport, "timing", "test_heartbeat_ticks.py",
        )

        assert should_reset is False


class TestPytestCollectFile:
    """Tests for the pytest_collect_file hook."""

    def test_returns_none_for_non_test_file(self) -> None:
        """Should not collect helper files."""
        result = pytest_device.pytest_collect_file(
            None, Path("/x/functional_tests/conftest.py"),
        )
        assert result is None

    def test_returns_none_outside_functional_tests(self) -> None:
        """Should not collect regular test files."""
        result = pytest_device.pytest_collect_file(
            None, Path("/x/tests/test_normal.py"),
        )
        assert result is None


# ---------------------------------------------------------------------------
# Direct tests for the IDE-path hot loop: _ensure_prepared + _ensure_batch_result
# + the three Item runtest() bodies.  These are what fires when the user
# clicks the PyCharm / VS Code play button on a functional_tests/ target.
# ---------------------------------------------------------------------------


_PASS_OUTPUT = (
    "PASS test_one (0.001s)\n"
    "SUMMARY total=1 failed=0 time=0.001s\n"
)

_TWO_TESTS_OUTPUT = (
    "PASS test_one (0.001s)\n"
    "FAIL test_two (0.002s): boom\n"
    "SUMMARY total=2 failed=1 time=0.003s\n"
)


class _HotPathTransport:
    """Focused FakeTransport for the pytest_device hot path.

    Supports deploy modes the pytest plugin cares about (``ram``,
    ``mount``, ``flash``) plus execute_scripts for chunked RAM-mode
    execution, recover(), and soft_reset().
    """

    def __init__(
        self,
        *,
        mode: str = "ram",
        outputs: list[str] | None = None,
        connect_raises: Exception | None = None,
        execute_raises: Exception | None = None,
        recover_raises: Exception | None = None,
    ) -> None:
        self.mode = mode
        self._outputs = list(outputs or [])
        self._connect_raises = connect_raises
        self._execute_raises = execute_raises
        self._recover_raises = recover_raises
        self.calls: list[tuple[str, tuple]] = []
        self.staged_sources: list[tuple[str, str]] = []

    def connect(self) -> None:
        self.calls.append(("connect", ()))
        if self._connect_raises is not None:
            raise self._connect_raises

    def stage(self, source_dirs, test_files, harness_source) -> None:
        self.calls.append(("stage", (source_dirs, test_files, harness_source)))

    def execute(self, bootstrap_script: str) -> str:
        self.calls.append(("execute", (bootstrap_script,)))
        if self._execute_raises is not None:
            raise self._execute_raises
        return self._outputs.pop(0) if self._outputs else ""

    def execute_scripts(self, bootstrap_scripts: list[str]) -> str:
        self.calls.append(("execute_scripts", (list(bootstrap_scripts),)))
        if self._execute_raises is not None:
            raise self._execute_raises
        return self._outputs.pop(0) if self._outputs else ""

    def inline_script_budget_bytes(self) -> int:
        return 32 * 1024

    def soft_reset(self) -> None:
        self.calls.append(("soft_reset", ()))

    def reset(self) -> None:
        self.calls.append(("reset", ()))

    def recover(self) -> None:
        self.calls.append(("recover", ()))
        if self._recover_raises is not None:
            raise self._recover_raises

    def disconnect(self) -> None:
        self.calls.append(("disconnect", ()))


class _FakeSession:
    """Minimal pytest.Session stand-in that hosts a _TransportCache."""

    def __init__(self, cache: pytest_device._TransportCache) -> None:
        self._device_transport_cache = cache


def _hot_path_device(runtime: str = "circuitpython") -> DeviceEntry:
    return DeviceEntry(
        identifier=f"{runtime}-1",
        runtime=runtime,
        address=f"/dev/ttyUSB-{runtime}",
        deploy_mode="ram",
    )


def _prime_cache_with_transport(
    cache: pytest_device._TransportCache,
    device_entry: DeviceEntry,
    transport: _HotPathTransport,
) -> None:
    """Install *transport* in *cache* without hitting create_transport."""
    cache._transports[device_entry.identifier] = transport


@pytest.fixture
def hot_path_cache():
    """Return a fresh _TransportCache for hot-path tests."""
    return pytest_device._TransportCache()


@pytest.fixture
def hot_path_session(hot_path_cache):
    """Return a minimal session object with the cache attached."""
    return _FakeSession(hot_path_cache)


def _make_prepare_item(session, device_entry, test_file) -> pytest_device.DevicePrepareItem:
    """Instantiate a DevicePrepareItem bypassing pytest's collect machinery."""
    # DevicePrepareItem extends pytest.Item; Item.__init__ needs a parent.
    # Using Item.from_parent is brittle in-unit-test; construct via
    # __new__ and set the attributes DeviceRuntimeItem.__init__ sets.
    item = pytest_device.DevicePrepareItem.__new__(pytest_device.DevicePrepareItem)
    item.session = session
    item.test_file = test_file
    item.target_device = device_entry
    item.library_dir = test_file.parent.parent
    item._library_name = item.library_dir.name
    item._reported_duration = None
    item._reported_test_total_duration = None
    return item


def _make_run_file_item(session, device_entry, test_file) -> pytest_device.DeviceRunFileItem:
    item = pytest_device.DeviceRunFileItem.__new__(pytest_device.DeviceRunFileItem)
    item.session = session
    item.test_file = test_file
    item.target_device = device_entry
    item.library_dir = test_file.parent.parent
    item._library_name = item.library_dir.name
    item._reported_duration = None
    item._reported_test_total_duration = None
    return item


def _make_test_item(
    session, device_entry, test_file, function_name: str,
) -> pytest_device.DeviceTestItem:
    item = pytest_device.DeviceTestItem.__new__(pytest_device.DeviceTestItem)
    item.session = session
    item.test_file = test_file
    item.target_device = device_entry
    item.library_dir = test_file.parent.parent
    item._library_name = item.library_dir.name
    item._function_name = function_name
    item._reported_duration = None
    item._reported_test_total_duration = None
    return item


def _make_functional_test_file(tmp_path: Path, library: str) -> Path:
    """Create a minimal functional_tests file layout tmp_path/<library>/functional_tests/."""
    test_dir = tmp_path / library / "functional_tests"
    test_dir.mkdir(parents=True)
    test_file = test_dir / "test_x.py"
    test_file.write_text(
        "def test_one(): pass\n"
        "def test_two(): pass\n",
    )
    return test_file


class TestEnsurePrepared:
    """Tests for DeviceRuntimeItem._ensure_prepared."""

    def test_flash_mode_bulk_stages_once(
        self, tmp_path, hot_path_session, hot_path_cache, monkeypatch,
    ) -> None:
        """Flash mode triggers bulk staging on first use, then never again."""
        device = _hot_path_device()
        transport = _HotPathTransport(mode="flash")
        _prime_cache_with_transport(hot_path_cache, device, transport)

        bulk_calls: list[tuple] = []
        monkeypatch.setattr(
            pytest_device, "_bulk_stage_for_device",
            lambda session, device_entry, transport: bulk_calls.append(
                (session, device_entry.identifier),
            ),
        )

        test_file = _make_functional_test_file(tmp_path, "alpha")
        item = _make_prepare_item(hot_path_session, device, test_file)
        item._ensure_prepared(device)
        item._ensure_prepared(device)  # second call should not re-stage.

        assert len(bulk_calls) == 1
        assert hot_path_cache.is_fully_staged(device.identifier)

    def test_ram_mode_stages_per_file(
        self, tmp_path, hot_path_session, hot_path_cache, monkeypatch,
    ) -> None:
        """RAM mode stages per (device, library, file); changing file triggers re-stage."""
        device = _hot_path_device()
        transport = _HotPathTransport(mode="ram")
        _prime_cache_with_transport(hot_path_cache, device, transport)

        monkeypatch.setattr(
            pytest_device, "resolve_library_source_dirs",
            lambda library_dir, test_files=None: [library_dir / "src"],
        )

        test_file_a = _make_functional_test_file(tmp_path, "alpha")
        test_file_b = tmp_path / "alpha" / "functional_tests" / "test_y.py"
        test_file_b.write_text("def test_other(): pass\n")

        item_a = _make_prepare_item(hot_path_session, device, test_file_a)
        item_a._ensure_prepared(device)
        item_a._ensure_prepared(device)  # same file — no re-stage.

        item_b = _make_prepare_item(hot_path_session, device, test_file_b)
        item_b._ensure_prepared(device)  # different file — re-stages.

        stage_calls = [call for call in transport.calls if call[0] == "stage"]
        assert len(stage_calls) == 2

    def test_connect_failure_fails_current_item_and_caches_error(
        self, tmp_path, hot_path_session, hot_path_cache, monkeypatch,
    ) -> None:
        """A failed get_transport fails the item and caches the error."""
        device = _hot_path_device()

        def raise_on_create(device_entry, deploy_mode=None):
            raise RuntimeError("device not reachable")

        monkeypatch.setattr(pytest_device, "create_transport", raise_on_create)

        test_file = _make_functional_test_file(tmp_path, "alpha")
        item = _make_prepare_item(hot_path_session, device, test_file)

        with pytest.raises(pytest.fail.Exception, match="Transport connection failed"):
            item._ensure_prepared(device)

        # Error was cached for the batch so subsequent items in the
        # same file surface the same message.
        cached = hot_path_cache.get_batch_result(
            (device.identifier, "alpha", test_file.name),
        )
        assert cached is not None
        assert "not reachable" in cached[1]


class TestEnsureBatchResult:
    """Tests for DeviceRuntimeItem._ensure_batch_result."""

    def test_parses_and_caches_result_on_first_call(
        self, tmp_path, hot_path_session, hot_path_cache, monkeypatch,
    ) -> None:
        """First call runs the batch, parses output, and caches the result."""
        device = _hot_path_device()
        transport = _HotPathTransport(mode="ram", outputs=[_PASS_OUTPUT])
        _prime_cache_with_transport(hot_path_cache, device, transport)

        monkeypatch.setattr(
            pytest_device, "resolve_library_source_dirs",
            lambda library_dir, test_files=None: [library_dir / "src"],
        )

        test_file = _make_functional_test_file(tmp_path, "alpha")
        item = _make_run_file_item(hot_path_session, device, test_file)
        result, raw = item._ensure_batch_result(device)

        assert raw == _PASS_OUTPUT
        assert result is not None
        assert len(result.tests) == 1
        assert result.tests[0].status == "PASS"

        # Cache populated.
        cached = hot_path_cache.get_batch_result(
            (device.identifier, "alpha", test_file.name),
        )
        assert cached == (result, raw)

    def test_returns_cached_result_on_second_call(
        self, tmp_path, hot_path_session, hot_path_cache, monkeypatch,
    ) -> None:
        """Second call looks up the cached result instead of re-running."""
        device = _hot_path_device()
        transport = _HotPathTransport(mode="ram", outputs=[_PASS_OUTPUT])
        _prime_cache_with_transport(hot_path_cache, device, transport)

        monkeypatch.setattr(
            pytest_device, "resolve_library_source_dirs",
            lambda library_dir, test_files=None: [library_dir / "src"],
        )

        test_file = _make_functional_test_file(tmp_path, "alpha")
        item = _make_run_file_item(hot_path_session, device, test_file)
        item._ensure_batch_result(device)

        # Transport had one outputs entry — second call must NOT pop again.
        result, raw = item._ensure_batch_result(device)
        assert raw == _PASS_OUTPUT
        # Only one execute/execute_scripts ever happened.
        execute_total = sum(
            1 for name, _ in transport.calls
            if name in ("execute", "execute_scripts")
        )
        assert execute_total == 1

    def test_execute_failure_calls_recover_and_caches_error(
        self, tmp_path, hot_path_session, hot_path_cache, monkeypatch,
    ) -> None:
        """Execute failures trigger recover() and cache the error message."""
        device = _hot_path_device()
        transport = _HotPathTransport(
            mode="ram",
            execute_raises=RuntimeError("timeout"),
        )
        _prime_cache_with_transport(hot_path_cache, device, transport)

        monkeypatch.setattr(
            pytest_device, "resolve_library_source_dirs",
            lambda library_dir, test_files=None: [library_dir / "src"],
        )

        test_file = _make_functional_test_file(tmp_path, "alpha")
        item = _make_run_file_item(hot_path_session, device, test_file)

        with pytest.raises(pytest.fail.Exception, match="Device execution failed"):
            item._ensure_batch_result(device)

        # recover() was called.
        assert ("recover", ()) in transport.calls
        # Error cached with parsed_result=None so subsequent items fail the same way.
        cached = hot_path_cache.get_batch_result(
            (device.identifier, "alpha", test_file.name),
        )
        assert cached is not None
        parsed_result, error_text = cached
        assert parsed_result is None
        assert "timeout" in error_text

    def test_recover_failure_evicts_transport(
        self, tmp_path, hot_path_session, hot_path_cache, monkeypatch,
    ) -> None:
        """When recover() fails, the transport is evicted from the cache.

        The next file's _ensure_prepared will reconnect from scratch
        instead of hitting a cached transport stuck mid-raw-REPL.
        """
        device = _hot_path_device()
        transport = _HotPathTransport(
            mode="ram",
            execute_raises=RuntimeError("timeout"),
            recover_raises=RuntimeError("board wedged"),
        )
        _prime_cache_with_transport(hot_path_cache, device, transport)

        monkeypatch.setattr(
            pytest_device, "resolve_library_source_dirs",
            lambda library_dir, test_files=None: [library_dir / "src"],
        )

        test_file = _make_functional_test_file(tmp_path, "alpha")
        item = _make_run_file_item(hot_path_session, device, test_file)

        with pytest.raises(pytest.fail.Exception, match="Device execution failed"):
            item._ensure_batch_result(device)

        # Transport is gone from the cache.
        assert device.identifier not in hot_path_cache._transports
        # Batch error still cached so subsequent items see the same failure.
        cached = hot_path_cache.get_batch_result(
            (device.identifier, "alpha", test_file.name),
        )
        assert cached is not None
        assert cached[0] is None


class TestDevicePrepareItemRuntest:
    """Tests for DevicePrepareItem.runtest."""

    def test_runtest_prepares_and_exits_cleanly(
        self, tmp_path, hot_path_session, hot_path_cache, monkeypatch,
    ) -> None:
        """Prepare item succeeds after staging."""
        device = _hot_path_device()
        transport = _HotPathTransport(mode="flash")
        _prime_cache_with_transport(hot_path_cache, device, transport)
        monkeypatch.setattr(
            pytest_device, "_bulk_stage_for_device",
            lambda session, device_entry, transport: None,
        )

        test_file = _make_functional_test_file(tmp_path, "alpha")
        item = _make_prepare_item(hot_path_session, device, test_file)
        item.runtest()  # must not raise


class TestDeviceRunFileItemRuntest:
    """Tests for DeviceRunFileItem.runtest."""

    def test_runtest_succeeds_when_batch_produces_tests(
        self, tmp_path, hot_path_session, hot_path_cache, monkeypatch,
    ) -> None:
        """A successful batch with tests lets the run-file item pass."""
        device = _hot_path_device()
        transport = _HotPathTransport(mode="ram", outputs=[_PASS_OUTPUT])
        _prime_cache_with_transport(hot_path_cache, device, transport)
        monkeypatch.setattr(
            pytest_device, "resolve_library_source_dirs",
            lambda library_dir, test_files=None: [library_dir / "src"],
        )

        test_file = _make_functional_test_file(tmp_path, "alpha")
        item = _make_run_file_item(hot_path_session, device, test_file)
        item.runtest()

        # The reported total duration is set from parsed test durations.
        assert item._reported_test_total_duration is not None

    def test_runtest_fails_when_cached_batch_has_no_result(
        self, tmp_path, hot_path_session, hot_path_cache,
    ) -> None:
        """A pre-cached (None, error) batch result fails the item with the error."""
        device = _hot_path_device()
        test_file = _make_functional_test_file(tmp_path, "alpha")
        hot_path_cache.cache_batch_result(
            (device.identifier, "alpha", test_file.name),
            None, "Previous boot failure",
        )

        item = _make_run_file_item(hot_path_session, device, test_file)
        with pytest.raises(pytest.fail.Exception, match="Previous boot failure"):
            item.runtest()


class TestDeviceTestItemRuntest:
    """Tests for DeviceTestItem.runtest — per-test result lookup."""

    def test_passes_when_individual_test_passed(
        self, tmp_path, hot_path_session, hot_path_cache, monkeypatch,
    ) -> None:
        """test_one in a passing batch → item passes."""
        device = _hot_path_device()
        transport = _HotPathTransport(mode="ram", outputs=[_PASS_OUTPUT])
        _prime_cache_with_transport(hot_path_cache, device, transport)
        monkeypatch.setattr(
            pytest_device, "resolve_library_source_dirs",
            lambda library_dir, test_files=None: [library_dir / "src"],
        )

        test_file = _make_functional_test_file(tmp_path, "alpha")
        item = _make_test_item(
            hot_path_session, device, test_file, "test_one",
        )
        item.runtest()  # must not raise.
        assert item._reported_duration == pytest.approx(0.001)

    def test_fails_when_individual_test_failed(
        self, tmp_path, hot_path_session, hot_path_cache, monkeypatch,
    ) -> None:
        """test_two failed in the harness output → item fails with the raw output."""
        device = _hot_path_device()
        transport = _HotPathTransport(mode="ram", outputs=[_TWO_TESTS_OUTPUT])
        _prime_cache_with_transport(hot_path_cache, device, transport)
        monkeypatch.setattr(
            pytest_device, "resolve_library_source_dirs",
            lambda library_dir, test_files=None: [library_dir / "src"],
        )

        test_file = _make_functional_test_file(tmp_path, "alpha")
        item = _make_test_item(
            hot_path_session, device, test_file, "test_two",
        )
        with pytest.raises(pytest.fail.Exception, match="Device test FAIL"):
            item.runtest()

    def test_fails_when_function_name_not_in_output(
        self, tmp_path, hot_path_session, hot_path_cache, monkeypatch,
    ) -> None:
        """If the function name isn't in the parsed output, fail with a clear error."""
        device = _hot_path_device()
        transport = _HotPathTransport(mode="ram", outputs=[_PASS_OUTPUT])
        _prime_cache_with_transport(hot_path_cache, device, transport)
        monkeypatch.setattr(
            pytest_device, "resolve_library_source_dirs",
            lambda library_dir, test_files=None: [library_dir / "src"],
        )

        test_file = _make_functional_test_file(tmp_path, "alpha")
        item = _make_test_item(
            hot_path_session, device, test_file, "test_nonexistent",
        )
        with pytest.raises(pytest.fail.Exception, match="not found in device output"):
            item.runtest()

    def test_shares_batch_result_across_items(
        self, tmp_path, hot_path_session, hot_path_cache, monkeypatch,
    ) -> None:
        """Multiple items from the same file trigger only one execute_scripts.

        The batched-execution optimization: 7 tests from the same file
        run as ONE on-device invocation, not 7.
        """
        device = _hot_path_device()
        transport = _HotPathTransport(mode="ram", outputs=[_TWO_TESTS_OUTPUT])
        _prime_cache_with_transport(hot_path_cache, device, transport)
        monkeypatch.setattr(
            pytest_device, "resolve_library_source_dirs",
            lambda library_dir, test_files=None: [library_dir / "src"],
        )

        test_file = _make_functional_test_file(tmp_path, "alpha")
        item_one = _make_test_item(
            hot_path_session, device, test_file, "test_one",
        )
        item_one.runtest()  # pass

        # Second test item reuses the cached result.
        item_two = _make_test_item(
            hot_path_session, device, test_file, "test_two",
        )
        with pytest.raises(pytest.fail.Exception):
            item_two.runtest()

        # Only one batch invocation happened.
        batch_invocations = sum(
            1 for name, _ in transport.calls
            if name in ("execute", "execute_scripts")
        )
        assert batch_invocations == 1
