"""Tests for discover_config_loaders and the entry-point registration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from chumicro_deploy import Device
from chumicro_deploy.config import (
    CONFIG_LOADERS_ENTRY_POINT_GROUP,
    discover_config_loaders,
)


class _FakeEntryPoint:
    """Duck-typed stand-in for importlib.metadata.EntryPoint."""

    def __init__(self, name: str, target: Any) -> None:
        self.name = name
        self._target = target

    def load(self) -> Any:
        return self._target


def _my_format_loader(path: Path | str, *, device_id: str | None = None) -> Device:  # noqa: ARG001
    """Example third-party loader."""
    return Device(transport="micropython", address="/dev/my-format-loaded")


class TestDiscoverConfigLoaders:
    def test_always_includes_chumicro_builtin(self) -> None:
        loaders = discover_config_loaders()
        assert "chumicro" in loaders

    def test_registers_third_party_loaders(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from importlib import metadata

        def fake_entry_points(**kwargs):
            if kwargs.get("group") == CONFIG_LOADERS_ENTRY_POINT_GROUP:
                return [_FakeEntryPoint("myformat", _my_format_loader)]
            return []

        monkeypatch.setattr(metadata, "entry_points", fake_entry_points)
        loaders = discover_config_loaders()
        assert "myformat" in loaders
        assert loaders["myformat"] is _my_format_loader
        assert "chumicro" in loaders  # builtin still present

    def test_third_party_cannot_shadow_builtin(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from importlib import metadata

        def fake_entry_points(**kwargs):
            if kwargs.get("group") == CONFIG_LOADERS_ENTRY_POINT_GROUP:
                return [_FakeEntryPoint("chumicro", _my_format_loader)]
            return []

        monkeypatch.setattr(metadata, "entry_points", fake_entry_points)
        with pytest.raises(ValueError, match="reserved for the built-in"):
            discover_config_loaders()

    def test_builtin_loads_chumicro_yaml(self, tmp_path: Path) -> None:
        yaml_path = tmp_path / "devices.yml"
        yaml_path.write_text(
            "defaults:\n"
            "  micropython: mp\n"
            "  deploy_mode: ram\n"
            "devices:\n"
            "  - id: mp\n"
            "    runtime: micropython\n"
            "    address: /dev/ttyACM0\n"
            "    serial_baudrate: 115200\n"
        )
        loaders = discover_config_loaders()
        device = loaders["chumicro"](yaml_path)
        assert device.transport == "micropython"
        assert device.address == "/dev/ttyACM0"
