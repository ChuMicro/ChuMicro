"""``WifiState`` — five-value state machine for ``WifiService``.

State transitions::

    DISCONNECTED -> CONNECTING -> CONNECTED
                        |            |
                        |            v
                        |       RECONNECTING (on link-down)
                        |            |
                        v            v
                     FAILED <--- backoff exhausted (if reconnect_max set)

Plain-string sentinels (no ``enum`` import — unavailable on some
MicroPython boards).  Compare via ``state == WifiState.CONNECTED``.
"""


class WifiState:
    """String-sentinel state names.  Do not instantiate."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"
