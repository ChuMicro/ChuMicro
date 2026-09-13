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
only-include = ["src/", "VERSION", "README.md", "tests/", "examples/", "docs/"]
"""

_PYPROJECT_NO_TEST_EXTRA = """\
[project]
name = "chumicro-{dist}"

[tool.hatch.build.targets.sdist]
only-include = ["src/", "VERSION", "README.md", "tests/", "examples/", "docs/"]
"""


_LICENSE_TEXT = b"MIT License fixture body\n"


def _write_sdist(
    dest: Path, base: str, top_dirs: list[str], *, with_license: bool = True,
) -> None:
    """Write a minimal .tar.gz with one file under each of *top_dirs*."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(dest, "w:gz") as archive:
        for top in ["src", *top_dirs]:
            payload = b"x"
            info = tarfile.TarInfo(f"{base}/{top}/placeholder")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
        if with_license:
            info = tarfile.TarInfo(f"{base}/LICENSE")
            info.size = len(_LICENSE_TEXT)
            archive.addfile(info, io.BytesIO(_LICENSE_TEXT))


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
    (library_dir / "LICENSE").write_bytes(_LICENSE_TEXT)
    # The canonical license the checker compares against, one level up.
    canonical = root / "LICENSE"
    if not canonical.exists():
        canonical.write_bytes(_LICENSE_TEXT)
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
        assert check_library_sdist(
            library, canonical_license=tmp_path / "LICENSE",
        ) == []

    def test_missing_required_dir_flagged(self, tmp_path: Path):
        library = _make_library(
            tmp_path, "mqtt", "0.11.4",
            sdist_dirs=["tests", "examples"],  # docs/ dropped
        )
        problems = check_library_sdist(
            library, canonical_license=tmp_path / "LICENSE",
        )
        assert len(problems) == 1
        assert "docs/" in problems[0]

    def test_missing_test_extra_flagged(self, tmp_path: Path):
        library = _make_library(
            tmp_path, "mqtt", "0.11.4",
            pyproject=_PYPROJECT_NO_TEST_EXTRA,
            sdist_dirs=["tests", "examples", "docs"],
        )
        problems = check_library_sdist(
            library, canonical_license=tmp_path / "LICENSE",
        )
        assert len(problems) == 1
        assert "test" in problems[0]

    def test_missing_sdist_file_flagged(self, tmp_path: Path):
        library = _make_library(tmp_path, "mqtt", "0.11.4", sdist_dirs=None)
        problems = check_library_sdist(
            library, canonical_license=tmp_path / "LICENSE",
        )
        assert any("built sdist not found" in problem for problem in problems)

    def test_missing_pyproject_flagged(self, tmp_path: Path):
        library_dir = tmp_path / "mqtt"
        library_dir.mkdir()
        assert check_library_sdist(
            library_dir, canonical_license=tmp_path / "LICENSE",
        ) == ["mqtt: no pyproject.toml"]

    def test_missing_package_license_flagged(self, tmp_path: Path):
        library = _make_library(
            tmp_path, "mqtt", "0.11.4",
            sdist_dirs=["tests", "examples", "docs"],
        )
        (library / "LICENSE").unlink()
        problems = check_library_sdist(
            library, canonical_license=tmp_path / "LICENSE",
        )
        assert len(problems) == 1
        assert "no LICENSE file" in problems[0]

    def test_drifted_license_flagged(self, tmp_path: Path):
        library = _make_library(
            tmp_path, "mqtt", "0.11.4",
            sdist_dirs=["tests", "examples", "docs"],
        )
        (library / "LICENSE").write_bytes(b"edited text\n")
        problems = check_library_sdist(
            library, canonical_license=tmp_path / "LICENSE",
        )
        assert len(problems) == 1
        assert "does not start with the repo root LICENSE" in problems[0]

    def test_appended_attribution_passes(self, tmp_path: Path):
        library = _make_library(
            tmp_path, "mqtt", "0.11.4",
            sdist_dirs=["tests", "examples", "docs"],
        )
        canonical = (tmp_path / "LICENSE").read_bytes()
        (library / "LICENSE").write_bytes(
            canonical + b"\nPortions Copyright (c) 2021 Upstream Author\n",
        )
        problems = check_library_sdist(
            library, canonical_license=tmp_path / "LICENSE",
        )
        assert problems == []

    def test_sdist_without_license_flagged(self, tmp_path: Path):
        library = _make_library(tmp_path, "mqtt", "0.11.4", sdist_dirs=None)
        _write_sdist(
            library / "dist" / "chumicro_mqtt-0.11.4.tar.gz",
            "chumicro_mqtt-0.11.4",
            ["tests", "examples", "docs"],
            with_license=False,
        )
        problems = check_library_sdist(
            library, canonical_license=tmp_path / "LICENSE",
        )
        assert len(problems) == 1
        assert "missing LICENSE" in problems[0]


def _write_sdist_members(dest: Path, member_names: list[str]) -> None:
    """Write a .tar.gz containing exactly *member_names* (each a 1-byte file)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(dest, "w:gz") as archive:
        for member in member_names:
            payload = b"x"
            info = tarfile.TarInfo(member)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))


class TestDeclaredDataFiles:
    """S7: the sdist gate flags a declared __chumicro_data_files__ sibling
    that the built tarball dropped."""

    def _make_library_with_data_file(
        self, root: Path, name: str, version: str, *, include_der: bool,
    ) -> Path:
        library_dir = root / name
        package = f"chumicro_{name}"
        pkg_dir = library_dir / "src" / package
        pkg_dir.mkdir(parents=True)
        (library_dir / "pyproject.toml").write_text(
            _PYPROJECT.format(dist=name.replace("_", "-")),
        )
        (library_dir / "VERSION").write_text(f"{version}\n")
        (library_dir / "LICENSE").write_bytes(_LICENSE_TEXT)
        if not (root / "LICENSE").exists():
            (root / "LICENSE").write_bytes(_LICENSE_TEXT)
        (pkg_dir / "__init__.py").write_text(
            '__chumicro_data_files__ = ("_ca_bundle.der",)\n',
        )
        (pkg_dir / "_ca_bundle.der").write_bytes(b"\x30\x82der")

        base = f"{package}-{version}"
        members = [
            f"{base}/src/{package}/__init__.py",
            f"{base}/tests/placeholder",
            f"{base}/examples/placeholder",
            f"{base}/docs/placeholder",
            f"{base}/LICENSE",
        ]
        if include_der:
            members.append(f"{base}/src/{package}/_ca_bundle.der")
        _write_sdist_members(
            library_dir / "dist" / f"{base}.tar.gz", members,
        )
        return library_dir

    def test_declared_data_file_present_has_no_problem(self, tmp_path: Path):
        library = self._make_library_with_data_file(
            tmp_path, "sockets", "0.11.0", include_der=True,
        )
        assert check_library_sdist(
            library, canonical_license=tmp_path / "LICENSE",
        ) == []

    def test_missing_declared_data_file_flagged(self, tmp_path: Path):
        library = self._make_library_with_data_file(
            tmp_path, "sockets", "0.11.0", include_der=False,
        )
        problems = check_library_sdist(
            library, canonical_license=tmp_path / "LICENSE",
        )
        assert len(problems) == 1
        assert "_ca_bundle.der" in problems[0]
        assert "__chumicro_data_files__" in problems[0]


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
        problems = check_all_library_sdists(
            [good, bad], canonical_license=tmp_path / "LICENSE",
        )
        assert len(problems) == 1
        assert "ntp" in problems[0]
        assert "examples/" in problems[0]
