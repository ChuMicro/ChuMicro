"""Tests for the plugin's internal device-test primitives.

Coverage focuses on the helpers the plugin relies on: bootstrap
generation, transport construction, intra-workspace source
resolution, and deploy-mode precedence.  PR-summary rendering has
its own test module.

``TestResolveLibrarySourceDirs`` exercises dependency resolution
against a synthetic multi-library workspace materialized under
``tmp_path`` via the ``_make_synthetic_library`` helper — no test
reads the real on-disk state of any real chumicro library.  The
prior version pinned ``libraries/runner`` / ``libraries/timing`` /
``libraries/msgpack`` and silently changed behavior whenever any of
those packages was renamed, restructured, or had its dependency
list edited.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from chumicro_deploy import DeviceEntry
from chumicro_pytest_device import _test_runner as device_testing


def _make_synthetic_library(
    libraries_root: Path,
    name: str,
    *,
    deps: list[str] | None = None,
    test_imports: list[str] | None = None,
) -> Path:
    """Stage a synthetic library at ``libraries_root/<name>/`` and return it.

    Materializes ``src/chumicro_<name>/__init__.py`` and a
    ``pyproject.toml`` listing each ``deps`` entry as
    ``chumicro-<dep>``.  When ``test_imports`` is supplied, also
    creates ``functional_tests/test_integration.py`` with one
    ``import chumicro_<dep>`` line per entry so the
    test-imported-library path of ``resolve_library_source_dirs``
    has something to walk.
    """
    library_dir = libraries_root / name
    source_dir = library_dir / "src" / f"chumicro_{name}"
    source_dir.mkdir(parents=True)
    (source_dir / "__init__.py").touch()

    if deps:
        deps_block = "dependencies = [\n" + "".join(
            f'    "chumicro-{dep}",\n' for dep in deps
        ) + "]\n"
    else:
        deps_block = ""
    (library_dir / "pyproject.toml").write_text(
        f'[project]\nname = "chumicro-{name}"\n{deps_block}',
    )

    if test_imports is not None:
        functional_dir = library_dir / "functional_tests"
        functional_dir.mkdir()
        import_lines = "\n".join(
            f"import chumicro_{module}" for module in test_imports
        )
        (functional_dir / "test_integration.py").write_text(
            f"{import_lines}\n\ndef test_integration() -> None:\n    pass\n",
        )

    return library_dir


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

    def test_chunk_boundaries_none_by_default(self) -> None:
        """No boundaries ⇒ the device keeps the single whole-file exec."""
        script = device_testing.build_bootstrap("test_x.py")
        assert "chunk_boundaries=None" in script

    def test_chunk_boundaries_embedded_when_set(self) -> None:
        """Boundaries are embedded as a literal list for the device."""
        script = device_testing.build_bootstrap(
            "test_x.py", chunk_boundaries=[1, 7, 40]
        )
        assert "chunk_boundaries=[1, 7, 40]" in script
        compile(script, "<bootstrap>", "exec")


class TestChunkBoundariesFor:
    """Tests for chunk_boundaries_for (host-side AST segmentation)."""

    def test_decorator_aware_start_lines(self, tmp_path: Path) -> None:
        """A decorated def starts at its decorator, not the def line."""
        source = (
            "import os\n"          # 1
            "\n"                    # 2
            "def deco(f):\n"        # 3
            "    return f\n"        # 4
            "\n"                    # 5
            "@deco\n"               # 6
            "def thing():\n"        # 7
            "    return 1\n"        # 8
        )
        path = tmp_path / "m.py"
        path.write_text(source)
        assert device_testing.chunk_boundaries_for(path) == [1, 3, 6]

    def test_future_import_disables_chunking(self, tmp_path: Path) -> None:
        """A __future__ import ⇒ None (each chunk compiles alone)."""
        path = tmp_path / "m.py"
        path.write_text(
            "from __future__ import annotations\n\n"
            "def a():\n    pass\n\ndef b():\n    pass\n"
        )
        assert device_testing.chunk_boundaries_for(path) is None

    def test_single_statement_returns_none(self, tmp_path: Path) -> None:
        """Fewer than two top-level statements ⇒ nothing to split."""
        path = tmp_path / "m.py"
        path.write_text("class TestOnly:\n    def test_a(self):\n        pass\n")
        assert device_testing.chunk_boundaries_for(path) is None


class TestCreateTransport:
    """Tests for build_transport_for_entry deploy mode routing."""

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
        transport = device_testing.build_transport_for_entry(entry, deploy_mode="ram")
        assert transport.mode == "mount"

    def test_micropython_flash_uses_copy_mode(self) -> None:
        """Flash deploy mode should map to copy for MicroPython."""
        entry = self._make_device_entry(runtime="micropython")
        transport = device_testing.build_transport_for_entry(entry, deploy_mode="flash")
        assert transport.mode == "copy"

    def test_circuitpython_ram_mode(self) -> None:
        """RAM deploy mode should pass ram to CircuitPython transport."""
        entry = self._make_device_entry(runtime="circuitpython")
        transport = device_testing.build_transport_for_entry(entry, deploy_mode="ram")
        assert transport.mode == "ram"

    def test_circuitpython_flash_mode(self) -> None:
        """Flash deploy mode should pass flash to CircuitPython transport."""
        entry = self._make_device_entry(runtime="circuitpython")
        transport = device_testing.build_transport_for_entry(entry, deploy_mode="flash")
        assert transport.mode == "flash"

    def test_unsupported_runtime_raises(self) -> None:
        """Unsupported runtime should raise ValueError."""
        entry = self._make_device_entry(runtime="unknown")
        # Override runtime since DeviceEntry doesn't validate.
        entry.runtime = "unknown"
        with pytest.raises(ValueError, match="Unsupported transport"):
            device_testing.build_transport_for_entry(entry)

    def test_default_deploy_mode_is_flash(self) -> None:
        """Default deploy mode (from device entry) should be flash → copy.

        Flash is the production-shaped default; RAM mode stays
        available as opt-in via per-device or CLI override.
        """
        entry = self._make_device_entry(runtime="micropython")
        transport = device_testing.build_transport_for_entry(entry)
        assert transport.mode == "copy"

    def test_device_entry_deploy_mode_flash(self) -> None:
        """Device entry deploy_mode=flash should apply when CLI is None."""
        entry = self._make_device_entry(
            runtime="micropython", deploy_mode="flash",
        )
        transport = device_testing.build_transport_for_entry(entry)
        assert transport.mode == "copy"

    def test_cli_overrides_device_entry_deploy_mode(self) -> None:
        """CLI deploy_mode should override the device entry default."""
        entry = self._make_device_entry(
            runtime="micropython", deploy_mode="flash",
        )
        transport = device_testing.build_transport_for_entry(entry, deploy_mode="ram")
        assert transport.mode == "mount"

    def test_circuitpython_device_entry_flash(self) -> None:
        """CP device entry deploy_mode=flash should apply when CLI is None."""
        entry = self._make_device_entry(
            runtime="circuitpython",
            deploy_mode="flash",
        )
        transport = device_testing.build_transport_for_entry(entry)
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
    """Tests for ``resolve_library_source_dirs`` against a synthetic
    libraries/ tree built per-test under ``tmp_path``."""

    def test_resolves_chumicro_imports_from_test_files(
        self, tmp_path: Path,
    ) -> None:
        """Functional test imports should stage additional ChuMicro libraries."""
        libraries_root = tmp_path / "libraries"
        _make_synthetic_library(libraries_root, "leaf")
        consumer_dir = _make_synthetic_library(
            libraries_root, "consumer", test_imports=["leaf"],
        )
        integration_test = (
            consumer_dir / "functional_tests" / "test_integration.py"
        )

        result = device_testing.resolve_library_source_dirs(
            consumer_dir,
            libraries_root=libraries_root,
            test_files=[integration_test],
        )

        leaf_source = libraries_root / "leaf" / "src"
        assert leaf_source in result

    def test_includes_own_source_dir(self, tmp_path: Path) -> None:
        """The library under test always shows up with its own ``src/``."""
        libraries_root = tmp_path / "libraries"
        library_dir = _make_synthetic_library(libraries_root, "solo")
        result = device_testing.resolve_library_source_dirs(
            library_dir, libraries_root=libraries_root,
        )
        assert library_dir / "src" in result

    def test_includes_dependency_source_dirs(self, tmp_path: Path) -> None:
        """A library that depends on another should pull in both ``src/`` dirs."""
        libraries_root = tmp_path / "libraries"
        _make_synthetic_library(libraries_root, "leaf")
        consumer_dir = _make_synthetic_library(
            libraries_root, "consumer", deps=["leaf"],
        )
        result = device_testing.resolve_library_source_dirs(
            consumer_dir, libraries_root=libraries_root,
        )
        leaf_source = libraries_root / "leaf" / "src"
        consumer_source = consumer_dir / "src"
        assert leaf_source in result
        assert consumer_source in result

    def test_dependency_comes_before_library(self, tmp_path: Path) -> None:
        """Dependency ``src/`` dirs precede the consuming library's own ``src/``."""
        libraries_root = tmp_path / "libraries"
        _make_synthetic_library(libraries_root, "leaf")
        consumer_dir = _make_synthetic_library(
            libraries_root, "consumer", deps=["leaf"],
        )
        result = device_testing.resolve_library_source_dirs(
            consumer_dir, libraries_root=libraries_root,
        )
        leaf_source = libraries_root / "leaf" / "src"
        consumer_source = consumer_dir / "src"
        assert result.index(leaf_source) < result.index(consumer_source)

    def test_test_import_dependency_comes_before_library(
        self, tmp_path: Path,
    ) -> None:
        """Test-imported libraries should stage before the library under test."""
        libraries_root = tmp_path / "libraries"
        _make_synthetic_library(libraries_root, "leaf")
        consumer_dir = _make_synthetic_library(
            libraries_root, "consumer", test_imports=["leaf"],
        )
        integration_test = (
            consumer_dir / "functional_tests" / "test_integration.py"
        )

        result = device_testing.resolve_library_source_dirs(
            consumer_dir,
            libraries_root=libraries_root,
            test_files=[integration_test],
        )

        leaf_source = libraries_root / "leaf" / "src"
        consumer_source = consumer_dir / "src"
        assert result.index(leaf_source) < result.index(consumer_source)

    def test_library_without_dependencies(self, tmp_path: Path) -> None:
        """A library with no deps should return only its own ``src/``."""
        libraries_root = tmp_path / "libraries"
        library_dir = _make_synthetic_library(libraries_root, "solo")
        result = device_testing.resolve_library_source_dirs(
            library_dir, libraries_root=libraries_root,
        )
        assert result == [library_dir / "src"]

    def test_nonexistent_library_returns_empty(self, tmp_path: Path) -> None:
        """A nonexistent library dir should return an empty list."""
        libraries_root = tmp_path / "libraries"
        libraries_root.mkdir()
        result = device_testing.resolve_library_source_dirs(
            libraries_root / "nope", libraries_root=libraries_root,
        )
        assert result == []

    def test_no_duplicate_entries(self, tmp_path: Path) -> None:
        """Diamond-shape deps still produce a deduplicated source list."""
        libraries_root = tmp_path / "libraries"
        _make_synthetic_library(libraries_root, "leaf")
        _make_synthetic_library(libraries_root, "left", deps=["leaf"])
        _make_synthetic_library(libraries_root, "right", deps=["leaf"])
        top_dir = _make_synthetic_library(
            libraries_root, "top", deps=["left", "right"],
        )
        result = device_testing.resolve_library_source_dirs(
            top_dir, libraries_root=libraries_root,
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

    def test_defaults_to_flash_when_device_entry_field_empty(self) -> None:
        """Belt-and-braces: an empty ``deploy_mode`` falls back to flash
        (the production-shaped default).
        """
        device = DeviceEntry(
            identifier="d", runtime="micropython", address="/dev/a",
        )
        object.__setattr__(device, "deploy_mode", "")
        assert device_testing.resolve_effective_deploy_mode(device, None) == "flash"
