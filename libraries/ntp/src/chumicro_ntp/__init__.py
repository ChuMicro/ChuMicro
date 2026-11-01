"""``chumicro_ntp`` reads the current time from a network time server without blocking the main loop.

The client speaks SNTP (Simple Network Time Protocol, RFC 4330).  It sends one
48-byte UDP request to a time server and reads one 48-byte reply.  The reply
carries the server's clock, which ``NTPResult.unix_seconds`` turns into whole
seconds since 1 January 1970 UTC.
"""

import gc

from chumicro_ntp.core import NTPClient, NTPError, NTPResult

__all__ = ["NTPClient", "NTPError", "NTPResult"]

gc.collect()
