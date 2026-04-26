"""Tests for workspace path resolution."""

from pathlib import Path

import pytest
from chumicro_workspace.workspace import (
    WorkspaceLayout,
    WorkspaceNotFoundError,
)


def _seed_root(tmp_path: Path) -> Path:
    """Drop a workspace.yml at *tmp_path* so it counts as a root."""
    (tmp_path / "workspace.yml").write_text("defaults: {}\n")
    return tmp_path


class TestWorkspaceLayout:
    def test_paths_derive_from_root(self, tmp_path: Path) -> None:
        root = _seed_root(tmp_path)
        layout = WorkspaceLayout(root=root)
        assert layout.workspace_yaml == root / "workspace.yml"
        assert layout.devices_yaml == root / "devices.yml"
        assert layout.secrets_yaml == root / "secrets.yml"
        assert layout.things_dir == root / "things"
        assert layout.libs_dir == root / "libs"
        assert layout.packages_dir == root / "packages"

    def test_thing_dir_returns_named_subdir(self, tmp_path: Path) -> None:
        layout = WorkspaceLayout(root=_seed_root(tmp_path))
        assert layout.thing_dir("back-porch") == tmp_path / "things" / "back-porch"

    def test_list_things_empty_when_no_things_dir(self, tmp_path: Path) -> None:
        layout = WorkspaceLayout(root=_seed_root(tmp_path))
        assert layout.list_things() == []

    def test_list_things_returns_sorted_names(self, tmp_path: Path) -> None:
        layout = WorkspaceLayout(root=_seed_root(tmp_path))
        (layout.things_dir / "back-porch").mkdir(parents=True)
        (layout.things_dir / "front-door").mkdir()
        (layout.things_dir / "attic").mkdir()
        assert layout.list_things() == ["attic", "back-porch", "front-door"]

    def test_list_things_skips_template_and_hidden(self, tmp_path: Path) -> None:
        layout = WorkspaceLayout(root=_seed_root(tmp_path))
        (layout.things_dir / "_template").mkdir(parents=True)
        (layout.things_dir / ".hidden").mkdir()
        (layout.things_dir / "real-thing").mkdir()
        assert layout.list_things() == ["real-thing"]

    def test_list_things_skips_files(self, tmp_path: Path) -> None:
        layout = WorkspaceLayout(root=_seed_root(tmp_path))
        layout.things_dir.mkdir()
        (layout.things_dir / "stray.txt").write_text("\n")
        assert layout.list_things() == []


class TestFromDir:
    def test_finds_workspace_in_start_dir(self, tmp_path: Path) -> None:
        root = _seed_root(tmp_path)
        layout = WorkspaceLayout.from_dir(root)
        assert layout.root == root.resolve()

    def test_walks_up_to_find_root(self, tmp_path: Path) -> None:
        root = _seed_root(tmp_path)
        nested = root / "things" / "back-porch"
        nested.mkdir(parents=True)
        layout = WorkspaceLayout.from_dir(nested)
        assert layout.root == root.resolve()

    def test_raises_when_no_workspace(self, tmp_path: Path) -> None:
        with pytest.raises(WorkspaceNotFoundError):
            WorkspaceLayout.from_dir(tmp_path)

    def test_default_start_is_cwd(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        root = _seed_root(tmp_path)
        monkeypatch.chdir(root)
        layout = WorkspaceLayout.from_dir()
        assert layout.root == root.resolve()
