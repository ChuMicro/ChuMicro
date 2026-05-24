"""Tests for chumicro_pytest_device.fixtures.mosquitto."""

import shutil
from pathlib import Path
from unittest.mock import patch

from chumicro_pytest_device.fixtures.mosquitto import start_mosquitto_broker


def test_start_mosquitto_returns_none_when_binary_missing(tmp_path: Path):
    """`start_mosquitto_broker` returns None when `mosquitto` is not on PATH."""
    with patch.object(shutil, "which", return_value=None):
        assert start_mosquitto_broker("127.0.0.1", tmp_path) is None


def test_start_mosquitto_writes_broker_config_when_binary_present(tmp_path: Path):
    """`start_mosquitto_broker` writes a broker.conf with the bind host + port before exec."""
    # Patch shutil.which to lie about mosquitto being present, then
    # short-circuit the subprocess.Popen so we don't actually exec.
    # The contract under test is: config gets written, port is allocated.
    with patch.object(shutil, "which", return_value="/usr/bin/mosquitto"), \
         patch("chumicro_pytest_device.fixtures.mosquitto.subprocess.Popen") as popen, \
         patch(
             "chumicro_pytest_device.fixtures.mosquitto.wait_until_listening",
             return_value=False,
         ):
        # wait_until_listening=False makes the function terminate the fake
        # process and return None — but config.write_text already ran.
        popen.return_value.wait.return_value = 0
        result = start_mosquitto_broker("127.0.0.1", tmp_path)
        assert result is None

    config_path = tmp_path / "broker.conf"
    assert config_path.exists()
    config_body = config_path.read_text()
    assert "127.0.0.1" in config_body
    assert "allow_anonymous true" in config_body
    assert "persistence false" in config_body
