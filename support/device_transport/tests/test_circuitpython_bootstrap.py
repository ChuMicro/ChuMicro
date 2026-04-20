"""Tests for the CircuitPython bootstrap code generator."""

from __future__ import annotations

from pathlib import Path

import pytest
from chumicro_device_transport.circuitpython_bootstrap import (
    CircuitpythonBootstrapTooLargeError,
    _escape_source,
    _prepare_inline_source,
    build_circuitpython_bootstrap,
    build_circuitpython_bootstrap_scripts,
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

        assert "_m='chumicro_timing'" in result
        assert "_m='chumicro_timing.ticks'" in result
        assert "_populate_module(_m,_s)" in result

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
        assert "setattr(sys.modules[parts[0]],parts[1]" in result

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

    def test_chunked_scripts_split_large_payloads(self, tmp_path: Path) -> None:
        """Large RAM-mode payloads should be split into multiple scripts."""
        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok(): pass")
        staged_sources = [
            (f"chumicro_massive_{index}", "x = 1\n" * 600)
            for index in range(4)
        ]

        scripts = build_circuitpython_bootstrap_scripts(
            staged_sources,
            test_file,
            max_chunk_size_bytes=10 * 1024,
        )

        assert len(scripts) > 2
        assert all(
            len(script.encode("utf-8")) <= 10 * 1024
            for script in scripts
        )

    def test_chunked_scripts_are_valid_python(
        self, tmp_path: Path,
    ) -> None:
        """Each generated chunk should parse on its own."""
        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok(): pass")
        scripts = build_circuitpython_bootstrap_scripts(
            [
                (f"chumicro_massive_{index}", "x = 1\n" * 400)
                for index in range(3)
            ],
            test_file,
            max_chunk_size_bytes=8 * 1024,
        )

        for script in scripts:
            compile(script, "<bootstrap-chunk>", "exec")

    def test_chunked_scripts_retry_deferred_imports(self, tmp_path: Path) -> None:
        """The final chunk should retry deferred imports before running tests."""
        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok(): pass")

        scripts = build_circuitpython_bootstrap_scripts([], test_file)

        assert scripts[-1].startswith("_retry_deferred()")

    def test_raises_when_single_chunk_cannot_fit_budget(
        self, tmp_path: Path,
    ) -> None:
        """A too-small live budget should fail before raw REPL execution."""
        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok(): pass")

        with pytest.raises(
            CircuitpythonBootstrapTooLargeError,
            match="live RAM budget",
        ):
            build_circuitpython_bootstrap_scripts(
                [("chumicro_massive", "x = 1\n" * 20)],
                test_file,
                max_chunk_size_bytes=64,
            )

    def test_population_block_does_not_duplicate_embedded_source(
        self, tmp_path: Path,
    ) -> None:
        """Each module source should appear once in its population block."""
        test_file = tmp_path / "test_example.py"
        module_source = "def helper():\n    return 'value'\n"
        test_file.write_text("def test_ok(): pass")

        result = build_circuitpython_bootstrap(
            [("chumicro_sample", module_source)],
            test_file,
        )

        prepared_source = _prepare_inline_source(module_source)
        assert result.count(repr(prepared_source)) == 1

    def test_strips_comments_and_docstrings_from_staged_source(
        self, tmp_path: Path,
    ) -> None:
        """Staged library source should be minified before inline embedding."""
        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok(): pass")
        staged_source = (
            '"""module doc"""\n'
            '# top-level comment\n'
            'def helper():\n'
            '    """function doc"""\n'
            '    value = 1  # inline comment\n'
            '    return value\n'
        )

        result = build_circuitpython_bootstrap(
            [("chumicro_sample", staged_source)],
            test_file,
        )

        assert "module doc" not in result
        assert "top-level comment" not in result
        assert "function doc" not in result

    def test_docstring_only_classes_remain_valid_after_minification(
        self, tmp_path: Path,
    ) -> None:
        """Stripping class docstrings should still leave syntactically valid code."""
        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok(): pass")
        staged_source = 'class OnlyDoc:\n    """doc"""\n'

        result = build_circuitpython_bootstrap(
            [("chumicro_sample", staged_source)],
            test_file,
        )

        compile(result, "<bootstrap>", "exec")
        assert repr("class OnlyDoc:\n    pass") in result


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
