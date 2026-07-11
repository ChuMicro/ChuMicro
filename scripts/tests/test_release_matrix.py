"""Tests for release_matrix.py — release-job matrix builder."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import release_matrix


@pytest.fixture
def fake_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point release_matrix at a temporary root with empty libraries/+workbench/."""
    (tmp_path / "libraries").mkdir()
    (tmp_path / "workbench").mkdir()
    monkeypatch.setattr(release_matrix, "ROOT", tmp_path)
    monkeypatch.setattr(release_matrix, "_tag_exists", lambda _: False)
    return tmp_path


def _make_package(parent: Path, name: str, version: str) -> Path:
    """Create parent/<name>/VERSION with the given version contents."""
    package_dir = parent / name
    package_dir.mkdir()
    (package_dir / "VERSION").write_text(version + "\n")
    return package_dir


class TestCollectEntries:
    """Tests for _collect_entries."""

    def test_returns_empty_when_no_packages(self, fake_root: Path) -> None:
        """An empty workspace yields an empty matrix."""
        assert release_matrix._collect_entries(suffix="", libraries_filter=None) == []

    def test_collects_library_entries(self, fake_root: Path) -> None:
        """Library packages get kind=library and the correct tag."""
        _make_package(fake_root / "libraries", "timing", "1.2.3")

        entries = release_matrix._collect_entries(suffix="", libraries_filter=None)

        assert entries == [
            {
                "library_name": "timing",
                "library_dir": "libraries/timing",
                "version": "1.2.3",
                "tag": "chumicro-timing-v1.2.3",
                "kind": "library",
            },
        ]

    def test_collects_workbench_entries(self, fake_root: Path) -> None:
        """Workbench packages get kind=workbench."""
        _make_package(fake_root / "workbench", "deploy", "0.5.0")

        entries = release_matrix._collect_entries(suffix="", libraries_filter=None)

        assert entries == [
            {
                "library_name": "deploy",
                "library_dir": "workbench/deploy",
                "version": "0.5.0",
                "tag": "chumicro-deploy-v0.5.0",
                "kind": "workbench",
            },
        ]

    def test_applies_experimental_suffix(self, fake_root: Path) -> None:
        """The suffix flows into the tag."""
        _make_package(fake_root / "libraries", "timing", "1.0.0")

        entries = release_matrix._collect_entries(
            suffix="-experimental", libraries_filter=None,
        )

        assert entries[0]["tag"] == "chumicro-timing-v1.0.0-experimental"

    def test_filters_by_libraries(self, fake_root: Path) -> None:
        """Only packages in the filter list are returned."""
        _make_package(fake_root / "libraries", "timing", "1.0.0")
        _make_package(fake_root / "libraries", "wifi", "2.0.0")

        entries = release_matrix._collect_entries(
            suffix="", libraries_filter=["timing"],
        )

        names = [entry["library_name"] for entry in entries]
        assert names == ["timing"]

    def test_unknown_filter_name_exits(self, fake_root: Path) -> None:
        """A typo'd --libraries name fails loudly instead of silently
        no-opping into has_releases=false on a green run."""
        _make_package(fake_root / "libraries", "mqtt", "1.0.0")

        with pytest.raises(SystemExit) as excinfo:
            release_matrix._collect_entries(suffix="", libraries_filter=["mqqt"])

        message = str(excinfo.value)
        assert "Unknown package(s): mqqt" in message
        assert "Available: mqtt" in message

    def test_pypi_hyphen_form_filter_name_exits(self, fake_root: Path) -> None:
        """The PyPI hyphen form (http-server) is rejected; the directory
        basename (http_server) is the valid spelling."""
        _make_package(fake_root / "libraries", "http_server", "1.0.0")

        with pytest.raises(SystemExit) as excinfo:
            release_matrix._collect_entries(
                suffix="", libraries_filter=["http-server"],
            )

        message = str(excinfo.value)
        assert "Unknown package(s): http-server" in message
        assert "http_server" in message

    def test_malformed_version_exits(self, fake_root: Path) -> None:
        """A malformed VERSION aborts the matrix build: it could publish to
        experimental but never promote (promote_validate.py is strict)."""
        _make_package(fake_root / "libraries", "timing", "1.2.3rc1")

        with pytest.raises(SystemExit) as excinfo:
            release_matrix._collect_entries(suffix="", libraries_filter=None)

        assert "1.2.3rc1" in str(excinfo.value)

    def test_skips_existing_tags(
        self, fake_root: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Packages whose tag already exists are skipped (re-run safety)."""
        _make_package(fake_root / "libraries", "timing", "1.0.0")
        _make_package(fake_root / "libraries", "wifi", "2.0.0")

        monkeypatch.setattr(
            release_matrix, "_tag_exists",
            lambda tag: tag == "chumicro-timing-v1.0.0",
        )

        entries = release_matrix._collect_entries(suffix="", libraries_filter=None)

        names = [entry["library_name"] for entry in entries]
        assert names == ["wifi"]

    def test_strips_whitespace_from_version(self, fake_root: Path) -> None:
        """Whitespace in VERSION files is trimmed."""
        package = _make_package(fake_root / "libraries", "timing", "1.0.0")
        (package / "VERSION").write_text("  1.0.0  \n\n")

        entries = release_matrix._collect_entries(suffix="", libraries_filter=None)

        assert entries[0]["version"] == "1.0.0"

    def test_excludes_parked_library(self, fake_root: Path) -> None:
        """A parked library is held out of the release matrix (Decision 0107)."""
        _make_package(fake_root / "libraries", "timing", "1.0.0")
        parked = _make_package(fake_root / "libraries", "logging", "0.5.1")
        (parked / "PARKED").write_text("zero adopters\n")

        entries = release_matrix._collect_entries(suffix="", libraries_filter=None)

        names = [entry["library_name"] for entry in entries]
        assert names == ["timing"]

    def test_parked_excluded_even_when_named_in_filter(self, fake_root: Path) -> None:
        """An explicit --libraries request cannot release a parked library —
        un-parking (removing the marker) is the only way in (Decision 0107)."""
        parked = _make_package(fake_root / "libraries", "logging", "0.5.1")
        (parked / "PARKED").write_text("zero adopters\n")

        entries = release_matrix._collect_entries(
            suffix="", libraries_filter=["logging"],
        )

        assert entries == []

    def test_skips_pre_release_floor(self, fake_root: Path) -> None:
        """A package at 0.0.0 is held out of the matrix (Decision 0038 §6)."""
        _make_package(fake_root / "libraries", "timing", "1.0.0")
        _make_package(fake_root / "libraries", "fresh", "0.0.0")

        entries = release_matrix._collect_entries(suffix="", libraries_filter=None)

        names = [entry["library_name"] for entry in entries]
        assert names == ["timing"]

    def test_pre_release_floor_excluded_even_when_named_in_filter(
        self, fake_root: Path,
    ) -> None:
        """The 0.0.0 floor holds even for an explicit --libraries request."""
        _make_package(fake_root / "libraries", "fresh", "0.0.0")

        entries = release_matrix._collect_entries(
            suffix="", libraries_filter=["fresh"],
        )

        assert entries == []

    def test_include_tagged_keeps_existing_tags(
        self, fake_root: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """--include-tagged re-includes packages whose tag already exists."""
        _make_package(fake_root / "libraries", "timing", "1.0.0")
        _make_package(fake_root / "libraries", "wifi", "2.0.0")

        monkeypatch.setattr(
            release_matrix, "_tag_exists",
            lambda tag: tag == "chumicro-timing-v1.0.0",
        )

        entries = release_matrix._collect_entries(
            suffix="", libraries_filter=None, include_tagged=True,
        )

        names = sorted(entry["library_name"] for entry in entries)
        assert names == ["timing", "wifi"]

    def test_include_tagged_still_skips_pre_release_floor(
        self, fake_root: Path,
    ) -> None:
        """--include-tagged does not override the 0.0.0 floor."""
        _make_package(fake_root / "libraries", "fresh", "0.0.0")

        entries = release_matrix._collect_entries(
            suffix="", libraries_filter=None, include_tagged=True,
        )

        assert entries == []


class TestReadVersion:
    """Tests for _read_version."""

    def test_valid_version_passes(self, tmp_path: Path) -> None:
        """A MAJOR.MINOR.PATCH version is returned trimmed."""
        version_file = tmp_path / "VERSION"
        version_file.write_text("1.2.3\n")

        assert release_matrix._read_version(version_file) == "1.2.3"

    @pytest.mark.parametrize(
        "raw", ["1.2", "v1.2.3", "1.2.3-rc1", "1.2.3.4", "banana", ""],
    )
    def test_malformed_version_exits(self, tmp_path: Path, raw: str) -> None:
        """A non-MAJOR.MINOR.PATCH VERSION exits naming the path and content."""
        version_file = tmp_path / "VERSION"
        version_file.write_text(raw + "\n")

        with pytest.raises(SystemExit) as excinfo:
            release_matrix._read_version(version_file)

        message = str(excinfo.value)
        assert str(version_file) in message
        assert repr(raw) in message


class TestEmitOutputs:
    """Tests for _emit_outputs."""

    def test_emits_no_releases_for_empty_entries(self) -> None:
        """Empty entries yield has_releases=false and empty matrix."""
        payload = release_matrix._emit_outputs([])

        assert "has_releases=false" in payload
        assert 'matrix={"include":[]}' in payload
        assert "has_library_releases=false" in payload
        assert 'library_matrix={"include":[]}' in payload

    def test_emits_full_matrix_for_libraries(self) -> None:
        """Library entries appear in both matrix and library_matrix."""
        entries = [
            {"library_name": "timing", "library_dir": "libraries/timing",
             "version": "1.0.0", "tag": "chumicro-timing-v1.0.0", "kind": "library"},
        ]

        payload = release_matrix._emit_outputs(entries)

        assert "has_releases=true" in payload
        assert "has_library_releases=true" in payload

        matrix_line = next(line for line in payload.splitlines() if line.startswith("matrix="))
        matrix = json.loads(matrix_line.split("=", 1)[1])
        assert matrix == {"include": entries}

        prefix = "library_matrix="
        library_matrix_line = next(line for line in payload.splitlines() if line.startswith(prefix))
        library_matrix = json.loads(library_matrix_line.split("=", 1)[1])
        assert library_matrix == {"include": entries}

    def test_workbench_entry_excluded_from_library_matrix(self) -> None:
        """Workbench entries flow into matrix but not library_matrix."""
        entries = [
            {"library_name": "deploy", "library_dir": "workbench/deploy",
             "version": "0.1.0", "tag": "chumicro-deploy-v0.1.0", "kind": "workbench"},
        ]

        payload = release_matrix._emit_outputs(entries)

        assert "has_releases=true" in payload
        assert "has_library_releases=false" in payload
        assert 'library_matrix={"include":[]}' in payload


class TestMain:
    """Tests for the main entry point."""

    def test_writes_to_github_output_when_set(
        self, fake_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """When GITHUB_OUTPUT is set, payload goes to that file."""
        _make_package(fake_root / "libraries", "timing", "1.0.0")

        github_output = tmp_path / "github_output.txt"
        monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))

        result = release_matrix.main([])

        assert result == 0
        content = github_output.read_text()
        assert "has_releases=true" in content
        assert "chumicro-timing-v1.0.0" in content

    def test_writes_to_stdout_when_github_output_unset(
        self, fake_root: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Without GITHUB_OUTPUT, payload goes to stdout for local testing."""
        _make_package(fake_root / "libraries", "timing", "1.0.0")
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)

        result = release_matrix.main([])

        assert result == 0
        captured = capsys.readouterr()
        assert "has_releases=true" in captured.out

    def test_libraries_filter_flag(
        self, fake_root: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """--libraries filters to the named packages."""
        _make_package(fake_root / "libraries", "timing", "1.0.0")
        _make_package(fake_root / "libraries", "wifi", "2.0.0")
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)

        result = release_matrix.main(["--libraries", "timing"])

        assert result == 0
        captured = capsys.readouterr()
        assert "chumicro-timing-v1.0.0" in captured.out
        assert "wifi" not in captured.out

    def test_include_tagged_flag(
        self, fake_root: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """--include-tagged reaches _collect_entries so a tagged package stays."""
        _make_package(fake_root / "libraries", "timing", "1.0.0")
        monkeypatch.setattr(release_matrix, "_tag_exists", lambda _: True)
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)

        result = release_matrix.main(["--include-tagged", "--libraries", "timing"])

        assert result == 0
        captured = capsys.readouterr()
        assert "has_releases=true" in captured.out
        assert "chumicro-timing-v1.0.0" in captured.out

    def test_include_tagged_without_libraries_exits(
        self, fake_root: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An unscoped --include-tagged would re-run EVERY tagged package,
        overwriting GitHub-release assets from a drifted tree."""
        _make_package(fake_root / "libraries", "timing", "1.0.0")
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)

        with pytest.raises(SystemExit) as excinfo:
            release_matrix.main(["--include-tagged"])

        assert "--include-tagged requires --libraries" in str(excinfo.value)

    def test_include_tagged_with_blank_libraries_exits(
        self, fake_root: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A whitespace-only --libraries value does not scope the re-run."""
        _make_package(fake_root / "libraries", "timing", "1.0.0")
        monkeypatch.delenv("GITHUB_OUTPUT", raising=False)

        with pytest.raises(SystemExit) as excinfo:
            release_matrix.main(["--include-tagged", "--libraries", " , "])

        assert "--include-tagged requires --libraries" in str(excinfo.value)
