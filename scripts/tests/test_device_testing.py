"""Tests for device_testing — device test orchestration."""

from __future__ import annotations

import device_testing


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

