# User Guide

## Overview

`chumicro-sockets` gives a board three ways onto a network.  [`connector`](api.md#chumicro_sockets.connector) opens a TCP or TLS connection to a server, [`listener`](api.md#chumicro_sockets.listener) accepts connections from other devices, and [`udp_socket`](api.md#chumicro_sockets.udp_socket) sends and receives single messages.  The same calls work on CircuitPython, MicroPython, and CPython, because each runtime gets its own modules underneath: `socketpool` on CircuitPython, `socket` and `ssl` on MicroPython, the standard library on CPython.

A connector does not connect the moment you create it.  It works through a connection in steps, and each call to its `tick()` method runs the next one: look up the server's address, open the TCP connection, then finish the TLS handshake when `tls=True`.  Its `state` reports how far it got, ending at `"ready"` or `"failed"`.  Your loop decides when each step runs, so a board can do other work while a connection opens.

`chumicro-requests`, `chumicro-mqtt`, `chumicro-websockets`, `chumicro-http-server`, and `chumicro-ntp` all build on this library.

## Getting started

This loop fetches a web page every 30 seconds for as long as the board has power.  The [`tcp_roundtrip.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets/examples/tcp_roundtrip.py) example is the same program with wifi setup added.

```python
import time

from chumicro_sockets import connector

# CircuitPython needs the wifi radio: `import wifi`, then radio = wifi.radio.
# MicroPython and CPython ignore radio, so None works there.
radio = None

buffer = bytearray(256)

while True:
    # connector() returns at once.  Each tick() takes the next step (look up
    # the address, then connect) until the state is "ready" or "failed".
    dial = connector("example.com", 80, radio=radio)
    while dial.state not in ("ready", "failed"):
        dial.tick(0)  # the time in ms; a connector keeps no deadlines, so 0 works
        time.sleep(0.01)

    if dial.state == "failed":
        print(f"connect failed: {dial.last_error!r}")
    else:
        sock = dial.socket
        try:
            sock.settimeout(5)  # wait at most 5 s on each send and read
            sock.send(b"GET / HTTP/1.0\r\nHost: example.com\r\n\r\n")
            count = sock.recv_into(buffer)
            first_line = bytes(buffer[:count]).split(b"\r\n")[0]
            print(f"reply: {first_line.decode()}")
        except OSError as error:
            print(f"send or receive failed: {error!r}")
        sock.close()

    time.sleep(30)
```

What each part does:

- **`connector(host, port, radio=radio)`** returns at once with `state` set to `"awaiting_dns"`.  Nothing has touched the network yet.
- **`dial.tick(0)`** runs the next step.  `state` moves through `"awaiting_dns"` and `"awaiting_tcp"` (and `"awaiting_tls"` on some runtimes when `tls=True`) and stops at `"ready"` or `"failed"`.  The argument is the current time in milliseconds, which a runner hands every service it drives.  A connector keeps no deadlines, so any number works.
- **`dial.socket`** is the connected socket once `state` is `"ready"`.  Call `send` and `recv_into` on it, and close it when you are done: a board holds only a few sockets at once, so a loop that leaks one per pass runs out.
- **`dial.last_error`** is the exception behind a `"failed"` state.  The connector has already closed its own socket by then, so the loop prints the error and tries again on the next pass.
- **`dial.cancel()`** gives up on a connect in progress.  A connector never times out by itself; `cancel()` closes any half-open socket and sets `state` to `"failed"`.

## Choosing how a socket waits

The runtimes disagree on how a connected socket waits: CircuitPython hands it back blocking, while MicroPython and CPython hand it back non-blocking.  Set the mode you want right after `"ready"`, as the loop above does.

- **`sock.settimeout(seconds)`** makes each `send` and `recv_into` wait up to that long, then raise `OSError`.  Choose it when the board has one job, as in the loop above.  Avoid a blocking read with no timeout in a forever loop: a server that stops answering would stall the board for good.
- **`sock.setblocking(False)`** makes each call return at once.  When nothing has arrived, `recv_into` raises `OSError` with `errno.EAGAIN` as its first argument.  That means "nothing yet", so check again on a later pass of your loop:

```python
import errno

sock.setblocking(False)

# Inside your loop:
try:
    count = sock.recv_into(buffer)
except OSError as error:
    if error.args[0] != errno.EAGAIN:
        raise
    count = None  # nothing has arrived yet; look again next pass
```

A `recv_into` that returns `0` means the other end closed the connection.

## TLS

Pass `tls=True` and the connector encrypts the connection and checks the server's certificate:

```python
dial = connector("example.com", 443, tls=True, radio=radio)
```

Drive it exactly as in [Getting started](#getting-started).  With no `context=`, each runtime checks certificates against its own list of trusted certificate authorities (CAs):

| Runtime | Trusted CAs |
|---|---|
| CircuitPython | The CA bundle built into the firmware. |
| CPython | The operating system's trust store, through `ssl.create_default_context()`. |
| MicroPython | A bundle shipped with this library: 17 widely used roots in 16 KB, covering Let's Encrypt, DigiCert, Amazon, Google, GlobalSign, Sectigo, GoDaddy/Starfield, Entrust, and Microsoft.  Replace it with [`set_default_ca_bundle`](api.md#chumicro_sockets.set_default_ca_bundle) for a private CA or wider coverage. |

To skip certificate checks, for a development server with a self-signed certificate or a captive-portal probe, pass `context=ssl_context_no_verify()`.  The explicit name makes every place that turns checking off easy to find in review.

### Trusting your own certificate authority

A server on your own network usually has a certificate signed by your own CA.  [`ssl_context_with_ca`](api.md#chumicro_sockets.ssl_context_with_ca) builds a context that trusts only the CA certificates you pass in.  They replace the built-in list on every runtime, your laptop's Python included.  Build it once and pass it to every connector:

```python
from chumicro_sockets import connector, ssl_context_with_ca

with open("ca.pem", "rb") as ca_file:
    context = ssl_context_with_ca(ca_file.read())

dial = connector("homelab.local", 443, tls=True, context=context, radio=radio)
```

PEM text works on every runtime.  MicroPython and CPython also accept DER bytes.  The [`tls_with_custom_ca.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets/examples/tls_with_custom_ca.py) example runs this against letsencrypt.org with the CA certificate pasted into the file.

## UDP

UDP sends single messages (datagrams) with no connection to open.  [`udp_socket`](api.md#chumicro_sockets.udp_socket) returns a socket bound to a free local port, ready at once:

```python
import errno

from chumicro_sockets import udp_socket

sock = udp_socket(radio=radio)
sock.setblocking(False)
buffer = bytearray(64)

sock.sendto(b"hello", "192.168.1.10", 12345)  # the receiver's IP address and port

# Inside your loop:
try:
    count, sender = sock.recvfrom_into(buffer)
    print(f"got {bytes(buffer[:count])} from {sender}")
except OSError as error:
    if error.args[0] != errno.EAGAIN:  # EAGAIN: nothing has arrived yet
        raise
```

`sendto` takes the host and port as separate arguments, and `recvfrom_into` returns the byte count plus a `(host, port)` tuple for the sender.  UDP never resends a lost message, so a program that expects a reply decides how long to wait before giving up.  `udp_socket(broadcast=True)` lets `sendto` reach a broadcast address.  The [`udp_echo_client.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets/examples/udp_echo_client.py) example sends a message every 5 seconds and reports each echo, or its absence.

## Accepting connections

[`listener`](api.md#chumicro_sockets.listener) opens a listening socket that never waits.  `accept()` hands back a connected socket and the caller's address, or raises `OSError` with `errno.EAGAIN` when nobody is connecting:

```python
import errno
import time

from chumicro_sockets import listener

server = listener("0.0.0.0", 8080, radio=radio)

while True:
    try:
        client, address = server.accept()
    except OSError as error:
        if error.args[0] != errno.EAGAIN:  # EAGAIN: nobody is connecting right now
            print(f"accept failed: {error!r}")
        client = None

    if client is not None:
        print(f"connection from {address}")
        client.settimeout(5)
        try:
            client.send(b"hello from the board\r\n")
        except OSError as error:
            print(f"send failed: {error!r}")
        client.close()

    time.sleep(0.01)
```

For a TLS listener, pass `tls=True` and a server-side context: [`ssl_context_with_cert_and_key_paths`](api.md#chumicro_sockets.ssl_context_with_cert_and_key_paths) reads the certificate and key from files on every runtime, and [`ssl_context_with_cert_and_key`](api.md#chumicro_sockets.ssl_context_with_cert_and_key) takes them as bytes on MicroPython and CPython.  On CircuitPython the bytes form raises `UnsupportedSSLConfigError`, because CircuitPython loads keys only from files.  With TLS, `accept()` also runs the handshake and waits for it to finish.

## Runner pattern

The loops above wait on each step, which suits a board with one job.  When a board blinks an LED, reads a sensor, and talks to a server at once, a [`chumicro-runner`](https://chumicro.com/ChuMicro/runner/stable/) `Runner` takes turns between them.  Each `runner.tick()` gives every service you added one short turn, and `runner.wait()` then sleeps the CPU until a socket is ready or a timer is due.

A connector is a runner service as it stands: `runner.add(dial)` runs its steps, and your loop checks `dial.state` between turns.  For a round trip that repeats, write it as a generator with the helpers in [`chumicro_sockets.generators`](api.md#chumicro_sockets.generators).  Each `yield from` pauses the round trip until its socket is ready, and the rest of the board runs in the meantime:

```python
from chumicro_runner import Runner
from chumicro_runner.generators import sleep_until
from chumicro_sockets import connector
from chumicro_sockets.generators import connect, recv_until, send_all
from chumicro_timing import ticks_add, ticks_ms

REQUEST = b"GET / HTTP/1.1\r\nHost: example.com\r\n\r\n"


def fetch_forever(radio):
    """Fetch example.com every 30 seconds without stalling the loop."""
    while True:
        try:
            sock = yield from connect(connector("example.com", 80, radio=radio))
            sock.setblocking(False)  # CircuitPython hands back a blocking socket
            try:
                yield from send_all(sock, REQUEST)
                first_line = yield from recv_until(sock, b"\r\n", max_bytes=256)
                print(f"reply: {first_line.decode().strip()}")
            finally:
                sock.close()
        except OSError as error:
            print(f"round trip failed: {error!r}")
        yield from sleep_until(ticks_add(ticks_ms(), 30_000))


runner = Runner()
runner.add_generator(fetch_forever(radio))

while True:
    now_ms = runner.tick()  # every registered service takes one small step
    runner.wait(now_ms)  # then the CPU sleeps until the next event or deadline
```

`connect` drives a connector and returns its socket, `send_all` writes every byte, and `recv_until` reads up to a separator, capped at `max_bytes`.  Behind each pause sits a [`ReadWait`](api.md#chumicro_sockets.waits.ReadWait) or [`WriteWait`](api.md#chumicro_sockets.waits.WriteWait) that tells the runner which socket to watch.  Yield one directly when you write your own helper.  The timing guide's [Choosing a wait](https://chumicro.com/ChuMicro/timing/stable/guide/#choosing-a-wait) table lists these alongside the timer and completion waits.

The networking libraries built on this one (`chumicro-mqtt`, `chumicro-requests`, and the rest) register with a runner the same way, so `runner.add(client)` is the whole wiring.

## Memory notes

`recv_into` and `recvfrom_into` fill a buffer you pass in, so you choose its size and how long it lives.  Allocate one `bytearray` per connection at startup and reuse it for every read.  A loop that allocates a fresh buffer on each pass fragments a small board's heap.

```python
RX_BUFFER = bytearray(256)


def read(sock):
    count = sock.recv_into(RX_BUFFER)
    return memoryview(RX_BUFFER)[:count]
```

The `memoryview` slice hands back the bytes read without copying them.

## Testing

`chumicro_sockets.testing` provides `FakeSocket`, `FakeUDPSocket`, and `FakeSocketConnector`.  They answer the same calls as the real sockets from in-memory buffers, so code that talks over a socket runs under pytest with no network.  [Testing Helpers](testing.md) shows each one in a test.

## Platform notes

| Runtime | TCP | TLS | Custom CA |
|---|---|---|---|
| CPython | ✅ standard-library `socket` | ✅ `ssl.SSLContext` | ✅ `ssl_context_with_ca` |
| MicroPython | ✅ `socket` | ✅ `ssl.SSLContext` (mbedTLS) | ✅ `ssl_context_with_ca` |
| CircuitPython | ✅ `socketpool` plus `radio` | ✅ built-in `ssl.SSLContext` | ✅ `ssl_context_with_ca` |

CircuitPython needs `radio=` on every `connector`, `listener`, and `udp_socket` call: pass `wifi.radio` from the built-in `wifi` module, or `wifi.adapter.radio` from a `chumicro-wifi` `WifiService`.  MicroPython and CPython ignore it.

Some connect steps wait inside a single `tick()`, because the runtime offers no way to run them in pieces:

| Step | CircuitPython | MicroPython | CPython |
|---|---|---|---|
| Address lookup (DNS) | Waits for the answer | Waits for the answer | Waits for the answer |
| TCP connect | Waits, and runs the TLS handshake in the same call | Checked once per tick | Checked once per tick |
| TLS handshake | (part of the TCP step) | Waits for the handshake | One piece per tick |

Every supported board runs current firmware with an `ssl` module, so TLS calls look the same on all of them.  Wifi co-processors without one, such as an AirLift, are outside this library's reach; `adafruit_connection_manager` serves those boards.

### Runtime and chip quirks

These limits come from the runtimes and chips themselves.  They decide how you build certificates and which board can serve TLS:

| Runtime + chip | Quirk | Workaround |
|---|---|---|
| CircuitPython on rp2 (Pi Pico W, Pi Pico 2 W), TLS *server* | `listener(tls=True)` raises `UnsupportedSSLConfigError` up front.  The CYW43 wifi chip's TLS server path fails mid-handshake with `OSError(32)` and leaves the radio stuck until you unplug and replug USB power. | Serve HTTPS from an ESP32-family board, or run MicroPython on the Pi Pico W.  A TLS *client* on CircuitPython rp2 works. |
| MicroPython on rp2 (Pi Pico W) | The mbedTLS build rejects self-signed certificates with `ValueError('invalid cert')`. | Sign the server's certificate with a CA. |
| MicroPython on rp2 (Pi Pico W) | The clock starts at 2021-01-01 after boot, so every certificate looks not yet valid. | Set the clock from NTP (`ntptime.settime()`) before the first TLS connect. |
| MicroPython TLS sockets | The TLS socket has no `settimeout`, so this library's wrapper accepts the call and ignores it. | Use `setblocking(False)` and check for `EAGAIN` instead of relying on a timeout. |
| Stricter mbedTLS builds | Reject a certificate that names only an IP address. | Give the certificate at least one DNS name.  On a home network, `<hostname>.local` works; connect with that name as the host. |

Tested on real CircuitPython and MicroPython boards for both plain TCP and TLS before each release.

## Examples

Each example runs until the board loses power, repeating its work on a timer.  All three are hardware examples that join wifi.

| Example | What it shows |
|---|---|
| [`tcp_roundtrip.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets/examples/tcp_roundtrip.py) | Every 30 seconds, connect to example.com, send an HTTP request, print the first line of the reply, and close.  CircuitPython and MicroPython. |
| [`tls_with_custom_ca.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets/examples/tls_with_custom_ca.py) | The same round trip over TLS, trusting only the CA certificate pasted into the file.  CircuitPython. |
| [`udp_echo_client.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets/examples/udp_echo_client.py) | Every 5 seconds, send a numbered message to an echo server on your computer and print the reply, in a loop that never waits on the network.  CircuitPython and MicroPython. |

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets) · \
[PyPI](https://pypi.org/project/chumicro-sockets/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
