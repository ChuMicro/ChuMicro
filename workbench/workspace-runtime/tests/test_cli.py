"""Tests for the chumicro-workspace-runtime CLI dispatcher.

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
from chumicro_workspace_runtime import cli


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
        "setup", "new", "add-device", "probe", "discover", "devices",
        "deploy", "sim", "test", "repl", "env", "use", "rename",
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
        assert "nothing to install yet" in capsys.readouterr().out

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


# ---------------------------------------------------------------------------
# new
# ---------------------------------------------------------------------------


class TestNew:
    def test_copies_template_to_named_dir(self, tmp_path: Path) -> None:
        root = _seed_workspace(tmp_path)
        template = root / "things" / "_template"
        template.mkdir(parents=True)
        (template / "code.py").write_text("# template\n")
        (template / "config.toml").write_text("[app]\n")

        exit_code = cli.main(
            ["new", "--workspace-dir", str(root), "kitchen-sensor"],
        )
        assert exit_code == 0

        target = root / "things" / "kitchen-sensor"
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
        ("add-device", "Slice 3"),
        ("rename", "Slice 3"),
        ("sim", "sim runner"),
        ("env", "environments"),
        ("use", "environments"),
        ("sync", "Phase 4b"),
        ("upgrade", "Phase 4b"),
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
