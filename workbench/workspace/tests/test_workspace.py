"""Tests for workspace path resolution + recursive project classification."""

from pathlib import Path

import pytest
from chumicro_workspace.workspace import (
    ProjectClassification,
    WorkspaceLayout,
    WorkspaceNotFoundError,
    runner_invocation,
)


def _seed_root(tmp_path: Path) -> Path:
    """Drop a workspace.yml at *tmp_path* so it counts as a root."""
    (tmp_path / "workspace.yml").write_text('# machinery only\n')
    (tmp_path / "secrets.toml").write_text('')
    return tmp_path


def _make_project(parent: Path, *segments: str) -> Path:
    """Create a leaf project dir with an ``app.py`` entry-point.

    The classifier picks any of ``app.py`` / ``code.py`` / ``main.py``;
    tests use ``app.py`` since that's the workspace-runtime convention.
    """
    target = parent.joinpath(*segments)
    target.mkdir(parents=True)
    (target / "app.py").write_text("def run() -> None:\n    pass\n")
    return target


class TestWorkspaceLayout:
    def test_paths_derive_from_root(self, tmp_path: Path) -> None:
        root = _seed_root(tmp_path)
        layout = WorkspaceLayout(root=root)
        assert layout.workspace_yaml == root / "workspace.yml"
        assert layout.devices_yaml == root / "devices.yml"
        assert layout.projects_dir == root / "projects"
        assert layout.shared_dir == root / "shared"
        assert layout.packages_dir == root / "packages"

    def test_project_dir_returns_named_subdir(self, tmp_path: Path) -> None:
        layout = WorkspaceLayout(root=_seed_root(tmp_path))
        assert layout.project_dir("bedroom_sensor") == (
            tmp_path / "projects" / "bedroom_sensor"
        )

    def test_project_dir_accepts_slash_form(self, tmp_path: Path) -> None:
        layout = WorkspaceLayout(root=_seed_root(tmp_path))
        assert layout.project_dir("upstairs/bedroom_sensor") == (
            tmp_path / "projects" / "upstairs" / "bedroom_sensor"
        )

    def test_project_dir_accepts_dotted_form(self, tmp_path: Path) -> None:
        """Dotted names round-trip through ``Path`` after a ``.`` → ``/`` normalize."""
        layout = WorkspaceLayout(root=_seed_root(tmp_path))
        assert layout.project_dir("upstairs.bedroom_sensor") == (
            tmp_path / "projects" / "upstairs" / "bedroom_sensor"
        )


