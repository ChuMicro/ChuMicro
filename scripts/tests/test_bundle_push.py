"""Tests for bundle_push.py — bundle repository commit/tag/push helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

import bundle_push
import pytest


class TestBuildCommitMessageFromMatrix:
    """Tests for _build_commit_message_from_matrix."""

    def test_single_entry(self) -> None:
        """A one-entry matrix yields ``Update: name vX``."""
        matrix = '{"include":[{"library_name":"timing","version":"1.0.0"}]}'

        result = bundle_push._build_commit_message_from_matrix(matrix)

        assert result == "Update: timing v1.0.0"

    def test_multiple_entries(self) -> None:
        """Multiple entries are joined with ', '."""
        matrix = (
            '{"include":[{"library_name":"timing","version":"1.0.0"},'
            '{"library_name":"wifi","version":"2.0.0"}]}'
        )

        result = bundle_push._build_commit_message_from_matrix(matrix)

        assert result == "Update: timing v1.0.0, wifi v2.0.0"

    def test_empty_matrix(self) -> None:
        """An empty matrix yields a placeholder message."""
        result = bundle_push._build_commit_message_from_matrix('{"include":[]}')

        assert "empty matrix" in result


class TestPushBundle:
    """Tests for push_bundle."""

    def test_returns_nonzero_when_bundle_dir_missing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture,
    ) -> None:
        """A non-existent bundle-dir exits 1."""
        result = bundle_push.push_bundle(
            tmp_path / "nonexistent", "2026.05.10", "Update: timing v1.0.0",
        )

        assert result == 1
        assert "does not exist" in capsys.readouterr().err

    def test_returns_zero_when_no_changes_and_tag_on_remote(
        self, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """No staged changes and the tag already on the remote → clean exit 0."""
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()

        calls: list[list[str]] = []

        def fake_run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[bytes]:
            calls.append(command)
            return subprocess.CompletedProcess(command, 0)

        monkeypatch.setattr(bundle_push, "_run", fake_run)
        monkeypatch.setattr(bundle_push, "_has_staged_changes", lambda _: False)
        monkeypatch.setattr(bundle_push, "_tag_on_remote", lambda *_: True)

        result = bundle_push.push_bundle(
            bundle_dir, "2026.05.10", "Update: timing v1.0.0",
        )

        assert result == 0
        assert "No changes to commit" in capsys.readouterr().out
        # We should have run git config + git add but no commit/tag/push.
        commands = [call[1] for call in calls if call[0] == "git"]
        assert "commit" not in commands
        assert "tag" not in commands
        assert "push" not in commands

    def test_pushes_unpushed_tag_when_committed_but_not_on_remote(
        self, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No staged changes but the tag is missing on the remote → push it.

        Models a prior run that committed the bundle then failed at the tag
        push: the re-run finds nothing staged yet must not exit 0 with the
        release untagged.
        """
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()

        calls: list[list[str]] = []

        def fake_run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[bytes]:
            calls.append(command)
            return subprocess.CompletedProcess(command, 0)

        monkeypatch.setattr(bundle_push, "_run", fake_run)
        monkeypatch.setattr(bundle_push, "_has_staged_changes", lambda _: False)
        monkeypatch.setattr(bundle_push, "_tag_on_remote", lambda *_: False)

        result = bundle_push.push_bundle(
            bundle_dir, "2026.05.10", "Update: timing v1.0.0",
        )

        assert result == 0
        commands = [call[1] for call in calls if call[0] == "git"]
        assert "commit" not in commands  # nothing to commit
        assert "tag" in commands
        assert "push" in commands
        # The push carries the tag refspec.
        push_call = next(call for call in calls if call[:2] == ["git", "push"])
        assert "2026.05.10" in push_call

    def test_returns_push_failure_when_repushing_unpushed_tag(
        self, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A failed re-push of the unpushed tag propagates its exit code."""
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()

        def fake_run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[bytes]:
            if command[:2] == ["git", "push"]:
                return subprocess.CompletedProcess(command, 9)
            return subprocess.CompletedProcess(command, 0)

        monkeypatch.setattr(bundle_push, "_run", fake_run)
        monkeypatch.setattr(bundle_push, "_has_staged_changes", lambda _: False)
        monkeypatch.setattr(bundle_push, "_tag_on_remote", lambda *_: False)

        result = bundle_push.push_bundle(
            bundle_dir, "2026.05.10", "Update: timing v1.0.0",
        )

        assert result == 9

    def test_commits_tags_and_pushes_when_changes_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Staged changes → commit + tag + push."""
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()

        calls: list[list[str]] = []

        def fake_run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[bytes]:
            calls.append(command)
            return subprocess.CompletedProcess(command, 0)

        monkeypatch.setattr(bundle_push, "_run", fake_run)
        monkeypatch.setattr(bundle_push, "_has_staged_changes", lambda _: True)

        result = bundle_push.push_bundle(
            bundle_dir, "2026.05.10", "Update: timing v1.0.0",
        )

        assert result == 0
        commands = [call[1] for call in calls if call[0] == "git"]
        assert "commit" in commands
        assert "tag" in commands
        assert "push" in commands

    def test_returns_push_failure_code(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A failing git push propagates its exit code."""
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()

        def fake_run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[bytes]:
            if command[:2] == ["git", "push"]:
                return subprocess.CompletedProcess(command, 7)
            return subprocess.CompletedProcess(command, 0)

        monkeypatch.setattr(bundle_push, "_run", fake_run)
        monkeypatch.setattr(bundle_push, "_has_staged_changes", lambda _: True)

        result = bundle_push.push_bundle(
            bundle_dir, "2026.05.10", "Update: timing v1.0.0",
        )

        assert result == 7


class TestMain:
    """Tests for the CLI entry point."""

    def test_matrix_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """--matrix builds the commit message and delegates to push_bundle."""
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()

        captured: dict[str, object] = {}

        def fake_push(directory: Path, tag: str, message: str) -> int:
            captured["dir"] = directory
            captured["tag"] = tag
            captured["message"] = message
            return 0

        monkeypatch.setattr(bundle_push, "push_bundle", fake_push)

        result = bundle_push.main([
            "--bundle-dir", str(bundle_dir),
            "--tag", "2026.05.10",
            "--matrix", '{"include":[{"library_name":"timing","version":"1.0.0"}]}',
        ])

        assert result == 0
        assert captured["message"] == "Update: timing v1.0.0"

    def test_commit_message_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """--commit-message passes the literal message through."""
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()

        captured: dict[str, object] = {}

        def fake_push(directory: Path, tag: str, message: str) -> int:
            captured["message"] = message
            return 0

        monkeypatch.setattr(bundle_push, "push_bundle", fake_push)

        result = bundle_push.main([
            "--bundle-dir", str(bundle_dir),
            "--tag", "2026.05.10",
            "--commit-message", "Update: wifi v2.5.1",
        ])

        assert result == 0
        assert captured["message"] == "Update: wifi v2.5.1"

    def test_requires_one_of_matrix_or_message(
        self, tmp_path: Path, capsys: pytest.CaptureFixture,
    ) -> None:
        """Neither --matrix nor --commit-message → argparse exits non-zero."""
        bundle_dir = tmp_path / "bundle"
        bundle_dir.mkdir()

        with pytest.raises(SystemExit):
            bundle_push.main([
                "--bundle-dir", str(bundle_dir),
                "--tag", "2026.05.10",
            ])
