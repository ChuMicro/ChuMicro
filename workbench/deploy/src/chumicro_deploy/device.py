"""Device — transport-agnostic configuration for a target board.

A :class:`Device` bundles the runtime identity (``circuitpython`` /
``micropython``), the host-side connection details (serial address,
baudrate, CIRCUITPY drive path), and the deploy-mode preference.
:meth:`Device.create_transport` returns a concrete
:class:`~chumicro_deploy.protocol.TransportProtocol` instance, so
callers don't have to branch on runtime themselves.

The deploy-time fields (``entrypoint_name``, ``resource_prefix``) are
reserved for the upcoming :class:`~chumicro_deploy.deployer.Deployer`
facade and are exposed on the device now so downstream code can pass a
single ``Device`` instance through the deploy pipeline.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .protocol import DeployMode, Runtime, TransportProtocol

#: Default serial baudrate for CircuitPython raw-REPL sessions.
DEFAULT_BAUDRATE = 115200

#: Default deploy mode.  ``"flash"`` writes files to the board (maps to
#: ``copy`` on MicroPython / CIRCUITPY drive copy on CircuitPython) —
#: this is the production-shaped path and matches how a real deploy
#: behaves on the device.  ``"ram"`` is opt-in for fast iteration on
#: single-library unit-style tests (maps to ``mount`` on MicroPython /
#: inline-exec on CircuitPython).
DEFAULT_DEPLOY_MODE = "flash"

#: On-device directory where deployed library files land by default.
DEFAULT_RESOURCE_PREFIX = "/lib"


@dataclass(frozen=True)
class Device:
    """Configuration for a target board.

    Constructed explicitly in code, from a dict
    (``Device.from_dict(...)``), or via the built-in
    ``devices.yml`` loader
    (``chumicro_deploy.config.default.load_devices_yml``) — or a
    third-party loader registered through the
    ``chumicro_deploy.config_loaders`` entry-point group.

    Attributes:
        transport: Runtime identifier — ``"circuitpython"`` or
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
            CircuitPython, ``"main.py"`` on MicroPython) — pass
            ``None`` to use the runtime default.
        resource_prefix: On-device directory where library files land
            at deploy time.

    The CIRCUITPY drive (CP flash-mode deploys) is auto-resolved at
    deploy time via :func:`find_circuitpy_drive` and verified against
    the board's identity via :meth:`CircuitpythonTransport._verify_drive_for_board`,
    so no per-device drive path is configured here.
    """

    transport: str
    address: str
    baudrate: int = DEFAULT_BAUDRATE
    deploy_mode: str = DEFAULT_DEPLOY_MODE
    entrypoint_name: str | None = None
    resource_prefix: str = DEFAULT_RESOURCE_PREFIX

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

        Accepts the same keys as the constructor — ``transport``,
        ``address``, and optional ``baudrate``, ``deploy_mode``,
        ``entrypoint_name``, and ``resource_prefix``.  Unknown keys
        are ignored so YAML / TOML / JSON inputs with extra metadata
        fields (``id``, ``description``, ``circuitpy_drive_path`` from
        legacy registries, etc.) pass through without filtering.

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
            entrypoint_name=data.get("entrypoint_name"),
            resource_prefix=data.get("resource_prefix", DEFAULT_RESOURCE_PREFIX),
        )

    def create_transport(self) -> TransportProtocol:
        """Construct the concrete transport for this device.

        Returns a :class:`~chumicro_deploy.micropython_transport.MicropythonTransport`
        or :class:`~chumicro_deploy.circuitpython_transport.CircuitpythonTransport`
        depending on :attr:`transport`.  Deploy-mode translation
        (``ram``/``flash`` to the transport's native label) happens here.
        """
        if self.transport == Runtime.MICROPYTHON:
            from .micropython_transport import MicropythonTransport

            mpremote_mode = (
                "mount" if self.deploy_mode == DeployMode.RAM else "copy"
            )
            return MicropythonTransport(self.address, mode=mpremote_mode)
        # __post_init__ has already rejected anything except the two
        # supported runtimes, so we can assume circuitpython here.
        from .circuitpython_transport import CircuitpythonTransport

        return CircuitpythonTransport(
            self.address,
            baudrate=self.baudrate,
            mode=self.deploy_mode,
        )
