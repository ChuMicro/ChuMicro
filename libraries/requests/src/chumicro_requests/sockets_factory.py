"""Default :mod:`chumicro_sockets` wiring for :class:`chumicro_requests.HttpClient`.

Helpers that import a chumicro core-infrastructure library live in
their own submodule — the package's ``__init__.py`` does **not**
import this one.  Users who want the default wiring opt in
explicitly::

    from chumicro_requests import HttpClient
    from chumicro_requests.sockets_factory import chumicro_sockets_factory

    client = HttpClient(connection_factory=chumicro_sockets_factory())
    handle = client.get("http://api.example.com/now", timeout_ms=5000)

Users injecting a custom transport simply skip the import — the
deploy-time AST walker won't follow what isn't referenced, so
:mod:`chumicro_sockets` doesn't ship to the device even though it
sits in ``[project].dependencies``.
"""

import chumicro_sockets


def chumicro_sockets_factory(*, radio=None, ssl_context=None):
    """Return a ``connection_factory`` wired to :mod:`chumicro_sockets`.

    The returned callable matches the
    ``connection_factory(host, port, use_tls) -> TCPClientSocket``
    signature :class:`chumicro_requests.HttpClient` expects.
    Plain TCP routes to :func:`chumicro_sockets.tcp_client_socket`;
    TLS routes to :func:`chumicro_sockets.tls_client_socket` with
    the supplied *ssl_context* (or the runtime default when omitted).

    Args:
        radio: CP-only radio object.  Defaults to ``wifi.radio`` on CP
            (auto-detected); ignored on MP and CPython.  Pass explicitly
            for multi-radio prototypes or boards without a ``wifi`` module.
        ssl_context: Pre-built :class:`ssl.SSLContext` to use for
            ``https://`` connections.  Build via
            :func:`chumicro_sockets.ssl_context_with_ca` for CA pinning;
            ``None`` uses the runtime default
            (``ssl.create_default_context()`` — picks up the system
            trust store, modern ciphers, hostname verification on).

    Returns:
        A ``callable(host, port, use_tls)`` ready to pass into
        :class:`chumicro_requests.HttpClient`'s
        ``connection_factory=`` parameter.
    """
    def factory(host, port, use_tls):
        if use_tls:
            return chumicro_sockets.tls_client_socket(
                host, port, context=ssl_context, radio=radio,
            )
        return chumicro_sockets.tcp_client_socket(host, port, radio=radio)

    return factory
