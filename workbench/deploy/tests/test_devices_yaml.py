"""Tests for the three-zone devices.yml round-trip writer."""

from pathlib import Path

import pytest
from chumicro_deploy.config.devices_yaml import (
    DeviceAlreadyExistsError,
    DeviceNotFoundError,
    DevicesYamlError,
    HardwareOverwriteError,
    add_device,
    dump_devices,
    find_device,
    list_device_ids,
    load_devices,
    rename_device,
    set_runtime_default,
    update_device_address,
    update_device_firmware_version,
    update_device_hardware,
)

# ---------------------------------------------------------------------------
# load_devices
# ---------------------------------------------------------------------------


class TestLoadDevices:
    def test_missing_file_returns_empty_map(self, tmp_path: Path) -> None:
        result = load_devices(tmp_path / "absent.yml")
        assert dict(result) == {}

    def test_empty_file_returns_empty_map(self, tmp_path: Path) -> None:
        path = tmp_path / "devices.yml"
        path.write_text("")
        assert dict(load_devices(path)) == {}

    def test_top_level_list_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "devices.yml"
        path.write_text("- not\n- a\n- mapping\n")
        with pytest.raises(DevicesYamlError):
            load_devices(path)

    def test_returns_data(self, tmp_path: Path) -> None:
        path = tmp_path / "devices.yml"
        path.write_text(
            "defaults:\n"
            "  micropython: pico\n"
            "devices:\n"
            "  - id: pico\n"
            "    runtime: micropython\n"
            "    address: /dev/cu.fake\n"
        )
        data = load_devices(path)
        assert data["defaults"]["micropython"] == "pico"
        assert data["devices"][0]["id"] == "pico"


# ---------------------------------------------------------------------------
# Round-trip preservation — the headline property
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_top_level_comments_survive(self, tmp_path: Path) -> None:
        original = (
            "# Workspace devices file (edit by hand or via add-device).\n"
            "defaults:\n"
            "  micropython: pico\n"
            "devices:\n"
            "  - id: pico\n"
            "    runtime: micropython\n"
            "    address: /dev/cu.fake\n"
        )
        path = tmp_path / "devices.yml"
        path.write_text(original)
        dump_devices(load_devices(path), path)
        assert "# Workspace devices file" in path.read_text()

    def test_inline_comments_survive(self, tmp_path: Path) -> None:
        path = tmp_path / "devices.yml"
        path.write_text(
            "defaults:\n"
            "  micropython: pico  # picked at first add-device\n"
            "devices:\n"
            "  - id: pico\n"
            "    runtime: micropython\n"
            "    address: /dev/cu.fake\n"
        )
        dump_devices(load_devices(path), path)
        assert "# picked at first add-device" in path.read_text()

    def test_key_order_preserved(self, tmp_path: Path) -> None:
        """User-chosen field order survives rather than getting alphabetized."""
        path = tmp_path / "devices.yml"
        path.write_text(
            "devices:\n"
            "  - id: pico\n"
            "    description: Front porch sensor\n"
            "    runtime: micropython\n"
            "    address: /dev/cu.fake\n"
        )
        dump_devices(load_devices(path), path)
        round_tripped = path.read_text()
        # description must still come before runtime + address.
        description_index = round_tripped.index("description")
        runtime_index = round_tripped.index("runtime")
        address_index = round_tripped.index("address")
        assert description_index < runtime_index < address_index


# ---------------------------------------------------------------------------
# dump_devices — atomic write
# ---------------------------------------------------------------------------


class TestDumpDevices:
    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        target = tmp_path / "nested" / "deeper" / "devices.yml"
        data = load_devices(tmp_path / "absent.yml")
        add_device(
            data,
            device_id="pico",
            runtime="micropython",
            address="/dev/cu.fake",
        )
        dump_devices(data, target)
        assert target.exists()

    def test_atomic_no_temp_file_left_behind(self, tmp_path: Path) -> None:
        path = tmp_path / "devices.yml"
        data = load_devices(path)
        add_device(
            data,
            device_id="pico",
            runtime="micropython",
            address="/dev/cu.fake",
        )
        dump_devices(data, path)
        # Only the final file should be present.
        siblings = sorted(child.name for child in tmp_path.iterdir())
        assert siblings == ["devices.yml"]


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


