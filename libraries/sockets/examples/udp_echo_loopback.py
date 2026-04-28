"""UDP echo round-trip on loopback — runs anywhere CPython runs.

Two UDP sockets on ``127.0.0.1``: a "server" bound to a known port
that echoes whatever it receives back to the sender, and a "client"
that sends one datagram and reads the echo.

The same shape works on a board — replace the loopback addresses
with the LAN IPs of your host echo server and the board's wifi-radio
factory call (see ``examples/circuitpython_udp_echo_client.py`` for
the device-side variant).

Runs on CPython.  Useful as a smoke test for ``udp_socket`` and for
copy-paste-style examples in talks.

Example output::

    server bound on 127.0.0.1:54321
    client sent 5 bytes to 127.0.0.1:54321
    server received 'hello' from ('127.0.0.1', <ephemeral>)
    client got echo 'hello' from ('127.0.0.1', 54321)
"""

from chumicro_sockets import udp_socket

server = udp_socket("127.0.0.1", 0)
server_host, server_port = server.getsockname()
print(f"server bound on {server_host}:{server_port}")

client = udp_socket("127.0.0.1", 0)
n_sent = client.sendto(b"hello", server_host, server_port)
print(f"client sent {n_sent} bytes to {server_host}:{server_port}")

server_buffer = bytearray(64)
n_received, sender = server.recvfrom_into(server_buffer)
payload = bytes(server_buffer[:n_received]).decode()
print(f"server received {payload!r} from {sender}")

# Echo back to the sender.
server.sendto(server_buffer[:n_received], sender[0], sender[1])

client_buffer = bytearray(64)
n_received, peer = client.recvfrom_into(client_buffer)
echo = bytes(client_buffer[:n_received]).decode()
print(f"client got echo {echo!r} from {peer}")

client.close()
server.close()
