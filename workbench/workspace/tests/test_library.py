"""Tests for chumicro_workspace.library — the snapshot fetch backend.

No sockets: an injected ``http_get`` serves an ``index.json`` and a
snapshot tarball built in memory.
"""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest
from chumicro_workspace.curated_libraries import DEFAULT_CHANNEL
from chumicro_workspace.library import (
    LOCAL_EDIT_SENTINEL,
    LibraryFetchError,
    LibraryFetchFailureKind,
    fetch_closure,
    fetch_library,
    is_locally_held,
    read_installed_version,
    remove_library,
)
from chumicro_workspace.library_channel import channel_repo, index_url, tarball_url

# The channel-less fetch_* calls below resolve to DEFAULT_CHANNEL, so the
# served fixtures must key on that channel's repo (tracks the default
# through any future stable/experimental flip).
_REPO = channel_repo(DEFAULT_CHANNEL)


def _pyproject(deps: tuple[str, ...]) -> bytes:
    body = "[project]\nname = 'x'\ndependencies = [{}]\n".format(
        ", ".join(repr(dep) for dep in deps),
    )
    return body.encode()


def _snapshot(
    tag: str,
    libraries: dict[str, dict],
    *,
    drop_tree: str | None = None,
) -> bytes:
    """Build a GitHub-shaped tarball of full curated library trees.

    *libraries* maps short name -> {"version": str, "deps": tuple}.
    *drop_tree* omits one REQUIRED tree from every library (to
    exercise the malformed-content guard).
    """
    wrapper = f"ChuMicro-Libraries-{tag}"
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        def add(name: str, body: bytes = b"x") -> None:
            info = tarfile.TarInfo(name)
            info.size = len(body)
            archive.addfile(info, io.BytesIO(body))

        index = {"tag": tag, "libraries": {}}
        for short, spec in libraries.items():
            index["libraries"][f"chumicro_{short}"] = {
                "version": spec["version"],
            }
            for tree in ("src", "tests", "examples", "docs"):
                if tree == drop_tree:
                    continue
                add(f"{wrapper}/{short}/{tree}/placeholder")
            add(
                f"{wrapper}/{short}/src/chumicro_{short}/__init__.py",
            )
            add(
                f"{wrapper}/{short}/pyproject.toml",
                _pyproject(spec.get("deps", ())),
            )
            add(f"{wrapper}/{short}/VERSION", spec["version"].encode())
            add(f"{wrapper}/{short}/README.md")
        add(f"{wrapper}/index.json", json.dumps(index).encode())
    return buffer.getvalue()


def _channel(tag: str, libraries: dict[str, dict]):
    """An ``http_get`` serving the index + tarball for one snapshot."""
    tarball = _snapshot(tag, libraries)
    index = json.dumps({
        "tag": tag,
        "libraries": {
            f"chumicro_{short}": {"version": spec["version"]}
            for short, spec in libraries.items()
        },
    }).encode()
    served = {
        index_url(_REPO, "main"): index,
        index_url(_REPO, tag): index,
        tarball_url(_REPO, tag): tarball,
    }
    calls: list[str] = []

    def http_get(url: str) -> bytes:
        calls.append(url)
        try:
            return served[url]
        except KeyError:
            raise LibraryFetchError(
                LibraryFetchFailureKind.PACKAGE_NOT_FOUND, f"404 {url}",
            ) from None

    http_get.calls = calls  # type: ignore[attr-defined]
    return http_get


