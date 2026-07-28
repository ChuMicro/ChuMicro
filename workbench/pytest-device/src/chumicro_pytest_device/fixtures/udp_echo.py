"""Daemon-thread UDP echo server for chumicro-sockets functional tests.

`start_udp_echo_server(bind_host)` binds a UDP socket, spawns a daemon
thread that echoes every received datagram back to its sender, and
returns `(host, port, stop_event)`. The caller sets `stop_event` from
its own pytest_sessionfinish hook to signal a clean shutdown.

Workbench-only (CPython).
"""

from __future__ import annotations

import socket
import threading

#: Maximum datagram size the echo server accepts. Generous for any
#: chumicro library traffic (NTP is 48 bytes, mDNS / SSDP query
#: payloads stay well under 1 KB).
_MAX_DATAGRAM = 1500


def start_udp_echo_server(bind_host: str) -> tuple[str, int, threading.Event]:
    """Bind a UDP echo socket on `bind_host`; return `(host, port, stop_event)`.

    The echo thread loops on `recvfrom` with a 50 ms timeout so it
    can poll the stop event between datagrams. Sends are best-effort:
    OSError on send (peer rebooted etc.) is silently dropped.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((bind_host, 0))
    sock.settimeout(0.05)
    host, port = sock.getsockname()
    stop = threading.Event()

    def _serve() -> None:  # pragma: no cover - daemon thread, exercised by sockets functional tests
        while not stop.is_set():
            try:
                data, peer = sock.recvfrom(_MAX_DATAGRAM)
            except (TimeoutError, OSError):
                continue
            try:
                sock.sendto(data, peer)
            except OSError:
                continue
        sock.close()

    thread = threading.Thread(target=_serve, name="udp-echo-server", daemon=True)
    thread.start()
    return host, port, stop
