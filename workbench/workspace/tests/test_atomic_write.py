"""Tests for chumicro_workspace.atomic_write — crash-safe file writes.

A mid-write crash must never truncate the target, since it may be the
user's only copy of secrets.toml credentials.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
from chumicro_workspace.atomic_write import atomic_write_text


class TestAtomicWriteText:
    def test_creates_new_file(self, tmp_path: Path) -> None:
        target = tmp_path / "new.txt"
        atomic_write_text(target, "hello\n")
        assert target.read_text() == "hello\n"

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        target = tmp_path / "existing.txt"
        target.write_text("old\n")
        atomic_write_text(target, "new\n")
        assert target.read_text() == "new\n"

    def test_preserves_existing_permissions(self, tmp_path: Path) -> None:
        target = tmp_path / "secrets.toml"
        target.write_text("[wifi]\n")
        target.chmod(0o600)
        atomic_write_text(target, "[wifi]\nssid = 'x'\n")
        assert stat.S_IMODE(target.stat().st_mode) == 0o600

    def test_no_temp_litter_after_success(self, tmp_path: Path) -> None:
        target = tmp_path / "workspace.yml"
        atomic_write_text(target, "a: 1\n")
        # The temp file was renamed onto the target, leaving only it.
        assert [entry.name for entry in tmp_path.iterdir()] == ["workspace.yml"]

    def test_original_survives_failed_replace(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Simulate a crash at the rename step: the original bytes must
        # remain intact and no temp file may be left behind.
        target = tmp_path / "secrets.toml"
        target.write_text("original\n")

        def boom(source, destination):
            raise OSError("disk full")

        monkeypatch.setattr(
            "chumicro_workspace.atomic_write.os.replace", boom,
        )
        with pytest.raises(OSError, match="disk full"):
            atomic_write_text(target, "replacement\n")
        assert target.read_text() == "original\n"
        assert [entry.name for entry in tmp_path.iterdir()] == ["secrets.toml"]
