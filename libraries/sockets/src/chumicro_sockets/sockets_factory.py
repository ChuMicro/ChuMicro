"""``chumicro_sockets.sockets_factory`` builds the transport functions that network clients
and servers take at construction.

Each builder captures a radio and TLS material once and returns a function
that opens a fresh connector, listening socket, or UDP socket on every call.
Every builder takes ``radio``, the CircuitPython ``wifi.radio`` object, which
MicroPython and CPython ignore.

A program that supplies its own transport everywhere lists
``"sockets_factory"`` in ``__chumicro_skip_factories__``.  The deployer then
leaves this module off the board, and with it ``chumicro_sockets``.
"""

import chumicro_sockets


def connector_factory(*, radio=None, ssl_context=None):
    """Return a function ``factory(host, port, use_tls)`` that builds a new ``connector`` per call.

    An HTTP or WebSocket client takes the function as its transport and calls
    it once per connection.  ``ssl_context`` is the ``ssl.SSLContext`` for
    connections with ``use_tls=True``.  ``None`` checks the server against the
    runtime's default certificate store.
    """
    def factory(host, port, use_tls):
        return chumicro_sockets.connector(
            host, port,
            tls=use_tls,
            context=ssl_context if use_tls else None,
            radio=radio,
        )

    return factory


def fixed_connector_factory(host, port, *, use_tls=False, radio=None, ssl_context=None):
    """Return a function ``factory()`` that builds a new ``connector`` to ``host`` and ``port`` per call.

    A client that always dials one server, such as an MQTT client, takes this
    form.  ``use_tls=True`` dials TLS and, with no ``ssl_context``, checks the
    server against the runtime's default certificate store.  Passing an
    ``ssl_context`` turns TLS on even when ``use_tls`` is ``False``.
    """
    def factory():
        return chumicro_sockets.connector(
            host, port,
            tls=use_tls or ssl_context is not None,
            context=ssl_context,
            radio=radio,
        )

    return factory


def listener_factory(host, port, *, radio=None, ssl_context=None,
                     cert_path=None, key_path=None):
    """Return a function ``factory()`` that opens a new ``listener`` on ``host`` and ``port`` per call.

    An HTTP or WebSocket server takes the function and calls it when it starts
    listening.  A ``host`` of ``"0.0.0.0"`` listens on every interface.  The
    listener speaks TLS when ``ssl_context`` or ``cert_path`` is set, and
    ``ssl_context`` wins when both are.  ``cert_path`` and ``key_path`` name
    the PEM certificate and private-key files on the board, and each call
    loads them through ``ssl_context_with_cert_and_key_paths``.
    """
    use_tls = ssl_context is not None or cert_path is not None

    def factory():
        if not use_tls:
            return chumicro_sockets.listener(host, port, radio=radio)
        context = (
            ssl_context
            if ssl_context is not None
            else chumicro_sockets.ssl_context_with_cert_and_key_paths(
                cert_path=cert_path, key_path=key_path,
            )
        )
        return chumicro_sockets.listener(
            host, port, tls=True, context=context, radio=radio,
        )

    return factory


def udp_socket_factory(*, radio=None):
    """Return a function ``factory()`` that opens a new non-blocking UDP socket per call.

    Each socket comes from ``udp_socket(radio=radio)``, bound to a free port
    on every interface.  The factory switches it to non-blocking mode, so
    ``recvfrom_into`` raises ``OSError`` with ``EAGAIN`` when no datagram is
    waiting.
    """
    def factory():
        udp_socket = chumicro_sockets.udp_socket(radio=radio)
        udp_socket.setblocking(False)
        return udp_socket

    return factory
