"""Send a UDP message to your computer every 5 seconds and print the echo.

The board joins your wifi, opens a UDP socket, and sends a numbered
message (``hello 1``, ``hello 2``, and so on) to an echo server on your
computer every 5 seconds.  The echo server sends each message straight
back, and the board prints it.  UDP never resends a lost message, so
when an echo does not come back before the next send, the board says so
and carries on.

The loop never stops to wait for the network.  ``recvfrom_into`` hands
back a message that has already arrived, or raises ``OSError`` with
``errno.EAGAIN`` ("nothing yet"), and the loop moves on to its next
pass.  Any request-and-reply protocol over UDP, such as NTP or SSDP,
fits the same loop.

Before you run it:

1. Start an echo server on your computer.  Save these lines as
   ``udp_echo_server.py`` and run ``python3 udp_echo_server.py``::

       import socket

       server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
       server.bind(("0.0.0.0", 12345))
       while True:
           data, sender = server.recvfrom(64)
           server.sendto(data, sender)

2. Set ``ECHO_HOST`` below to your computer's IP address on the network
   the board joins, and set ``WIFI_SSID`` and ``WIFI_PASSWORD``.  If you
   deploy with chumicro-workspace, ``wifi.ssid`` and ``wifi.password``
   in your ``secrets.toml`` are used instead of the wifi constants.
3. Put ``chumicro_sockets`` and this folder's ``helpers.py`` on the
   board, and save this file as ``code.py`` (CircuitPython) or
   ``main.py`` (MicroPython).  From a ChuMicro workspace, one command
   does all of that::

       chumicro-workspace deploy-example sockets udp_echo_client --device <id>

What you will see::

    WIFI_OK ip=192.168.1.42
    sent b'hello 1' to 192.168.1.10:12345
    echo b'hello 1' from ('192.168.1.10', 12345)
    sent b'hello 2' to 192.168.1.10:12345
    echo b'hello 2' from ('192.168.1.10', 12345)

With the echo server stopped, each send is followed five seconds later
by ``no echo for message 1`` (2, 3, ...) and the sends keep going.
"""

#: Runs on CircuitPython and MicroPython; needs a wifi radio and an access point.
__chumicro_runtimes__ = ("circuitpython", "micropython")

import errno
import time

from chumicro_sockets import udp_socket
from helpers import ticks_add, ticks_diff, ticks_ms, wifi_up

WIFI_SSID = "your-wifi-ssid"  # noqa: S105 - replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105 - replace before deploying

ECHO_HOST = "192.168.1.10"  # your computer's IP address
ECHO_PORT = 12345
SEND_EVERY_MS = 5000

# Join wifi.  wifi_up waits until the board has an IP address.
radio, ip = wifi_up(WIFI_SSID, WIFI_PASSWORD)
print(f"WIFI_OK ip={ip}")

# Open a UDP socket.  No connection to set up: it can send right away.
sock = udp_socket(radio=radio)
sock.setblocking(False)  # recvfrom_into returns at once instead of waiting

buffer = bytearray(64)  # one receive buffer, reused on every pass
message_number = 0
waiting_for_echo = False
next_send_ms = ticks_ms()

while True:
    now_ms = ticks_ms()

    # Every SEND_EVERY_MS, send the next numbered message.
    if ticks_diff(now_ms, next_send_ms) >= 0:
        next_send_ms = ticks_add(now_ms, SEND_EVERY_MS)
        if waiting_for_echo:
            print(f"no echo for message {message_number}")
        message_number += 1
        message = f"hello {message_number}".encode()
        waiting_for_echo = False
        try:
            sock.sendto(message, ECHO_HOST, ECHO_PORT)
            print(f"sent {message} to {ECHO_HOST}:{ECHO_PORT}")
            waiting_for_echo = True
        except OSError as error:
            print(f"send failed: {error!r}")

    # Check for an echo without waiting for one.
    try:
        size, sender = sock.recvfrom_into(buffer)
        print(f"echo {bytes(buffer[:size])} from {sender}")
        waiting_for_echo = False
    except OSError as error:
        if error.args[0] != errno.EAGAIN:  # EAGAIN only means nothing has arrived
            print(f"receive failed: {error!r}")

    time.sleep(0.01)
