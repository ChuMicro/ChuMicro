"""TCP round-trip example — connect to a host, send + receive.

Identical shape on CircuitPython, MicroPython, and CPython.  CP needs
``radio=wifi.radio`` (or whatever your board exposes); MP and CPython
ignore the kwarg.

To run on a real board, replace ``host``/``port`` with a server you
control (the ``.scratch/run_sockets_acceptance.py`` runner spins up
a host-side echo server you can point this at).

Example output (against an echo server)::

    sent: b'PING from chumicro-sockets\\n'
    received: b'PING from chumicro-sockets\\n'
    closed cleanly
"""

import sys

from chumicro_sockets import tcp_client_socket


def fetch_radio():
    """Return the wifi radio on CP, ``None`` everywhere else.

    The ``import wifi`` lives inside the function so this example
    parses + imports cleanly on CPython for verify-examples; the
    actual import only happens on a CP board where ``wifi`` exists.
    """
    if sys.implementation.name == "circuitpython":
        wifi = __import__("wifi")  # noqa: PLC0415 — CP-only, deferred at runtime

        return wifi.radio
    return None


def run_roundtrip(host: str, port: int) -> None:
    radio = fetch_radio()
    sock = tcp_client_socket(host, port, radio=radio)
    try:
        sock.send(b"PING from chumicro-sockets\n")
        print("sent: b'PING from chumicro-sockets\\n'")
        buffer = bytearray(64)
        nbytes_read = sock.recv_into(buffer, 64)
        print(f"received: {bytes(buffer[:nbytes_read])!r}")
    finally:
        sock.close()
        print("closed cleanly")


if __name__ == "__main__":
    # Replace with a real server (or run via the .scratch acceptance
    # runner which spins up a localhost echo server).
    run_roundtrip("127.0.0.1", 8000)
