"""Default :mod:`chumicro_sockets` wiring for :class:`chumicro_http_server.HttpServer`.

Helpers that import a chumicro core-infrastructure library live in
their own submodule — the package's ``__init__.py`` does **not**
import this one.  Users who want the default wiring opt in
explicitly::

    from chumicro_http_server import HttpServer
    from chumicro_http_server.sockets_factory import chumicro_sockets_factory

    server = HttpServer(
        listener_factory=chumicro_sockets_factory(
            {"http_server.bind_port": 8080},
            radio=wifi.radio,
        ),
        handler=handle_request,
    )

:meth:`HttpServer.from_config` reaches for this helper internally
when the caller doesn't supply *listener_factory*, so the
config-driven entry point keeps working without changes — users
who pass their own listener simply never reference this submodule
and :mod:`chumicro_sockets` stays out of their deploy.
"""

from chumicro_config import MissingConfigKey


def chumicro_sockets_factory(config, *, radio=None, ssl_context=None):
    """Return a ``() -> ListeningSocket`` factory wired to :mod:`chumicro_sockets`.

    Reads ``http_server.bind_host`` / ``http_server.bind_port`` from
    *config* (defaults ``"0.0.0.0"`` / ``8080``) and bakes them into
    the returned 0-arg callable.

    TLS resolution:

    1. *ssl_context* supplied → routes through
       :func:`chumicro_sockets.tls_listening_socket` with that context.
       Config TLS paths ignored.
    2. Both ``http_server.tls.cert_path`` and
       ``http_server.tls.key_path`` set in config → builds an
       ``ssl.SSLContext`` via
       :func:`chumicro_sockets.ssl_context_with_cert_and_key_paths`
       and uses :func:`chumicro_sockets.tls_listening_socket`.
    3. Otherwise → plain :func:`chumicro_sockets.tcp_listening_socket`.

    Exactly one of ``cert_path`` / ``key_path`` set is rejected with
    :class:`chumicro_config.MissingConfigKey` — both-or-neither is the
    only valid TLS shape.

    Args:
        config: A :class:`chumicro_config.RuntimeConfig` (typically
            ``chumicro_config.config``) or plain flat dict.  Keys
            read are flat dotted strings.
        radio: CP-only radio object.  Defaults to ``wifi.radio`` on CP
            (auto-detected); ignored on MP and CPython.  Pass explicitly
            for multi-radio prototypes or CP boards without a ``wifi``
            module.
        ssl_context: Pre-built ``ssl.SSLContext`` for TLS.  When
            supplied, the config TLS paths are ignored.

    Returns:
        A ``callable() -> ListeningSocket`` ready to pass into
        :class:`chumicro_http_server.HttpServer`'s
        ``listener_factory=`` parameter.

    Raises:
        chumicro_config.MissingConfigKey: Exactly one of
            ``http_server.tls.cert_path`` /
            ``http_server.tls.key_path`` is set in *config*.

    Lazy-imports :mod:`chumicro_sockets` inside the returned closure
    so this submodule can be unit-tested without the transport on
    PYTHONPATH and so the deploy walker doesn't follow the transport
    import unless the user actually references this submodule.
    """
    host = config.get("http_server.bind_host", "0.0.0.0")
    port = config.get("http_server.bind_port", 8080)
    cert_path = config.get("http_server.tls.cert_path")
    key_path = config.get("http_server.tls.key_path")

    # Half-TLS guard: both keys present or both absent.  Surfacing
    # this loudly beats silently dropping into a plain TCP listener
    # when the user obviously *meant* TLS.
    if (cert_path is None) != (key_path is None):
        missing = (
            "http_server.tls.cert_path" if cert_path is None
            else "http_server.tls.key_path"
        )
        raise MissingConfigKey(
            f"required config key {missing!r} is missing — TLS "
            "requires both cert_path and key_path",
        )

    use_tls = ssl_context is not None or cert_path is not None

    def factory():
        from chumicro_sockets import (  # noqa: PLC0415 - lazy
            ssl_context_with_cert_and_key_paths,
            tcp_listening_socket,
            tls_listening_socket,
        )
        if not use_tls:
            return tcp_listening_socket(host, port, radio=radio)
        context = (
            ssl_context
            if ssl_context is not None
            else ssl_context_with_cert_and_key_paths(
                cert_path=cert_path, key_path=key_path,
            )
        )
        return tls_listening_socket(
            host, port, context=context, radio=radio,
        )

    return factory
