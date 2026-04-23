"""Tests for the chumicro-deploy CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from chumicro_deploy import DeviceImplementation, DeviceInfo
from chumicro_deploy.cli import build_parser, main


class TestParser:
    def test_requires_subcommand(self) -> None:
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])

    def test_probe_parses_required_args(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            ["probe", "--transport", "micropython", "--address", "/dev/x"],
        )
        assert args.command == "probe"
        assert args.transport == "micropython"
        assert args.address == "/dev/x"
        assert args.json_output is False

    def test_flash_parses_required_args(self) -> None:
        parser = build_parser()
        args = parser.parse_args([
            "flash",
            "--transport", "micropython",
            "--address", "/dev/x",
            "--url", "https://example/fw.bin",
            "--method", "esptool",
            "--erase",
            "--offset", "0x1000",
        ])
        assert args.url == "https://example/fw.bin"
        assert args.method == "esptool"
        assert args.erase is True
        assert args.offset == "0x1000"

    def test_flash_defaults_offset_zero(self) -> None:
        parser = build_parser()
        args = parser.parse_args([
            "flash",
            "--transport", "circuitpython",
            "--address", "/dev/x",
            "--url", "https://example/fw.uf2",
            "--method", "uf2",
        ])
        assert args.offset == "0x0"
        assert args.erase is False

    def test_deploy_requires_source(self) -> None:
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([
                "deploy",
                "--transport", "micropython",
                "--address", "/dev/x",
                "--entrypoint", "/main.py",
            ])


class TestCommandProbe:
    def test_text_output(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    ) -> None:
        expected = DeviceInfo(
            implementation=DeviceImplementation(
                name="micropython", version="1.28.0", machine="rp2040",
            ),
            board_id="",
            uid="",
        )
        monkeypatch.setattr(
            "chumicro_deploy.cli.probe_device", lambda _device: expected,
        )
        exit_code = main([
            "probe", "--transport", "micropython", "--address", "/dev/x",
        ])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "runtime: micropython" in out
        assert "version: 1.28.0" in out
        assert "machine: rp2040" in out

    def test_json_output(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(
            "chumicro_deploy.cli.probe_device",
            lambda _device: DeviceInfo(
                implementation=DeviceImplementation(
                    name="circuitpython", version="10.2.0", machine="pico_w",
                ),
            ),
        )
        exit_code = main([
            "probe",
            "--transport", "circuitpython",
            "--address", "/dev/x",
            "--json",
        ])
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["runtime"] == "circuitpython"
        assert payload["version"] == "10.2.0"

    def test_no_marker_returns_nonzero(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "chumicro_deploy.cli.probe_device",
            lambda _device: DeviceInfo(implementation=None),
        )
        exit_code = main([
            "probe", "--transport", "micropython", "--address", "/dev/x",
        ])
        assert exit_code == 1


class TestCommandFlash:
    def test_forwards_flags_to_flash_firmware(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, Any] = {}

        def fake_flash(url, device, **kwargs):  # noqa: ANN001
            captured["url"] = url
            captured["device"] = device
            captured.update(kwargs)

        monkeypatch.setattr("chumicro_deploy.cli.flash_firmware", fake_flash)

        exit_code = main([
            "flash",
            "--transport", "micropython",
            "--address", "/dev/cu.usbmodem01",
            "--url", "https://example/fw.bin",
            "--method", "esptool",
            "--erase",
            "--offset", "0x1000",
            "--non-interactive",
        ])
        assert exit_code == 0
        assert captured["url"] == "https://example/fw.bin"
        assert captured["reflash_method"] == "esptool"
        assert captured["erase_flash"] is True
        assert captured["flash_offset"] == "0x1000"
        assert captured["interactive"] is False


class TestCommandResolveFirmwareUrl:
    def test_prints_canonical_cp_url(
        self, capsys: pytest.CaptureFixture[str],
    ) -> None:
        exit_code = main([
            "resolve-firmware-url",
            "--board-id", "raspberry_pi_pico_w",
            "--runtime", "circuitpython",
            "--version", "10.1.4",
        ])
        assert exit_code == 0
        out = capsys.readouterr().out.strip()
        assert out.startswith("https://downloads.circuitpython.org/")
        assert "10.1.4.uf2" in out


class TestCommandDeploy:
    def test_directory_source(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        source_dir = tmp_path / "app"
        source_dir.mkdir()
        (source_dir / "main.py").write_text("print('x')")

        captured: dict[str, Any] = {}

        class FakeDeployer:
            def __init__(self, device):  # noqa: ANN001
                captured["device"] = device

            def deploy(self, source, **kwargs):  # noqa: ANN001
                captured["source"] = source
                captured["kwargs"] = kwargs
                from chumicro_deploy import DeployResult
                return DeployResult(success=True, execute_output="ok\n")

        monkeypatch.setattr("chumicro_deploy.deployer.Deployer", FakeDeployer)

        exit_code = main([
            "deploy",
            "--transport", "micropython",
            "--address", "/dev/x",
            "--directory", str(source_dir),
            "--entrypoint", "/main.py",
        ])
        assert exit_code == 0

    def test_file_map_source(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        file_map_path = tmp_path / "files.json"
        file_map_path.write_text(json.dumps({"/code.py": "print('y')"}))

        class FakeDeployer:
            def __init__(self, device):  # noqa: ANN001
                pass

            def deploy(self, source, **kwargs):  # noqa: ANN001
                from chumicro_deploy import DeployResult
                return DeployResult(success=True, execute_output="y\n")

        monkeypatch.setattr("chumicro_deploy.deployer.Deployer", FakeDeployer)

        exit_code = main([
            "deploy",
            "--transport", "circuitpython",
            "--address", "/dev/x",
            "--file-map", str(file_map_path),
            "--entrypoint", "/code.py",
        ])
        assert exit_code == 0

    def test_deployer_failure_returns_nonzero(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        source_dir = tmp_path / "app"
        source_dir.mkdir()
        (source_dir / "main.py").write_text("1/0")

        class FakeDeployer:
            def __init__(self, device):  # noqa: ANN001
                pass

            def deploy(self, source, **kwargs):  # noqa: ANN001
                from chumicro_deploy import DeployResult
                return DeployResult(
                    success=False,
                    execute_output="",
                    traceback="ZeroDivisionError",
                )

        monkeypatch.setattr("chumicro_deploy.deployer.Deployer", FakeDeployer)

        exit_code = main([
            "deploy",
            "--transport", "micropython",
            "--address", "/dev/x",
            "--directory", str(source_dir),
            "--entrypoint", "/main.py",
        ])
        assert exit_code == 1
