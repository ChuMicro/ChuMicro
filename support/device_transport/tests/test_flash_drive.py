"""Tests for flash_drive — CircuitPython flash-mode USB helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from chumicro_device_transport import flash_drive
from chumicro_device_transport.flash_drive import FlashDriveError


class TestMergePackages:
    """Tests for flash_drive.merge_packages."""

    def test_copies_top_level_packages(self, tmp_path: Path) -> None:
        """Packages with __init__.py are copied into the staging dir."""
        source = tmp_path / "src"
        source.mkdir()
        package = source / "chumicro_example"
        package.mkdir()
        (package / "__init__.py").write_text("# init")
        (package / "core.py").write_text("# core")

        staging = tmp_path / "staging"
        staging.mkdir()
        flash_drive.merge_packages(source, staging)

        assert (staging / "chumicro_example" / "__init__.py").is_file()
        assert (staging / "chumicro_example" / "core.py").is_file()

    def test_skips_directories_without_init(self, tmp_path: Path) -> None:
        """Directories without __init__.py are skipped."""
        source = tmp_path / "src"
        source.mkdir()
        (source / "notapackage").mkdir()
        (source / "notapackage" / "data.txt").write_text("data")

        staging = tmp_path / "staging"
        staging.mkdir()
        flash_drive.merge_packages(source, staging)

        assert not (staging / "notapackage").exists()

    def test_skips_missing_source(self, tmp_path: Path) -> None:
        """A nonexistent source directory is silently skipped."""
        staging = tmp_path / "staging"
        staging.mkdir()
        flash_drive.merge_packages(tmp_path / "missing", staging)
        assert list(staging.iterdir()) == []

    def test_merges_with_existing_staging_content(self, tmp_path: Path) -> None:
        """dirs_exist_ok=True means repeated merges don't fail on collisions."""
        source_a = tmp_path / "src_a"
        source_a.mkdir()
        (source_a / "pkg").mkdir()
        (source_a / "pkg" / "__init__.py").write_text("")
        (source_a / "pkg" / "one.py").write_text("# one")

        source_b = tmp_path / "src_b"
        source_b.mkdir()
        (source_b / "pkg").mkdir()
        (source_b / "pkg" / "__init__.py").write_text("")
        (source_b / "pkg" / "two.py").write_text("# two")

        staging = tmp_path / "staging"
        staging.mkdir()
        flash_drive.merge_packages(source_a, staging)
        flash_drive.merge_packages(source_b, staging)

        assert (staging / "pkg" / "one.py").is_file()
        assert (staging / "pkg" / "two.py").is_file()

    def test_ignores_pycache(self, tmp_path: Path) -> None:
        """__pycache__ is excluded from the merge."""
        source = tmp_path / "src"
        source.mkdir()
        (source / "pkg").mkdir()
        (source / "pkg" / "__init__.py").write_text("")
        (source / "pkg" / "__pycache__").mkdir()
        (source / "pkg" / "__pycache__" / "cached.pyc").write_text("bytecode")

        staging = tmp_path / "staging"
        staging.mkdir()
        flash_drive.merge_packages(source, staging)

        assert not (staging / "pkg" / "__pycache__").exists()


class TestRsync:
    """Tests for flash_drive.rsync."""

    def test_raises_on_failure(self, tmp_path: Path) -> None:
        """rsync failure produces a FlashDriveError."""
        source = tmp_path / "source"
        source.mkdir()
        destination = tmp_path / "destination"
        destination.mkdir()

        with patch(
            "chumicro_device_transport.flash_drive.subprocess.run",
            side_effect=subprocess.CalledProcessError(
                1, "rsync", stderr="permission denied",
            ),
        ):
            with pytest.raises(FlashDriveError, match="rsync failed"):
                flash_drive.rsync(source, destination)

    def test_raises_when_not_installed(self, tmp_path: Path) -> None:
        """FileNotFoundError becomes a clear FlashDriveError message."""
        source = tmp_path / "source"
        source.mkdir()
        destination = tmp_path / "destination"
        destination.mkdir()

        with patch(
            "chumicro_device_transport.flash_drive.subprocess.run",
            side_effect=FileNotFoundError("rsync"),
        ):
            with pytest.raises(FlashDriveError, match="rsync is required"):
                flash_drive.rsync(source, destination)

    def test_uses_expected_excludes(self, tmp_path: Path) -> None:
        """rsync command excludes boot.py, settings.toml, .DS_Store, ._*, __pycache__."""
        source = tmp_path / "source"
        source.mkdir()
        destination = tmp_path / "destination"
        destination.mkdir()

        captured: list[list[str]] = []

        def fake_run(command, **kwargs):
            captured.append(command)
            return subprocess.CompletedProcess(args=command, returncode=0)

        with patch(
            "chumicro_device_transport.flash_drive.subprocess.run",
            side_effect=fake_run,
        ):
            flash_drive.rsync(source, destination)

        assert captured
        command = captured[0]
        assert "--delete" in command
        assert "--checksum" in command
        assert "--inplace" in command
        for exclude in (
            "--exclude=__pycache__",
            "--exclude=*.pyc",
            "--exclude=.DS_Store",
            "--exclude=._*",
            "--exclude=boot.py",
            "--exclude=boot_out.txt",
            "--exclude=code.py",
            "--exclude=settings.toml",
        ):
            assert exclude in command


