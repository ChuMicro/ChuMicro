"""Tests for sdist_content — the build-time curated-sdist guard."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

from sdist_content import (
    _sdist_distribution_name,
    check_all_library_sdists,
    check_library_sdist,
)

_PYPROJECT = """\
[project]
name = "chumicro-{dist}"

[project.optional-dependencies]
test = ["pytest"]

[tool.hatch.build.targets.sdist]
include = ["src/", "VERSION", "README.md", "tests/", "examples/", "docs/"]
"""

_PYPROJECT_NO_TEST_EXTRA = """\
[project]
name = "chumicro-{dist}"

[tool.hatch.build.targets.sdist]
include = ["src/", "VERSION", "README.md", "tests/", "examples/", "docs/"]
"""


def _write_sdist(dest: Path, base: str, top_dirs: list[str]) -> None:
    """Write a minimal .tar.gz with one file under each of *top_dirs*."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(dest, "w:gz") as archive:
        for top in ["src", *top_dirs]:
            payload = b"x"
            info = tarfile.TarInfo(f"{base}/{top}/placeholder")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))


def _make_library(
    root: Path,
    name: str,
    version: str,
    *,
    pyproject: str = _PYPROJECT,
    sdist_dirs: list[str] | None = None,
) -> Path:
    library_dir = root / name
    library_dir.mkdir(parents=True)
    (library_dir / "pyproject.toml").write_text(
        pyproject.format(dist=name.replace("_", "-"))
    )
    (library_dir / "VERSION").write_text(f"{version}\n")
    if sdist_dirs is not None:
        distribution = f"chumicro_{name}"
        _write_sdist(
            library_dir / "dist" / f"{distribution}-{version}.tar.gz",
            f"{distribution}-{version}",
            sdist_dirs,
        )
    return library_dir


class TestDistributionName:
    def test_collapses_hyphens_to_underscore(self):
        pyproject = {"project": {"name": "chumicro-http-server"}}
        assert _sdist_distribution_name(pyproject) == "chumicro_http_server"

    def test_simple_name_unchanged(self):
        pyproject = {"project": {"name": "chumicro-mqtt"}}
        assert _sdist_distribution_name(pyproject) == "chumicro_mqtt"


class TestCheckLibrarySdist:
    def test_complete_sdist_has_no_problems(self, tmp_path: Path):
        library = _make_library(
            tmp_path, "mqtt", "0.11.4",
            sdist_dirs=["tests", "examples", "docs"],
        )
        assert check_library_sdist(library) == []

    def test_missing_required_dir_flagged(self, tmp_path: Path):
        library = _make_library(
            tmp_path, "mqtt", "0.11.4",
            sdist_dirs=["tests", "examples"],  # docs/ dropped
        )
        problems = check_library_sdist(library)
        assert len(problems) == 1
        assert "docs/" in problems[0]

    def test_missing_test_extra_flagged(self, tmp_path: Path):
        library = _make_library(
            tmp_path, "mqtt", "0.11.4",
            pyproject=_PYPROJECT_NO_TEST_EXTRA,
            sdist_dirs=["tests", "examples", "docs"],
        )
        problems = check_library_sdist(library)
        assert len(problems) == 1
        assert "test" in problems[0]

    def test_missing_sdist_file_flagged(self, tmp_path: Path):
        library = _make_library(tmp_path, "mqtt", "0.11.4", sdist_dirs=None)
        problems = check_library_sdist(library)
        assert any("built sdist not found" in problem for problem in problems)

    def test_missing_pyproject_flagged(self, tmp_path: Path):
        library_dir = tmp_path / "mqtt"
        library_dir.mkdir()
        assert check_library_sdist(library_dir) == ["mqtt: no pyproject.toml"]


class TestCheckAllLibrarySdists:
    def test_aggregates_across_libraries(self, tmp_path: Path):
        good = _make_library(
            tmp_path, "mqtt", "0.11.4",
            sdist_dirs=["tests", "examples", "docs"],
        )
        bad = _make_library(
            tmp_path, "ntp", "0.8.4",
            sdist_dirs=["tests", "docs"],  # examples/ dropped
        )
        problems = check_all_library_sdists([good, bad])
        assert len(problems) == 1
        assert "ntp" in problems[0]
        assert "examples/" in problems[0]
