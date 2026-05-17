"""End-to-end tests for the ``chumicro-workspace library`` subcommands."""

from __future__ import annotations

import io
import subprocess
import tarfile
from pathlib import Path

import pytest
from chumicro_workspace import cli
from chumicro_workspace.curated_libraries import read_curated_libraries
from chumicro_workspace.testing import seed_workspace

# Dep graph the fake registry serves: import-name -> chumicro deps.
_GRAPH = {
    "chumicro_mqtt": ["chumicro-sockets", "chumicro-timing"],
    "chumicro_sockets": ["chumicro-timing"],
    "chumicro_timing": [],
}


def _spec_to_import_name(spec: str) -> tuple[str, str | None]:
    """('chumicro-mqtt-experimental==0.2' ) -> ('chumicro_mqtt', '0.2')."""
    name, _, version = spec.partition("==")
    name = name.removesuffix("-experimental")
    return name.replace("-", "_"), (version or None)


class _RegistryRunner:
    """Fake pip that serves sdists from :data:`_GRAPH`.

    Unknown packages return a pip "no matching distribution" failure.
    """

    def __init__(self, *, version: str = "1.0.0") -> None:
        self.version = version
        self.fetched: list[str] = []

    def __call__(self, args, **kwargs):
        spec = args[args.index("-d") - 1]
        dest = Path(args[args.index("-d") + 1])
        import_name, pinned = _spec_to_import_name(spec)
        if import_name not in _GRAPH:
            return subprocess.CompletedProcess(
                args, 1, "",
                "ERROR: Could not find a version that satisfies the "
                f"requirement {spec}",
            )
        self.fetched.append(import_name)
        version = pinned or self.version
        self._build(dest, import_name, version, _GRAPH[import_name])
        return subprocess.CompletedProcess(args, 0, "", "")

    @staticmethod
    def _build(
        dest: Path, import_name: str, version: str, deps: list[str],
    ) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        base = f"{import_name}-{version}"
        rendered = ", ".join(f'"{dep}"' for dep in deps)
        files = {
            "pyproject.toml": (
                f'[project]\nname = "{import_name.replace("_", "-")}"\n'
                f"dependencies = [{rendered}]\n"
            ),
            "VERSION": f"{version}\n",
            "README.md": "# x\n",
            "src/placeholder": "",
            "tests/placeholder": "",
            "examples/placeholder": "",
            "docs/placeholder": "",
        }
        with tarfile.open(dest / f"{base}.tar.gz", "w:gz") as archive:
            for name, body in files.items():
                payload = body.encode()
                info = tarfile.TarInfo(f"{base}/{name}")
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))


def _run(args: list[str], runner: _RegistryRunner) -> int:
    return cli.main(args, env=cli.CliEnv(subprocess_runner=runner))


class TestList:
    def test_empty(self, tmp_path: Path, capsys: pytest.CaptureFixture):
        seed_workspace(tmp_path)
        assert _run(
            ["library", "list", "--workspace-dir", str(tmp_path)],
            _RegistryRunner(),
        ) == 0
        assert "No curated libraries" in capsys.readouterr().out


class TestAdd:
    def test_adds_full_transitive_closure_non_interactive(
        self, tmp_path: Path,
    ):
        seed_workspace(tmp_path)
        runner = _RegistryRunner(version="0.9.0")
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
            _RegistryRunner(),
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
            _RegistryRunner(),
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
            _RegistryRunner(),
        ) == 2

    def test_unknown_package_fails(self, tmp_path: Path):
        seed_workspace(tmp_path)
        assert _run(
            [
                "library", "add", "chumicro_nope",
                "--workspace-dir", str(tmp_path), "--non-interactive",
            ],
            _RegistryRunner(),
        ) == 1


class TestRemove:
    def test_unknown_is_usage_error(self, tmp_path: Path):
        seed_workspace(tmp_path)
        assert _run(
            [
                "library", "remove", "chumicro_mqtt",
                "--workspace-dir", str(tmp_path), "--non-interactive",
            ],
            _RegistryRunner(),
        ) == 2

    def test_removes_and_warns_on_dependents(
        self, tmp_path: Path, capsys: pytest.CaptureFixture,
    ):
        seed_workspace(tmp_path)
        runner = _RegistryRunner()
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
        table = read_curated_libraries(tmp_path / "workspace.yml")
        assert "chumicro_timing" not in table
        assert not (tmp_path / "libraries" / "chumicro_timing").exists()


class TestSwitchChannel:
    def _seed_one(self, tmp_path: Path, runner: _RegistryRunner) -> None:
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
            _RegistryRunner(),
        ) == 2

    def test_switch_re_resolves_and_records(self, tmp_path: Path):
        runner = _RegistryRunner(version="0.3.1")
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
        runner = _RegistryRunner()
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
            _RegistryRunner(),
        ) == 2

    def test_pinned_skipped_floating_refetched(
        self, tmp_path: Path, capsys: pytest.CaptureFixture,
    ):
        seed_workspace(tmp_path)
        runner = _RegistryRunner()
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