class TestMacOSHelpers:
    """Tests for strip_extended_attributes / clean_dot_files / disable_spotlight_indexing."""

    def test_strip_extended_attributes_calls_xattr(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """On macOS, strip_extended_attributes runs `xattr -cr <path>`."""
        monkeypatch.setattr(
            "chumicro_device_transport.flash_drive._sys_module.platform",
            "darwin",
        )
        captured: list[list[str]] = []

        def fake_run(command, **kwargs):
            captured.append(command)
            return subprocess.CompletedProcess(args=command, returncode=0)

        with patch(
            "chumicro_device_transport.flash_drive.subprocess.run",
            side_effect=fake_run,
        ):
            flash_drive.strip_extended_attributes(tmp_path)

        assert ["xattr", "-cr", str(tmp_path)] in captured

    def test_strip_extended_attributes_tolerates_missing_xattr(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Missing xattr binary is a warning, not a raise."""
        monkeypatch.setattr(
            "chumicro_device_transport.flash_drive._sys_module.platform",
            "darwin",
        )
        with patch(
            "chumicro_device_transport.flash_drive.subprocess.run",
            side_effect=FileNotFoundError("xattr"),
        ):
            flash_drive.strip_extended_attributes(tmp_path)  # must not raise

    def test_clean_dot_files_calls_dot_clean(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """On macOS, clean_dot_files runs dot_clean on the drive path."""
        monkeypatch.setattr(
            "chumicro_device_transport.flash_drive._sys_module.platform",
            "darwin",
        )
        captured: list[list[str]] = []

        def fake_run(command, **kwargs):
            captured.append(command)
            return subprocess.CompletedProcess(args=command, returncode=0)

        with patch(
            "chumicro_device_transport.flash_drive.subprocess.run",
            side_effect=fake_run,
        ):
            flash_drive.clean_dot_files(tmp_path)

        assert ["dot_clean", str(tmp_path)] in captured

    def test_clean_dot_files_tolerates_missing_dot_clean(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Missing dot_clean binary does not raise."""
        monkeypatch.setattr(
            "chumicro_device_transport.flash_drive._sys_module.platform",
            "darwin",
        )
        with patch(
            "chumicro_device_transport.flash_drive.subprocess.run",
            side_effect=FileNotFoundError("dot_clean"),
        ):
            flash_drive.clean_dot_files(tmp_path)  # must not raise

    def test_disable_spotlight_indexing_calls_mdutil(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """On macOS, disable_spotlight_indexing runs mdutil -i off."""
        monkeypatch.setattr(
            "chumicro_device_transport.flash_drive._sys_module.platform",
            "darwin",
        )
        captured: list[list[str]] = []

        def fake_run(command, **kwargs):
            captured.append(command)
            return subprocess.CompletedProcess(args=command, returncode=0)

        with patch(
            "chumicro_device_transport.flash_drive.subprocess.run",
            side_effect=fake_run,
        ):
            flash_drive.disable_spotlight_indexing(tmp_path)

        assert ["mdutil", "-i", "off", str(tmp_path)] in captured

    def test_disable_spotlight_indexing_tolerates_missing_mdutil(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Missing mdutil binary does not raise."""
        monkeypatch.setattr(
            "chumicro_device_transport.flash_drive._sys_module.platform",
            "darwin",
        )
        with patch(
            "chumicro_device_transport.flash_drive.subprocess.run",
            side_effect=FileNotFoundError("mdutil"),
        ):
            flash_drive.disable_spotlight_indexing(tmp_path)  # must not raise


class TestFlushVolume:
    """Tests for flash_drive.flush_volume."""

    def test_calls_sync_on_darwin(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """On macOS, flush_volume runs the `sync` command."""
        monkeypatch.setattr(
            "chumicro_device_transport.flash_drive._sys_module.platform",
            "darwin",
        )
        captured: list[list[str]] = []

        def fake_run(command, **kwargs):
            captured.append(command)
            return subprocess.CompletedProcess(args=command, returncode=0)

        sleep_calls: list[float] = []
        with patch(
            "chumicro_device_transport.flash_drive.subprocess.run",
            side_effect=fake_run,
        ):
            flash_drive.flush_volume(tmp_path, sleep=sleep_calls.append)

        assert ["sync"] in captured

    def test_routes_settle_delay_through_injected_sleep(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The settle delay is applied via the injected sleep callable.

        Ensures Decision 0010 constructor injection holds so flash-mode
        tests can skip the real 0.5 s settle delay.
        """
        monkeypatch.setattr(
            "chumicro_device_transport.flash_drive._sys_module.platform",
            "darwin",
        )
        sleep_durations: list[float] = []

        with patch(
            "chumicro_device_transport.flash_drive.subprocess.run",
            side_effect=lambda command, **kwargs: subprocess.CompletedProcess(
                args=command, returncode=0,
            ),
        ):
            flash_drive.flush_volume(tmp_path, sleep=sleep_durations.append)

        assert sleep_durations == [flash_drive.FLUSH_SETTLE_DELAY]

    def test_honors_custom_settle_delay(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Callers can override the settle delay per-invocation."""
        monkeypatch.setattr(
            "chumicro_device_transport.flash_drive._sys_module.platform",
            "darwin",
        )
        sleep_durations: list[float] = []

        with patch(
            "chumicro_device_transport.flash_drive.subprocess.run",
            side_effect=lambda command, **kwargs: subprocess.CompletedProcess(
                args=command, returncode=0,
            ),
        ):
            flash_drive.flush_volume(
                tmp_path,
                sleep=sleep_durations.append,
                settle_delay=0.123,
            )

        assert sleep_durations == [0.123]
