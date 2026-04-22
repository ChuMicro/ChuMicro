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

from dataclasses import dataclass
from pathlib import Path

from .circuitpython_transport import CircuitpythonTransport
from .micropython_transport import MicropythonTransport
from .protocol import TransportProtocol

#: Default serial baudrate for CircuitPython raw-REPL sessions.
DEFAULT_BAUDRATE = 115200

#: Default deploy mode.  ``"ram"`` keeps edits off the board's flash
#: (maps to ``mount`` on MicroPython / inline-exec on CircuitPython);
#: ``"flash"`` writes files to the board (maps to ``copy`` on
#: MicroPython / CIRCUITPY drive copy on CircuitPython).
DEFAULT_DEPLOY_MODE = "ram"

#: On-device directory where deployed library files land by default.
DEFAULT_RESOURCE_PREFIX = "/lib"


@dataclass(frozen=True)
class Device:
    """Configuration for a target board.

    Constructed explicitly in code, from a dict
    (``Device.from_dict(...)``), from environment variables
    (``Device.from_env(prefix=...)``), or via a workspace-specific
    loader (see ``chumicro_deploy.config.chumicro.load_devices_yml``
    once Slice 1e lands).

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
        circuitpy_drive_path: Filesystem path where the CIRCUITPY
            drive is mounted.  Only used on CircuitPython in flash
            mode.  ``None`` means auto-detect.
        entrypoint_name: Top-level script the runtime executes on
            boot.  Defaults vary per runtime (``"code.py"`` on
            CircuitPython, ``"main.py"`` on MicroPython) — pass
            ``None`` to use the runtime default.
        resource_prefix: On-device directory where library files land
            at deploy time.
    """

    transport: str
    address: str
    baudrate: int = DEFAULT_BAUDRATE
    deploy_mode: str = DEFAULT_DEPLOY_MODE
    circuitpy_drive_path: Path | None = None
    entrypoint_name: str | None = None
    resource_prefix: str = DEFAULT_RESOURCE_PREFIX

    def __post_init__(self) -> None:
        if self.transport not in ("circuitpython", "micropython"):
            raise ValueError(
                f"Unsupported transport: {self.transport!r} "
                f"(expected 'circuitpython' or 'micropython')"
            )
        if self.deploy_mode not in ("ram", "flash"):
            raise ValueError(
                f"Unsupported deploy_mode: {self.deploy_mode!r} "
                f"(expected 'ram' or 'flash')"
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

    def create_transport(self) -> TransportProtocol:
        """Construct the concrete transport for this device.

        Returns a :class:`~chumicro_deploy.micropython_transport.MicropythonTransport`
        or :class:`~chumicro_deploy.circuitpython_transport.CircuitpythonTransport`
        depending on :attr:`transport`.  Deploy-mode translation
        (``ram``/``flash`` to the transport's native label) happens here.
        """
        if self.transport == "micropython":
            mpremote_mode = "mount" if self.deploy_mode == "ram" else "copy"
            return MicropythonTransport(self.address, mode=mpremote_mode)
        # __post_init__ has already rejected anything except the two
        # supported runtimes, so we can assume circuitpython here.
        return CircuitpythonTransport(
            self.address,
            baudrate=self.baudrate,
            mode=self.deploy_mode,
            circuitpy_drive_path=self.circuitpy_drive_path,
        )
