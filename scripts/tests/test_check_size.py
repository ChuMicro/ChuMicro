"""Tests for check_size.py — the per-library size-regression gate.

Covers the four layers independently:

- :func:`shipped_source_files` / :func:`measure_library` — the
  measurement, exercised on a synthetic fixture tree with the real
  ``strip_source`` and (when available) the prepared ``mpy-cross``.  The
  test-support (``testing.py``) and ``__pycache__`` exclusions are
  asserted here.
- :func:`_check` — the ceiling comparison and every failure mode
  (over budget, missing entry, stale entry, missing mpy-cross), driven
  with a stubbed :func:`measure_library` so the comparison logic is
  tested without shelling out.
- :func:`load_budgets` — budget-file parse errors.

The ``_check`` tests stub measurement the same way ``test_check_version``
stubs ``changed_files`` / ``read_version``: the gate runs against a
synthetic snapshot, so outcomes never couple to the real fleet's sizes.
"""

from __future__ import annotations

from pathlib import Path

import check_size
import pytest
from check_size import (
    BudgetError,
    _check,
    load_budgets,
    measure_library,
    prepared_mpy_cross,
    shipped_source_files,
)
from chumicro_deploy.source_minify import strip_source

# ---------------------------------------------------------------------------
# Fixture tree helpers
# ---------------------------------------------------------------------------

_MODULE_WITH_PROSE = '''\
"""A module docstring that strip_source blanks out."""

# A leading comment, also blanked.
VALUE = 42  # trailing comment


def add(left, right):
    """Docstring on a function."""
    return left + right
'''

_INIT_SOURCE = '''\
"""Package docstring."""

from .core import add
'''

_TESTING_SOURCE = '''\
"""Test-support fakes — must never ship, and must never be budgeted."""

__chumicro_test_support__ = True

FAKE = "x" * 1000
'''


def _make_library(root: Path, name: str = "mylib") -> Path:
    """Build a library tree under *root* and return the library dir.

    Layout: ``<root>/<name>/src/chumicro_<name>/`` with ``__init__.py``,
    ``core.py`` (real prose), ``testing.py`` (test-support marker), and a
    stray ``__pycache__/ghost.py`` — the last two must be excluded from
    the measured set.
    """
    package = root / name / "src" / f"chumicro_{name}"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(_INIT_SOURCE, encoding="utf-8")
    (package / "core.py").write_text(_MODULE_WITH_PROSE, encoding="utf-8")
    (package / "testing.py").write_text(_TESTING_SOURCE, encoding="utf-8")
    pycache = package / "__pycache__"
    pycache.mkdir()
    (pycache / "ghost.py").write_text("SHOULD_NOT_COUNT = 1\n", encoding="utf-8")
    return root / name


def _mpy_cross_or_skip() -> str:
    """Return the prepared mpy-cross path, or skip when it isn't built."""
    prepared = prepared_mpy_cross()
    if prepared is None:
        pytest.skip("prepared mpy-cross not available")
    return str(prepared)


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------


class TestShippedSourceFiles:
    """Tests for the shipped-file walk (which files count)."""

    def test_excludes_testing_and_pycache(self, tmp_path):
        """testing.py (test-support) and __pycache__ files are dropped."""
        library_dir = _make_library(tmp_path)
        package_dir = library_dir / "src" / "chumicro_mylib"
        names = {path.name for path in shipped_source_files(package_dir)}
        assert names == {"__init__.py", "core.py"}
        assert "testing.py" not in names
        assert "ghost.py" not in names


class TestMeasureLibrary:
    """Tests for the stripped + mpy byte measurement."""

    def test_stripped_total_matches_recomputed(self, tmp_path):
        """stripped bytes equal the sum of strip_source() over shipped files."""
        mpy_cross = _mpy_cross_or_skip()
        library_dir = _make_library(tmp_path)
        package_dir = library_dir / "src" / "chumicro_mylib"

        expected = sum(
            len(strip_source(path.read_text(encoding="utf-8")).encode("utf-8"))
            for path in shipped_source_files(package_dir)
        )
        sizes = measure_library(package_dir, library_dir / "src", mpy_cross)
        assert sizes["stripped"] == expected

    def test_testing_module_bytes_excluded(self, tmp_path):
        """The 1 KB test-support module never inflates the stripped total."""
        mpy_cross = _mpy_cross_or_skip()
        library_dir = _make_library(tmp_path)
        package_dir = library_dir / "src" / "chumicro_mylib"
        sizes = measure_library(package_dir, library_dir / "src", mpy_cross)
        # testing.py alone is > 1 KB; the two shipped modules are small.
        assert sizes["stripped"] < 500

    def test_mpy_total_positive(self, tmp_path):
        """Compiling the stripped modules yields non-empty bytecode."""
        mpy_cross = _mpy_cross_or_skip()
        library_dir = _make_library(tmp_path)
        package_dir = library_dir / "src" / "chumicro_mylib"
        sizes = measure_library(package_dir, library_dir / "src", mpy_cross)
        assert sizes["mpy"] > 0

    def test_measurement_is_deterministic(self, tmp_path):
        """Two runs over the same tree produce identical byte totals."""
        mpy_cross = _mpy_cross_or_skip()
        library_dir = _make_library(tmp_path)
        package_dir = library_dir / "src" / "chumicro_mylib"
        first = measure_library(package_dir, library_dir / "src", mpy_cross)
        second = measure_library(package_dir, library_dir / "src", mpy_cross)
        assert first == second