class TestLookups:
    def test_find_device_returns_entry(self, tmp_path: Path) -> None:
        data = load_devices(tmp_path / "x.yml")
        add_device(data, device_id="alpha", runtime="micropython", address="/a")
        add_device(data, device_id="beta", runtime="circuitpython", address="/b")
        assert find_device(data, "alpha")["address"] == "/a"
        assert find_device(data, "beta")["address"] == "/b"

    def test_find_device_returns_none_when_missing(self, tmp_path: Path) -> None:
        data = load_devices(tmp_path / "x.yml")
        assert find_device(data, "ghost") is None

    def test_list_device_ids_preserves_order(self, tmp_path: Path) -> None:
        data = load_devices(tmp_path / "x.yml")
        add_device(data, device_id="zulu", runtime="micropython", address="/z")
        add_device(data, device_id="alpha", runtime="circuitpython", address="/a")
        assert list_device_ids(data) == ["zulu", "alpha"]


# ---------------------------------------------------------------------------
# add_device
# ---------------------------------------------------------------------------


class TestAddDevice:
    def test_creates_required_keys(self, tmp_path: Path) -> None:
        data = load_devices(tmp_path / "x.yml")
        add_device(
            data,
            device_id="pico",
            runtime="micropython",
            address="/dev/cu.fake",
        )
        entry = find_device(data, "pico")
        assert entry["id"] == "pico"
        assert entry["runtime"] == "micropython"
        assert entry["address"] == "/dev/cu.fake"

    def test_writes_optional_user_fields(self, tmp_path: Path) -> None:
        data = load_devices(tmp_path / "x.yml")
        add_device(
            data,
            device_id="pico",
            runtime="micropython",
            address="/a",
            description="Garage sensor",
            deploy_mode="flash",
            serial_baudrate=115200,
            circuitpy_drive_path="/Volumes/CIRCUITPY",
        )
        entry = find_device(data, "pico")
        assert entry["description"] == "Garage sensor"
        assert entry["deploy_mode"] == "flash"
        assert entry["serial_baudrate"] == 115200
        assert entry["circuitpy_drive_path"] == "/Volumes/CIRCUITPY"

    def test_writes_hardware_block(self, tmp_path: Path) -> None:
        data = load_devices(tmp_path / "x.yml")
        add_device(
            data,
            device_id="pico",
            runtime="micropython",
            address="/a",
            hardware={"uid": "ABCD1234", "machine": "Pi Pico W"},
        )
        entry = find_device(data, "pico")
        assert entry["hardware"]["uid"] == "ABCD1234"
        assert entry["hardware"]["machine"] == "Pi Pico W"

    def test_no_hardware_block_when_not_supplied(self, tmp_path: Path) -> None:
        data = load_devices(tmp_path / "x.yml")
        add_device(
            data,
            device_id="pico",
            runtime="micropython",
            address="/a",
        )
        entry = find_device(data, "pico")
        assert "hardware" not in entry

    def test_seeds_runtime_default_on_first_entry(self, tmp_path: Path) -> None:
        data = load_devices(tmp_path / "x.yml")
        add_device(data, device_id="pico", runtime="micropython", address="/a")
        assert data["defaults"]["micropython"] == "pico"

    def test_does_not_clobber_existing_default(self, tmp_path: Path) -> None:
        path = tmp_path / "x.yml"
        path.write_text(
            "defaults:\n  micropython: existing-default\n"
            "devices:\n  - id: existing-default\n"
            "    runtime: micropython\n"
            "    address: /old\n"
        )
        data = load_devices(path)
        add_device(data, device_id="newer", runtime="micropython", address="/new")
        # Default stays pinned to whoever was already there.
        assert data["defaults"]["micropython"] == "existing-default"

    def test_set_default_false_skips_default_seed(self, tmp_path: Path) -> None:
        data = load_devices(tmp_path / "x.yml")
        add_device(
            data,
            device_id="pico",
            runtime="micropython",
            address="/a",
            set_default=False,
        )
        assert "micropython" not in data.get("defaults", {})

    def test_duplicate_id_raises(self, tmp_path: Path) -> None:
        data = load_devices(tmp_path / "x.yml")
        add_device(data, device_id="pico", runtime="micropython", address="/a")
        with pytest.raises(DeviceAlreadyExistsError):
            add_device(
                data, device_id="pico", runtime="micropython", address="/b",
            )


# ---------------------------------------------------------------------------
# update_device_address — probed-always (silent)
# ---------------------------------------------------------------------------


class TestUpdateAddress:
    def test_overwrites_silently(self, tmp_path: Path) -> None:
        data = load_devices(tmp_path / "x.yml")
        add_device(
            data,
            device_id="pico",
            runtime="micropython",
            address="/dev/cu.old",
        )
        update_device_address(data, "pico", "/dev/cu.new")
        assert find_device(data, "pico")["address"] == "/dev/cu.new"

    def test_missing_device_raises(self, tmp_path: Path) -> None:
        data = load_devices(tmp_path / "x.yml")
        with pytest.raises(DeviceNotFoundError):
            update_device_address(data, "ghost", "/x")


