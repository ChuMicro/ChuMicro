"""chumicro-pytest-device: pytest plugin for on-device library tests.

Runs library functional tests on connected CircuitPython and
MicroPython boards.  pytest loads the plugin through the
``pytest11`` entry point at :mod:`chumicro_pytest_device.plugin`;
the collection, transport-cache, and device-backend machinery live
in sibling submodules and are imported directly, not re-exported here.
"""

from __future__ import annotations
