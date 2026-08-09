"""Tests for the CircuitPython bootstrap code generator."""

from __future__ import annotations

from pathlib import Path

import pytest
from chumicro_deploy.circuitpython_bootstrap import (
    CircuitpythonBootstrapTooLargeError,
    _derive_module_name,
    _escape_source,
    _prepare_inline_source,
    build_circuitpython_bootstrap_scripts,
    build_circuitpython_deploy_scripts,
)

# Tests below assert against the *combined* bootstrap text, convenient
# for substring checks like "_register_module" / "run_module".  In
# production, the transport executes the chunks one by one
# (`execute_scripts`), but for unit-test substring assertions an
# arbitrary-sized single chunk is the simpler shape.  The 1 MiB
# budget is well over any test fixture's payload.
_UNCAPPED_BUDGET = 1024 * 1024


def _combined_bootstrap_text(
    staged_sources: list[tuple[str, str]],
    test_file: Path,
    *,
    name_filter: str | None = None,
) -> str:
    """Test helper.  Call `_scripts` with a huge budget and join the result.

    Production code never combines the chunks.  The transport executes
    them one by one via ``execute_scripts``.  But unit-test substring
    assertions are easier against the combined text, so this helper
    asks for an effectively-unbounded single chunk.
    """
    return "\n\n".join(build_circuitpython_bootstrap_scripts(
        staged_sources,
        test_file,
        name_filter=name_filter,
        max_chunk_size_bytes=_UNCAPPED_BUDGET,
    ))


