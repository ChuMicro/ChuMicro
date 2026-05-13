"""Runner-shaped SNTP client for CircuitPython, MicroPython, and CPython.

Built on :class:`chumicro_sockets.UDPSocket` — pass any socket
matching the protocol shape; tests inject :class:`FakeUDPSocket` and
apps reach for the opt-in :mod:`chumicro_ntp.sockets_factory` helper.
"""

from chumicro_ntp.core import NTPClient, NTPError, NTPResult

__all__ = ["NTPClient", "NTPError", "NTPResult"]
