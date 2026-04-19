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

    def test_test_filter_matches_function_name(self) -> None:
        """Function-name filters should include the containing test file."""
        plan = device_testing.discover_functional_tests(
            library="timing", test_filter="non_negative"
        )
        assert len(plan) == 1
        _library_name, _source_dir, test_files = plan[0]
        assert [path.name for path in test_files] == ["test_ticks_arithmetic.py"]

    def test_test_filter_non_matching_function_returns_empty(self) -> None:
        """A filter matching neither filename nor function names should exclude the file."""
        plan = device_testing.discover_functional_tests(
            library="timing", test_filter="definitely_not_a_real_test_name"
        )
        assert plan == []


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
        result = device_testing.test_device(micropython_device="nonexistent")
        assert result == 2

    def test_no_filters_use_devices_yml_defaults(
        self, monkeypatch, tmp_path,
    ) -> None:
        """Bare CLI runs should target the defaults-selected device(s)."""
        devices_file = tmp_path / "devices.yml"
        devices_file.write_text(
            "defaults:\n"
            "  micropython: mp-default\n"
            "  circuitpython: cp-default\n"
            "  ide_runtime: both\n"
            "devices:\n"
            "  - id: mp-other\n"
            "    runtime: micropython\n"
            "    address: /dev/ttyUSB0\n"
            "  - id: mp-default\n"
            "    runtime: micropython\n"
            "    address: /dev/ttyUSB1\n"
            "  - id: cp-default\n"
            "    runtime: circuitpython\n"
            "    address: /dev/cu.usbmodem1\n"
        )
        monkeypatch.setenv("CHUMICRO_DEVICES", str(devices_file))

        selected_device_ids: list[str] = []

        def fake_run_tests_on_device(
            device_entry,
            test_plan,
            harness_source,
            test_filter,
            deploy_mode=None,
        ):
            selected_device_ids.append(device_entry.identifier)
            return 1, 0, 0

        monkeypatch.setattr(
            device_testing,
            "discover_functional_tests",
            lambda library=None, test_filter=None: [
                (
                    "timing",
                    device_testing.ROOT / "libraries" / "timing" / "src",
                    [
                        device_testing.ROOT
                        / "libraries"
                        / "timing"
                        / "functional_tests"
                        / "test_heartbeat.py",
                    ],
                ),
            ],
        )
        monkeypatch.setattr(
            device_testing, "_run_tests_on_device", fake_run_tests_on_device,
        )

        result = device_testing.test_device()

        assert result == 0
        assert selected_device_ids == ["mp-default", "cp-default"]

    def test_runtime_filter_overrides_defaults(
        self, monkeypatch, tmp_path,
    ) -> None:
        """Explicit runtime filters should change the runtime set, not fan out to every device."""
        devices_file = tmp_path / "devices.yml"
        devices_file.write_text(
            "defaults:\n"
            "  micropython: mp-two\n"
            "  circuitpython: cp-default\n"
            "  ide_runtime: circuitpython\n"
            "devices:\n"
            "  - id: mp-one\n"
            "    runtime: micropython\n"
            "    address: /dev/ttyUSB0\n"
            "  - id: mp-two\n"
            "    runtime: micropython\n"
            "    address: /dev/ttyUSB1\n"
            "  - id: cp-default\n"
            "    runtime: circuitpython\n"
            "    address: /dev/cu.usbmodem1\n"
        )
        monkeypatch.setenv("CHUMICRO_DEVICES", str(devices_file))

        selected_device_ids: list[str] = []

        def fake_run_tests_on_device(
            device_entry,
            test_plan,
            harness_source,
            test_filter,
            deploy_mode=None,
        ):
            selected_device_ids.append(device_entry.identifier)
            return 1, 0, 0

        monkeypatch.setattr(
            device_testing,
            "discover_functional_tests",
            lambda library=None, test_filter=None: [
                (
                    "timing",
                    device_testing.ROOT / "libraries" / "timing" / "src",
                    [
                        device_testing.ROOT
                        / "libraries"
                        / "timing"
                        / "functional_tests"
                        / "test_heartbeat.py",
                    ],
                ),
            ],
        )
        monkeypatch.setattr(
            device_testing, "_run_tests_on_device", fake_run_tests_on_device,
        )

        result = device_testing.test_device(runtime="micropython")

        assert result == 0
        assert selected_device_ids == ["mp-two"]

    def test_explicit_both_runtime_matches_omission(
        self, monkeypatch, tmp_path,
    ) -> None:
        """runtime='both' should override defaults.ide_runtime but keep default IDs."""
        devices_file = tmp_path / "devices.yml"
        devices_file.write_text(
            "defaults:\n"
            "  micropython: mp-default\n"
            "  circuitpython: cp-default\n"
            "  ide_runtime: micropython\n"
            "devices:\n"
            "  - id: mp-default\n"
            "    runtime: micropython\n"
            "    address: /dev/ttyUSB0\n"
            "  - id: cp-default\n"
            "    runtime: circuitpython\n"
            "    address: /dev/cu.usbmodem1\n"
        )
        monkeypatch.setenv("CHUMICRO_DEVICES", str(devices_file))

        selected_device_ids: list[str] = []

        def fake_run_tests_on_device(
            device_entry,
            test_plan,
            harness_source,
            test_filter,
            deploy_mode=None,
        ):
            selected_device_ids.append(device_entry.identifier)
            return 1, 0, 0

        monkeypatch.setattr(
            device_testing,
            "discover_functional_tests",
            lambda library=None, test_filter=None: [
                (
                    "timing",
                    device_testing.ROOT / "libraries" / "timing" / "src",
                    [
                        device_testing.ROOT
                        / "libraries"
                        / "timing"
                        / "functional_tests"
                        / "test_heartbeat.py",
                    ],
                ),
            ],
        )
        monkeypatch.setattr(
            device_testing, "_run_tests_on_device", fake_run_tests_on_device,
        )

        result = device_testing.test_device(runtime="both")

        assert result == 0
        assert selected_device_ids == ["mp-default", "cp-default"]

    def test_runtime_specific_device_overrides_replace_defaults(
        self, monkeypatch, tmp_path,
    ) -> None:
        """Per-runtime CLI overrides should replace only their matching default IDs."""
        devices_file = tmp_path / "devices.yml"
        devices_file.write_text(
            "defaults:\n"
            "  micropython: mp-default\n"
            "  circuitpython: cp-default\n"
            "  ide_runtime: both\n"
            "devices:\n"
            "  - id: mp-default\n"
            "    runtime: micropython\n"
            "    address: /dev/ttyUSB0\n"
            "  - id: mp-alt\n"
            "    runtime: micropython\n"
            "    address: /dev/ttyUSB1\n"
            "  - id: cp-default\n"
            "    runtime: circuitpython\n"
            "    address: /dev/cu.usbmodem1\n"
            "  - id: cp-alt\n"
            "    runtime: circuitpython\n"
            "    address: /dev/cu.usbmodem2\n"
        )
        monkeypatch.setenv("CHUMICRO_DEVICES", str(devices_file))

        selected_device_ids: list[str] = []

        def fake_run_tests_on_device(
            device_entry,
            test_plan,
            harness_source,
            test_filter,
            deploy_mode=None,
        ):
            selected_device_ids.append(device_entry.identifier)
            return 1, 0, 0

        monkeypatch.setattr(
            device_testing,
            "discover_functional_tests",
            lambda library=None, test_filter=None: [
                (
                    "timing",
                    device_testing.ROOT / "libraries" / "timing" / "src",
                    [
                        device_testing.ROOT
                        / "libraries"
                        / "timing"
                        / "functional_tests"
                        / "test_heartbeat.py",
                    ],
                ),
            ],
        )
        monkeypatch.setattr(
            device_testing, "_run_tests_on_device", fake_run_tests_on_device,
        )

        result = device_testing.test_device(
            runtime="both",
            micropython_device="mp-alt",
            circuitpython_device="cp-alt",
        )

        assert result == 0
        assert selected_device_ids == ["mp-alt", "cp-alt"]

    def test_runtime_specific_override_leaves_other_runtime_on_default(
        self, monkeypatch, tmp_path,
    ) -> None:
        """Overriding one runtime should leave the other runtime on its default board."""
        devices_file = tmp_path / "devices.yml"
        devices_file.write_text(
            "defaults:\n"
            "  micropython: mp-default\n"
            "  circuitpython: cp-default\n"
            "  ide_runtime: both\n"
            "devices:\n"
            "  - id: mp-default\n"
            "    runtime: micropython\n"
            "    address: /dev/ttyUSB0\n"
            "  - id: cp-default\n"
            "    runtime: circuitpython\n"
            "    address: /dev/cu.usbmodem1\n"
            "  - id: cp-alt\n"
            "    runtime: circuitpython\n"
            "    address: /dev/cu.usbmodem2\n"
        )
        monkeypatch.setenv("CHUMICRO_DEVICES", str(devices_file))

        selected_device_ids: list[str] = []

        def fake_run_tests_on_device(
            device_entry,
            test_plan,
            harness_source,
            test_filter,
            deploy_mode=None,
        ):
            selected_device_ids.append(device_entry.identifier)
            return 1, 0, 0

        monkeypatch.setattr(
            device_testing,
            "discover_functional_tests",
            lambda library=None, test_filter=None: [
                (
                    "timing",
                    device_testing.ROOT / "libraries" / "timing" / "src",
                    [
                        device_testing.ROOT
                        / "libraries"
                        / "timing"
                        / "functional_tests"
                        / "test_heartbeat.py",
                    ],
                ),
            ],
        )
        monkeypatch.setattr(
            device_testing, "_run_tests_on_device", fake_run_tests_on_device,
        )

        result = device_testing.test_device(
            circuitpython_device="cp-alt",
        )

        assert result == 0
        assert selected_device_ids == ["mp-default", "cp-alt"]


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
        """Default deploy mode (from device entry) should be ram → mount."""
        entry = self._make_device_entry(runtime="micropython")
        transport = device_testing._create_transport(entry)
        assert transport.mode == "mount"

    def test_device_entry_deploy_mode_flash(self) -> None:
        """Device entry deploy_mode=flash should apply when CLI is None."""
        entry = self._make_device_entry(
            runtime="micropython", deploy_mode="flash",
        )
        transport = device_testing._create_transport(entry)
        assert transport.mode == "copy"

    def test_cli_overrides_device_entry_deploy_mode(self) -> None:
        """CLI deploy_mode should override the device entry default."""
        entry = self._make_device_entry(
            runtime="micropython", deploy_mode="flash",
        )
        transport = device_testing._create_transport(entry, deploy_mode="ram")
        assert transport.mode == "mount"

    def test_circuitpython_device_entry_flash(self) -> None:
        """CP device entry deploy_mode=flash should apply when CLI is None."""
        entry = self._make_device_entry(
            runtime="circuitpython",
            deploy_mode="flash",
            circuitpy_drive_path="/Volumes/CIRCUITPY",
        )
        transport = device_testing._create_transport(entry)
        assert transport.mode == "flash"


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
        # Inline bootstrap uses _populate_module.
        assert "_populate_module" in bootstrap

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
        # Standard bootstrap uses import, not _populate_module.
        assert "_populate_module" not in bootstrap
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
        assert "_make_lazy_module" not in bootstrap
        assert "_populate_module" not in bootstrap
        assert "run_module" in bootstrap


