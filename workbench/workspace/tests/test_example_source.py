"""Tests for chumicro_workspace.example_source.

End-to-end against in-tmp-path libraries/<lib>/{src,examples}/ trees
— no real boards, no real network.  Mirrors the test shape used for
project_import_graph_source: stage a fake mono-repo layout, build the
source, assert the on-device file map.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from chumicro_workspace.deploy_source import (
    RUNTIME_CONFIG_DEVICE_PATH,
    WithRuntimeConfig,
)
from chumicro_workspace.example_source import _default_output_path, example_source

# ---------------------------------------------------------------------------
# Helpers — stage a minimal mono-repo with one library + one example
# ---------------------------------------------------------------------------


def _seed_library(
    libs_root: Path,
    name: str,
    *,
    extra_module_body: str = "",
    config_manifest: str = "",
) -> Path:
    """Create ``<libs_root>/<name>/{src/chumicro_<name>,pyproject.toml}``.

    The src tree has one importable module under
    ``chumicro_<name>/__init__.py``; *extra_module_body* lets a test
    override what's in it (e.g. add an import to pull a second lib in).
    The pyproject.toml carries an empty ``[tool.chumicro.config]``
    block so manifest validation runs but accepts everything.
    """
    library_root = libs_root / name
    library_root.mkdir(parents=True)
    src_pkg = library_root / "src" / f"chumicro_{name}"
    src_pkg.mkdir(parents=True)
    body = f"VERSION = '{name}-1.0'\n" + extra_module_body
    (src_pkg / "__init__.py").write_text(body)

    pyproject_body = (
        f"[project]\n"
        f"name = \"chumicro-{name}\"\n"
        f"version = \"0.1.0\"\n"
        f"\n"
        f"[tool.chumicro.config]\n"
        f"required_keys = []\n"
        f"optional_keys = []\n"
    )
    if config_manifest:
        pyproject_body = (
            f"[project]\n"
            f"name = \"chumicro-{name}\"\n"
            f"version = \"0.1.0\"\n"
            f"\n"
            f"{config_manifest}\n"
        )
    (library_root / "pyproject.toml").write_text(pyproject_body)
    return library_root


def _seed_example(
    library_root: Path,
    example_name: str,
    body: str,
    *,
    runtimes_marker: str | None = None,
) -> Path:
    """Create ``<library_root>/examples/<example_name>.py`` with *body*.

    *runtimes_marker* (e.g. ``"circuitpython"``) writes a
    ``__chumicro_runtimes__`` tuple at the top so the runtime filter
    can drop the file from the wrong-runtime case.
    """
    examples = library_root / "examples"
    examples.mkdir(exist_ok=True)
    full_body = body
    if runtimes_marker is not None:
        full_body = f"__chumicro_runtimes__ = ({runtimes_marker!r},)\n" + body
    path = examples / example_name
    path.write_text(full_body)
    return path


def _seed_secrets(workspace_root: Path, body: str = "[wifi]\nssid = 'x'\n") -> Path:
    secrets = workspace_root / "secrets.toml"
    secrets.write_text(body)
    return secrets


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestExampleSourceHappyPath:
    def test_circuitpython_entrypoint_lands_at_code_py(
        self, tmp_path: Path,
    ) -> None:
        """Runtime ``circuitpython`` → on-device entrypoint is ``/code.py``."""
        libs = tmp_path / "libraries"
        timing = _seed_library(libs, "timing")
        _seed_example(
            timing, "circuitpython_blink.py",
            "from chumicro_timing import VERSION\nprint('blink', VERSION)\n",
        )
        secrets = _seed_secrets(tmp_path)

        source = example_source(
            timing, "circuitpython_blink",
            library_roots=[timing],
            runtime="circuitpython",
            secrets_toml=secrets,
            output_path=tmp_path / "out.msgpack",
        )

        assert source.entrypoint() == "/code.py"
        files = source.files()
        assert "/code.py" in files
        assert b"blink" in files["/code.py"]
        # The walked library module lands under /lib/.
        assert "/lib/chumicro_timing/__init__.py" in files

    def test_micropython_entrypoint_lands_at_main_py(
        self, tmp_path: Path,
    ) -> None:
        """Runtime ``micropython`` → on-device entrypoint is ``/main.py``."""
        libs = tmp_path / "libraries"
        timing = _seed_library(libs, "timing")
        _seed_example(timing, "micropython_blink.py", "print('mp blink')\n")
        secrets = _seed_secrets(tmp_path)

        source = example_source(
            timing, "micropython_blink",
            library_roots=[timing],
            runtime="micropython",
            secrets_toml=secrets,
            output_path=tmp_path / "out.msgpack",
        )

        assert source.entrypoint() == "/main.py"
        assert "/main.py" in source.files()

    def test_returns_with_runtime_config_wrapper(
        self, tmp_path: Path,
    ) -> None:
        """The returned source is a ``WithRuntimeConfig`` so deploy-time
        msgpack regeneration + manifest validation come for free."""
        libs = tmp_path / "libraries"
        timing = _seed_library(libs, "timing")
        _seed_example(timing, "blink.py", "pass\n")
        secrets = _seed_secrets(tmp_path)

        source = example_source(
            timing, "blink",
            library_roots=[timing],
            runtime="circuitpython",
            secrets_toml=secrets,
            output_path=tmp_path / "out.msgpack",
        )
        assert isinstance(source, WithRuntimeConfig)


# ---------------------------------------------------------------------------
# Import-graph walk
# ---------------------------------------------------------------------------


class TestImportGraphWalk:
    def test_walks_imports_into_other_libraries(self, tmp_path: Path) -> None:
        """An example importing chumicro_runner pulls runner under /lib/
        even when only the owning library is in *library_roots*'s
        explicit list (the implicit add of *library_root* itself
        plus any other listed root combine)."""
        libs = tmp_path / "libraries"
        runner = _seed_library(libs, "runner")
        timing = _seed_library(
            libs, "timing",
            extra_module_body="from chumicro_runner import VERSION as _R\n",
        )
        _seed_example(timing, "blink.py", "from chumicro_timing import VERSION\n")
        secrets = _seed_secrets(tmp_path)

        source = example_source(
            timing, "blink",
            library_roots=[timing, runner],
            runtime="circuitpython",
            secrets_toml=secrets,
            output_path=tmp_path / "out.msgpack",
        )
        files = source.files()
        assert "/lib/chumicro_timing/__init__.py" in files
        assert "/lib/chumicro_runner/__init__.py" in files

    def test_skips_unimported_libraries(self, tmp_path: Path) -> None:
        """A library in *library_roots* that the example doesn't
        actually import does NOT land on-device — that's the whole
        point of using ImportGraphSource over DirectorySource."""
        libs = tmp_path / "libraries"
        runner = _seed_library(libs, "runner")
        timing = _seed_library(libs, "timing")
        _seed_example(timing, "blink.py", "from chumicro_timing import VERSION\n")
        secrets = _seed_secrets(tmp_path)

        source = example_source(
            timing, "blink",
            library_roots=[timing, runner],
            runtime="circuitpython",
            secrets_toml=secrets,
            output_path=tmp_path / "out.msgpack",
        )
        files = source.files()
        assert "/lib/chumicro_runner/__init__.py" not in files

    def test_extra_modules_force_includes(self, tmp_path: Path) -> None:
        """Dynamic imports the AST can't see ride along via
        *extra_modules*."""
        libs = tmp_path / "libraries"
        timing = _seed_library(libs, "timing")
        _seed_example(timing, "blink.py", "pass\n")  # no imports!
        secrets = _seed_secrets(tmp_path)

        source = example_source(
            timing, "blink",
            library_roots=[timing],
            runtime="circuitpython",
            secrets_toml=secrets,
            output_path=tmp_path / "out.msgpack",
            extra_modules=["chumicro_timing"],
        )
        assert "/lib/chumicro_timing/__init__.py" in source.files()


# ---------------------------------------------------------------------------
# Runtime filter (__chumicro_runtimes__)
# ---------------------------------------------------------------------------


class TestRuntimeFilter:
    def test_wrong_runtime_module_is_dropped(self, tmp_path: Path) -> None:
        """A walked module whose ``__chumicro_runtimes__`` doesn't
        match the target runtime drops out of the file map.
        """
        libs = tmp_path / "libraries"
        timing = libs / "timing"
        timing.mkdir(parents=True)
        src_pkg = timing / "src" / "chumicro_timing"
        src_pkg.mkdir(parents=True)
        # Top-level module imports a CP-only submodule.
        (src_pkg / "__init__.py").write_text(
            "from chumicro_timing._cp_only import bonus\nVERSION = '1.0'\n",
        )
        # CP-only submodule.
        (src_pkg / "_cp_only.py").write_text(
            "__chumicro_runtimes__ = ('circuitpython',)\nbonus = 7\n",
        )
        (timing / "pyproject.toml").write_text(
            '[project]\nname = "chumicro-timing"\nversion = "0.1.0"\n'
            '\n[tool.chumicro.config]\nrequired_keys = []\noptional_keys = []\n',
        )
        _seed_example(
            timing, "main.py",
            "from chumicro_timing import VERSION\n",
        )
        secrets = _seed_secrets(tmp_path)

        # Build for MicroPython: the CP-only submodule should drop.
        source = example_source(
            timing, "main",
            library_roots=[timing],
            runtime="micropython",
            secrets_toml=secrets,
            output_path=tmp_path / "out.msgpack",
        )
        files = source.files()
        assert "/lib/chumicro_timing/_cp_only.py" not in files

        # Sanity: with target_runtime=circuitpython, the same submodule
        # DOES ship.
        source_cp = example_source(
            timing, "main",
            library_roots=[timing],
            runtime="circuitpython",
            secrets_toml=secrets,
            output_path=tmp_path / "out2.msgpack",
        )
        assert "/lib/chumicro_timing/_cp_only.py" in source_cp.files()


# ---------------------------------------------------------------------------
# Runtime config integration
# ---------------------------------------------------------------------------


class TestRuntimeConfigIntegration:
    def test_secrets_only_msgpack_rides_along(self, tmp_path: Path) -> None:
        """Empty per-example config + non-empty secrets.toml → the
        flat msgpack at /runtime_config.msgpack carries secrets keys."""
        from chumicro_msgpack import unpackb

        libs = tmp_path / "libraries"
        timing = _seed_library(libs, "timing")
        _seed_example(timing, "blink.py", "pass\n")
        secrets = _seed_secrets(
            tmp_path, body="[wifi]\nssid = 'home'\npassword = 'pw'\n",
        )

        source = example_source(
            timing, "blink",
            library_roots=[timing],
            runtime="circuitpython",
            secrets_toml=secrets,
            output_path=tmp_path / "out.msgpack",
        )
        files = source.files()
        assert RUNTIME_CONFIG_DEVICE_PATH in files
        decoded = unpackb(files[RUNTIME_CONFIG_DEVICE_PATH])
        assert decoded["wifi.ssid"] == "home"
        assert decoded["wifi.password"] == "pw"

    def test_per_example_config_merges_with_secrets(self, tmp_path: Path) -> None:
        """When examples/config.toml exists, its keys override + extend
        secrets.toml."""
        from chumicro_msgpack import unpackb

        libs = tmp_path / "libraries"
        timing = _seed_library(libs, "timing")
        _seed_example(timing, "blink.py", "pass\n")
        secrets = _seed_secrets(
            tmp_path, body="[wifi]\nssid = 'home'\n",
        )
        # Per-example config overrides the wifi.ssid + adds an app key.
        (timing / "examples" / "config.toml").write_text(
            "[wifi]\nssid = 'override'\n\n[demo]\ntopic = 'led'\n",
        )

        source = example_source(
            timing, "blink",
            library_roots=[timing],
            runtime="circuitpython",
            secrets_toml=secrets,
            output_path=tmp_path / "out.msgpack",
        )
        decoded = unpackb(source.files()[RUNTIME_CONFIG_DEVICE_PATH])
        assert decoded["wifi.ssid"] == "override"
        assert decoded["demo.topic"] == "led"

    def test_explicit_project_config_overrides_default_lookup(
        self, tmp_path: Path,
    ) -> None:
        """Caller-supplied project_config wins over the default
        examples/config.toml lookup."""
        from chumicro_msgpack import unpackb

        libs = tmp_path / "libraries"
        timing = _seed_library(libs, "timing")
        _seed_example(timing, "blink.py", "pass\n")
        secrets = _seed_secrets(tmp_path, body="")
        # Default-lookup config exists but should be ignored.
        (timing / "examples" / "config.toml").write_text(
            "[demo]\ntopic = 'auto-default'\n",
        )
        # Caller supplies a different config.
        explicit = tmp_path / "explicit_config.toml"
        explicit.write_text("[demo]\ntopic = 'caller-supplied'\n")

        source = example_source(
            timing, "blink",
            library_roots=[timing],
            runtime="circuitpython",
            secrets_toml=secrets,
            project_config=explicit,
            output_path=tmp_path / "out.msgpack",
        )
        decoded = unpackb(source.files()[RUNTIME_CONFIG_DEVICE_PATH])
        assert decoded["demo.topic"] == "caller-supplied"


# ---------------------------------------------------------------------------
# Naming + arg validation
# ---------------------------------------------------------------------------


class TestNamingAndValidation:
    def test_example_name_accepts_with_and_without_py_suffix(
        self, tmp_path: Path,
    ) -> None:
        """``"blink"`` and ``"blink.py"`` resolve to the same example file."""
        libs = tmp_path / "libraries"
        timing = _seed_library(libs, "timing")
        _seed_example(timing, "blink.py", "pass\n")
        secrets = _seed_secrets(tmp_path)

        source_a = example_source(
            timing, "blink",
            library_roots=[timing],
            runtime="circuitpython",
            secrets_toml=secrets,
            output_path=tmp_path / "a.msgpack",
        )
        source_b = example_source(
            timing, "blink.py",
            library_roots=[timing],
            runtime="circuitpython",
            secrets_toml=secrets,
            output_path=tmp_path / "b.msgpack",
        )
        assert source_a.entrypoint() == source_b.entrypoint()
        assert "/code.py" in source_a.files()
        assert "/code.py" in source_b.files()

    def test_invalid_runtime_raises(self, tmp_path: Path) -> None:
        libs = tmp_path / "libraries"
        timing = _seed_library(libs, "timing")
        _seed_example(timing, "blink.py", "pass\n")
        secrets = _seed_secrets(tmp_path)
        with pytest.raises(ValueError, match="runtime must be one of"):
            example_source(
                timing, "blink",
                library_roots=[timing],
                runtime="javascript",
                secrets_toml=secrets,
                output_path=tmp_path / "out.msgpack",
            )

    def test_missing_example_raises_file_not_found(self, tmp_path: Path) -> None:
        libs = tmp_path / "libraries"
        timing = _seed_library(libs, "timing")
        secrets = _seed_secrets(tmp_path)
        with pytest.raises(FileNotFoundError):
            example_source(
                timing, "no_such_example",
                library_roots=[timing],
                runtime="circuitpython",
                secrets_toml=secrets,
                output_path=tmp_path / "out.msgpack",
            )


# ---------------------------------------------------------------------------
# Default output_path
# ---------------------------------------------------------------------------


class TestDefaultOutputPath:
    def test_default_output_path_lands_under_scratch(self, tmp_path: Path) -> None:
        """Default output path is ``<secrets>.parent/.scratch/`` so the
        artifact lands in the gitignored scratch tree, never inside
        the tracked libraries/<lib>/examples/ folder."""
        libs = tmp_path / "libraries"
        timing = _seed_library(libs, "timing")
        path = _default_output_path(
            tmp_path / "secrets.toml", timing, "circuitpython_blink",
        )
        assert path == (
            tmp_path / ".scratch"
            / "example_runtime_config_timing_circuitpython_blink.msgpack"
        )

    def test_default_output_path_strips_py_suffix(self, tmp_path: Path) -> None:
        libs = tmp_path / "libraries"
        timing = _seed_library(libs, "timing")
        with_suffix = _default_output_path(
            tmp_path / "secrets.toml", timing, "blink.py",
        )
        without_suffix = _default_output_path(
            tmp_path / "secrets.toml", timing, "blink",
        )
        assert with_suffix == without_suffix

    def test_omitted_output_path_uses_default(self, tmp_path: Path) -> None:
        """Caller doesn't pass output_path → defaults to .scratch/."""
        libs = tmp_path / "libraries"
        timing = _seed_library(libs, "timing")
        _seed_example(timing, "blink.py", "pass\n")
        secrets = _seed_secrets(tmp_path)
        # Don't pass output_path — it should default.
        source = example_source(
            timing, "blink",
            library_roots=[timing],
            runtime="circuitpython",
            secrets_toml=secrets,
        )
        # files() materializes the msgpack — by the time it returns,
        # the default scratch artifact must exist on disk.
        source.files()
        expected = (
            tmp_path / ".scratch"
            / "example_runtime_config_timing_blink.msgpack"
        )
        assert expected.is_file()


# ---------------------------------------------------------------------------
# Library-roots resilience
# ---------------------------------------------------------------------------


class TestLibraryRootsResilience:
    def test_root_without_src_dir_is_silently_skipped(
        self, tmp_path: Path,
    ) -> None:
        """A *library_roots* entry whose ``<root>/src`` doesn't exist
        is skipped without error — useful when the caller passes a
        glob of every libraries/<name>/ but some are stub directories
        not yet populated."""
        libs = tmp_path / "libraries"
        timing = _seed_library(libs, "timing")
        # Stub library — no src/.
        stub_root = libs / "stub"
        stub_root.mkdir()
        _seed_example(timing, "blink.py", "from chumicro_timing import VERSION\n")
        secrets = _seed_secrets(tmp_path)

        source = example_source(
            timing, "blink",
            library_roots=[timing, stub_root],
            runtime="circuitpython",
            secrets_toml=secrets,
            output_path=tmp_path / "out.msgpack",
        )
        # The stub is silently skipped; the example deploys cleanly.
        files = source.files()
        assert "/lib/chumicro_timing/__init__.py" in files
