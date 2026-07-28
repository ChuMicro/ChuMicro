# Testing Helpers

`chumicro_sockets.testing` ships in-memory socket doubles so network code can be tested without a network.  `FakeSocket` answers the same `send` / `recv_into` / `close` / `setblocking` calls a real socket answers, `FakeUDPSocket` does the same for datagrams, and `FakeSocketConnector` stands in for the tick-driven dial a connector performs.  The module declares itself test support, so the deploy walker and the bundle builder drop it and it never lands on a microcontroller.

## Usage

```python
from chumicro_sockets.testing import FakeSocket


def test_handshake_writes_correct_prefix():
    sock = FakeSocket()
    # Script the response the server would have sent.
    sock.enqueue_recv(b"\x20\x02\x00\x00")  # MQTT CONNACK packet

    client = MQTTClient(sock)
    client.connect()

    # Assert what we sent.
    assert sock.sent.startswith(b"\x10")  # MQTT CONNECT packet prefix
```

`FakeSocket.sent` is a `bytearray` that accumulates every `send()` call.  `enqueue_recv(chunk)` queues a chunk for the next `recv_into()`; multiple chunks queue in FIFO order.  `enqueue_eagain_for_send(count)` and `enqueue_eagain_for_recv(count)` script `OSError(EAGAIN)` raises so non-blocking-loop logic can be exercised deterministically.

A short read pushes the unconsumed tail back on the queue head, the way a real socket splits a stream across reads:

```python
sock = FakeSocket()
sock.enqueue_recv(b"abcdef")
buffer = bytearray(8)
sock.recv_into(buffer, 3)   # reads "abc"; "def" still queued
sock.recv_into(buffer, 8)   # reads "def"
```

## Using these fakes in your own tests

Your test suite imports them straight from the installed package, the same way this library's own tests do:

```python
from chumicro_sockets.testing import FakeSocket
```

Project convention: libraries that expose injectable services ship their own test fakes alongside the production code.

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
