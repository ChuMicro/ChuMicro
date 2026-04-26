"""End-to-end CLI tests."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest
from chumicro_workspace_template import cli

# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class TestParser:
    EXPECTED_COMMANDS = ("init", "update")

    def test_all_commands_register(self) -> None:
        parser = cli.build_parser()
        subparsers_action = next(
            action for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        )
        registered = set(subparsers_action.choices)
        missing = set(self.EXPECTED_COMMANDS) - registered
        assert not missing

    def test_help_does_not_crash(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        with pytest.raises(SystemExit) as caught:
            cli.main(["--help"])
        assert caught.value.code == 0


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


class TestInitCommand:
    def test_init_creates_workspace(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        target = tmp_path / "fresh"
        exit_code = cli.main(["init", str(target)])
        assert exit_code == 0
        assert (target / "workspace.yml").is_file()
        assert (target / ".gitignore").is_file()
        # Summary printed to stdout.
        out = capsys.readouterr().out
        assert "summary:" in out
        assert "written=" in out

    def test_init_skipped_files_return_one(
        self,
        tmp_path: Path,
    ) -> None:
        target = tmp_path / "fresh"
        cli.main(["init", str(target)])
        # Re-run on already-populated dir without --force.
        exit_code = cli.main(["init", str(target)])
        assert exit_code == 1

    def test_init_force_returns_zero(
        self,
        tmp_path: Path,
    ) -> None:
        target = tmp_path / "fresh"
        cli.main(["init", str(target)])
        exit_code = cli.main(["init", str(target), "--force"])
        assert exit_code == 0

    def test_init_from_custom_source(
        self,
        tmp_path: Path,
    ) -> None:
        custom = tmp_path / "tpl"
        custom.mkdir()
        (custom / "workspace.yml").write_text("defaults:\n  custom: true\n")
        target = tmp_path / "fresh"
        exit_code = cli.main(["init", str(target), "--from", str(custom)])
        assert exit_code == 0
        assert "custom: true" in (target / "workspace.yml").read_text()

    def test_init_missing_source_returns_two(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        exit_code = cli.main([
            "init", str(tmp_path / "fresh"),
            "--from", str(tmp_path / "missing"),
        ])
        assert exit_code == 2
        assert "does not exist" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


class TestUpdateCommand:
    def test_update_refreshes_tool_owned(
        self,
        tmp_path: Path,
    ) -> None:
        target = tmp_path / "ws"
        cli.main(["init", str(target)])
        # Drift the tool-owned run.py.
        (target / "run.py").write_text("# drifted\n")
        exit_code = cli.main(["update", str(target)])
        assert exit_code == 0
        # Refresh restored canonical bytes.
        assert "drifted" not in (target / "run.py").read_text()

    def test_update_default_target_is_cwd(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        target = tmp_path / "ws"
        cli.main(["init", str(target)])
        monkeypatch.chdir(target)
        exit_code = cli.main(["update"])
        assert exit_code == 0

    def test_update_missing_target_returns_two(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        exit_code = cli.main(["update", str(tmp_path / "no-such-dir")])
        assert exit_code == 2
        assert "does not exist" in capsys.readouterr().err
