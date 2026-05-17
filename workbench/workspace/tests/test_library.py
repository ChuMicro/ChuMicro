"""Tests for chumicro_workspace.library — the PyPI fetch backend."""

from __future__ import annotations

import io
import subprocess
import tarfile
from pathlib import Path

import pytest
from chumicro_workspace.library import (
    HEAD,
    LibraryFetchError,
    LibraryFetchFailureKind,
    channel_distribution,
    classify_pip_failure,
    fetch_library,
)

_TREES = ("src", "tests", "examples", "docs")
_FILES = ("pyproject.toml", "VERSION", "README.md")


def _build_sdist(
    path: Path,
    base: str,
    *,
    trees: tuple[str, ...] = _TREES,
    files: tuple[str, ...] = _FILES,
    extra_root: bool = False,
    traversal_member: bool = False,
) -> None:
    """Write a minimal sdist .tar.gz to *path* with root dir *base*/."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w:gz") as archive:
        def add(name: str, body: bytes = b"x") -> None:
            info = tarfile.TarInfo(name)
            info.size = len(body)
            archive.addfile(info, io.BytesIO(body))

        for tree in trees:
            add(f"{base}/{tree}/placeholder")
        for filename in files:
            add(f"{base}/{filename}")
        if extra_root:
            add("second_root/placeholder")
        if traversal_member:
            add("../escape.py")


class _SdistRunner:
    """Fake subprocess.run that drops a sdist into pip's ``-d`` dir.

    Mirrors ``pip download -d <dir>`` for the happy path; configurable
    to skip the drop (wheel-only repo) or fail with canned stderr.
    """

    def __init__(
        self,
        *,
        base: str = "chumicro_mqtt-0.11.4",
        returncode: int = 0,
        stderr: str = "",
        drop_sdist: bool = True,
        **build_kwargs,
    ) -> None:
        self.base = base
        self.returncode = returncode
        self.stderr = stderr
        self.drop_sdist = drop_sdist
        self.build_kwargs = build_kwargs
        self.calls: list[list[str]] = []

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        if self.returncode == 0 and self.drop_sdist:
            dest = Path(args[args.index("-d") + 1])
            _build_sdist(
                dest / f"{self.base}.tar.gz", self.base, **self.build_kwargs,
            )
        return subprocess.CompletedProcess(
            args, self.returncode, "", self.stderr,
        )


class TestChannelDistribution:
    def test_stable(self):
        assert channel_distribution("chumicro_mqtt", "stable") == "chumicro-mqtt"

    def test_experimental(self):
        assert (
            channel_distribution("chumicro_mqtt", "experimental")
            == "chumicro-mqtt-experimental"
        )

    def test_unknown_channel_raises(self):
        with pytest.raises(LibraryFetchError) as caught:
            channel_distribution("chumicro_mqtt", "nightly")
        assert caught.value.kind is LibraryFetchFailureKind.UNKNOWN


class TestClassifyPipFailure:
    def test_package_not_found(self):
        stderr = "ERROR: Could not find a version that satisfies the requirement"
        assert (
            classify_pip_failure(stderr)
            is LibraryFetchFailureKind.PACKAGE_NOT_FOUND
        )

    def test_network(self):
        stderr = "Temporary failure in name resolution"
        assert classify_pip_failure(stderr) is LibraryFetchFailureKind.NETWORK

    def test_unknown(self):
        assert (
            classify_pip_failure("something unexpected")
            is LibraryFetchFailureKind.UNKNOWN
        )


class TestFetchLibrary:
    def test_happy_path_lands_curated_content(self, tmp_path: Path):
        runner = _SdistRunner()
        destination = fetch_library(
            "chumicro_mqtt",
            workspace_root=tmp_path,
            subprocess_runner=runner,
        )
        assert destination == tmp_path / "libraries" / "chumicro_mqtt"
        for tree in _TREES:
            assert (destination / tree).is_dir()
        for filename in _FILES:
            assert (destination / filename).is_file()

    def test_head_is_unpinned_spec(self, tmp_path: Path):
        runner = _SdistRunner()
        fetch_library(
            "chumicro_mqtt",
            version=HEAD,
            workspace_root=tmp_path,
            subprocess_runner=runner,
        )
        assert "chumicro-mqtt" in runner.calls[0]
        assert not any("==" in arg for arg in runner.calls[0])

    def test_pinned_version_in_spec(self, tmp_path: Path):
        runner = _SdistRunner(base="chumicro_mqtt-0.11.4")
        fetch_library(
            "chumicro_mqtt",
            version="0.11.4",
            workspace_root=tmp_path,
            subprocess_runner=runner,
        )
        assert "chumicro-mqtt==0.11.4" in runner.calls[0]

    def test_experimental_channel_spec(self, tmp_path: Path):
        runner = _SdistRunner(base="chumicro_mqtt_experimental-0.11.4")
        fetch_library(
            "chumicro_mqtt",
            channel="experimental",
            workspace_root=tmp_path,
            subprocess_runner=runner,
        )
        assert "chumicro-mqtt-experimental" in runner.calls[0]

    def test_pip_failure_is_classified(self, tmp_path: Path):
        runner = _SdistRunner(
            returncode=1,
            stderr="ERROR: Could not find a version that satisfies",
        )
        with pytest.raises(LibraryFetchError) as caught:
            fetch_library(
                "chumicro_nope",
                workspace_root=tmp_path,
                subprocess_runner=runner,
            )
        assert caught.value.kind is LibraryFetchFailureKind.PACKAGE_NOT_FOUND

    def test_no_sdist_downloaded(self, tmp_path: Path):
        runner = _SdistRunner(drop_sdist=False)
        with pytest.raises(LibraryFetchError) as caught:
            fetch_library(
                "chumicro_mqtt",
                workspace_root=tmp_path,
                subprocess_runner=runner,
            )
        assert caught.value.kind is LibraryFetchFailureKind.NO_SDIST

    def test_malformed_sdist_missing_tree(self, tmp_path: Path):
        runner = _SdistRunner(trees=("src", "tests", "examples"))  # no docs/
        with pytest.raises(LibraryFetchError) as caught:
            fetch_library(
                "chumicro_mqtt",
                workspace_root=tmp_path,
                subprocess_runner=runner,
            )
        assert caught.value.kind is LibraryFetchFailureKind.MALFORMED_PACKAGE
        assert "docs" in str(caught.value)

    def test_traversal_member_rejected(self, tmp_path: Path):
        runner = _SdistRunner(traversal_member=True)
        with pytest.raises(LibraryFetchError) as caught:
            fetch_library(
                "chumicro_mqtt",
                workspace_root=tmp_path,
                subprocess_runner=runner,
            )
        assert caught.value.kind is LibraryFetchFailureKind.BAD_ARCHIVE

    def test_extra_top_level_dir_rejected(self, tmp_path: Path):
        runner = _SdistRunner(extra_root=True)
        with pytest.raises(LibraryFetchError) as caught:
            fetch_library(
                "chumicro_mqtt",
                workspace_root=tmp_path,
                subprocess_runner=runner,
            )
        assert caught.value.kind is LibraryFetchFailureKind.MALFORMED_PACKAGE

    def test_replaces_existing_curated_copy(self, tmp_path: Path):
        stale = tmp_path / "libraries" / "chumicro_mqtt"
        stale.mkdir(parents=True)
        (stale / "stale_marker.py").write_text("old\n")
        runner = _SdistRunner()
        destination = fetch_library(
            "chumicro_mqtt",
            workspace_root=tmp_path,
            subprocess_runner=runner,
        )
        assert not (destination / "stale_marker.py").exists()
        assert (destination / "src").is_dir()
