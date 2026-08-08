"""Tests for the FileSource protocol and its three built-ins."""

from __future__ import annotations

from pathlib import Path

import pytest
from chumicro_deploy import (
    DirectorySource,
    FileMapSource,
    FileSource,
    ImportGraphSource,
    UnresolvedImportError,
)
from chumicro_deploy.recovery import classify_deploy_failure
from chumicro_deploy.recovery_kind import DeployFailureKind


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
        # helpers.greeting is), so ImportGraphSource should leave it out.
        assert "/lib/helpers/__init__.py" not in files

    def test_builtin_modules_are_skipped_not_shipped(self, tmp_path: Path):
        entrypoint, libs = self._scaffold(tmp_path)
        source = ImportGraphSource(entrypoint, search_paths=[libs])
        # sys is a device-runtime built-in on the allowlist: it resolves
        # to no search-path file, but the walk treats it as external and
        # ships nothing for it rather than refusing the deploy.
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

    def test_declared_data_file_is_staged_alongside_its_module(
        self, tmp_path: Path,
    ):
        """A module declaring ``__chumicro_data_files__`` gets its sibling
        data files staged, since the import walk can't see the runtime
        ``open`` of them (the CA-bundle .der regression)."""
        libs = tmp_path / "libs"
        libs.mkdir()
        pkg = libs / "netpkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("import netpkg.bundle\n")
        (pkg / "bundle.py").write_text(
            "__chumicro_data_files__ = ('roots.der',)\n"
            "def load():\n"
            "    return open('roots.der', 'rb').read()\n",
        )
        (pkg / "roots.der").write_bytes(b"\x00\x01\x02DERDATA")
        entrypoint = tmp_path / "app.py"
        entrypoint.write_text("import netpkg\n")
        source = ImportGraphSource(entrypoint, search_paths=[libs])
        files = source.files()
        assert "/lib/netpkg/bundle.py" in files
        assert "/lib/netpkg/roots.der" in files
        assert files["/lib/netpkg/roots.der"] == b"\x00\x01\x02DERDATA"

    def test_data_files_inherit_their_modules_runtime_marker(
        self, tmp_path: Path,
    ):
        """A runtime-marked module's declared data files ship only to
        that runtime: the module-level filter drops the module before
        its ``__chumicro_data_files__`` are read, so a CP deploy stages
        neither the MP-only module nor its .der while an MP deploy
        stages both.  Pins the cross-channel selection contract (the
        walker side; bundle_manager pins its own)."""
        libs = tmp_path / "libs"
        libs.mkdir()
        pkg = libs / "netpkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text(
            "try:\n"
            "    import netpkg.bundle\n"
            "except ImportError:\n"
            "    pass\n",
        )
        (pkg / "bundle.py").write_text(
            "__chumicro_runtimes__ = ('micropython',)\n"
            "__chumicro_data_files__ = ('roots.der',)\n",
        )
        (pkg / "roots.der").write_bytes(b"DER")
        entrypoint = tmp_path / "app.py"
        entrypoint.write_text("import netpkg\n")

        cp = ImportGraphSource(
            entrypoint, search_paths=[libs], target_runtime="circuitpython",
        ).files()
        assert "/lib/netpkg/bundle.py" not in cp
        assert "/lib/netpkg/roots.der" not in cp

        mp = ImportGraphSource(
            entrypoint, search_paths=[libs], target_runtime="micropython",
        ).files()
        assert "/lib/netpkg/bundle.py" in mp
        assert "/lib/netpkg/roots.der" in mp

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
        # The check has to be case-strict.  On macOS APFS the lookup
        # ``Heartbeat.py`` succeeds against the real ``heartbeat.py``,
        # and the regression bug staged that path.
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
        # broken module still ships as bytes, its imports just don't
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
        ``foo/__init__.py``.  The walker probes ``foo.not_a_module`` as a
        speculative submodule, which resolves to no file.  Because the probe
        is never *required* (only the real ``foo`` import is), the miss is
        dropped silently and does not refuse the deploy.
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
        """``from foo import *`` should not probe ``foo.*`` as a name."""
        libs = tmp_path / "libs"
        libs.mkdir()
        pkg = libs / "foo"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("X = 1\n")
        entrypoint = tmp_path / "app.py"
        entrypoint.write_text("from foo import *\n")

        # Just confirms construction does not raise on the literal "*".
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
        # pkg/__init__.py uses a relative import (level=1).  The walker
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
        """Default behavior preserved, no filtering."""
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
        """Markers only filter ``.py`` files.  Data files always ship."""
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
        # cp_dependency was reachable only via cp_only, also dropped.
        assert "/lib/cp_dependency.py" not in files


