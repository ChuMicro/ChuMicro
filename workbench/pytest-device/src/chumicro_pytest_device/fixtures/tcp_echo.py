"""Daemon-thread TCP echo server for chumicro-sockets demos and tests.

`start_tcp_echo_server(bind_host)` binds a TCP listener, spawns a daemon
thread that accepts one connection at a time and echoes every received
byte back to the sender, and returns `(host, port, stop_event)`. The
caller sets `stop_event` to drain the accept loop on shutdown.

Workbench-only (CPython).
"""

from __future__ import annotations

import socket
import threading

#: Max bytes consumed per recv() call. Sized to comfortably cover any
#: chumicro library probe (the sockets demo sends ~32 bytes).
_RECV_CHUNK = 4096


def start_tcp_echo_server(bind_host: str) -> tuple[str, int, threading.Event]:
    """Bind a TCP echo socket on `bind_host`; return `(host, port, stop_event)`.

    Sequential-accept: one connection at a time, no per-client threading.
    The accept loop polls with a 50 ms timeout so it can notice
    `stop_event` between connections. Each accepted client runs an inner
    recv loop that echoes back until the client closes or `stop_event`
    fires.
    """
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((bind_host, 0))
    listener.listen(4)
    listener.settimeout(0.05)
    host, port = listener.getsockname()
    stop = threading.Event()

    def _serve() -> None:  # pragma: no cover - daemon thread, exercised by sockets demos
        while not stop.is_set():
            try:
                client, _peer = listener.accept()
            except (TimeoutError, OSError):
                continue
            # The accepted socket would inherit the listener's 50 ms
            # stop-poll timeout; give the echo conversation its own
            # idle budget instead.
            client.settimeout(0.25)
            try:
                while not stop.is_set():
                    chunk = client.recv(_RECV_CHUNK)
                    if not chunk:
                        break
                    client.sendall(chunk)
            except OSError:
                continue
            finally:
                try:
                    client.close()
                except OSError:
                    pass
        listener.close()

    thread = threading.Thread(target=_serve, name="tcp-echo-server", daemon=True)
    thread.start()
    return host, port, stop
