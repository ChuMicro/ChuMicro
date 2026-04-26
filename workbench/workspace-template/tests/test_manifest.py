"""Tests for the three-zone manifest classification."""

from __future__ import annotations

import pytest
from chumicro_workspace_template import Zone, classify
from chumicro_workspace_template.manifest import rename_dot_prefix


class TestClassify:
    @pytest.mark.parametrize(
        "path",
        [
            "run.py",
            "AGENTS.md",
            "pyproject.toml",
            "things/_template/config.toml",
            "things/_template/app.py",
        ],
    )
    def test_tool_owned_paths(self, path: str) -> None:
        assert classify(path) is Zone.TOOL_OWNED

    @pytest.mark.parametrize(
        "path",
        [
            "workspace.yml",
            "devices.yml",
            "secrets.yml",
            "libs/my_lib.py",
            "libs/nested/deep/file.py",
            "packages/some_external/__init__.py",
            "things/back-porch/app.py",
            "things/back-porch/helpers/util.py",
        ],
    )
    def test_user_owned_paths(self, path: str) -> None:
        assert classify(path) is Zone.USER_OWNED

    @pytest.mark.parametrize(
        "path",
        [
            ".gitignore",
            "secrets.yml.example",
            "README.md",
        ],
    )
    def test_init_only_paths(self, path: str) -> None:
        assert classify(path) is Zone.INIT_ONLY

    def test_unknown_top_level_falls_through_to_user(self) -> None:
        # User adds a file we don't know about — err on safe side.
        assert classify("Makefile") is Zone.USER_OWNED
        assert classify("custom_dir/script.sh") is Zone.USER_OWNED

    def test_things_real_thing_user_owned_not_template(self) -> None:
        """`things/back-porch/app.py` is user-owned even though
        `things/_template/app.py` is tool-owned — the test guards the
        classifier against a "tool-owned takes prefix precedence"
        regression."""
        assert classify("things/_template/app.py") is Zone.TOOL_OWNED
        assert classify("things/back-porch/app.py") is Zone.USER_OWNED


class TestRenameDotPrefix:
    def test_basename_dot_prefix_renamed(self) -> None:
        assert rename_dot_prefix("dot_gitignore") == ".gitignore"

    def test_intermediate_dirs_passthrough(self) -> None:
        assert rename_dot_prefix("libs/dot_gitkeep") == "libs/.gitkeep"
        assert (
            rename_dot_prefix("packages/dot_gitignore")
            == "packages/.gitignore"
        )

    def test_no_prefix_passthrough(self) -> None:
        assert rename_dot_prefix("things/_template/app.py") == "things/_template/app.py"

    def test_dot_prefix_only_in_basename(self) -> None:
        # If someone has a `dot_x/` directory, the directory name
        # is NOT renamed — only the trailing basename's dot_ prefix.
        assert rename_dot_prefix("dot_x/file.py") == "dot_x/file.py"
