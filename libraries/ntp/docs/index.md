# chumicro-ntp

**Non-blocking SNTP client for CircuitPython, MicroPython, and CPython.**

Pure-Python, takes a UDP socket you provide, returns the server's transmit timestamp without blocking your tick loop.

## Quick example

```python
from chumicro_ntp import NTPClient
from chumicro_sockets import udp_socket
from chumicro_timing import ticks_ms
from chumicro_wifi import WifiConfig, WifiService

# The board has to be on the network first; this is the chumicro-wifi
# service from the ChuMicro quick start.  Drive it from your loop until
# wifi.connected is True, then open the socket.  CircuitPython takes the
# radio from the service; MicroPython and CPython take no radio at all.
wifi = WifiService(WifiConfig(ssid="home-wifi", password="…"))
sock = udp_socket(radio=wifi.adapter.radio)
sock.setblocking(False)

client = NTPClient(socket=sock, server="pool.ntp.org")
request = client.query()
while not request.done:
    now = ticks_ms()
    if client.check(now):
        client.handle(now)
print("unix seconds:", request.unix_seconds)
```

## Documentation

- [User Guide](guide.md): getting started, bringing your own UDP transport, the runner pattern, and the failure modes a query can end in
- [API Reference](api.md): `NTPClient`, the `NTPResult` handle `query()` returns, and `NTPError`

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/ntp) · \
[PyPI](https://pypi.org/project/chumicro-ntp/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
