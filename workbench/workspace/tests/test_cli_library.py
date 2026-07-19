"""End-to-end tests for the ``chumicro-workspace library`` subcommands."""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest
from chumicro_workspace import cli
from chumicro_workspace.cli.library import _apply_selected
from chumicro_workspace.curated_libraries import read_curated_libraries
from chumicro_workspace.testing import seed_workspace
from chumicro_workspace.workspace import WorkspaceLayout

# Dep graph the fake channel serves: import-name -> chumicro dist deps.
_GRAPH = {
    "chumicro_mqtt": ["chumicro-sockets", "chumicro-timing"],
    "chumicro_sockets": ["chumicro-timing"],
    "chumicro_timing": [],
}


class _Channel:
    """Fake snapshot channel: serves index.json + a source tarball.

    A snapshot is built lazily per requested tag (``"latest"`` for an
    unpinned/main resolve, the pin string itself for ``--version T``)
    so every library lands at version *version*.  Both the stable and
    experimental repos are served, so ``switch-channel`` works.
    Unknown libraries simply aren't in the tarball — the extract step
    raises ``PACKAGE_NOT_FOUND``, the real not-found path.
    """

    def __init__(self, *, version: str = "1.0.0") -> None:
        self.version = version
        self.calls: list[str] = []

    def _tarball(self, repo_stem: str, tag: str) -> bytes:
        wrapper = f"{repo_stem}-{tag}"
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            def add(name: str, body: bytes = b"") -> None:
                info = tarfile.TarInfo(name)
                info.size = len(body)
                archive.addfile(info, io.BytesIO(body))

            for import_name, deps in _GRAPH.items():
                short = import_name.removeprefix("chumicro_")
                rendered = ", ".join(f'"{dep}"' for dep in deps)
                add(
                    f"{wrapper}/{short}/pyproject.toml",
                    f'[project]\nname = "{short}"\n'
                    f"dependencies = [{rendered}]\n".encode(),
                )
                add(f"{wrapper}/{short}/VERSION", f"{self.version}\n".encode())
                add(f"{wrapper}/{short}/README.md", b"# x\n")
                add(f"{wrapper}/{short}/src/chumicro_{short}/__init__.py")
                for tree in ("src", "tests", "examples", "docs"):
                    add(f"{wrapper}/{short}/{tree}/placeholder")
            add(f"{wrapper}/index.json", self._index(tag))
        return buffer.getvalue()

    def _index(self, tag: str) -> bytes:
        return json.dumps({
            "tag": tag,
            "libraries": {
                name: {"version": self.version} for name in _GRAPH
            },
        }).encode()

    def http_get(self, url: str) -> bytes:
        self.calls.append(url)
        raw = "https://raw.githubusercontent.com/"
        codeload = "https://codeload.github.com/"
        if url.startswith(raw):
            # <owner>/<repo>/<ref>/index.json
            _, _, reference, _ = url[len(raw):].split("/", 3)
            return self._index(
                "latest" if reference == "main" else reference,
            )
        if url.startswith(codeload):
            # <owner>/<repo>/tar.gz/refs/tags/<tag>
            _, repo, _, _, _, tag = url[len(codeload):].split("/", 5)
            return self._tarball(repo, tag)
        raise AssertionError(f"unexpected URL {url}")


def _run(args: list[str], runner: _Channel) -> int:
    return cli.main(args, env=cli.CliEnv(http_get=runner.http_get))


class TestList:
    def test_empty(self, tmp_path: Path, capsys: pytest.CaptureFixture):
        seed_workspace(tmp_path)
        assert _run(
            ["library", "list", "--workspace-dir", str(tmp_path)],
            _Channel(),
        ) == 0
        assert "No curated libraries" in capsys.readouterr().out


