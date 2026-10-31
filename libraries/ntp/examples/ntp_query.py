"""Ask an internet time server for the time once a minute, forever.

The board joins your wifi, asks ``pool.ntp.org`` what time it is, and
prints the answer two ways: as Unix seconds (seconds since 1 January
1970, UTC) and as a UTC clock time.  A minute later it asks again, and
it keeps asking until you unplug it.  When a query fails, for example
because no reply arrived within five seconds, the board prints the
reason and tries again on the next round.

The loop never stops to wait for the reply.  ``client.query()`` sends
the question and returns without waiting for the answer.  On every
pass, ``client.check()`` says whether a reply is still pending and
``client.handle()`` reads it once it lands, so anything else you add
to the loop, such as blinking an LED, keeps running in the meantime.

Setup
=====

1. Put your wifi name and password in ``secrets.toml`` under
   ``[wifi]`` as ``ssid`` and ``password``.  If you copy files to the
   board by hand instead of deploying, type them into ``WIFI_SSID`` and
   ``WIFI_PASSWORD`` below.
2. Deploy it.  The command then shows what the board prints::

       chumicro-workspace deploy-example ntp ntp_query --device <id>

To ask a different server, add an ``[ntp]`` table to ``secrets.toml``
with ``server`` (and, if you need them, ``port`` and ``timeout_ms``).
The defaults are ``pool.ntp.org``, port 123, and a 5000 ms timeout.

Example output::

    WIFI_OK ip=10.0.0.42
    NTP_OK unix_seconds=1793462709 utc=16:05:09
    NTP_OK unix_seconds=1793462769 utc=16:06:09
    NTP_FAIL retry_in_s=60
        SNTP query timed out after 5012 ms
    NTP_OK unix_seconds=1793462889 utc=16:08:09
"""

#: Runs on CircuitPython and MicroPython boards that have wifi.
__chumicro_runtimes__ = ("circuitpython", "micropython")

import time

from chumicro_ntp import NTPClient
from helpers import runtime_config, ticks_add, ticks_diff, ticks_ms, wifi_up

WIFI_SSID = "your-wifi-ssid"  # noqa: S105 - replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105 - replace before deploying
SYNC_EVERY_MS = 60_000  # once a minute so you see it work; a real project can wait hours

# Join wifi.  Values from secrets.toml win over the two constants above.
config = runtime_config()
radio, ip = wifi_up(WIFI_SSID, WIFI_PASSWORD)
print(f"WIFI_OK ip={ip}")

# Build the client.  It opens its UDP socket on the first query.
client = NTPClient.from_config(config, radio=radio)

request = None             # the query waiting for a reply, or None
next_sync_ms = ticks_ms()  # due now, so the first query goes out on the first pass

while True:
    now_ms = ticks_ms()

    # Time to ask?  Send a query and book the next one a minute from now.
    if ticks_diff(now_ms, next_sync_ms) >= 0:
        request = client.query()
        next_sync_ms = ticks_add(now_ms, SYNC_EVERY_MS)

    # check() is True while a query waits for its reply.  handle() reads
    # the reply when it lands, or gives up once the timeout has passed.
    if client.check(now_ms):
        client.handle(now_ms)

    # The query finished: print the time, or the reason it failed.
    if request is not None and request.done:
        if request.error is None:
            unix_seconds = request.unix_seconds
            # Every Unix day is exactly 86400 seconds, so the UTC clock
            # time is whole-number division.
            hours = (unix_seconds // 3600) % 24
            minutes = (unix_seconds // 60) % 60
            seconds = unix_seconds % 60
            print(
                f"NTP_OK unix_seconds={unix_seconds} "
                f"utc={hours:02d}:{minutes:02d}:{seconds:02d}",
            )
        else:
            print(f"NTP_FAIL retry_in_s={SYNC_EVERY_MS // 1000}")
            print(f"    {request.error}")
        request = None

    # Your own work, such as blinking an LED, goes in this loop too.
    time.sleep(0.02)  # rest 20 ms between passes
