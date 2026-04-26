"""Library-shaped exceptions.

Adapters translate runtime-specific socket errors into these so
downstream libs (``chumicro-mqtt``, future ``chumicro-requests``)
have one error shape across CP / MP / CPython.

The supported boards (Decision 0015) all ship the on-board ``ssl``
module on current LTS firmware, so the TLS surface is uniform —
``UnsupportedSSLConfigError`` is reserved for genuinely impossible
configurations rather than per-runtime quirks.  In practice that
means: a downstream caller hands us a context shape we can't pass
through (e.g. a runtime-specific opaque object on the wrong
runtime).  Today's adapters don't raise it; the class exists so
future adapters can fail loudly + early when needed.
"""


class UnsupportedSSLConfigError(RuntimeError):
    """Raised when the requested TLS configuration isn't supported on this runtime.

    Reserved.  Today's adapters (Pi Pico W, ESP32-S2/S3 native wifi
    on CP; modern MP with mbedTLS; CPython stdlib) all accept the
    same :class:`ssl.SSLContext` shape, so the error doesn't fire
    in steady state.  Downstream libs should still ``except`` it
    so adapter additions for older / different hardware can surface
    as a structured failure instead of a confusing ``AttributeError``.
    """
