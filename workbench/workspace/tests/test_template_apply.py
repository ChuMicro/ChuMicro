"""Tests for template clone / update / materialize orchestration.

Workspaces are created by cloning the template repo directly (there
is no scaffolding CLI command), so the update tests below stand a
workspace up with :func:`_clone_template`, which mirrors the README's
Option A: ``git clone`` then decouple from upstream.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from chumicro_workspace.template_apply import (
    DEFAULT_TEMPLATE_URL,
    TEMPLATE_STATE_FILENAME,
    ApplyAction,
    materialize_workspace_templates,
    update,
)

if TYPE_CHECKING:
    from collections.abc import Iterable


@pytest.fixture
def fake_template_repo(tmp_path: Path) -> Path:
    """A local git repo populated like the workspace template.

    Layout mirrors the ChuMicro-Workbench-Template repo: tool-owned
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
    _commit_all(repo, "initial")
    return repo


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(  # noqa: S603 — args fully controlled
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
    )


def _commit_all(repo: Path, message: str) -> None:
    """Stage every change in *repo* (adds and deletions) and commit."""
    _git("add", "-A", cwd=repo)
    _git("-c", "user.email=test@example.com", "-c", "user.name=Test",
         "commit", "-m", message, cwd=repo)


def _read_state(target: Path) -> dict[str, str]:
    """Return the ``applied`` fingerprint mapping from the state file."""
    raw = json.loads(
        (target / TEMPLATE_STATE_FILENAME).read_text(encoding="utf-8"),
    )
    return raw["applied"]


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


def _template_repo_with_pyproject(parent: Path, pyproject_text: str) -> Path:
    """Build a one-file template git repo carrying *pyproject_text*.

    The repo tracks only ``pyproject.toml`` (tool-owned), which is all
    the dependency-preservation carve-out needs to exercise.  Returns
    the repo path, suitable as a ``template_url=str(path)`` argument.
    """
    repo = parent / "fake-template"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(pyproject_text)
    _git("init", "-b", "main", cwd=repo)
    _commit_all(repo, "initial")
    return repo


def _files(report_iter: Iterable[tuple[str, str]]) -> dict[str, str]:
    return dict(report_iter)


class TestDefaultTemplateUrl:
    def test_default_url_is_chumicro_template(self) -> None:
        # Smoke check on the constant — no network call.
        assert DEFAULT_TEMPLATE_URL.endswith("ChuMicro-Workbench-Template")
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


