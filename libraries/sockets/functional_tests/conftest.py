"""Host-side fixtures for sockets functional tests.

Two responsibilities:

1. Materialise ``_test_creds.py`` from the unified config sources
   (``workspace.yml`` + per-library ``functional_tests/config.toml``
   + ``workspace.local.yml``) so the on-device tests can
   ``from _test_creds import SSID, PASSWORD, ECHO_HOST, ECHO_PORT``
   without committing secrets.
2. Start a host-side UDP echo server on the LAN interface so the
   board's UDP smoke test has a counterparty.  The server runs in a
   daemon thread for the duration of the pytest session and echoes
   any datagram it receives straight back to the sender.

Phase 4 of the unification workstream
(``plans/workstreams/scripts-workbench-config-unification.md``)
retired the legacy ``chumicro-dev-config.toml`` source — every
networking library's conftest reads from the same
``workspace.yml`` + ``workspace.local.yml`` pair the workspace-template's
user projects use.
"""

from __future__ import annotations

import socket
import threading
from pathlib import Path

from chumicro_workspace import compose_runtime_config

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
_WORKSPACE_YAML = _REPO_ROOT / "workspace.yml"
_LIBRARY_CONFIG = _HERE / "config.toml"  # optional; absent → workspace defaults only
_WORKSPACE_LOCAL_YAML = _REPO_ROOT / "workspace.local.yml"
_SHIM_PATH = _HERE / "_test_creds.py"

#: Maximum datagram size the echo server accepts.  Generous for any
#: chumicro library traffic (NTP is 48 bytes, mDNS/SSDP query
#: payloads stay well under 1 KB).
_MAX_DATAGRAM = 1500


def _read_wifi_section() -> tuple[str, str] | None:
    """Return ``(ssid, password)`` from the unified config, or ``None``.

    Silent-skip on every "creds not configured" path: missing
    workspace.yml, missing wifi section, missing keys, secrets
    resolution failure, placeholder SSID still in place.
    """
    if not _WORKSPACE_YAML.is_file():
        return None
    try:
        merged = compose_runtime_config(
            workspace_yaml=_WORKSPACE_YAML,
            project_config=_LIBRARY_CONFIG,
            workspace_local_yaml=_WORKSPACE_LOCAL_YAML,
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
    return ssid, password


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
