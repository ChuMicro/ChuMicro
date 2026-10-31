# Testing Helpers

`chumicro_sockets.testing` ships in-memory stand-ins for real sockets, so code that talks over a network runs under pytest with no network attached.  `FakeSocket` answers the same `send`, `recv_into`, `close`, `setblocking`, and `settimeout` calls as a connected TCP socket.  `FakeUDPSocket` does the same for `sendto` and `recvfrom_into`, and `FakeSocketConnector` plays a connector whose steps you script.  The module marks itself as test support, so deploys and the bundle builder leave it off the board.

## Testing code that uses a TCP socket

Pass a `FakeSocket` wherever your code expects a connected socket.  Queue what the server would send with `enqueue_recv`, then check what your code sent in `sent`:

```python
from chumicro_sockets.testing import FakeSocket


def ask_status(sock):
    """Send STATUS and return the first line of the reply."""
    sock.send(b"STATUS\r\n")
    buffer = bytearray(64)
    count = sock.recv_into(buffer)
    return bytes(buffer[:count]).split(b"\r\n")[0]


def test_ask_status_sends_the_command_and_returns_the_reply():
    sock = FakeSocket()
    sock.enqueue_recv(b"OK ready\r\n")  # what the server sends back

    assert ask_status(sock) == b"OK ready"
    assert sock.sent == b"STATUS\r\n"
```

`sent` is a `bytearray` holding every byte passed to `send()`.  Each `enqueue_recv(chunk)` call queues one chunk for a later `recv_into()`, in order.  With nothing queued, `recv_into()` raises `OSError(EAGAIN)`, the way a non-blocking socket says "nothing yet".  After `simulate_peer_close()`, it returns `0` once the queue is empty, the way a real socket reports that the server hung up.  `enqueue_eagain_for_send(count)` and `enqueue_eagain_for_recv(count)` make the next `count` calls raise `OSError(EAGAIN)`, so a test can walk your code through its retry path.

A read smaller than the queued chunk leaves the rest queued, the way a real socket splits a stream across reads:

```python
sock = FakeSocket()
sock.enqueue_recv(b"abcdef")
buffer = bytearray(8)
sock.recv_into(buffer, 3)   # reads b"abc"; b"def" stays queued
sock.recv_into(buffer, 8)   # reads b"def"
```

## Testing UDP code

`FakeUDPSocket` records each `sendto` as a `(data, host, port)` tuple in `sent`, and `enqueue_recv` queues a datagram along with the address it came from:

```python
from chumicro_sockets.testing import FakeUDPSocket


def test_ping_gets_a_pong():
    sock = FakeUDPSocket()
    sock.enqueue_recv(b"pong", host="192.168.1.10", port=12345)

    sock.sendto(b"ping", "192.168.1.10", 12345)
    buffer = bytearray(16)

    assert sock.recvfrom_into(buffer) == (4, ("192.168.1.10", 12345))
    assert sock.sent == [(b"ping", "192.168.1.10", 12345)]
```

## Scripting a connector

`FakeSocketConnector` takes a list of actions, and each `tick()` plays the next one: `"dns_ok"`, `"tcp_pending"`, `"tcp_ok"`, `"tls_pending"`, `"tls_ok"`, or `"fail:<message>"`, which sets `last_error` to `OSError("<message>")`.  A `tick()` with no actions left changes nothing, so script every run to `"ready"` or `"failed"`.  Once ready, `socket` is the `FakeSocket` you passed in:

```python
from chumicro_sockets.testing import FakeSocket, FakeSocketConnector


def open_socket(dial):
    """Tick *dial* until it finishes; return its socket, or None on failure."""
    while dial.state not in ("ready", "failed"):
        dial.tick(0)
    return dial.socket if dial.state == "ready" else None


def test_open_socket_returns_the_connected_socket():
    sock = FakeSocket()
    dial = FakeSocketConnector(actions=["dns_ok", "tcp_pending", "tcp_ok"], socket=sock)

    assert open_socket(dial) is sock


def test_open_socket_returns_none_when_the_connect_fails():
    dial = FakeSocketConnector(actions=["dns_ok", "fail:connection refused"])

    assert open_socket(dial) is None
    assert str(dial.last_error) == "connection refused"
```

With `tls=True`, `"tcp_ok"` moves the fake to `"awaiting_tls"`, and `"tls_ok"` finishes it.

## API Reference

::: chumicro_sockets.testing

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets) · \
[PyPI](https://pypi.org/project/chumicro-sockets/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
