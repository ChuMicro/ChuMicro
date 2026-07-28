"""chumicro-deploy: host-side device transports and deploy tooling.

Publishable workbench tool for deploying code and running tests on
MicroPython and CircuitPython hardware.

Transport contract is captured in :mod:`protocol`:

- :class:`TransportProtocol` is the minimum every transport implements.
- :class:`ExtendedTransportProtocol` adds the CircuitPython RAM-mode
  chunking helpers (``execute_scripts``, ``probe_free_memory``,
  ``inline_script_budget_bytes``).

The :class:`Device` facade bundles runtime identity + connection
details + deploy-mode preference into a single object that
:meth:`Device.create_transport` turns into a concrete
:class:`TransportProtocol`.
"""

from __future__ import annotations

from .circuitpython_bootstrap import build_circuitpython_bootstrap_scripts
from .circuitpython_serial_transport import CircuitpythonSerialTransport
from .circuitpython_transport import (
    CircuitpythonMidDeployDisconnected,
    CircuitpythonTransportError,
)
from .config.default import (
    DeviceConfigError,
    DeviceDefaults,
    DeviceEntry,
    load_device_registry,
    load_devices,
    resolve_ide_devices,
)
from .config.devices_yaml import read_devices_yml_template
from .deployer import Deployer
from .device import DEFAULT_DEPLOY_MODE, Device
from .firmware import (
    FlashFirmwareError,
    flash_firmware,
    resolve_firmware_url,
)
from .firmware_url import UnresolvedFirmwareError
from .host_platform import RsyncMissingError, WindowsNotSupportedError
from .macos_fskit import (
    MACOS_FSKIT_RECOVERY_COMMAND,
    detect_fskit_wedge,
)
from .micropython_transport import (
    MicropythonMidDeployDisconnected,
    MicropythonTransportError,
)
from .preflight import (
    DeviceCaps,
    find_libraries_requiring_flash,
    resolve_deploy_mode,
)
from .probe import DeviceInfo, probe_device
from .protocol import (
    DeployMode,
    DeviceImplementation,
    DeviceTransportError,
    ExtendedTransportProtocol,
    MidDeployDisconnected,
    Runtime,
    TransportProtocol,
    UnsupportedExtraFilesError,
)
from .recovery import (
    DeployFailureKind,
    RecoveringDeployer,
    RecoveryPlan,
    classify_deploy_failure,
    recovery_plan_for,
)
from .result import DeployError, DeployResult
from .runtime_marker import (
    file_targets_runtime,
    is_host_only_test,
    is_test_support_module,
    read_runtime_marker,
)
from .sources import (
    DirectorySource,
    FileMapSource,
    FileSource,
    ImportGraphSource,
    UnresolvedImportError,
)
from .testing import FakeTransport

__all__ = [
    "CircuitpythonMidDeployDisconnected",
    "CircuitpythonSerialTransport",
    "CircuitpythonTransportError",
    "DEFAULT_DEPLOY_MODE",
    "DeployError",
    "DeployFailureKind",
    "DeployMode",
    "DeployResult",
    "Deployer",
    "Device",
    "DeviceCaps",
    "DeviceConfigError",
    "DeviceDefaults",
    "DeviceEntry",
    "DeviceImplementation",
    "DeviceInfo",
    "DeviceTransportError",
    "DirectorySource",
    "ExtendedTransportProtocol",
    "FakeTransport",
    "FileMapSource",
    "FileSource",
    "FlashFirmwareError",
    "ImportGraphSource",
    "MACOS_FSKIT_RECOVERY_COMMAND",
    "MicropythonMidDeployDisconnected",
    "MicropythonTransportError",
    "MidDeployDisconnected",
    "RecoveringDeployer",
    "RecoveryPlan",
    "RsyncMissingError",
    "Runtime",
    "TransportProtocol",
    "UnresolvedFirmwareError",
    "UnresolvedImportError",
    "UnsupportedExtraFilesError",
    "WindowsNotSupportedError",
    "build_circuitpython_bootstrap_scripts",
    "classify_deploy_failure",
    "detect_fskit_wedge",
    "file_targets_runtime",
    "find_libraries_requiring_flash",
    "flash_firmware",
    "is_host_only_test",
    "is_test_support_module",
    "load_device_registry",
    "load_devices",
    "probe_device",
    "read_devices_yml_template",
    "read_runtime_marker",
    "recovery_plan_for",
    "resolve_deploy_mode",
    "resolve_firmware_url",
    "resolve_ide_devices",
]
assert sorted(__all__) == __all__, "__all__ must be alphabetized"
