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

    def test_file_filter_matches_file_names_only(self) -> None:
        """``file_filter`` should include every file whose name matches the substring."""
        plan = device_testing.discover_functional_tests(
            library="timing", file_filter="heartbeat",
        )
        if plan:
            for _, _, test_files in plan:
                assert all("heartbeat" in path.name for path in test_files)

    def test_function_filter_restricts_to_files_with_matching_functions(self) -> None:
        """``function_filter`` should keep only files that define a matching function.

        Critical regression: the old combined filter would also match
        against filenames and let irrelevant files slip into the plan
        purely on function-name substrings.  ``function_filter`` is now
        strictly function-only.
        """
        plan = device_testing.discover_functional_tests(
            library="timing", function_filter="non_negative",
        )
        assert len(plan) == 1
        _library_name, _source_dir, test_files = plan[0]
        assert [path.name for path in test_files] == ["test_ticks_arithmetic.py"]

    def test_function_filter_does_not_match_file_names(self) -> None:
        """Using a function filter whose text appears only in a filename excludes the file.

        This is the explicit contract with the old behavior: passing
        ``function_filter="heartbeat"`` must not include a file just
        because the filename contains "heartbeat" — only function-name
        matches count.
        """
        plan = device_testing.discover_functional_tests(
            library="timing",
            function_filter="this_function_name_does_not_exist_anywhere",
        )
        assert plan == []

    def test_file_and_function_filters_compose(self) -> None:
        """Both filters apply as an AND — file must match and contain a matching function."""
        plan = device_testing.discover_functional_tests(
            library="timing",
            file_filter="heartbeat",
            function_filter="definitely_not_a_real_test_name",
        )
        # File name matches but no function matches → excluded.
        assert plan == []

    def test_library_scope_binds_file_and_function_filters(self) -> None:
        """Filters apply within the selected library only.

        A function name that exists in another library must not drag
        that library into a ``--library timing`` run.
        """
        plan = device_testing.discover_functional_tests(
            library="timing",
            function_filter="test_",  # matches in every library
        )
        library_names = {library_name for library_name, _, _ in plan}
        # Even with a very permissive function filter, only ``timing``
        # is in the plan — the library scope binds everything else.
        assert library_names == {"timing"}


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

    def test_no_matching_files_with_filter_returns_2(
        self, monkeypatch, tmp_path, capsys,
    ) -> None:
        """A filter that matches nothing must exit 2 (not silently pass).

        Regression: bare invocations on an empty workspace return 0
        (nothing to run, nothing to fail).  But when the user explicitly
        filters with ``--library`` / ``--file`` / ``--test``, a zero
        plan means the filter was wrong — exit 2 so CI and scripts
        don't mistake a typo for a clean run.
        """
        devices_file = tmp_path / "devices.yml"
        devices_file.write_text(
            "defaults:\n"
            "  micropython: mp-one\n"
            "  ide_runtime: micropython\n"
            "devices:\n"
            "  - id: mp-one\n"
            "    runtime: micropython\n"
            "    address: /dev/ttyUSB0\n"
        )
        monkeypatch.setenv("CHUMICRO_DEVICES", str(devices_file))
        monkeypatch.setattr(
            device_testing, "discover_functional_tests",
            lambda library=None, file_filter=None, function_filter=None: [],
        )

        result = device_testing.test_device(
            library="timing", function_filter="definitely_not_a_test",
        )

        captured = capsys.readouterr()
        assert result == 2
        assert "No functional tests matched" in captured.out
        assert "--library timing" in captured.out
        assert "--function definitely_not_a_test" in captured.out

    def test_empty_plan_without_filters_still_returns_0(
        self, monkeypatch, tmp_path,
    ) -> None:
        """No filter + empty plan remains a benign exit 0 (fresh-project case)."""
        devices_file = tmp_path / "devices.yml"
        devices_file.write_text(
            "defaults:\n"
            "  micropython: mp-one\n"
            "  ide_runtime: micropython\n"
            "devices:\n"
            "  - id: mp-one\n"
            "    runtime: micropython\n"
            "    address: /dev/ttyUSB0\n"
        )
        monkeypatch.setenv("CHUMICRO_DEVICES", str(devices_file))
        monkeypatch.setattr(
            device_testing, "discover_functional_tests",
            lambda library=None, file_filter=None, function_filter=None: [],
        )

        result = device_testing.test_device()

        assert result == 0

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
            function_filter,
            deploy_mode=None,
        ):
            selected_device_ids.append(device_entry.identifier)
            return device_testing.DeviceRunResult(
                device=device_entry, passed=1, failed=0, errors=0,
                implementation=None, deploy_mode="ram",
            )

        monkeypatch.setattr(
            device_testing,
            "discover_functional_tests",
            lambda library=None, file_filter=None, function_filter=None: [
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
            function_filter,
            deploy_mode=None,
        ):
            selected_device_ids.append(device_entry.identifier)
            return device_testing.DeviceRunResult(
                device=device_entry, passed=1, failed=0, errors=0,
                implementation=None, deploy_mode="ram",
            )

        monkeypatch.setattr(
            device_testing,
            "discover_functional_tests",
            lambda library=None, file_filter=None, function_filter=None: [
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
            function_filter,
            deploy_mode=None,
        ):
            selected_device_ids.append(device_entry.identifier)
            return device_testing.DeviceRunResult(
                device=device_entry, passed=1, failed=0, errors=0,
                implementation=None, deploy_mode="ram",
            )

        monkeypatch.setattr(
            device_testing,
            "discover_functional_tests",
            lambda library=None, file_filter=None, function_filter=None: [
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
            function_filter,
            deploy_mode=None,
        ):
            selected_device_ids.append(device_entry.identifier)
            return device_testing.DeviceRunResult(
                device=device_entry, passed=1, failed=0, errors=0,
                implementation=None, deploy_mode="ram",
            )

        monkeypatch.setattr(
            device_testing,
            "discover_functional_tests",
            lambda library=None, file_filter=None, function_filter=None: [
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
            function_filter,
            deploy_mode=None,
        ):
            selected_device_ids.append(device_entry.identifier)
            return device_testing.DeviceRunResult(
                device=device_entry, passed=1, failed=0, errors=0,
                implementation=None, deploy_mode="ram",
            )

        monkeypatch.setattr(
            device_testing,
            "discover_functional_tests",
            lambda library=None, file_filter=None, function_filter=None: [
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
    """Tests for create_transport deploy mode routing."""

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
        transport = device_testing.create_transport(entry, deploy_mode="ram")
        assert transport.mode == "mount"

    def test_micropython_flash_uses_copy_mode(self) -> None:
        """Flash deploy mode should map to copy for MicroPython."""
        entry = self._make_device_entry(runtime="micropython")
        transport = device_testing.create_transport(entry, deploy_mode="flash")
        assert transport.mode == "copy"

    def test_circuitpython_ram_mode(self) -> None:
        """RAM deploy mode should pass ram to CircuitPython transport."""
        entry = self._make_device_entry(runtime="circuitpython")
        transport = device_testing.create_transport(entry, deploy_mode="ram")
        assert transport.mode == "ram"

    def test_circuitpython_flash_mode(self) -> None:
        """Flash deploy mode should pass flash to CircuitPython transport."""
        entry = self._make_device_entry(
            runtime="circuitpython",
            circuitpy_drive_path="/Volumes/CIRCUITPY",
        )
        transport = device_testing.create_transport(entry, deploy_mode="flash")
        assert transport.mode == "flash"
        assert transport.circuitpy_drive_path == "/Volumes/CIRCUITPY"

    def test_unsupported_runtime_raises(self) -> None:
        """Unsupported runtime should raise ValueError."""
        import pytest

        entry = self._make_device_entry(runtime="unknown")
        # Override runtime since DeviceEntry doesn't validate.
        entry.runtime = "unknown"
        with pytest.raises(ValueError, match="Unsupported runtime"):
            device_testing.create_transport(entry)

    def test_default_deploy_mode_is_ram(self) -> None:
        """Default deploy mode (from device entry) should be ram → mount."""
        entry = self._make_device_entry(runtime="micropython")
        transport = device_testing.create_transport(entry)
        assert transport.mode == "mount"

    def test_device_entry_deploy_mode_flash(self) -> None:
        """Device entry deploy_mode=flash should apply when CLI is None."""
        entry = self._make_device_entry(
            runtime="micropython", deploy_mode="flash",
        )
        transport = device_testing.create_transport(entry)
        assert transport.mode == "copy"

    def test_cli_overrides_device_entry_deploy_mode(self) -> None:
        """CLI deploy_mode should override the device entry default."""
        entry = self._make_device_entry(
            runtime="micropython", deploy_mode="flash",
        )
        transport = device_testing.create_transport(entry, deploy_mode="ram")
        assert transport.mode == "mount"

    def test_circuitpython_device_entry_flash(self) -> None:
        """CP device entry deploy_mode=flash should apply when CLI is None."""
        entry = self._make_device_entry(
            runtime="circuitpython",
            deploy_mode="flash",
            circuitpy_drive_path="/Volumes/CIRCUITPY",
        )
        transport = device_testing.create_transport(entry)
        assert transport.mode == "flash"


class TestBuildDeviceBootstrap:
    """Tests for build_device_bootstrap mode routing."""

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

            @staticmethod
            def inline_script_budget_bytes() -> int:
                return 32 * 1024

        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok(): pass")

        bootstrap = device_testing.build_device_bootstrap(
            entry, FakeTransport(), test_file, None,
        )
        assert isinstance(bootstrap, list)
        # Inline bootstrap uses _populate_module in one of the chunked scripts.
        assert any("_populate_module" in script for script in bootstrap)

    def test_circuitpython_ram_uses_live_chunk_budget_for_inline_bootstrap(
        self, tmp_path, monkeypatch,
    ) -> None:
        """CP ram mode should pass the transport's live chunk budget through."""
        import chumicro_deploy

        entry = DeviceEntry(
            identifier="cp-board",
            runtime="circuitpython",
            address="/dev/null",
        )

        class FakeTransport:
            mode = "ram"
            staged_sources = [("chumicro_timing", "# init")]

            @staticmethod
            def inline_script_budget_bytes() -> int:
                return 12345

        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok(): pass")
        captured_arguments: dict[str, object] = {}

        def fake_build_circuitpython_bootstrap_scripts(
            staged_sources,
            bootstrap_test_file,
            *,
            name_filter=None,
            max_chunk_size_bytes=0,
        ) -> list[str]:
            captured_arguments["max_chunk_size_bytes"] = max_chunk_size_bytes
            captured_arguments["test_file_name"] = bootstrap_test_file.name
            assert staged_sources == [("chumicro_timing", "# init")]
            assert name_filter is None
            return ["inline bootstrap"]

        monkeypatch.setattr(
            chumicro_deploy,
            "build_circuitpython_bootstrap_scripts",
            fake_build_circuitpython_bootstrap_scripts,
        )

        bootstrap = device_testing.build_device_bootstrap(
            entry, FakeTransport(), test_file, None,
        )

        assert bootstrap == ["inline bootstrap"]
        assert captured_arguments == {
            "max_chunk_size_bytes": 12345,
            "test_file_name": "test_example.py",
        }

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

        bootstrap = device_testing.build_device_bootstrap(
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

        bootstrap = device_testing.build_device_bootstrap(
            entry, FakeTransport(), test_file, None,
        )
        assert "_make_lazy_module" not in bootstrap
        assert "_populate_module" not in bootstrap
        assert "run_module" in bootstrap


class TestResolveLibrarySourceDirs:
    """Tests for resolve_library_source_dirs."""

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

        result = device_testing.resolve_library_source_dirs(
            runner_dir, test_files=[integration_test],
        )

        msgpack_source = (
            device_testing.ROOT / "libraries" / "msgpack" / "src"
        )
        assert msgpack_source in result

    def test_includes_own_source_dir(self) -> None:
        """Should include the library's own src/ directory."""
        timing_dir = device_testing.ROOT / "libraries" / "timing"
        result = device_testing.resolve_library_source_dirs(timing_dir)
        assert timing_dir / "src" in result

    def test_includes_dependency_source_dirs(self) -> None:
        """Runner depends on timing — both src/ dirs should appear."""
        runner_dir = device_testing.ROOT / "libraries" / "runner"
        result = device_testing.resolve_library_source_dirs(runner_dir)
        timing_source = device_testing.ROOT / "libraries" / "timing" / "src"
        runner_source = runner_dir / "src"
        assert timing_source in result
        assert runner_source in result

    def test_dependency_comes_before_library(self) -> None:
        """Dependencies should appear before the library itself."""
        runner_dir = device_testing.ROOT / "libraries" / "runner"
        result = device_testing.resolve_library_source_dirs(runner_dir)
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

        result = device_testing.resolve_library_source_dirs(
            runner_dir, test_files=[integration_test],
        )

        msgpack_source = (
            device_testing.ROOT / "libraries" / "msgpack" / "src"
        )
        runner_source = runner_dir / "src"
        assert result.index(msgpack_source) < result.index(runner_source)


class TestExecuteDeviceBootstrap:
    """Tests for execute_device_bootstrap."""

    def test_runs_chunked_bootstraps_with_execute_scripts(self) -> None:
        """List bootstraps should use execute_scripts when the transport has it."""

        class FakeTransport:
            captured_bootstrap = None

            @staticmethod
            def execute_scripts(bootstrap_scripts):
                FakeTransport.captured_bootstrap = bootstrap_scripts
                return "chunked output"

        result = device_testing.execute_device_bootstrap(
            FakeTransport(), ["chunk-1", "chunk-2"],
        )

        assert result == "chunked output"
        assert FakeTransport.captured_bootstrap == ["chunk-1", "chunk-2"]

    def test_runs_single_bootstraps_with_execute(self) -> None:
        """String bootstraps should continue to use execute()."""

        class FakeTransport:
            captured_bootstrap = None

            @staticmethod
            def execute(bootstrap_script):
                FakeTransport.captured_bootstrap = bootstrap_script
                return "single output"

        result = device_testing.execute_device_bootstrap(
            FakeTransport(), "single bootstrap",
        )

        assert result == "single output"
        assert FakeTransport.captured_bootstrap == "single bootstrap"

    def test_library_without_dependencies(self) -> None:
        """A library with no deps should return only its own src/."""
        timing_dir = device_testing.ROOT / "libraries" / "timing"
        result = device_testing.resolve_library_source_dirs(timing_dir)
        assert result == [timing_dir / "src"]

    def test_nonexistent_library_returns_empty(self, tmp_path) -> None:
        """A nonexistent library dir should return an empty list."""
        result = device_testing.resolve_library_source_dirs(tmp_path / "nope")
        assert result == []

    def test_no_duplicate_entries(self) -> None:
        """Source dirs should not appear more than once."""
        runner_dir = device_testing.ROOT / "libraries" / "runner"
        result = device_testing.resolve_library_source_dirs(runner_dir)
        assert len(result) == len(set(result))


# ---------------------------------------------------------------------------
# Direct tests for _run_tests_on_device — the 150-line orchestration hot path
# ---------------------------------------------------------------------------


class _RecordingTransport:
    """FakeTransport variant that lets each test drive exact orchestration outcomes.

    Exposes the same duck-typed transport surface ``_run_tests_on_device``
    uses (``connect``, ``stage``, ``execute``, ``reset``, ``soft_reset``,
    ``recover``, ``disconnect``, plus the ``mode`` attribute).  Tests
    configure per-method behavior via callables on the instance.
    """

    def __init__(
        self,
        *,
        mode: str = "ram",
        outputs: list[str] | None = None,
        connect_raises: Exception | None = None,
        stage_raises: Exception | None = None,
        execute_raises: Exception | None = None,
        recover_raises: Exception | None = None,
        soft_reset_raises: Exception | None = None,
        reset_raises: Exception | None = None,
    ) -> None:
        self.mode = mode
        # Canned outputs queued for each execute() call.  When exhausted,
        # returns an empty string (which surfaces as "no summary" in
        # _run_tests_on_device).
        self._outputs = list(outputs or [])
        self._connect_raises = connect_raises
        self._stage_raises = stage_raises
        self._execute_raises = execute_raises
        self._recover_raises = recover_raises
        self._soft_reset_raises = soft_reset_raises
        self._reset_raises = reset_raises
        self.calls: list[tuple[str, tuple]] = []
        self.staged_sources: list[tuple[str, str]] = []

    def connect(self) -> None:
        self.calls.append(("connect", ()))
        if self._connect_raises is not None:
            raise self._connect_raises

    def stage(self, source_dirs, test_files, harness_source) -> None:
        self.calls.append(("stage", (source_dirs, test_files, harness_source)))
        if self._stage_raises is not None:
            raise self._stage_raises

    def execute(self, bootstrap_script: str) -> str:
        self.calls.append(("execute", (bootstrap_script,)))
        if self._execute_raises is not None:
            raise self._execute_raises
        if self._outputs:
            return self._outputs.pop(0)
        return ""

    def execute_scripts(self, bootstrap_scripts: list[str]) -> str:
        """Return one canned output per chunked-execute call.

        Mirrors ``CircuitpythonTransport.execute_scripts``: runs the full
        list at once and returns the output for the whole batch (not
        per-script).  Counts as ONE outputs-queue pop so tests can
        reason about per-file behavior the same as regular execute().
        """
        self.calls.append(("execute_scripts", (list(bootstrap_scripts),)))
        if self._execute_raises is not None:
            raise self._execute_raises
        if self._outputs:
            return self._outputs.pop(0)
        return ""

    def inline_script_budget_bytes(self) -> int:
        """Let RAM-mode bootstrap builders chunk to any reasonable size."""
        return 32 * 1024

    def reset(self) -> None:
        self.calls.append(("reset", ()))
        if self._reset_raises is not None:
            raise self._reset_raises

    def soft_reset(self) -> None:
        self.calls.append(("soft_reset", ()))
        if self._soft_reset_raises is not None:
            raise self._soft_reset_raises

    def recover(self) -> None:
        self.calls.append(("recover", ()))
        if self._recover_raises is not None:
            raise self._recover_raises

    def disconnect(self) -> None:
        self.calls.append(("disconnect", ()))


#: A realistic harness summary line with one passing test.
#: ``_run_tests_on_device`` parses this and increments ``passed`` by
#: ``total - failed``.  Format matches result_parser._SUMMARY_PATTERN.
_PASS_OUTPUT = "PASS test_one (0.001s)\nSUMMARY total=1 failed=0 time=0.001s\n"

#: Mixed summary — two tests, one failed.
_MIXED_OUTPUT = (
    "PASS test_one (0.001s)\n"
    "FAIL test_two (0.002s): boom\n"
    "SUMMARY total=2 failed=1 time=0.003s\n"
)

#: Empty output — no SUMMARY line — triggers the "No summary line in output" path.
_NO_SUMMARY_OUTPUT = "PASS test_one (0.001s)\n"


def _circuitpython_device(identifier: str = "cp-1") -> DeviceEntry:
    return DeviceEntry(
        identifier=identifier,
        runtime="circuitpython",
        address="/dev/ttyUSB-cp",
        deploy_mode="ram",
    )


def _micropython_device(identifier: str = "mp-1") -> DeviceEntry:
    return DeviceEntry(
        identifier=identifier,
        runtime="micropython",
        address="/dev/ttyUSB-mp",
        deploy_mode="ram",
    )


def _plan_entry(tmp_path, library_name: str, file_count: int = 1):
    """Build a synthetic (library_name, source_dir, [test_files]) entry."""
    library_dir = tmp_path / library_name
    source_dir = library_dir / "src"
    source_dir.mkdir(parents=True)
    (source_dir / f"chumicro_{library_name}").mkdir()
    (source_dir / f"chumicro_{library_name}" / "__init__.py").write_text("")
    test_files = []
    for file_index in range(file_count):
        test_file = library_dir / "functional_tests" / f"test_{file_index}.py"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("def test_ok(): pass\n")
        test_files.append(test_file)
    return (library_name, source_dir, test_files)


class TestRunTestsOnDevice:
    """Direct tests for the 150-line orchestration hot path."""

    def test_single_library_all_pass(self, tmp_path, monkeypatch) -> None:
        """One library + one file + one passing test → passed=1, failed=0."""
        transport = _RecordingTransport(outputs=[_PASS_OUTPUT])
        monkeypatch.setattr(
            device_testing, "create_transport",
            lambda device_entry, deploy_mode=None: transport,
        )

        plan = [_plan_entry(tmp_path, "alpha")]
        device_result = device_testing._run_tests_on_device(
            _circuitpython_device(),
            plan,
            harness_source=tmp_path / "harness",
            function_filter=None,
        )

        assert (device_result.passed, device_result.failed, device_result.errors) == (1, 0, 0)
        # Transport lifecycle: connect → stage → execute(_scripts) → reset → disconnect.
        call_names = [name for name, _ in transport.calls]
        assert call_names[0] == "connect"
        assert "stage" in call_names
        # CircuitPython RAM mode uses the chunked-execution path; other paths
        # call execute() directly.  Accept either.
        assert "execute" in call_names or "execute_scripts" in call_names
        assert call_names[-2:] == ["reset", "disconnect"]

    def test_connection_failure_returns_one_error_and_skips_rest(
        self, tmp_path, monkeypatch,
    ) -> None:
        """A failed connect short-circuits the whole run with a single error."""
        transport = _RecordingTransport(
            connect_raises=RuntimeError("no device"),
        )
        monkeypatch.setattr(
            device_testing, "create_transport",
            lambda device_entry, deploy_mode=None: transport,
        )

        plan = [_plan_entry(tmp_path, "alpha"), _plan_entry(tmp_path, "beta")]
        device_result = device_testing._run_tests_on_device(
            _circuitpython_device(), plan,
            harness_source=tmp_path / "harness", function_filter=None,
        )

        assert (device_result.passed, device_result.failed, device_result.errors) == (0, 0, 1)
        # No stage / execute after the connect failure.
        names = [name for name, _ in transport.calls]
        assert "stage" not in names
        assert "execute" not in names

    def test_stage_failure_in_non_ram_mode_returns_errors_for_all_files(
        self, tmp_path, monkeypatch,
    ) -> None:
        """Non-RAM deploy modes bulk-stage upfront; a stage failure errors every file."""
        transport = _RecordingTransport(
            mode="copy",
            stage_raises=RuntimeError("mount denied"),
        )
        monkeypatch.setattr(
            device_testing, "create_transport",
            lambda device_entry, deploy_mode=None: transport,
        )

        plan = [
            _plan_entry(tmp_path, "alpha", file_count=2),
            _plan_entry(tmp_path, "beta", file_count=1),
        ]
        # Drain the generator of source dirs (it calls discover_library_dirs);
        # stub it out to avoid hitting the real workspace.
        monkeypatch.setattr(device_testing, "discover_library_dirs", lambda: [])

        device_result = device_testing._run_tests_on_device(
            _micropython_device(), plan,
            harness_source=tmp_path / "harness", function_filter=None,
        )

        # 3 test files total: all become errors.
        assert (device_result.passed, device_result.failed, device_result.errors) == (0, 0, 3)
        names = [name for name, _ in transport.calls]
        assert "disconnect" in names

    def test_soft_reset_fires_between_libraries_for_micropython(
        self, tmp_path, monkeypatch,
    ) -> None:
        """MicroPython soft_resets between library groups so state is clean.

        The persistent-serial ``SerialTransport`` keeps one interpreter
        alive across files, so ``sys.modules`` would accumulate until
        RAM runs out on Tier-2 boards (RP2040 class, 264 KB SRAM).  The
        soft reset is a VM-level Ctrl-D via raw REPL — it does not
        toggle USB, unlike the older ``mpremote reset`` subprocess path.
        """
        transport = _RecordingTransport(
            mode="mount",
            outputs=[_PASS_OUTPUT, _PASS_OUTPUT],
        )
        monkeypatch.setattr(
            device_testing, "create_transport",
            lambda device_entry, deploy_mode=None: transport,
        )
        monkeypatch.setattr(device_testing, "discover_library_dirs", lambda: [])

        plan = [_plan_entry(tmp_path, "alpha"), _plan_entry(tmp_path, "beta")]
        device_testing._run_tests_on_device(
            _micropython_device(), plan,
            harness_source=tmp_path / "harness", function_filter=None,
        )

        # Soft reset happened at least once (between alpha and beta).
        assert "soft_reset" in [name for name, _ in transport.calls]

    def test_soft_reset_fires_between_libraries_for_circuitpython(
        self, tmp_path, monkeypatch,
    ) -> None:
        """CircuitPython soft_resets between library groups so state is clean."""
        transport = _RecordingTransport(
            mode="ram", outputs=[_PASS_OUTPUT, _PASS_OUTPUT],
        )
        monkeypatch.setattr(
            device_testing, "create_transport",
            lambda device_entry, deploy_mode=None: transport,
        )

        plan = [_plan_entry(tmp_path, "alpha"), _plan_entry(tmp_path, "beta")]
        device_testing._run_tests_on_device(
            _circuitpython_device(), plan,
            harness_source=tmp_path / "harness", function_filter=None,
        )

        # Soft reset happened at least once (between alpha and beta).
        assert "soft_reset" in [name for name, _ in transport.calls]

    def test_execute_failure_calls_recover_and_continues(
        self, tmp_path, monkeypatch,
    ) -> None:
        """A failed test execute triggers recover() and lets subsequent files run.

        The cascade-fail protection: without this, a timeout on one file
        would leave the board stuck and every subsequent file would
        cascade-fail.  With recover(), the next file starts clean.
        """
        outputs = [_PASS_OUTPUT]

        class _FailFirstTransport(_RecordingTransport):
            def __init__(self) -> None:
                super().__init__(mode="ram", outputs=outputs)
                self._execute_count = 0

            def execute_scripts(self, bootstrap_scripts: list[str]) -> str:
                self._execute_count += 1
                self.calls.append(("execute_scripts", (list(bootstrap_scripts),)))
                if self._execute_count == 1:
                    raise RuntimeError("timeout on test 1")
                return outputs.pop(0) if outputs else ""

        transport = _FailFirstTransport()
        monkeypatch.setattr(
            device_testing, "create_transport",
            lambda device_entry, deploy_mode=None: transport,
        )

        plan = [_plan_entry(tmp_path, "alpha", file_count=2)]
        device_result = device_testing._run_tests_on_device(
            _circuitpython_device(), plan,
            harness_source=tmp_path / "harness", function_filter=None,
        )

        # First file errored; second passed.
        assert device_result.errors == 1
        assert device_result.passed == 1
        # recover() was called after the exception.
        names = [name for name, _ in transport.calls]
        assert "recover" in names

    def test_recover_failure_aborts_remaining_tests(
        self, tmp_path, monkeypatch,
    ) -> None:
        """If recover() itself fails, remaining tests are skipped with abort."""

        class _FatalTransport(_RecordingTransport):
            def __init__(self) -> None:
                super().__init__(
                    mode="ram",
                    outputs=[],
                    recover_raises=RuntimeError("board is wedged"),
                )
                self._execute_count = 0

            def execute_scripts(self, bootstrap_scripts: list[str]) -> str:
                self._execute_count += 1
                self.calls.append(("execute_scripts", (list(bootstrap_scripts),)))
                raise RuntimeError("first failure")

        transport = _FatalTransport()
        monkeypatch.setattr(
            device_testing, "create_transport",
            lambda device_entry, deploy_mode=None: transport,
        )

        plan = [_plan_entry(tmp_path, "alpha", file_count=3)]
        device_result = device_testing._run_tests_on_device(
            _circuitpython_device(), plan,
            harness_source=tmp_path / "harness", function_filter=None,
        )

        # Only the first file ran; the rest were aborted.
        assert transport._execute_count == 1
        assert device_result.errors == 1
        assert device_result.passed == 0

    def test_missing_summary_counts_as_error(
        self, tmp_path, monkeypatch,
    ) -> None:
        """Output without a SUMMARY line increments the error counter."""
        transport = _RecordingTransport(
            mode="ram", outputs=[_NO_SUMMARY_OUTPUT],
        )
        monkeypatch.setattr(
            device_testing, "create_transport",
            lambda device_entry, deploy_mode=None: transport,
        )

        plan = [_plan_entry(tmp_path, "alpha")]
        device_result = device_testing._run_tests_on_device(
            _circuitpython_device(), plan,
            harness_source=tmp_path / "harness", function_filter=None,
        )

        assert device_result.errors == 1
        assert (device_result.passed, device_result.failed) == (0, 0)

    def test_mixed_pass_fail_summary_counted_correctly(
        self, tmp_path, monkeypatch,
    ) -> None:
        """A 2/2 passed, 1 failed summary counts as passed=1, failed=1."""
        transport = _RecordingTransport(
            mode="ram", outputs=[_MIXED_OUTPUT],
        )
        monkeypatch.setattr(
            device_testing, "create_transport",
            lambda device_entry, deploy_mode=None: transport,
        )

        plan = [_plan_entry(tmp_path, "alpha")]
        device_result = device_testing._run_tests_on_device(
            _circuitpython_device(), plan,
            harness_source=tmp_path / "harness", function_filter=None,
        )

        # total=2, failed=1 → passed=1, failed=1, errors=0.
        assert (device_result.passed, device_result.failed, device_result.errors) == (1, 1, 0)

    def test_ram_mode_stages_per_library(
        self, tmp_path, monkeypatch,
    ) -> None:
        """RAM mode stages each library separately (not bulk upfront).

        RAM-mode bootstraps embed source inline and have a per-script
        RAM budget; staging per library ensures only the library under
        test and its dependencies land in each bootstrap.
        """
        transport = _RecordingTransport(
            mode="ram", outputs=[_PASS_OUTPUT, _PASS_OUTPUT],
        )
        monkeypatch.setattr(
            device_testing, "create_transport",
            lambda device_entry, deploy_mode=None: transport,
        )
        # Stub the source-dir resolver so we don't need real pyproject data.
        monkeypatch.setattr(
            device_testing, "resolve_library_source_dirs",
            lambda library_dir, test_files=None: [library_dir / "src"],
        )

        plan = [_plan_entry(tmp_path, "alpha"), _plan_entry(tmp_path, "beta")]
        device_testing._run_tests_on_device(
            _circuitpython_device(), plan,
            harness_source=tmp_path / "harness", function_filter=None,
        )

        # Two stage calls (per library), not one.
        stage_calls = [call for call in transport.calls if call[0] == "stage"]
        assert len(stage_calls) == 2

    def test_micropython_mount_ram_mode_stages_per_library(
        self, tmp_path, monkeypatch,
    ) -> None:
        """MicroPython RAM mode must re-stage per library after each soft reset.

        Regression: the orchestrator used ``transport.mode == \"ram\"`` to
        decide whether staging was per-library. MicroPython RAM mode reports
        ``mode == \"mount\"``, so the run bulk-staged once, soft-reset after
        the first library, dropped the mount, and then the second library's
        bootstrap failed with ``ImportError: no module named
        'chumicro_test_harness'``.
        """
        transport = _RecordingTransport(
            mode="mount", outputs=[_PASS_OUTPUT, _PASS_OUTPUT],
        )
        monkeypatch.setattr(
            device_testing, "create_transport",
            lambda device_entry, deploy_mode=None: transport,
        )
        monkeypatch.setattr(
            device_testing, "resolve_library_source_dirs",
            lambda library_dir, test_files=None: [library_dir / "src"],
        )

        plan = [_plan_entry(tmp_path, "alpha"), _plan_entry(tmp_path, "beta")]
        device_result = device_testing._run_tests_on_device(
            _micropython_device(), plan,
            harness_source=tmp_path / "harness", function_filter=None,
        )

        assert (device_result.passed, device_result.failed, device_result.errors) == (2, 0, 0)
        stage_calls = [call for call in transport.calls if call[0] == "stage"]
        assert len(stage_calls) == 2
        soft_reset_calls = [call for call in transport.calls if call[0] == "soft_reset"]
        assert len(soft_reset_calls) == 1

    def test_stage_failure_in_ram_mode_errors_only_that_library(
        self, tmp_path, monkeypatch,
    ) -> None:
        """A RAM-mode stage failure errors only the files in that library."""

        class _StageOnceTransport(_RecordingTransport):
            def __init__(self) -> None:
                super().__init__(
                    mode="ram", outputs=[_PASS_OUTPUT],
                )
                self._stage_count = 0

            def stage(self, source_dirs, test_files, harness_source) -> None:
                self._stage_count += 1
                self.calls.append(
                    ("stage", (source_dirs, test_files, harness_source)),
                )
                if self._stage_count == 1:
                    raise RuntimeError("chunk too big")

        transport = _StageOnceTransport()
        monkeypatch.setattr(
            device_testing, "create_transport",
            lambda device_entry, deploy_mode=None: transport,
        )
        monkeypatch.setattr(
            device_testing, "resolve_library_source_dirs",
            lambda library_dir, test_files=None: [library_dir / "src"],
        )

        plan = [
            _plan_entry(tmp_path, "alpha", file_count=2),
            _plan_entry(tmp_path, "beta", file_count=1),
        ]
        device_result = device_testing._run_tests_on_device(
            _circuitpython_device(), plan,
            harness_source=tmp_path / "harness", function_filter=None,
        )

        # alpha: 2 errors (stage failed).  beta: 1 pass (stage succeeded).
        assert device_result.errors == 2
        assert device_result.passed == 1


class TestFormatTestDeviceCommand:
    """Tests for _format_test_device_command — PR summary command reconstruction."""

    def test_no_flags_when_all_args_none(self) -> None:
        """Default invocation renders just the base command."""
        command = device_testing._format_test_device_command(
            runtime=None,
            micropython_device=None,
            circuitpython_device=None,
            library=None,
            file_filter=None,
            function_filter=None,
            deploy_mode=None,
        )
        assert command == "python scripts/run.py test-device"

    def test_includes_every_flag_when_all_args_set(self) -> None:
        """Each non-None arg maps to its CLI flag with a hyphenated name."""
        command = device_testing._format_test_device_command(
            runtime="both",
            micropython_device="pico-w",
            circuitpython_device="s2-mini",
            library="timing",
            file_filter="test_heartbeat",
            function_filter="fires_on_interval",
            deploy_mode="flash",
        )
        assert "--runtime both" in command
        assert "--micropython-device pico-w" in command
        assert "--circuitpython-device s2-mini" in command
        assert "--library timing" in command
        assert "--file test_heartbeat" in command
        assert "--function fires_on_interval" in command
        assert "--deploy-mode flash" in command
        assert command.startswith("python scripts/run.py test-device ")

    def test_skips_flags_that_are_none(self) -> None:
        """Partial invocations only render the flags the user actually passed."""
        command = device_testing._format_test_device_command(
            runtime="micropython",
            micropython_device=None,
            circuitpython_device=None,
            library="runner",
            file_filter=None,
            function_filter=None,
            deploy_mode=None,
        )
        assert command == (
            "python scripts/run.py test-device --runtime micropython --library runner"
        )

    def test_file_and_function_flags_render_distinct_options(self) -> None:
        """``--file`` and ``--function`` are separate flags in the rendered command."""
        command = device_testing._format_test_device_command(
            runtime=None,
            micropython_device=None,
            circuitpython_device=None,
            library=None,
            file_filter="test_heartbeat",
            function_filter="fires",
            deploy_mode=None,
        )
        assert "--file test_heartbeat" in command
        assert "--function fires" in command


def _make_device_result(
    identifier: str = "mp-one",
    runtime: str = "micropython",
    address: str = "/dev/cu.usbmodem1",
    *,
    passed: int = 0,
    failed: int = 0,
    errors: int = 0,
    implementation=None,
    deploy_mode: str = "ram",
    duration_seconds: float = 0.0,
    files=None,
):
    """Build a DeviceRunResult with a synthetic DeviceEntry for tests."""
    device = DeviceEntry(
        identifier=identifier, runtime=runtime, address=address,
    )
    return device_testing.DeviceRunResult(
        device=device,
        passed=passed, failed=failed, errors=errors,
        implementation=implementation, deploy_mode=deploy_mode,
        duration_seconds=duration_seconds,
        files=list(files) if files is not None else [],
    )


class TestFormatPrSummaryBlock:
    """Tests for _format_pr_summary_block — paste-ready PR markdown."""

    def test_empty_results_still_renders_command_and_zero_total(self) -> None:
        """No devices run → block shows just the command and a bold zero total."""
        block = device_testing._format_pr_summary_block(
            command="python scripts/run.py test-device",
            per_device_results=[],
        )
        lines = block.splitlines()
        assert lines[0] == "- Command: `python scripts/run.py test-device`"
        assert "**Total: 0 passed, 0 failed, 0 errors**" in block
        # No table when there are no devices.
        assert "| Device" not in block

    def test_duration_line_included_when_provided(self) -> None:
        """``Duration:`` line appears right after the Command when passed."""
        block = device_testing._format_pr_summary_block(
            command="cmd",
            per_device_results=[],
            total_duration_seconds=12.345,
        )
        lines = block.splitlines()
        assert lines[0].startswith("- Command:")
        assert lines[1] == "- Duration: 12.35s"

    def test_single_device_renders_table_row(self) -> None:
        """A device appears as a padded markdown table row with its duration."""
        result = _make_device_result(
            identifier="pico-w", passed=5, duration_seconds=1.5,
        )
        block = device_testing._format_pr_summary_block(
            command="python scripts/run.py test-device --runtime micropython",
            per_device_results=[result],
        )
        # Header + separator + data row present.
        assert "| Device" in block
        assert "| Runtime" in block
        assert "| Duration" in block
        assert "---" in block
        # The data row contains the identifier, runtime, mode, counts,
        # and duration.
        data_rows = [
            line for line in block.splitlines()
            if line.startswith("| `pico-w`")
        ]
        assert len(data_rows) == 1
        data_row = data_rows[0]
        assert "MicroPython" in data_row
        assert "ram" in data_row
        assert " 5 " in data_row
        assert "1.50s" in data_row
        # Total follows the table, not embedded in it.
        assert "**Total: 5 passed, 0 failed, 0 errors**" in block

    def test_multiple_devices_sum_into_bold_total(self) -> None:
        """Per-device counts accumulate into the bolded final line."""
        mp_result = _make_device_result(
            identifier="pico-w", passed=4, failed=1,
        )
        cp_result = _make_device_result(
            identifier="s2-mini", runtime="circuitpython",
            address="/dev/cu.usbmodem2",
            passed=3, errors=2, deploy_mode="flash",
        )
        block = device_testing._format_pr_summary_block(
            command="python scripts/run.py test-device --runtime both",
            per_device_results=[mp_result, cp_result],
        )
        # Both devices appear as table rows.
        data_rows = [
            line for line in block.splitlines()
            if line.startswith("| `") and ("pico-w" in line or "s2-mini" in line)
        ]
        assert len(data_rows) == 2
        assert "**Total: 7 passed, 1 failed, 2 errors**" in block

    def test_uses_human_friendly_runtime_labels(self) -> None:
        """Internal runtime names render as human labels in the block."""
        block = device_testing._format_pr_summary_block(
            command="cmd",
            per_device_results=[
                _make_device_result(identifier="x", address="/dev/a"),
                _make_device_result(
                    identifier="y", runtime="circuitpython", address="/dev/b",
                ),
            ],
        )
        assert "MicroPython" in block
        assert "CircuitPython" in block
        # Internal identifiers should NOT leak into the rendered block.
        assert "| micropython " not in block
        assert "| circuitpython " not in block

    def test_probe_result_surfaces_version_and_board(self) -> None:
        """When the probe succeeded, version and machine fill their table columns."""
        from chumicro_deploy import DeviceImplementation

        result = _make_device_result(
            identifier="pico-w", passed=5,
            implementation=DeviceImplementation(
                name="micropython",
                version="1.26.0",
                machine="Raspberry Pi Pico W with RP2040",
            ),
        )
        block = device_testing._format_pr_summary_block(
            command="python scripts/run.py test-device",
            per_device_results=[result],
        )
        # Version lives in the Runtime column, machine in the Board column.
        assert "MicroPython 1.26.0" in block
        assert "Raspberry Pi Pico W with RP2040" in block

    def test_probe_result_without_machine_keeps_board_cell_empty(self) -> None:
        """Empty ``machine`` leaves the Board cell blank (not missing)."""
        from chumicro_deploy import DeviceImplementation

        result = _make_device_result(
            identifier="cp", runtime="circuitpython",
            address="/dev/cu.usbmodem2",
            implementation=DeviceImplementation(
                name="circuitpython",
                version="10.1.4",
                machine="",
            ),
        )
        block = device_testing._format_pr_summary_block(
            command="cmd",
            per_device_results=[result],
        )
        assert "CircuitPython 10.1.4" in block
        # Still a well-formed table row: | `cp` | CircuitPython 10.1.4 |  | ...
        data_row = next(
            line for line in block.splitlines()
            if line.startswith("| `cp`")
        )
        # Exactly 8 data columns + 2 outer borders → 9 pipes.
        assert data_row.count("|") == 9

    def test_deploy_mode_surfaces_even_without_probe(self) -> None:
        """Bare ``test-device`` (no probe result) still shows the deploy mode."""
        result = _make_device_result(
            identifier="cp", runtime="circuitpython",
            address="/dev/cu.usbmodem2",
            passed=1, deploy_mode="flash",
        )
        block = device_testing._format_pr_summary_block(
            command="python scripts/run.py test-device",
            per_device_results=[result],
        )
        data_row = next(
            line for line in block.splitlines()
            if line.startswith("| `cp`")
        )
        assert " flash " in data_row

    def test_different_devices_can_show_different_modes(self) -> None:
        """Per-device modes render independently so mixed runs are legible."""
        block = device_testing._format_pr_summary_block(
            command="cmd",
            per_device_results=[
                _make_device_result(identifier="mp", address="/dev/a"),
                _make_device_result(
                    identifier="cp", runtime="circuitpython",
                    address="/dev/b", deploy_mode="flash",
                ),
            ],
        )
        mp_row = next(
            line for line in block.splitlines()
            if line.startswith("| `mp`")
        )
        cp_row = next(
            line for line in block.splitlines()
            if line.startswith("| `cp`")
        )
        assert " ram " in mp_row
        assert " flash " in cp_row

    def test_single_file_run_renders_per_test_table(self) -> None:
        """One file → per-test detail table with status + duration per method."""
        from result_parser import TestResult

        files = [device_testing.FileRunResult(
            library="timing",
            file_name="test_heartbeat.py",
            passed=2,
            failed=1,
            errors=0,
            tests=[
                TestResult(
                    name="test_heartbeat_fires",
                    status="PASS",
                    duration=0.012,
                ),
                TestResult(
                    name="test_heartbeat_resets",
                    status="FAIL",
                    duration=0.008,
                    message="",
                ),
                TestResult(
                    name="test_heartbeat_period",
                    status="PASS",
                    duration=0.002,
                ),
            ],
            duration_seconds=0.045,
        )]
        result = _make_device_result(
            passed=2, failed=1, duration_seconds=1.2, files=files,
        )
        block = device_testing._format_pr_summary_block(
            command="cmd",
            per_device_results=[result],
        )
        assert "per-test breakdown" in block
        assert "| Test" in block
        assert "| Status" in block
        assert "`test_heartbeat_fires`" in block
        assert "PASS" in block
        assert "FAIL" in block
        assert "12ms" in block
        # Per-file table should NOT appear when only one file ran
        # (the device row + per-test table are enough).
        assert "per-file breakdown" not in block

    def test_multi_file_run_renders_per_file_table(self) -> None:
        """Multiple files → per-file detail table with counts + duration."""
        files = [
            device_testing.FileRunResult(
                library="timing", file_name="test_heartbeat.py",
                passed=3, failed=0, errors=0, duration_seconds=0.120,
            ),
            device_testing.FileRunResult(
                library="timing", file_name="test_ticks.py",
                passed=2, failed=0, errors=0, duration_seconds=0.080,
            ),
        ]
        result = _make_device_result(
            passed=5, duration_seconds=0.5, files=files,
        )
        block = device_testing._format_pr_summary_block(
            command="cmd",
            per_device_results=[result],
        )
        assert "per-file breakdown" in block
        assert "| File" in block
        assert "`timing/test_heartbeat.py`" in block
        assert "`timing/test_ticks.py`" in block
        assert "120ms" in block
        assert "80ms" in block
        # Test-level detail must be suppressed when multiple files run.
        assert "per-test breakdown" not in block

    def test_device_without_files_has_no_detail_section(self) -> None:
        """A device that never ran any file gets no detail section."""
        result = _make_device_result(errors=1, duration_seconds=0.05)
        block = device_testing._format_pr_summary_block(
            command="cmd",
            per_device_results=[result],
        )
        assert "per-file breakdown" not in block
        assert "per-test breakdown" not in block
        # Summary row still there.
        assert "| `mp-one`" in block


class TestFormatMarkdownTable:
    """Tests for the padded-table helper used by the PR summary."""

    def test_left_alignment_default_pads_right(self) -> None:
        """With no alignments argument, every column pads on the right."""
        table = device_testing._format_markdown_table(
            headers=["Name", "Value"],
            rows=[["alpha", "1"], ["bravo", "22"]],
        )
        lines = table.splitlines()
        # Header row and two data rows, all the same width → padded.
        row_widths = [len(line) for line in lines]
        assert len(set(row_widths)) == 1
        # Separator is ``|  ---- |`` style — all dashes, no colons.
        separator = lines[1]
        assert ":" not in separator

    def test_right_alignment_adds_trailing_colon_to_separator(self) -> None:
        """``"right"`` alignment marks the separator with a trailing colon."""
        table = device_testing._format_markdown_table(
            headers=["N"],
            rows=[["1"], ["10"]],
            alignments=["right"],
        )
        # With the 3-char minimum column width, the separator is ``--:``.
        separator = table.splitlines()[1]
        assert " --: " in separator
        # Right-aligned data rows pad on the left (numbers right-justified).
        data_rows = table.splitlines()[2:]
        assert "|   1 |" in data_rows[0]
        assert "|  10 |" in data_rows[1]

    def test_center_alignment_marks_both_ends_of_separator(self) -> None:
        """``"center"`` alignment marks the separator with colons on both ends."""
        table = device_testing._format_markdown_table(
            headers=["Mode"],
            rows=[["ram"]],
            alignments=["center"],
        )
        separator = table.splitlines()[1]
        # Strip the outer "| " / " |" then check the payload.
        inner = separator[2:-2]
        assert inner.startswith(":")
        assert inner.endswith(":")

    def test_column_widths_respect_max_content(self) -> None:
        """Each column widens to fit its widest cell (header or data)."""
        table = device_testing._format_markdown_table(
            headers=["Short", "Wider header"],
            rows=[["loooooong value", "x"]],
        )
        # Long data cell in column 0 forces the header to pad:
        # ``| Short           | Wider header |``
        header_row = table.splitlines()[0]
        assert "Short           " in header_row


class TestResolveEffectiveDeployMode:
    """Tests for _resolve_effective_deploy_mode — deploy-mode precedence."""

    def test_cli_override_wins(self) -> None:
        """CLI ``--deploy-mode`` takes precedence over the device entry."""
        device = DeviceEntry(
            identifier="d", runtime="micropython", address="/dev/a",
            deploy_mode="flash",
        )
        assert device_testing._resolve_effective_deploy_mode(device, "ram") == "ram"

    def test_device_entry_used_when_override_none(self) -> None:
        """Without a CLI override the device entry's ``deploy_mode`` applies."""
        device = DeviceEntry(
            identifier="d", runtime="micropython", address="/dev/a",
            deploy_mode="flash",
        )
        assert device_testing._resolve_effective_deploy_mode(device, None) == "flash"

    def test_defaults_to_ram_when_device_entry_field_empty(self) -> None:
        """Belt-and-braces: an empty ``deploy_mode`` falls back to ram."""
        # The loader always populates deploy_mode, but the helper's
        # ``or "ram"`` tail protects against a future code path that
        # constructs a DeviceEntry by hand.
        device = DeviceEntry(
            identifier="d", runtime="micropython", address="/dev/a",
        )
        object.__setattr__(device, "deploy_mode", "")
        assert device_testing._resolve_effective_deploy_mode(device, None) == "ram"


class TestSummaryAlwaysPrints:
    """Summary + PR block must print on every non-empty run — pass, fail, or crash.

    Contributors rely on the PR block for copy/paste; losing it because
    one device raised an exception mid-run was painful and confusing.
    """

    def _write_devices_yml(self, tmp_path, monkeypatch) -> None:
        """Write a minimal devices.yml and set CHUMICRO_DEVICES."""
        devices_file = tmp_path / "devices.yml"
        devices_file.write_text(
            "defaults:\n"
            "  micropython: mp-one\n"
            "  ide_runtime: micropython\n"
            "devices:\n"
            "  - id: mp-one\n"
            "    runtime: micropython\n"
            "    address: /dev/ttyUSB0\n"
        )
        monkeypatch.setenv("CHUMICRO_DEVICES", str(devices_file))

    def _stub_functional_tests(self, monkeypatch) -> None:
        """Stub out discover_functional_tests with a single plan entry."""
        monkeypatch.setattr(
            device_testing,
            "discover_functional_tests",
            lambda library=None, file_filter=None, function_filter=None: [
                (
                    "timing",
                    device_testing.ROOT / "libraries" / "timing" / "src",
                    [
                        device_testing.ROOT / "libraries" / "timing"
                        / "functional_tests" / "test_heartbeat.py",
                    ],
                ),
            ],
        )

    def test_summary_prints_when_tests_fail(
        self, tmp_path, monkeypatch, capsys,
    ) -> None:
        """A failing run (failed>0) still prints the summary banner and PR block."""
        self._write_devices_yml(tmp_path, monkeypatch)
        self._stub_functional_tests(monkeypatch)
        monkeypatch.setattr(
            device_testing, "_run_tests_on_device",
            lambda device_entry, *args, **kwargs: device_testing.DeviceRunResult(
                device=device_entry, passed=2, failed=1, errors=0,
                implementation=None, deploy_mode="ram",
            ),
        )

        result = device_testing.test_device()

        captured = capsys.readouterr()
        assert result == 1  # non-zero because of failed=1
        assert "Device test summary: 2 passed, 1 failed, 0 errors" in captured.out
        assert "PR summary (paste into the 'Device testing' section" in captured.out
        assert "**Total: 2 passed, 1 failed, 0 errors**" in captured.out
        # Duration line always present in non-empty runs.
        assert "\n- Duration: " in captured.out

    def test_summary_prints_when_device_run_raises(
        self, tmp_path, monkeypatch, capsys,
    ) -> None:
        """A ``_run_tests_on_device`` crash still yields the full summary.

        Regression: an unwrapped ``transport.disconnect()`` raise used
        to propagate out of ``test_device`` and skip the summary
        entirely.  The crashing device gets a ``(0, 0, 1)`` row so the
        PR block still shows the failure visibly.
        """
        self._write_devices_yml(tmp_path, monkeypatch)
        self._stub_functional_tests(monkeypatch)

        def exploding_run(device_entry, *args, **kwargs):
            raise RuntimeError("serial port yanked mid-run")

        monkeypatch.setattr(
            device_testing, "_run_tests_on_device", exploding_run,
        )

        result = device_testing.test_device()

        captured = capsys.readouterr()
        assert result == 1
        assert "FATAL: Device run raised: serial port yanked mid-run" in captured.out
        assert "Device test summary: 0 passed, 0 failed, 1 errors" in captured.out
        assert "PR summary (paste into the 'Device testing' section" in captured.out
        # Crashed device still shows up as a bullet so reviewers see the
        # failure, not silence.
        assert "`mp-one`" in captured.out
        assert "**Total: 0 passed, 0 failed, 1 errors**" in captured.out

    def test_partial_results_survive_one_bad_device(
        self, tmp_path, monkeypatch, capsys,
    ) -> None:
        """When one device crashes and another passes, both rows appear.

        The loop must not abort after a crash — other devices should
        still run and land in the per-device block.
        """
        devices_file = tmp_path / "devices.yml"
        devices_file.write_text(
            "defaults:\n"
            "  micropython: mp-one\n"
            "  circuitpython: cp-one\n"
            "  ide_runtime: both\n"
            "devices:\n"
            "  - id: mp-one\n"
            "    runtime: micropython\n"
            "    address: /dev/ttyUSB0\n"
            "  - id: cp-one\n"
            "    runtime: circuitpython\n"
            "    address: /dev/cu.usbmodem1\n"
        )
        monkeypatch.setenv("CHUMICRO_DEVICES", str(devices_file))
        self._stub_functional_tests(monkeypatch)

        def half_exploding_run(device_entry, *args, **kwargs):
            if device_entry.identifier == "mp-one":
                raise RuntimeError("mpremote hung")
            return device_testing.DeviceRunResult(
                device=device_entry, passed=3, failed=0, errors=0,
                implementation=None, deploy_mode="ram",
            )

        monkeypatch.setattr(
            device_testing, "_run_tests_on_device", half_exploding_run,
        )

        result = device_testing.test_device()

        captured = capsys.readouterr()
        assert result == 1  # mp-one errored
        # Both devices have rows in the summary table (wrapped in
        # backticks like `mp-one`).
        assert "`mp-one`" in captured.out
        assert "`cp-one`" in captured.out
        # Totals banner and Total bold line both include the aggregate
        # (3 passed from cp-one + 1 error from mp-one's crash).
        assert "Device test summary: 3 passed, 0 failed, 1 errors" in captured.out
        assert "**Total: 3 passed, 0 failed, 1 errors**" in captured.out
