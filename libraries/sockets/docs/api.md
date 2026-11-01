# API Reference

`connector` is the function to start with for a client connection, `listener` for a server, and `udp_socket` for datagrams.  All three live in `chumicro_sockets`, with the `ssl_context_*` functions that build their TLS setup.  `chumicro_sockets.sockets_factory` wraps them as the transport functions other ChuMicro libraries take.  `chumicro_sockets.generators` runs socket I/O inside a generator.  `chumicro_sockets.waits` holds the wait objects those generators yield.

## `chumicro_sockets`

::: chumicro_sockets

## `chumicro_sockets.sockets_factory`

`connector_factory` builds the transport for `chumicro-requests` and the `chumicro-websockets` client.  `fixed_connector_factory` builds it for `chumicro-mqtt`.  `listener_factory` builds it for `chumicro-http-server` and the `chumicro-websockets` server.  `udp_socket_factory` builds it for `chumicro-ntp`.  Each library's `from_config` calls the matching builder itself when no transport is passed.

::: chumicro_sockets.sockets_factory

## `chumicro_sockets.generators`

::: chumicro_sockets.generators

## `chumicro_sockets.waits`

::: chumicro_sockets.waits

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets) · \
[PyPI](https://pypi.org/project/chumicro-sockets/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
