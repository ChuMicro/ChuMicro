"""LAN-side host primitives used by other host fixtures.

Three helpers, each callable from a conftest's pytest_configure hook:

* `detect_lan_ip()` returns the host's primary LAN IPv4 address (or
  `None` when the host is loopback-only or the kernel can't pick a
  route).
* `find_free_port(bind_host)` binds + immediately closes a TCP socket
  on `bind_host` to get an OS-allocated ephemeral port.
* `wait_until_listening(host, port, deadline_seconds=5.0)` polls
  `(host, port)` with a TCP connect until something accepts or the
  deadline expires.

Workbench-only (CPython); the device side never imports this module.
"""

from __future__ import annotations

import socket
import time


def detect_lan_ip() -> str | None:
    """Return the host's primary LAN IPv4, or `None` when undetectable.

    Opens a UDP socket and "connects" it to a public IP. No packet
    is sent, but the kernel selects the local address it would use to
    route there. `getsockname` then exposes that address. Works on
    macOS and Linux multi-interface setups.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))  # pragma: no cover - real-network side effect
        host, _port = sock.getsockname()  # pragma: no cover - real-network side effect
        if host.startswith("127."):  # pragma: no cover - loopback-only host
            return None
        return host  # pragma: no cover - real-network side effect
    except OSError:
        return None
    finally:
        sock.close()


def find_free_port(bind_host: str) -> int:
    """Bind a temporary socket on `bind_host` and return the OS-allocated port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((bind_host, 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def wait_until_listening(
    host: str, port: int, *, deadline_seconds: float = 5.0,
) -> bool:
    """Poll `(host, port)` with TCP connect until something accepts or the deadline expires."""
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        try:
            probe = socket.create_connection((host, port), timeout=0.5)
        except OSError:
            time.sleep(0.05)
            continue
        probe.close()
        return True
    return False
