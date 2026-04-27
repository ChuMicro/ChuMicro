"""Fixtures for chumicro-workspace hardware-gated tests.

These tests deploy boot-shim layouts to real boards through the
public ``chumicro_workspace`` API and verify the on-device
``workspace_runtime.boot()`` chain (``code.py`` →
``workspace_runtime.boot()`` → ``things.<name>.app.run()``) runs
end-to-end.  Skip cleanly when ``devices.yml`` has no matching
entry, so contributors without hardware run preflight + this
directory and just see "skipped".

Mirrors the structure of
``workbench/repl/functional_tests/conftest.py`` so contributors
moving between the two suites see the same shape.  Run this suite
explicitly:

    pytest workbench/workspace-runtime/functional_tests/

or scope to one runtime:

    pytest workbench/workspace-runtime/functional_tests/ -k circuitpython
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

    Pick order matches the deploy fixture: if ``defaults`` names a
    device ID for this runtime and it exists, use it; otherwise
    fall back to the first matching entry.
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
    """A CircuitPython DeviceEntry from devices.yml, or skip the test."""
    devices, defaults = _load_registry_or_skip()
    return _pick_device(devices, defaults, "circuitpython")
