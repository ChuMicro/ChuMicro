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


# ---------------------------------------------------------------------------
# add-device  (Slice 3 — three-zone YAML writer wired in)
# ---------------------------------------------------------------------------


def _fake_probe_info(
    runtime: str = "micropython",
    machine: str = "Lolin S2",
    uid: str = "ABCD1234",
    board_id: str = "lolin_s2",
):
    """Return an object that mimics chumicro_deploy.probe_device's return."""
    from chumicro_deploy import DeviceImplementation

    class _Info:
        implementation = DeviceImplementation(
            name=runtime, version="1.26.0", machine=machine, uid=uid,
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
        from chumicro_workspace_runtime import onboarding

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
        from chumicro_workspace_runtime import onboarding

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
        from chumicro_workspace_runtime import onboarding

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
