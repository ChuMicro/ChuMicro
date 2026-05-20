"""Tests for template clone / update / materialize orchestration.

Workspaces are created by cloning the template repo directly (there
is no scaffolding CLI command), so the update tests below stand a
workspace up with :func:`_clone_template`, which mirrors the README's
Option A: ``git clone`` then decouple from upstream.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from chumicro_workspace.template_apply import (
    DEFAULT_TEMPLATE_URL,
    ApplyAction,
    materialize_workspace_templates,
    update,
)

if TYPE_CHECKING:
    from collections.abc import Iterable


@pytest.fixture
def fake_template_repo(tmp_path: Path) -> Path:
    """A local git repo populated like the workspace template.

    Layout mirrors the ChuMicro-Workspace-Template repo: tool-owned
    files at the root, a tracked but user-editable `README.md`.
    `workspace.yml` /
    `secrets.toml` / `devices.yml` are gitignored — setup
    materializes them from the workspace templates.

    Returns the absolute path to the repo (suitable as a
    ``template_url=str(path)`` argument).
    """
    repo = tmp_path / "fake-template"
    repo.mkdir()
    (repo / "run.py").write_text("# tool-owned shim\n")
    (repo / "AGENTS.md").write_text("# tool-owned agents doc\n")  # noqa: CHU006  template-payload filename data
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "my-workspace"\n',
    )
    (repo / "README.md").write_text("# clone-seeded readme\n")
    (repo / ".gitignore").write_text(
        ".venv/\n/workspace.yml\n/secrets.toml\n/devices.yml\n",
    )
    (repo / "projects").mkdir()
    (repo / "projects" / "_template").mkdir()
    (repo / "projects" / "_template" / "app.py").write_text(
        "def run(): pass\n",
    )
    (repo / "projects" / "_template" / "project_config.toml").write_text(
        '[project]\nname = "_template"\n',
    )
    _git("init", "-b", "main", cwd=repo)
    _git("add", "-A", cwd=repo)
    _git("-c", "user.email=test@example.com", "-c", "user.name=Test",
         "commit", "-m", "initial", cwd=repo)
    return repo


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(  # noqa: S603 — args fully controlled
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
    )


def _clone_template(template_repo: Path, target: Path) -> None:
    """Stand up a workspace the way a real user does.

    Mirrors the template README's Option A: ``git clone`` the
    template, then decouple from upstream (strip ``.git``, fresh
    ``git init``).  There is deliberately no ``init`` CLI command —
    this helper is what ``update``'s callers look like in the wild.
    """
    _git("clone", "--depth", "1", str(template_repo), str(target),
         cwd=target.parent)
    shutil.rmtree(target / ".git")
    _git("init", "-b", "main", cwd=target)


def _files(report_iter: Iterable[tuple[str, str]]) -> dict[str, str]:
    return dict(report_iter)


class TestDefaultTemplateUrl:
    def test_default_url_is_chumicro_template(self) -> None:
        # Smoke check on the constant — no network call.
        assert DEFAULT_TEMPLATE_URL.endswith("ChuMicro-Workspace-Template")
        assert DEFAULT_TEMPLATE_URL.startswith("https://github.com/")


class TestUpdate:
    def test_refreshes_tool_owned_paths(
        self, fake_template_repo: Path, tmp_path: Path,
    ) -> None:
        target = tmp_path / "my-house"
        _clone_template(fake_template_repo, target)
        # Mutate one tool-owned file in the workspace.
        (target / "run.py").write_text("# user mucked with this\n")
        report = update(target, template_url=str(fake_template_repo))
        actions = _files(report)
        assert actions["run.py"] == ApplyAction.REFRESHED
        assert (target / "run.py").read_text() == "# tool-owned shim\n"

    def test_does_not_clobber_user_secrets_toml(
        self, fake_template_repo: Path, tmp_path: Path,
    ) -> None:
        """User's gitignored secrets.toml at root survives update.

        secrets.toml at root is gitignored; the template repo never
        tracks it, so update never walks it.  It can't end up in the
        report at all — neither REFRESHED nor SKIPPED — and the
        user's content stays put.
        """
        target = tmp_path / "my-house"
        _clone_template(fake_template_repo, target)
        # User materializes / fills in secrets.toml after cloning.
        (target / "workspace.yml").write_text("# machinery only\n")
        (target / "secrets.toml").write_text('[wifi]\npassword = "user-edited"\n')
        report = update(target, template_url=str(fake_template_repo))
        actions = _files(report)
        # Upstream doesn't carry secrets.toml at root (gitignored),
        # so update never visits it.
        assert "secrets.toml" not in actions
        # User content untouched on disk.
        assert (target / "secrets.toml").read_text() == (
            '[wifi]\npassword = "user-edited"\n'
        )

    def test_unchanged_when_tool_owned_files_match_upstream(
        self, fake_template_repo: Path, tmp_path: Path,
    ) -> None:
        target = tmp_path / "my-house"
        _clone_template(fake_template_repo, target)
        report = update(target, template_url=str(fake_template_repo))
        actions = _files(report)
        # Every tool-owned file should report UNCHANGED post-clone since
        # the clone seeded them straight from the same source.
        assert actions["run.py"] == ApplyAction.UNCHANGED
        assert actions["AGENTS.md"] == ApplyAction.UNCHANGED  # noqa: CHU006  template-payload filename data
        assert actions["pyproject.toml"] == ApplyAction.UNCHANGED

    def test_skips_user_edited_readme(
        self, fake_template_repo: Path, tmp_path: Path,
    ) -> None:
        target = tmp_path / "my-house"
        _clone_template(fake_template_repo, target)
        (target / "README.md").write_text("# my custom readme\n")
        report = update(target, template_url=str(fake_template_repo))
        actions = _files(report)
        assert actions["README.md"] == ApplyAction.SKIPPED
        assert (target / "README.md").read_text() == "# my custom readme\n"

    def test_unreachable_template_url_raises(self, tmp_path: Path) -> None:
        target = tmp_path / "my-house"
        target.mkdir()
        with pytest.raises(RuntimeError, match="git clone failed"):
            update(target, template_url="/nonexistent/path/to/repo")

    def test_missing_target_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            update(tmp_path / "does-not-exist")

    def test_target_must_be_directory(self, tmp_path: Path) -> None:
        target = tmp_path / "afile.txt"
        target.write_text("not a workspace\n")
        with pytest.raises(NotADirectoryError):
            update(target)


class TestMaterializeWorkspaceTemplates:
    """Canonical workspace templates land at the workspace root from the
    owning package's payloads."""

    def test_writes_devices_yml_from_payload(
        self, tmp_path: Path,
    ) -> None:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        report = materialize_workspace_templates(workspace)
        actions = _files(report)
        assert actions["devices.yml"] == ApplyAction.MATERIALIZED
        # Content matches the template reader.
        from chumicro_workspace import read_devices_yml_template  # noqa: PLC0415

        assert (workspace / "devices.yml").read_text() == read_devices_yml_template()

    def test_writes_workspace_yml_from_payload(
        self, tmp_path: Path,
    ) -> None:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        report = materialize_workspace_templates(workspace)
        actions = _files(report)
        assert actions["workspace.yml"] == ApplyAction.MATERIALIZED
        from chumicro_workspace import read_workspace_yml_template  # noqa: PLC0415

        assert (
            (workspace / "workspace.yml").read_text()
            == read_workspace_yml_template()
        )

    def test_skips_existing_files(self, tmp_path: Path) -> None:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        (workspace / "devices.yml").write_text("user-edited devices\n")
        (workspace / "workspace.yml").write_text("user-edited overlay\n")

        report = materialize_workspace_templates(workspace)
        actions = _files(report)
        assert actions["devices.yml"] == ApplyAction.UNCHANGED
        assert actions["workspace.yml"] == ApplyAction.UNCHANGED
        # User edits preserved verbatim.
        assert (workspace / "devices.yml").read_text() == "user-edited devices\n"
        assert (workspace / "workspace.yml").read_text() == "user-edited overlay\n"

    def test_idempotent_across_multiple_invocations(
        self, tmp_path: Path,
    ) -> None:
        workspace = tmp_path / "ws"
        workspace.mkdir()

        first = materialize_workspace_templates(workspace)
        actions_first = _files(first)
        assert actions_first["devices.yml"] == ApplyAction.MATERIALIZED
        assert actions_first["workspace.yml"] == ApplyAction.MATERIALIZED

        second = materialize_workspace_templates(workspace)
        actions_second = _files(second)
        assert actions_second["devices.yml"] == ApplyAction.UNCHANGED
        assert actions_second["workspace.yml"] == ApplyAction.UNCHANGED