# ---------------------------------------------------------------------------
# Budget file parsing
# ---------------------------------------------------------------------------


class TestLoadBudgets:
    """Tests for load_budgets — the budget-file parser."""

    def _write(self, tmp_path: Path, text: str) -> Path:
        path = tmp_path / "size-budgets.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_valid_file_parses(self, tmp_path):
        """A well-formed file returns the per-library ceiling map."""
        path = self._write(
            tmp_path,
            "[timing]\nstripped = 4738\nmpy = 2595\n",
        )
        assert load_budgets(path) == {"timing": {"stripped": 4738, "mpy": 2595}}

    def test_missing_file_raises(self, tmp_path):
        """A missing budget file is a BudgetError, not a bare OSError."""
        with pytest.raises(BudgetError, match="not found"):
            load_budgets(tmp_path / "does-not-exist.toml")

    def test_invalid_toml_raises(self, tmp_path):
        """Malformed TOML surfaces as a BudgetError."""
        path = self._write(tmp_path, "[timing]\nstripped = = 5\n")
        with pytest.raises(BudgetError, match="not valid TOML"):
            load_budgets(path)

    def test_missing_dimension_raises(self, tmp_path):
        """An entry missing a dimension is rejected."""
        path = self._write(tmp_path, "[timing]\nstripped = 4738\n")
        with pytest.raises(BudgetError, match="missing 'mpy'"):
            load_budgets(path)

    def test_non_integer_value_raises(self, tmp_path):
        """A non-integer ceiling is rejected."""
        path = self._write(
            tmp_path,
            '[timing]\nstripped = "big"\nmpy = 2595\n',
        )
        with pytest.raises(BudgetError, match="non-negative integer"):
            load_budgets(path)

    def test_boolean_value_raises(self, tmp_path):
        """A boolean ceiling (int subclass) is rejected, not coerced to 1."""
        path = self._write(
            tmp_path,
            "[timing]\nstripped = true\nmpy = 2595\n",
        )
        with pytest.raises(BudgetError, match="non-negative integer"):
            load_budgets(path)

    def test_non_table_entry_raises(self, tmp_path):
        """A scalar where a library table is expected is rejected."""
        path = self._write(tmp_path, "timing = 4738\n")
        with pytest.raises(BudgetError, match="must be a table"):
            load_budgets(path)


# ---------------------------------------------------------------------------
# The gate (_check)
# ---------------------------------------------------------------------------


