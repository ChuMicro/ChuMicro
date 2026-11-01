# Testing Helpers

`chumicro_sockets.testing` holds in-memory stand-ins for network sockets, so code that talks over a network runs under pytest with no network attached.  `FakeSocket` replaces a connected TCP socket, `FakeUDPSocket` replaces a UDP socket, and `FakeSocketConnector` replaces the connector that opens a TCP or TLS connection one step per tick.  `pip install chumicro-sockets pytest` installs everything the tests on this page import.  Project deploys and the board bundles leave the module out.

## The smallest test

Save this as `test_status_command.py` and run `pytest test_status_command.py`:

```python
from chumicro_sockets.testing import FakeSocket


def ask_status(sock):
    sock.send(b"STATUS\r\n")
    buffer = bytearray(64)
    count = sock.recv_into(buffer)
    return bytes(buffer[:count]).split(b"\r\n")[0]


def test_ask_status_sends_the_command_and_reads_the_reply():
    sock = FakeSocket()
    sock.enqueue_recv(b"OK ready\r\n")

    assert ask_status(sock) == b"OK ready"
    assert sock.sent == b"STATUS\r\n"
```

`ask_status` takes its socket as an argument, so the test hands it a `FakeSocket`.  `enqueue_recv` queues what the server sends back.  `sent` collects what the code sent.

## `FakeSocket`

`FakeSocket` answers the same `send`, `recv_into`, `close`, `setblocking`, and `settimeout` calls as a connected TCP socket.

| Call or attribute | What it does |
|---|---|
| `enqueue_recv(chunk)` | Queues one chunk of bytes for later `recv_into()` calls, in order. |
| `simulate_peer_close()` | Plays the server hanging up: once the queue is empty, `recv_into()` returns `0`. |
| `enqueue_eagain_for_recv(count=1)` | Makes the next `count` `recv_into()` calls raise `OSError(EAGAIN)`. |
| `enqueue_eagain_for_send(count=1)` | Makes the next `count` `send()` calls raise `OSError(EAGAIN)`. |
| `sent` | A `bytearray` of every byte passed to `send()`. |
| `closed` | `True` after `close()`.  Any later `send()` or `recv_into()` raises `OSError(EBADF)`. |
| `blocking` | The mode the last `setblocking()` or `settimeout()` set. |

A read smaller than the queued chunk leaves the rest queued, the way a real socket splits a stream across reads:

```python
from chumicro_sockets.testing import FakeSocket


def test_a_short_read_leaves_the_rest_queued():
    sock = FakeSocket()
    sock.enqueue_recv(b"abcdef")
    buffer = bytearray(8)

    assert sock.recv_into(buffer, 3) == 3
    assert bytes(buffer[:3]) == b"abc"
    assert sock.recv_into(buffer, 8) == 3
    assert bytes(buffer[:3]) == b"def"
```

With nothing queued, `recv_into()` raises `OSError(EAGAIN)`, the way a non-blocking socket says nothing has arrived yet.  After `simulate_peer_close()` it returns `0`:

```python
import errno

from chumicro_sockets.testing import FakeSocket


def test_an_empty_socket_waits_until_the_server_hangs_up():
    sock = FakeSocket()
    buffer = bytearray(8)
    try:
        sock.recv_into(buffer)
        raise AssertionError("expected EAGAIN")
    except OSError as error:
        assert error.errno == errno.EAGAIN

    sock.simulate_peer_close()
    assert sock.recv_into(buffer) == 0
```

## `FakeUDPSocket`

`FakeUDPSocket(bind_host="0.0.0.0", bind_port=54321)` answers `sendto`, `recvfrom_into`, `getsockname`, `close`, `setblocking`, and `settimeout`.

| Call or attribute | What it does |
|---|---|
| `enqueue_recv(data, *, host="0.0.0.0", port=0)` | Queues one datagram and the address it came from. |
| `enqueue_eagain_for_recv(count=1)`, `enqueue_eagain_for_send(count=1)` | Make the next `count` calls raise `OSError(EAGAIN)`. |
| `sent` | A list of `(data, host, port)` tuples, one per `sendto()`. |
| `getsockname()` | Returns `(bind_host, bind_port)`. |

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

## `FakeSocketConnector`

`FakeSocketConnector(host="test.example", port=1883, *, tls=False, actions=None, socket=None)` plays a connector from a script.  Each `tick()` plays the next entry in `actions`:

| Action | Effect |
|---|---|
| `"dns_ok"` | Finishes the name lookup.  `state` moves to `"awaiting_tcp"`. |
| `"tcp_pending"` | Leaves the TCP connect in progress. |
| `"tcp_ok"` | Finishes the TCP connect.  `state` moves to `"ready"`, or to `"awaiting_tls"` with `tls=True`. |
| `"tls_pending"` | Leaves the TLS handshake in progress. |
| `"tls_ok"` | Finishes the TLS handshake.  `state` moves to `"ready"`. |
| `"fail:<message>"` | Fails the connect.  `state` moves to `"failed"` and `last_error` holds `OSError("<message>")`. |

Once `state` is `"ready"`, `socket` holds the `FakeSocket` passed as `socket=`.  A `tick()` with no actions left changes nothing, so each script ends in `"ready"` or `"failed"`.  An action that does not fit the current state raises `AssertionError`.

```python
from chumicro_sockets.testing import FakeSocket, FakeSocketConnector


def open_socket(dial):
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

`HttpClient` from `chumicro-requests` and `WebSocketClient` from `chumicro-websockets` open connections through a `transport_factory`.  A test passes them a factory that returns a `FakeSocketConnector`.

## API reference

::: chumicro_sockets.testing

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets) · \
[PyPI](https://pypi.org/project/chumicro-sockets/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
