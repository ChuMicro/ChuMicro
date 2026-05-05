"""Host-side fixtures for sockets functional tests.

Two responsibilities:

1. Register the merged runtime-config dict (workspace.yml +
   per-library overrides) with pytest-device so it stages at
   ``/runtime_config.msgpack`` on the device — on-device tests read
   wifi creds + the dynamic ``sockets.echo`` host/port from there.
2. Start a host-side UDP echo server on the LAN interface so the
   board's UDP smoke test has a counterparty.  The server runs in a
   daemon thread for the duration of the pytest session and echoes
   any datagram it receives straight back to the sender.
"""

from __future__ import annotations

import socket
import threading
from pathlib import Path

import pytest
from chumicro_pytest_device.runtime_config import set_runtime_config
from chumicro_workspace import compose_runtime_config

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
_WORKSPACE_YAML = _REPO_ROOT / "workspace.yml"
_LIBRARY_CONFIG = _HERE / "config.toml"  # optional; absent → workspace defaults only

#: Maximum datagram size the echo server accepts.  Generous for any
#: chumicro library traffic (NTP is 48 bytes, mDNS/SSDP query
#: payloads stay well under 1 KB).
_MAX_DATAGRAM = 1500


def _merged_runtime_config_with_creds() -> dict | None:
    """Return the deep-merged runtime-config dict, or ``None`` to silent-skip.

    Returns the dict only when wifi credentials are configured —
    matches the pre-migration behaviour where the on-device tests
    silently skipped on missing creds.
    """
    if not _WORKSPACE_YAML.is_file():
        return None
    try:
        merged = compose_runtime_config(
            workspace_yaml=_WORKSPACE_YAML,
            project_config=_LIBRARY_CONFIG,
        )
    except Exception:  # noqa: BLE001 — silent skip on any config error
        return None
    wifi = merged.get("wifi")
    if not isinstance(wifi, dict):
        return None
    ssid = wifi.get("ssid")
    password = wifi.get("password")
    if not isinstance(ssid, str) or not isinstance(password, str):
        return None
    if ssid == "replace-with-your-ap-ssid":
        return None
    return merged


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


def pytest_configure(config: pytest.Config) -> None:
    """Spin up the host UDP echo server; register the runtime-config payload.

    Always shapes ``sockets.echo`` with ``host``/``port`` keys when a
    payload is registered — values are ``None`` when the fixture didn't
    spawn, so on-device test code can read ``config["sockets"]["echo"]["host"]``
    directly without defensive ``.get()`` chaining.
    """
    global _ECHO_STOP

    merged = _merged_runtime_config_with_creds()

    if merged is not None:
        echo_host: str | None = None
        echo_port: int | None = None
        lan_ip = _detect_lan_ip()
        if lan_ip is not None:
            echo_host, echo_port, _ECHO_STOP = _start_echo_server(lan_ip)
        merged.setdefault("sockets", {})["echo"] = {
            "host": echo_host,
            "port": echo_port,
        }

    set_runtime_config(config, merged)


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ARG001 — pytest hook
    """Tear down the UDP echo server."""
    if _ECHO_STOP is not None:
        _ECHO_STOP.set()
