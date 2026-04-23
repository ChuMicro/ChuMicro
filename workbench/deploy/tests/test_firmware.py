"""Tests for resolve_firmware_url."""

from __future__ import annotations

import pytest
from chumicro_deploy import UnresolvedFirmwareError, resolve_firmware_url


class TestCircuitpython:
    def test_formats_canonical_adafruit_url(self):
        url = resolve_firmware_url(
            "raspberry_pi_pico_w", "circuitpython", "10.1.4"
        )
        assert url == (
            "https://downloads.circuitpython.org/bin/raspberry_pi_pico_w/"
            "en_US/adafruit-circuitpython-raspberry_pi_pico_w-en_US-10.1.4.uf2"
        )

    def test_supports_prerelease_version(self):
        url = resolve_firmware_url(
            "adafruit_feather_esp32s3", "circuitpython", "10.2.0-rc.0"
        )
        assert url.endswith("10.2.0-rc.0.uf2")

    def test_custom_language_override(self):
        url = resolve_firmware_url(
            "raspberry_pi_pico_w",
            "circuitpython",
            "10.1.4",
            language="de_DE",
        )
        assert "/de_DE/" in url
        assert "de_DE-10.1.4.uf2" in url


class TestMicropython:
    def test_raises_with_roadmap_message(self):
        with pytest.raises(UnresolvedFirmwareError, match="MicroPython"):
            resolve_firmware_url(
                "RPI_PICO_W", "micropython", "1.26.0"
            )


class TestValidation:
    def test_empty_board_id_raises(self):
        with pytest.raises(UnresolvedFirmwareError, match="board_id"):
            resolve_firmware_url("", "circuitpython", "10.1.4")

    def test_empty_version_raises(self):
        with pytest.raises(UnresolvedFirmwareError, match="version"):
            resolve_firmware_url("raspberry_pi_pico_w", "circuitpython", "")

    def test_unknown_runtime_raises(self):
        with pytest.raises(UnresolvedFirmwareError, match="Unsupported runtime"):
            resolve_firmware_url("foo", "zephyr", "1.0")
