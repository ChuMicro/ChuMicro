# API Reference

A program builds a `WebSocketClient` to connect to a server, or a `WebSocketServer` to accept clients.  The server hands each client over as a `Connection`, which shares the client's send, receive, and close methods.  `WebSocketClient`, `WebSocketServer`, and `Connection` import straight from `chumicro_websockets`.

## `chumicro_websockets`

The exception types, the `WebSocketState` names, the `InboundMessage` record, the `WhenOversized` policy names, and the handshake helper functions.

::: chumicro_websockets

## `chumicro_websockets.client`

`WebSocketClient` with every method, including the ones it shares with `Connection`.

::: chumicro_websockets.client
    options:
      inherited_members: true

## `chumicro_websockets.server`

`WebSocketServer` and the `Connection` it hands to `on_connection`.

::: chumicro_websockets.server
    options:
      inherited_members: true

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/websockets) · \
[PyPI](https://pypi.org/project/chumicro-websockets/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
