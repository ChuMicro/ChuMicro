"""Tests for the full-tree libraries-channel producer."""

from __future__ import annotations

import json
from pathlib import Path

from libraries_channel import (
    channel_repo,
    main,
    stage_libraries_channel,
)


def _make_library(
    libraries_dir: Path,
    name: str,
    *,
    version: str,
    description: str,
    examples: tuple[str, ...] = (),
    with_optional: bool = True,
) -> None:
    library_dir = libraries_dir / name
    (library_dir / "src" / f"chumicro_{name}").mkdir(parents=True)
    (library_dir / "src" / f"chumicro_{name}" / "__init__.py").write_text("x\n")
    (library_dir / "pyproject.toml").write_text(
        f'[project]\nname = "chumicro-{name}"\n'
        f'description = "{description}"\n',
    )
    (library_dir / "VERSION").write_text(f"{version}\n")
    (library_dir / "README.md").write_text(f"# chumicro_{name}\n")
    if with_optional:
        (library_dir / "tests").mkdir()
        (library_dir / "tests" / "test_x.py").write_text("pass\n")
        (library_dir / "docs").mkdir()
        (library_dir / "docs" / "guide.md").write_text("# guide\n")
    for example in examples:
        example_path = library_dir / "examples" / example
        example_path.parent.mkdir(parents=True, exist_ok=True)
        example_path.write_text("print('hi')\n")


class TestChannelRepo:
    def test_stable(self):
        assert channel_repo(experimental=False) == "ChuMicro-Libraries"

    def test_experimental(self):
        assert (
            channel_repo(experimental=True)
            == "ChuMicro-Libraries-Experimental"
        )


class TestStage:
    def test_full_tree_and_index(self, tmp_path: Path):
        root = tmp_path / "repo"
        libraries_dir = root / "libraries"
        libraries_dir.mkdir(parents=True)
        _make_library(
            libraries_dir, "mqtt", version="1.2.0",
            description="MQTT client",
            examples=("pub.py", "advanced/tls.py"),
        )
        _make_library(
            libraries_dir, "timing", version="0.5.0",
            description="tick helpers", with_optional=False,
        )

        staging = tmp_path / "staged"
        document = stage_libraries_channel(root, staging, tag="20260519")

        # Tree shape a tarball of the tag must unwrap to.
        assert (staging / "mqtt" / "src" / "chumicro_mqtt"
                / "__init__.py").is_file()
        assert (staging / "mqtt" / "pyproject.toml").is_file()
        assert (staging / "mqtt" / "VERSION").is_file()
        assert (staging / "mqtt" / "tests" / "test_x.py").is_file()
        # Optional trees absent in source are simply not staged.
        assert not (staging / "timing" / "tests").exists()

        index = json.loads((staging / "index.json").read_text())
        assert index == document
        assert index["tag"] == "20260519"
        mqtt = index["libraries"]["chumicro_mqtt"]
        assert mqtt["version"] == "1.2.0"
        assert mqtt["description"] == "MQTT client"
        assert mqtt["readme_path"] == "mqtt/README.md"
        # Examples: repo-root-relative, POSIX, sorted, recursive.
        assert mqtt["examples"] == [
            "mqtt/examples/advanced/tls.py",
            "mqtt/examples/pub.py",
        ]
        assert index["libraries"]["chumicro_timing"]["examples"] == []

    def test_restage_wipes_stale_library(self, tmp_path: Path):
        root = tmp_path / "repo"
        libraries_dir = root / "libraries"
        libraries_dir.mkdir(parents=True)
        _make_library(
            libraries_dir, "mqtt", version="1.0.0", description="d",
        )
        staging = tmp_path / "staged"
        stage_libraries_channel(root, staging, tag="t1")
        assert (staging / "mqtt").is_dir()

        # mqtt removed upstream — a re-stage must not leave it behind.
        import shutil

        shutil.rmtree(libraries_dir / "mqtt")
        _make_library(
            libraries_dir, "timing", version="2.0.0", description="d",
        )
        document = stage_libraries_channel(root, staging, tag="t2")
        assert not (staging / "mqtt").exists()
        assert (staging / "timing").is_dir()
        assert set(document["libraries"]) == {"chumicro_timing"}

    def test_no_libraries_dir_is_empty(self, tmp_path: Path):
        document = stage_libraries_channel(
            tmp_path, tmp_path / "staged", tag="t",
        )
        assert document == {"tag": "t", "libraries": {}}

    def test_dir_without_version_is_skipped(self, tmp_path: Path):
        root = tmp_path / "repo"
        libraries_dir = root / "libraries"
        (libraries_dir / "scratch").mkdir(parents=True)
        (libraries_dir / "scratch" / "pyproject.toml").write_text("x\n")
        _make_library(
            libraries_dir, "mqtt", version="1.0.0", description="d",
        )
        document = stage_libraries_channel(
            root, tmp_path / "staged", tag="t",
        )
        assert set(document["libraries"]) == {"chumicro_mqtt"}


class TestMain:
    def test_stage_only_no_push(self, tmp_path: Path, capsys):
        root = tmp_path / "repo"
        libraries_dir = root / "libraries"
        libraries_dir.mkdir(parents=True)
        _make_library(
            libraries_dir, "mqtt", version="1.0.0", description="d",
        )
        staging = tmp_path / "staged"

        code = main([
            "--root", str(root),
            "--staging-dir", str(staging),
            "--tag", "20260519",
        ])
        assert code == 0
        assert (staging / "index.json").is_file()
        out = capsys.readouterr().out
        assert "Staged 1 libraries for ChuMicro-Libraries @ 20260519" in out

    def test_experimental_repo_in_summary(self, tmp_path: Path, capsys):
        root = tmp_path / "repo"
        (root / "libraries").mkdir(parents=True)
        code = main([
            "--root", str(root),
            "--staging-dir", str(tmp_path / "s"),
            "--tag", "t", "--experimental",
        ])
        assert code == 0
        assert "ChuMicro-Libraries-Experimental" in capsys.readouterr().out
