"""Tests for template init / update / materialize orchestration."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from chumicro_workspace.template_apply import (
    DEFAULT_TEMPLATE_URL,
    ApplyAction,
    init,
    materialize_templates,
    materialize_workbench_starters,
    update,
)

if TYPE_CHECKING:
    from collections.abc import Iterable


@pytest.fixture
def fake_template_repo(tmp_path: Path) -> Path:
    """A local git repo populated like the canonical workspace template.

    Layout mirrors the post-Decision-0038 ChuMicro-Workspace-Template
    repo: tool-owned files at the root, a tool-owned `_workspace_template/`
    directory, user-owned `workspace.yml`, init-only `README.md`.

    Returns the absolute path to the repo (suitable as a
    ``template_url=str(path)`` argument).
    """
    repo = tmp_path / "fake-template"
    repo.mkdir()
    (repo / "run.py").write_text("# tool-owned shim\n")
    (repo / "AGENTS.md").write_text("# tool-owned agents doc\n")
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "my-workspace"\n',
    )
    (repo / "README.md").write_text("# init-only readme\n")
    # `workspace.yml` at root is gitignored under Decision 0057 — the
    # template never tracks it.  Setup materializes it from
    # `_workspace_template/workspace.yml` (this repo's override) or
    # the workbench-owned starter.
    (repo / ".gitignore").write_text(".venv/\n/workspace.yml\n")
    (repo / "projects").mkdir()
    (repo / "projects" / "_template").mkdir()
    (repo / "projects" / "_template" / "app.py").write_text(
        "def run(): pass\n",
    )
    (repo / "projects" / "_template" / "config.toml").write_text(
        '[project]\nname = "_template"\n',
    )
    (repo / "_workspace_template").mkdir()
    (repo / "_workspace_template" / "workspace.yml").write_text(
        "# machinery only\n",
    )
    (repo / "_workspace_template" / "secrets.toml").write_text("")
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


def _files(report_iter: Iterable[tuple[str, str]]) -> dict[str, str]:
    return dict(report_iter)


class TestInit:
    def test_clones_template_into_target(
        self, fake_template_repo: Path, tmp_path: Path,
    ) -> None:
        target = tmp_path / "my-house"
        report = init(target, template_url=str(fake_template_repo))
        assert (target / "run.py").is_file()
        # workspace.yml at root is gitignored (Decision 0057) — init
        # clones what's tracked; setup materializes the rest.
        assert not (target / "workspace.yml").is_file()
        assert (target / "_workspace_template" / "workspace.yml").is_file()
        # All files reported as WRITTEN.
        actions = _files(report)
        assert actions["run.py"] == ApplyAction.WRITTEN
        assert actions["_workspace_template/workspace.yml"] == ApplyAction.WRITTEN

    def test_strips_dot_git_and_reinitializes(
        self, fake_template_repo: Path, tmp_path: Path,
    ) -> None:
        target = tmp_path / "my-house"
        init(target, template_url=str(fake_template_repo))
        assert (target / ".git").is_dir()
        # Fresh `git init` — no remotes, no history (a single empty branch).
        completed = subprocess.run(  # noqa: S603 — args fully controlled
            ["git", "log", "--oneline"],
            cwd=str(target),
            capture_output=True,
            check=False,
            text=True,
        )
        assert completed.stdout.strip() == ""

    def test_refuses_non_empty_target_without_force(
        self, fake_template_repo: Path, tmp_path: Path,
    ) -> None:
        target = tmp_path / "my-house"
        target.mkdir()
        (target / "existing.txt").write_text("already here\n")
        with pytest.raises(FileExistsError):
            init(target, template_url=str(fake_template_repo))
        # Existing file untouched.
        assert (target / "existing.txt").read_text() == "already here\n"

    def test_force_clears_target_then_clones(
        self, fake_template_repo: Path, tmp_path: Path,
    ) -> None:
        target = tmp_path / "my-house"
        target.mkdir()
        (target / "existing.txt").write_text("will be wiped\n")
        init(target, template_url=str(fake_template_repo), force=True)
        assert not (target / "existing.txt").exists()
        assert (target / "run.py").is_file()

    def test_unreachable_template_url_raises(self, tmp_path: Path) -> None:
        target = tmp_path / "my-house"
        with pytest.raises(RuntimeError, match="git clone failed"):
            init(target, template_url="/nonexistent/path/to/repo")

    def test_default_url_is_canonical_chumicro_template(self) -> None:
        # Smoke check on the constant — no network call.
        assert DEFAULT_TEMPLATE_URL.endswith("ChuMicro-Workspace-Template")
        assert DEFAULT_TEMPLATE_URL.startswith("https://github.com/")


class TestUpdate:
    def test_refreshes_tool_owned_paths(
        self, fake_template_repo: Path, tmp_path: Path,
    ) -> None:
        target = tmp_path / "my-house"
        init(target, template_url=str(fake_template_repo))
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
        init(target, template_url=str(fake_template_repo))
        # User materializes / fills in secrets.toml after init.
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
        init(target, template_url=str(fake_template_repo))
        report = update(target, template_url=str(fake_template_repo))
        actions = _files(report)
        # Every tool-owned file should report UNCHANGED post-init since
        # init wrote them straight from the same source.
        assert actions["run.py"] == ApplyAction.UNCHANGED
        assert actions["AGENTS.md"] == ApplyAction.UNCHANGED
        assert actions["pyproject.toml"] == ApplyAction.UNCHANGED

    def test_skips_init_only_files(
        self, fake_template_repo: Path, tmp_path: Path,
    ) -> None:
        target = tmp_path / "my-house"
        init(target, template_url=str(fake_template_repo))
        (target / "README.md").write_text("# my custom readme\n")
        report = update(target, template_url=str(fake_template_repo))
        actions = _files(report)
        assert actions["README.md"] == ApplyAction.SKIPPED
        assert (target / "README.md").read_text() == "# my custom readme\n"

    def test_refreshes_workspace_template_directory(
        self, fake_template_repo: Path, tmp_path: Path,
    ) -> None:
        """Decision 0038 §5: `_workspace_template/` is tool-owned and flows on
        update so newer template skeletons reach existing workspaces."""
        target = tmp_path / "my-house"
        init(target, template_url=str(fake_template_repo))
        # Mutate the _workspace_template source — update should restore it.
        (target / "_workspace_template" / "workspace.yml").write_text(
            "# stale local edit\n",
        )
        report = update(target, template_url=str(fake_template_repo))
        actions = _files(report)
        assert actions["_workspace_template/workspace.yml"] == ApplyAction.REFRESHED

    def test_missing_target_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            update(tmp_path / "does-not-exist")

    def test_target_must_be_directory(self, tmp_path: Path) -> None:
        target = tmp_path / "afile.txt"
        target.write_text("not a workspace\n")
        with pytest.raises(NotADirectoryError):
            update(target)


class TestMaterializeTemplates:
    def test_materializes_missing_files_from_workspace_template_dir(
        self, tmp_path: Path,
    ) -> None:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        templates = workspace / "_workspace_template"
        templates.mkdir()
        (templates / "workspace.yml").write_text('# machinery only\n')
        (templates / "secrets.toml").write_text('')
        report = materialize_templates(workspace)
        actions = _files(report)
        assert actions["workspace.yml"] == ApplyAction.MATERIALIZED
        assert (workspace / "workspace.yml").read_text() == "# machinery only\n"

    def test_skips_existing_files(self, tmp_path: Path) -> None:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        templates = workspace / "_workspace_template"
        templates.mkdir()
        (templates / "workspace.yml").write_text("from template\n")
        (workspace / "workspace.yml").write_text("user-edited\n")
        report = materialize_templates(workspace)
        actions = _files(report)
        assert actions["workspace.yml"] == ApplyAction.UNCHANGED
        # User edits preserved.
        assert (workspace / "workspace.yml").read_text() == "user-edited\n"

    def test_no_workspace_template_dir_returns_empty_report(
        self, tmp_path: Path,
    ) -> None:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        report = materialize_templates(workspace)
        assert list(report) == []

    def test_handles_nested_template_files(self, tmp_path: Path) -> None:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        templates = workspace / "_workspace_template"
        (templates / "config" / "deep").mkdir(parents=True)
        (templates / "config" / "deep" / "settings.yml").write_text(
            "key: value\n",
        )
        report = materialize_templates(workspace)
        actions = _files(report)
        assert actions["config/deep/settings.yml"] == ApplyAction.MATERIALIZED
        assert (workspace / "config" / "deep" / "settings.yml").is_file()

    def test_idempotent_across_multiple_invocations(
        self, tmp_path: Path,
    ) -> None:
        workspace = tmp_path / "ws"
        templates = workspace / "_workspace_template"
        templates.mkdir(parents=True)
        (templates / "workspace.yml").write_text("placeholder\n")

        first = materialize_templates(workspace)
        actions_first = _files(first)
        assert actions_first["workspace.yml"] == ApplyAction.MATERIALIZED

        # Second invocation — file already exists, should be unchanged.
        second = materialize_templates(workspace)
        actions_second = _files(second)
        assert actions_second["workspace.yml"] == ApplyAction.UNCHANGED


class TestMaterializeWorkbenchStarters:
    """Workbench-owned starters land at the workspace root from the package's payloads."""

    def test_writes_devices_yml_from_workbench_payload(
        self, tmp_path: Path,
    ) -> None:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        report = materialize_workbench_starters(workspace)
        actions = _files(report)
        assert actions["devices.yml"] == ApplyAction.MATERIALIZED
        # Content matches the canonical reader.
        from chumicro_workspace import read_devices_yml_starter  # noqa: PLC0415

        assert (workspace / "devices.yml").read_text() == read_devices_yml_starter()

    def test_writes_workspace_yml_from_workbench_payload(
        self, tmp_path: Path,
    ) -> None:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        report = materialize_workbench_starters(workspace)
        actions = _files(report)
        assert actions["workspace.yml"] == ApplyAction.MATERIALIZED
        from chumicro_workspace import read_workspace_yml_starter  # noqa: PLC0415

        assert (
            (workspace / "workspace.yml").read_text()
            == read_workspace_yml_starter()
        )

    def test_skips_existing_files(self, tmp_path: Path) -> None:
        workspace = tmp_path / "ws"
        workspace.mkdir()
        (workspace / "devices.yml").write_text("user-edited devices\n")
        (workspace / "workspace.yml").write_text("user-edited overlay\n")

        report = materialize_workbench_starters(workspace)
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

        first = materialize_workbench_starters(workspace)
        actions_first = _files(first)
        assert actions_first["devices.yml"] == ApplyAction.MATERIALIZED
        assert actions_first["workspace.yml"] == ApplyAction.MATERIALIZED

        second = materialize_workbench_starters(workspace)
        actions_second = _files(second)
        assert actions_second["devices.yml"] == ApplyAction.UNCHANGED
        assert actions_second["workspace.yml"] == ApplyAction.UNCHANGED
