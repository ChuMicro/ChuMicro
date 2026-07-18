"""Runner-shaped SNTP client for CircuitPython, MicroPython, and CPython.

Pass any non-blocking UDP socket that offers ``sendto`` /
``recvfrom_into`` / ``close`` / ``setblocking``; the client polls it each
tick to answer "what time is it?" against an NTP server.
"""

import gc

from chumicro_ntp.core import NTPClient, NTPError, NTPResult

__all__ = ["NTPClient", "NTPError", "NTPResult"]

gc.collect()
