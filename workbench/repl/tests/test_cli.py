"""Tests for the ``chumicro-repl`` argparse-driven CLI."""

from __future__ import annotations

import argparse
from unittest.mock import patch

import pytest
from chumicro_repl import cli


class TestParser:
    """``build_parser`` wires up every flag the CLI promises."""

    def test_help_does_not_raise(self):
        parser = cli.build_parser()
        # SystemExit on -h is fine — we want to confirm the parser
        # builds at all, including all subparsers.
        with pytest.raises(SystemExit):
            parser.parse_args(["-h"])

    def test_address_only_default_mode(self):
        parser = cli.build_parser()
        args = parser.parse_args(["--address", "/dev/cu.x"])
        assert args.address == "/dev/cu.x"
        assert args.transport is None
        assert args.tail is None
        assert args.fail_on_traceback is True

    def test_tail_flag_is_float(self):
        parser = cli.build_parser()
        args = parser.parse_args(["--address", "/dev/cu.x", "--tail", "2.5"])
        assert args.tail == pytest.approx(2.5)

    def test_no_fail_flag_inverts_default(self):
        parser = cli.build_parser()
        args = parser.parse_args([
            "--address", "/dev/cu.x",
            "--tail", "1",
            "--no-fail-on-traceback",
        ])
        assert args.fail_on_traceback is False


class TestDeviceFromArgs:
    """``_device_from_args`` resolves to a Device, devices.yml entry, or path."""

    def test_bare_address_string_returned(self):
        args = argparse.Namespace(
            transport=None,
            address="/dev/cu.bare",
            baudrate=115200,
            devices_file=None,
            device_id=None,
            runtime=None,
            devices_format="default",
        )
        result = cli._device_from_args(args)
        assert result == "/dev/cu.bare"

    def test_transport_plus_address_builds_device(self):
        args = argparse.Namespace(
            transport="circuitpython",
            address="/dev/cu.x",
            baudrate=115200,
            devices_file=None,
            device_id=None,
            runtime=None,
            devices_format="default",
        )
        result = cli._device_from_args(args)
        from chumicro_deploy import Device

        assert isinstance(result, Device)
        assert result.transport == "circuitpython"

    def test_missing_address_raises(self):
        args = argparse.Namespace(
            transport=None,
            address=None,
            baudrate=115200,
            devices_file=None,
            device_id=None,
            runtime=None,
            devices_format="default",
        )
        with pytest.raises(SystemExit):
            cli._device_from_args(args)


_DEVICES_YML_BOTH = """\
defaults:
  micropython: mp-board
  circuitpython: cp-board
  deploy_mode: ram
devices:
  - id: mp-board
    runtime: micropython
    address: /dev/cu.mp
    serial_baudrate: 115200
  - id: cp-board
    runtime: circuitpython
    address: /dev/cu.cp
    serial_baudrate: 115200
"""

_DEVICES_YML_MP_ONLY = """\
defaults:
  micropython: solo-board
  deploy_mode: ram
devices:
  - id: solo-board
    runtime: micropython
    address: /dev/cu.solo
    serial_baudrate: 115200
"""