# ---------------------------------------------------------------------------
# update_device_firmware_version — probed-always (silent)
# ---------------------------------------------------------------------------


class TestUpdateFirmwareVersion:
    def test_overwrites_silently(self, tmp_path: Path) -> None:
        data = load_devices(tmp_path / "x.yml")
        add_device(
            data,
            device_id="pico",
            runtime="micropython",
            address="/a",
            firmware_version="1.26.0",
        )
        update_device_firmware_version(data, "pico", "1.27.0")
        assert find_device(data, "pico")["firmware_version"] == "1.27.0"

    def test_writes_when_missing(self, tmp_path: Path) -> None:
        """A device added before Decision 0039 has no firmware_version yet."""
        data = load_devices(tmp_path / "x.yml")
        add_device(data, device_id="pico", runtime="micropython", address="/a")
        update_device_firmware_version(data, "pico", "1.27.0")
        assert find_device(data, "pico")["firmware_version"] == "1.27.0"

    def test_missing_device_raises(self, tmp_path: Path) -> None:
        data = load_devices(tmp_path / "x.yml")
        with pytest.raises(DeviceNotFoundError):
            update_device_firmware_version(data, "ghost", "1.27.0")


class TestAddDeviceFirmwareVersion:
    def test_firmware_version_lands_in_entry(self, tmp_path: Path) -> None:
        data = load_devices(tmp_path / "x.yml")
        add_device(
            data,
            device_id="pico",
            runtime="micropython",
            address="/a",
            firmware_version="1.27.0",
        )
        assert find_device(data, "pico")["firmware_version"] == "1.27.0"

    def test_omitted_firmware_version_is_absent(self, tmp_path: Path) -> None:
        data = load_devices(tmp_path / "x.yml")
        add_device(data, device_id="pico", runtime="micropython", address="/a")
        assert "firmware_version" not in find_device(data, "pico")


# ---------------------------------------------------------------------------
# update_device_hardware — hardware-once (prompts on overwrite)
# ---------------------------------------------------------------------------


class TestUpdateHardware:
    def test_writes_unset_fields(self, tmp_path: Path) -> None:
        data = load_devices(tmp_path / "x.yml")
        add_device(data, device_id="pico", runtime="micropython", address="/a")
        update_device_hardware(data, "pico", {"uid": "ABCD"})
        assert find_device(data, "pico")["hardware"]["uid"] == "ABCD"

    def test_same_value_is_idempotent(self, tmp_path: Path) -> None:
        """Re-probe of an unchanged board should be a clean no-op."""
        data = load_devices(tmp_path / "x.yml")
        add_device(
            data,
            device_id="pico",
            runtime="micropython",
            address="/a",
            hardware={"uid": "ABCD"},
        )
        update_device_hardware(data, "pico", {"uid": "ABCD"})
        assert find_device(data, "pico")["hardware"]["uid"] == "ABCD"

    def test_changed_value_raises_without_force(self, tmp_path: Path) -> None:
        """The 'did you swap boards?' guard."""
        data = load_devices(tmp_path / "x.yml")
        add_device(
            data,
            device_id="pico",
            runtime="micropython",
            address="/a",
            hardware={"uid": "ABCD"},
        )
        with pytest.raises(HardwareOverwriteError) as caught:
            update_device_hardware(data, "pico", {"uid": "NEW1"})
        assert caught.value.field_name == "hardware.uid"
        assert caught.value.old_value == "ABCD"
        assert caught.value.new_value == "NEW1"

    def test_force_allows_overwrite(self, tmp_path: Path) -> None:
        data = load_devices(tmp_path / "x.yml")
        add_device(
            data,
            device_id="pico",
            runtime="micropython",
            address="/a",
            hardware={"uid": "ABCD"},
        )
        update_device_hardware(data, "pico", {"uid": "NEW1"}, force=True)
        assert find_device(data, "pico")["hardware"]["uid"] == "NEW1"

    def test_missing_device_raises(self, tmp_path: Path) -> None:
        data = load_devices(tmp_path / "x.yml")
        with pytest.raises(DeviceNotFoundError):
            update_device_hardware(data, "ghost", {"uid": "X"})


# ---------------------------------------------------------------------------
# rename_device
# ---------------------------------------------------------------------------


