"""Tests for device_testing — device test orchestration."""

from __future__ import annotations

import device_testing
from device_config import DeviceEntry


class TestBuildBootstrap:
    """Tests for build_bootstrap."""

    def test_generates_valid_python(self) -> None:
        """The bootstrap should be syntactically valid Python."""
        script = device_testing.build_bootstrap("test_example.py")
        compile(script, "<bootstrap>", "exec")

    def test_includes_test_filename(self) -> None:
        """The bootstrap should reference the test file."""
        script = device_testing.build_bootstrap("test_heartbeat.py")
        assert "test_heartbeat.py" in script

    def test_includes_name_filter_when_set(self) -> None:
        """The bootstrap should pass the name filter to run_module."""
        script = device_testing.build_bootstrap("test_x.py", name_filter="alpha")
        assert "'alpha'" in script

    def test_name_filter_none_by_default(self) -> None:
        """The bootstrap should pass None when no filter is set."""
        script = device_testing.build_bootstrap("test_x.py")
        assert "name_filter=None" in script


class TestDiscoverFunctionalTests:
    """Tests for discover_functional_tests."""

    def test_discovers_existing_tests(self) -> None:
        """Should find the timing functional test that exists."""
        plan = device_testing.discover_functional_tests()
        library_names = [name for name, _, _ in plan]
        assert "timing" in library_names

    def test_library_filter(self) -> None:
        """Should limit to the specified library."""
        plan = device_testing.discover_functional_tests(library="timing")
        assert all(name == "timing" for name, _, _ in plan)

    def test_nonexistent_library_returns_empty(self) -> None:
        """A library with no functional tests should return empty."""
        plan = device_testing.discover_functional_tests(library="nonexistent_lib_xyz")
        assert plan == []

    def test_test_filter(self) -> None:
        """Should filter test files by name substring."""
        plan = device_testing.discover_functional_tests(
            library="timing", test_filter="heartbeat"
        )
        if plan:
            for _, _, test_files in plan:
                assert all("heartbeat" in path.name for path in test_files)


class TestCollectSourceDirs:
    """Tests for collect_source_dirs."""

    def test_primary_source_is_first(self) -> None:
        """The primary source dir should be the first element."""
        from workspace import ROOT

        primary = ROOT / "libraries" / "timing" / "src"
        result = device_testing.collect_source_dirs(primary)
        assert result[0] == primary

    def test_includes_other_libraries(self) -> None:
        """Other library source dirs should be included."""
        from workspace import ROOT

        primary = ROOT / "libraries" / "timing" / "src"
        result = device_testing.collect_source_dirs(primary)
        assert len(result) >= 3


class TestDeviceOrchestration:
    """Tests for the top-level test_device orchestration."""

    def test_missing_config_returns_2(self, monkeypatch, tmp_path) -> None:
        """Should return 2 when devices.yml is missing."""
        monkeypatch.setenv("CHUMICRO_DEVICES", str(tmp_path / "nope.yml"))
        result = device_testing.test_device()
        assert result == 2

    def test_no_matching_devices_returns_2(
        self, monkeypatch, tmp_path
    ) -> None:
        """Should return 2 when no devices match the filter."""
        devices_file = tmp_path / "devices.yml"
        devices_file.write_text(
            "devices:\n"
            "  - id: mp-1\n"
            "    runtime: micropython\n"
            "    address: /dev/null\n"
        )
        monkeypatch.setenv("CHUMICRO_DEVICES", str(devices_file))
        result = device_testing.test_device(device="nonexistent")
        assert result == 2


