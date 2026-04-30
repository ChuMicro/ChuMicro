"""Tests for the plugin's internal device-test primitives.

Coverage focuses on the helpers the plugin relies on: bootstrap
generation, transport construction, intra-workspace source
resolution, and deploy-mode precedence.  PR-summary rendering has
its own test module.

A few tests under ``TestResolveLibrarySourceDirs`` need a real
multi-library workspace to exercise dependency resolution; they
pin the chumicro mono-repo's ``libraries/`` directory via
:data:`_MONO_REPO_LIBRARIES` and skip cleanly when the layout
isn't where they expect (e.g. the published wheel running against
a third-party project).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from chumicro_deploy import DeviceEntry
from chumicro_pytest_device import _test_runner as device_testing

#: Path to the chumicro mono-repo's ``libraries/`` directory when this
#: file is checked out in-tree.  ``parents[3]`` walks up from
#: ``workbench/pytest-device/tests/test_test_runner.py`` to the repo
#: root.
_MONO_REPO_LIBRARIES = Path(__file__).resolve().parents[3] / "libraries"


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
        entry = self._make_device_entry(runtime="unknown")
        # Override runtime since DeviceEntry doesn't validate.
        entry.runtime = "unknown"
        with pytest.raises(ValueError, match="Unsupported transport"):
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
    """Tests for ``resolve_library_source_dirs``.

    Mono-repo integration tests — they need real ``libraries/runner``,
    ``libraries/timing``, and ``libraries/msgpack`` directories to
    exercise dependency resolution, so they skip cleanly when the
    layout isn't where ``_MONO_REPO_LIBRARIES`` points.
    """

    def setup_method(self) -> None:
        if not _MONO_REPO_LIBRARIES.is_dir():
            pytest.skip("chumicro mono-repo libraries/ not present")

    def test_resolves_chumicro_imports_from_test_files(self) -> None:
        """Functional test imports should stage additional ChuMicro libraries."""
        runner_dir = _MONO_REPO_LIBRARIES / "runner"
        integration_test = runner_dir / "functional_tests" / "test_integration.py"

        result = device_testing.resolve_library_source_dirs(
            runner_dir,
            libraries_root=_MONO_REPO_LIBRARIES,
            test_files=[integration_test],
        )

        msgpack_source = _MONO_REPO_LIBRARIES / "msgpack" / "src"
        assert msgpack_source in result

    def test_includes_own_source_dir(self) -> None:
        timing_dir = _MONO_REPO_LIBRARIES / "timing"
        result = device_testing.resolve_library_source_dirs(
            timing_dir, libraries_root=_MONO_REPO_LIBRARIES,
        )
        assert timing_dir / "src" in result

    def test_includes_dependency_source_dirs(self) -> None:
        """Runner depends on timing — both ``src/`` dirs should appear."""
        runner_dir = _MONO_REPO_LIBRARIES / "runner"
        result = device_testing.resolve_library_source_dirs(
            runner_dir, libraries_root=_MONO_REPO_LIBRARIES,
        )
        timing_source = _MONO_REPO_LIBRARIES / "timing" / "src"
        runner_source = runner_dir / "src"
        assert timing_source in result
        assert runner_source in result

    def test_dependency_comes_before_library(self) -> None:
        runner_dir = _MONO_REPO_LIBRARIES / "runner"
        result = device_testing.resolve_library_source_dirs(
            runner_dir, libraries_root=_MONO_REPO_LIBRARIES,
        )
        timing_source = _MONO_REPO_LIBRARIES / "timing" / "src"
        runner_source = runner_dir / "src"
        assert result.index(timing_source) < result.index(runner_source)

    def test_test_import_dependency_comes_before_library(self) -> None:
        """Test-imported libraries should stage before the library under test."""
        runner_dir = _MONO_REPO_LIBRARIES / "runner"
        integration_test = runner_dir / "functional_tests" / "test_integration.py"

        result = device_testing.resolve_library_source_dirs(
            runner_dir,
            libraries_root=_MONO_REPO_LIBRARIES,
            test_files=[integration_test],
        )

        msgpack_source = _MONO_REPO_LIBRARIES / "msgpack" / "src"
        runner_source = runner_dir / "src"
        assert result.index(msgpack_source) < result.index(runner_source)

    def test_library_without_dependencies(self) -> None:
        """A library with no deps should return only its own ``src/``."""
        timing_dir = _MONO_REPO_LIBRARIES / "timing"
        result = device_testing.resolve_library_source_dirs(
            timing_dir, libraries_root=_MONO_REPO_LIBRARIES,
        )
        assert result == [timing_dir / "src"]

    def test_nonexistent_library_returns_empty(self, tmp_path) -> None:
        """A nonexistent library dir should return an empty list."""
        result = device_testing.resolve_library_source_dirs(
            tmp_path / "nope", libraries_root=_MONO_REPO_LIBRARIES,
        )
        assert result == []

    def test_no_duplicate_entries(self) -> None:
        runner_dir = _MONO_REPO_LIBRARIES / "runner"
        result = device_testing.resolve_library_source_dirs(
            runner_dir, libraries_root=_MONO_REPO_LIBRARIES,
        )
        assert len(result) == len(set(result))


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


class TestResolveEffectiveDeployMode:
    """Tests for resolve_effective_deploy_mode — deploy-mode precedence."""

    def test_cli_override_wins(self) -> None:
        """CLI ``--deploy-mode`` takes precedence over the device entry."""
        device = DeviceEntry(
            identifier="d", runtime="micropython", address="/dev/a",
            deploy_mode="flash",
        )
        assert device_testing.resolve_effective_deploy_mode(device, "ram") == "ram"

    def test_device_entry_used_when_override_none(self) -> None:
        """Without a CLI override the device entry's ``deploy_mode`` applies."""
        device = DeviceEntry(
            identifier="d", runtime="micropython", address="/dev/a",
            deploy_mode="flash",
        )
        assert device_testing.resolve_effective_deploy_mode(device, None) == "flash"

    def test_defaults_to_ram_when_device_entry_field_empty(self) -> None:
        """Belt-and-braces: an empty ``deploy_mode`` falls back to ram."""
        device = DeviceEntry(
            identifier="d", runtime="micropython", address="/dev/a",
        )
        object.__setattr__(device, "deploy_mode", "")
        assert device_testing.resolve_effective_deploy_mode(device, None) == "ram"
