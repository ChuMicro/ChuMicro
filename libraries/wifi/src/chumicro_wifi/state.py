"""``WifiState`` — five-value state machine for ``WifiService``.

State transitions (Decision 0029 §wifi-ownership-stance,
``plans/workstreams/project-workspace.md`` Phase 3a)::

    DISCONNECTED -> CONNECTING -> CONNECTED
                        |            |
                        |            v
                        |       RECONNECTING (on link-down)
                        |            |
                        v            v
                     FAILED <--- backoff exhausted (if reconnect_max set)

Plain-string sentinel values (no `enum` import — unavailable on
some MicroPython boards) so the contract is portable across CP, MP,
and CPython.  Compare via ``state == WifiState.CONNECTED`` etc.
"""


class WifiState:
    """String-sentinel state names.  Do not instantiate."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"

    ALL = (DISCONNECTED, CONNECTING, CONNECTED, RECONNECTING, FAILED)
