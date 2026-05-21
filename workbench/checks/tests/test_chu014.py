"""Tests for CHU014: workspace CLI command-table parity."""

from __future__ import annotations

from pathlib import Path

from chumicro_checks.rules.chu014 import (
    CHU014,
    _command_token,
    _documented_commands,
    _find_command_table,
    _registered_commands,
)

_CLI_DIR = "workbench/workspace/src/chumicro_workspace/cli"
_README = "workbench/workspace/README.md"


def _stage(repo_root: Path, relative: str, content: str) -> Path:
    target = repo_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def _adder(*commands: str) -> str:
    """A cli module registering *commands* as top-level subparsers."""
    calls = "\n".join(
        f'    subparsers.add_parser("{name}", help="h")' for name in commands
    )
    return (
        "import argparse\n\n\n"
        "def _add_parsers(subparsers: argparse._SubParsersAction) -> None:\n"
        f"{calls}\n"
    )


def _readme(*rows: str) -> str:
    body = "\n".join(rows)
    return (
        "# chumicro-workspace\n\n"
        "## Commands\n\n"
        "| Group | Commands |\n"
        "|---|---|\n"
        f"{body}\n\n"
        "Other prose.\n"
    )


class TestSilentNoOp:
    def test_empty_repo(self, tmp_path: Path) -> None:
        assert CHU014.check(tmp_path) == []

    def test_cli_dir_but_no_readme(self, tmp_path: Path) -> None:
        _stage(tmp_path, f"{_CLI_DIR}/deploy.py", _adder("deploy"))
        assert CHU014.check(tmp_path) == []

    def test_readme_without_command_table(self, tmp_path: Path) -> None:
        _stage(tmp_path, f"{_CLI_DIR}/deploy.py", _adder("deploy"))
        _stage(tmp_path, _README, "# workspace\n\nNo table here.\n")
        assert CHU014.check(tmp_path) == []

    def test_no_registered_commands(self, tmp_path: Path) -> None:
        _stage(tmp_path, f"{_CLI_DIR}/empty.py", "x = 1\n")
        _stage(tmp_path, _README, _readme("| **G** | `deploy` |"))
        assert CHU014.check(tmp_path) == []


class TestParity:
    def test_clean_parity_passes(self, tmp_path: Path) -> None:
        _stage(tmp_path, f"{_CLI_DIR}/cli.py", _adder("deploy", "probe"))
        _stage(
            tmp_path, _README, _readme("| **G** | `deploy <x>`, `probe` |"),
        )
        assert CHU014.check(tmp_path) == []

    def test_phantom_command_flagged(self, tmp_path: Path) -> None:
        _stage(tmp_path, f"{_CLI_DIR}/cli.py", _adder("deploy"))
        _stage(
            tmp_path,
            _README,
            _readme("| **G** | `deploy`, `teleport` |"),
        )
        findings = CHU014.check(tmp_path)
        assert len(findings) == 1
        assert "teleport" in findings[0].message
        assert "phantom" in findings[0].message

    def test_hidden_command_flagged(self, tmp_path: Path) -> None:
        _stage(tmp_path, f"{_CLI_DIR}/cli.py", _adder("deploy", "secret"))
        _stage(tmp_path, _README, _readme("| **G** | `deploy` |"))
        findings = CHU014.check(tmp_path)
        assert len(findings) == 1
        assert "secret" in findings[0].message
        assert "hidden" in findings[0].message

    def test_nested_verbs_are_not_top_level(self, tmp_path: Path) -> None:
        """`verbs.add_parser("list")` is a sub-verb, not a command."""
        module = (
            "import argparse\n\n\n"
            "def _add(subparsers: argparse._SubParsersAction) -> None:\n"
            '    library = subparsers.add_parser("library", help="h")\n'
            "    verbs = library.add_subparsers()\n"
            '    verbs.add_parser("list", help="h")\n'
            '    verbs.add_parser("add", help="h")\n'
        )
        _stage(tmp_path, f"{_CLI_DIR}/library.py", module)
        _stage(tmp_path, _README, _readme("| **G** | `library list\\|add` |"))
        # Only `library` is top-level. `list`/`add` must not be
        # treated as hidden commands.
        assert CHU014.check(tmp_path) == []


class TestEscapedPipeParsing:
    """Regression: GFM cells legitimately contain ``\\|``."""

    def test_escaped_pipe_cell_not_shredded(self, tmp_path: Path) -> None:
        _stage(
            tmp_path,
            f"{_CLI_DIR}/cli.py",
            _adder("library", "install-libraries"),
        )
        _stage(
            tmp_path,
            _README,
            _readme(
                "| **Libraries** | `library list\\|add\\|remove`, "
                "`install-libraries <project>` |",
            ),
        )
        # A naive split("|") would split the library cell and read
        # `library`/`install-libraries` as hidden.  Correct parsing
        # sees both documented, which is clean.
        assert CHU014.check(tmp_path) == []

    def test_documented_extracts_leading_token_only(
        self, tmp_path: Path,
    ) -> None:
        lines = _readme(
            "| **G** | `library list\\|add\\|remove` |",
        ).splitlines()
        header = _find_command_table(lines)
        assert header is not None
        documented = _documented_commands(lines, header)
        assert "library" in documented
        # The verbs after `library ` are not separate commands.
        assert "list" not in documented
        assert "add" not in documented


class TestCommandToken:
    def test_plain_command(self) -> None:
        assert _command_token("deploy") == "deploy"

    def test_hyphenated_command(self) -> None:
        assert _command_token("add-device") == "add-device"

    def test_command_with_arg_placeholder(self) -> None:
        assert _command_token("new <path>") == "new"
        assert _command_token("repl [<project>]") == "repl"

    def test_prose_filename_rejected(self) -> None:
        # `workspace.yml` is table prose, not a command.
        assert _command_token("workspace.yml") is None

    def test_prose_with_colon_rejected(self) -> None:
        assert _command_token("quality:") is None

    def test_flag_rejected(self) -> None:
        assert _command_token("--flat") is None


class TestSuppression:
    def test_noqa_on_phantom_row(self, tmp_path: Path) -> None:
        _stage(tmp_path, f"{_CLI_DIR}/cli.py", _adder("deploy"))
        _stage(
            tmp_path,
            _README,
            _readme(
                "| **G** | `deploy`, `teleport` | <!-- noqa: CHU014 -->",
            ),
        )
        assert CHU014.check(tmp_path) == []

    def test_noqa_on_table_header_suppresses_hidden(
        self, tmp_path: Path,
    ) -> None:
        _stage(tmp_path, f"{_CLI_DIR}/cli.py", _adder("deploy", "secret"))
        readme = (
            "# workspace\n\n"
            "| Group | Commands | <!-- noqa: CHU014 -->\n"
            "|---|---|\n"
            "| **G** | `deploy` |\n"
        )
        _stage(tmp_path, _README, readme)
        assert CHU014.check(tmp_path) == []


class TestAgainstRealRepo:
    """The mono-repo's workspace command table must stay parity-clean.

    Guards the regression mechanically. A phantom or hidden command
    landing in the real README fails this test, not just review.
    """

    def test_repo_workspace_table_is_clean(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        # chumicro-checks tests run only in the mono-repo checkout,
        # where the workspace README + CLI tree always exist.
        assert (repo_root / _README).is_file()
        registered = _registered_commands(repo_root / _CLI_DIR)
        assert registered, "expected workspace subcommands to be discoverable"
        assert CHU014.check(repo_root) == []
