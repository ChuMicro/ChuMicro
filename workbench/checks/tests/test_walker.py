"""Tests for the shared file walker."""

from __future__ import annotations

from pathlib import Path

from chumicro_checks._walker import EXCLUDED_DIRECTORY_NAMES, iter_text_files


def test_yields_matching_suffixes_only(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("")
    (tmp_path / "b.md").write_text("")
    (tmp_path / "c.txt").write_text("")
    files = list(iter_text_files(tmp_path, suffixes=(".py", ".md")))
    suffixes = sorted(file.suffix for file in files)
    assert suffixes == [".md", ".py"]


def test_skips_excluded_directory_names(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "b.py").write_text("")
    files = list(iter_text_files(tmp_path, suffixes=(".py",)))
    assert [path.name for path in files] == ["a.py"]


def test_skips_egg_info(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg.egg-info"
    pkg.mkdir()
    (pkg / "PKG-INFO").write_text("")
    (tmp_path / "real.py").write_text("")
    files = list(iter_text_files(tmp_path, suffixes=(".py",)))
    assert [path.name for path in files] == ["real.py"]


def test_single_file_root(tmp_path: Path) -> None:
    target = tmp_path / "foo.py"
    target.write_text("")
    files = list(iter_text_files(target, suffixes=(".py",)))
    assert files == [target]


def test_single_file_root_with_wrong_suffix(tmp_path: Path) -> None:
    target = tmp_path / "foo.txt"
    target.write_text("")
    assert list(iter_text_files(target, suffixes=(".py",))) == []


def test_missing_root_yields_nothing(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    assert list(iter_text_files(missing, suffixes=(".py",))) == []


def test_excluded_dir_set_is_frozenset() -> None:
    # The export is part of the public surface; spot-check it's stable.
    assert "__pycache__" in EXCLUDED_DIRECTORY_NAMES
    assert ".venv" in EXCLUDED_DIRECTORY_NAMES


def test_output_is_sorted(tmp_path: Path) -> None:
    (tmp_path / "z.py").write_text("")
    (tmp_path / "a.py").write_text("")
    (tmp_path / "m.py").write_text("")
    names = [path.name for path in iter_text_files(tmp_path, suffixes=(".py",))]
    assert names == sorted(names)
