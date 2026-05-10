"""Tests for the FileSource protocol and its three built-ins."""

from __future__ import annotations

from pathlib import Path

import pytest
from chumicro_deploy import (
    DirectorySource,
    FileMapSource,
    FileSource,
    ImportGraphSource,
)


class TestFileSourceProtocol:
    """FileSource is runtime-checkable and accepts duck-typed implementations."""

    def test_all_builtins_satisfy_protocol(self, tmp_path: Path):
        file_map = FileMapSource({"/code.py": "print(1)"}, entrypoint="/code.py")
        assert isinstance(file_map, FileSource)

        directory_root = tmp_path / "pkg"
        directory_root.mkdir()
        (directory_root / "code.py").write_text("print(2)")
        directory_source = DirectorySource(directory_root, entrypoint="/code.py")
        assert isinstance(directory_source, FileSource)

        entrypoint_file = tmp_path / "app.py"
        entrypoint_file.write_text("print(3)")
        graph_source = ImportGraphSource(entrypoint_file, search_paths=[])
        assert isinstance(graph_source, FileSource)

    def test_custom_implementation_satisfies_protocol(self):
        class MySource:
            def files(self) -> dict[str, bytes]:
                return {"/code.py": b"print(4)"}

            def entrypoint(self) -> str:
                return "/code.py"

        assert isinstance(MySource(), FileSource)


class TestFileMapSource:
    def test_string_values_encoded_to_utf8(self):
        source = FileMapSource(
            {"/code.py": "print('héllo')"}, entrypoint="/code.py"
        )
        assert source.files() == {"/code.py": "print('héllo')".encode()}

    def test_bytes_values_pass_through(self):
        source = FileMapSource(
            {"/blob.bin": b"\x00\x01\x02\xff"}, entrypoint="/blob.bin"
        )
        assert source.files() == {"/blob.bin": b"\x00\x01\x02\xff"}

    def test_mixed_string_and_bytes(self):
        source = FileMapSource(
            {"/a.py": "text", "/b.bin": b"\xde\xad"}, entrypoint="/a.py"
        )
        assert source.files() == {
            "/a.py": b"text",
            "/b.bin": b"\xde\xad",
        }

    def test_entrypoint_must_be_in_files(self):
        with pytest.raises(ValueError, match="entrypoint"):
            FileMapSource({"/code.py": "x"}, entrypoint="/missing.py")

    def test_files_returns_copy(self):
        source = FileMapSource({"/code.py": "x"}, entrypoint="/code.py")
        mutated = source.files()
        mutated["/injected.py"] = b"bad"
        # Second call is untouched.
        assert "/injected.py" not in source.files()

    def test_entrypoint_matches_construction(self):
        source = FileMapSource(
            {"/app.py": "x", "/lib/helper.py": "y"}, entrypoint="/app.py"
        )
        assert source.entrypoint() == "/app.py"


class TestDirectorySource:
    def _make_tree(self, root: Path) -> None:
        (root / "code.py").write_text("print('entry')")
        lib_dir = root / "lib"
        lib_dir.mkdir()
        (lib_dir / "helper.py").write_text("print('helper')")
        nested = lib_dir / "nested"
        nested.mkdir()
        (nested / "deep.py").write_text("print('deep')")

    def test_walks_directory(self, tmp_path: Path):
        self._make_tree(tmp_path)
        source = DirectorySource(tmp_path, entrypoint="/code.py")
        files = source.files()
        assert files == {
            "/code.py": b"print('entry')",
            "/lib/helper.py": b"print('helper')",
            "/lib/nested/deep.py": b"print('deep')",
        }

    def test_applies_resource_prefix(self, tmp_path: Path):
        self._make_tree(tmp_path)
        source = DirectorySource(
            tmp_path, entrypoint="/pkg/code.py", resource_prefix="/pkg"
        )
        assert "/pkg/code.py" in source.files()
        assert "/pkg/lib/helper.py" in source.files()

    def test_excludes_default_artifacts(self, tmp_path: Path):
        self._make_tree(tmp_path)
        cache_dir = tmp_path / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "artifact.pyc").write_bytes(b"compiled")
        source = DirectorySource(tmp_path, entrypoint="/code.py")
        files = source.files()
        assert not any("__pycache__" in path for path in files)

    def test_custom_excluded_names_override(self, tmp_path: Path):
        self._make_tree(tmp_path)
        (tmp_path / "keep_me").mkdir()
        (tmp_path / "keep_me" / "kept.py").write_text("ok")
        source = DirectorySource(
            tmp_path,
            entrypoint="/code.py",
            excluded_names=frozenset({"lib"}),
        )
        files = source.files()
        assert "/keep_me/kept.py" in files
        assert not any(path.startswith("/lib/") for path in files)

    def test_missing_root_raises(self, tmp_path: Path):
        with pytest.raises(NotADirectoryError):
            DirectorySource(tmp_path / "nope", entrypoint="/code.py")

    def test_missing_entrypoint_raises(self, tmp_path: Path):
        self._make_tree(tmp_path)
        # DirectorySource walks lazily on the first files() call so
        # construction is cheap for callers that only inspect the
        # entrypoint property.  The entrypoint-vs-tree check fires on
        # the first files() access.
        source = DirectorySource(tmp_path, entrypoint="/not_present.py")
        with pytest.raises(ValueError, match="entrypoint"):
            source.files()

    def test_entrypoint_accessor(self, tmp_path: Path):
        self._make_tree(tmp_path)
        source = DirectorySource(tmp_path, entrypoint="/code.py")
        assert source.entrypoint() == "/code.py"


