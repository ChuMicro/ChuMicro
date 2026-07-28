"""Device: transport-agnostic configuration for a target board.

A :class:`Device` bundles the runtime identity (``circuitpython`` /
``micropython``), the host-side connection details (serial address,
baudrate, CIRCUITPY drive path), and the deploy-mode preference.
:meth:`Device.create_transport` returns a concrete
:class:`~chumicro_deploy.protocol.TransportProtocol` instance, so
callers don't have to branch on runtime themselves.

Two fields, ``entrypoint_name`` and ``resource_prefix``, aren't
read by :meth:`create_transport`.  They are deploy-config carried
on Device so a deploy takes one configured object.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .protocol import DeployMode, Runtime, TransportProtocol

#: Default serial baudrate for CircuitPython raw-REPL sessions.
DEFAULT_BAUDRATE = 115200

#: Default deploy mode.  ``"flash"`` writes files to the board (maps to
#: ``copy`` on MicroPython / CIRCUITPY drive copy on CircuitPython).
#: Matches how a real deploy behaves on the device.  ``"ram"`` is
#: opt-in for fast iteration on single-library unit-style tests (maps
#: to ``mount`` on MicroPython / inline-exec on CircuitPython).
DEFAULT_DEPLOY_MODE = "flash"

#: On-device directory where deployed library files land by default.
DEFAULT_RESOURCE_PREFIX = "/lib"

#: Default deploy-transport selection.  ``"auto"`` lets the host-side
#: builder pick drive-vs-serial (see
#: :func:`chumicro_workspace.device_orchestration.build_transport_for_entry`);
#: ``"serial"`` forces the drive-less raw-REPL path for a board that
#: has no CIRCUITPY volume (classic ESP32, no native USB); ``"drive"``
#: forces the CIRCUITPY-drive path.  Only meaningful for CircuitPython.
DEFAULT_DEPLOY_TRANSPORT = "auto"

#: Recognized ``deploy_transport`` values.
_VALID_DEPLOY_TRANSPORTS = ("auto", "serial", "drive")


@dataclass(frozen=True)
class Device:
    """Configuration for a target board.

    Constructed explicitly in code, from a dict
    (``Device.from_dict(...)``), or via the built-in
    ``devices.yml`` loader
    (``chumicro_deploy.config.default.load_devices_yml``), or a
    third-party loader registered through the
    ``chumicro_deploy.config_loaders`` entry-point group.

    Attributes:
        transport: Runtime identifier, ``"circuitpython"`` or
            ``"micropython"``.
        address: Serial port path (``"/dev/cu.usbmodem..."`` on macOS,
            ``"/dev/ttyACM0"`` on Linux, ``"COM3"`` on Windows).
        baudrate: Serial baudrate.  Only meaningful for the
            CircuitPython transport; the MicroPython transport uses
            ``mpremote`` defaults.
        deploy_mode: ``"ram"`` or ``"flash"``.  Mapped to the
            transport's mode label at construction time
            (``mount``/``copy`` on MP, ``ram``/``flash`` on CP).
        entrypoint_name: Top-level script the runtime executes on
            boot.  Defaults vary per runtime (``"code.py"`` on
            CircuitPython, ``"main.py"`` on MicroPython).  Pass
            ``None`` to use the runtime default.
        resource_prefix: On-device directory where library files land
            at deploy time.
        transport_factory: Override hook for :meth:`create_transport`.
            When set, :meth:`create_transport` returns
            ``transport_factory(self)`` instead of building the
            runtime-specific transport.  Per-instance, so multiple
            Devices can carry different transport implementations.

    The CIRCUITPY drive (CP flash-mode deploys) is auto-resolved at
    deploy time by scanning the host's mount points and matching the
    connected board's UID / machine string against each candidate's
    ``boot_out.txt``, so no per-device drive path is configured here.
    """

    transport: str
    address: str
    baudrate: int = DEFAULT_BAUDRATE
    deploy_mode: str = DEFAULT_DEPLOY_MODE
    deploy_transport: str = DEFAULT_DEPLOY_TRANSPORT
    entrypoint_name: str | None = None
    resource_prefix: str = DEFAULT_RESOURCE_PREFIX
    transport_factory: Callable[[Device], TransportProtocol] | None = field(
        default=None, repr=False, compare=False,
    )

    def __post_init__(self) -> None:
        if self.transport not in Runtime._value2member_map_:
            allowed = ", ".join(f"{runtime.value!r}" for runtime in Runtime)
            raise ValueError(
                f"Unsupported transport: {self.transport!r} "
                f"(expected {allowed})"
            )
        if self.deploy_mode not in DeployMode._value2member_map_:
            allowed = ", ".join(f"{mode.value!r}" for mode in DeployMode)
            raise ValueError(
                f"Unsupported deploy_mode: {self.deploy_mode!r} "
                f"(expected {allowed})"
            )
        if self.deploy_transport not in _VALID_DEPLOY_TRANSPORTS:
            allowed = ", ".join(f"{choice!r}" for choice in _VALID_DEPLOY_TRANSPORTS)
            raise ValueError(
                f"Unsupported deploy_transport: {self.deploy_transport!r} "
                f"(expected {allowed})"
            )

    @property
    def effective_entrypoint(self) -> str:
        """Return the entrypoint filename, resolving runtime default when unset.

        CircuitPython boards boot ``code.py``; MicroPython boards boot
        ``main.py``.  Override via :attr:`entrypoint_name` when the
        target runs something else.
        """
        if self.entrypoint_name is not None:
            return self.entrypoint_name
        return "code.py" if self.transport == "circuitpython" else "main.py"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Device:
        """Construct a :class:`Device` from a mapping of field names.

        Accepts the same keys as the constructor: ``transport``,
        ``address``, and optional ``baudrate``, ``deploy_mode``,
        ``entrypoint_name``, and ``resource_prefix``.  Unknown keys
        are ignored so YAML / TOML / JSON inputs with extra metadata
        fields (``id``, ``description``, ``circuitpy_drive_path``,
        etc.) pass through without filtering.

        Args:
            data: Mapping of field names to values.  ``transport``
                and ``address`` are required; everything else falls
                back to the constructor default.

        Raises:
            ValueError: Missing ``transport`` or ``address``, or any
                of the constructor's normal validation
                (unsupported transport / deploy_mode).
        """
        if "transport" not in data or "address" not in data:
            missing = [key for key in ("transport", "address") if key not in data]
            raise ValueError(
                f"Device.from_dict missing required key(s): {missing!r}"
            )

        return cls(
            transport=data["transport"],
            address=data["address"],
            baudrate=int(data.get("baudrate", DEFAULT_BAUDRATE)),
            deploy_mode=data.get("deploy_mode", DEFAULT_DEPLOY_MODE),
            deploy_transport=data.get("deploy_transport", DEFAULT_DEPLOY_TRANSPORT),
            entrypoint_name=data.get("entrypoint_name"),
            resource_prefix=data.get("resource_prefix", DEFAULT_RESOURCE_PREFIX),
        )

    def create_transport(self) -> TransportProtocol:
        """Construct the concrete transport for this device.

        Returns a :class:`~chumicro_deploy.micropython_transport.MicropythonTransport`
        or :class:`~chumicro_deploy.circuitpython_transport.CircuitpythonTransport`
        depending on :attr:`transport`.  Deploy-mode translation
        (``ram``/``flash`` to the transport's native label) happens here.

        When :attr:`transport_factory` is set, returns its result
        instead.
        """
        if self.transport_factory is not None:
            return self.transport_factory(self)
        if self.transport == Runtime.MICROPYTHON:
            from .micropython_transport import MicropythonTransport

            mpremote_mode = (
                "mount" if self.deploy_mode == DeployMode.RAM else "copy"
            )
            return MicropythonTransport(
                self.address,
                baudrate=self.baudrate,
                mode=mpremote_mode,
            )
        # __post_init__ has already rejected anything except the two
        # supported runtimes, so we can assume circuitpython here.
        #
        # ``deploy_transport == "serial"`` selects the drive-less
        # raw-REPL transport (a board with no CIRCUITPY volume, such as a
        # classic ESP32 without native USB).  ``"auto"`` / ``"drive"`` keep the
        # CIRCUITPY-drive transport: this method is pure construction and
        # cannot probe for a drive, so the auto → serial fallback is
        # resolved one layer up in
        # ``build_transport_for_entry`` before the Device is built.
        if self.deploy_transport == "serial":
            from .circuitpython_serial_transport import (
                CircuitpythonSerialTransport,
            )

            return CircuitpythonSerialTransport(
                self.address,
                baudrate=self.baudrate,
            )
        from .circuitpython_transport import CircuitpythonTransport

        return CircuitpythonTransport(
            self.address,
            baudrate=self.baudrate,
            mode=self.deploy_mode,
        )
