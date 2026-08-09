# API Reference

## `chumicro_sockets`

The three socket entry points (`connector`, `listener`, `udp_socket`), the SSL-context builders behind their `tls=` flag, and `set_default_ca_bundle` for replacing the shipped trust store.

::: chumicro_sockets

## `chumicro_sockets.sockets_factory`

Builders that turn hosts, ports, and TLS material into the transport callable a networking library asks for at construction.  `connector_factory` returns the `(host, port, use_tls)` callable `chumicro-requests` and `chumicro-websockets` expect, and `fixed_connector_factory` pins one endpoint and returns the no-argument form `chumicro-mqtt` takes.  `listener_factory` returns the listening-socket callable the HTTP and WebSocket servers take, and `udp_socket_factory` returns a fresh bound datagram socket per call, the way `chumicro-ntp` uses it.

::: chumicro_sockets.sockets_factory

## `chumicro_sockets.generators`

Socket I/O as `yield from` steps for generators registered with `Runner.add_generator`: `connect` drives a connector until it hands back a connected socket, `send_all` writes a whole buffer, and `recv_until` reads a delimited chunk.  Each one suspends whenever the socket would block, so the rest of the device keeps running while it waits.

::: chumicro_sockets.generators

## `chumicro_sockets.waits`

The two wait objects the generator helpers yield.  `ReadWait(sock)` and `WriteWait(sock)` tell the runner which socket to poll and, given a `deadline_ms`, when to give up.  Yield them directly when you write a generator helper of your own.

::: chumicro_sockets.waits

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets) · \
[PyPI](https://pypi.org/project/chumicro-sockets/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
