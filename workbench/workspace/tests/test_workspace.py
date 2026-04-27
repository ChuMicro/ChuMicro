"""Tests for workspace path resolution + recursive thing classification."""

from pathlib import Path

import pytest
from chumicro_workspace.workspace import (
    ThingClassification,
    WorkspaceLayout,
    WorkspaceNotFoundError,
)


def _seed_root(tmp_path: Path) -> Path:
    """Drop a workspace.yml at *tmp_path* so it counts as a root."""
    (tmp_path / "workspace.yml").write_text("defaults: {}\n")
    return tmp_path


def _make_thing(parent: Path, *segments: str) -> Path:
    """Create a leaf thing dir with an ``app.py`` entry-point.

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
        assert layout.secrets_yaml == root / "secrets.yml"
        assert layout.things_dir == root / "things"
        assert layout.libs_dir == root / "libs"
        assert layout.packages_dir == root / "packages"

    def test_thing_dir_returns_named_subdir(self, tmp_path: Path) -> None:
        layout = WorkspaceLayout(root=_seed_root(tmp_path))
        assert layout.thing_dir("bedroom_sensor") == (
            tmp_path / "things" / "bedroom_sensor"
        )

    def test_thing_dir_accepts_slash_form(self, tmp_path: Path) -> None:
        layout = WorkspaceLayout(root=_seed_root(tmp_path))
        assert layout.thing_dir("upstairs/bedroom_sensor") == (
            tmp_path / "things" / "upstairs" / "bedroom_sensor"
        )

    def test_thing_dir_accepts_dotted_form(self, tmp_path: Path) -> None:
        """Dotted names round-trip through ``Path`` after a ``.`` → ``/`` normalise."""
        layout = WorkspaceLayout(root=_seed_root(tmp_path))
        assert layout.thing_dir("upstairs.bedroom_sensor") == (
            tmp_path / "things" / "upstairs" / "bedroom_sensor"
        )


class TestListThings:
    def test_empty_when_no_things_dir(self, tmp_path: Path) -> None:
        layout = WorkspaceLayout(root=_seed_root(tmp_path))
        assert layout.list_things() == []

    def test_flat_layout_returns_sorted_names(self, tmp_path: Path) -> None:
        layout = WorkspaceLayout(root=_seed_root(tmp_path))
        _make_thing(layout.things_dir, "back_porch")
        _make_thing(layout.things_dir, "front_door")
        _make_thing(layout.things_dir, "attic")
        assert layout.list_things() == ["attic", "back_porch", "front_door"]

    def test_directory_without_entry_point_is_supporting(
        self, tmp_path: Path,
    ) -> None:
        """No ``app.py`` / ``code.py`` / ``main.py`` → classified supporting."""
        layout = WorkspaceLayout(root=_seed_root(tmp_path))
        empty_dir = layout.things_dir / "halfway_built"
        empty_dir.mkdir(parents=True)
        (empty_dir / "README.md").write_text("notes only\n")
        assert layout.list_things() == []

    def test_skips_template_and_hidden(self, tmp_path: Path) -> None:
        layout = WorkspaceLayout(root=_seed_root(tmp_path))
        _make_thing(layout.things_dir, "_template")
        _make_thing(layout.things_dir, ".hidden")
        _make_thing(layout.things_dir, "real_thing")
        assert layout.list_things() == ["real_thing"]

    def test_skips_files(self, tmp_path: Path) -> None:
        layout = WorkspaceLayout(root=_seed_root(tmp_path))
        layout.things_dir.mkdir()
        (layout.things_dir / "stray.txt").write_text("\n")
        assert layout.list_things() == []

    def test_two_level_nested_layout(self, tmp_path: Path) -> None:
        layout = WorkspaceLayout(root=_seed_root(tmp_path))
        _make_thing(layout.things_dir, "upstairs", "bedroom_sensor")
        _make_thing(layout.things_dir, "upstairs", "nightstand_lamp")
        _make_thing(layout.things_dir, "thermostat")
        assert layout.list_things() == [
            "thermostat",
            "upstairs/bedroom_sensor",
            "upstairs/nightstand_lamp",
        ]

    def test_three_level_nested_layout(self, tmp_path: Path) -> None:
        layout = WorkspaceLayout(root=_seed_root(tmp_path))
        _make_thing(layout.things_dir, "garage", "sensors", "door_open")
        _make_thing(layout.things_dir, "garage", "controls", "heater")
        assert layout.list_things() == [
            "garage/controls/heater",
            "garage/sensors/door_open",
        ]

    def test_namespace_with_supporting_files_still_lists_descendants(
        self, tmp_path: Path,
    ) -> None:
        """A namespace dir may contain README/notes alongside its things."""
        layout = WorkspaceLayout(root=_seed_root(tmp_path))
        garage = layout.things_dir / "garage"
        garage.mkdir(parents=True)
        (garage / "README.md").write_text("garage namespace notes\n")
        (garage / "notes").mkdir()
        (garage / "notes" / "wiring.txt").write_text("\n")
        _make_thing(garage, "door_open")
        assert layout.list_things() == ["garage/door_open"]

    def test_namespace_with_only_supporting_subdir_is_hidden(
        self, tmp_path: Path,
    ) -> None:
        """A namespace whose subtree has no things at all classifies supporting."""
        layout = WorkspaceLayout(root=_seed_root(tmp_path))
        notes = layout.things_dir / "design_notes"
        (notes / "wiring").mkdir(parents=True)
        (notes / "wiring" / "schematic.txt").write_text("\n")
        # No app.py anywhere — every classified dir is SUPPORTING.
        assert layout.list_things() == []

    def test_thing_subdirs_are_not_recursed_into(self, tmp_path: Path) -> None:
        """Once a directory is a thing, its sub-folders aren't more things."""
        layout = WorkspaceLayout(root=_seed_root(tmp_path))
        thing_dir = _make_thing(layout.things_dir, "weather")
        # An app.py inside a sub-folder of the thing — internal structure,
        # not another thing.
        (thing_dir / "submodule").mkdir()
        (thing_dir / "submodule" / "app.py").write_text("def run(): pass\n")
        assert layout.list_things() == ["weather"]


