# User Guide

## Overview

`chumicro-sockets` connects a board to a network.

- [`connector`](api.md#chumicro_sockets.connector) opens a TCP or TLS connection to a server.
- [`listener`](api.md#chumicro_sockets.listener) accepts connections from other devices.
- [`udp_socket`](api.md#chumicro_sockets.udp_socket) sends and receives single messages.

The same calls work on CircuitPython, MicroPython, and CPython.  Underneath, each runtime uses its own modules: `socketpool` on CircuitPython, `socket` and `ssl` on MicroPython, and the standard library on CPython.

A connector opens its connection in steps, one per call to its `tick()` method.  It looks up the server's address, opens the TCP connection, and finishes the TLS handshake when `tls=True`.  Its `state` reports how far it got and ends at `"ready"` or `"failed"`.  The loop decides when each step runs, so a board can do other work while a connection opens.

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
    dial = connector("example.com", 80, radio=radio)    # returns at once
    while dial.state not in ("ready", "failed"):
        dial.tick(0)                                    # one step per call
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

- **`connector(host, port, radio=radio)`** returns at once with `state` set to `"awaiting_dns"`.  Nothing has touched the network yet.
- **`dial.tick(0)`** runs the next step.  `state` moves through `"awaiting_dns"` and `"awaiting_tcp"`, plus `"awaiting_tls"` on some runtimes when `tls=True`, and stops at `"ready"` or `"failed"`.  The argument is the current time in milliseconds, the value a runner hands every service.  A connector keeps no deadlines, so any number works.
- **`dial.socket`** is the connected socket once `state` is `"ready"`.  The program calls `send` and `recv_into` on it and closes it when done.  A board holds only a few sockets at once, so a loop that leaks one per pass runs out.
- **`dial.last_error`** is the exception behind a `"failed"` state.  The connector has already closed its own socket by then, so the loop prints the error and tries again on the next pass.
- **`dial.cancel()`** gives up on a connect in progress, closes any half-open socket, and sets `state` to `"failed"`.  A connector never times out by itself.

## Choosing how a socket waits

CircuitPython hands back a connected socket in blocking mode.  MicroPython and CPython hand it back non-blocking.  A program sets the mode it wants right after `"ready"`, as the loop above does.

- **`sock.settimeout(seconds)`** makes each `send` and `recv_into` wait up to that long, then raise `OSError`.  It suits a board with one job, as in the loop above.  A blocking read with no timeout would let a server that stops answering stall the board for good.
- **`sock.setblocking(False)`** makes each call return at once.  When nothing has arrived, `recv_into` raises `OSError` with `errno.EAGAIN` as its first argument.  That error means "nothing yet", and a later pass of the loop checks again:

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

`tls=True` makes the connector encrypt the connection and check the server's certificate:

```python
dial = connector("example.com", 443, tls=True, radio=radio)
```

The loop drives it exactly as in [Getting started](#getting-started).  With no `context=`, each runtime checks certificates against its own list of trusted certificate authorities (CAs):

| Runtime | Trusted CAs |
|---|---|
| CircuitPython | The CA bundle built into the firmware. |
| CPython | The operating system's trust store, through `ssl.create_default_context()`. |
| MicroPython | A bundle shipped with this library: 17 widely used roots in 16 KB, covering Let's Encrypt, DigiCert, Amazon, Google, GlobalSign, Sectigo, GoDaddy/Starfield, Entrust, and Microsoft.  [`set_default_ca_bundle`](api.md#chumicro_sockets.set_default_ca_bundle) replaces it for a private CA or wider coverage. |

`context=ssl_context_no_verify()` skips certificate checks, for a development server with a self-signed certificate or a captive-portal probe.  Its explicit name makes every place that turns checking off easy to find in review.

### Trusting your own certificate authority

A server on a home network usually has a certificate signed by a private CA.  [`ssl_context_with_ca`](api.md#chumicro_sockets.ssl_context_with_ca) builds a context that trusts only the CA certificates passed in.  They replace the built-in list on every runtime, CPython included.  One context serves every connector:

```python
from chumicro_sockets import connector, ssl_context_with_ca

with open("ca.pem", "rb") as ca_file:
    context = ssl_context_with_ca(ca_file.read())

dial = connector("homelab.local", 443, tls=True, context=context, radio=radio)
```

PEM text works on every runtime.  MicroPython and CPython also accept DER bytes.  The [`tls_with_custom_ca.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets/examples/tls_with_custom_ca.py) example runs this against letsencrypt.org with the CA certificate pasted into the file.

## UDP

UDP sends single messages, called datagrams, with no connection to open.  [`udp_socket`](api.md#chumicro_sockets.udp_socket) returns a socket bound to a free local port, ready at once:

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

`sendto` takes the host and port as separate arguments.  `recvfrom_into` returns the byte count plus a `(host, port)` tuple for the sender.  UDP never resends a lost message, so a program that expects a reply decides how long to wait before giving up.  `udp_socket(broadcast=True)` lets `sendto` reach a broadcast address.  The [`udp_echo_client.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets/examples/udp_echo_client.py) example sends a message every 5 seconds and reports each echo, or its absence.

## Accepting connections

[`listener`](api.md#chumicro_sockets.listener) opens a listening socket that never waits.  `accept()` hands back a connected socket and the caller's address, or raises `OSError` with `errno.EAGAIN` when nobody is connecting:

```python
import errno
import time

from chumicro_sockets import listener

radio = None    # wifi.radio on CircuitPython

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

A TLS listener takes `tls=True` and a server-side context.  [`ssl_context_with_cert_and_key_paths`](api.md#chumicro_sockets.ssl_context_with_cert_and_key_paths) reads the certificate and key from files on every runtime.  [`ssl_context_with_cert_and_key`](api.md#chumicro_sockets.ssl_context_with_cert_and_key) takes them as bytes on MicroPython and CPython.  On CircuitPython, the bytes form raises `UnsupportedSSLConfigError`, because CircuitPython loads keys only from files.  With TLS, `accept()` also runs the handshake and waits for it to finish.

## Runner pattern

The loops above wait on each step, which suits a board with one job.  A board that blinks an LED, reads a sensor, and talks to a server at once shares its time through a [`chumicro-runner`](https://chumicro.com/ChuMicro/runner/stable/guide/) `Runner`.

A connector is a runner service as it stands.  `runner.add(dial)` runs its steps, and the loop checks `dial.state` between turns.  A round trip that repeats reads best as a [generator task](https://chumicro.com/ChuMicro/runner/stable/guide/#generator-tasks) built from the helpers in [`chumicro_sockets.generators`](api.md#chumicro_sockets.generators).  Each `yield from` pauses the round trip until its socket is ready, while the rest of the board runs:

```python
from chumicro_runner import Runner
from chumicro_runner.generators import sleep_until
from chumicro_sockets import connector
from chumicro_sockets.generators import connect, recv_until, send_all
from chumicro_timing import ticks_add, ticks_ms

radio = None    # wifi.radio on CircuitPython

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

`connect` drives a connector and returns its socket.  `send_all` writes every byte.  `recv_until` reads up to a separator, capped at `max_bytes`, so a peer that never sends the separator cannot fill the board's memory.  A failed step raises `OSError` at the line that failed, so a plain `try` / `except` handles a dropped connection.

Behind each pause sits a [`ReadWait`](api.md#chumicro_sockets.waits.ReadWait) or [`WriteWait`](api.md#chumicro_sockets.waits.WriteWait) that tells the runner which socket to watch.  A custom helper yields one directly ([What a generator task yields](https://chumicro.com/ChuMicro/runner/stable/guide/#what-a-generator-task-yields)).  The timing guide's [Choosing a wait](https://chumicro.com/ChuMicro/timing/stable/guide/#choosing-a-wait) table lists these alongside the timer and completion waits.

The networking libraries built on this one, such as `chumicro-mqtt` and `chumicro-requests`, register with a runner the same way, so `runner.add(client)` is the whole wiring.

## Memory notes

`recv_into` and `recvfrom_into` fill a buffer the program passes in, so the program chooses its size and how long it lives.  One `bytearray` per connection, allocated at startup and reused for every read, keeps the heap steady.  A loop that allocates a fresh buffer on each pass fragments a small board's heap.

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

CircuitPython needs `radio=` on every `connector`, `listener`, and `udp_socket` call.  The radio is `wifi.radio` from the built-in `wifi` module, or `wifi.adapter.radio` from a `chumicro-wifi` `WifiService`.  MicroPython and CPython ignore it.

Some connect steps wait inside a single `tick()`, because the runtime offers no way to run them in pieces:

| Step | CircuitPython | MicroPython | CPython |
|---|---|---|---|
| Address lookup (DNS) | Waits for the answer | Waits for the answer | Waits for the answer |
| TCP connect | Waits, and runs the TLS handshake in the same call | Checked once per tick | Checked once per tick |
| TLS handshake | (part of the TCP step) | Waits for the handshake | One piece per tick |

Every supported board runs current firmware with an `ssl` module, so TLS calls look the same on all of them.  This library leaves out wifi co-processors without one, such as an AirLift.  `adafruit_connection_manager` serves those boards.

### Runtime and chip quirks

| Runtime + chip | Quirk | Workaround |
|---|---|---|
| CircuitPython on rp2 (Pi Pico W, Pi Pico 2 W), TLS *server* | `listener(tls=True)` raises `UnsupportedSSLConfigError` up front.  The CYW43 wifi chip's TLS server path fails mid-handshake with `OSError(32)` and leaves the radio stuck until USB power is unplugged and replugged. | Serve HTTPS from an ESP32-family board, or run MicroPython on the Pi Pico W.  A TLS *client* on CircuitPython rp2 works. |
| MicroPython on rp2 (Pi Pico W) | The mbedTLS build rejects self-signed certificates with `ValueError('invalid cert')`. | Sign the server's certificate with a CA. |
| MicroPython on rp2 (Pi Pico W) | The clock starts at 2021-01-01 after boot, so every certificate looks not yet valid. | Set the clock from NTP (`ntptime.settime()`) before the first TLS connect. |
| MicroPython TLS sockets | The TLS socket has no `settimeout`, so this library's wrapper accepts the call and ignores it. | Use `setblocking(False)` and check for `EAGAIN` instead of relying on a timeout. |
| Stricter mbedTLS builds | Reject a certificate that names only an IP address. | Give the certificate at least one DNS name.  On a home network, `<hostname>.local` works.  The connector then takes that name as the host. |

## Examples

Each example runs until the board loses power, repeating its work on a timer.  All three are hardware examples that join wifi.

| Example | What it shows |
|---|---|
| [`tcp_roundtrip.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets/examples/tcp_roundtrip.py) | Every 30 seconds, connect to example.com, send an HTTP request, print the first line of the reply, and close.  CircuitPython and MicroPython. |
| [`tls_with_custom_ca.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets/examples/tls_with_custom_ca.py) | The same round trip over TLS, trusting only the CA certificate pasted into the file.  CircuitPython. |
| [`udp_echo_client.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets/examples/udp_echo_client.py) | Every 5 seconds, send a numbered message to an echo server on a computer and print the reply, in a loop that never waits on the network.  CircuitPython and MicroPython. |

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets) · \
[PyPI](https://pypi.org/project/chumicro-sockets/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
