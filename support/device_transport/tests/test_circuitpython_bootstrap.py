"""Tests for the CircuitPython bootstrap code generator."""

from __future__ import annotations

from pathlib import Path

from chumicro_device_transport.circuitpython_bootstrap import (
    _escape_source,
    _resolve_relative_imports,
    build_circuitpython_bootstrap,
)


class TestBuildCircuitpythonBootstrap:
    """Tests for build_circuitpython_bootstrap."""

    def test_generates_module_injection(self, tmp_path: Path) -> None:
        """Bootstrap should contain populate calls for each module."""
        staged_sources = [
            ("chumicro_timing", "# timing init"),
            ("chumicro_timing.ticks", "def ticks_ms(): pass"),
        ]
        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok(): pass")

        result = build_circuitpython_bootstrap(staged_sources, test_file)

        assert "_populate_module('chumicro_timing'" in result
        assert "_populate_module('chumicro_timing.ticks'" in result

    def test_includes_module_helpers(self, tmp_path: Path) -> None:
        """Bootstrap should define stub and populate helpers."""
        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok(): pass")

        result = build_circuitpython_bootstrap([], test_file)

        assert "def _register_stub(module_name):" in result
        assert "def _populate_module(module_name, source_code):" in result
        assert "sys.modules[module_name]" in result

    def test_execs_test_file(self, tmp_path: Path) -> None:
        """Bootstrap should exec the test file source."""
        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_hello(): assert True")

        result = build_circuitpython_bootstrap([], test_file)

        assert "exec(" in result
        assert "_test_namespace" in result
        assert "def test_hello" in result or "test_hello" in result

    def test_calls_run_module(self, tmp_path: Path) -> None:
        """Bootstrap should call run_module with the test namespace."""
        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok(): pass")

        result = build_circuitpython_bootstrap([], test_file)

        assert "run_module(_TestModule" in result

    def test_passes_name_filter(self, tmp_path: Path) -> None:
        """Bootstrap should pass name_filter to run_module when set."""
        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok(): pass")

        result = build_circuitpython_bootstrap(
            [], test_file, name_filter="test_specific",
        )

        assert "name_filter='test_specific'" in result

    def test_name_filter_none_by_default(self, tmp_path: Path) -> None:
        """Bootstrap should pass None for name_filter when not set."""
        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok(): pass")

        result = build_circuitpython_bootstrap([], test_file)

        assert "name_filter=None" in result

    def test_imports_sys(self, tmp_path: Path) -> None:
        """Bootstrap should import sys for module registration."""
        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok(): pass")

        result = build_circuitpython_bootstrap([], test_file)

        assert "import sys" in result

    def test_creates_test_module_class(self, tmp_path: Path) -> None:
        """Bootstrap should create a _TestModule class from namespace."""
        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok(): pass")

        result = build_circuitpython_bootstrap([], test_file)

        assert "class _TestModule:" in result
        assert "setattr(_TestModule" in result

    def test_module_helpers_attach_submodules(
        self, tmp_path: Path,
    ) -> None:
        """Module helpers should attach submodules to parent packages."""
        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok(): pass")

        result = build_circuitpython_bootstrap(
            [("pkg", "x = 1"), ("pkg.sub", "y = 2")],
            test_file,
        )

        # The helper should contain parent-attachment logic.
        assert "setattr(sys.modules[parent]" in result

    def test_registers_stubs_before_population(self, tmp_path: Path) -> None:
        """Bootstrap should register stubs before populating modules."""
        staged_sources = [
            ("chumicro_timing.ticks", "def ticks_ms(): pass"),
            ("chumicro_timing", "from chumicro_timing.ticks import ticks_ms"),
        ]
        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok(): pass")

        result = build_circuitpython_bootstrap(staged_sources, test_file)

        # Stubs should appear before populate calls.
        stub_position = result.index("_register_stub(")
        populate_position = result.index("_populate_module(")
        assert stub_position < populate_position

    def test_resolves_relative_imports_in_source(
        self, tmp_path: Path,
    ) -> None:
        """Bootstrap should rewrite relative imports to absolute."""
        staged_sources = [
            ("mypkg.sub", "x = 1"),
            ("mypkg", "from .sub import x"),
        ]
        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok(): pass")

        result = build_circuitpython_bootstrap(staged_sources, test_file)

        assert "from mypkg.sub import x" in result

    def test_does_not_call_sys_exit(self, tmp_path: Path) -> None:
        """Bootstrap should not call sys.exit (breaks mpremote cleanup)."""
        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok(): pass")

        result = build_circuitpython_bootstrap([], test_file)

        assert "sys.exit" not in result

    def test_generated_code_is_valid_python(self, tmp_path: Path) -> None:
        """The generated bootstrap should parse as valid Python."""
        staged_sources = [
            ("chumicro_timing", "x = 1\ny = 'hello'"),
            ("chumicro_timing.ticks", "def ticks_ms():\n    return 0"),
        ]
        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok():\n    assert True\n")

        result = build_circuitpython_bootstrap(
            staged_sources, test_file, name_filter="test_ok",
        )

        # compile() will raise SyntaxError if the code is invalid.
        compile(result, "<bootstrap>", "exec")

    def test_handles_source_with_special_characters(
        self, tmp_path: Path,
    ) -> None:
        """Bootstrap should safely embed source with quotes and backslashes."""
        staged_sources = [
            ("mypkg", "x = 'single'\ny = \"double\"\nz = '''triple'''"),
        ]
        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok(): pass")

        result = build_circuitpython_bootstrap(staged_sources, test_file)

        # Should be valid Python despite tricky source content.
        compile(result, "<bootstrap>", "exec")


