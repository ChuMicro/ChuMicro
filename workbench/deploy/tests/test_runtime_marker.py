"""Tests for ``chumicro_deploy.runtime_marker``.

Decisions 0037 + 0044 — the marker is read via AST (no module
execution), unmarked files match every target (default-safe), and
sub-runtime markers fold into ``micropython``.
"""

from pathlib import Path

from chumicro_deploy.runtime_marker import (
    DEVICE_RUNTIMES,
    KNOWN_RUNTIMES,
    file_targets_runtime,
    read_runtime_marker,
)


class TestReadRuntimeMarker:
    """Tests for ``read_runtime_marker``."""

    def test_no_marker_returns_none(self, tmp_path: Path) -> None:
        """A file without ``__chumicro_runtimes__`` returns None (universal)."""
        file = tmp_path / "module.py"
        file.write_text("# nothing\n")
        assert read_runtime_marker(file) is None

    def test_tuple_marker(self, tmp_path: Path) -> None:
        """Tuple-form marker is parsed."""
        file = tmp_path / "cp.py"
        file.write_text('__chumicro_runtimes__ = ("circuitpython",)\n')
        assert read_runtime_marker(file) == frozenset({"circuitpython"})

    def test_list_marker(self, tmp_path: Path) -> None:
        """List-form marker is parsed."""
        file = tmp_path / "shared.py"
        file.write_text(
            '__chumicro_runtimes__ = ["circuitpython", "micropython"]\n',
        )
        assert read_runtime_marker(file) == frozenset(
            {"circuitpython", "micropython"},
        )

    def test_marker_does_not_execute_file(self, tmp_path: Path) -> None:
        """Decision 0037: AST-only — adapter files import device-only modules."""
        file = tmp_path / "cp.py"
        file.write_text(
            '__chumicro_runtimes__ = ("circuitpython",)\n'
            "import this_module_does_not_exist\n",
        )
        assert read_runtime_marker(file) == frozenset({"circuitpython"})

    def test_unparseable_file_returns_none(self, tmp_path: Path) -> None:
        """Syntax errors are treated as universal (fail-safe)."""
        file = tmp_path / "broken.py"
        file.write_text("def : invalid\n")
        assert read_runtime_marker(file) is None


class TestFileTargetsRuntime:
    """Tests for ``file_targets_runtime``."""

    def test_target_none_matches_everything(self, tmp_path: Path) -> None:
        """``target_runtime=None`` is the unfiltered case."""
        file = tmp_path / "cp.py"
        file.write_text('__chumicro_runtimes__ = ("circuitpython",)\n')
        assert file_targets_runtime(file, target_runtime=None) is True

    def test_unmarked_file_matches_every_target(self, tmp_path: Path) -> None:
        """Default-safe — unmarked files ship to every target."""
        file = tmp_path / "shared.py"
        file.write_text("# universal\n")
        for runtime in ("circuitpython", "micropython", "cpython"):
            assert file_targets_runtime(
                file, target_runtime=runtime,
            ) is True

    def test_cp_marker_matches_only_circuitpython(self, tmp_path: Path) -> None:
        file = tmp_path / "cp.py"
        file.write_text('__chumicro_runtimes__ = ("circuitpython",)\n')
        assert file_targets_runtime(file, target_runtime="circuitpython")
        assert not file_targets_runtime(file, target_runtime="micropython")
        assert not file_targets_runtime(file, target_runtime="cpython")

    def test_micropython_submarker_folds(self, tmp_path: Path) -> None:
        """Decision 0037: ``micropython_esp32`` matches ``micropython``."""
        file = tmp_path / "esp32.py"
        file.write_text('__chumicro_runtimes__ = ("micropython_esp32",)\n')
        assert file_targets_runtime(file, target_runtime="micropython")
        assert not file_targets_runtime(file, target_runtime="circuitpython")

    def test_known_runtimes_constant_includes_canonicals(self) -> None:
        """The exported constant is a frozen set of the supported names."""
        assert "circuitpython" in KNOWN_RUNTIMES
        assert "micropython" in KNOWN_RUNTIMES
        assert "cpython" in KNOWN_RUNTIMES

    def test_device_runtimes_constant(self) -> None:
        """``DEVICE_RUNTIMES`` is the source-bundle target — both MCU runtimes."""
        assert DEVICE_RUNTIMES == frozenset({"circuitpython", "micropython"})

    def test_frozenset_target_drops_cpython_only_marker(
        self, tmp_path: Path,
    ) -> None:
        """A ``("cpython",)``-marked file does not match the device-runtimes set."""
        file = tmp_path / "testing.py"
        file.write_text('__chumicro_runtimes__ = ("cpython",)\n')
        assert not file_targets_runtime(file, target_runtime=DEVICE_RUNTIMES)

    def test_frozenset_target_keeps_cp_only_marker(self, tmp_path: Path) -> None:
        """``("circuitpython",)``-marked files ride along in the source bundle."""
        file = tmp_path / "cp.py"
        file.write_text('__chumicro_runtimes__ = ("circuitpython",)\n')
        assert file_targets_runtime(file, target_runtime=DEVICE_RUNTIMES)

    def test_frozenset_target_keeps_unmarked_files(self, tmp_path: Path) -> None:
        """Default-safe still applies for set targets."""
        file = tmp_path / "shared.py"
        file.write_text("# universal\n")
        assert file_targets_runtime(file, target_runtime=DEVICE_RUNTIMES)

    def test_frozenset_target_folds_sub_runtimes(self, tmp_path: Path) -> None:
        """Sub-runtime markers fold against the device-runtime set too."""
        file = tmp_path / "esp32.py"
        file.write_text('__chumicro_runtimes__ = ("micropython_esp32",)\n')
        assert file_targets_runtime(file, target_runtime=DEVICE_RUNTIMES)