class TestImportGraphSource:
    def _scaffold(self, tmp_path: Path) -> tuple[Path, Path]:
        """Build: root/app.py imports helpers.greeting and pkg.inner.

        Returns (entrypoint_path, search_path).
        """
        root = tmp_path
        libs = root / "libs"
        libs.mkdir()
        (libs / "helpers").mkdir()
        (libs / "helpers" / "__init__.py").write_text("")
        (libs / "helpers" / "greeting.py").write_text(
            "def hello():\n    return 'hi'\n"
        )
        pkg_dir = libs / "pkg"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("from pkg.inner import X\n")
        (pkg_dir / "inner.py").write_text("X = 1\n")
        entrypoint = root / "app.py"
        entrypoint.write_text(
            "import sys  # stdlib, not on search path\n"
            "from helpers.greeting import hello\n"
            "from pkg import X\n"
            "print(hello(), X)\n"
        )
        return entrypoint, libs

    def test_walks_imports_and_packs_reachable(self, tmp_path: Path):
        entrypoint, libs = self._scaffold(tmp_path)
        source = ImportGraphSource(entrypoint, search_paths=[libs])
        files = source.files()
        assert "/code.py" in files
        assert "/lib/helpers/greeting.py" in files
        assert "/lib/pkg/__init__.py" in files
        assert "/lib/pkg/inner.py" in files
        # helpers/__init__.py is not directly imported (only
        # helpers.greeting is); ImportGraphSource should leave it out.
        assert "/lib/helpers/__init__.py" not in files

    def test_unresolved_modules_are_skipped(self, tmp_path: Path):
        entrypoint, libs = self._scaffold(tmp_path)
        source = ImportGraphSource(entrypoint, search_paths=[libs])
        # sys is a stdlib module, not resolvable against the search
        # path — ImportGraphSource silently skips it rather than
        # raising.
        assert "sys" not in " ".join(source.files())

    def test_extra_modules_forced_in(self, tmp_path: Path):
        entrypoint, libs = self._scaffold(tmp_path)
        (libs / "dynamic_loader.py").write_text("X = 7\n")
        entrypoint.write_text("print('no static imports')\n")
        source = ImportGraphSource(
            entrypoint,
            search_paths=[libs],
            extra_modules=["dynamic_loader"],
        )
        assert "/lib/dynamic_loader.py" in source.files()

    def test_custom_device_entrypoint(self, tmp_path: Path):
        entrypoint, libs = self._scaffold(tmp_path)
        source = ImportGraphSource(
            entrypoint,
            search_paths=[libs],
            device_entrypoint="/main.py",
        )
        assert "/main.py" in source.files()
        assert source.entrypoint() == "/main.py"

    def test_custom_resource_prefix(self, tmp_path: Path):
        entrypoint, libs = self._scaffold(tmp_path)
        source = ImportGraphSource(
            entrypoint,
            search_paths=[libs],
            resource_prefix="/pkg",
        )
        files = source.files()
        assert "/pkg/helpers/greeting.py" in files

    def test_missing_entrypoint_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            ImportGraphSource(tmp_path / "nope.py", search_paths=[])

    def test_missing_search_path_raises(self, tmp_path: Path):
        entrypoint = tmp_path / "app.py"
        entrypoint.write_text("print(1)")
        with pytest.raises(NotADirectoryError):
            ImportGraphSource(entrypoint, search_paths=[tmp_path / "missing"])

    def test_class_import_does_not_pull_in_case_mismatched_module(
        self, tmp_path: Path,
    ):
        """``from pkg import Heartbeat`` (a *class* in ``heartbeat.py``)
        must not be treated as a submodule import.

        On case-insensitive host filesystems (default macOS APFS, NTFS),
        ``Path('pkg/Heartbeat.py').is_file()`` returns True when only
        ``pkg/heartbeat.py`` exists on disk.  Without case-strict
        existence checking, :class:`ImportGraphSource` would resolve
        the class import as if it pointed at a ``Heartbeat.py`` module
        and stage a wrong-case path that fails on the device's case-
        sensitive filesystem (LittleFS on MicroPython).

        Test scaffolds the exact "class lives in a lowercase module"
        shape (``chumicro_timing.heartbeat.Heartbeat``) and asserts:

        - The submodule ``heartbeat.py`` lands at the on-disk casing.
        - No ``Heartbeat.py`` device path is created from the class
          import alias.
        """
        libs = tmp_path / "libs"
        libs.mkdir()
        pkg = libs / "timing"
        pkg.mkdir()
        (pkg / "__init__.py").write_text(
            "from timing.heartbeat import Heartbeat\n",
        )
        (pkg / "heartbeat.py").write_text(
            "class Heartbeat:\n    pass\n",
        )
        entrypoint = tmp_path / "app.py"
        entrypoint.write_text(
            "from timing import Heartbeat\n"
            "print(Heartbeat)\n"
        )
        source = ImportGraphSource(entrypoint, search_paths=[libs])
        files = source.files()
        # Real submodule lands with on-disk casing.
        assert "/lib/timing/heartbeat.py" in files
        assert "/lib/timing/__init__.py" in files
        # Class-import alias does NOT produce a wrong-case device path.
        # The check has to be case-strict — on macOS APFS the lookup
        # ``Heartbeat.py`` succeeds against the real ``heartbeat.py``;
        # the regression bug staged that path.
        assert "/lib/timing/Heartbeat.py" not in files

    def test_syntax_error_in_reachable_module_is_skipped(self, tmp_path: Path):
        libs = tmp_path / "libs"
        libs.mkdir()
        (libs / "broken.py").write_text("def foo(:\n")  # invalid syntax
        (libs / "ok.py").write_text("X = 2\n")
        entrypoint = tmp_path / "app.py"
        entrypoint.write_text(
            "import broken\n"
            "import ok\n"
        )
        source = ImportGraphSource(entrypoint, search_paths=[libs])
        files = source.files()
        # broken module still ships as bytes; its imports just don't
        # contribute further walk targets.
        assert "/lib/broken.py" in files
        assert "/lib/ok.py" in files

    def test_from_import_resolves_named_submodule(self, tmp_path: Path):
        """``from foo._adapters import mp`` ships ``foo/_adapters/mp.py``.

        Without explicit aliased-submodule probing, the walker
        captures the package (``foo._adapters``) but ignores the
        named alias (``mp``), leaving the runtime-gated adapter off
        the device.  Probing ``foo._adapters.mp`` as a candidate
        submodule plus skipping unresolvable names quietly is the
        smallest fix.
        """
        libs = tmp_path / "libs"
        libs.mkdir()
        pkg = libs / "foo"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        adapters = pkg / "_adapters"
        adapters.mkdir()
        (adapters / "__init__.py").write_text("")
        (adapters / "cp.py").write_text("def connect(): ...\n")
        (adapters / "mp.py").write_text("def connect(): ...\n")

        entrypoint = tmp_path / "app.py"
        entrypoint.write_text(
            "def use_mp():\n"
            "    from foo._adapters import mp\n"
            "    return mp.connect()\n"
        )

        source = ImportGraphSource(entrypoint, search_paths=[libs])
        files = source.files()
        # The submodule named in the from-import lands on device.
        assert "/lib/foo/_adapters/mp.py" in files
        # The package itself rides along.
        assert "/lib/foo/_adapters/__init__.py" in files
        # Siblings that the user code did not name are NOT auto-included.
        assert "/lib/foo/_adapters/cp.py" not in files

    def test_from_import_alias_that_is_not_a_submodule_is_skipped(
        self, tmp_path: Path
    ):
        """``from foo import not_a_module`` doesn't error or over-include.

        ``not_a_module`` is a function/class defined inside
        ``foo/__init__.py``.  The walker probes ``foo.not_a_module``,
        gets a None from ``_resolve_module``, and silently skips —
        the same path stdlib imports take.
        """
        libs = tmp_path / "libs"
        libs.mkdir()
        pkg = libs / "foo"
        pkg.mkdir()
        (pkg / "__init__.py").write_text(
            "def not_a_module():\n"
            "    return 'hi'\n"
        )
        entrypoint = tmp_path / "app.py"
        entrypoint.write_text("from foo import not_a_module\n")

        source = ImportGraphSource(entrypoint, search_paths=[libs])
        files = source.files()
        assert "/lib/foo/__init__.py" in files
        # No bogus ``foo/not_a_module.py`` keys leaked into the file map.
        assert not any("not_a_module" in path for path in files)

    def test_from_import_wildcard_does_not_probe(self, tmp_path: Path):
        """``from foo import *`` shouldn't probe ``foo.*`` as a name."""
        libs = tmp_path / "libs"
        libs.mkdir()
        pkg = libs / "foo"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("X = 1\n")
        entrypoint = tmp_path / "app.py"
        entrypoint.write_text("from foo import *\n")

        # Just confirms construction doesn't raise on the literal "*".
        source = ImportGraphSource(entrypoint, search_paths=[libs])
        assert "/lib/foo/__init__.py" in source.files()

    def test_handles_relative_imports_silently(self, tmp_path: Path):
        libs = tmp_path / "libs"
        libs.mkdir()
        pkg = libs / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("from .inner import X\n")
        (pkg / "inner.py").write_text("X = 1\n")
        entrypoint = tmp_path / "app.py"
        entrypoint.write_text("import pkg\n")
        source = ImportGraphSource(entrypoint, search_paths=[libs])
        # pkg/__init__.py uses a relative import (level=1); the walker
        # must not treat "inner" as a top-level name to resolve.  It
        # still ships pkg/__init__.py itself since pkg was imported
        # from app.py.
        files = source.files()
        assert "/lib/pkg/__init__.py" in files