class TestAdd:
    def test_adds_full_transitive_closure_non_interactive(
        self, tmp_path: Path,
    ):
        seed_workspace(tmp_path)
        runner = _Channel(version="0.9.0")
        code = _run(
            [
                "library", "add", "chumicro_mqtt",
                "--workspace-dir", str(tmp_path), "--non-interactive",
            ],
            runner,
        )
        assert code == 0
        table = read_curated_libraries(tmp_path / "workspace.yml")
        assert set(table) == {
            "chumicro_mqtt", "chumicro_sockets", "chumicro_timing",
        }
        for name in table:
            assert (tmp_path / "libraries" / name / "src").is_dir()
            # No --channel passed → records the DEFAULT_CHANNEL (stable
            # since the 2026-07-19 launch).
            assert table[name].channel == "stable"
            assert table[name].version == "0.9.0"

    def test_pin_records_version(self, tmp_path: Path):
        seed_workspace(tmp_path)
        _run(
            [
                "library", "add", "chumicro_timing",
                "--version", "0.3.1",
                "--workspace-dir", str(tmp_path), "--non-interactive",
            ],
            _Channel(),
        )
        table = read_curated_libraries(tmp_path / "workspace.yml")
        assert table["chumicro_timing"].version == "0.3.1"

    def test_floating_records_head(self, tmp_path: Path):
        seed_workspace(tmp_path)
        _run(
            [
                "library", "add", "chumicro_timing", "--floating",
                "--workspace-dir", str(tmp_path), "--non-interactive",
            ],
            _Channel(),
        )
        table = read_curated_libraries(tmp_path / "workspace.yml")
        assert table["chumicro_timing"].version == "HEAD"

    def test_version_and_floating_conflict(self, tmp_path: Path):
        seed_workspace(tmp_path)
        assert _run(
            [
                "library", "add", "chumicro_timing",
                "--version", "1", "--floating",
                "--workspace-dir", str(tmp_path), "--non-interactive",
            ],
            _Channel(),
        ) == 2

    def test_unknown_package_fails(self, tmp_path: Path):
        seed_workspace(tmp_path)
        assert _run(
            [
                "library", "add", "chumicro_nope",
                "--workspace-dir", str(tmp_path), "--non-interactive",
            ],
            _Channel(),
        ) == 1

    def test_per_dep_deselect_declines_only_chosen(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        """Interactive per-dep prompt: decline sockets, keep timing."""
        seed_workspace(tmp_path)
        from chumicro_workspace.cli import library as lib_mod

        monkeypatch.setattr(lib_mod, "_interactive", lambda args: True)
        monkeypatch.setattr(
            lib_mod, "_confirm",
            lambda question: "chumicro_sockets" not in question,
        )
        code = cli.main(
            ["library", "add", "chumicro_mqtt",
             "--workspace-dir", str(tmp_path)],
            env=cli.CliEnv(http_get=_Channel().http_get),
        )
        assert code == 0
        table = read_curated_libraries(tmp_path / "workspace.yml")
        assert table["chumicro_mqtt"].declined is False
        assert table["chumicro_timing"].declined is False
        assert table["chumicro_sockets"].declined is True
        assert (tmp_path / "libraries" / "chumicro_timing" / "src").is_dir()
        assert not (tmp_path / "libraries" / "chumicro_sockets").exists()


class TestRemove:
    def test_unknown_is_usage_error(self, tmp_path: Path):
        seed_workspace(tmp_path)
        assert _run(
            [
                "library", "remove", "chumicro_mqtt",
                "--workspace-dir", str(tmp_path), "--non-interactive",
            ],
            _Channel(),
        ) == 2

    def test_remove_uninstalls_but_keeps_declined_row(
        self, tmp_path: Path, capsys: pytest.CaptureFixture,
    ):
        seed_workspace(tmp_path)
        runner = _Channel()
        _run(
            [
                "library", "add", "chumicro_mqtt",
                "--workspace-dir", str(tmp_path), "--non-interactive",
            ],
            runner,
        )
        capsys.readouterr()
        code = _run(
            [
                "library", "remove", "chumicro_timing",
                "--workspace-dir", str(tmp_path), "--non-interactive",
            ],
            runner,
        )
        assert code == 0
        out = capsys.readouterr().out
        assert "still depend on chumicro_timing" in out
        assert "library forget chumicro_timing" in out
        table = read_curated_libraries(tmp_path / "workspace.yml")
        # Row kept, flipped to declined; tree uninstalled.
        assert table["chumicro_timing"].declined is True
        assert not (tmp_path / "libraries" / "chumicro_timing").exists()

    def test_update_skips_declined_then_add_flips_back(self, tmp_path: Path):
        seed_workspace(tmp_path)
        runner = _Channel(version="0.3.1")
        _run(
            [
                "library", "add", "chumicro_timing",
                "--workspace-dir", str(tmp_path), "--non-interactive",
            ],
            runner,
        )
        _run(
            [
                "library", "remove", "chumicro_timing",
                "--workspace-dir", str(tmp_path), "--non-interactive",
            ],
            runner,
        )
        # update must not resurrect a declined entry.
        _run(
            [
                "library", "update", "chumicro_timing",
                "--workspace-dir", str(tmp_path), "--non-interactive",
            ],
            runner,
        )
        assert not (tmp_path / "libraries" / "chumicro_timing").exists()
        # add flips declined back off and reinstalls.
        _run(
            [
                "library", "add", "chumicro_timing",
                "--workspace-dir", str(tmp_path), "--non-interactive",
            ],
            runner,
        )
        table = read_curated_libraries(tmp_path / "workspace.yml")
        assert table["chumicro_timing"].declined is False
        assert (tmp_path / "libraries" / "chumicro_timing" / "src").is_dir()


class TestForget:
    def test_unknown_is_usage_error(self, tmp_path: Path):
        seed_workspace(tmp_path)
        assert _run(
            [
                "library", "forget", "chumicro_mqtt",
                "--workspace-dir", str(tmp_path), "--non-interactive",
            ],
            _Channel(),
        ) == 2

    def test_forget_drops_row_and_uninstalls(self, tmp_path: Path):
        seed_workspace(tmp_path)
        runner = _Channel()
        _run(
            [
                "library", "add", "chumicro_timing",
                "--workspace-dir", str(tmp_path), "--non-interactive",
            ],
            runner,
        )
        code = _run(
            [
                "library", "forget", "chumicro_timing",
                "--workspace-dir", str(tmp_path), "--non-interactive",
            ],
            runner,
        )
        assert code == 0
        table = read_curated_libraries(tmp_path / "workspace.yml")
        assert "chumicro_timing" not in table
        assert not (tmp_path / "libraries" / "chumicro_timing").exists()

    def test_forget_a_declined_entry(self, tmp_path: Path):
        """The documented path: remove -> declined, then forget."""
        seed_workspace(tmp_path)
        runner = _Channel()
        for verb in ("add", "remove"):
            _run(
                [
                    "library", verb, "chumicro_timing",
                    "--workspace-dir", str(tmp_path), "--non-interactive",
                ],
                runner,
            )
        assert read_curated_libraries(
            tmp_path / "workspace.yml",
        )["chumicro_timing"].declined is True
        _run(
            [
                "library", "forget", "chumicro_timing",
                "--workspace-dir", str(tmp_path), "--non-interactive",
            ],
            runner,
        )
        assert "chumicro_timing" not in read_curated_libraries(
            tmp_path / "workspace.yml",
        )


class TestSwitchChannel:
    def _seed_one(self, tmp_path: Path, runner: _Channel) -> None:
        seed_workspace(tmp_path)
        _run(
            [
                "library", "add", "chumicro_timing",
                "--workspace-dir", str(tmp_path), "--non-interactive",
            ],
            runner,
        )

    def test_not_curated(self, tmp_path: Path):
        seed_workspace(tmp_path)
        assert _run(
            [
                "library", "switch-channel", "chumicro_timing",
                "experimental",
                "--workspace-dir", str(tmp_path), "--non-interactive",
            ],
            _Channel(),
        ) == 2

    def test_switch_re_resolves_and_records(self, tmp_path: Path):
        runner = _Channel(version="0.3.1")
        self._seed_one(tmp_path, runner)
        code = _run(
            [
                "library", "switch-channel", "chumicro_timing",
                "experimental",
                "--workspace-dir", str(tmp_path), "--non-interactive",
            ],
            runner,
        )
        assert code == 0
        entry = read_curated_libraries(tmp_path / "workspace.yml")[
            "chumicro_timing"
        ]
        assert entry.channel == "experimental"
        assert entry.version == "0.3.1"

    def test_already_on_channel_noop(self, tmp_path: Path):
        runner = _Channel()
        self._seed_one(tmp_path, runner)
        assert _run(
            [
                "library", "switch-channel", "chumicro_timing", "stable",
                "--workspace-dir", str(tmp_path), "--non-interactive",
            ],
            runner,
        ) == 0


class TestUpdate:
    def test_unknown_is_usage_error(self, tmp_path: Path):
        seed_workspace(tmp_path)
        assert _run(
            [
                "library", "update", "chumicro_mqtt",
                "--workspace-dir", str(tmp_path), "--non-interactive",
            ],
            _Channel(),
        ) == 2

    def test_pinned_skipped_floating_refetched(
        self, tmp_path: Path, capsys: pytest.CaptureFixture,
    ):
        seed_workspace(tmp_path)
        runner = _Channel()
        _run(
            [
                "library", "add", "chumicro_sockets", "--floating",
                "--workspace-dir", str(tmp_path), "--non-interactive",
            ],
            runner,
        )
        _run(
            [
                "library", "add", "chumicro_timing", "--version", "0.3.1",
                "--workspace-dir", str(tmp_path), "--non-interactive",
            ],
            runner,
        )
        capsys.readouterr()
        code = _run(
            [
                "library", "update",
                "--workspace-dir", str(tmp_path), "--non-interactive",
            ],
            runner,
        )
        assert code == 0
        out = capsys.readouterr().out
        assert "pinned to 0.3.1" in out
        assert "chumicro_sockets" in out


class TestBrowse:
    def test_non_tty_refuses_with_usage_exit(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        seed_workspace(tmp_path)
        # pytest's stdin is not a TTY — the inherently-interactive
        # contract: exit 2, point at the scriptable verb, no prompt.
        code = _run(
            ["library", "browse", "--workspace-dir", str(tmp_path)],
            _Channel(),
        )
        assert code == 2
        stderr = capsys.readouterr().err
        assert "needs a TTY" in stderr
        assert "library add" in stderr

    def test_apply_selected_fetches_closure_and_records(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        seed_workspace(tmp_path)
        workspace = WorkspaceLayout.from_dir(tmp_path)
        channel = _Channel(version="2.1.0")

        code = _apply_selected(
            workspace, "stable", ["chumicro_mqtt"], channel.http_get,
        )
        assert code == 0
        table = read_curated_libraries(workspace.workspace_yaml)
        # mqtt + its closure (sockets, timing) all recorded + on disk.
        assert {"chumicro_mqtt", "chumicro_sockets", "chumicro_timing"} <= set(
            table,
        )
        assert (tmp_path / "libraries" / "chumicro_mqtt" / "src").is_dir()
        assert table["chumicro_mqtt"].version == "2.1.0"
        assert "Added" in capsys.readouterr().out

    def test_apply_selected_fetch_error_returns_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        seed_workspace(tmp_path)
        workspace = WorkspaceLayout.from_dir(tmp_path)

        code = _apply_selected(
            workspace, "stable", ["chumicro_nope"], _Channel().http_get,
        )
        assert code == 1
        assert "library browse:" in capsys.readouterr().err


def _read_extra_paths(tmp_path: Path) -> list[str]:
    """Return the ``extraPaths`` list from the workspace pyrightconfig."""
    document = json.loads(
        (tmp_path / "pyrightconfig.json").read_text(encoding="utf-8"),
    )
    return document["extraPaths"]


class TestPyrightExtraPaths:
    """``library`` maintains ``pyrightconfig.json`` extraPaths."""

    def test_add_registers_source_dirs_and_notes(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ):
        seed_workspace(tmp_path)
        code = _run(
            [
                "library", "add", "chumicro_mqtt",
                "--workspace-dir", str(tmp_path), "--non-interactive",
            ],
            _Channel(),
        )
        assert code == 0
        # Every acquired library's src dir lands, appended sorted.
        assert _read_extra_paths(tmp_path) == [
            "libraries/chumicro_mqtt/src",
            "libraries/chumicro_sockets/src",
            "libraries/chumicro_timing/src",
        ]
        assert "Updated pyrightconfig.json" in capsys.readouterr().out

    def test_missing_file_is_created(self, tmp_path: Path):
        seed_workspace(tmp_path)
        assert not (tmp_path / "pyrightconfig.json").exists()
        _run(
            [
                "library", "add", "chumicro_timing",
                "--workspace-dir", str(tmp_path), "--non-interactive",
            ],
            _Channel(),
        )
        text = (tmp_path / "pyrightconfig.json").read_text(encoding="utf-8")
        # 2-space indent, trailing newline, just the extraPaths key.
        assert text == (
            '{\n  "extraPaths": [\n'
            '    "libraries/chumicro_timing/src"\n  ]\n}\n'
        )

    def test_re_add_is_idempotent(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ):
        seed_workspace(tmp_path)
        runner = _Channel()
        _run(
            [
                "library", "add", "chumicro_timing",
                "--workspace-dir", str(tmp_path), "--non-interactive",
            ],
            runner,
        )
        capsys.readouterr()
        _run(
            [
                "library", "add", "chumicro_timing",
                "--workspace-dir", str(tmp_path), "--non-interactive",
            ],
            runner,
        )
        # No duplicate entry, and the idempotent re-add prints no pyright note.
        assert _read_extra_paths(tmp_path) == [
            "libraries/chumicro_timing/src",
        ]
        assert "Updated pyrightconfig.json" not in capsys.readouterr().out

    def test_unrelated_entries_and_keys_preserved(self, tmp_path: Path):
        seed_workspace(tmp_path)
        (tmp_path / "pyrightconfig.json").write_text(
            json.dumps(
                {"include": ["projects"], "extraPaths": ["shared"]},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        _run(
            [
                "library", "add", "chumicro_timing",
                "--workspace-dir", str(tmp_path), "--non-interactive",
            ],
            _Channel(),
        )
        document = json.loads(
            (tmp_path / "pyrightconfig.json").read_text(encoding="utf-8"),
        )
        # "shared" kept first; new entry appended after it.
        assert document["extraPaths"] == [
            "shared", "libraries/chumicro_timing/src",
        ]
        # Unrelated top-level key untouched.
        assert document["include"] == ["projects"]

    def test_remove_drops_entry_and_keeps_others(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ):
        seed_workspace(tmp_path)
        (tmp_path / "pyrightconfig.json").write_text(
            '{\n  "extraPaths": [\n    "shared"\n  ]\n}\n',
            encoding="utf-8",
        )
        runner = _Channel()
        _run(
            [
                "library", "add", "chumicro_timing",
                "--workspace-dir", str(tmp_path), "--non-interactive",
            ],
            runner,
        )
        assert _read_extra_paths(tmp_path) == [
            "shared", "libraries/chumicro_timing/src",
        ]
        capsys.readouterr()
        _run(
            [
                "library", "remove", "chumicro_timing",
                "--workspace-dir", str(tmp_path), "--non-interactive",
            ],
            runner,
        )
        # Library entry dropped; unrelated "shared" preserved.
        assert _read_extra_paths(tmp_path) == ["shared"]
        assert "Updated pyrightconfig.json" in capsys.readouterr().out

    def test_forget_drops_entry(self, tmp_path: Path):
        seed_workspace(tmp_path)
        runner = _Channel()
        _run(
            [
                "library", "add", "chumicro_timing",
                "--workspace-dir", str(tmp_path), "--non-interactive",
            ],
            runner,
        )
        _run(
            [
                "library", "forget", "chumicro_timing",
                "--workspace-dir", str(tmp_path), "--non-interactive",
            ],
            runner,
        )
        assert _read_extra_paths(tmp_path) == []

    def test_invalid_json_warns_but_add_succeeds(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ):
        seed_workspace(tmp_path)
        (tmp_path / "pyrightconfig.json").write_text(
            "{ not valid json", encoding="utf-8",
        )
        code = _run(
            [
                "library", "add", "chumicro_timing",
                "--workspace-dir", str(tmp_path), "--non-interactive",
            ],
            _Channel(),
        )
        # Acquisition still succeeds even though the config can't be updated.
        assert code == 0
        table = read_curated_libraries(tmp_path / "workspace.yml")
        assert "chumicro_timing" in table
        assert (tmp_path / "libraries" / "chumicro_timing" / "src").is_dir()
        out = capsys.readouterr().out
        assert "pyrightconfig.json is not valid JSON" in out
        # The broken file is left exactly as it was.
        assert (tmp_path / "pyrightconfig.json").read_text(
            encoding="utf-8",
        ) == "{ not valid json"
