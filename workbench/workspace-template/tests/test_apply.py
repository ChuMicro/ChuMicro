"""Tests for ``init`` + ``update`` end-to-end."""

from __future__ import annotations

from pathlib import Path

import pytest
from chumicro_workspace_template import (
    ApplyAction,
    default_template_root,
    init,
    update,
)

# ---------------------------------------------------------------------------
# Helpers — synthesize a tiny custom template under tmp_path
# ---------------------------------------------------------------------------


def _seed_custom_template(root: Path) -> Path:
    """A minimal custom template for `--from <path>` tests."""
    template = root / "tpl"
    template.mkdir()
    (template / "workspace.yml").write_text("defaults: {}\n")
    (template / "AGENTS.md").write_text("# Custom workspace\n")
    (template / "run.py").write_text(
        "# custom shim\nfrom chumicro_workspace_runtime.cli import main\n",
    )
    (template / "pyproject.toml").write_text("[project]\nname = 'custom'\n")
    (template / "dot_gitignore").write_text(".venv/\n")
    things_template = template / "things" / "_template"
    things_template.mkdir(parents=True)
    (things_template / "app.py").write_text("def run(): print('hi')\n")
    return template


# ---------------------------------------------------------------------------
# default_template_root sanity
# ---------------------------------------------------------------------------


class TestDefaultTemplateRoot:
    def test_directory_exists(self) -> None:
        root = default_template_root()
        assert root.is_dir(), f"built-in template not found at {root}"

    def test_canonical_files_present(self) -> None:
        root = default_template_root()
        assert (root / "workspace.yml").is_file()
        assert (root / "AGENTS.md").is_file()
        assert (root / "run.py").is_file()
        assert (root / "pyproject.toml").is_file()
        assert (root / "things" / "_template" / "config.toml").is_file()
        assert (root / "things" / "_template" / "app.py").is_file()
        # devices.yml is intentionally NOT shipped — users create it via
        # `chumicro-workspace-runtime add-device` (Phase 4b decision).
        assert not (root / "devices.yml").exists()

    def test_dot_files_use_dot_prefix(self) -> None:
        """Hatchling-quirk-avoidance: every dotfile is a dot_-prefixed
        source so wheels ship them reliably."""
        root = default_template_root()
        assert (root / "dot_gitignore").is_file()
        assert (root / "libs" / "dot_gitkeep").is_file()
        assert (root / "packages" / "dot_gitignore").is_file()


# ---------------------------------------------------------------------------
# init — built-in template
# ---------------------------------------------------------------------------


class TestInitBuiltIn:
    def test_creates_target_directory(self, tmp_path: Path) -> None:
        target = tmp_path / "fresh"
        init(target)
        assert target.is_dir()
        # Top-level files written.
        assert (target / "workspace.yml").is_file()
        assert (target / "run.py").is_file()
        assert (target / "AGENTS.md").is_file()
        assert (target / "pyproject.toml").is_file()
        # Things template carried over.
        assert (target / "things" / "_template" / "config.toml").is_file()
        assert (target / "things" / "_template" / "app.py").is_file()
        # devices.yml is NOT created by init — users add it via
        # `chumicro-workspace-runtime add-device`.
        assert not (target / "devices.yml").exists()

    def test_dot_prefix_renamed_to_real_dotfile(self, tmp_path: Path) -> None:
        target = tmp_path / "fresh"
        init(target)
        # Top-level .gitignore from dot_gitignore.
        assert (target / ".gitignore").is_file()
        assert not (target / "dot_gitignore").exists()
        # libs/.gitkeep from libs/dot_gitkeep.
        assert (target / "libs" / ".gitkeep").is_file()
        assert not (target / "libs" / "dot_gitkeep").exists()
        # packages/.gitignore from packages/dot_gitignore.
        assert (target / "packages" / ".gitignore").is_file()

    def test_report_summary(self, tmp_path: Path) -> None:
        target = tmp_path / "fresh"
        report = init(target)
        # Every file under the built-in template should be written.
        assert report.count(ApplyAction.WRITTEN) > 0
        assert report.count(ApplyAction.SKIPPED) == 0
        # Every reported path is relative + uses forward slashes.
        for path, action in report:
            assert "\\" not in path
            assert action in {
                ApplyAction.WRITTEN,
                ApplyAction.SKIPPED,
                ApplyAction.REFRESHED,
                ApplyAction.UNCHANGED,
            }

    def test_skips_existing_without_force(self, tmp_path: Path) -> None:
        target = tmp_path / "fresh"
        init(target)
        # User edits one of the writable files.
        (target / "workspace.yml").write_text("defaults:\n  custom: true\n")
        # Re-run init without --force; user content should survive.
        report = init(target)
        assert report.count(ApplyAction.SKIPPED) > 0
        assert (
            "custom: true" in (target / "workspace.yml").read_text()
        ), "user edit survived second init without --force"

    def test_force_overwrites_existing(self, tmp_path: Path) -> None:
        target = tmp_path / "fresh"
        init(target)
        (target / "workspace.yml").write_text("defaults:\n  custom: true\n")
        report = init(target, force=True)
        assert report.count(ApplyAction.WRITTEN) > 0
        assert "custom: true" not in (target / "workspace.yml").read_text()


