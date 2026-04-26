"""Tests for the chumicro-workspace CLI dispatcher.

Covers command parsing, dispatch routing, the implemented commands
(via mocked underlying APIs), and the contract of stubs (exit code
2 + descriptive message).
"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from chumicro_deploy import Device
from chumicro_deploy.testing import FakeTransport
from chumicro_msgpack import unpackb
from chumicro_workspace import cli


def _seed_workspace(tmp_path: Path) -> Path:
    """Create a minimal workspace at *tmp_path* and return the root."""
    (tmp_path / "workspace.yml").write_text(
        "defaults:\n  wifi:\n    hostname_prefix: chu-\n"
    )
    (tmp_path / "secrets.yml").write_text("wifi_password: shh\n")
    (tmp_path / "devices.yml").write_text(
        "defaults:\n"
        "  micropython: lolin-s2\n"
        "devices:\n"
        "  - id: lolin-s2\n"
        "    runtime: micropython\n"
        "    address: /dev/cu.fake\n"
    )
    return tmp_path


def _seed_thing(workspace_root: Path, name: str = "back-porch") -> Path:
    """Add a thing under *workspace_root*/things/<name>/ and return its dir.

    Carries both ``code.py`` (CircuitPython convention) and ``main.py``
    (MicroPython convention) so the deploy command's runtime-derived
    entrypoint resolves cleanly regardless of the test fixture's chosen
    transport.
    """
    thing_dir = workspace_root / "things" / name
    thing_dir.mkdir(parents=True)
    (thing_dir / "config.toml").write_text(
        "[wifi]\nssid = 'HomeNet'\npassword = '!secret wifi_password'\n"
    )
    (thing_dir / "code.py").write_text("print('hello from thing')\n")
    (thing_dir / "main.py").write_text("print('hello from thing')\n")
    return thing_dir


# ---------------------------------------------------------------------------
# Parser construction — every command registers
# ---------------------------------------------------------------------------


class TestParser:
    """Each documented command must register on the top-level parser."""

    EXPECTED_COMMANDS = (
        "setup", "init", "update", "new", "add-device", "probe",
        "discover", "devices", "deploy", "switch", "things", "demo",
        "bootstrap", "sim", "test", "repl", "env", "use", "rename",
        "install-firmware", "upgrade-firmware", "sync", "upgrade",
    )

    def test_all_commands_register(self) -> None:
        parser = cli.build_parser()
        subparsers_action = next(
            action for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        )
        registered = set(subparsers_action.choices)
        missing = set(self.EXPECTED_COMMANDS) - registered
        assert not missing, f"missing CLI commands: {sorted(missing)}"

    def test_top_level_help_does_not_crash(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        with pytest.raises(SystemExit) as caught:
            cli.main(["--help"])
        assert caught.value.code == 0
        captured = capsys.readouterr()
        assert "deploy" in captured.out
        assert "probe" in captured.out


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------


class TestSetup:
    def test_no_pyproject_is_a_no_op(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _seed_workspace(tmp_path)
        exit_code = cli.main(["setup", "--workspace-dir", str(tmp_path)])
        assert exit_code == 0
        assert "skipping editable install" in capsys.readouterr().out

    def test_runs_pip_install_when_pyproject_present(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        root = _seed_workspace(tmp_path)
        (root / "pyproject.toml").write_text("[project]\nname = 'demo'\n")

        recorded: list[list[str]] = []

        def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
            recorded.append(args)
            return subprocess.CompletedProcess(args, 0)

        monkeypatch.setattr(cli.subprocess, "run", fake_run)
        exit_code = cli.main(["setup", "--workspace-dir", str(root)])
        assert exit_code == 0
        assert recorded == [
            [sys.executable, "-m", "pip", "install", "-e", str(root)],
        ]

    def test_materializes_templates_on_setup(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Decision 0038 §5: setup walks `_templates/` and materializes
        any missing files at the workspace root.  No pyproject means
        the install path short-circuits, but materialization still runs.
        """
        root = _seed_workspace(tmp_path)
        templates = root / "_templates"
        templates.mkdir()
        (templates / "secrets.yml").write_text(
            "# fill in your wifi password\nwifi_password: \n",
        )
        # Remove the pre-seeded secrets.yml so materialize has work to do.
        (root / "secrets.yml").unlink()
        exit_code = cli.main(["setup", "--workspace-dir", str(root)])
        assert exit_code == 0
        assert (root / "secrets.yml").read_text().startswith("# fill in your")
        assert "materialized 1 file(s) from _templates/" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# init / update
# ---------------------------------------------------------------------------


