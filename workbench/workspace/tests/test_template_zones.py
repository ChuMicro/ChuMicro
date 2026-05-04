"""Tests for the three-zone manifest classification."""

from __future__ import annotations

import pytest
from chumicro_workspace.template_zones import Zone, classify


class TestClassify:
    @pytest.mark.parametrize(
        "path",
        [
            "run.py",
            "AGENTS.md",
            "CONTRIBUTING.md",
            "pyproject.toml",
            "projects/_template/config.toml",
            "projects/_template/app.py",
            "_workspace_template/secrets.yml",
            "_workspace_template/nested/file.txt",
            ".github/skills/deploy-and-debug/SKILL.md",
            ".github/skills/add-new-project/SKILL.md",
            ".github/skills/register-board/SKILL.md",
            # Slice 5 — `examples/` is reading material; `update`
            # re-flows the canonical content from upstream.
            "examples/README.md",
            "examples/hello_world/app.py",
            "examples/wifi_only/config.toml",
            "examples/two_projects/server/app.py",
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
            "shared/my_lib.py",
            "shared/nested/deep/file.py",
            "packages/some_external/__init__.py",
            "projects/back-porch/app.py",
            "projects/back-porch/helpers/util.py",
        ],
    )
    def test_user_owned_paths(self, path: str) -> None:
        assert classify(path) is Zone.USER_OWNED

    @pytest.mark.parametrize(
        "path",
        [
            ".gitignore",
            "README.md",
        ],
    )
    def test_init_only_paths(self, path: str) -> None:
        assert classify(path) is Zone.INIT_ONLY

    def test_unknown_top_level_falls_through_to_user(self) -> None:
        # User adds a file we don't know about — err on safe side.
        assert classify("Makefile") is Zone.USER_OWNED
        assert classify("custom_dir/script.sh") is Zone.USER_OWNED

    def test_projects_real_project_user_owned_not_template(self) -> None:
        """`projects/back-porch/app.py` is user-owned even though
        `projects/_template/app.py` is tool-owned — guards against a
        "tool-owned prefix takes precedence" regression."""
        assert classify("projects/_template/app.py") is Zone.TOOL_OWNED
        assert classify("projects/back-porch/app.py") is Zone.USER_OWNED

    def test_secrets_yml_user_owned_not_init_only(self) -> None:
        """Decision 0038 §5: `secrets.yml` is the materialized output
        of `_workspace_template/secrets.yml`; `update` must never touch it."""
        assert classify("secrets.yml") is Zone.USER_OWNED
        assert classify("_workspace_template/secrets.yml") is Zone.TOOL_OWNED
