"""Runner-shaped SNTP client for CircuitPython, MicroPython, and CPython."""

import gc

from chumicro_ntp.core import NTPClient, NTPError, NTPResult

__all__ = ["NTPClient", "NTPError", "NTPResult"]

gc.collect()