class TestFetchLibrary:
    def test_lands_curated_tree(self, tmp_path: Path):
        http_get = _channel("20260519", {"mqtt": {"version": "1.2.0"}})
        destination = fetch_library(
            "chumicro_mqtt",
            workspace_root=tmp_path,
            http_get=http_get,
        )
        assert destination == tmp_path / "libraries" / "chumicro_mqtt"
        assert (destination / "src" / "chumicro_mqtt" / "__init__.py").is_file()
        assert (destination / "pyproject.toml").is_file()
        assert read_installed_version(tmp_path, "chumicro_mqtt") == "1.2.0"

    def test_pinned_tag_resolves_that_snapshot(self, tmp_path: Path):
        http_get = _channel("20260101", {"mqtt": {"version": "0.9.0"}})
        fetch_library(
            "chumicro_mqtt",
            version="20260101",
            workspace_root=tmp_path,
            http_get=http_get,
        )
        assert read_installed_version(tmp_path, "chumicro_mqtt") == "0.9.0"

    def test_refetch_backs_up_edited_tree(self, tmp_path: Path):
        http_get = _channel("20260519", {"mqtt": {"version": "1.2.0"}})
        fetch_library(
            "chumicro_mqtt", workspace_root=tmp_path, http_get=http_get,
        )
        edited = (
            tmp_path / "libraries" / "chumicro_mqtt" / "src"
            / "chumicro_mqtt" / "__init__.py"
        )
        edited.write_text("# my local change\n", encoding="utf-8")

        fetch_library(
            "chumicro_mqtt", workspace_root=tmp_path, http_get=http_get,
        )

        backups = list(
            (tmp_path / "_library-backups" / "chumicro_mqtt").iterdir(),
        )
        assert len(backups) == 1
        assert backups[0].name.startswith("1.2.0-")
        preserved = (
            backups[0] / "src" / "chumicro_mqtt" / "__init__.py"
        ).read_text(encoding="utf-8")
        assert preserved == "# my local change\n"
        # Fresh copy replaced the working tree.
        assert "my local change" not in edited.read_text(encoding="utf-8")

    def test_malformed_tree_is_classified(self, tmp_path: Path):
        tarball = _snapshot(
            "t", {"mqtt": {"version": "1.0.0"}}, drop_tree="tests",
        )
        served = {
            index_url(_REPO, "main"): json.dumps(
                {"tag": "t", "libraries": {"chumicro_mqtt": {"version": "1"}}},
            ).encode(),
            tarball_url(_REPO, "t"): tarball,
        }
        with pytest.raises(LibraryFetchError) as caught:
            fetch_library(
                "chumicro_mqtt",
                workspace_root=tmp_path,
                http_get=lambda url: served[url],
            )
        assert caught.value.kind is LibraryFetchFailureKind.MALFORMED_PACKAGE

    def test_unknown_library_propagates(self, tmp_path: Path):
        http_get = _channel("t", {"timing": {"version": "1.0.0"}})
        with pytest.raises(LibraryFetchError) as caught:
            fetch_library(
                "chumicro_mqtt", workspace_root=tmp_path, http_get=http_get,
            )
        assert caught.value.kind is LibraryFetchFailureKind.PACKAGE_NOT_FOUND


class TestFetchClosure:
    def test_single_snapshot_one_tarball_get(self, tmp_path: Path):
        http_get = _channel("20260519", {
            "mqtt": {"version": "1.2.0", "deps": ("chumicro-timing",)},
            "timing": {"version": "0.5.0"},
        })
        closure = fetch_closure(
            "chumicro_mqtt", workspace_root=tmp_path, http_get=http_get,
        )
        assert closure == ["chumicro_mqtt", "chumicro_timing"]
        assert read_installed_version(tmp_path, "chumicro_timing") == "0.5.0"
        # One snapshot: exactly one tarball download for the whole set.
        tar_gets = [
            url for url in http_get.calls
            if url == tarball_url(_REPO, "20260519")
        ]
        assert len(tar_gets) == 1

    def test_cycle_safe(self, tmp_path: Path):
        http_get = _channel("t", {
            "a": {"version": "1", "deps": ("chumicro-b",)},
            "b": {"version": "1", "deps": ("chumicro-a",)},
        })
        closure = fetch_closure(
            "chumicro_a", workspace_root=tmp_path, http_get=http_get,
        )
        assert sorted(closure) == ["chumicro_a", "chumicro_b"]


class TestHousekeeping:
    def test_read_installed_version_absent(self, tmp_path: Path):
        assert read_installed_version(tmp_path, "chumicro_mqtt") is None

    def test_remove_library(self, tmp_path: Path):
        http_get = _channel("t", {"mqtt": {"version": "1.0.0"}})
        fetch_library(
            "chumicro_mqtt", workspace_root=tmp_path, http_get=http_get,
        )
        assert remove_library(tmp_path, "chumicro_mqtt") is True
        assert remove_library(tmp_path, "chumicro_mqtt") is False