class TestRenameDevice:
    def test_renames_id_and_default_reference(self, tmp_path: Path) -> None:
        data = load_devices(tmp_path / "x.yml")
        add_device(data, device_id="old", runtime="micropython", address="/a")
        rename_device(data, "old", "shiny-new")
        assert find_device(data, "old") is None
        assert find_device(data, "shiny-new") is not None
        assert data["defaults"]["micropython"] == "shiny-new"

    def test_only_matching_defaults_get_rewritten(self, tmp_path: Path) -> None:
        data = load_devices(tmp_path / "x.yml")
        add_device(data, device_id="alpha", runtime="micropython", address="/a")
        add_device(data, device_id="beta", runtime="circuitpython", address="/b")
        # Defaults now: micropython=alpha, circuitpython=beta.
        rename_device(data, "alpha", "alpha-renamed")
        assert data["defaults"]["micropython"] == "alpha-renamed"
        assert data["defaults"]["circuitpython"] == "beta"

    def test_missing_device_raises(self, tmp_path: Path) -> None:
        data = load_devices(tmp_path / "x.yml")
        with pytest.raises(DeviceNotFoundError):
            rename_device(data, "ghost", "anything")

    def test_existing_target_raises(self, tmp_path: Path) -> None:
        data = load_devices(tmp_path / "x.yml")
        add_device(data, device_id="alpha", runtime="micropython", address="/a")
        add_device(data, device_id="beta", runtime="circuitpython", address="/b")
        with pytest.raises(DeviceAlreadyExistsError):
            rename_device(data, "alpha", "beta")


# ---------------------------------------------------------------------------
# set_runtime_default
# ---------------------------------------------------------------------------


class TestSetRuntimeDefault:
    def test_sets_when_device_exists(self, tmp_path: Path) -> None:
        data = load_devices(tmp_path / "x.yml")
        add_device(
            data,
            device_id="pico",
            runtime="micropython",
            address="/a",
            set_default=False,
        )
        set_runtime_default(data, "micropython", "pico")
        assert data["defaults"]["micropython"] == "pico"

    def test_missing_device_raises(self, tmp_path: Path) -> None:
        data = load_devices(tmp_path / "x.yml")
        with pytest.raises(DeviceNotFoundError):
            set_runtime_default(data, "micropython", "ghost")


# ---------------------------------------------------------------------------
# Malformed-input handling
# ---------------------------------------------------------------------------


class TestMalformedInput:
    def test_devices_value_not_list_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "devices.yml"
        path.write_text("devices: not-a-list\n")
        data = load_devices(path)
        with pytest.raises(DevicesYamlError):
            add_device(data, device_id="x", runtime="micropython", address="/a")

    def test_defaults_value_not_mapping_raises(self, tmp_path: Path) -> None:
        # Load a file where 'defaults' is a scalar, then trigger a code
        # path that needs to access the defaults block.  add_device's
        # set_default=True branch is the natural touchpoint.
        path = tmp_path / "devices.yml"
        path.write_text("defaults: not-a-mapping\ndevices: []\n")
        data = load_devices(path)
        with pytest.raises(DevicesYamlError):
            add_device(
                data,
                device_id="x",
                runtime="micropython",
                address="/a",
            )

    def test_hardware_value_not_mapping_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "devices.yml"
        path.write_text(
            "devices:\n"
            "  - id: pico\n"
            "    runtime: micropython\n"
            "    address: /a\n"
            "    hardware: not-a-mapping\n"
        )
        data = load_devices(path)
        with pytest.raises(DevicesYamlError):
            update_device_hardware(data, "pico", {"uid": "X"})


# ---------------------------------------------------------------------------
# Integration: add → dump → reload → assert
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_add_dump_reload_round_trip(self, tmp_path: Path) -> None:
        path = tmp_path / "devices.yml"
        original = (
            "# Devices.\n"
            "defaults:\n"
            "  # picked by first add-device\n"
            "  micropython: pico-1\n"
            "devices:\n"
            "  - id: pico-1\n"
            "    runtime: micropython\n"
            "    address: /dev/cu.first\n"
        )
        path.write_text(original)

        data = load_devices(path)
        add_device(
            data,
            device_id="pico-2",
            runtime="circuitpython",
            address="/dev/cu.second",
            hardware={"uid": "FFFF"},
        )
        dump_devices(data, path)

        reloaded = path.read_text()
        # User comments survive.
        assert "# Devices." in reloaded
        assert "# picked by first add-device" in reloaded
        # New entry is in the file.
        assert "pico-2" in reloaded
        assert "FFFF" in reloaded
        # Original entry is still there + intact.
        assert "/dev/cu.first" in reloaded
