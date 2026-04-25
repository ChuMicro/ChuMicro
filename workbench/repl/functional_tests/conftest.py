"""Fixtures for chumicro-repl hardware-gated tests.

These tests drive real boards from the host through the public
``chumicro_repl`` API (``ReplSession`` / ``tail`` / ``run_loop``) —
they are not routed through the on-device test harness.  The
``scripts/pytest_device.py`` collector intentionally only intercepts
``libraries/<name>/functional_tests/`` paths (Decision 0032 rule 7),
so this directory runs as plain host-side pytest with a fixture-based
gate on ``devices.yml``.

Mirrors the structure of
``workbench/deploy/functional_tests/conftest.py`` so contributors
moving between the two suites see the same shape.  Run this suite
explicitly:

    pytest workbench/repl/functional_tests/

or scope to one runtime:

    pytest workbench/repl/functional_tests/ -k circuitpython
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

# scripts/ is on sys.path via root conftest.py.
from device_config import (  # type: ignore[import-not-found]
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
    """A CircuitPython DeviceEntry from devices.yml, or skip the test.

    REPL fixtures don't need a CIRCUITPY drive — every ``ReplSession``
    / ``tail`` interaction goes through the raw REPL over serial.
    """
    devices, defaults = _load_registry_or_skip()
    return _pick_device(devices, defaults, "circuitpython")