class TestUpdatePreservesPyprojectDependencies:
    """`update` re-flows ``pyproject.toml`` but keeps user-added
    ``[project].dependencies`` entries instead of clobbering them."""

    def test_reapplies_user_added_dependency_onto_upstream(
        self, tmp_path: Path,
    ) -> None:
        # Upstream evolved (ships tomlkit); the workspace file adds the
        # user's own requests dep.  After update both must be present.
        upstream = (
            '[project]\n'
            'name = "my-workspace"\n'
            'dependencies = [\n'
            '  # add your own host-side dependencies below this line\n'
            '  "tomlkit>=0.13",\n'
            ']\n'
        )
        incumbent = (
            '[project]\n'
            'name = "my-workspace"\n'
            'dependencies = [\n'
            '  # add your own host-side dependencies below this line\n'
            '  "requests>=2.31",\n'
            ']\n'
        )
        repo = _template_repo_with_pyproject(tmp_path, upstream)
        target = tmp_path / "my-house"
        _clone_template(repo, target)
        (target / "pyproject.toml").write_text(incumbent)

        report = update(target, template_url=str(repo))

        actions = _files(report)
        assert actions["pyproject.toml"] == ApplyAction.REFRESHED
        assert "pyproject.toml" in report.dependency_preserved_paths
        dependencies = tomllib.loads(
            (target / "pyproject.toml").read_text(),
        )["project"]["dependencies"]
        # User addition carried across; upstream's own dep flowed in.
        assert "requests>=2.31" in dependencies
        assert "tomlkit>=0.13" in dependencies

    def test_byte_identical_pyproject_stays_a_noop(
        self, tmp_path: Path,
    ) -> None:
        # Fresh clone leaves pyproject.toml byte-identical to upstream,
        # so the carve-out must not perturb it into a REFRESHED write.
        upstream = (
            '[project]\n'
            'name = "my-workspace"\n'
            'dependencies = [\n'
            '  # add your own host-side dependencies below this line\n'
            ']\n'
        )
        repo = _template_repo_with_pyproject(tmp_path, upstream)
        target = tmp_path / "my-house"
        _clone_template(repo, target)

        report = update(target, template_url=str(repo))

        actions = _files(report)
        assert actions["pyproject.toml"] == ApplyAction.UNCHANGED
        assert report.dependency_preserved_paths == []

    def test_unparseable_incumbent_falls_back_to_overwrite(
        self, tmp_path: Path,
    ) -> None:
        # A workspace file that isn't valid TOML can't be diffed, so the
        # plain overwrite stands and nothing is reported as preserved.
        upstream = (
            '[project]\n'
            'name = "my-workspace"\n'
            'dependencies = [\n'
            '  "tomlkit>=0.13",\n'
            ']\n'
        )
        repo = _template_repo_with_pyproject(tmp_path, upstream)
        target = tmp_path / "my-house"
        _clone_template(repo, target)
        (target / "pyproject.toml").write_text("this is not = valid = toml [[[\n")

        report = update(target, template_url=str(repo))

        actions = _files(report)
        assert actions["pyproject.toml"] == ApplyAction.REFRESHED
        assert (target / "pyproject.toml").read_text() == upstream
        assert "pyproject.toml" not in report.dependency_preserved_paths

    def test_incoming_without_project_table_falls_back_to_overwrite(
        self, tmp_path: Path,
    ) -> None:
        # Upstream carries no [project] table, so there is no array to
        # append into: overwrite plainly rather than crash.
        upstream = '[build-system]\nrequires = ["setuptools"]\n'
        incumbent = (
            '[project]\n'
            'name = "my-workspace"\n'
            'dependencies = [\n'
            '  "requests>=2.31",\n'
            ']\n'
        )
        repo = _template_repo_with_pyproject(tmp_path, upstream)
        target = tmp_path / "my-house"
        _clone_template(repo, target)
        (target / "pyproject.toml").write_text(incumbent)

        report = update(target, template_url=str(repo))

        actions = _files(report)
        assert actions["pyproject.toml"] == ApplyAction.REFRESHED
        assert (target / "pyproject.toml").read_text() == upstream
        assert "pyproject.toml" not in report.dependency_preserved_paths

    def test_preserved_output_is_valid_toml_and_keeps_upstream_comment(
        self, tmp_path: Path,
    ) -> None:
        # The style-preserving re-flow keeps upstream's marker comment
        # and the user dep, and the result round-trips through tomllib.
        upstream = (
            '[project]\n'
            'name = "my-workspace"\n'
            'dependencies = [\n'
            '  # keep upstream deps; add your own below this marker\n'
            '  "tomlkit>=0.13",\n'
            ']\n'
        )
        incumbent = (
            '[project]\n'
            'name = "my-workspace"\n'
            'dependencies = [\n'
            '  # keep upstream deps; add your own below this marker\n'
            '  "requests>=2.31",\n'
            ']\n'
        )
        repo = _template_repo_with_pyproject(tmp_path, upstream)
        target = tmp_path / "my-house"
        _clone_template(repo, target)
        (target / "pyproject.toml").write_text(incumbent)

        update(target, template_url=str(repo))

        written = (target / "pyproject.toml").read_text()
        assert "keep upstream deps; add your own below this marker" in written
        assert "requests>=2.31" in written
        dependencies = tomllib.loads(written)["project"]["dependencies"]
        assert dependencies == ["tomlkit>=0.13", "requests>=2.31"]