class TestEscapeSource:
    """Tests for _escape_source helper."""

    def test_escapes_simple_string(self) -> None:
        """Should produce a valid Python string literal."""
        result = _escape_source("x = 1")
        assert eval(result) == "x = 1"

    def test_escapes_quotes(self) -> None:
        """Should handle embedded quotes."""
        result = _escape_source("x = 'hello \"world\"'")
        assert eval(result) == "x = 'hello \"world\"'"

    def test_escapes_backslashes(self) -> None:
        """Should handle backslash characters."""
        result = _escape_source("path = 'C:\\\\Users'")
        assert eval(result) == "path = 'C:\\\\Users'"

    def test_escapes_newlines(self) -> None:
        """Should handle multiline source."""
        source = "def foo():\n    return 1\n"
        result = _escape_source(source)
        assert eval(result) == source

    def test_escapes_triple_quotes(self) -> None:
        """Should handle triple-quoted strings in source."""
        source = '"""docstring"""\nx = 1'
        result = _escape_source(source)
        assert eval(result) == source


class TestResolveRelativeImports:
    """Tests for _resolve_relative_imports."""

    def test_rewrites_from_dot_module(self) -> None:
        """Should rewrite ``from .sub import x`` to absolute."""
        source = "from .sub import x"
        result = _resolve_relative_imports(source, "mypkg")
        assert result == "from mypkg.sub import x"

    def test_rewrites_from_dot_import(self) -> None:
        """Should rewrite ``from . import x`` to absolute."""
        source = "from . import x"
        result = _resolve_relative_imports(source, "mypkg")
        assert result == "from mypkg import x"

    def test_preserves_absolute_imports(self) -> None:
        """Should not touch absolute imports."""
        source = "from os.path import join"
        result = _resolve_relative_imports(source, "mypkg")
        assert result == source

    def test_preserves_indented_relative_imports(self) -> None:
        """Should handle indented relative imports (e.g. in if blocks)."""
        source = "    from .sub import x"
        result = _resolve_relative_imports(source, "mypkg")
        assert result == "    from mypkg.sub import x"

    def test_handles_multiple_relative_imports(self) -> None:
        """Should rewrite all relative imports in the source."""
        source = "from .alpha import a\nfrom .beta import b"
        result = _resolve_relative_imports(source, "pkg")
        assert "from pkg.alpha import a" in result
        assert "from pkg.beta import b" in result