class TestLocalEditSentinel:
    """A user-dropped `.chumicro-local` claims the tree as theirs."""

    def test_is_locally_held_detects_sentinel(self, tmp_path: Path):
        package_dir = tmp_path / "libraries" / "chumicro_mqtt"
        package_dir.mkdir(parents=True)
        assert is_locally_held(tmp_path, "chumicro_mqtt") is False
        (package_dir / LOCAL_EDIT_SENTINEL).write_text(
            "# I own this tree now.\n",
        )
        assert is_locally_held(tmp_path, "chumicro_mqtt") is True

    def test_fetch_preserves_held_tree_and_notices(
        self, tmp_path: Path, capsys,
    ):
        # First install lands the channel content (no sentinel yet —
        # the sentinel is a user-added marker, not part of the snapshot).
        http_get = _channel("t1", {"mqtt": {"version": "1.0.0"}})
        fetch_library(
            "chumicro_mqtt", workspace_root=tmp_path, http_get=http_get,
        )
        edited = (
            tmp_path / "libraries" / "chumicro_mqtt" / "src"
            / "chumicro_mqtt" / "__init__.py"
        )
        edited.write_text("# my fork\n", encoding="utf-8")
        # User drops the sentinel: "leave this alone from now on."
        (
            tmp_path / "libraries" / "chumicro_mqtt" / LOCAL_EDIT_SENTINEL
        ).write_text("# my fork", encoding="utf-8")
        capsys.readouterr()

        # Channel bumps to a new version + a re-fetch runs.
        http_get_v2 = _channel("t2", {"mqtt": {"version": "2.0.0"}})
        fetch_library(
            "chumicro_mqtt", workspace_root=tmp_path, http_get=http_get_v2,
        )

        # Sentinel wins: the edited file survives intact; no backup
        # directory was created (no clobber happened to back up from).
        assert edited.read_text(encoding="utf-8") == "# my fork\n"
        assert not (tmp_path / "_library-backups").exists()
        notice = capsys.readouterr().out
        assert "kept local edits in libraries/chumicro_mqtt/" in notice
        assert "channel has v2.0.0" in notice
        # The notice mentions the actual sentinel filename so a future
        # reader can find it by grep.
        assert LOCAL_EDIT_SENTINEL in notice

    def test_transitive_walk_respects_sentinel(
        self, tmp_path: Path, capsys,
    ):
        # Set up a closure where the user has held one transitive dep.
        # First install: pull mqtt → also pulls timing.
        http_get = _channel("t1", {
            "mqtt": {"version": "1.0.0", "deps": ("chumicro-timing",)},
            "timing": {"version": "0.5.0"},
        })
        fetch_closure(
            "chumicro_mqtt", workspace_root=tmp_path, http_get=http_get,
        )
        # User edits timing + claims it.
        timing_init = (
            tmp_path / "libraries" / "chumicro_timing" / "src"
            / "chumicro_timing" / "__init__.py"
        )
        timing_init.write_text("# my timing fork\n", encoding="utf-8")
        (
            tmp_path / "libraries" / "chumicro_timing" / LOCAL_EDIT_SENTINEL
        ).touch()
        capsys.readouterr()

        # Re-add mqtt (or anything pulling timing transitively): mqtt's
        # tree gets replaced from the new snapshot, timing stays put.
        http_get_v2 = _channel("t2", {
            "mqtt": {"version": "1.1.0", "deps": ("chumicro-timing",)},
            "timing": {"version": "0.6.0"},
        })
        fetch_closure(
            "chumicro_mqtt", workspace_root=tmp_path, http_get=http_get_v2,
        )
        assert timing_init.read_text(encoding="utf-8") == "# my timing fork\n"
        notice = capsys.readouterr().out
        assert "kept local edits in libraries/chumicro_timing/" in notice
        # The non-held member (mqtt) was actually refreshed.
        assert read_installed_version(tmp_path, "chumicro_mqtt") == "1.1.0"
