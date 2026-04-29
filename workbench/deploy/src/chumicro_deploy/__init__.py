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
"""

from __future__ import annotations

from .circuitpython_bootstrap import (
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