# ---------------------------------------------------------------------------
# init — custom template via --from
# ---------------------------------------------------------------------------


class TestInitCustomSource:
    def test_from_local_path(self, tmp_path: Path) -> None:
        custom = _seed_custom_template(tmp_path)
        target = tmp_path / "fresh"
        init(target, source=custom)
        # File from custom template ended up in target.
        assert "Custom workspace" in (target / "AGENTS.md").read_text()
        # Dotfile rename still applies.
        assert (target / ".gitignore").is_file()

    def test_missing_source_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            init(tmp_path / "fresh", source=tmp_path / "does-not-exist")

    def test_source_must_be_directory(self, tmp_path: Path) -> None:
        not_a_dir = tmp_path / "file"
        not_a_dir.write_text("not a template\n")
        with pytest.raises(NotADirectoryError):
            init(tmp_path / "fresh", source=not_a_dir)


# ---------------------------------------------------------------------------
# update — three-zone discipline
# ---------------------------------------------------------------------------


class TestUpdate:
    def test_refreshes_tool_owned_only(self, tmp_path: Path) -> None:
        target = tmp_path / "ws"
        init(target)
        # User customizes things — preserved across update.
        thing_dir = target / "things" / "back-porch"
        thing_dir.mkdir()
        (thing_dir / "app.py").write_text(
            "def run(): print('back-porch')\n",
        )
        # User-owned file edits.
        (target / "workspace.yml").write_text("defaults:\n  user_pinned: 1\n")
        # User added a devices.yml after init (the post-init
        # `chumicro-workspace-runtime add-device` flow); update must
        # never touch it even though it's not in the template payload.
        (target / "devices.yml").write_text("# user-edited devices file\n")
        # Tool-owned files: simulate a drift by editing them, then
        # `update` must re-refresh.
        (target / "run.py").write_text("# stale shim\n")

        report = update(target)

        # User-owned + init-only files in the template: skipped.
        skipped = {path for path, action in report if action == ApplyAction.SKIPPED}
        assert "workspace.yml" in skipped
        assert ".gitignore" in skipped
        assert "README.md" in skipped
        # User-edited file content survived.
        assert "user_pinned: 1" in (target / "workspace.yml").read_text()
        # devices.yml isn't in the template, so update doesn't enumerate
        # it; the file on disk is untouched because update only walks
        # template-shaped paths.
        assert "user-edited" in (target / "devices.yml").read_text()
        # Tool-owned: refreshed.
        refreshed = {
            path for path, action in report if action == ApplyAction.REFRESHED
        }
        assert "run.py" in refreshed
        # Refreshed run.py matches the template's bytes again.
        canonical = (default_template_root() / "run.py").read_bytes()
        assert (target / "run.py").read_bytes() == canonical
        # User-created thing untouched.
        assert (
            "back-porch"
            in (thing_dir / "app.py").read_text()
        )

    def test_unchanged_when_already_in_sync(self, tmp_path: Path) -> None:
        target = tmp_path / "ws"
        init(target)
        report = update(target)
        # Tool-owned files are already at canonical bytes — every
        # tool-owned file should report UNCHANGED, not REFRESHED.
        for path, action in report:
            if action in {ApplyAction.UNCHANGED, ApplyAction.SKIPPED}:
                continue
            pytest.fail(
                f"unexpected action {action!r} for {path!r} on a fresh-init workspace",
            )

    def test_missing_target_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            update(tmp_path / "no-such-dir")

    def test_target_must_be_directory(self, tmp_path: Path) -> None:
        not_a_dir = tmp_path / "file"
        not_a_dir.write_text("not a workspace\n")
        with pytest.raises(NotADirectoryError):
            update(not_a_dir)

    def test_things_template_refreshed_on_update(self, tmp_path: Path) -> None:
        """`things/_template/` is tool-owned — updates flow in even
        when the user edited it."""
        target = tmp_path / "ws"
        init(target)
        # User mucks with the canonical _template (mistake — it's
        # tool-owned).
        template_app = target / "things" / "_template" / "app.py"
        template_app.write_text("# user mistakenly edited this\n")
        report = update(target)
        refreshed = {
            path for path, action in report if action == ApplyAction.REFRESHED
        }
        assert "things/_template/app.py" in refreshed
        assert (
            "user mistakenly" not in template_app.read_text()
        ), "tool-owned _template should be refreshed on update"


# ---------------------------------------------------------------------------
# init -> update full cycle
# ---------------------------------------------------------------------------


class TestInitThenUpdate:
    def test_full_cycle_idempotent(self, tmp_path: Path) -> None:
        target = tmp_path / "ws"
        init(target)
        # Snapshot the tree.
        before = {
            entry.relative_to(target).as_posix(): entry.read_bytes()
            for entry in target.rglob("*")
            if entry.is_file()
        }
        update(target)
        after = {
            entry.relative_to(target).as_posix(): entry.read_bytes()
            for entry in target.rglob("*")
            if entry.is_file()
        }
        assert before == after, "init -> update on a fresh workspace should be a no-op"