class TestResolveLibrarySourceDirs:
    """Tests for _resolve_library_source_dirs."""

    def test_resolves_chumicro_imports_from_test_files(self) -> None:
        """Functional test imports should stage additional ChuMicro libraries."""
        runner_dir = device_testing.ROOT / "libraries" / "runner"
        integration_test = (
            device_testing.ROOT
            / "libraries"
            / "runner"
            / "functional_tests"
            / "test_integration.py"
        )

        result = device_testing._resolve_library_source_dirs(
            runner_dir, test_files=[integration_test],
        )

        msgpack_source = (
            device_testing.ROOT / "libraries" / "msgpack" / "src"
        )
        assert msgpack_source in result

    def test_includes_own_source_dir(self) -> None:
        """Should include the library's own src/ directory."""
        timing_dir = device_testing.ROOT / "libraries" / "timing"
        result = device_testing._resolve_library_source_dirs(timing_dir)
        assert timing_dir / "src" in result

    def test_includes_dependency_source_dirs(self) -> None:
        """Runner depends on timing — both src/ dirs should appear."""
        runner_dir = device_testing.ROOT / "libraries" / "runner"
        result = device_testing._resolve_library_source_dirs(runner_dir)
        timing_source = device_testing.ROOT / "libraries" / "timing" / "src"
        runner_source = runner_dir / "src"
        assert timing_source in result
        assert runner_source in result

    def test_dependency_comes_before_library(self) -> None:
        """Dependencies should appear before the library itself."""
        runner_dir = device_testing.ROOT / "libraries" / "runner"
        result = device_testing._resolve_library_source_dirs(runner_dir)
        timing_source = device_testing.ROOT / "libraries" / "timing" / "src"
        runner_source = runner_dir / "src"
        assert result.index(timing_source) < result.index(runner_source)

    def test_test_import_dependency_comes_before_library(self) -> None:
        """Test-imported libraries should stage before the library under test."""
        runner_dir = device_testing.ROOT / "libraries" / "runner"
        integration_test = (
            device_testing.ROOT
            / "libraries"
            / "runner"
            / "functional_tests"
            / "test_integration.py"
        )

        result = device_testing._resolve_library_source_dirs(
            runner_dir, test_files=[integration_test],
        )

        msgpack_source = (
            device_testing.ROOT / "libraries" / "msgpack" / "src"
        )
        runner_source = runner_dir / "src"
        assert result.index(msgpack_source) < result.index(runner_source)

    def test_library_without_dependencies(self) -> None:
        """A library with no deps should return only its own src/."""
        timing_dir = device_testing.ROOT / "libraries" / "timing"
        result = device_testing._resolve_library_source_dirs(timing_dir)
        assert result == [timing_dir / "src"]

    def test_nonexistent_library_returns_empty(self, tmp_path) -> None:
        """A nonexistent library dir should return an empty list."""
        result = device_testing._resolve_library_source_dirs(tmp_path / "nope")
        assert result == []

    def test_no_duplicate_entries(self) -> None:
        """Source dirs should not appear more than once."""
        runner_dir = device_testing.ROOT / "libraries" / "runner"
        result = device_testing._resolve_library_source_dirs(runner_dir)
        assert len(result) == len(set(result))
