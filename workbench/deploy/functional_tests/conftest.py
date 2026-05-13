"""Fixtures for chumicro-deploy hardware-gated tests.

These tests drive real boards from the host through the public
``chumicro_deploy`` API (``Device`` / ``Deployer``) — they are not
routed through the on-device test harness.  The
``chumicro-pytest-device`` plugin intentionally only intercepts
``libraries/<name>/functional_tests/`` paths, so this directory
runs as plain host-side pytest with a fixture-based gate on
``devices.yml``.

Root ``conftest.py`` already excludes ``functional_tests/`` from
default collection — run this suite explicitly with
``pytest workbench/deploy/functional_tests/`` or via IDE targeting.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from chumicro_deploy import (
    DeviceConfigError,
    DeviceDefaults,
    DeviceEntry,
    load_device_registry,
)
from chumicro_deploy.circuitpy_drive import _circuitpy_volume_candidates
from chumicro_deploy.macos_fskit import (
    MACOS_FSKIT_RECOVERY_COMMAND,
    detect_fskit_wedge,
)


@pytest.fixture(scope="session", autouse=True)
def _check_fskit_wedge_at_session_start() -> None:
    """Skip the whole suite if macOS FSKit is wedged before tests start.

    A pre-existing wedge would otherwise turn the suite into a 10+
    second-per-test failure cascade on every flash-mode test
    (CIRCUITPY drives never appear; ``_resolve_circuitpy_drive`` waits
    out its budget on every call).  Detecting once at session start
    fails fast with the recovery command instead.

    No-op on non-macOS — :func:`detect_fskit_wedge` returns False on
    every other platform.
    """
    if detect_fskit_wedge():
        pytest.skip(
            "macOS FSKit is wedged before the functional suite starts.  "
            "Clear it before retrying:\n"
            f"    {MACOS_FSKIT_RECOVERY_COMMAND}",
        )


def _load_registry_or_skip() -> tuple[list[DeviceEntry], DeviceDefaults]:
    """Load devices.yml once; skip the whole test when missing/invalid."""
    try:
        return load_device_registry()
    except (DeviceConfigError, FileNotFoundError, OSError) as load_error:
        pytest.skip(f"devices.yml unavailable: {load_error}")


def _pick_device(
    devices: list[DeviceEntry],
    defaults: DeviceDefaults,
    runtime: str,
    *,
    predicate: Callable[[DeviceEntry], bool] | None = None,
) -> DeviceEntry:
    """Return the default device for *runtime* or skip.

    The pick order matches ``resolve_ide_devices``: if ``defaults``
    names a device ID for this runtime and it exists, use it;
    otherwise fall back to the first matching entry.  An optional
    *predicate* further filters (used by flash-mode tests to require
    a mounted CIRCUITPY drive).
    """
    preferred_id = (
        defaults.micropython if runtime == "micropython" else defaults.circuitpython
    )
    matches = [
        device for device in devices
        if device.runtime == runtime
        and (predicate is None or predicate(device))
    ]
    if not matches:
        pytest.skip(f"No {runtime} device available in devices.yml")

    if preferred_id:
        for device in matches:
            if device.identifier == preferred_id:
                return device
    return matches[0]


@pytest.fixture
def micropython_device() -> DeviceEntry:
    """A MicroPython DeviceEntry from devices.yml, or skip the test."""
    devices, defaults = _load_registry_or_skip()
    return _pick_device(devices, defaults, "micropython")


@pytest.fixture
def circuitpython_device() -> DeviceEntry:
    """A CircuitPython DeviceEntry from devices.yml, or skip the test.

    No drive-mount predicate — RAM-mode deploy reaches the board
    through the raw REPL alone and does not require a CIRCUITPY
    drive.  Flash-mode tests should use :func:`circuitpython_flash_device`
    instead.
    """
    devices, defaults = _load_registry_or_skip()
    return _pick_device(devices, defaults, "circuitpython")


@pytest.fixture
def circuitpython_flash_device() -> DeviceEntry:
    """A CircuitPython DeviceEntry suitable for flash-mode deploy.

    Skips when no CIRCUITPY drive is currently mounted on the host —
    flash-mode deploy needs somewhere to write files, and the
    transport resolves the drive at deploy time via
    :func:`_circuitpy_volume_candidates` plus UID-based auto-correction.
    """
    devices, defaults = _load_registry_or_skip()
    if not _circuitpy_volume_candidates():
        pytest.skip("No CIRCUITPY drive mounted on the host")
    return _pick_device(devices, defaults, "circuitpython")