class TestUpdateDirtyGuard:
    """`update` refuses to overwrite a tool-owned file whose on-disk
    content differs from the fingerprint recorded when it was last
    applied, unless ``force=True``."""

    def test_update_records_fingerprint_state(
        self, fake_template_repo: Path, tmp_path: Path,
    ) -> None:
        """An update writes the state file and its ``applied`` mapping
        covers every tool-owned file, including files that reported
        UNCHANGED, and no user-owned file."""
        target = tmp_path / "my-house"
        _clone_template(fake_template_repo, target)
        update(target, template_url=str(fake_template_repo))
        state = _read_state(target)
        assert {"run.py", "AGENTS.md", "pyproject.toml"} <= set(state)  # noqa: CHU006  template-payload filename data
        assert "README.md" not in state

    def test_refuses_overwrite_of_locally_edited_file(
        self, fake_template_repo: Path, tmp_path: Path,
    ) -> None:
        """A run.py edited after the baseline-recording update reports
        REFUSED and keeps its local content when upstream evolves."""
        target = tmp_path / "my-house"
        _clone_template(fake_template_repo, target)
        update(target, template_url=str(fake_template_repo))
        (target / "run.py").write_text("# my local tweak\n")
        (fake_template_repo / "run.py").write_text("# upstream v2\n")
        _commit_all(fake_template_repo, "evolve run.py")

        report = update(target, template_url=str(fake_template_repo))

        actions = _files(report)
        assert actions["run.py"] == ApplyAction.REFUSED
        assert (target / "run.py").read_text() == "# my local tweak\n"

    def test_refusal_persists_across_runs(
        self, fake_template_repo: Path, tmp_path: Path,
    ) -> None:
        """A refused file keeps its recorded baseline, and the next
        update refuses it again rather than treating the untouched
        local content as the new last-applied version."""
        target = tmp_path / "my-house"
        _clone_template(fake_template_repo, target)
        update(target, template_url=str(fake_template_repo))
        (target / "run.py").write_text("# my local tweak\n")
        (fake_template_repo / "run.py").write_text("# upstream v2\n")
        _commit_all(fake_template_repo, "evolve run.py")
        update(target, template_url=str(fake_template_repo))

        report = update(target, template_url=str(fake_template_repo))

        actions = _files(report)
        assert actions["run.py"] == ApplyAction.REFUSED
        assert (target / "run.py").read_text() == "# my local tweak\n"

    def test_force_overwrites_locally_edited_file(
        self, fake_template_repo: Path, tmp_path: Path,
    ) -> None:
        target = tmp_path / "my-house"
        _clone_template(fake_template_repo, target)
        update(target, template_url=str(fake_template_repo))
        (target / "run.py").write_text("# my local tweak\n")
        (fake_template_repo / "run.py").write_text("# upstream v2\n")
        _commit_all(fake_template_repo, "evolve run.py")

        report = update(
            target, template_url=str(fake_template_repo), force=True,
        )

        actions = _files(report)
        assert actions["run.py"] == ApplyAction.REFRESHED
        assert (target / "run.py").read_text() == "# upstream v2\n"

    def test_refused_file_does_not_block_other_refreshes(
        self, fake_template_repo: Path, tmp_path: Path,
    ) -> None:
        """One dirty file refuses while a clean sibling still takes the
        upstream refresh, so a single local edit never wedges the
        whole update."""
        target = tmp_path / "my-house"
        _clone_template(fake_template_repo, target)
        update(target, template_url=str(fake_template_repo))
        (target / "run.py").write_text("# my local tweak\n")
        (fake_template_repo / "run.py").write_text("# upstream v2\n")
        (fake_template_repo / "AGENTS.md").write_text("# agents v2\n")  # noqa: CHU006  template-payload filename data
        _commit_all(fake_template_repo, "evolve run.py and agents doc")

        report = update(target, template_url=str(fake_template_repo))

        actions = _files(report)
        assert actions["run.py"] == ApplyAction.REFUSED
        assert actions["AGENTS.md"] == ApplyAction.REFRESHED  # noqa: CHU006  template-payload filename data
        assert (target / "AGENTS.md").read_text() == "# agents v2\n"  # noqa: CHU006  template-payload filename data

    def test_first_update_without_state_is_unguarded(
        self, fake_template_repo: Path, tmp_path: Path,
    ) -> None:
        """With no recorded state (a workspace that never ran a
        state-recording update) a locally edited tool-owned file is
        still overwritten: the guard needs a baseline, and the first
        update is what records one."""
        target = tmp_path / "my-house"
        _clone_template(fake_template_repo, target)
        (target / "run.py").write_text("# my local tweak\n")

        report = update(target, template_url=str(fake_template_repo))

        actions = _files(report)
        assert actions["run.py"] == ApplyAction.REFRESHED
        assert (target / "run.py").read_text() == "# tool-owned shim\n"