class TestCheck:
    """Tests for _check — ceiling comparison and failure reporting.

    measure_library and find_package_dir are stubbed so the comparison
    logic is exercised without the filesystem or mpy-cross.  Each
    library dir is a bare path whose ``.name`` is the library name; the
    stubbed find_package_dir derives the package dir from it, and the
    stubbed measure_library returns canned sizes keyed by library name
    (recovered from ``src_root.parent.name``).
    """

    def _run(
        self,
        tmp_path,
        monkeypatch,
        budgets_text: str,
        measured: dict[str, dict[str, int]],
        *,
        mpy_cross: str | None = "/fake/mpy-cross",
    ) -> int:
        budget_file = tmp_path / "size-budgets.toml"
        budget_file.write_text(budgets_text, encoding="utf-8")

        monkeypatch.setattr(
            check_size, "find_package_dir",
            lambda library_dir: library_dir / "src" / f"chumicro_{library_dir.name}",
        )
        monkeypatch.setattr(
            check_size, "measure_library",
            lambda _package_dir, src_root, _mpy_cross: measured[src_root.parent.name],
        )
        library_dirs = [tmp_path / name for name in measured]
        return _check(
            budget_path=budget_file,
            library_dirs=library_dirs,
            mpy_cross=mpy_cross,
        )

    def test_within_budget_passes(self, tmp_path, monkeypatch, capsys):
        """Every library at or under both ceilings passes with a terse OK."""
        result = self._run(
            tmp_path, monkeypatch,
            "[timing]\nstripped = 5000\nmpy = 3000\n",
            {"timing": {"stripped": 4738, "mpy": 2595}},
        )
        assert result == 0
        out = capsys.readouterr().out
        assert "OK: 1 libraries within size budgets" in out

    def test_exactly_at_ceiling_passes(self, tmp_path, monkeypatch, capsys):
        """Measured == ceiling is within budget (only over trips the gate)."""
        result = self._run(
            tmp_path, monkeypatch,
            "[timing]\nstripped = 4738\nmpy = 2595\n",
            {"timing": {"stripped": 4738, "mpy": 2595}},
        )
        assert result == 0

    def test_over_mpy_ceiling_fails(self, tmp_path, monkeypatch, capsys):
        """A library over its mpy ceiling fails with a named violation line."""
        result = self._run(
            tmp_path, monkeypatch,
            "[timing]\nstripped = 5000\nmpy = 2595\n",
            {"timing": {"stripped": 4738, "mpy": 2600}},
        )
        assert result == 1
        out = capsys.readouterr().out
        assert "FAIL: timing mpy 2600 B > ceiling 2595 B (over by 5 B)." in out
        assert "ratchet DOWN" in out

    def test_over_stripped_ceiling_fails(self, tmp_path, monkeypatch, capsys):
        """A library over its stripped ceiling fails."""
        result = self._run(
            tmp_path, monkeypatch,
            "[timing]\nstripped = 4738\nmpy = 3000\n",
            {"timing": {"stripped": 5000, "mpy": 2595}},
        )
        assert result == 1
        out = capsys.readouterr().out
        assert "FAIL: timing stripped 5000 B > ceiling 4738 B (over by 262 B)." in out

    def test_missing_budget_entry_fails(self, tmp_path, monkeypatch, capsys):
        """A measured library with no budget entry fails and quotes its sizes."""
        result = self._run(
            tmp_path, monkeypatch,
            "[timing]\nstripped = 5000\nmpy = 3000\n",
            {
                "timing": {"stripped": 4738, "mpy": 2595},
                "newlib": {"stripped": 1000, "mpy": 500},
            },
        )
        assert result == 1
        out = capsys.readouterr().out
        assert "FAIL: newlib — no size-budget entry" in out
        assert "measured stripped=1000 B, mpy=500 B" in out

    def test_stale_budget_entry_fails(self, tmp_path, monkeypatch, capsys):
        """A budget entry with no matching library fails as stale."""
        result = self._run(
            tmp_path, monkeypatch,
            "[timing]\nstripped = 5000\nmpy = 3000\n"
            "[ghostlib]\nstripped = 100\nmpy = 50\n",
            {"timing": {"stripped": 4738, "mpy": 2595}},
        )
        assert result == 1
        out = capsys.readouterr().out
        assert "FAIL: ghostlib — size-budget entry has no matching library" in out

    def test_missing_mpy_cross_fails_with_remedy(
        self, tmp_path, monkeypatch, capsys,
    ):
        """mpy_cross=None fails with the prepare-mpy-cross remedy, never skips."""
        result = self._run(
            tmp_path, monkeypatch,
            "[timing]\nstripped = 5000\nmpy = 3000\n",
            {"timing": {"stripped": 4738, "mpy": 2595}},
            mpy_cross=None,
        )
        assert result == 1
        out = capsys.readouterr().out
        assert "prepared mpy-cross not found" in out
        assert "prepare-mpy-cross" in out

    def test_malformed_budget_file_fails(self, tmp_path, monkeypatch, capsys):
        """A budget file that won't parse fails the gate (not a crash)."""
        result = self._run(
            tmp_path, monkeypatch,
            "[timing]\nstripped = = 5\n",
            {"timing": {"stripped": 4738, "mpy": 2595}},
        )
        assert result == 1
        assert "FAIL:" in capsys.readouterr().out


class TestRealBudgetFile:
    """Guard the committed budget file itself stays well-formed."""

    def test_committed_budgets_parse(self):
        """size-budgets.toml at the repo root loads and covers every library."""
        from repo_layout import discover_library_dirs

        budgets = load_budgets(check_size.BUDGET_FILE)
        library_names = {library.name for library in discover_library_dirs()}
        assert set(budgets) == library_names
        for name, entry in budgets.items():
            assert entry["stripped"] > 0, name
            assert entry["mpy"] > 0, name