class TestDirectorySourceExcludesTestSupport:
    """A `DirectorySource` (app / product deploy path) never carries a
    test-support module onto the device.
    """

    def test_testing_module_dropped(self, tmp_path: Path) -> None:
        root = tmp_path / "project"
        package = root / "chumicro_demo"
        package.mkdir(parents=True)
        (root / "code.py").write_text("import chumicro_demo\n")
        (package / "__init__.py").write_text("VALUE = 1\n")
        (package / "testing.py").write_text(
            "__chumicro_test_support__ = True\n\nclass FakeThing:\n    pass\n",
        )
        source = DirectorySource(root, entrypoint="/code.py")
        files = source.files()
        assert "/code.py" in files
        assert "/chumicro_demo/__init__.py" in files
        # The fake never ships to a product/app deploy.
        assert "/chumicro_demo/testing.py" not in files


class TestImportGraphSourceRefusesUnresolvedImports:
    """An import that ships nowhere and isn't a device built-in refuses the
    deploy at construction instead of shipping an ImportError-at-boot.
    """

    def test_unregistered_chumicro_import_refused_with_named_file_and_module(
        self, tmp_path: Path,
    ) -> None:
        """An unregistered library import names the importing file and module."""
        libs = tmp_path / "libs"
        libs.mkdir()
        entrypoint = tmp_path / "app.py"
        entrypoint.write_text("import chumicro_missing\n")
        with pytest.raises(UnresolvedImportError) as caught:
            ImportGraphSource(entrypoint, search_paths=[libs])
        message = str(caught.value)
        assert "chumicro_missing" in message
        assert "app.py" in message
        # Collect-all-then-fail exposes the offending pair on the exception.
        assert caught.value.unresolved == [(entrypoint, "chumicro_missing")]

    def test_genuine_stdlib_builtin_passes(self, tmp_path: Path) -> None:
        """A pure-stdlib entrypoint (struct, sys) deploys without refusal."""
        libs = tmp_path / "libs"
        libs.mkdir()
        entrypoint = tmp_path / "app.py"
        entrypoint.write_text("import struct\nimport sys\nimport json\n")
        source = ImportGraphSource(entrypoint, search_paths=[libs])
        # None of the built-ins ship as files; the entrypoint alone lands.
        assert source.files() == {"/code.py": entrypoint.read_bytes()}

    def test_platform_only_builtins_pass(self, tmp_path: Path) -> None:
        """Platform built-ins (wifi, microcontroller, board, machine) pass.

        These resolve against the runtime on-device, never against the host
        search path, so the allowlist must accept them across runtimes.
        """
        libs = tmp_path / "libs"
        libs.mkdir()
        entrypoint = tmp_path / "app.py"
        entrypoint.write_text(
            "import wifi\n"
            "import microcontroller\n"
            "import board\n"
            "import machine\n"
        )
        source = ImportGraphSource(entrypoint, search_paths=[libs])
        assert source.files() == {"/code.py": entrypoint.read_bytes()}

    def test_import_error_guarded_import_is_not_refused(
        self, tmp_path: Path,
    ) -> None:
        """A try/except ImportError fallback ships without refusal.

        The guarded module resolves to no file and is not a built-in, but the
        guard marks it a deliberate optional fallback, so the walk neither
        refuses the deploy nor ships a file for it.
        """
        libs = tmp_path / "libs"
        libs.mkdir()
        entrypoint = tmp_path / "app.py"
        entrypoint.write_text(
            "try:\n"
            "    import optional_accelerator\n"
            "except ImportError:\n"
            "    optional_accelerator = None\n"
        )
        source = ImportGraphSource(entrypoint, search_paths=[libs])
        assert "optional_accelerator" not in " ".join(source.files())

    def test_guarded_from_import_tuple_handler_is_not_refused(
        self, tmp_path: Path,
    ) -> None:
        """``except (ImportError, OSError)`` still exempts the guarded import."""
        libs = tmp_path / "libs"
        libs.mkdir()
        entrypoint = tmp_path / "app.py"
        entrypoint.write_text(
            "try:\n"
            "    from optional_pkg import thing\n"
            "except (ImportError, OSError):\n"
            "    thing = None\n"
        )
        source = ImportGraphSource(entrypoint, search_paths=[libs])
        assert "optional_pkg" not in " ".join(source.files())

    def test_aliased_exception_tuple_guard_is_not_refused(
        self, tmp_path: Path,
    ) -> None:
        """``except guarded:`` against a named tuple still reads as a guard.

        Binding the exception tuple to a name is ordinary Python, and
        ``chumicro_mqtt.client`` writes its hardware-UID fallback chain that
        way.  Before the handler check resolved aliases, the ``ast.Name`` said
        nothing on its own and every mqtt deploy was refused over the guarded
        ``import uuid``.
        """
        libs = tmp_path / "libs"
        libs.mkdir()
        entrypoint = tmp_path / "app.py"
        entrypoint.write_text(
            "guarded = (ImportError, AttributeError, OSError)\n"
            "try:\n"
            "    import optional_uid\n"
            "except guarded:\n"
            "    optional_uid = None\n"
        )
        source = ImportGraphSource(entrypoint, search_paths=[libs])
        assert "optional_uid" not in " ".join(source.files())

    def test_function_local_aliased_guard_is_not_refused(
        self, tmp_path: Path,
    ) -> None:
        """The alias binding is found wherever it sits, including in a def."""
        libs = tmp_path / "libs"
        libs.mkdir()
        entrypoint = tmp_path / "app.py"
        entrypoint.write_text(
            "def client_id():\n"
            "    guarded = (ImportError, OSError)\n"
            "    try:\n"
            "        import optional_uid\n"
            "    except guarded:\n"
            "        return None\n"
            "    return optional_uid\n"
        )
        source = ImportGraphSource(entrypoint, search_paths=[libs])
        assert "optional_uid" not in " ".join(source.files())

    def test_alias_bound_to_unrelated_tuple_still_refuses(
        self, tmp_path: Path,
    ) -> None:
        """An alias that never names ImportError exempts nothing."""
        libs = tmp_path / "libs"
        libs.mkdir()
        entrypoint = tmp_path / "app.py"
        entrypoint.write_text(
            "guarded = (ValueError, TypeError)\n"
            "try:\n"
            "    import missing_thing\n"
            "except guarded:\n"
            "    missing_thing = None\n"
        )
        with pytest.raises(UnresolvedImportError) as caught:
            ImportGraphSource(entrypoint, search_paths=[libs])
        assert caught.value.unresolved == [(entrypoint, "missing_thing")]

    def test_alias_rebound_to_unrelated_tuple_still_refuses(
        self, tmp_path: Path,
    ) -> None:
        """A rebinding that stops catching ImportError poisons the alias.

        Resolving aliases must not guess in the permissive direction: were the
        first binding taken on its own, the deploy would ship an import that
        raises at boot on the device.
        """
        libs = tmp_path / "libs"
        libs.mkdir()
        entrypoint = tmp_path / "app.py"
        entrypoint.write_text(
            "guarded = (ImportError, OSError)\n"
            "guarded = (ValueError,)\n"
            "try:\n"
            "    import missing_thing\n"
            "except guarded:\n"
            "    missing_thing = None\n"
        )
        with pytest.raises(UnresolvedImportError) as caught:
            ImportGraphSource(entrypoint, search_paths=[libs])
        assert caught.value.unresolved == [(entrypoint, "missing_thing")]

    def test_bare_except_guard_exempts_import(self, tmp_path: Path) -> None:
        """A bare ``except:`` catches everything, so its import is optional."""
        libs = tmp_path / "libs"
        libs.mkdir()
        entrypoint = tmp_path / "app.py"
        entrypoint.write_text(
            "try:\n"
            "    import optional_thing\n"
            "except:  # noqa: E722 — deliberate catch-all under test\n"
            "    optional_thing = None\n"
        )
        source = ImportGraphSource(entrypoint, search_paths=[libs])
        assert "optional_thing" not in " ".join(source.files())

    def test_non_importerror_guard_still_refuses(self, tmp_path: Path) -> None:
        """A ``try/except ValueError`` does NOT exempt a missing import.

        Only ImportError-family guards mark an import optional.  An
        unresolved import inside an unrelated guard still ships nowhere and
        must be refused.
        """
        libs = tmp_path / "libs"
        libs.mkdir()
        entrypoint = tmp_path / "app.py"
        entrypoint.write_text(
            "try:\n"
            "    import chumicro_missing\n"
            "except ValueError:\n"
            "    chumicro_missing = None\n"
        )
        with pytest.raises(UnresolvedImportError) as caught:
            ImportGraphSource(entrypoint, search_paths=[libs])
        assert caught.value.unresolved == [(entrypoint, "chumicro_missing")]

    def test_dotted_exception_guard_still_refuses(self, tmp_path: Path) -> None:
        """An ``except module.SomeError`` handler does NOT exempt the import.

        A dotted (attribute) exception type can't be confirmed as
        ImportError, so the walker treats the guard as unrelated and refuses
        the unresolved import.
        """
        libs = tmp_path / "libs"
        libs.mkdir()
        entrypoint = tmp_path / "app.py"
        entrypoint.write_text(
            "import errno\n"
            "try:\n"
            "    import chumicro_missing\n"
            "except errno.Whatever:\n"
            "    chumicro_missing = None\n"
        )
        with pytest.raises(UnresolvedImportError) as caught:
            ImportGraphSource(entrypoint, search_paths=[libs])
        assert caught.value.unresolved == [(entrypoint, "chumicro_missing")]

    def test_transitive_unregistered_import_refused_names_importing_file(
        self, tmp_path: Path,
    ) -> None:
        """A registered lib reaching an unregistered transitive is refused,
        and the error names the transitive's importing file, not the entrypoint.
        """
        libs = tmp_path / "libs"
        libs.mkdir()
        client = libs / "chumicro_thing"
        client.mkdir()
        (client / "__init__.py").write_text("import chumicro_unregistered\n")
        entrypoint = tmp_path / "app.py"
        entrypoint.write_text("import chumicro_thing\n")
        with pytest.raises(UnresolvedImportError) as caught:
            ImportGraphSource(entrypoint, search_paths=[libs])
        importing_file, module_name = caught.value.unresolved[0]
        assert module_name == "chumicro_unregistered"
        # The file that wrote the broken import is the library __init__,
        # not the entrypoint.
        assert importing_file == client / "__init__.py"

    def test_collect_all_then_fail_reports_every_missing_module(
        self, tmp_path: Path,
    ) -> None:
        """Two distinct unresolved imports both surface in one refusal."""
        libs = tmp_path / "libs"
        libs.mkdir()
        entrypoint = tmp_path / "app.py"
        entrypoint.write_text(
            "import chumicro_first_missing\n"
            "import chumicro_second_missing\n"
        )
        with pytest.raises(UnresolvedImportError) as caught:
            ImportGraphSource(entrypoint, search_paths=[libs])
        missing = {module for _file, module in caught.value.unresolved}
        assert missing == {"chumicro_first_missing", "chumicro_second_missing"}

    def test_from_import_of_unregistered_module_refused(
        self, tmp_path: Path,
    ) -> None:
        """``from chumicro_missing import x`` refuses on the module, not the alias.

        The real ``chumicro_missing`` module is required and unresolved; the
        speculative ``chumicro_missing.x`` probe is not separately reported.
        """
        libs = tmp_path / "libs"
        libs.mkdir()
        entrypoint = tmp_path / "app.py"
        entrypoint.write_text("from chumicro_missing import helper\n")
        with pytest.raises(UnresolvedImportError) as caught:
            ImportGraphSource(entrypoint, search_paths=[libs])
        missing = [module for _file, module in caught.value.unresolved]
        assert missing == ["chumicro_missing"]

    def test_required_import_not_masked_by_prior_alias_probe(
        self, tmp_path: Path,
    ) -> None:
        """A broken ``import foo.bar`` is refused even after a probe of the
        same dotted name.

        ``from foo import bar`` queues a non-required ``foo.bar`` probe that
        resolves to nothing.  A later real ``import foo.bar`` of the same
        unresolved name must still be refused — the required check runs ahead
        of the visited-set dedup so the probe can't swallow it.
        """
        libs = tmp_path / "libs"
        libs.mkdir()
        foo = libs / "chumicro_foo"
        foo.mkdir()
        (foo / "__init__.py").write_text("")
        entrypoint = tmp_path / "app.py"
        entrypoint.write_text(
            "from chumicro_foo import bar\n"
            "import chumicro_foo.bar\n"
        )
        with pytest.raises(UnresolvedImportError) as caught:
            ImportGraphSource(entrypoint, search_paths=[libs])
        assert [
            module for _file, module in caught.value.unresolved
        ] == ["chumicro_foo.bar"]

    def test_refusal_classifies_to_unresolved_import_kind(
        self, tmp_path: Path,
    ) -> None:
        """The refusal routes through the recovery taxonomy, not UNKNOWN."""
        libs = tmp_path / "libs"
        libs.mkdir()
        entrypoint = tmp_path / "app.py"
        entrypoint.write_text("import chumicro_missing\n")
        with pytest.raises(UnresolvedImportError) as caught:
            ImportGraphSource(entrypoint, search_paths=[libs])
        assert (
            classify_deploy_failure(caught.value)
            is DeployFailureKind.UNRESOLVED_IMPORT
        )

    def test_unresolved_imports_accessor_empty_on_success(
        self, tmp_path: Path,
    ) -> None:
        """A successfully-built source reports no unresolved imports."""
        libs = tmp_path / "libs"
        libs.mkdir()
        (libs / "helper.py").write_text("X = 1\n")
        entrypoint = tmp_path / "app.py"
        entrypoint.write_text("import helper\nimport sys\n")
        source = ImportGraphSource(entrypoint, search_paths=[libs])
        assert source.unresolved_imports() == []