class TestUpdateReconcilesDeletions:
    """`update` deletes tool-owned files it applied earlier that
    upstream no longer ships, under the same local-edit guard as
    overwrites."""

    def test_removes_file_dropped_upstream(
        self, fake_template_repo: Path, tmp_path: Path,
    ) -> None:
        target = tmp_path / "my-house"
        _clone_template(fake_template_repo, target)
        update(target, template_url=str(fake_template_repo))
        removed_relative = "projects/_template/project_config.toml"
        (fake_template_repo / removed_relative).unlink()
        _commit_all(fake_template_repo, "drop template project config")

        report = update(target, template_url=str(fake_template_repo))

        actions = _files(report)
        assert actions[removed_relative] == ApplyAction.REMOVED
        assert not (target / removed_relative).exists()
        assert removed_relative not in _read_state(target)

    def test_removal_prunes_empty_directories(
        self, fake_template_repo: Path, tmp_path: Path,
    ) -> None:
        """Deleting the last file of a nested tool-owned tree removes
        the emptied parent directories too, and stops at the first
        directory that still has content."""
        skill_relative = ".github/skills/example/SKILL.md"
        skill_path = fake_template_repo / skill_relative
        skill_path.parent.mkdir(parents=True)
        skill_path.write_text("# a shipped skill\n")
        _commit_all(fake_template_repo, "ship a skill")
        target = tmp_path / "my-house"
        _clone_template(fake_template_repo, target)
        update(target, template_url=str(fake_template_repo))
        assert (target / skill_relative).is_file()
        shutil.rmtree(fake_template_repo / ".github")
        _commit_all(fake_template_repo, "retire the skill")

        report = update(target, template_url=str(fake_template_repo))

        actions = _files(report)
        assert actions[skill_relative] == ApplyAction.REMOVED
        assert not (target / ".github").exists()
        assert (target / "run.py").is_file()

    def test_refuses_deletion_of_locally_modified_file_until_forced(
        self, fake_template_repo: Path, tmp_path: Path,
    ) -> None:
        """A locally edited file slated for upstream deletion reports
        REFUSED and stays on disk, and a follow-up ``force=True`` run
        deletes it."""
        target = tmp_path / "my-house"
        _clone_template(fake_template_repo, target)
        update(target, template_url=str(fake_template_repo))
        (target / "AGENTS.md").write_text("# my local tweak\n")  # noqa: CHU006  template-payload filename data
        (fake_template_repo / "AGENTS.md").unlink()  # noqa: CHU006  template-payload filename data
        _commit_all(fake_template_repo, "drop agents doc")

        refused_report = update(target, template_url=str(fake_template_repo))
        refused_actions = _files(refused_report)
        assert refused_actions["AGENTS.md"] == ApplyAction.REFUSED  # noqa: CHU006  template-payload filename data
        assert (target / "AGENTS.md").read_text() == "# my local tweak\n"  # noqa: CHU006  template-payload filename data

        forced_report = update(
            target, template_url=str(fake_template_repo), force=True,
        )
        forced_actions = _files(forced_report)
        assert forced_actions["AGENTS.md"] == ApplyAction.REMOVED  # noqa: CHU006  template-payload filename data
        assert not (target / "AGENTS.md").exists()  # noqa: CHU006  template-payload filename data

    def test_leaves_user_created_files_in_tool_owned_directories(
        self, fake_template_repo: Path, tmp_path: Path,
    ) -> None:
        """A user-created file inside a tool-owned directory was never
        applied by the tool, so deletion reconciliation neither
        deletes nor reports it."""
        target = tmp_path / "my-house"
        _clone_template(fake_template_repo, target)
        update(target, template_url=str(fake_template_repo))
        user_file = target / "projects" / "_template" / "my_note.txt"
        user_file.write_text("# mine, not the template's\n")

        report = update(target, template_url=str(fake_template_repo))

        actions = _files(report)
        assert "projects/_template/my_note.txt" not in actions
        assert user_file.read_text() == "# mine, not the template's\n"

    def test_state_entry_dropped_when_file_already_gone_locally(
        self, fake_template_repo: Path, tmp_path: Path,
    ) -> None:
        """A recorded file that upstream dropped and the user already
        deleted locally produces no report entry, and its fingerprint
        leaves the state record."""
        target = tmp_path / "my-house"
        _clone_template(fake_template_repo, target)
        update(target, template_url=str(fake_template_repo))
        (target / "AGENTS.md").unlink()  # noqa: CHU006  template-payload filename data
        (fake_template_repo / "AGENTS.md").unlink()  # noqa: CHU006  template-payload filename data
        _commit_all(fake_template_repo, "drop agents doc")

        report = update(target, template_url=str(fake_template_repo))

        actions = _files(report)
        assert "AGENTS.md" not in actions  # noqa: CHU006  template-payload filename data
        assert "AGENTS.md" not in _read_state(target)  # noqa: CHU006  template-payload filename data


