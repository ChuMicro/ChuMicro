"""Tests for release_source.py — source archive replay helpers."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
import release_source


def _make_archive(target: Path, payload: dict[str, str]) -> None:
    """Build a zip at ``target`` containing the given filename→content payload."""
    with zipfile.ZipFile(target, "w") as archive:
        for name, content in payload.items():
            archive.writestr(name, content)


#: Minimal payload satisfying the full-tree archive verification
#: (pyproject.toml, VERSION, src/ must all be present after extraction).
_FULL_TREE_PAYLOAD = {
    "src/chumicro_timing/__init__.py": "# new\n",
    "VERSION": "1.0.0\n",
    "pyproject.toml": "[project]\nname = 'chumicro-timing'\n",
    "README.md": "# new\n",
}


class TestReplacePackageSource:
    """Tests for _replace_package_source."""

    def test_removes_existing_src_directory(self, tmp_path: Path) -> None:
        """Existing src/ tree is wiped before unpack."""
        library_dir = tmp_path / "libraries" / "timing"
        (library_dir / "src" / "stale").mkdir(parents=True)
        (library_dir / "src" / "stale" / "old.py").write_text("# old\n")

        archive = tmp_path / "archive.zip"
        _make_archive(archive, {
            "src/chumicro_timing/__init__.py": "# new\n",
            "VERSION": "1.0.0\n",
            "pyproject.toml": "[project]\nname = 'chumicro-timing'\n",
            "README.md": "# new\n",
        })

        release_source._replace_package_source(library_dir, archive)

        assert not (library_dir / "src" / "stale").exists()
        assert (library_dir / "src" / "chumicro_timing" / "__init__.py").read_text() == "# new\n"

    def test_removes_existing_top_level_files(self, tmp_path: Path) -> None:
        """Existing pyproject.toml / VERSION / README.md are replaced by archive contents."""
        library_dir = tmp_path / "libraries" / "timing"
        library_dir.mkdir(parents=True)
        (library_dir / "pyproject.toml").write_text("[project]\nname = 'old'\n")
        (library_dir / "VERSION").write_text("0.0.1\n")
        (library_dir / "README.md").write_text("old\n")

        archive = tmp_path / "archive.zip"
        _make_archive(archive, {**_FULL_TREE_PAYLOAD, "VERSION": "2.0.0\n"})

        release_source._replace_package_source(library_dir, archive)

        assert (library_dir / "VERSION").read_text() == "2.0.0\n"
        assert "chumicro-timing" in (library_dir / "pyproject.toml").read_text()
        assert (library_dir / "README.md").read_text() == "# new\n"

    def test_removes_trees_absent_from_archive(self, tmp_path: Path) -> None:
        """Existing trees not in the archive (tests/, docs/) are wiped, not mixed.

        The stable sdist ships tests/, examples/, and docs/; leaving
        main-current copies in place would blend frozen src with newer
        trees in the promoted build.
        """
        library_dir = tmp_path / "libraries" / "timing"
        (library_dir / "tests").mkdir(parents=True)
        (library_dir / "tests" / "test_newer_api.py").write_text("# from main\n")
        (library_dir / "docs").mkdir()
        (library_dir / "docs" / "guide.md").write_text("# from main\n")

        archive = tmp_path / "archive.zip"
        _make_archive(archive, {
            **_FULL_TREE_PAYLOAD,
            "tests/test_frozen.py": "# frozen\n",
        })

        release_source._replace_package_source(library_dir, archive)

        assert not (library_dir / "tests" / "test_newer_api.py").exists()
        assert not (library_dir / "docs").exists()
        assert (library_dir / "tests" / "test_frozen.py").read_text() == "# frozen\n"

    def test_tolerates_missing_targets(self, tmp_path: Path) -> None:
        """Replaying onto a directory without existing files does not raise."""
        library_dir = tmp_path / "libraries" / "timing"
        library_dir.mkdir(parents=True)

        archive = tmp_path / "archive.zip"
        _make_archive(archive, _FULL_TREE_PAYLOAD)

        release_source._replace_package_source(library_dir, archive)

        assert (library_dir / "VERSION").read_text() == "1.0.0\n"

    def test_incomplete_archive_raises(self, tmp_path: Path) -> None:
        """An archive missing src/ (the pre-full-tree format) fails loudly."""
        library_dir = tmp_path / "libraries" / "timing"
        library_dir.mkdir(parents=True)

        archive = tmp_path / "archive.zip"
        _make_archive(archive, {"VERSION": "1.0.0\n", "pyproject.toml": "[project]\n"})

        with pytest.raises(RuntimeError, match="full-tree archive"):
            release_source._replace_package_source(library_dir, archive)


class TestMain:
    """Tests for the CLI entry point."""

    def test_returns_nonzero_when_library_dir_missing(
        self, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A non-existent library-dir exits 1."""
        monkeypatch.setattr(release_source, "ROOT", tmp_path)

        result = release_source.main([
            "--tag", "chumicro-timing-v1.0.0-experimental",
            "--source-zip", "chumicro-timing-v1.0.0-source.zip",
            "--library-dir", "libraries/nonexistent",
        ])

        assert result == 1
        assert "does not exist" in capsys.readouterr().err

    def test_replays_archive_end_to_end(
        self, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """A valid call downloads (fake) and unpacks onto library_dir."""
        library_dir = tmp_path / "libraries" / "timing"
        library_dir.mkdir(parents=True)
        monkeypatch.setattr(release_source, "ROOT", tmp_path)

        def fake_download(tag: str, source_zip: str, target_dir: Path) -> Path:
            archive = target_dir / source_zip
            target_dir.mkdir(parents=True, exist_ok=True)
            _make_archive(archive, _FULL_TREE_PAYLOAD)
            return archive

        monkeypatch.setattr(release_source, "_download_archive", fake_download)

        result = release_source.main([
            "--tag", "chumicro-timing-v1.0.0-experimental",
            "--source-zip", "chumicro-timing-v1.0.0-source.zip",
            "--library-dir", "libraries/timing",
        ])

        assert result == 0
        assert (library_dir / "VERSION").read_text() == "1.0.0\n"
