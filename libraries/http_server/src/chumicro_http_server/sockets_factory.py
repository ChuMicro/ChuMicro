"""Default :mod:`chumicro_sockets` wiring for :class:`HttpServer`.

Opt-in submodule — the package's ``__init__.py`` does not import it,
so users who pass their own ``transport_factory`` never pull
:mod:`chumicro_sockets` into the deploy graph.
"""

import chumicro_sockets
from chumicro_config import MissingConfigKey


def chumicro_sockets_factory(config, *, radio=None, ssl_context=None):
    """Build a ``() -> ListeningSocket`` factory from *config*.

    Reads ``http_server.bind_host`` / ``http_server.bind_port`` /
    ``http_server.tls.cert_path`` / ``http_server.tls.key_path``.
    Returns a plain TCP factory unless *ssl_context* is supplied or
    both TLS paths are set, in which case a TLS factory is built.
    Exactly one of ``cert_path`` / ``key_path`` raises
    :class:`chumicro_config.MissingConfigKey`.
    """
    host = config.get("http_server.bind_host", "0.0.0.0")
    port = config.get("http_server.bind_port", 8080)
    cert_path = config.get("http_server.tls.cert_path")
    key_path = config.get("http_server.tls.key_path")

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