class TestDirectorySourceTargetRuntime:
    """``target_runtime`` filters wrong-runtime ``.py`` files."""

    def _build_pkg(self, root: Path) -> None:
        pkg = root / "chumicro_pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("# universal\n")
        (pkg / "shared.py").write_text("# universal\n")
        adapters = pkg / "_adapters"
        adapters.mkdir()
        (adapters / "__init__.py").write_text("# universal\n")
        (adapters / "cp.py").write_text(
            '__chumicro_runtimes__ = ("circuitpython",)\n',
        )
        (adapters / "mp.py").write_text(
            '__chumicro_runtimes__ = ("micropython",)\n',
        )
        (adapters / "cpython.py").write_text(
            '__chumicro_runtimes__ = ("cpython",)\n',
        )

    def test_target_runtime_none_ships_everything(self, tmp_path: Path) -> None:
        """Default behavior preserved — no filtering."""
        root = tmp_path / "src"
        root.mkdir()
        self._build_pkg(root)
        source = DirectorySource(root, entrypoint="/chumicro_pkg/__init__.py")
        files = source.files()
        assert "/chumicro_pkg/_adapters/cp.py" in files
        assert "/chumicro_pkg/_adapters/mp.py" in files
        assert "/chumicro_pkg/_adapters/cpython.py" in files

    def test_circuitpython_target_drops_mp_and_cpython(
        self, tmp_path: Path,
    ) -> None:
        root = tmp_path / "src"
        root.mkdir()
        self._build_pkg(root)
        source = DirectorySource(
            root,
            entrypoint="/chumicro_pkg/__init__.py",
            target_runtime="circuitpython",
        )
        files = source.files()
        assert "/chumicro_pkg/_adapters/cp.py" in files
        assert "/chumicro_pkg/_adapters/mp.py" not in files
        assert "/chumicro_pkg/_adapters/cpython.py" not in files
        # Universal files (no marker) still ship.
        assert "/chumicro_pkg/shared.py" in files
        assert "/chumicro_pkg/_adapters/__init__.py" in files

    def test_micropython_target_drops_cp_and_cpython(
        self, tmp_path: Path,
    ) -> None:
        root = tmp_path / "src"
        root.mkdir()
        self._build_pkg(root)
        source = DirectorySource(
            root,
            entrypoint="/chumicro_pkg/__init__.py",
            target_runtime="micropython",
        )
        files = source.files()
        assert "/chumicro_pkg/_adapters/mp.py" in files
        assert "/chumicro_pkg/_adapters/cp.py" not in files
        assert "/chumicro_pkg/_adapters/cpython.py" not in files

    def test_non_python_files_unaffected(self, tmp_path: Path) -> None:
        """Markers only filter ``.py`` files; data files always ship."""
        root = tmp_path / "src"
        root.mkdir()
        (root / "code.py").write_text("# entrypoint\n")
        (root / "ca.pem").write_bytes(b"-----BEGIN CERTIFICATE-----\n")
        source = DirectorySource(
            root, entrypoint="/code.py", target_runtime="circuitpython",
        )
        files = source.files()
        assert "/ca.pem" in files