class TestDevicesFileFlow:
    """End-to-end ``--devices-file`` resolution against a real YAML."""

    def test_devices_file_with_explicit_device(self, tmp_path):
        yaml_path = tmp_path / "devices.yml"
        yaml_path.write_text(_DEVICES_YML_BOTH)
        parser = cli.build_parser()
        args = parser.parse_args([
            "--devices-file", str(yaml_path),
            "--device", "cp-board",
        ])
        device = cli._device_from_args(args)
        assert device.transport == "circuitpython"
        assert device.address == "/dev/cu.cp"

    def test_devices_file_with_runtime_picks_circuitpython(self, tmp_path):
        yaml_path = tmp_path / "devices.yml"
        yaml_path.write_text(_DEVICES_YML_BOTH)
        parser = cli.build_parser()
        args = parser.parse_args([
            "--devices-file", str(yaml_path),
            "--runtime", "circuitpython",
        ])
        device = cli._device_from_args(args)
        assert device.transport == "circuitpython"
        assert device.address == "/dev/cu.cp"

    def test_devices_file_with_runtime_picks_micropython(self, tmp_path):
        yaml_path = tmp_path / "devices.yml"
        yaml_path.write_text(_DEVICES_YML_BOTH)
        parser = cli.build_parser()
        args = parser.parse_args([
            "--devices-file", str(yaml_path),
            "--runtime", "micropython",
        ])
        device = cli._device_from_args(args)
        assert device.transport == "micropython"
        assert device.address == "/dev/cu.mp"

    def test_devices_file_no_flags_falls_back_to_single_default(self, tmp_path):
        # Only one runtime configured — the loader's existing
        # single-default fallback resolves it without --runtime.
        yaml_path = tmp_path / "devices.yml"
        yaml_path.write_text(_DEVICES_YML_MP_ONLY)
        parser = cli.build_parser()
        args = parser.parse_args(["--devices-file", str(yaml_path)])
        device = cli._device_from_args(args)
        assert device.transport == "micropython"
        assert device.address == "/dev/cu.solo"

    def test_devices_file_no_flags_with_both_defaults_raises(self, tmp_path):
        # Both runtimes configured + no --device + no --runtime —
        # the loader raises and the CLI surfaces the SystemExit.
        yaml_path = tmp_path / "devices.yml"
        yaml_path.write_text(_DEVICES_YML_BOTH)
        parser = cli.build_parser()
        args = parser.parse_args(["--devices-file", str(yaml_path)])
        with pytest.raises(ValueError, match="Multiple or no default"):
            cli._device_from_args(args)

    def test_device_and_runtime_together_systemexit(self, tmp_path):
        yaml_path = tmp_path / "devices.yml"
        yaml_path.write_text(_DEVICES_YML_BOTH)
        parser = cli.build_parser()
        args = parser.parse_args([
            "--devices-file", str(yaml_path),
            "--device", "mp-board",
            "--runtime", "circuitpython",
        ])
        with pytest.raises(SystemExit, match="mutually exclusive"):
            cli._device_from_args(args)

    def test_runtime_with_third_party_format_systemexits(self, tmp_path, monkeypatch):
        yaml_path = tmp_path / "devices.yml"
        yaml_path.write_text(_DEVICES_YML_BOTH)

        def third_party_loader(path, *, device_id=None):
            return f"loaded:{path}:{device_id}"

        monkeypatch.setattr(
            "chumicro_deploy.config.discover_config_loaders",
            lambda: {
                "default": __import__(
                    "chumicro_deploy.config.default", fromlist=["load_devices_yml"],
                ).load_devices_yml,
                "custom": third_party_loader,
            },
        )
        parser = cli.build_parser()
        args = parser.parse_args([
            "--devices-file", str(yaml_path),
            "--devices-format", "custom",
            "--runtime", "circuitpython",
        ])
        with pytest.raises(SystemExit, match="--runtime only works"):
            cli._device_from_args(args)


class TestMainDispatch:
    """``main`` routes to the tail or interactive subcommand."""

    def test_tail_mode_invokes_tail_function(self):
        # Patch the lazy-imported tail to return a known ExitCode.
        with patch("chumicro_repl._follow.tail") as fake_tail:
            from chumicro_repl import ExitCode

            fake_tail.return_value = ExitCode.OK
            result = cli.main([
                "--address", "/dev/cu.x",
                "--tail", "0.1",
            ])
            assert result == 0
            fake_tail.assert_called_once()
            args, kwargs = fake_tail.call_args
            assert args[0] == "/dev/cu.x"
            assert args[1] == pytest.approx(0.1)
            assert kwargs["fail_on_traceback"] is True

    def test_tail_mode_returns_traceback_exit_code(self):
        with patch("chumicro_repl._follow.tail") as fake_tail:
            from chumicro_repl import ExitCode

            fake_tail.return_value = ExitCode.TRACEBACK_DETECTED
            result = cli.main([
                "--address", "/dev/cu.x",
                "--tail", "0.1",
            ])
            assert result == int(ExitCode.TRACEBACK_DETECTED)

    def test_interactive_mode_invokes_interactive_function(self):
        with patch("chumicro_repl.tui.interactive") as fake_interactive:
            fake_interactive.return_value = 0
            result = cli.main(["--address", "/dev/cu.x"])
            assert result == 0
            fake_interactive.assert_called_once_with("/dev/cu.x")

    def test_no_fail_propagates_to_tail(self):
        with patch("chumicro_repl._follow.tail") as fake_tail:
            from chumicro_repl import ExitCode

            fake_tail.return_value = ExitCode.OK
            cli.main([
                "--address", "/dev/cu.x",
                "--tail", "0.1",
                "--no-fail-on-traceback",
            ])
            _, kwargs = fake_tail.call_args
            assert kwargs["fail_on_traceback"] is False