class TestUpdatePyprojectGuard:
    """The dirty guard treats ``[project].dependencies`` as user
    territory (matching the preservation carve-out) and every other
    ``pyproject.toml`` knob as tool-owned."""

    _UPSTREAM_V1 = (
        '[project]\n'
        'name = "my-workspace"\n'
        'requires-python = ">=3.11"\n'
        'dependencies = [\n'
        ']\n'
    )
    _UPSTREAM_V2 = (
        '[project]\n'
        'name = "my-workspace"\n'
        'requires-python = ">=3.11"\n'
        'dependencies = [\n'
        '  "tomlkit>=0.13",\n'
        ']\n'
    )

    def _workspace_with_baseline(self, tmp_path: Path) -> tuple[Path, Path]:
        """Stand up a repo + workspace pair with recorded state.

        Returns ``(repo, target)`` after one update has recorded the
        v1 pyproject fingerprint.
        """
        repo = _template_repo_with_pyproject(tmp_path, self._UPSTREAM_V1)
        target = tmp_path / "my-house"
        _clone_template(repo, target)
        update(target, template_url=str(repo))
        return repo, target

    def test_dependency_only_edit_is_not_refused(
        self, tmp_path: Path,
    ) -> None:
        """A user whose only edit is an added dependency sails through
        the guard, and the carve-out carries the addition onto the
        evolved upstream file."""
        repo, target = self._workspace_with_baseline(tmp_path)
        (target / "pyproject.toml").write_text(
            '[project]\n'
            'name = "my-workspace"\n'
            'requires-python = ">=3.11"\n'
            'dependencies = [\n'
            '  "requests>=2.31",\n'
            ']\n',
        )
        (repo / "pyproject.toml").write_text(self._UPSTREAM_V2)
        _commit_all(repo, "upstream ships tomlkit")

        report = update(target, template_url=str(repo))

        actions = _files(report)
        assert actions["pyproject.toml"] == ApplyAction.REFRESHED
        dependencies = tomllib.loads(
            (target / "pyproject.toml").read_text(),
        )["project"]["dependencies"]
        assert "requests>=2.31" in dependencies
        assert "tomlkit>=0.13" in dependencies

    def test_non_dependency_edit_is_refused(self, tmp_path: Path) -> None:
        repo, target = self._workspace_with_baseline(tmp_path)
        edited = (
            '[project]\n'
            'name = "my-workspace"\n'
            'requires-python = ">=3.12"\n'
            'dependencies = [\n'
            ']\n'
        )
        (target / "pyproject.toml").write_text(edited)
        (repo / "pyproject.toml").write_text(self._UPSTREAM_V2)
        _commit_all(repo, "upstream ships tomlkit")

        report = update(target, template_url=str(repo))

        actions = _files(report)
        assert actions["pyproject.toml"] == ApplyAction.REFUSED
        assert (target / "pyproject.toml").read_text() == edited

    def test_force_overwrites_knob_edit_but_keeps_added_dependency(
        self, tmp_path: Path,
    ) -> None:
        """``force=True`` takes the upstream side of a knob edit while
        the carve-out still carries the user's added dependency."""
        repo, target = self._workspace_with_baseline(tmp_path)
        (target / "pyproject.toml").write_text(
            '[project]\n'
            'name = "my-workspace"\n'
            'requires-python = ">=3.12"\n'
            'dependencies = [\n'
            '  "requests>=2.31",\n'
            ']\n',
        )
        (repo / "pyproject.toml").write_text(self._UPSTREAM_V2)
        _commit_all(repo, "upstream ships tomlkit")

        report = update(target, template_url=str(repo), force=True)

        actions = _files(report)
        assert actions["pyproject.toml"] == ApplyAction.REFRESHED
        assert "pyproject.toml" in report.dependency_preserved_paths
        document = tomllib.loads((target / "pyproject.toml").read_text())
        assert document["project"]["requires-python"] == ">=3.11"
        assert "requests>=2.31" in document["project"]["dependencies"]

    def test_mangled_pyproject_is_refused_after_baseline(
        self, tmp_path: Path,
    ) -> None:
        """An on-disk pyproject that no longer parses cannot match its
        recorded structural fingerprint, so the update refuses loudly
        instead of silently overwriting the mangled file."""
        repo, target = self._workspace_with_baseline(tmp_path)
        (target / "pyproject.toml").write_text(
            "this is not = valid = toml [[[\n",
        )
        (repo / "pyproject.toml").write_text(self._UPSTREAM_V2)
        _commit_all(repo, "upstream ships tomlkit")

        report = update(target, template_url=str(repo))

        actions = _files(report)
        assert actions["pyproject.toml"] == ApplyAction.REFUSED
        assert (target / "pyproject.toml").read_text() == (
            "this is not = valid = toml [[[\n"
        )
