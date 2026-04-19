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


class TestTransportCache:
    """Tests for the _TransportCache helper."""

    def test_needs_staging_initially(self) -> None:
        """A fresh cache should report staging needed."""
        cache = pytest_device._TransportCache()
        assert cache.needs_staging("dev1", "timing") is True

    def test_mark_staged_clears_need(self) -> None:
        """After marking staged, needs_staging returns False."""
        cache = pytest_device._TransportCache()
        cache.mark_staged("dev1", "timing")
        assert cache.needs_staging("dev1", "timing") is False

    def test_different_library_needs_staging(self) -> None:
        """A different library should still need staging."""
        cache = pytest_device._TransportCache()
        cache.mark_staged("dev1", "timing")
        assert cache.needs_staging("dev1", "runner") is True

    def test_different_device_needs_staging(self) -> None:
        """A different device should still need staging."""
        cache = pytest_device._TransportCache()
        cache.mark_staged("dev1", "timing")
        assert cache.needs_staging("dev2", "timing") is True

    def test_disconnect_all_clears_state(self) -> None:
        """disconnect_all should clear all cached state."""
        cache = pytest_device._TransportCache()
        cache.mark_staged("dev1", "timing")
        cache.disconnect_all()
        assert cache.needs_staging("dev1", "timing") is True

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


class TestEnvVarConstants:
    """Tests for environment variable names."""

    def test_runtime_env_var(self) -> None:
        """The runtime env var should match the documented convention."""
        assert pytest_device.RUNTIME_ENV_VAR == "CHUMICRO_DEVICE_RUNTIME"

    def test_device_id_env_var(self) -> None:
        """The device ID env var should match the documented convention."""
        assert pytest_device.DEVICE_ID_ENV_VAR == "CHUMICRO_DEVICE_ID"

    def test_deploy_mode_env_var(self) -> None:
        """The deploy mode env var should match the documented convention."""
        assert pytest_device.DEPLOY_MODE_ENV_VAR == "CHUMICRO_DEPLOY_MODE"


class TestLoadTargetDevice:
    """Tests for _load_target_device."""

    def test_skips_when_no_devices_file(self, monkeypatch, tmp_path) -> None:
        """Should skip with setup instructions when devices.yml is missing."""
        monkeypatch.delenv("CHUMICRO_DEVICE_RUNTIME", raising=False)
        monkeypatch.delenv("CHUMICRO_DEVICE_ID", raising=False)
        # Point to a nonexistent file.
        monkeypatch.setenv("CHUMICRO_DEVICES", str(tmp_path / "nope.yml"))
        with pytest.raises(pytest.skip.Exception, match="No devices.yml found"):
            pytest_device._load_target_device()

    def test_skips_when_no_devices_match_filter(self, monkeypatch, tmp_path) -> None:
        """Should skip when env var filters exclude all devices."""
        devices_file = tmp_path / "devices.yml"
        devices_file.write_text(
            "devices:\n"
            "  - id: board1\n"
            "    runtime: micropython\n"
            "    address: /dev/ttyUSB0\n"
        )
        monkeypatch.setenv("CHUMICRO_DEVICES", str(devices_file))
        monkeypatch.setenv("CHUMICRO_DEVICE_RUNTIME", "circuitpython")
        monkeypatch.delenv("CHUMICRO_DEVICE_ID", raising=False)
        with pytest.raises(pytest.skip.Exception, match="No device matches"):
            pytest_device._load_target_device()

    def test_returns_first_device(self, monkeypatch, tmp_path) -> None:
        """Should return the first device when no filters are set."""
        devices_file = tmp_path / "devices.yml"
        devices_file.write_text(
            "devices:\n"
            "  - id: board1\n"
            "    runtime: micropython\n"
            "    address: /dev/ttyUSB0\n"
            "  - id: board2\n"
            "    runtime: circuitpython\n"
            "    address: /dev/ttyUSB1\n"
        )
        monkeypatch.setenv("CHUMICRO_DEVICES", str(devices_file))
        monkeypatch.delenv("CHUMICRO_DEVICE_RUNTIME", raising=False)
        monkeypatch.delenv("CHUMICRO_DEVICE_ID", raising=False)
        device = pytest_device._load_target_device()
        assert device.identifier == "board1"

    def test_filters_by_runtime(self, monkeypatch, tmp_path) -> None:
        """Should respect CHUMICRO_DEVICE_RUNTIME filter."""
        devices_file = tmp_path / "devices.yml"
        devices_file.write_text(
            "devices:\n"
            "  - id: mp_board\n"
            "    runtime: micropython\n"
            "    address: /dev/ttyUSB0\n"
            "  - id: cp_board\n"
            "    runtime: circuitpython\n"
            "    address: /dev/ttyUSB1\n"
        )
        monkeypatch.setenv("CHUMICRO_DEVICES", str(devices_file))
        monkeypatch.setenv("CHUMICRO_DEVICE_RUNTIME", "circuitpython")
        monkeypatch.delenv("CHUMICRO_DEVICE_ID", raising=False)
        device = pytest_device._load_target_device()
        assert device.identifier == "cp_board"

    def test_filters_by_device_id(self, monkeypatch, tmp_path) -> None:
        """Should respect CHUMICRO_DEVICE_ID filter."""
        devices_file = tmp_path / "devices.yml"
        devices_file.write_text(
            "devices:\n"
            "  - id: board_a\n"
            "    runtime: micropython\n"
            "    address: /dev/ttyUSB0\n"
            "  - id: board_b\n"
            "    runtime: micropython\n"
            "    address: /dev/ttyUSB1\n"
        )
        monkeypatch.setenv("CHUMICRO_DEVICES", str(devices_file))
        monkeypatch.delenv("CHUMICRO_DEVICE_RUNTIME", raising=False)
        monkeypatch.setenv("CHUMICRO_DEVICE_ID", "board_b")
        device = pytest_device._load_target_device()
        assert device.identifier == "board_b"


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