class TestInitCommand:
    def test_clones_local_template_repo(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        upstream = tmp_path / "upstream"
        upstream.mkdir()
        (upstream / "run.py").write_text("# tool-owned shim\n")
        subprocess.run(  # noqa: S603 — args fully controlled
            ["git", "init", "-b", "main"], cwd=str(upstream), check=True,
            capture_output=True,
        )
        subprocess.run(  # noqa: S603 — args fully controlled
            ["git", "add", "-A"], cwd=str(upstream), check=True,
            capture_output=True,
        )
        subprocess.run(  # noqa: S603 — args fully controlled
            [
                "git",
                "-c", "user.email=test@example.com",
                "-c", "user.name=Test",
                "commit", "-m", "initial",
            ],
            cwd=str(upstream), check=True, capture_output=True,
        )

        target = tmp_path / "house"
        exit_code = cli.main([
            "init", str(target), "--from", str(upstream),
        ])
        assert exit_code == 0
        assert (target / "run.py").is_file()
        # Decoupled from upstream — fresh git init, no log entries.
        log = subprocess.run(  # noqa: S603 — args fully controlled
            ["git", "log", "--oneline"],
            cwd=str(target), capture_output=True, text=True, check=False,
        )
        assert log.stdout.strip() == ""
        captured = capsys.readouterr()
        assert "next: cd" in captured.out and "run.py setup" in captured.out

    def test_refuses_non_empty_target_without_force(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        target = tmp_path / "house"
        target.mkdir()
        (target / "leftover.txt").write_text("data\n")
        exit_code = cli.main([
            "init", str(target), "--from", "/nonexistent",
        ])
        assert exit_code == 1
        assert "--force" in capsys.readouterr().err


class TestUpdateCommand:
    def test_dispatches_to_template_apply_update(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from chumicro_workspace import template_apply

        recorded: dict[str, object] = {}

        def fake_update(
            target: Path, *, template_url: str, git_reference: str | None,
        ) -> Any:
            recorded["target"] = target
            recorded["url"] = template_url
            recorded["git_reference"] = git_reference
            return template_apply.ApplyReport()

        monkeypatch.setattr(template_apply, "update", fake_update)
        root = _seed_workspace(tmp_path)
        exit_code = cli.main([
            "update", "--workspace-dir", str(root),
            "--from", "https://example.com/fork",
            "--ref", "v1.2.3",
        ])
        assert exit_code == 0
        assert recorded["target"] == root
        assert recorded["url"] == "https://example.com/fork"
        assert recorded["git_reference"] == "v1.2.3"


class TestNew:
    def test_copies_template_to_named_dir(self, tmp_path: Path) -> None:
        root = _seed_workspace(tmp_path)
        template = root / "things" / "_template"
        template.mkdir(parents=True)
        (template / "code.py").write_text("# template\n")
        (template / "config.toml").write_text("[app]\n")

        exit_code = cli.main(
            ["new", "--workspace-dir", str(root), "kitchen_sensor"],
        )
        assert exit_code == 0

        target = root / "things" / "kitchen_sensor"
        assert (target / "code.py").read_text() == "# template\n"
        assert (target / "config.toml").read_text() == "[app]\n"

    def test_missing_template_raises(self, tmp_path: Path) -> None:
        root = _seed_workspace(tmp_path)
        with pytest.raises(SystemExit) as caught:
            cli.main(["new", "--workspace-dir", str(root), "anything"])
        assert "template" in str(caught.value)

    def test_existing_target_raises(self, tmp_path: Path) -> None:
        root = _seed_workspace(tmp_path)
        template = root / "things" / "_template"
        template.mkdir(parents=True)
        (template / "code.py").write_text("\n")
        (root / "things" / "exists").mkdir()
        with pytest.raises(SystemExit) as caught:
            cli.main(["new", "--workspace-dir", str(root), "exists"])
        assert "already exists" in str(caught.value)

    @pytest.mark.parametrize(
        ("bad_name", "match"),
        [
            ("kitchen-sensor", "valid Python identifier"),
            ("1sensor", "valid Python identifier"),
            ("kitchen.sensor", "valid Python identifier"),
            ("kitchen sensor", "valid Python identifier"),
            ("_template", "leading"),
            ("_private", "leading"),
            ("class", "keyword"),
            ("import", "keyword"),
        ],
    )
    def test_rejects_invalid_thing_names(
        self,
        tmp_path: Path,
        bad_name: str,
        match: str,
    ) -> None:
        # Validation runs before the template lookup, so we deliberately
        # don't pre-create things/_template — that lets us verify the
        # filesystem is untouched on rejection.
        root = _seed_workspace(tmp_path)
        with pytest.raises(SystemExit) as caught:
            cli.main(["new", "--workspace-dir", str(root), bad_name])
        assert match in str(caught.value)
        assert not (root / "things").exists()

    def test_rejects_empty_thing_name(self, tmp_path: Path) -> None:
        root = _seed_workspace(tmp_path)
        with pytest.raises(SystemExit) as caught:
            cli.main(["new", "--workspace-dir", str(root), ""])
        assert "empty" in str(caught.value)


# ---------------------------------------------------------------------------
# discover
# ---------------------------------------------------------------------------


class _FakePort:
    """Minimal stand-in for ``serial.tools.list_ports_common.ListPortInfo``."""

    def __init__(self, device: str, description: str = "") -> None:
        self.device = device
        self.description = description


class TestDiscover:
    def test_lists_ports(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from serial.tools import list_ports

        monkeypatch.setattr(
            list_ports,
            "comports",
            lambda: [_FakePort("/dev/cu.b", "Board B"), _FakePort("/dev/cu.a", "Board A")],
        )
        exit_code = cli.main(["discover"])
        assert exit_code == 0
        out = capsys.readouterr().out.splitlines()
        assert out == ["/dev/cu.a\tBoard A", "/dev/cu.b\tBoard B"]

    def test_no_ports_message(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from serial.tools import list_ports

        monkeypatch.setattr(list_ports, "comports", list)
        exit_code = cli.main(["discover"])
        assert exit_code == 0
        assert "no serial ports detected" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# devices
# ---------------------------------------------------------------------------


class TestDevices:
    def test_prints_entries(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _seed_workspace(tmp_path)
        exit_code = cli.main(["devices", "--workspace-dir", str(root)])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "lolin-s2" in out
        assert "micropython" in out
        assert "/dev/cu.fake" in out

    def test_missing_devices_yml_message(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        (tmp_path / "workspace.yml").write_text("defaults: {}\n")
        exit_code = cli.main(["devices", "--workspace-dir", str(tmp_path)])
        assert exit_code == 0
        assert "does not exist yet" in capsys.readouterr().out

    def test_no_entries_message(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        (tmp_path / "workspace.yml").write_text("defaults: {}\n")
        (tmp_path / "devices.yml").write_text("devices: []\n")
        exit_code = cli.main(["devices", "--workspace-dir", str(tmp_path)])
        assert exit_code == 0
        assert "no entries" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# deploy
# ---------------------------------------------------------------------------


class TestDeploy:
    def test_ships_thing_through_fake_transport(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        root = _seed_workspace(tmp_path)
        _seed_thing(root)

        transport = FakeTransport(execute_output="")
        monkeypatch.setattr(Device, "create_transport", lambda self: transport)

        exit_code = cli.main(
            ["deploy", "--workspace-dir", str(root), "back-porch"],
        )
        assert exit_code == 0

        deploy_calls = [call for call in transport.calls if call[0] == "deploy_files"]
        assert len(deploy_calls) == 1
        files, entrypoint = deploy_calls[0][1]
        assert entrypoint == "/main.py"  # MP default per Device.effective_entrypoint
        decoded = unpackb(files["/runtime_config.msgpack"])
        assert decoded["wifi"]["password"] == "shh"

    def test_missing_thing_raises(self, tmp_path: Path) -> None:
        root = _seed_workspace(tmp_path)
        with pytest.raises(SystemExit) as caught:
            cli.main(["deploy", "--workspace-dir", str(root), "ghost"])
        assert "ghost" in str(caught.value)

    def test_traceback_returns_exit_one(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _seed_workspace(tmp_path)
        _seed_thing(root)
        # FakeTransport returns whatever ``execute_output`` it's
        # carrying — supply a synthetic traceback so the deployer's
        # success heuristic flips to False.
        transport = FakeTransport(
            execute_output=(
                "Traceback (most recent call last):\n"
                "  File \"/code.py\", line 1\n"
                "RuntimeError: boom\n"
            ),
        )
        monkeypatch.setattr(Device, "create_transport", lambda self: transport)
        exit_code = cli.main(
            ["deploy", "--workspace-dir", str(root), "back-porch"],
        )
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "RuntimeError: boom" in captured.err

    def test_explicit_entrypoint_override(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        root = _seed_workspace(tmp_path)
        thing_dir = _seed_thing(root)
        (thing_dir / "boot.py").write_text("print('boot')\n")

        transport = FakeTransport(execute_output="")
        monkeypatch.setattr(Device, "create_transport", lambda self: transport)

        cli.main([
            "deploy", "--workspace-dir", str(root),
            "--entrypoint", "/boot.py", "back-porch",
        ])
        deploy_calls = [call for call in transport.calls if call[0] == "deploy_files"]
        assert deploy_calls[0][1][1] == "/boot.py"

    def test_boot_shim_flag_uses_boot_pattern(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Slice 7: --boot-shim routes through thing_boot_source."""
        root = _seed_workspace(tmp_path)
        thing_dir = root / "things" / "back-porch"
        thing_dir.mkdir(parents=True)
        (thing_dir / "config.toml").write_text(
            "[wifi]\nssid = 'HomeNet'\npassword = '!secret wifi_password'\n"
        )
        (thing_dir / "app.py").write_text("def run(): print('hi')\n")

        transport = FakeTransport(execute_output="")
        monkeypatch.setattr(Device, "create_transport", lambda self: transport)

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root),
            "--boot-shim", "back-porch",
        ])
        assert exit_code == 0
        deploy_calls = [call for call in transport.calls if call[0] == "deploy_files"]
        files, entrypoint = deploy_calls[0][1]
        # Boot-shim layout: shim entrypoint at root, thing under /lib/things/.
        assert entrypoint == "/main.py"  # MP runtime in seed
        assert "/main.py" in files
        assert "/active.py" in files
        assert "/lib/workspace_runtime/__init__.py" in files
        assert "/lib/things/back-porch/app.py" in files
        assert b'"back-porch"' in files["/active.py"]

    def test_boot_shim_and_import_graph_mutually_exclusive(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The two layouts can't combine — they ship different on-device shapes."""
        root = _seed_workspace(tmp_path)
        thing_dir = root / "things" / "back-porch"
        thing_dir.mkdir(parents=True)
        (thing_dir / "config.toml").write_text("[wifi]\nssid = 'x'\n")
        (thing_dir / "app.py").write_text("def run(): pass\n")
        (thing_dir / "main.py").write_text("import x\n")

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root),
            "--boot-shim", "--import-graph", "back-porch",
        ])
        assert exit_code == 2
        assert "mutually exclusive" in capsys.readouterr().err

    def test_import_graph_flag_uses_ast_walker(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Slice 6: --import-graph routes through thing_import_graph_source."""
        root = _seed_workspace(tmp_path)
        # Stage a libs/ module alongside the thing's main.py.
        libs = root / "libs"
        libs.mkdir()
        (libs / "imported_module.py").write_text("def helper(): pass\n")
        (libs / "unimported_module.py").write_text("# never reached\n")

        thing_dir = root / "things" / "back-porch"
        thing_dir.mkdir(parents=True)
        (thing_dir / "config.toml").write_text(
            "[wifi]\nssid = 'HomeNet'\npassword = '!secret wifi_password'\n"
        )
        # MP runtime in seed → effective_entrypoint == 'main.py'.
        (thing_dir / "main.py").write_text(
            "import imported_module\nprint('hi')\n"
        )

        transport = FakeTransport(execute_output="")
        monkeypatch.setattr(Device, "create_transport", lambda self: transport)

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root),
            "--import-graph", "back-porch",
        ])
        assert exit_code == 0
        deploy_calls = [call for call in transport.calls if call[0] == "deploy_files"]
        files, _entrypoint = deploy_calls[0][1]
        # AST walker shipped main.py + the imported helper, NOT the
        # unimported one.
        assert "/lib/imported_module.py" in files
        assert "/lib/unimported_module.py" not in files


def _seed_two_things(workspace_root: Path) -> tuple[Path, Path]:
    """Seed two boot-shim-ready things and return their dirs."""
    weather = workspace_root / "things" / "weather"
    weather.mkdir(parents=True)
    (weather / "config.toml").write_text(
        "[wifi]\nssid = 'WeatherNet'\npassword = '!secret wifi_password'\n",
    )
    (weather / "app.py").write_text("def run(): print('weather')\n")

    heater = workspace_root / "things" / "heater"
    heater.mkdir(parents=True)
    (heater / "config.toml").write_text("[heater]\ntoken = 'hot'\n")
    (heater / "app.py").write_text("def run(): print('heater')\n")
    return weather, heater


class TestDeploySingleThingDefault:
    """`deploy` with no positional defaults to the lone thing.

    Step 2 of the beginner-onramp workstream — covers the "I only
    have one app" beginner case so single-board users don't have to
    type the thing name.  Multiple-thing workspaces still require
    an explicit positional.
    """

    def test_zero_things_errors_with_help_text(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _seed_workspace(tmp_path)
        # things/ doesn't exist yet — list_things() returns empty.
        exit_code = cli.main(["deploy", "--workspace-dir", str(root)])
        assert exit_code == 2
        captured = capsys.readouterr()
        assert "no things to deploy" in captured.err
        assert "new <name>" in captured.err

    def test_single_thing_deploys_implicitly(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _seed_workspace(tmp_path)
        _seed_thing(root)

        transport = FakeTransport(execute_output="")
        monkeypatch.setattr(Device, "create_transport", lambda self: transport)

        exit_code = cli.main(["deploy", "--workspace-dir", str(root)])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "defaulting to back-porch" in captured.out

        # Same shipping behaviour as the explicit positional path.
        deploy_calls = [
            call for call in transport.calls if call[0] == "deploy_files"
        ]
        assert len(deploy_calls) == 1

    def test_multiple_things_requires_explicit_positional(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _seed_workspace(tmp_path)
        _seed_two_things(root)
        exit_code = cli.main(["deploy", "--workspace-dir", str(root)])
        assert exit_code == 2
        captured = capsys.readouterr()
        assert "multiple things" in captured.err
        # Both thing names should appear in the help text.
        assert "weather" in captured.err
        assert "heater" in captured.err

    def test_template_directory_does_not_count_as_a_thing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A workspace with only ``things/_template/`` deploys nothing.

        ``list_things()`` filters underscore-prefixed names so the
        starter template's ``_template/`` doesn't accidentally satisfy
        "exactly one thing".
        """
        root = _seed_workspace(tmp_path)
        template_dir = root / "things" / "_template"
        template_dir.mkdir(parents=True)
        (template_dir / "app.py").write_text("def run(): pass\n")

        exit_code = cli.main(["deploy", "--workspace-dir", str(root)])
        assert exit_code == 2
        captured = capsys.readouterr()
        assert "no things to deploy" in captured.err

    def test_explicit_positional_still_works_alongside_default(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Default kicks in only when names is empty — explicit always wins."""
        root = _seed_workspace(tmp_path)
        _seed_thing(root)

        transport = FakeTransport(execute_output="")
        monkeypatch.setattr(Device, "create_transport", lambda self: transport)

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root), "back-porch",
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        # Explicit positional → no "defaulting to ..." line.
        assert "defaulting to" not in captured.out


class TestDeployMultiThing:
    def test_two_things_with_boot_shim_ships_both(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        root = _seed_workspace(tmp_path)
        _seed_two_things(root)

        transport = FakeTransport(execute_output="")
        monkeypatch.setattr(Device, "create_transport", lambda self: transport)

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root),
            "--boot-shim", "weather", "heater",
        ])
        assert exit_code == 0
        deploy_calls = [call for call in transport.calls if call[0] == "deploy_files"]
        files, _entrypoint = deploy_calls[0][1]
        assert "/lib/things/weather/app.py" in files
        assert "/lib/things/heater/app.py" in files
        assert "/lib/things/weather/runtime_config.msgpack" in files
        assert "/lib/things/heater/runtime_config.msgpack" in files
        # First positional name is the default active.
        assert b'"weather"' in files["/active.py"]

    def test_active_flag_picks_non_first(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        root = _seed_workspace(tmp_path)
        _seed_two_things(root)

        transport = FakeTransport(execute_output="")
        monkeypatch.setattr(Device, "create_transport", lambda self: transport)

        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root),
            "--boot-shim", "--active", "heater",
            "weather", "heater",
        ])
        assert exit_code == 0
        deploy_calls = [call for call in transport.calls if call[0] == "deploy_files"]
        files, _entrypoint = deploy_calls[0][1]
        assert b'"heater"' in files["/active.py"]

    def test_multi_thing_without_boot_shim_exits_two(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Multi-thing deploy requires --boot-shim — flat layout would collide."""
        root = _seed_workspace(tmp_path)
        _seed_two_things(root)
        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root),
            "weather", "heater",
        ])
        assert exit_code == 2
        assert "requires --boot-shim" in capsys.readouterr().err

    def test_active_without_boot_shim_exits_two(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _seed_workspace(tmp_path)
        _seed_thing(root)
        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root),
            "--active", "back-porch", "back-porch",
        ])
        assert exit_code == 2
        assert "--active only applies with --boot-shim" in capsys.readouterr().err

    def test_active_not_in_names_exits_two(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _seed_workspace(tmp_path)
        _seed_two_things(root)
        exit_code = cli.main([
            "deploy", "--workspace-dir", str(root),
            "--boot-shim", "--active", "ghost",
            "weather", "heater",
        ])
        assert exit_code == 2
        assert "ghost" in capsys.readouterr().err


class TestSwitch:
    def test_ships_three_files(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        root = _seed_workspace(tmp_path)
        _seed_two_things(root)

        transport = FakeTransport(execute_output="")
        monkeypatch.setattr(Device, "create_transport", lambda self: transport)

        exit_code = cli.main([
            "switch", "--workspace-dir", str(root), "heater",
        ])
        assert exit_code == 0
        deploy_calls = [call for call in transport.calls if call[0] == "deploy_files"]
        files, entrypoint = deploy_calls[0][1]
        # Switch is just /code.py (or /main.py) + /active.py + msgpack.
        assert set(files) == {"/main.py", "/active.py", "/runtime_config.msgpack"}
        assert entrypoint == "/main.py"
        assert b'"heater"' in files["/active.py"]
        decoded = unpackb(files["/runtime_config.msgpack"])
        assert decoded["heater"]["token"] == "hot"

    def test_missing_thing_raises(self, tmp_path: Path) -> None:
        root = _seed_workspace(tmp_path)
        with pytest.raises(SystemExit) as caught:
            cli.main(["switch", "--workspace-dir", str(root), "ghost"])
        assert "ghost" in str(caught.value)

    def test_traceback_returns_exit_one(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _seed_workspace(tmp_path)
        _seed_two_things(root)
        transport = FakeTransport(
            execute_output=(
                "Traceback (most recent call last):\n"
                "  File \"/code.py\", line 1\n"
                "RuntimeError: switched-to-broken-thing\n"
            ),
        )
        monkeypatch.setattr(Device, "create_transport", lambda self: transport)
        exit_code = cli.main([
            "switch", "--workspace-dir", str(root), "heater",
        ])
        assert exit_code == 1
        assert "switched-to-broken-thing" in capsys.readouterr().err


class TestThings:
    def test_lists_workspace_things(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _seed_workspace(tmp_path)
        _seed_two_things(root)
        exit_code = cli.main(["things", "--workspace-dir", str(root)])
        assert exit_code == 0
        out = capsys.readouterr().out.splitlines()
        assert sorted(out) == ["heater", "weather"]

    def test_empty_workspace_prints_marker(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _seed_workspace(tmp_path)
        # things/ exists if any thing was seeded; without seeding it doesn't.
        # Either way list_things() returns [].
        exit_code = cli.main(["things", "--workspace-dir", str(root)])
        assert exit_code == 0
        assert "no things" in capsys.readouterr().out

    def test_skips_underscore_dirs(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """_template / leading-underscore dirs aren't shown as things."""
        root = _seed_workspace(tmp_path)
        _seed_thing(root, name="back-porch")
        (root / "things" / "_template").mkdir()
        (root / "things" / "_template" / "config.toml").write_text("\n")
        exit_code = cli.main(["things", "--workspace-dir", str(root)])
        assert exit_code == 0
        out = capsys.readouterr().out.splitlines()
        assert "_template" not in out
        assert "back-porch" in out


# ---------------------------------------------------------------------------
# demo  (Step 5 of beginner-onramp — built-in payload)
# ---------------------------------------------------------------------------


class TestDemo:
    """Built-in `chumicro-workspace demo` payload deploy."""

    def test_ships_demo_payload_through_fake_transport(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        root = _seed_workspace(tmp_path)

        transport = FakeTransport(execute_output="Hello from ChuMicro!\n")
        monkeypatch.setattr(Device, "create_transport", lambda self: transport)

        exit_code = cli.main(["demo", "--workspace-dir", str(root)])
        assert exit_code == 0

        deploy_calls = [
            call for call in transport.calls if call[0] == "deploy_files"
        ]
        assert len(deploy_calls) == 1
        files, entrypoint = deploy_calls[0][1]
        # MP runtime in the seed → /main.py.
        assert entrypoint == "/main.py"
        assert "/main.py" in files
        body = files["/main.py"].decode("utf-8")
        assert "Hello from ChuMicro" in body
        assert "demo complete" in body

    def test_prints_execute_output_to_user(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The captured execute output reaches stdout so the user
        sees the demo's prints."""
        root = _seed_workspace(tmp_path)

        transport = FakeTransport(
            execute_output="Hello from ChuMicro!\ndemo complete!\n",
        )
        monkeypatch.setattr(Device, "create_transport", lambda self: transport)

        exit_code = cli.main(["demo", "--workspace-dir", str(root)])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Hello from ChuMicro" in captured.out
        assert "demo complete" in captured.out

    def test_traceback_returns_exit_one(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Same failure-surfacing shape as `deploy`."""
        root = _seed_workspace(tmp_path)

        transport = FakeTransport(
            execute_output=(
                "Traceback (most recent call last):\n"
                "  File \"/main.py\", line 1\n"
                "RuntimeError: boom\n"
            ),
        )
        monkeypatch.setattr(Device, "create_transport", lambda self: transport)

        exit_code = cli.main(["demo", "--workspace-dir", str(root)])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "RuntimeError: boom" in captured.err

    def test_demo_payload_is_runtime_agnostic(self) -> None:
        """The baked-in payload uses no `board` / `machine` imports.

        Guards against a future regression where someone adds a
        hardware-touching line and the demo silently breaks on
        boards that don't expose the imported module.
        """
        from chumicro_workspace.cli import DEMO_PAYLOAD

        assert "import board" not in DEMO_PAYLOAD
        assert "import machine" not in DEMO_PAYLOAD
        assert "import digitalio" not in DEMO_PAYLOAD
        # Only stdlib imports allowed in the demo.
        assert "import time" in DEMO_PAYLOAD


# ---------------------------------------------------------------------------
# bootstrap  (Step 4 of beginner-onramp — end-to-end wizard)
# ---------------------------------------------------------------------------


class TestBootstrapHelpers:
    """Unit-level tests for the bootstrap helper functions."""

    def test_suggest_device_id_strips_with_chip_tail(self) -> None:
        from chumicro_deploy import DeviceImplementation
        from chumicro_workspace.cli import _suggest_device_id

        result = _suggest_device_id(DeviceImplementation(
            name="circuitpython",
            version="10.1.4",
            machine="Raspberry Pi Pico W with rp2040",
            uid="ABCD",
        ))
        assert result == "raspberry-pi-pico-w"

    def test_suggest_device_id_handles_blank_machine(self) -> None:
        from chumicro_deploy import DeviceImplementation
        from chumicro_workspace.cli import _suggest_device_id

        result = _suggest_device_id(DeviceImplementation(
            name="micropython", version="1.27.0", machine="", uid="",
        ))
        # Blank machine + non-empty runtime → use runtime name.
        assert result == "micropython"

    def test_suggest_device_id_falls_back_to_board(self) -> None:
        from chumicro_deploy import DeviceImplementation
        from chumicro_workspace.cli import _suggest_device_id

        result = _suggest_device_id(DeviceImplementation(
            name="", version="0.0.0", machine="!@#$%", uid="",
        ))
        assert result == "board"

    def test_resolve_bootstrap_port_explicit_wins(self) -> None:
        from chumicro_workspace.cli import _resolve_bootstrap_port

        result = _resolve_bootstrap_port("/dev/cu.fake")
        assert result == "/dev/cu.fake"

    def test_resolve_bootstrap_port_no_ports_returns_none(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from chumicro_workspace.cli import _resolve_bootstrap_port
        from serial.tools import list_ports

        monkeypatch.setattr(list_ports, "comports", lambda: [])
        result = _resolve_bootstrap_port(None)
        assert result is None

    def test_resolve_bootstrap_port_single_port_auto_picks(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from chumicro_workspace.cli import _resolve_bootstrap_port
        from serial.tools import list_ports

        class _FakePort:
            device = "/dev/cu.only"
            description = "Pi Pico W"

        monkeypatch.setattr(list_ports, "comports", lambda: [_FakePort()])
        result = _resolve_bootstrap_port(None)
        assert result == "/dev/cu.only"

    def test_resolve_bootstrap_port_multiple_ports_prompts(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from chumicro_workspace.cli import _resolve_bootstrap_port
        from serial.tools import list_ports

        class _Port:
            def __init__(self, device: str) -> None:
                self.device = device
                self.description = ""

        monkeypatch.setattr(
            list_ports,
            "comports",
            lambda: [_Port("/dev/cu.a"), _Port("/dev/cu.b")],
        )
        result = _resolve_bootstrap_port(None, prompt_func=lambda _: "2")
        assert result == "/dev/cu.b"

    def test_resolve_bootstrap_port_invalid_choice_returns_none(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from chumicro_workspace.cli import _resolve_bootstrap_port
        from serial.tools import list_ports

        class _Port:
            def __init__(self, device: str) -> None:
                self.device = device
                self.description = ""

        monkeypatch.setattr(
            list_ports,
            "comports",
            lambda: [_Port("/dev/cu.a"), _Port("/dev/cu.b")],
        )
        # Out-of-range numeric choice.
        result = _resolve_bootstrap_port(
            None, prompt_func=lambda _: "99",
        )
        assert result is None
        # Non-numeric choice.
        result = _resolve_bootstrap_port(
            None, prompt_func=lambda _: "garbage",
        )
        assert result is None

    def test_resolve_bootstrap_device_id_explicit_wins(self) -> None:
        from chumicro_workspace.cli import _resolve_bootstrap_device_id

        result = _resolve_bootstrap_device_id(
            "explicit", "suggested", prompt_func=lambda _: "ignored",
        )
        assert result == "explicit"

    def test_resolve_bootstrap_device_id_blank_uses_default(self) -> None:
        from chumicro_workspace.cli import _resolve_bootstrap_device_id

        result = _resolve_bootstrap_device_id(
            None, "suggested", prompt_func=lambda _: "  ",
        )
        assert result == "suggested"

    def test_resolve_bootstrap_device_id_uses_typed_value(self) -> None:
        from chumicro_workspace.cli import _resolve_bootstrap_device_id

        result = _resolve_bootstrap_device_id(
            None, "suggested", prompt_func=lambda _: "  porch  ",
        )
        assert result == "porch"


class TestBootstrapWizard:
    """End-to-end CLI tests for `chumicro-workspace bootstrap`."""

    def _seed(self, tmp_path: Path) -> Path:
        (tmp_path / "workspace.yml").write_text("defaults: {}\n")
        return tmp_path

    def test_full_flow_with_explicit_flags(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """All flags set → no prompts, full registration, summary printed."""
        root = self._seed(tmp_path)

        from chumicro_workspace import cli as workspace_cli
        from chumicro_workspace import onboarding

        def fake_inference(address: str, **_kw):
            return onboarding.RuntimeInferenceResult(
                info=_fake_probe_info(
                    runtime="micropython",
                    machine="Raspberry Pi Pico W with rp2040",
                    version="1.27.0",
                ),
                runtime="micropython",
                transport_used="micropython",
            )

        monkeypatch.setattr(
            workspace_cli, "probe_with_runtime_inference", fake_inference,
        )
        monkeypatch.setattr(
            onboarding, "probe_with_runtime_inference", fake_inference,
        )

        exit_code = cli.main([
            "bootstrap", "--workspace-dir", str(root),
            "--port", "/dev/cu.fake",
            "--device-id", "pico",
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "probing /dev/cu.fake" in captured.out
        assert "runtime: micropython 1.27.0" in captured.out
        assert "registered pico at /dev/cu.fake" in captured.out
        # Next-steps summary shows all three pointers.
        assert "new <thing-name>" in captured.out
        assert "deploy" in captured.out
        assert "repl" in captured.out

        body = (root / "devices.yml").read_text()
        assert "pico" in body
        assert "/dev/cu.fake" in body
        assert "firmware_version: 1.27.0" in body

    def test_inference_failure_prints_diagnosis(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = self._seed(tmp_path)

        from chumicro_workspace import cli as workspace_cli
        from chumicro_workspace import onboarding

        def fake_inference(address: str, **_kw):
            return onboarding.RuntimeInferenceResult(
                info=None, runtime=None, transport_used=None,
                last_exception=OSError("could not open port /dev/cu.x"),
            )

        monkeypatch.setattr(
            workspace_cli, "probe_with_runtime_inference", fake_inference,
        )
        monkeypatch.setattr(
            onboarding, "probe_with_runtime_inference", fake_inference,
        )
        monkeypatch.setattr(onboarding, "_UF2_MOUNT_SEARCH_PATHS", {})

        # detect_board_state runs its own probe — stub it.
        import chumicro_deploy
        monkeypatch.setattr(
            chumicro_deploy,
            "probe_device",
            lambda _d: (_ for _ in ()).throw(
                OSError("could not open port /dev/cu.x"),
            ),
        )

        exit_code = cli.main([
            "bootstrap", "--workspace-dir", str(root),
            "--port", "/dev/cu.x",
            "--device-id", "pico",
        ])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "auto-detect failed" in captured.err
        # Diagnosis next-steps suggest discover/replug for SERIAL_UNREACHABLE.
        assert "discover" in captured.err

    def test_old_firmware_warning_does_not_block(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = self._seed(tmp_path)

        from chumicro_workspace import cli as workspace_cli
        from chumicro_workspace import onboarding

        def fake_inference(address: str, **_kw):
            return onboarding.RuntimeInferenceResult(
                info=_fake_probe_info(
                    runtime="micropython", version="1.26.0",
                ),
                runtime="micropython",
                transport_used="micropython",
            )

        monkeypatch.setattr(
            workspace_cli, "probe_with_runtime_inference", fake_inference,
        )
        monkeypatch.setattr(
            onboarding, "probe_with_runtime_inference", fake_inference,
        )

        exit_code = cli.main([
            "bootstrap", "--workspace-dir", str(root),
            "--port", "/dev/cu.x",
            "--device-id", "pico",
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        # Warning emitted to stderr but registration proceeded.
        assert "1.26.0" in captured.err
        assert "1.27.0" in captured.err  # the floor
        body = (root / "devices.yml").read_text()
        assert "pico" in body

    def test_duplicate_device_id_returns_one(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Bootstrapping a second board onto an existing id should fail
        cleanly, not silently overwrite."""
        root = self._seed(tmp_path)
        # Pre-seed devices.yml with the conflicting id.
        (root / "devices.yml").write_text(
            "defaults: {}\n"
            "devices:\n"
            "  - id: pico\n"
            "    runtime: micropython\n"
            "    address: /dev/cu.old\n",
        )

        from chumicro_workspace import cli as workspace_cli
        from chumicro_workspace import onboarding

        def fake_inference(address: str, **_kw):
            return onboarding.RuntimeInferenceResult(
                info=_fake_probe_info(version="1.27.0"),
                runtime="micropython",
                transport_used="micropython",
            )

        monkeypatch.setattr(
            workspace_cli, "probe_with_runtime_inference", fake_inference,
        )
        monkeypatch.setattr(
            onboarding, "probe_with_runtime_inference", fake_inference,
        )

        exit_code = cli.main([
            "bootstrap", "--workspace-dir", str(root),
            "--port", "/dev/cu.new",
            "--device-id", "pico",
        ])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "already exists" in captured.err

    def test_with_demo_chains_into_deploy(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = self._seed(tmp_path)

        from chumicro_workspace import cli as workspace_cli
        from chumicro_workspace import onboarding

        def fake_inference(address: str, **_kw):
            return onboarding.RuntimeInferenceResult(
                info=_fake_probe_info(version="1.27.0"),
                runtime="micropython",
                transport_used="micropython",
            )

        monkeypatch.setattr(
            workspace_cli, "probe_with_runtime_inference", fake_inference,
        )
        monkeypatch.setattr(
            onboarding, "probe_with_runtime_inference", fake_inference,
        )

        # Stub the deploy transport so the demo step doesn't need
        # real hardware.
        transport = FakeTransport(
            execute_output="Hello from ChuMicro!\ndemo complete!\n",
        )
        monkeypatch.setattr(Device, "create_transport", lambda self: transport)

        exit_code = cli.main([
            "bootstrap", "--workspace-dir", str(root),
            "--port", "/dev/cu.fake",
            "--device-id", "pico",
            "--with-demo",
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "registered pico" in captured.out
        # The demo's execute output reaches stdout.
        assert "Hello from ChuMicro" in captured.out


# ---------------------------------------------------------------------------
# probe
# ---------------------------------------------------------------------------


class TestProbe:
    def test_prints_implementation_marker(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _seed_workspace(tmp_path)

        import chumicro_deploy
        from chumicro_deploy import DeviceImplementation

        class _Info:
            implementation = DeviceImplementation(
                name="micropython", version="1.26.0", machine="Lolin S2", uid="ABCD",
            )
            board_id = "lolin_s2"
            uid = "ABCD"

        monkeypatch.setattr(chumicro_deploy, "probe_device", lambda _device: _Info())
        exit_code = cli.main(["probe", "--workspace-dir", str(root)])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "runtime: micropython" in out
        assert "version: 1.26.0" in out
        assert "uid: ABCD" in out

    def test_no_implementation_returns_one(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _seed_workspace(tmp_path)
        import chumicro_deploy

        class _Info:
            implementation = None
            board_id = ""
            uid = ""

        monkeypatch.setattr(chumicro_deploy, "probe_device", lambda _device: _Info())
        exit_code = cli.main(["probe", "--workspace-dir", str(root)])
        assert exit_code == 1
        assert "no implementation marker" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# repl
# ---------------------------------------------------------------------------


class TestRepl:
    def test_interactive_path(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        root = _seed_workspace(tmp_path)
        captured: dict[str, Any] = {}

        def fake_interactive(device: Device) -> int:
            captured["device"] = device
            return 0

        import chumicro_repl
        monkeypatch.setattr(chumicro_repl, "interactive", fake_interactive)
        exit_code = cli.main(["repl", "--workspace-dir", str(root)])
        assert exit_code == 0
        assert captured["device"].address == "/dev/cu.fake"

    def test_tail_path(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        root = _seed_workspace(tmp_path)
        captured: dict[str, Any] = {}

        def fake_tail(device: Device, seconds: float, **kwargs: Any) -> int:
            captured["seconds"] = seconds
            captured["fail_on_traceback"] = kwargs["fail_on_traceback"]
            return 0

        import chumicro_repl
        monkeypatch.setattr(chumicro_repl, "tail", fake_tail)
        exit_code = cli.main([
            "repl", "--workspace-dir", str(root),
            "--tail", "1.5", "--no-fail-on-traceback",
        ])
        assert exit_code == 0
        assert captured["seconds"] == 1.5
        assert captured["fail_on_traceback"] is False


# ---------------------------------------------------------------------------
# install-firmware / upgrade-firmware
# ---------------------------------------------------------------------------


class TestInstallFirmware:
    def test_invokes_flash_firmware(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        root = _seed_workspace(tmp_path)
        captured: dict[str, Any] = {}

        def fake_flash(url: str, device: Device, **kwargs: Any) -> None:
            captured["url"] = url
            captured["device_address"] = device.address
            captured["method"] = kwargs["reflash_method"]

        import chumicro_deploy
        monkeypatch.setattr(chumicro_deploy, "flash_firmware", fake_flash)
        exit_code = cli.main([
            "install-firmware", "--workspace-dir", str(root),
            "--url", "https://example.com/fw.uf2", "--method", "uf2",
        ])
        assert exit_code == 0
        assert captured["url"] == "https://example.com/fw.uf2"
        assert captured["method"] == "uf2"

    def test_upgrade_firmware_uses_same_handler(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """upgrade-firmware aliases install-firmware — same flash flow."""
        root = _seed_workspace(tmp_path)
        called: list[str] = []

        def fake_flash(url: str, _device: Device, **_kwargs: Any) -> None:
            called.append(url)

        import chumicro_deploy
        monkeypatch.setattr(chumicro_deploy, "flash_firmware", fake_flash)
        exit_code = cli.main([
            "upgrade-firmware", "--workspace-dir", str(root),
            "--url", "https://example.com/fw.bin", "--method", "esptool",
        ])
        assert exit_code == 0
        assert called == ["https://example.com/fw.bin"]

    def test_url_omitted_derives_from_device_entry(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Slice 5: --url optional, derived from hardware.firmware_source."""
        (tmp_path / "workspace.yml").write_text("defaults: {}\n")
        (tmp_path / "devices.yml").write_text(
            "defaults:\n"
            "  micropython: pico\n"
            "devices:\n"
            "  - id: pico\n"
            "    runtime: micropython\n"
            "    address: /dev/cu.fake\n"
            "    hardware:\n"
            "      firmware_source: https://my-mirror/firmware.bin\n"
        )

        captured: list[str] = []

        def fake_flash(url: str, _device: Device, **_kwargs: Any) -> None:
            captured.append(url)

        import chumicro_deploy
        monkeypatch.setattr(chumicro_deploy, "flash_firmware", fake_flash)
        exit_code = cli.main([
            "install-firmware", "--workspace-dir", str(tmp_path),
            "--method", "esptool",
        ])
        assert exit_code == 0
        assert captured == ["https://my-mirror/firmware.bin"]
        assert "resolved https://my-mirror/firmware.bin" in capsys.readouterr().out

    def test_url_omitted_unknown_device_returns_two(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """No --url + no --device id → can't derive, exit 2."""
        root = _seed_workspace(tmp_path)
        # Default-resolution lands on lolin-s2, which has no
        # hardware block → derive raises UnresolvableFirmwareError.
        exit_code = cli.main([
            "install-firmware", "--workspace-dir", str(root),
            "--method", "uf2",
        ])
        assert exit_code == 2
        captured_stderr = capsys.readouterr().err
        assert "install-firmware" in captured_stderr

    def test_url_omitted_unresolvable_returns_two(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A device with no resolvable hardware fields → exit 2 with a hint."""
        (tmp_path / "workspace.yml").write_text("defaults: {}\n")
        (tmp_path / "devices.yml").write_text(
            "devices:\n"
            "  - id: orphan\n"
            "    runtime: micropython\n"
            "    address: /dev/cu.fake\n"
        )
        exit_code = cli.main([
            "install-firmware", "--workspace-dir", str(tmp_path),
            "--device", "orphan", "--method", "esptool",
        ])
        assert exit_code == 2
        assert "hardware.machine" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# test
# ---------------------------------------------------------------------------


class TestTestCommand:
    def test_shells_out_to_pytest(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        root = _seed_workspace(tmp_path)
        recorded: dict[str, Any] = {}

        def fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            recorded["args"] = args
            recorded["cwd"] = kwargs.get("cwd")
            return subprocess.CompletedProcess(args, 0)

        monkeypatch.setattr(cli.subprocess, "run", fake_run)
        exit_code = cli.main([
            "test", "--workspace-dir", str(root), "--", "-k", "sanity",
        ])
        assert exit_code == 0
        assert recorded["args"] == [
            sys.executable, "-m", "pytest", "--", "-k", "sanity",
        ]
        assert recorded["cwd"] == root


# ---------------------------------------------------------------------------
# Workspace-not-found
# ---------------------------------------------------------------------------


class TestWorkspaceResolution:
    def test_missing_workspace_yields_systemexit(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as caught:
            cli.main(["devices", "--workspace-dir", str(tmp_path)])
        assert "workspace.yml" in str(caught.value)


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("command", "slice_marker"),
    [
        ("sim", "sim runner"),
        ("env", "environments"),
        ("use", "environments"),
        ("sync", "superseded by `chumicro-workspace update`"),
        ("upgrade", "superseded by `chumicro-workspace update --ref"),
    ],
)
def test_stub_commands_exit_two_with_message(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    command: str,
    slice_marker: str,
) -> None:
    """Each stubbed command must report its planned slice and exit 2."""
    _seed_workspace(tmp_path)
    exit_code = cli.main([command, "--workspace-dir", str(tmp_path)])
    assert exit_code == 2
    captured_stderr = capsys.readouterr().err
    assert "not implemented yet" in captured_stderr
    assert slice_marker in captured_stderr


# ---------------------------------------------------------------------------
# add-device  (Slice 3 — three-zone YAML writer wired in)
# ---------------------------------------------------------------------------


def _fake_probe_info(
    runtime: str = "micropython",
    machine: str = "Lolin S2",
    uid: str = "ABCD1234",
    board_id: str = "lolin_s2",
    version: str = "1.27.0",
):
    """Return an object that mimics chumicro_deploy.probe_device's return.

    Default version is at the supported floor for ``micropython`` so
    tests that don't care about firmware support don't trip the
    Decision 0039 warning path.  Tests that exercise the floor pass
    a lower or runtime-specific *version*.
    """
    from chumicro_deploy import DeviceImplementation

    class _Info:
        implementation = DeviceImplementation(
            name=runtime, version=version, machine=machine, uid=uid,
        )

    info = _Info()
    info.board_id = board_id
    info.uid = uid
    return info


class TestAddDevice:
    def test_writes_new_entry_to_devices_yml(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Start with no devices.yml — typical fresh-workspace case.
        (tmp_path / "workspace.yml").write_text("defaults: {}\n")
        import chumicro_deploy
        monkeypatch.setattr(
            chumicro_deploy, "probe_device", lambda _device: _fake_probe_info(),
        )
        exit_code = cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.fake", "--runtime", "micropython",
            "--description", "Test board", "lolin-s2",
        ])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "registered lolin-s2" in out
        body = (tmp_path / "devices.yml").read_text()
        assert "lolin-s2" in body
        assert "/dev/cu.fake" in body
        assert "ABCD1234" in body  # hardware-once UID landed
        assert "Test board" in body  # user-owned description

    def test_re_register_without_force_fails(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        (tmp_path / "workspace.yml").write_text("defaults: {}\n")
        import chumicro_deploy
        monkeypatch.setattr(
            chumicro_deploy, "probe_device", lambda _device: _fake_probe_info(),
        )

        first = cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.fake", "--runtime", "micropython", "lolin-s2",
        ])
        assert first == 0
        capsys.readouterr()

        second = cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.fake", "--runtime", "micropython", "lolin-s2",
        ])
        assert second == 1
        assert "already exists" in capsys.readouterr().err

    def test_re_register_with_force_refreshes_address(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (tmp_path / "workspace.yml").write_text("defaults: {}\n")
        import chumicro_deploy
        monkeypatch.setattr(
            chumicro_deploy, "probe_device", lambda _device: _fake_probe_info(),
        )
        cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.old", "--runtime", "micropython", "lolin-s2",
        ])
        # Re-probe with --force at a different port.
        result = cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.new", "--runtime", "micropython",
            "--force", "lolin-s2",
        ])
        assert result == 0
        body = (tmp_path / "devices.yml").read_text()
        assert "/dev/cu.new" in body
        assert "/dev/cu.old" not in body

    def test_force_swap_with_changed_uid_succeeds(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """--force allows hardware.uid to change ('I swapped boards')."""
        (tmp_path / "workspace.yml").write_text("defaults: {}\n")
        import chumicro_deploy

        first_info = _fake_probe_info(uid="ORIGINAL")
        monkeypatch.setattr(chumicro_deploy, "probe_device", lambda _d: first_info)
        cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.x", "--runtime", "micropython", "lolin",
        ])

        second_info = _fake_probe_info(uid="DIFFERENT")
        monkeypatch.setattr(chumicro_deploy, "probe_device", lambda _d: second_info)
        result = cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.x", "--runtime", "micropython",
            "--force", "lolin",
        ])
        assert result == 0
        assert "DIFFERENT" in (tmp_path / "devices.yml").read_text()

    def test_probe_no_marker_returns_one(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        (tmp_path / "workspace.yml").write_text("defaults: {}\n")

        class _NoMarker:
            implementation = None
            board_id = ""
            uid = ""

        import chumicro_deploy
        from chumicro_workspace import onboarding

        monkeypatch.setattr(chumicro_deploy, "probe_device", lambda _d: _NoMarker())
        # Force "no UF2 drive on the dev box" so the diagnosis lands on
        # NO_PROBE_RESPONSE (the esptool branch) rather than UF2_BOOTLOADER.
        monkeypatch.setattr(onboarding, "_UF2_MOUNT_SEARCH_PATHS", {})
        exit_code = cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.x", "--runtime", "micropython", "lolin",
        ])
        assert exit_code == 1
        captured_stderr = capsys.readouterr().err
        assert "did not return implementation" in captured_stderr
        # Slice 4 onboarding diagnosis follows on subsequent lines.
        assert "esptool" in captured_stderr.lower()

    def test_probe_raises_emits_onboarding_diagnosis(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A probe exception falls through to detect_board_state for help."""
        (tmp_path / "workspace.yml").write_text("defaults: {}\n")

        def raising_probe(_device):
            raise OSError("could not open port /dev/cu.absent")

        import chumicro_deploy
        from chumicro_workspace import onboarding

        monkeypatch.setattr(chumicro_deploy, "probe_device", raising_probe)
        monkeypatch.setattr(onboarding, "_UF2_MOUNT_SEARCH_PATHS", {})
        exit_code = cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.absent", "--runtime", "micropython", "lolin",
        ])
        assert exit_code == 1
        captured_stderr = capsys.readouterr().err
        assert "probe failed" in captured_stderr
        assert "discover" in captured_stderr  # SERIAL_UNREACHABLE recommendation

    def test_uf2_bootloader_message_when_drive_present(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A board in UF2 bootloader gets the install-firmware --method uf2 hint."""
        (tmp_path / "workspace.yml").write_text("defaults: {}\n")
        # Stage a fake UF2 mount under tmp_path.
        uf2_mount_root = tmp_path / "Volumes"
        uf2_mount_root.mkdir()
        drive = uf2_mount_root / "RPI-RP2"
        drive.mkdir()
        (drive / "INFO_UF2.TXT").write_text("UF2 Bootloader\n")

        class _NoMarker:
            implementation = None
            board_id = ""
            uid = ""

        import chumicro_deploy
        from chumicro_workspace import onboarding

        monkeypatch.setattr(chumicro_deploy, "probe_device", lambda _d: _NoMarker())
        monkeypatch.setattr(
            onboarding,
            "_UF2_MOUNT_SEARCH_PATHS",
            {"darwin": [uf2_mount_root], "linux": [uf2_mount_root], "win32": [uf2_mount_root]},
        )
        exit_code = cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.x", "--runtime", "micropython", "lolin",
        ])
        assert exit_code == 1
        captured_stderr = capsys.readouterr().err
        assert "UF2 bootloader" in captured_stderr
        assert "install-firmware" in captured_stderr

    def test_user_comments_in_devices_yml_survive_add(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The headline value of the round-trip writer."""
        (tmp_path / "workspace.yml").write_text("defaults: {}\n")
        (tmp_path / "devices.yml").write_text(
            "# House sensors — keep this file checked in.\n"
            "defaults:\n"
            "  micropython: existing  # default for deploy commands\n"
            "devices:\n"
            "  - id: existing\n"
            "    runtime: micropython\n"
            "    address: /dev/cu.preset\n"
        )

        import chumicro_deploy
        monkeypatch.setattr(
            chumicro_deploy, "probe_device", lambda _d: _fake_probe_info(),
        )
        cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.fake", "--runtime", "micropython", "lolin-s2",
        ])
        body = (tmp_path / "devices.yml").read_text()
        assert "# House sensors" in body
        assert "# default for deploy commands" in body
        assert "lolin-s2" in body  # new entry made it in


# ---------------------------------------------------------------------------
# add-device — firmware-version floor (Decision 0039)
# ---------------------------------------------------------------------------


class TestAddDeviceFirmwareFloor:
    def _seed(self, tmp_path: Path) -> None:
        (tmp_path / "workspace.yml").write_text("defaults: {}\n")

    def test_supported_firmware_emits_no_warning(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        self._seed(tmp_path)
        import chumicro_deploy

        monkeypatch.setattr(
            chumicro_deploy,
            "probe_device",
            lambda _d: _fake_probe_info(version="1.27.0"),
        )
        exit_code = cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.x", "--runtime", "micropython", "pico",
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "warning" not in captured.err.lower()

    def test_old_firmware_warns_but_succeeds(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Below-floor firmware: warn-not-block per Decision 0039."""
        self._seed(tmp_path)
        import chumicro_deploy

        monkeypatch.setattr(
            chumicro_deploy,
            "probe_device",
            lambda _d: _fake_probe_info(version="1.26.0"),
        )
        exit_code = cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.x", "--runtime", "micropython", "pico",
        ])
        assert exit_code == 0  # warn, do not block
        captured = capsys.readouterr()
        assert "1.26.0" in captured.err
        assert "1.27.0" in captured.err
        assert "install-firmware" in captured.err

    def test_unknown_runtime_warns(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        self._seed(tmp_path)
        import chumicro_deploy

        monkeypatch.setattr(
            chumicro_deploy,
            "probe_device",
            lambda _d: _fake_probe_info(runtime="cpython", version="3.13.0"),
        )
        exit_code = cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.x", "--runtime", "micropython", "host",
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "tested matrix" in captured.err

    def test_firmware_version_persisted_to_devices_yml(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The probed-always firmware_version field should land on disk."""
        self._seed(tmp_path)
        import chumicro_deploy

        monkeypatch.setattr(
            chumicro_deploy,
            "probe_device",
            lambda _d: _fake_probe_info(version="1.27.0"),
        )
        cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.x", "--runtime", "micropython", "pico",
        ])
        body = (tmp_path / "devices.yml").read_text()
        assert "firmware_version: 1.27.0" in body

    def test_force_reprobe_refreshes_firmware_version(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An upgrade out of band → re-probe with --force should overwrite."""
        self._seed(tmp_path)
        import chumicro_deploy

        monkeypatch.setattr(
            chumicro_deploy,
            "probe_device",
            lambda _d: _fake_probe_info(version="1.26.0"),
        )
        cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.x", "--runtime", "micropython", "pico",
        ])
        body_before = (tmp_path / "devices.yml").read_text()
        assert "firmware_version: 1.26.0" in body_before

        monkeypatch.setattr(
            chumicro_deploy,
            "probe_device",
            lambda _d: _fake_probe_info(version="1.27.0"),
        )
        result = cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.x", "--runtime", "micropython",
            "--force", "pico",
        ])
        assert result == 0
        body_after = (tmp_path / "devices.yml").read_text()
        assert "firmware_version: 1.27.0" in body_after
        assert "firmware_version: 1.26.0" not in body_after


# ---------------------------------------------------------------------------
# add-device — runtime auto-inference (Step 3 of beginner-onramp)
# ---------------------------------------------------------------------------


class TestAddDeviceRuntimeInference:
    """`--runtime` is optional; when omitted, runtime is probed."""

    def _seed(self, tmp_path: Path) -> None:
        (tmp_path / "workspace.yml").write_text("defaults: {}\n")

    def test_omitted_runtime_is_inferred(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        self._seed(tmp_path)
        from chumicro_workspace import onboarding

        # Fake the inference helper to return a CP probe.
        def fake_inference(address: str, **_kw):
            return onboarding.RuntimeInferenceResult(
                info=_fake_probe_info(
                    runtime="circuitpython", version="10.1.4",
                ),
                runtime="circuitpython",
                transport_used="circuitpython",
            )

        monkeypatch.setattr(
            onboarding, "probe_with_runtime_inference", fake_inference,
        )
        # Also rebind the name imported into cli.py.
        monkeypatch.setattr(cli, "probe_with_runtime_inference", fake_inference)

        exit_code = cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.x", "feather",
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "auto-detected runtime = circuitpython" in captured.out
        body = (tmp_path / "devices.yml").read_text()
        assert "runtime: circuitpython" in body
        assert "firmware_version: 10.1.4" in body

    def test_explicit_runtime_skips_inference(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Passing --runtime takes the existing path; inference is bypassed."""
        self._seed(tmp_path)
        called = {"inference": False, "probe": False}

        from chumicro_workspace import onboarding

        def fake_inference(*_args, **_kw):
            called["inference"] = True
            raise AssertionError("inference should not run when --runtime set")

        monkeypatch.setattr(
            onboarding, "probe_with_runtime_inference", fake_inference,
        )
        monkeypatch.setattr(cli, "probe_with_runtime_inference", fake_inference)

        import chumicro_deploy

        def fake_probe(_device):
            called["probe"] = True
            return _fake_probe_info(version="1.27.0")

        monkeypatch.setattr(chumicro_deploy, "probe_device", fake_probe)

        exit_code = cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.x", "--runtime", "micropython", "pico",
        ])
        assert exit_code == 0
        assert called["probe"] is True
        assert called["inference"] is False

    def test_inference_failure_falls_through_to_diagnosis(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """No transport produced a marker → exit 1 with a helpful diagnosis."""
        self._seed(tmp_path)
        from chumicro_workspace import onboarding

        def fake_inference(address: str, **_kw):
            return onboarding.RuntimeInferenceResult(
                info=None,
                runtime=None,
                transport_used=None,
                last_exception=OSError("could not open port /dev/cu.x"),
            )

        monkeypatch.setattr(
            onboarding, "probe_with_runtime_inference", fake_inference,
        )
        monkeypatch.setattr(cli, "probe_with_runtime_inference", fake_inference)
        # Force the diagnosis branch onto SERIAL_UNREACHABLE — no UF2 drive.
        monkeypatch.setattr(onboarding, "_UF2_MOUNT_SEARCH_PATHS", {})

        # detect_board_state will run its own probe — stub it so we don't
        # actually try to open the port.
        import chumicro_deploy
        monkeypatch.setattr(
            chumicro_deploy,
            "probe_device",
            lambda _d: (_ for _ in ()).throw(
                OSError("could not open port /dev/cu.x"),
            ),
        )

        exit_code = cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.x", "feather",
        ])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "auto-detect failed" in captured.err
        # Diagnosis next-steps suggest discover/replug for SERIAL_UNREACHABLE.
        assert "discover" in captured.err

    def test_inference_completes_but_returns_no_marker(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Probe ran cleanly on every transport but no implementation marker.

        last_exception stays None so the message reads "no runtime
        returned a probe marker" instead of pointing at an exception.
        """
        self._seed(tmp_path)
        from chumicro_workspace import onboarding

        def fake_inference(address: str, **_kw):
            return onboarding.RuntimeInferenceResult(
                info=None,
                runtime=None,
                transport_used=None,
                last_exception=None,
            )

        monkeypatch.setattr(
            onboarding, "probe_with_runtime_inference", fake_inference,
        )
        monkeypatch.setattr(cli, "probe_with_runtime_inference", fake_inference)
        monkeypatch.setattr(onboarding, "_UF2_MOUNT_SEARCH_PATHS", {})

        import chumicro_deploy

        class _NoMarker:
            implementation = None
            board_id = ""
            uid = ""

        monkeypatch.setattr(
            chumicro_deploy, "probe_device", lambda _d: _NoMarker(),
        )

        exit_code = cli.main([
            "add-device", "--workspace-dir", str(tmp_path),
            "--address", "/dev/cu.x", "feather",
        ])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "no runtime returned a probe marker" in captured.err


# ---------------------------------------------------------------------------
# rename  (Slice 3 — wired to thing dirs + devices.yml)
# ---------------------------------------------------------------------------


class TestRename:
    def test_thing_renames_directory(self, tmp_path: Path) -> None:
        root = _seed_workspace(tmp_path)
        _seed_thing(root, "old-name")
        exit_code = cli.main([
            "rename", "--workspace-dir", str(root),
            "--thing", "old-name", "new-name",
        ])
        assert exit_code == 0
        assert not (root / "things" / "old-name").exists()
        assert (root / "things" / "new-name" / "code.py").exists()

    def test_thing_missing_returns_one(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _seed_workspace(tmp_path)
        exit_code = cli.main([
            "rename", "--workspace-dir", str(root),
            "--thing", "ghost", "spook",
        ])
        assert exit_code == 1
        assert "not found" in capsys.readouterr().err

    def test_thing_target_exists_returns_one(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _seed_workspace(tmp_path)
        _seed_thing(root, "alpha")
        _seed_thing(root, "beta")
        exit_code = cli.main([
            "rename", "--workspace-dir", str(root),
            "--thing", "alpha", "beta",
        ])
        assert exit_code == 1
        assert "already exists" in capsys.readouterr().err

    def test_device_rename_rewrites_id_and_default(self, tmp_path: Path) -> None:
        root = _seed_workspace(tmp_path)
        # Seed devices.yml has 'lolin-s2' as default.
        exit_code = cli.main([
            "rename", "--workspace-dir", str(root),
            "--device", "lolin-s2", "back-porch",
        ])
        assert exit_code == 0
        body = (root / "devices.yml").read_text()
        assert "lolin-s2" not in body
        assert "back-porch" in body

    def test_device_missing_returns_one(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        root = _seed_workspace(tmp_path)
        exit_code = cli.main([
            "rename", "--workspace-dir", str(root),
            "--device", "ghost", "spook",
        ])
        assert exit_code == 1
        assert "not found" in capsys.readouterr().err

    def test_device_target_exists_returns_one(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        (tmp_path / "workspace.yml").write_text("defaults: {}\n")
        (tmp_path / "devices.yml").write_text(
            "devices:\n"
            "  - id: alpha\n"
            "    runtime: micropython\n"
            "    address: /a\n"
            "  - id: beta\n"
            "    runtime: circuitpython\n"
            "    address: /b\n"
        )
        exit_code = cli.main([
            "rename", "--workspace-dir", str(tmp_path),
            "--device", "alpha", "beta",
        ])
        assert exit_code == 1
        assert "already exists" in capsys.readouterr().err

    def test_neither_thing_nor_device_specified_argparse_errors(
        self,
        tmp_path: Path,
    ) -> None:
        """Argparse's mutually-exclusive group raises SystemExit on missing input."""
        root = _seed_workspace(tmp_path)
        with pytest.raises(SystemExit):
            cli.main(["rename", "--workspace-dir", str(root)])
