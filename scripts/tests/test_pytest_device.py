"""Tests for pytest_device — the pytest plugin for device functional tests.

Tests AST-based test discovery, DeviceTestItem behavior with faked
transports, device config loading, and collection hook behavior.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import pytest_device
from device_config import DeviceEntry


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

        assert pytest_device._runtime_prepare_name(device) == "[CircuitPython setup]"

    def test_runtime_run_file_name(self) -> None:
        """Run-file items should include the runtime in a stable label."""
        device = DeviceEntry(
            identifier="mp-board",
            runtime="micropython",
            address="/dev/ttyUSB0",
        )

        assert pytest_device._runtime_run_file_name(device) == "[MicroPython batch run]"


class TestTransportCache:
    """Tests for the _TransportCache helper."""

    def test_needs_staging_initially(self) -> None:
        """A fresh cache should report staging needed."""
        cache = pytest_device._TransportCache()
        assert cache.needs_staging("dev1", "timing", "test_ticks.py") is True

    def test_mark_staged_clears_need(self) -> None:
        """After marking staged, needs_staging returns False."""
        cache = pytest_device._TransportCache()
        cache.mark_staged("dev1", "timing", "test_ticks.py")
        assert cache.needs_staging("dev1", "timing", "test_ticks.py") is False

    def test_has_staged_file_false_initially(self) -> None:
        """A fresh cache should report no prior staged files."""
        cache = pytest_device._TransportCache()
        assert cache.has_staged_file("dev1") is False

    def test_has_staged_file_true_after_mark_staged(self) -> None:
        """mark_staged should record that the device has staged a file."""
        cache = pytest_device._TransportCache()
        cache.mark_staged("dev1", "timing", "test_ticks.py")
        assert cache.has_staged_file("dev1") is True

    def test_different_library_needs_staging(self) -> None:
        """A different library should still need staging."""
        cache = pytest_device._TransportCache()
        cache.mark_staged("dev1", "timing", "test_ticks.py")
        assert cache.needs_staging("dev1", "runner", "test_ticks.py") is True

    def test_different_test_file_needs_staging(self) -> None:
        """A different test file in the same library should need staging."""
        cache = pytest_device._TransportCache()
        cache.mark_staged("dev1", "timing", "test_ticks.py")
        assert cache.needs_staging("dev1", "timing", "test_heartbeat.py") is True

    def test_different_device_needs_staging(self) -> None:
        """A different device should still need staging."""
        cache = pytest_device._TransportCache()
        cache.mark_staged("dev1", "timing", "test_ticks.py")
        assert cache.needs_staging("dev2", "timing", "test_ticks.py") is True

    def test_disconnect_all_clears_state(self) -> None:
        """disconnect_all should clear all cached state including batch results."""
        cache = pytest_device._TransportCache()
        cache.mark_staged("dev1", "timing", "test_ticks.py")
        cache.cache_batch_result("dev1", "timing", "test_ticks.py", "result", "output")
        cache.mark_fully_staged("dev1")
        cache.disconnect_all()
        assert cache.needs_staging("dev1", "timing", "test_ticks.py") is True
        assert cache.get_batch_result("dev1", "timing", "test_ticks.py") is None
        assert cache.is_fully_staged("dev1") is False

    def test_batch_result_not_cached_initially(self) -> None:
        """A fresh cache should have no batch results."""
        cache = pytest_device._TransportCache()
        assert cache.get_batch_result("dev1", "timing", "test_ticks.py") is None

    def test_cache_and_retrieve_batch_result(self) -> None:
        """Cached batch results should be retrievable."""
        cache = pytest_device._TransportCache()
        cache.cache_batch_result(
            "dev1", "timing", "test_ticks.py", "parsed", "raw output",
        )
        result = cache.get_batch_result("dev1", "timing", "test_ticks.py")
        assert result == ("parsed", "raw output")

    def test_batch_result_separate_per_device(self) -> None:
        """Batch results should be keyed per device."""
        cache = pytest_device._TransportCache()
        cache.cache_batch_result(
            "dev1", "timing", "test_ticks.py", "result_1", "output_1",
        )
        assert cache.get_batch_result("dev2", "timing", "test_ticks.py") is None

    def test_batch_result_separate_per_file(self) -> None:
        """Batch results should be keyed per test file."""
        cache = pytest_device._TransportCache()
        cache.cache_batch_result(
            "dev1", "timing", "test_ticks.py", "result_1", "output_1",
        )
        assert cache.get_batch_result("dev1", "timing", "test_heartbeat.py") is None

    def test_batch_result_caches_failure(self) -> None:
        """A None parsed result (failure) should be cached and retrievable."""
        cache = pytest_device._TransportCache()
        cache.cache_batch_result(
            "dev1", "timing", "test_ticks.py", None, "connection error",
        )
        result = cache.get_batch_result("dev1", "timing", "test_ticks.py")
        assert result == (None, "connection error")

    def test_get_transport_creates_and_caches(self) -> None:
        """get_transport should create a transport and reuse it."""
        from chumicro_device_transport.testing import FakeTransport

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

        # Monkey-patch _create_transport to avoid real hardware.
        original = pytest_device._create_transport
        pytest_device._create_transport = fake_create
        try:
            transport_a = cache.get_transport(device, None)
            transport_b = cache.get_transport(device, None)
            assert transport_a is transport_b
            assert len(calls) == 1
        finally:
            pytest_device._create_transport = original

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
        from chumicro_device_transport.testing import FakeTransport

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
        from chumicro_device_transport.testing import FakeTransport

        cache = pytest_device._TransportCache()
        cache.mark_staged("cp_dev", "timing", "test_heartbeat.py")
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
        from chumicro_device_transport.testing import FakeTransport

        cache = pytest_device._TransportCache()
        cache.mark_staged("cp_dev", "timing", "test_heartbeat.py")
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
        from chumicro_device_transport.testing import FakeTransport

        cache = pytest_device._TransportCache()
        cache.mark_staged("cp_dev", "timing", "test_heartbeat.py")
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

    def test_false_for_micropython_mount_mode(self) -> None:
        """MicroPython already gets clean execution without this reset path."""
        from chumicro_device_transport.testing import FakeTransport

        cache = pytest_device._TransportCache()
        cache.mark_staged("mp_dev", "timing", "test_heartbeat.py")
        device = DeviceEntry(
            identifier="mp_dev",
            runtime="micropython",
            address="/dev/ttyUSB0",
        )
        transport = FakeTransport(mode="mount")

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