class TestCreateTransport:
    """Tests for _create_transport deploy mode routing."""

    def _make_device_entry(
        self,
        runtime: str = "micropython",
        **kwargs,
    ) -> DeviceEntry:
        """Create a DeviceEntry for testing."""
        return DeviceEntry(
            identifier="test-board",
            runtime=runtime,
            address="/dev/null",
            **kwargs,
        )

    def test_micropython_ram_uses_mount_mode(self) -> None:
        """RAM deploy mode should map to mount for MicroPython."""
        entry = self._make_device_entry(runtime="micropython")
        transport = device_testing._create_transport(entry, deploy_mode="ram")
        assert transport.mode == "mount"

    def test_micropython_flash_uses_copy_mode(self) -> None:
        """Flash deploy mode should map to copy for MicroPython."""
        entry = self._make_device_entry(runtime="micropython")
        transport = device_testing._create_transport(entry, deploy_mode="flash")
        assert transport.mode == "copy"

    def test_circuitpython_ram_mode(self) -> None:
        """RAM deploy mode should pass ram to CircuitPython transport."""
        entry = self._make_device_entry(runtime="circuitpython")
        transport = device_testing._create_transport(entry, deploy_mode="ram")
        assert transport.mode == "ram"

    def test_circuitpython_flash_mode(self) -> None:
        """Flash deploy mode should pass flash to CircuitPython transport."""
        entry = self._make_device_entry(
            runtime="circuitpython",
            circuitpy_drive_path="/Volumes/CIRCUITPY",
        )
        transport = device_testing._create_transport(entry, deploy_mode="flash")
        assert transport.mode == "flash"
        assert transport.circuitpy_drive_path == "/Volumes/CIRCUITPY"

    def test_unsupported_runtime_raises(self) -> None:
        """Unsupported runtime should raise ValueError."""
        import pytest

        entry = self._make_device_entry(runtime="unknown")
        # Override runtime since DeviceEntry doesn't validate.
        entry.runtime = "unknown"
        with pytest.raises(ValueError, match="Unsupported runtime"):
            device_testing._create_transport(entry)

    def test_default_deploy_mode_is_ram(self) -> None:
        """Default deploy mode should be ram."""
        entry = self._make_device_entry(runtime="micropython")
        transport = device_testing._create_transport(entry)
        assert transport.mode == "mount"


class TestBuildDeviceBootstrap:
    """Tests for _build_device_bootstrap mode routing."""

    def test_circuitpython_ram_uses_inline_bootstrap(self, tmp_path) -> None:
        """CP ram mode should use inline bootstrap with module injection."""
        entry = DeviceEntry(
            identifier="cp-board",
            runtime="circuitpython",
            address="/dev/null",
        )

        class FakeTransport:
            mode = "ram"
            staged_sources = [("chumicro_timing", "# init")]

        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok(): pass")

        bootstrap = device_testing._build_device_bootstrap(
            entry, FakeTransport(), test_file, None,
        )
        # Inline bootstrap uses _inject_module.
        assert "_inject_module" in bootstrap

    def test_circuitpython_flash_uses_standard_bootstrap(
        self, tmp_path,
    ) -> None:
        """CP flash mode should use standard import-based bootstrap."""
        entry = DeviceEntry(
            identifier="cp-board",
            runtime="circuitpython",
            address="/dev/null",
        )

        class FakeTransport:
            mode = "flash"
            staged_sources = []

        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok(): pass")

        bootstrap = device_testing._build_device_bootstrap(
            entry, FakeTransport(), test_file, None,
        )
        # Standard bootstrap uses import, not _inject_module.
        assert "_inject_module" not in bootstrap
        assert "run_module" in bootstrap

    def test_micropython_uses_standard_bootstrap(self, tmp_path) -> None:
        """MicroPython should always use standard import-based bootstrap."""
        entry = DeviceEntry(
            identifier="mp-board",
            runtime="micropython",
            address="/dev/null",
        )

        class FakeTransport:
            mode = "mount"
            staged_sources = []

        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok(): pass")

        bootstrap = device_testing._build_device_bootstrap(
            entry, FakeTransport(), test_file, None,
        )
        assert "_inject_module" not in bootstrap
        assert "run_module" in bootstrap