class TestIterThingsWithClassification:
    def test_includes_namespaces_above_their_things(self, tmp_path: Path) -> None:
        layout = WorkspaceLayout(root=_seed_root(tmp_path))
        _make_thing(layout.things_dir, "garage", "sensors", "door_open")
        _make_thing(layout.things_dir, "garage", "controls", "heater")
        _make_thing(layout.things_dir, "thermostat")
        result = layout.iter_things_with_classification()
        assert result == [
            ("garage", ThingClassification.NAMESPACE),
            ("garage/controls", ThingClassification.NAMESPACE),
            ("garage/controls/heater", ThingClassification.THING),
            ("garage/sensors", ThingClassification.NAMESPACE),
            ("garage/sensors/door_open", ThingClassification.THING),
            ("thermostat", ThingClassification.THING),
        ]

    def test_supporting_branches_are_omitted(self, tmp_path: Path) -> None:
        layout = WorkspaceLayout(root=_seed_root(tmp_path))
        _make_thing(layout.things_dir, "real_thing")
        # Supporting subtree — README only, no entry-points.
        notes = layout.things_dir / "design_notes"
        notes.mkdir()
        (notes / "wiring.txt").write_text("\n")
        result = layout.iter_things_with_classification()
        assert result == [("real_thing", ThingClassification.THING)]

    def test_empty_when_things_dir_missing(self, tmp_path: Path) -> None:
        layout = WorkspaceLayout(root=_seed_root(tmp_path))
        assert layout.iter_things_with_classification() == []


class TestFromDir:
    def test_finds_workspace_in_start_dir(self, tmp_path: Path) -> None:
        root = _seed_root(tmp_path)
        layout = WorkspaceLayout.from_dir(root)
        assert layout.root == root.resolve()

    def test_walks_up_to_find_root(self, tmp_path: Path) -> None:
        root = _seed_root(tmp_path)
        nested = root / "things" / "garage" / "door_open"
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
