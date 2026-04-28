"""Runner-shaped SNTP client for chumicro libraries.

A small Simple Network Time Protocol (SNTP) client that runs identically
on CircuitPython, MicroPython, and CPython.  Built on
``chumicro_sockets.UDPSocket`` — pass any socket that satisfies the
protocol; tests inject ``FakeUDPSocket`` and apps inject the
runtime's real UDP socket via the ``sockets_factory`` submodule.

Public API::

    from chumicro_ntp import NTPClient, NTPError, NTPResult
    from chumicro_ntp.sockets_factory import chumicro_sockets_factory

    sock = chumicro_sockets_factory(radio=wifi.adapter.radio)
    client = NTPClient(socket=sock, server="pool.ntp.org")
    request = client.query()
    while not request.done:
        if client.check(now_ms()):
            client.handle(now_ms())
    print("unix seconds:", request.unix_seconds)

By Decision 0042's "decoration / observability" rule, no other chumicro
library imports this one.  ``chumicro-sockets`` is a hard dep declared
in ``pyproject.toml`` (Decision 0042 "core infrastructure" rule); the
factory helper that wires it lives in ``chumicro_ntp.sockets_factory``,
a separate submodule users only import when they want the default
wiring (so consumers with a custom UDP transport don't pull
``chumicro-sockets`` into their deploy graph).
"""

from chumicro_ntp.core import NTPClient, NTPError, NTPResult

__all__ = ["NTPClient", "NTPError", "NTPResult"]
