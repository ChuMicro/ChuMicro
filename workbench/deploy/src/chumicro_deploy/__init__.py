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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Re-imports for static analysis only.  Runtime resolution goes
    # through the lazy ``__getattr__`` hook below; this block exists
    # so pyright / mypy can see every name declared in ``__all__``
    # without eagerly loading every submodule (which would defeat
    # the lazy pattern's whole purpose — short-lived entrypoints
    # like ``--help`` and ``probe`` don't need the full dep graph).
    from .circuitpython_bootstrap import (
        build_circuitpython_bootstrap,
        build_circuitpython_bootstrap_scripts,
        build_circuitpython_deploy_scripts,
    )
    from .circuitpython_transport import (
        CircuitpythonMidDeployDisconnected,
        CircuitpythonTransport,
        CircuitpythonTransportError,
        SerialPort,
        find_circuitpy_drive,
    )
    from .config.default import (
        DEFAULT_DEVICES_FILENAME,
        DeviceConfigError,
        DeviceDefaults,
        DeviceEntry,
        filter_devices,
        load_device_registry,
        load_devices,
        resolve_ide_devices,
    )
    from .deployer import Deployer
    from .device import Device
    from .firmware import (
        CIRCUITPYTHON_FIRMWARE_URL_TEMPLATE,
        FlashFirmwareError,
        UnresolvedFirmwareError,
        flash_firmware,
        resolve_firmware_url,
    )
    from .host_platform import RsyncMissingError, WindowsNotSupportedError
    from .macos_fskit import (
        MACOS_FSKIT_RECOVERY_COMMAND,
        detect_fskit_wedge,
    )
    from .micropython_transport import (
        MicropythonMidDeployDisconnected,
        MicropythonTransport,
        MicropythonTransportError,
    )
    from .probe import DeviceInfo, probe_device
    from .protocol import (
        DEPLOY_SCOPE_FILES,
        DEPLOY_SCOPE_PREFIXES,
        DeployMode,
        DeviceImplementation,
        ExtendedTransportProtocol,
        ReflashMethod,
        Runtime,
        TransportProtocol,
        is_in_deploy_scope,
    )
    from .recovery import (
        DeployFailureKind,
        InteractiveDeployer,
        RecoveryPlan,
        classify_deploy_failure,
        recovery_plan_for,
    )
    from .result import DeployError, DeployResult
    from .sources import DirectorySource, FileMapSource, FileSource, ImportGraphSource
    from .testing import FakeTransport

#: Map of public attribute -> submodule.  ``__getattr__`` below walks
#: this table to defer each submodule import until the attribute is
#: first read, so short-lived entrypoints (``--help``, ``probe``,
#: ``resolve-firmware-url``) don't pay the full dependency graph.
_LAZY_ATTRS: dict[str, str] = {
    "CIRCUITPYTHON_FIRMWARE_URL_TEMPLATE": "firmware",
    "CircuitpythonMidDeployDisconnected": "circuitpython_transport",
    "CircuitpythonTransport": "circuitpython_transport",
    "CircuitpythonTransportError": "circuitpython_transport",
    "DEFAULT_DEVICES_FILENAME": "config.default",
    "DEPLOY_SCOPE_FILES": "protocol",
    "DEPLOY_SCOPE_PREFIXES": "protocol",
    "DeployError": "result",
    "DeployFailureKind": "recovery",
    "DeployMode": "protocol",
    "DeployResult": "result",
    "Deployer": "deployer",
    "Device": "device",
    "DeviceConfigError": "config.default",
    "DeviceDefaults": "config.default",
    "DeviceEntry": "config.default",
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
    "MicropythonMidDeployDisconnected": "micropython_transport",
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
    "filter_devices": "config.default",
    "find_circuitpy_drive": "circuitpython_transport",
    "flash_firmware": "firmware",
    "is_in_deploy_scope": "protocol",
    "load_device_registry": "config.default",
    "load_devices": "config.default",
    "probe_device": "probe",
    "recovery_plan_for": "recovery",
    "resolve_firmware_url": "firmware",
    "resolve_ide_devices": "config.default",
}

#: Public API surface.  Spelled as a literal list so static type
#: checkers (pyright in particular) can see every exported name;
#: the assertion below catches drift between the literal list and
#: the lazy-attr table.  Keep alphabetized.
__all__ = [
    "CIRCUITPYTHON_FIRMWARE_URL_TEMPLATE",
    "CircuitpythonMidDeployDisconnected",
    "CircuitpythonTransport",
    "CircuitpythonTransportError",
    "DEFAULT_DEVICES_FILENAME",
    "DEPLOY_SCOPE_FILES",
    "DEPLOY_SCOPE_PREFIXES",
    "DeployError",
    "DeployFailureKind",
    "DeployMode",
    "DeployResult",
    "Deployer",
    "Device",
    "DeviceConfigError",
    "DeviceDefaults",
    "DeviceEntry",
    "DeviceImplementation",
    "DeviceInfo",
    "DirectorySource",
    "ExtendedTransportProtocol",
    "FakeTransport",
    "FileMapSource",
    "FileSource",
    "FlashFirmwareError",
    "ImportGraphSource",
    "InteractiveDeployer",
    "MACOS_FSKIT_RECOVERY_COMMAND",
    "MicropythonMidDeployDisconnected",
    "MicropythonTransport",
    "MicropythonTransportError",
    "RecoveryPlan",
    "ReflashMethod",
    "RsyncMissingError",
    "Runtime",
    "SerialPort",
    "TransportProtocol",
    "UnresolvedFirmwareError",
    "WindowsNotSupportedError",
    "build_circuitpython_bootstrap",
    "build_circuitpython_bootstrap_scripts",
    "build_circuitpython_deploy_scripts",
    "classify_deploy_failure",
    "detect_fskit_wedge",
    "filter_devices",
    "find_circuitpy_drive",
    "flash_firmware",
    "is_in_deploy_scope",
    "load_device_registry",
    "load_devices",
    "probe_device",
    "recovery_plan_for",
    "resolve_firmware_url",
    "resolve_ide_devices",
]
assert sorted(__all__) == __all__, "__all__ must be alphabetized"
assert set(__all__) == set(_LAZY_ATTRS), "__all__ must match _LAZY_ATTRS"


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
