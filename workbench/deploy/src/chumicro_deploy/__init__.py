"""chumicro-deploy — host-side device transports and deploy tooling.

Publishable workbench tool (Decision 0032) for deploying code and
running tests on MicroPython and CircuitPython hardware.

Transport contract (Decision 0027) is captured in :mod:`protocol`:

- :class:`TransportProtocol` — minimum every transport must implement.
- :class:`ExtendedTransportProtocol` — adds the CircuitPython RAM-mode
  chunking helpers (``execute_scripts``, ``probe_free_memory``,
  ``inline_script_budget_bytes``).

The :class:`Device` facade bundles runtime identity + connection
details + deploy-mode preference into a single object that
:meth:`Device.create_transport` turns into a concrete
:class:`TransportProtocol`.

Imports are resolved lazily via the module-level ``__getattr__`` hook
(the mechanism added in PEP 562).  ``from chumicro_deploy import X``
still works, but the underlying modules (``circuitpython_transport``,
``firmware``, etc.) are only loaded on first attribute access.  A
``chumicro-deploy --help`` or a ``probe`` invocation no longer pays
the cost of importing ``pyserial``, ``mpremote``, and
``urllib.request`` up front.
"""

from __future__ import annotations

import importlib
from typing import Any

#: Map of public attribute -> submodule.  ``__getattr__`` below walks
#: this table to defer each submodule import until the attribute is
#: first read, so short-lived entrypoints (``--help``, ``probe``,
#: ``resolve-firmware-url``) don't pay the full dependency graph.
_LAZY_ATTRS: dict[str, str] = {
    "CIRCUITPYTHON_FIRMWARE_URL_TEMPLATE": "firmware",
    "CircuitpythonTransport": "circuitpython_transport",
    "CircuitpythonTransportError": "circuitpython_transport",
    "DeployError": "result",
    "DeployFailureKind": "recovery",
    "DeployMode": "protocol",
    "DeployResult": "result",
    "Deployer": "deployer",
    "Device": "device",
    "DeviceImplementation": "protocol",
    "DeviceInfo": "probe",
    "DirectorySource": "sources",
    "ExtendedTransportProtocol": "protocol",
    "FakeTransport": "testing",
    "FileMapSource": "sources",
    "FileSource": "sources",
    "FlashFirmwareError": "firmware",
    "ImportGraphSource": "sources",
    "InteractiveDeployer": "recovery",
    "MACOS_FSKIT_RECOVERY_COMMAND": "macos_fskit",
    "MicropythonTransport": "micropython_transport",
    "MicropythonTransportError": "micropython_transport",
    "RecoveryPlan": "recovery",
    "ReflashMethod": "protocol",
    "RsyncMissingError": "host_platform",
    "Runtime": "protocol",
    "SerialPort": "circuitpython_transport",
    "TransportProtocol": "protocol",
    "UnresolvedFirmwareError": "firmware",
    "WindowsNotSupportedError": "host_platform",
    "build_circuitpython_bootstrap": "circuitpython_bootstrap",
    "build_circuitpython_bootstrap_scripts": "circuitpython_bootstrap",
    "build_circuitpython_deploy_scripts": "circuitpython_bootstrap",
    "classify_deploy_failure": "recovery",
    "detect_fskit_wedge": "macos_fskit",
    "find_circuitpy_drive": "circuitpython_transport",
    "flash_firmware": "firmware",
    "probe_device": "probe",
    "recovery_plan_for": "recovery",
    "resolve_firmware_url": "firmware",
}

__all__ = sorted(_LAZY_ATTRS.keys())


def __getattr__(name: str) -> Any:
    module_name = _LAZY_ATTRS.get(name)
    if module_name is None:
        raise AttributeError(
            f"module 'chumicro_deploy' has no attribute {name!r}"
        )
    module = importlib.import_module(f".{module_name}", __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return [*globals().keys(), *_LAZY_ATTRS.keys()]