class TestListProjects:
    def test_empty_when_no_projects_dir(self, tmp_path: Path) -> None:
        layout = WorkspaceLayout(root=_seed_root(tmp_path))
        assert layout.list_projects() == []

    def test_flat_layout_returns_sorted_names(self, tmp_path: Path) -> None:
        layout = WorkspaceLayout(root=_seed_root(tmp_path))
        _make_project(layout.projects_dir, "back_porch")
        _make_project(layout.projects_dir, "front_door")
        _make_project(layout.projects_dir, "attic")
        assert layout.list_projects() == ["attic", "back_porch", "front_door"]

    def test_directory_without_entry_point_is_supporting(
        self, tmp_path: Path,
    ) -> None:
        """No ``app.py`` / ``code.py`` / ``main.py`` → classified supporting."""
        layout = WorkspaceLayout(root=_seed_root(tmp_path))
        empty_dir = layout.projects_dir / "halfway_built"
        empty_dir.mkdir(parents=True)
        (empty_dir / "README.md").write_text("notes only\n")
        assert layout.list_projects() == []

    def test_skips_template_and_hidden(self, tmp_path: Path) -> None:
        layout = WorkspaceLayout(root=_seed_root(tmp_path))
        _make_project(layout.projects_dir, "_template")
        _make_project(layout.projects_dir, ".hidden")
        _make_project(layout.projects_dir, "real_project")
        assert layout.list_projects() == ["real_project"]

    def test_skips_files(self, tmp_path: Path) -> None:
        layout = WorkspaceLayout(root=_seed_root(tmp_path))
        layout.projects_dir.mkdir()
        (layout.projects_dir / "stray.txt").write_text("\n")
        assert layout.list_projects() == []

    def test_two_level_nested_layout(self, tmp_path: Path) -> None:
        layout = WorkspaceLayout(root=_seed_root(tmp_path))
        _make_project(layout.projects_dir, "upstairs", "bedroom_sensor")
        _make_project(layout.projects_dir, "upstairs", "nightstand_lamp")
        _make_project(layout.projects_dir, "thermostat")
        assert layout.list_projects() == [
            "thermostat",
            "upstairs/bedroom_sensor",
            "upstairs/nightstand_lamp",
        ]

    def test_three_level_nested_layout(self, tmp_path: Path) -> None:
        layout = WorkspaceLayout(root=_seed_root(tmp_path))
        _make_project(layout.projects_dir, "garage", "sensors", "door_open")
        _make_project(layout.projects_dir, "garage", "controls", "heater")
        assert layout.list_projects() == [
            "garage/controls/heater",
            "garage/sensors/door_open",
        ]

    def test_namespace_with_supporting_files_still_lists_descendants(
        self, tmp_path: Path,
    ) -> None:
        """A namespace dir may contain README/notes alongside its projects."""
        layout = WorkspaceLayout(root=_seed_root(tmp_path))
        garage = layout.projects_dir / "garage"
        garage.mkdir(parents=True)
        (garage / "README.md").write_text("garage namespace notes\n")
        (garage / "notes").mkdir()
        (garage / "notes" / "wiring.txt").write_text("\n")
        _make_project(garage, "door_open")
        assert layout.list_projects() == ["garage/door_open"]

    def test_namespace_with_only_supporting_subdir_is_hidden(
        self, tmp_path: Path,
    ) -> None:
        """A namespace whose subtree has no projects at all classifies supporting."""
        layout = WorkspaceLayout(root=_seed_root(tmp_path))
        notes = layout.projects_dir / "design_notes"
        (notes / "wiring").mkdir(parents=True)
        (notes / "wiring" / "schematic.txt").write_text("\n")
        # No app.py anywhere — every classified dir is SUPPORTING.
        assert layout.list_projects() == []

    def test_project_subdirs_are_not_recursed_into(self, tmp_path: Path) -> None:
        """Once a directory is a project, its sub-folders aren't more projects."""
        layout = WorkspaceLayout(root=_seed_root(tmp_path))
        project_dir = _make_project(layout.projects_dir, "weather")
        # An app.py inside a sub-folder of the project — internal structure,
        # not another project.
        (project_dir / "submodule").mkdir()
        (project_dir / "submodule" / "app.py").write_text("def run(): pass\n")
        assert layout.list_projects() == ["weather"]


class TestIterProjectsWithClassification:
    def test_includes_namespaces_above_their_projects(self, tmp_path: Path) -> None:
        layout = WorkspaceLayout(root=_seed_root(tmp_path))
        _make_project(layout.projects_dir, "garage", "sensors", "door_open")
        _make_project(layout.projects_dir, "garage", "controls", "heater")
        _make_project(layout.projects_dir, "thermostat")
        result = layout.iter_projects_with_classification()
        assert result == [
            ("garage", ProjectClassification.NAMESPACE),
            ("garage/controls", ProjectClassification.NAMESPACE),
            ("garage/controls/heater", ProjectClassification.PROJECT),
            ("garage/sensors", ProjectClassification.NAMESPACE),
            ("garage/sensors/door_open", ProjectClassification.PROJECT),
            ("thermostat", ProjectClassification.PROJECT),
        ]

    def test_supporting_branches_are_omitted(self, tmp_path: Path) -> None:
        layout = WorkspaceLayout(root=_seed_root(tmp_path))
        _make_project(layout.projects_dir, "real_project")
        # Supporting subtree — README only, no entry-points.
        notes = layout.projects_dir / "design_notes"
        notes.mkdir()
        (notes / "wiring.txt").write_text("\n")
        result = layout.iter_projects_with_classification()
        assert result == [("real_project", ProjectClassification.PROJECT)]

    def test_empty_when_projects_dir_missing(self, tmp_path: Path) -> None:
        layout = WorkspaceLayout(root=_seed_root(tmp_path))
        assert layout.iter_projects_with_classification() == []


class TestFromDir:
    def test_finds_workspace_in_start_dir(self, tmp_path: Path) -> None:
        root = _seed_root(tmp_path)
        layout = WorkspaceLayout.from_dir(root)
        assert layout.root == root.resolve()

    def test_walks_up_to_find_root(self, tmp_path: Path) -> None:
        root = _seed_root(tmp_path)
        nested = root / "projects" / "garage" / "door_open"
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


class TestRunnerInvocation:
    def test_names_the_shim_when_run_py_exists(self, tmp_path: Path) -> None:
        root = _seed_root(tmp_path)
        (root / "run.py").write_text("# dispatcher shim\n")
        assert runner_invocation(root) == "python3 run.py"

    def test_names_the_cli_without_the_shim(self, tmp_path: Path) -> None:
        root = _seed_root(tmp_path)
        assert runner_invocation(root) == "chumicro-workspace"
