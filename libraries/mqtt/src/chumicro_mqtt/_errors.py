"""Library-shaped exceptions.

Adapters and parsers translate transport / wire-format failures into
these so user code has one error shape across runtimes.
"""


class MQTTError(Exception):
    """Base class for every chumicro-mqtt failure."""


class MQTTProtocolError(MQTTError):
    """The broker sent something the spec doesn't allow.

    Examples: malformed remaining-length, undecodable packet type,
    PUBACK with an unknown packet-id.  Always indicates a peer or
    network bug — the right response is usually disconnect + reconnect.
    """


class MQTTConnectError(MQTTError):
    """CONNACK arrived with a non-zero return code.

    The broker rejected the CONNECT.  Common causes: bad credentials,
    unsupported protocol version, server full, client_id refused.
    The numeric ``return_code`` is on the exception so callers can
    branch.
    """

    def __init__(self, message, *, return_code):
        super().__init__(message)
        self.return_code = return_code


class UnsupportedQoSError(MQTTError):
    """User requested QoS 2.

    Decision 0029 Phase 6 §"Allow but don't implement" — the packet
    constants for QoS 2 are reserved but the handlers aren't wired.
    Tests assert this raises so the deferral stays intentional.
    """
