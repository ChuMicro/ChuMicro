"""Tests for the chumicro-pytest-device plugin.

Tests AST-based test discovery, DeviceTestItem behaviour with faked
transports, device config loading, and collection hook behaviour.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest
from chumicro_deploy import DeviceEntry
from chumicro_pytest_device import backends
from chumicro_pytest_device import plugin as pytest_device
from chumicro_pytest_device.result_parser import TestResult as ParsedTestResult


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


class TestFilterTargetsByMarker:
    """Tests for the ``__chumicro_runtimes__`` collection filter."""

    @staticmethod
    def _two_runtime_targets() -> list[DeviceEntry]:
        return [
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

    def test_unmarked_file_keeps_every_target(self, tmp_path: Path) -> None:
        """No marker → every configured target survives the filter."""
        test_file = tmp_path / "test_universal.py"
        test_file.write_text("def test_alpha():\n    pass\n")
        targets = self._two_runtime_targets()

        result = pytest_device._filter_targets_by_marker(targets, test_file)

        assert result == targets

    def test_circuitpython_marker_drops_micropython_target(
        self, tmp_path: Path,
    ) -> None:
        """``("circuitpython",)`` marker keeps only the CP target."""
        test_file = tmp_path / "test_cp_only.py"
        test_file.write_text(
            '__chumicro_runtimes__ = ("circuitpython",)\n'
            "def test_alpha():\n    pass\n",
        )

        result = pytest_device._filter_targets_by_marker(
            self._two_runtime_targets(), test_file,
        )

        assert [device.runtime for device in result or []] == ["circuitpython"]

    def test_micropython_marker_drops_circuitpython_target(
        self, tmp_path: Path,
    ) -> None:
        """``("micropython",)`` marker keeps only the MP target."""
        test_file = tmp_path / "test_mp_only.py"
        test_file.write_text(
            '__chumicro_runtimes__ = ("micropython",)\n'
            "def test_alpha():\n    pass\n",
        )

        result = pytest_device._filter_targets_by_marker(
            self._two_runtime_targets(), test_file,
        )

        assert [device.runtime for device in result or []] == ["micropython"]

    def test_sub_runtime_marker_folds_into_base_runtime(
        self, tmp_path: Path,
    ) -> None:
        """``("micropython_esp32",)`` matches generic ``micropython`` targets.

        Folds the same way :func:`chumicro_deploy.runtime_marker.file_targets_runtime`
        does — both MP variants share one bundle today.
        """
        test_file = tmp_path / "test_mp_esp32_only.py"
        test_file.write_text(
            '__chumicro_runtimes__ = ("micropython_esp32",)\n'
            "def test_alpha():\n    pass\n",
        )

        result = pytest_device._filter_targets_by_marker(
            self._two_runtime_targets(), test_file,
        )

        assert [device.runtime for device in result or []] == ["micropython"]

    def test_marker_excluding_every_target_returns_empty_list(
        self, tmp_path: Path,
    ) -> None:
        """All targets dropped → empty list (collect() yields nothing)."""
        test_file = tmp_path / "test_cpython_only.py"
        test_file.write_text(
            '__chumicro_runtimes__ = ("cpython",)\n'
            "def test_alpha():\n    pass\n",
        )

        result = pytest_device._filter_targets_by_marker(
            self._two_runtime_targets(), test_file,
        )

        assert result == []

    def test_none_targets_passthrough(self, tmp_path: Path) -> None:
        """No devices.yml → ``None`` flows through unchanged."""
        test_file = tmp_path / "test_anything.py"
        test_file.write_text("def test_alpha():\n    pass\n")

        result = pytest_device._filter_targets_by_marker(None, test_file)

        assert result is None


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
        cache.mark_library_staged("dev1", "timing")
        cache.disconnect_all()
        assert cache.needs_staging(("dev1", "timing", "test_ticks.py")) is True
        assert cache.get_batch_result(("dev1", "timing", "test_ticks.py")) is None
        assert cache.current_staged_library("dev1") is None

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

    def test_current_staged_library_not_set_initially(self) -> None:
        """A fresh cache should report no library staged on any device."""
        cache = pytest_device._TransportCache()
        assert cache.current_staged_library("dev1") is None

    def test_mark_library_staged(self) -> None:
        """After marking a library staged, current_staged_library returns it."""
        cache = pytest_device._TransportCache()
        cache.mark_library_staged("dev1", "timing")
        assert cache.current_staged_library("dev1") == "timing"

    def test_mark_library_staged_replaces_prior(self) -> None:
        """Marking a different library replaces the prior marker (drive cleanup is rsync's job)."""
        cache = pytest_device._TransportCache()
        cache.mark_library_staged("dev1", "timing")
        cache.mark_library_staged("dev1", "kvstore")
        assert cache.current_staged_library("dev1") == "kvstore"

    def test_staged_library_separate_per_device(self) -> None:
        """Staged-library state should be per-device."""
        cache = pytest_device._TransportCache()
        cache.mark_library_staged("dev1", "timing")
        assert cache.current_staged_library("dev2") is None

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
            cache.mark_library_staged("dev1", "timing")
            assert cache.current_staged_library("dev1") == "timing"
            assert "dev1" in cache._transports

            cache.invalidate_device("dev1")

            # Transport gone, staging cleared.
            assert "dev1" not in cache._transports
            assert cache.has_staged_file("dev1") is False
            assert cache.current_staged_library("dev1") is None
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

    def test_skips_when_no_devices_file(self, tmp_path) -> None:
        """Should skip with setup instructions when devices.yml is missing."""
        with pytest.raises(pytest.skip.Exception, match="No devices.yml found"):
            pytest_device._load_fallback_device(
                _FakeSession(pytest_device._TransportCache(), rootpath=tmp_path),
            )

    def test_skips_when_no_devices_configured(self, tmp_path) -> None:
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
        with pytest.raises(pytest.skip.Exception, match="No devices registered"):
            pytest_device._load_fallback_device(
                _FakeSession(pytest_device._TransportCache(), rootpath=tmp_path),
            )

    def test_returns_target_device(self, tmp_path) -> None:
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
        device = pytest_device._load_fallback_device(
            _FakeSession(pytest_device._TransportCache(), rootpath=tmp_path),
        )
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


class TestIsLibraryUnitTest:
    """Tests for _is_library_unit_test path-shape classification."""

    def test_matches_libraries_tests_test_file(self) -> None:
        assert pytest_device._is_library_unit_test(
            Path("libraries/timing/tests/test_heartbeat.py"),
        ) is True

    def test_excludes_pytest_only_suffix(self) -> None:
        """``test_*_pytest.py`` files opt out of the cross-runtime harness."""
        assert pytest_device._is_library_unit_test(
            Path("libraries/timing/tests/test_ticks_pytest.py"),
        ) is False

    def test_excludes_functional_tests_path(self) -> None:
        assert pytest_device._is_library_unit_test(
            Path("libraries/timing/functional_tests/test_real.py"),
        ) is False

    def test_excludes_workbench_tests(self) -> None:
        assert pytest_device._is_library_unit_test(
            Path("workbench/deploy/tests/test_device.py"),
        ) is False

    def test_excludes_non_test_file(self) -> None:
        assert pytest_device._is_library_unit_test(
            Path("libraries/timing/tests/conftest.py"),
        ) is False


class TestSynthesizeUnixPortTargets:
    """Tests for the unix-port DeviceEntry synthesis."""

    def test_runtime_micropython_yields_one_entry(self) -> None:
        targets = pytest_device._synthesize_unix_port_targets("micropython")
        assert len(targets) == 1
        assert targets[0].runtime == "micropython"
        assert targets[0].identifier == "micropython-unix-port"
        assert targets[0].address == "unix-port"

    def test_runtime_circuitpython_yields_one_entry(self) -> None:
        targets = pytest_device._synthesize_unix_port_targets("circuitpython")
        assert len(targets) == 1
        assert targets[0].runtime == "circuitpython"

    def test_runtime_both_yields_two_entries(self) -> None:
        targets = pytest_device._synthesize_unix_port_targets("both")
        runtimes = [target.runtime for target in targets]
        assert runtimes == ["micropython", "circuitpython"]


class TestReadLibraryPlatforms:
    """Tests for the per-library [tool.chumicro].platforms reader."""

    def test_returns_none_when_pyproject_absent(self, tmp_path: Path) -> None:
        result = pytest_device._read_library_platforms(tmp_path)
        assert result is None

    def test_returns_none_when_platforms_key_absent(
        self, tmp_path: Path,
    ) -> None:
        (tmp_path / "pyproject.toml").write_text(
            "[project]\nname = \"chumicro-foo\"\n",
        )
        result = pytest_device._read_library_platforms(tmp_path)
        assert result is None

    def test_returns_declared_platforms(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            "[tool.chumicro]\nplatforms = [\"cpython\", \"micropython\"]\n",
        )
        result = pytest_device._read_library_platforms(tmp_path)
        assert result == ("cpython", "micropython")


class TestResolveUnixPortBinary:
    """Tests for the unix-port binary resolution helper."""

    def test_explicit_override_wins(self, tmp_path: Path) -> None:
        resolved = backends.resolve_unix_port_binary(
            tmp_path, "micropython", "/some/explicit/path",
        )
        assert resolved == "/some/explicit/path"

    def test_falls_back_to_marker_file(self, tmp_path: Path) -> None:
        tools_dir = tmp_path / ".tools"
        tools_dir.mkdir()
        binary = tools_dir / "stub_micropython"
        binary.write_text("#!/bin/sh\necho stub\n")
        (tools_dir / "micropython.path").write_text(str(binary))
        resolved = backends.resolve_unix_port_binary(
            tmp_path, "micropython", None,
        )
        assert resolved == str(binary)

    def test_skips_marker_when_binary_missing(self, tmp_path: Path) -> None:
        """A stale marker pointing at a deleted binary should not resolve."""
        tools_dir = tmp_path / ".tools"
        tools_dir.mkdir()
        (tools_dir / "micropython.path").write_text(
            str(tmp_path / "deleted-binary"),
        )
        # No PATH lookup will hit "micropython" in this isolated test env,
        # so resolution returns None.
        resolved = backends.resolve_unix_port_binary(
            tmp_path, "micropython", None,
        )
        assert resolved is None or resolved != str(
            tmp_path / "deleted-binary",
        )


class TestUnixPortBackendPrepare:
    """Tests for UnixPortBackend.prepare raising on missing prerequisites."""

    def test_missing_binary_raises_prepare_error(self, tmp_path: Path) -> None:
        backend = backends.UnixPortBackend(
            tmp_path, binaries={"micropython": None, "circuitpython": None},
        )
        target = DeviceEntry(
            identifier="micropython-unix-port",
            runtime="micropython",
            address="unix-port",
        )
        item = SimpleNamespace(test_file=tmp_path / "test_x.py")
        with pytest.raises(backends.BackendPrepareError, match="not found"):
            backend.prepare(item, target)  # type: ignore[arg-type]

    def test_missing_harness_script_raises_prepare_error(
        self, tmp_path: Path,
    ) -> None:
        binary = tmp_path / "stub-micropython"
        binary.write_text("#!/bin/sh\n")
        backend = backends.UnixPortBackend(
            tmp_path, binaries={"micropython": str(binary)},
        )
        target = DeviceEntry(
            identifier="micropython-unix-port",
            runtime="micropython",
            address="unix-port",
        )
        item = SimpleNamespace(test_file=tmp_path / "test_x.py")
        with pytest.raises(backends.BackendPrepareError, match="harness"):
            backend.prepare(item, target)  # type: ignore[arg-type]


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

    def stage(
        self,
        source_dirs,
        test_files,
        harness_source,
        *,
        extra_modules=None,
        extra_files=None,
    ) -> None:
        self.calls.append(
            (
                "stage",
                (source_dirs, test_files, harness_source, extra_modules, extra_files),
            ),
        )

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


class _FakeConfig:
    """Minimal pytest.Config stand-in that returns None for every option."""

    def __init__(self, rootpath: Path) -> None:
        # ``pytest.Config.rootpath`` is what the plugin uses to derive
        # ``support/test_harness/src`` and ``libraries/`` paths.  Always
        # required — pinning a default to a hard-coded workspace root
        # silently couples tests to live filesystem state.
        self.rootpath = rootpath
        # ``Config.stash`` is the canonical place for plugin data.
        # ``set_runtime_config`` writes to it; the plugin reads from it
        # at stage time to encode the runtime-config payload.  Real
        # pytest provides a ``Stash`` instance here; a plain dict
        # exposes the same ``__setitem__`` / ``.get(...)`` surface the
        # plugin uses.
        self.stash: dict = {}

    def getoption(self, name: str, default=None):  # noqa: D401, ANN001
        return default


class _FakeSession:
    """Minimal pytest.Session stand-in that hosts a _TransportCache."""

    def __init__(
        self, cache: pytest_device._TransportCache, *, rootpath: Path,
    ) -> None:
        self._device_transport_cache = cache
        self._backend = pytest_device.DeviceBackend()
        self.config = _FakeConfig(rootpath=rootpath)


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
def hot_path_session(hot_path_cache, tmp_path):
    """Return a minimal session object with the cache attached.

    ``rootpath`` points at ``tmp_path`` so any plugin code path that
    reads ``session.config.rootpath`` resolves to a synthetic dir
    rather than the contributor's real workspace.
    """
    return _FakeSession(hot_path_cache, rootpath=tmp_path)


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

    def test_flash_mode_bulk_stages_once_per_library(
        self, tmp_path, hot_path_session, hot_path_cache, monkeypatch,
    ) -> None:
        """Flash mode bulk-stages on first use per library; same-library re-entry is a no-op."""
        device = _hot_path_device()
        transport = _HotPathTransport(mode="flash")
        _prime_cache_with_transport(hot_path_cache, device, transport)

        bulk_calls: list[tuple] = []
        monkeypatch.setattr(
            pytest_device, "_bulk_stage_for_device",
            lambda session, device_entry, transport, *, library_filter=None: bulk_calls.append(
                (session, device_entry.identifier, library_filter),
            ),
        )

        test_file = _make_functional_test_file(tmp_path, "alpha")
        item = _make_prepare_item(hot_path_session, device, test_file)
        item._ensure_prepared(device)
        item._ensure_prepared(device)  # second call should not re-stage.

        assert len(bulk_calls) == 1
        assert bulk_calls[0] == (hot_path_session, device.identifier, "alpha")
        assert hot_path_cache.current_staged_library(device.identifier) == "alpha"

    def test_flash_mode_restages_on_library_switch(
        self, tmp_path, hot_path_session, hot_path_cache, monkeypatch,
    ) -> None:
        """Flash mode re-stages when the next test belongs to a different library."""
        device = _hot_path_device()
        transport = _HotPathTransport(mode="flash")
        _prime_cache_with_transport(hot_path_cache, device, transport)

        bulk_calls: list[tuple] = []
        monkeypatch.setattr(
            pytest_device, "_bulk_stage_for_device",
            lambda session, device_entry, transport, *, library_filter=None: bulk_calls.append(
                (session, device_entry.identifier, library_filter),
            ),
        )

        alpha_test = _make_functional_test_file(tmp_path, "alpha")
        beta_test = _make_functional_test_file(tmp_path, "beta")
        alpha_item = _make_prepare_item(hot_path_session, device, alpha_test)
        beta_item = _make_prepare_item(hot_path_session, device, beta_test)

        alpha_item._ensure_prepared(device)
        beta_item._ensure_prepared(device)
        beta_item._ensure_prepared(device)  # same library — no extra stage.
        alpha_item._ensure_prepared(device)  # back to alpha — restage.

        library_sequence = [call[2] for call in bulk_calls]
        assert library_sequence == ["alpha", "beta", "alpha"]
        assert hot_path_cache.current_staged_library(device.identifier) == "alpha"

    def test_ram_mode_stages_per_file(
        self, tmp_path, hot_path_session, hot_path_cache, monkeypatch,
    ) -> None:
        """RAM mode stages per (device, library, file); changing file triggers re-stage."""
        device = _hot_path_device()
        transport = _HotPathTransport(mode="ram")
        _prime_cache_with_transport(hot_path_cache, device, transport)

        monkeypatch.setattr(
            pytest_device, "resolve_library_source_dirs",
            lambda library_dir, *, libraries_root=None, test_files=None: [library_dir / "src"],
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
            lambda library_dir, *, libraries_root=None, test_files=None: [library_dir / "src"],
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
            lambda library_dir, *, libraries_root=None, test_files=None: [library_dir / "src"],
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
            lambda library_dir, *, libraries_root=None, test_files=None: [library_dir / "src"],
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
            lambda library_dir, *, libraries_root=None, test_files=None: [library_dir / "src"],
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
            lambda session, device_entry, transport, *, library_filter=None: None,
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
            lambda library_dir, *, libraries_root=None, test_files=None: [library_dir / "src"],
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
            lambda library_dir, *, libraries_root=None, test_files=None: [library_dir / "src"],
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
            lambda library_dir, *, libraries_root=None, test_files=None: [library_dir / "src"],
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
            lambda library_dir, *, libraries_root=None, test_files=None: [library_dir / "src"],
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
            lambda library_dir, *, libraries_root=None, test_files=None: [library_dir / "src"],
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


class TestPytestCollectionModifyItemsRequiredKeys:
    """Skip-marker behavior for missing required runtime-config keys.

    The hook reads the conftest's registered ``required_keys`` via
    ``set_runtime_config(..., required_keys=...)`` and applies a
    skip marker to every :class:`DeviceRuntimeItem` when one or more
    keys are absent from the staged payload.
    """

    @staticmethod
    def _make_device_item_mock(nodeid: str = "tests/test_x.py::test_y") -> object:
        """Return a Mock satisfying ``isinstance(item, DeviceRuntimeItem)``.

        The deselect-sweep guard reads ``item.nodeid`` as a string, so
        we set it explicitly — leaving it as a Mock raises TypeError
        on ``"functional_tests" in item.nodeid``.
        """
        from unittest.mock import Mock  # noqa: PLC0415

        item = Mock(spec=pytest_device.DeviceRuntimeItem)
        item.nodeid = nodeid
        return item

    @staticmethod
    def _make_non_device_item_mock(
        nodeid: str = "tests/test_x.py::test_y",
    ) -> object:
        """Return a plain Mock that's NOT a ``DeviceRuntimeItem`` subclass."""
        from unittest.mock import Mock  # noqa: PLC0415

        item = Mock(spec=pytest.Item)
        item.nodeid = nodeid
        return item

    def _stub_config(
        self,
        payload: dict | None,
        required_keys: tuple[str, ...] = (),
    ) -> object:
        from chumicro_pytest_device.runtime_config import set_runtime_config  # noqa: PLC0415

        class _Stub:
            def __init__(self) -> None:
                self.stash: dict = {}
                self.hook = SimpleNamespace(
                    pytest_deselected=lambda **_kwargs: None,
                )

            def getoption(self, _name, default=None):  # noqa: ANN001
                return default

        config = _Stub()
        set_runtime_config(config, payload, required_keys=required_keys)
        return config

    def test_no_required_keys_no_skip(self) -> None:
        """Default behavior — no required_keys means no validation."""
        config = self._stub_config(payload={"wifi.ssid": "x"})
        device_item = self._make_device_item_mock()
        items = [device_item]
        pytest_device.pytest_collection_modifyitems(config, items)
        device_item.add_marker.assert_not_called()

    def test_complete_payload_no_skip(self) -> None:
        """Required keys all present in payload → no skip marker."""
        config = self._stub_config(
            payload={"wifi.ssid": "x", "wifi.password": "p"},
            required_keys=("wifi.ssid", "wifi.password"),
        )
        device_item = self._make_device_item_mock()
        items = [device_item]
        pytest_device.pytest_collection_modifyitems(config, items)
        device_item.add_marker.assert_not_called()

    def test_partial_payload_skips_with_named_missing_keys(self) -> None:
        """Skip message names every missing key in declaration order."""
        config = self._stub_config(
            payload={"wifi.ssid": "x"},
            required_keys=("wifi.ssid", "wifi.password", "mqtt.broker.host"),
        )
        device_item_a = self._make_device_item_mock()
        device_item_b = self._make_device_item_mock()
        items = [device_item_a, device_item_b]
        pytest_device.pytest_collection_modifyitems(config, items)
        # Both items got a skip marker.
        device_item_a.add_marker.assert_called_once()
        device_item_b.add_marker.assert_called_once()
        # The skip reason names every missing key.
        skip_marker = device_item_a.add_marker.call_args.args[0]
        assert "wifi.password" in skip_marker.kwargs["reason"]
        assert "mqtt.broker.host" in skip_marker.kwargs["reason"]
        # Already-present keys aren't repeated as missing.
        assert "wifi.ssid" not in skip_marker.kwargs["reason"].split(": ", 1)[1]

    def test_none_payload_skips_naming_every_required_key(self) -> None:
        """``payload=None`` + required_keys = unconfigured-creds path.
        Skip names every required key (nothing's staged)."""
        config = self._stub_config(
            payload=None, required_keys=("wifi.ssid", "wifi.password"),
        )
        device_item = self._make_device_item_mock()
        items = [device_item]
        pytest_device.pytest_collection_modifyitems(config, items)
        skip_marker = device_item.add_marker.call_args.args[0]
        assert "wifi.ssid" in skip_marker.kwargs["reason"]
        assert "wifi.password" in skip_marker.kwargs["reason"]

    def test_non_device_items_not_marked(self) -> None:
        """Skip marker applies only to ``DeviceRuntimeItem`` instances —
        a plain pytest.Item that survived the deselect sweep is left
        alone (the missing-keys check is functional-tests-specific)."""
        config = self._stub_config(
            payload=None, required_keys=("wifi.ssid",),
        )
        non_device_item = self._make_non_device_item_mock(
            nodeid="tests/test_unrelated.py::test_x",
        )
        items = [non_device_item]
        pytest_device.pytest_collection_modifyitems(config, items)
        non_device_item.add_marker.assert_not_called()


class TestPytestCollectionModifyItemsFeatures:
    """Feature-marker filtering: items targeting devices that don't
    expose the required features get deselected so the test never runs
    on the wrong board.

    The plugin lazy-probes each device once via ``transport.execute``
    and caches the result on the session, so a session with N
    feature-marked items + M devices pays at most M probes.
    """

    @staticmethod
    def _write_feature_test_file(
        tmp_path: Path, *, marker_tuple: str | None,
    ) -> Path:
        """Materialise a fake test file with the given features marker.

        Args:
            tmp_path: Pytest fixture-supplied temp dir.
            marker_tuple: Source representation of the tuple, or
                ``None`` to omit the marker entirely.
        """
        target = tmp_path / "test_feature_aware.py"
        body = ""
        if marker_tuple is not None:
            body += f"__chumicro_features__ = {marker_tuple}\n"
        body += "def test_anything() -> None:\n    pass\n"
        target.write_text(body)
        return target

    @staticmethod
    def _stub_session(
        transport_features: dict[str, str | Exception],
    ) -> object:
        """Return a session stub with a transport cache that returns
        ``transport_features`` from ``execute()``.

        Each entry maps device identifier → either the probe-output
        string the transport's ``execute`` should produce, or an
        Exception instance to raise (simulating an offline device).
        """
        from unittest.mock import MagicMock  # noqa: PLC0415

        class _StubTransport:
            def __init__(self, response: str | Exception) -> None:
                self._response = response

            def run_script(self, _script: str, **_kwargs: object) -> str:
                if isinstance(self._response, Exception):
                    raise self._response
                return self._response

        class _StubTransportCache:
            def __init__(self, features_by_device: dict[str, str | Exception]) -> None:
                self._features = features_by_device

            def get_transport(
                self, device_entry: object, _deploy_mode: object,
            ) -> object:
                return _StubTransport(self._features[device_entry.identifier])

        session = MagicMock(spec=pytest.Session)
        session.config = MagicMock()
        # The default getoption ('--deploy-mode') returns ``None``.
        session.config.getoption = lambda *_args, **_kwargs: None
        session._device_transport_cache = _StubTransportCache(transport_features)
        # Drop the auto-spec attribute pre-set by MagicMock so the
        # plugin's own assignment to session._device_features_cache
        # works through the descriptor.
        del session._device_features_cache  # type: ignore[attr-defined]
        return session

    @staticmethod
    def _make_device_entry(identifier: str, runtime: str = "micropython") -> DeviceEntry:
        return DeviceEntry(
            identifier=identifier, runtime=runtime, address="/dev/null",
        )

    @staticmethod
    def _make_feature_item(
        session: object,
        device: DeviceEntry,
        test_file: Path,
        nodeid: str = "libraries/x/functional_tests/test_y.py::test_anything",
    ) -> object:
        """Return a Mock satisfying ``isinstance(item, DeviceRuntimeItem)``
        with ``target_device`` and ``test_file`` populated."""
        from unittest.mock import Mock  # noqa: PLC0415

        item = Mock(spec=pytest_device.DeviceRuntimeItem)
        item.nodeid = nodeid
        item.target_device = device
        item.test_file = test_file
        item.session = session
        return item

    def _stub_config(self) -> object:
        from chumicro_pytest_device.runtime_config import set_runtime_config  # noqa: PLC0415

        class _Stub:
            def __init__(self) -> None:
                self.stash: dict = {}
                self.deselected: list[object] = []
                self.hook = SimpleNamespace(
                    pytest_deselected=lambda items: self.deselected.extend(items),
                )

            def getoption(self, _name, default=None):  # noqa: ANN001
                return default

        config = _Stub()
        # No required_keys — keep the unrelated check inert in these tests.
        set_runtime_config(config, payload=None, required_keys=())
        return config

    def test_item_kept_when_no_features_marker(self, tmp_path: Path) -> None:
        """Files without the marker pass through unchanged."""
        test_file = self._write_feature_test_file(tmp_path, marker_tuple=None)
        config = self._stub_config()
        session = self._stub_session(transport_features={"esp32-board": "ignored"})
        device = self._make_device_entry("esp32-board")
        item = self._make_feature_item(session, device, test_file)

        items = [item]
        pytest_device.pytest_collection_modifyitems(config, items)

        assert items == [item]
        assert config.deselected == []

    def test_item_kept_when_device_has_required_feature(self, tmp_path: Path) -> None:
        """Probe reports the required feature → item runs on that device."""
        test_file = self._write_feature_test_file(
            tmp_path, marker_tuple='("esp32",)',
        )
        config = self._stub_config()
        session = self._stub_session(transport_features={
            "esp32-board": (
                "boot noise\n"
                "CHUMICRO_FEATURES_BEGIN\n"
                "esp32\n"
                "CHUMICRO_FEATURES_END\n"
            ),
        })
        device = self._make_device_entry("esp32-board")
        item = self._make_feature_item(session, device, test_file)

        items = [item]
        pytest_device.pytest_collection_modifyitems(config, items)

        assert items == [item]
        assert config.deselected == []

    def test_item_deselected_when_device_lacks_required_feature(
        self, tmp_path: Path,
    ) -> None:
        """Probe reports an empty feature set → ESP32-required item drops."""
        test_file = self._write_feature_test_file(
            tmp_path, marker_tuple='("esp32",)',
        )
        config = self._stub_config()
        session = self._stub_session(transport_features={
            "rp2-board": (
                "CHUMICRO_FEATURES_BEGIN\n"
                "CHUMICRO_FEATURES_END\n"
            ),
        })
        device = self._make_device_entry("rp2-board")
        item = self._make_feature_item(session, device, test_file)

        items = [item]
        pytest_device.pytest_collection_modifyitems(config, items)

        assert items == []
        assert config.deselected == [item]

    def test_probe_failure_emits_warning_and_deselects(
        self, tmp_path: Path, recwarn: pytest.WarningsRecorder,
    ) -> None:
        """An unreachable device → warning + deselect, never crash."""
        test_file = self._write_feature_test_file(
            tmp_path, marker_tuple='("esp32",)',
        )
        config = self._stub_config()
        session = self._stub_session(transport_features={
            "offline-board": ConnectionError("device went away"),
        })
        device = self._make_device_entry("offline-board")
        item = self._make_feature_item(session, device, test_file)

        items = [item]
        pytest_device.pytest_collection_modifyitems(config, items)

        assert items == []
        assert config.deselected == [item]
        warning_messages = [str(warning.message) for warning in recwarn.list]
        assert any(
            "offline-board" in message and "device went away" in message
            for message in warning_messages
        )

    def test_probe_runs_once_per_device_across_many_items(
        self, tmp_path: Path,
    ) -> None:
        """Two items on the same device share a single probe."""
        test_file = self._write_feature_test_file(
            tmp_path, marker_tuple='("esp32",)',
        )
        config = self._stub_config()

        probe_calls: list[str] = []

        class _CountingTransport:
            def __init__(self, output: str, identifier: str) -> None:
                self._output = output
                self._identifier = identifier

            def run_script(self, _script: str, **_kwargs: object) -> str:
                probe_calls.append(self._identifier)
                return self._output

        class _CountingTransportCache:
            def get_transport(
                self, device_entry: DeviceEntry, _deploy_mode: object,
            ) -> object:
                return _CountingTransport(
                    "CHUMICRO_FEATURES_BEGIN\nesp32\nCHUMICRO_FEATURES_END\n",
                    device_entry.identifier,
                )

        from unittest.mock import MagicMock  # noqa: PLC0415

        session = MagicMock(spec=pytest.Session)
        session.config = MagicMock()
        session.config.getoption = lambda *_args, **_kwargs: None
        session._device_transport_cache = _CountingTransportCache()
        del session._device_features_cache  # type: ignore[attr-defined]

        device = self._make_device_entry("esp32-board")
        item_a = self._make_feature_item(
            session, device, test_file, nodeid="x::test_a",
        )
        item_b = self._make_feature_item(
            session, device, test_file, nodeid="x::test_b",
        )

        items = [item_a, item_b]
        pytest_device.pytest_collection_modifyitems(config, items)

        assert items == [item_a, item_b]
        assert probe_calls == ["esp32-board"], (
            f"expected one probe per device, got {probe_calls}"
        )
