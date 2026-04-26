"""Library-shaped exceptions.

Adapters translate runtime-specific socket errors into these so
downstream libs have one error shape across CP / MP / CPython.

Every supported board ships on-board ``ssl`` so the TLS surface is
uniform; ``UnsupportedSSLConfigError`` is reserved for genuinely
impossible configurations a future adapter (older hardware) might
encounter.
"""


class UnsupportedSSLConfigError(RuntimeError):
    """Raised when the requested TLS configuration isn't supported on this runtime.

    Reserved — today's adapters all accept the same
    :class:`ssl.SSLContext` shape so the error doesn't fire in
    steady state.  Downstream libs ``except`` it so future adapter
    additions for older hardware surface as a structured failure
    instead of an ``AttributeError``.
    """
