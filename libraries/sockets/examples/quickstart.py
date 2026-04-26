"""Sockets quickstart.

Drives a FakeSocket through the public protocol surface so the example
runs identically on CPython / MicroPython / CircuitPython without
needing a network.  Real-network use is identical except you call
``tcp_client_socket(host, port, radio=...)`` instead of ``FakeSocket()``.

Example output::

    sent: b'PING\\r\\n'
    received: b'PONG\\r\\n'
    closed cleanly
"""

from chumicro_sockets.testing import FakeSocket


def run_quickstart() -> None:
    sock = FakeSocket()
    # Script the response the test peer would have sent.
    sock.enqueue_recv(b"PONG\r\n")
    sock.send(b"PING\r\n")
    print(f"sent: {bytes(sock.sent)!r}")
    buffer = bytearray(64)
    nbytes_read = sock.recv_into(buffer, 64)
    print(f"received: {bytes(buffer[:nbytes_read])!r}")
    sock.close()
    print("closed cleanly")


run_quickstart()
