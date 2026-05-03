"""Tests for the Device facade."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from chumicro_deploy import (
    CircuitpythonTransport,
    Device,
    MicropythonTransport,
)


class TestConstruction:
    """Validation in __post_init__ and defaults."""

    def test_minimum_valid_construction(self):
        device = Device(transport="circuitpython", address="/dev/cu.usbmodem1")
        assert device.transport == "circuitpython"
        assert device.address == "/dev/cu.usbmodem1"

    def test_defaults(self):
        device = Device(transport="micropython", address="/dev/ttyACM0")
        assert device.baudrate == 115200
        # Decision 0047 — flash is the default; RAM is opt-in.
        assert device.deploy_mode == "flash"
        assert device.circuitpy_drive_path is None
        assert device.entrypoint_name is None
        assert device.resource_prefix == "/lib"

    def test_custom_fields(self):
        device = Device(
            transport="circuitpython",
            address="COM7",
            baudrate=9600,
            deploy_mode="flash",
            circuitpy_drive_path=Path("/Volumes/CIRCUITPY"),
            entrypoint_name="app.py",
            resource_prefix="/pkg",
        )
        assert device.baudrate == 9600
        assert device.deploy_mode == "flash"
        assert device.circuitpy_drive_path == Path("/Volumes/CIRCUITPY")
        assert device.entrypoint_name == "app.py"
        assert device.resource_prefix == "/pkg"

    def test_rejects_unknown_transport(self):
        with pytest.raises(ValueError, match="Unsupported transport"):
            Device(transport="zephyr", address="/dev/null")

    def test_rejects_unknown_deploy_mode(self):
        with pytest.raises(ValueError, match="Unsupported deploy_mode"):
            Device(
                transport="circuitpython",
                address="/dev/null",
                deploy_mode="rom",
            )

    def test_frozen(self):
        device = Device(transport="circuitpython", address="/dev/cu.usbmodem1")
        with pytest.raises(FrozenInstanceError):
            device.address = "/dev/other"  # type: ignore[misc]


class TestEffectiveEntrypoint:
    """Runtime-aware entrypoint default resolution."""

    def test_circuitpython_default(self):
        device = Device(transport="circuitpython", address="/dev/cu.x")
        assert device.effective_entrypoint == "code.py"

    def test_micropython_default(self):
        device = Device(transport="micropython", address="/dev/ttyACM0")
        assert device.effective_entrypoint == "main.py"

    def test_explicit_override(self):
        device = Device(
            transport="circuitpython",
            address="/dev/cu.x",
            entrypoint_name="app.py",
        )
        assert device.effective_entrypoint == "app.py"


class TestFromDict:
    def test_minimum_required(self):
        device = Device.from_dict(
            {"transport": "circuitpython", "address": "/dev/cu.x"},
        )
        assert device.transport == "circuitpython"
        assert device.address == "/dev/cu.x"
        assert device.baudrate == 115200
        # Decision 0047 — flash is the default; RAM is opt-in.
        assert device.deploy_mode == "flash"
        assert device.circuitpy_drive_path is None

    def test_all_fields(self):
        device = Device.from_dict(
            {
                "transport": "circuitpython",
                "address": "COM7",
                "baudrate": 230400,
                "deploy_mode": "flash",
                "circuitpy_drive_path": "/Volumes/CIRCUITPY",
                "entrypoint_name": "app.py",
                "resource_prefix": "/pkg",
            },
        )
        assert device.baudrate == 230400
        assert device.deploy_mode == "flash"
        assert device.circuitpy_drive_path == Path("/Volumes/CIRCUITPY")
        assert device.entrypoint_name == "app.py"
        assert device.resource_prefix == "/pkg"

    def test_ignores_unknown_keys(self):
        device = Device.from_dict(
            {
                "transport": "micropython",
                "address": "/dev/x",
                "id": "mp-board-1",
                "description": "extra metadata",
            },
        )
        assert device.transport == "micropython"

    def test_missing_transport_raises(self):
        with pytest.raises(ValueError, match="transport"):
            Device.from_dict({"address": "/dev/x"})

    def test_missing_address_raises(self):
        with pytest.raises(ValueError, match="address"):
            Device.from_dict({"transport": "micropython"})

    def test_empty_string_drive_path_treated_as_none(self):
        device = Device.from_dict(
            {
                "transport": "circuitpython",
                "address": "/dev/x",
                "circuitpy_drive_path": "",
            },
        )
        assert device.circuitpy_drive_path is None

    def test_validation_propagates(self):
        with pytest.raises(ValueError, match="Unsupported transport"):
            Device.from_dict({"transport": "zephyr", "address": "/dev/x"})


class TestCreateTransport:
    """create_transport branches on runtime and maps deploy_mode."""

    def test_micropython_ram_maps_to_mount(self):
        device = Device(
            transport="micropython", address="/dev/ttyACM0", deploy_mode="ram"
        )
        transport = device.create_transport()
        assert isinstance(transport, MicropythonTransport)
        assert transport.mode == "mount"
        assert transport.address == "/dev/ttyACM0"

    def test_micropython_flash_maps_to_copy(self):
        device = Device(
            transport="micropython", address="/dev/ttyACM0", deploy_mode="flash"
        )
        transport = device.create_transport()
        assert isinstance(transport, MicropythonTransport)
        assert transport.mode == "copy"

    def test_circuitpython_ram_keeps_ram_label(self):
        device = Device(
            transport="circuitpython", address="/dev/cu.x", deploy_mode="ram"
        )
        transport = device.create_transport()
        assert isinstance(transport, CircuitpythonTransport)
        assert transport.mode == "ram"

    def test_circuitpython_flash_keeps_flash_label(self):
        device = Device(
            transport="circuitpython",
            address="/dev/cu.x",
            deploy_mode="flash",
            circuitpy_drive_path=Path("/Volumes/CIRCUITPY"),
        )
        transport = device.create_transport()
        assert isinstance(transport, CircuitpythonTransport)
        assert transport.mode == "flash"

    def test_circuitpython_passes_baudrate_and_drive_path(self):
        drive = Path("/Volumes/CIRCUITPY")
        device = Device(
            transport="circuitpython",
            address="/dev/cu.x",
            baudrate=230400,
            deploy_mode="flash",
            circuitpy_drive_path=drive,
        )
        transport = device.create_transport()
        assert isinstance(transport, CircuitpythonTransport)
        assert transport.baudrate == 230400
        # ``Device`` stores the drive as a ``Path`` for typed
        # downstream consumers; ``CircuitpythonTransport`` keeps the
        # ``str`` shape it inherited from pyserial / mpremote.
        # ``Device.create_transport`` does the conversion.
        assert transport.circuitpy_drive_path == str(drive)