class TestImportGraphSourceTargetRuntime:
    """``target_runtime`` drops wrong-runtime modules."""

    def _build_workspace(self, tmp_path: Path) -> tuple[Path, Path]:
        libs = tmp_path / "libs"
        libs.mkdir()
        adapters = libs / "_adapters"
        adapters.mkdir()
        (adapters / "__init__.py").write_text("")
        (adapters / "cp.py").write_text(
            '__chumicro_runtimes__ = ("circuitpython",)\n',
        )
        (adapters / "mp.py").write_text(
            '__chumicro_runtimes__ = ("micropython",)\n',
        )
        entrypoint = tmp_path / "code.py"
        entrypoint.write_text(
            "from _adapters import cp\nfrom _adapters import mp\n",
        )
        return entrypoint, libs

    def test_target_runtime_none_ships_both(self, tmp_path: Path) -> None:
        entrypoint, libs = self._build_workspace(tmp_path)
        source = ImportGraphSource(entrypoint, search_paths=[libs])
        files = source.files()
        assert "/lib/_adapters/cp.py" in files
        assert "/lib/_adapters/mp.py" in files

    def test_circuitpython_target_drops_mp(self, tmp_path: Path) -> None:
        entrypoint, libs = self._build_workspace(tmp_path)
        source = ImportGraphSource(
            entrypoint,
            search_paths=[libs],
            target_runtime="circuitpython",
        )
        files = source.files()
        assert "/lib/_adapters/cp.py" in files
        assert "/lib/_adapters/mp.py" not in files

    def test_micropython_target_drops_cp(self, tmp_path: Path) -> None:
        entrypoint, libs = self._build_workspace(tmp_path)
        source = ImportGraphSource(
            entrypoint,
            search_paths=[libs],
            target_runtime="micropython",
        )
        files = source.files()
        assert "/lib/_adapters/mp.py" in files
        assert "/lib/_adapters/cp.py" not in files

    def test_filtered_module_imports_not_walked(self, tmp_path: Path) -> None:
        """A dropped module's imports must not pull more files into the bundle."""
        libs = tmp_path / "libs"
        libs.mkdir()
        cp_only = libs / "cp_only.py"
        cp_only.write_text(
            '__chumicro_runtimes__ = ("circuitpython",)\n'
            "import cp_dependency\n",
        )
        # cp_dependency would be walked if cp_only.py were included.
        (libs / "cp_dependency.py").write_text("# CP-only support module\n")
        entrypoint = tmp_path / "code.py"
        entrypoint.write_text("import cp_only\n")
        source = ImportGraphSource(
            entrypoint,
            search_paths=[libs],
            target_runtime="micropython",
        )
        files = source.files()
        assert "/lib/cp_only.py" not in files
        # cp_dependency was reachable only via cp_only — also dropped.
        assert "/lib/cp_dependency.py" not in files
