"""Host-side fixtures for sockets functional tests.

Two responsibilities:

1. Materialise ``_test_creds.py`` from ``chumicro-dev-config.toml``
   so the on-device tests can ``from _test_creds import SSID,
   PASSWORD, ECHO_HOST, ECHO_PORT`` without committing secrets.
2. Start a host-side UDP echo server on the LAN interface so the
   board's UDP smoke test has a counterparty.  The server runs in a
   daemon thread for the duration of the pytest session and echoes
   any datagram it receives straight back to the sender.

See ``libraries/requests/functional_tests/conftest.py`` for the
shared ``[wifi]`` rationale.
"""

from __future__ import annotations

import socket
import threading
import tomllib
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
_DEV_CONFIG = _REPO_ROOT / "chumicro-dev-config.toml"
_SHIM_PATH = _HERE / "_test_creds.py"

#: Maximum datagram size the echo server accepts.  Generous for any
#: chumicro library traffic (NTP is 48 bytes, mDNS/SSDP query
#: payloads stay well under 1 KB).
_MAX_DATAGRAM = 1500


def _read_wifi_section() -> tuple[str, str] | None:
    if not _DEV_CONFIG.exists():
        return None
    try:
        data = tomllib.loads(_DEV_CONFIG.read_text())
        wifi = data["wifi"]
        return wifi["ssid"], wifi["password"]
    except (KeyError, ValueError):
        return None


def _detect_lan_ip() -> str | None:
    """Return the host's primary LAN IPv4, or ``None`` if undetectable.

    Trick: open a UDP socket and "connect" it to a public IP — no
    packet is sent, but the kernel selects the local address it would
    use to route there.  ``getsockname`` then exposes that address.
    Robust across macOS / Linux multi-interface setups.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        host, _port = sock.getsockname()
        if host.startswith("127."):
            return None
        return host
    except OSError:
        return None
    finally:
        sock.close()


def _start_echo_server(bind_host: str) -> tuple[str, int, threading.Event]:
    """Bind a UDP echo socket on *bind_host*; return (host, port, stop_event).

    Echoes every received datagram straight back to its sender on a
    daemon thread.  The stop event lets the session-finish hook
    signal a clean shutdown.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((bind_host, 0))
    sock.settimeout(0.25)
    host, port = sock.getsockname()
    stop = threading.Event()

    def _serve() -> None:
        while not stop.is_set():
            try:
                data, peer = sock.recvfrom(_MAX_DATAGRAM)
            except (TimeoutError, OSError):
                continue
            try:
                sock.sendto(data, peer)
            except OSError:
                # Best effort — drop on send failure (peer rebooted, etc.).
                continue
        sock.close()

    thread = threading.Thread(target=_serve, name="udp-echo-server", daemon=True)
    thread.start()
    return host, port, stop


_ECHO_STOP: threading.Event | None = None


def pytest_configure(config) -> None:  # noqa: ARG001 — pytest hook signature
    """Refresh ``_test_creds.py``; spin up the host UDP echo server."""
    global _ECHO_STOP

    creds = _read_wifi_section()
    echo_host: str | None = None
    echo_port: int | None = None

    if creds is not None:
        lan_ip = _detect_lan_ip()
        if lan_ip is not None:
            echo_host, echo_port, _ECHO_STOP = _start_echo_server(lan_ip)

    if creds is None:
        if _SHIM_PATH.exists():
            _SHIM_PATH.unlink()
        return

    ssid, password = creds
    lines = [
        '"""Auto-generated test creds shim — do not check in."""\n',
        f"SSID = {ssid!r}\n",
        f"PASSWORD = {password!r}\n",
    ]
    if echo_host is not None and echo_port is not None:
        lines.extend(
            (
                f"ECHO_HOST = {echo_host!r}\n",
                f"ECHO_PORT = {echo_port!r}\n",
            ),
        )
    else:
        lines.extend(
            (
                "ECHO_HOST = None\n",
                "ECHO_PORT = None\n",
            ),
        )
    _SHIM_PATH.write_text("".join(lines))


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ARG001 — pytest hook
    """Tear down the UDP echo server."""
    if _ECHO_STOP is not None:
        _ECHO_STOP.set()