class TestBuildCircuitpythonBootstrap:
    """Tests for the combined bootstrap text via :func:`_combined_bootstrap_text`."""

    def test_generates_module_injection(self, tmp_path: Path) -> None:
        """Bootstrap should contain populate calls for each module."""
        staged_sources = [
            ("chumicro_timing", "# timing init"),
            ("chumicro_timing.ticks", "def ticks_ms(): pass"),
        ]
        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok(): pass")

        result = _combined_bootstrap_text(staged_sources, test_file)

        assert "_m='chumicro_timing'" in result
        assert "_m='chumicro_timing.ticks'" in result
        assert "_populate_module(_m,_s)" in result

    def test_includes_module_helpers(self, tmp_path: Path) -> None:
        """Bootstrap should define stub and populate helpers."""
        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok(): pass")

        result = _combined_bootstrap_text([], test_file)

        assert "def _register_stub(module_name):" in result
        assert "def _populate_module(module_name, source_code):" in result
        assert "sys.modules[module_name]" in result

    def test_execs_test_file(self, tmp_path: Path) -> None:
        """Bootstrap should exec the test file source."""
        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_hello(): assert True")

        result = _combined_bootstrap_text([], test_file)

        assert "exec(" in result
        assert "_test_namespace" in result
        assert "def test_hello" in result or "test_hello" in result

    def test_calls_run_module(self, tmp_path: Path) -> None:
        """Bootstrap should call run_module with the test namespace."""
        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok(): pass")

        result = _combined_bootstrap_text([], test_file)

        assert "run_module(_TestModule" in result

    def test_passes_name_filter(self, tmp_path: Path) -> None:
        """Bootstrap should pass name_filter to run_module when set."""
        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok(): pass")

        result = _combined_bootstrap_text(
            [], test_file, name_filter="test_specific",
        )

        assert "name_filter='test_specific'" in result

    def test_name_filter_none_by_default(self, tmp_path: Path) -> None:
        """Bootstrap should pass None for name_filter when not set."""
        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok(): pass")

        result = _combined_bootstrap_text([], test_file)

        assert "name_filter=None" in result

    def test_imports_sys(self, tmp_path: Path) -> None:
        """Bootstrap should import sys for module registration."""
        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok(): pass")

        result = _combined_bootstrap_text([], test_file)

        assert "import sys" in result

    def test_creates_test_module_class(self, tmp_path: Path) -> None:
        """Bootstrap should create a _TestModule class from namespace."""
        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok(): pass")

        result = _combined_bootstrap_text([], test_file)

        assert "class _TestModule:" in result
        assert "setattr(_TestModule" in result

    def test_module_helpers_attach_submodules(
        self, tmp_path: Path,
    ) -> None:
        """Module helpers should attach submodules to parent packages."""
        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok(): pass")

        result = _combined_bootstrap_text(
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

        result = _combined_bootstrap_text(staged_sources, test_file)

        # Stubs should appear before populate calls.
        stub_position = result.index("_register_stub(")
        populate_position = result.index("_populate_module(")
        assert stub_position < populate_position

    def test_does_not_call_sys_exit(self, tmp_path: Path) -> None:
        """Bootstrap should not call sys.exit (breaks mpremote cleanup)."""
        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok(): pass")

        result = _combined_bootstrap_text([], test_file)

        assert "sys.exit" not in result

    def test_generated_code_is_valid_python(self, tmp_path: Path) -> None:
        """The generated bootstrap should parse as valid Python."""
        staged_sources = [
            ("chumicro_timing", "x = 1\ny = 'hello'"),
            ("chumicro_timing.ticks", "def ticks_ms():\n    return 0"),
        ]
        test_file = tmp_path / "test_example.py"
        test_file.write_text("def test_ok():\n    assert True\n")

        result = _combined_bootstrap_text(
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

        result = _combined_bootstrap_text(staged_sources, test_file)

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

        result = _combined_bootstrap_text(
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

        result = _combined_bootstrap_text(
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

        result = _combined_bootstrap_text(
            [("chumicro_sample", staged_source)],
            test_file,
        )

        compile(result, "<bootstrap>", "exec")
        assert repr("class OnlyDoc:\n    pass") in result


class TestBuildCircuitpythonDeployScripts:
    """Tests for build_circuitpython_deploy_scripts, the RAM-mode deploy path."""

    def test_single_file_entrypoint(self) -> None:
        """A one-file deploy produces helpers + empty stubs + final exec."""
        scripts = build_circuitpython_deploy_scripts(
            {"/code.py": b"print('hi')\n"},
            entrypoint="/code.py",
        )
        # Helpers are always the first chunk.  Entrypoint is always last.
        assert "def _register_stub(" in scripts[0]
        assert "_retry_deferred()" in scripts[-1]
        assert "'__main__'" in scripts[-1]
        # With no lib modules the entrypoint source is the one project
        # that has to survive.  Round-trip through repr/eval to assert.
        joined = "\n".join(scripts)
        assert "print('hi')" in joined

    def test_lib_modules_are_injected(self) -> None:
        """Files under /lib/ become importable via sys.modules."""
        scripts = build_circuitpython_deploy_scripts(
            {
                "/code.py": b"from helper import CONSTANT\nprint(CONSTANT)\n",
                "/lib/helper.py": b"CONSTANT = 42\n",
                "/lib/pkg/__init__.py": b"VALUE = 'pkg'\n",
                "/lib/pkg/sub.py": b"from pkg import VALUE\n",
            },
            entrypoint="/code.py",
        )
        joined = "\n".join(scripts)
        assert "_register_stub('helper')" in joined
        assert "_register_stub('pkg')" in joined
        assert "_register_stub('pkg.sub')" in joined
        # Entrypoint must not appear as a registered module.
        assert "_register_stub('code')" not in joined

    def test_non_python_files_are_skipped(self) -> None:
        """Assets (.toml, .json) are not importable, so they're silently skipped."""
        scripts = build_circuitpython_deploy_scripts(
            {
                "/code.py": b"print('ok')\n",
                "/settings.toml": b"[wifi]\nssid = 'net'\n",
                "/data/payload.json": b'{"x": 1}\n',
            },
            entrypoint="/code.py",
        )
        joined = "\n".join(scripts)
        assert "settings" not in joined
        assert "payload" not in joined
        assert "print('ok')" in joined

    def test_decodes_bytes_payload(self) -> None:
        """Both bytes and str inputs round-trip through the builder."""
        scripts = build_circuitpython_deploy_scripts(
            {
                "/code.py": "print('str')\n",  # type: ignore[dict-item]
                "/lib/a.py": b"A = 1\n",
            },
            entrypoint="/code.py",
        )
        joined = "\n".join(scripts)
        assert "print('str')" in joined
        assert "_register_stub('a')" in joined

    def test_missing_entrypoint_raises(self) -> None:
        with pytest.raises(ValueError, match="missing from files"):
            build_circuitpython_deploy_scripts(
                {"/code.py": b"pass"}, entrypoint="/boot.py",
            )

    def test_zero_budget_raises(self) -> None:
        with pytest.raises(ValueError, match="max_chunk_size_bytes"):
            build_circuitpython_deploy_scripts(
                {"/code.py": b"pass"},
                entrypoint="/code.py",
                max_chunk_size_bytes=0,
            )

    def test_too_large_entrypoint_raises(self) -> None:
        giant_source = "x = " + ("'x' * 100\n" * 200)
        with pytest.raises(CircuitpythonBootstrapTooLargeError):
            build_circuitpython_deploy_scripts(
                {"/code.py": giant_source.encode()},
                entrypoint="/code.py",
                max_chunk_size_bytes=256,
            )

    def test_generated_scripts_compile(self) -> None:
        """Every returned script must be syntactically valid Python."""
        scripts = build_circuitpython_deploy_scripts(
            {
                "/code.py": b"from helper import CONSTANT\nprint(CONSTANT)\n",
                "/lib/helper.py": b"CONSTANT = 42\n",
            },
            entrypoint="/code.py",
        )
        for script in scripts:
            compile(script, "<deploy-bootstrap>", "exec")


class TestDeriveModuleName:
    """Tests for _derive_module_name helper."""

    @pytest.mark.parametrize(
        ("device_path", "expected"),
        [
            ("/lib/foo.py", "foo"),
            ("/lib/foo/__init__.py", "foo"),
            ("/lib/foo/bar.py", "foo.bar"),
            ("/lib/foo/bar/baz.py", "foo.bar.baz"),
            ("/foo.py", "foo"),
            ("foo.py", "foo"),  # already-relative paths also accepted
            ("/settings.toml", None),
            ("/data.json", None),
            ("/", None),
            ("/lib/", None),
            ("/lib/foo.txt", None),
        ],
    )
    def test_derivations(
        self, device_path: str, expected: str | None,
    ) -> None:
        assert _derive_module_name(device_path) == expected


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


class TestLazyExportMaterialization:
    """PEP-562 lazy exports must survive the class-as-module pattern."""

    def _run_prelude(self, scripts: list[str]) -> dict:
        """Execute every script but the final test-execution one in a
        shared namespace, the way the raw REPL runs chunks sequentially,
        then resolve the deferred queue the way the final script would."""
        shared: dict = {}
        for script in scripts[:-1]:
            exec(script, shared)
        shared["_retry_deferred"]()
        shared["_materialize_lazy_exports"]()
        return shared

    def test_from_import_shape_materializes(self, tmp_path: Path) -> None:
        """A package lazy-exporting via ``from pkg._impl import Name``
        defers while ``_impl`` is a bare stub and resolves on retry, so
        ``from pkg import Name`` works against the populated module."""
        import sys

        init_source = (
            "__all__ = ['Widget']\n"
            "def __getattr__(name):\n"
            "    if name == 'Widget':\n"
            "        from bootpkglazy._impl import Widget\n"
            "        return Widget\n"
            "    raise AttributeError(name)\n"
        )
        impl_source = "class Widget:\n    pass\n"
        test_file = tmp_path / "test_x.py"
        test_file.write_text("def test_ok(): pass")
        scripts = build_circuitpython_bootstrap_scripts(
            [("bootpkglazy", init_source), ("bootpkglazy._impl", impl_source)],
            test_file,
        )
        try:
            self._run_prelude(scripts)
            module = sys.modules["bootpkglazy"]
            assert isinstance(module.Widget, type)
            assert module.Widget.__name__ == "Widget"
        finally:
            sys.modules.pop("bootpkglazy", None)
            sys.modules.pop("bootpkglazy._impl", None)

    def test_getattr_shape_materializes(self, tmp_path: Path) -> None:
        """A package lazy-exporting via ``import pkg.sub`` + ``getattr``
        (the mqtt / requests / http_server shape) materializes the same
        way: the AttributeError against the bare stub converts to a
        deferral, and the retry resolves it."""
        import sys

        init_source = (
            "__all__ = ['Client']\n"
            "def __getattr__(name):\n"
            "    if name == 'Client':\n"
            "        import bootpkggetattr.client as _client\n"
            "        return _client.Client\n"
            "    raise AttributeError(name)\n"
        )
        client_source = "class Client:\n    pass\n"
        test_file = tmp_path / "test_x.py"
        test_file.write_text("def test_ok(): pass")
        scripts = build_circuitpython_bootstrap_scripts(
            [
                ("bootpkggetattr", init_source),
                ("bootpkggetattr.client", client_source),
            ],
            test_file,
        )
        try:
            self._run_prelude(scripts)
            module = sys.modules["bootpkggetattr"]
            assert module.Client.__name__ == "Client"
        finally:
            sys.modules.pop("bootpkggetattr", None)
            sys.modules.pop("bootpkggetattr.client", None)

    def test_unresolvable_lazy_export_is_left_absent(self, tmp_path: Path) -> None:
        """An ``__all__`` name whose provider is not in the staged set
        stays absent, the way a flash deploy leaves the file off the
        board: the session survives, eager names work, and importing
        the absent name fails at that import with the true message.
        The wifi RAM session hit exactly this — chumicro_config's lazy
        ``config`` resolves from runtime.py, which own-src scoping
        never stages, and the old defer-on-miss shape hung the whole
        session on it."""
        init_source = (
            "__all__ = ['Present', 'Ghost']\n"
            "Present = 1\n"
            "def __getattr__(name):\n"
            "    if name == 'Ghost':\n"
            "        from bootpkgghost._absent import Ghost\n"
            "        return Ghost\n"
            "    raise AttributeError(name)\n"
        )
        test_file = tmp_path / "test_x.py"
        test_file.write_text("def test_ok(): pass")
        scripts = build_circuitpython_bootstrap_scripts(
            [("bootpkgghost", init_source)], test_file,
        )
        import sys

        try:
            self._run_prelude(scripts)
            module = sys.modules["bootpkgghost"]
            assert module.Present == 1
            assert not hasattr(module, "Ghost")
        finally:
            sys.modules.pop("bootpkgghost", None)
