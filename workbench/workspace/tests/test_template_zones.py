"""Tests for the two-zone manifest classification."""

from __future__ import annotations

import pytest
from chumicro_workspace.template_zones import Zone, classify


class TestClassify:
    @pytest.mark.parametrize(
        "path",
        [
            "run.py",
            "AGENTS.md",  # noqa: CHU006  template-payload filename data
            "CONTRIBUTING.md",  # noqa: CHU006  template-payload filename data
            "pyproject.toml",
            "requirements.txt",
            # Pins for the requirements.txt floors; `update` must
            # re-flow them so a template release can roll every
            # workspace's pinned tooling forward or back.
            "constraints.txt",
            "projects/_template/project_config.toml",
            "projects/_template/app.py",
            ".github/skills/deploy-and-debug/SKILL.md",
            ".github/skills/add-new-project/SKILL.md",
            ".github/skills/register-board/SKILL.md",
            # CI workflows declare themselves tool-owned in their
            # headers; `update` must re-flow CI fixes into existing
            # workspaces.
            ".github/workflows/test.yml",
            # `examples/` is reading material; `update` re-flows
            # the content from upstream.
            "examples/README.md",
            "examples/hello_world/app.py",
            "examples/wifi_only/project_config.toml",
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
    def test_tracked_but_user_editable_files_are_user_owned(
        self, path: str,
    ) -> None:
        """`.gitignore` / `README.md` are tracked in the template (so
        the clone seeds them) but the user is meant to edit them — they
        must classify as user-owned so ``update`` never re-flows them.
        Guards against a tool-owned prefix accidentally swallowing them.
        """
        assert classify(path) is Zone.USER_OWNED

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

    def test_workspace_yml_user_owned(self) -> None:
        """Gitignored ``workspace.yml`` is the materialized output of
        the template; ``update`` must never touch it.  Same for
        ``secrets.toml``."""
        assert classify("workspace.yml") is Zone.USER_OWNED
        assert classify("secrets.toml") is Zone.USER_OWNED
