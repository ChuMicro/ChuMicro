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
        _make_archive(archive, {
            "pyproject.toml": "[project]\nname = 'chumicro-timing'\n",
            "VERSION": "2.0.0\n",
            "README.md": "new\n",
        })

        release_source._replace_package_source(library_dir, archive)

        assert (library_dir / "VERSION").read_text() == "2.0.0\n"
        assert "chumicro-timing" in (library_dir / "pyproject.toml").read_text()
        assert (library_dir / "README.md").read_text() == "new\n"

    def test_tolerates_missing_targets(self, tmp_path: Path) -> None:
        """Replaying onto a directory without existing files does not raise."""
        library_dir = tmp_path / "libraries" / "timing"
        library_dir.mkdir(parents=True)

        archive = tmp_path / "archive.zip"
        _make_archive(archive, {"VERSION": "1.0.0\n"})

        release_source._replace_package_source(library_dir, archive)

        assert (library_dir / "VERSION").read_text() == "1.0.0\n"


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
            _make_archive(archive, {"VERSION": "1.0.0\n"})
            return archive

        monkeypatch.setattr(release_source, "_download_archive", fake_download)

        result = release_source.main([
            "--tag", "chumicro-timing-v1.0.0-experimental",
            "--source-zip", "chumicro-timing-v1.0.0-source.zip",
            "--library-dir", "libraries/timing",
        ])

        assert result == 0
        assert (library_dir / "VERSION").read_text() == "1.0.0\n"
