"""Runner-shaped SNTP client for CircuitPython, MicroPython, and CPython.

Built on the chumicro-sockets UDP surface (``sendto`` /
``recvfrom_into`` / ``close`` / ``setblocking`` / ``settimeout`` /
``getsockname``) — pass any socket matching that shape; tests inject
:class:`FakeUDPSocket` and apps reach for the opt-in
:mod:`chumicro_ntp.sockets_factory` helper.
"""

import gc

from chumicro_ntp.core import NTPClient, NTPError, NTPResult

__all__ = ["NTPClient", "NTPError", "NTPResult"]

gc.collect()
