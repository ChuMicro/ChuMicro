"""Connection state + pending-work tracking.

Decision 0029 Phase 6 calls out two problems with the original
pythonProject3 client:

1. ``ProtocolState`` (connection lifecycle) and ``PendingWork``
   (which response we're awaiting) were conflated in a single
   ``_waiting_state`` integer.  The rewrite separates them so a
   ``CONNECTED`` client awaiting a ``SUBACK`` can still send a
   ``PUBLISH`` — the lock used to be too broad.

2. QoS 1 in-flight tracking stored whole ``MQTTMessage`` objects in
   a single ``_publish_retransmit`` boolean.  The rewrite swaps to
   a per-packet-id dict keyed by packet_id so multiple concurrent
   QoS 1 publishes work correctly.

Both are thin and independently exercised.  They live here together
so a single import covers the connection model.
"""


# ---------------------------------------------------------------------------
# ProtocolState — the public lifecycle the user observes
# ---------------------------------------------------------------------------


class ProtocolState:
    """Connection lifecycle states.

    Five values, transitioning monotonically forward except after a
    fault:

      DISCONNECTED  -> CONNECTING  -> CONNECTED  -> DISCONNECTING  -> DISCONNECTED
                                                 \\-> FAILED        -> DISCONNECTED
    """

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTING = "disconnecting"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Awaiting — which broker response a particular work-item is pending
# ---------------------------------------------------------------------------


class Awaiting:
    """Tags identifying which broker response a pending work-item expects."""

    CONNACK = "connack"
    PINGRESP = "pingresp"
    PUBACK = "puback"
    SUBACK = "suback"
    UNSUBACK = "unsuback"


# ---------------------------------------------------------------------------
# In-flight QoS 1 publish tracking
# ---------------------------------------------------------------------------


class InFlightPublish:
    """One outstanding QoS 1 PUBLISH awaiting a PUBACK.

    The original client tried to track this with a global
    ``_publish_retransmit`` boolean and stored whole ``MQTTMessage``
    objects in ``_waiting_state_args`` — broke as soon as two
    publishes were in flight.

    The rewrite uses one of these per packet_id, indexed in
    :class:`InFlightTable`.  Every entry carries the bytes ready to
    re-send (so we don't re-encode on retry), a retry counter, a
    deadline (ticks), and an optional callback that fires once on
    PUBACK.
    """

    __slots__ = (
        "callback",
        "deadline_ticks",
        "packet_bytes",
        "packet_id",
        "retry_count",
    )

    def __init__(self, packet_id, packet_bytes, deadline_ticks, callback=None):
        self.packet_id = packet_id
        self.packet_bytes = packet_bytes
        self.retry_count = 0
        self.deadline_ticks = deadline_ticks
        self.callback = callback


class InFlightTable:
    """Indexed collection of :class:`InFlightPublish`, keyed by packet_id.

    A thin wrapper over a dict — explicit type so call-sites read as
    "MQTT in-flight" rather than "another dict".  The wrapper also
    centralises packet-id allocation: callers ask for the next free
    id, the table picks the next 1-65535 wraparound that isn't
    already in flight.

    Packet-id 0 is reserved (the MQTT spec says so), so allocation
    starts at 1 and wraps at 65535.  An exhausted id-space (every
    65535 ids in flight at once) raises :class:`OverflowError` rather
    than silently reusing.
    """

    def __init__(self):
        self._entries = {}
        self._next_id = 1

    def __len__(self):
        return len(self._entries)

    def __contains__(self, packet_id):
        return packet_id in self._entries

    def __iter__(self):
        return iter(self._entries.values())

    def allocate_id(self):
        """Return the next free packet-id (1-65535)."""
        # Probe up to 65535 ids; bail if all are in flight (extreme).
        for _attempt in range(65535):
            candidate = self._next_id
            self._next_id += 1
            if self._next_id > 65535:
                self._next_id = 1
            if candidate not in self._entries:
                return candidate
        raise OverflowError(
            "MQTT in-flight table is full (65535 packet-ids in use)",
        )

    def add(self, entry):
        """Insert *entry*; raises :class:`KeyError` on packet_id collision."""
        if entry.packet_id in self._entries:
            raise KeyError(f"packet_id {entry.packet_id} already in flight")
        self._entries[entry.packet_id] = entry

    def get(self, packet_id):
        """Return the in-flight entry for *packet_id* or ``None``."""
        return self._entries.get(packet_id)

    def discard(self, packet_id):
        """Remove and return the in-flight entry for *packet_id*, or ``None``."""
        return self._entries.pop(packet_id, None)


# ---------------------------------------------------------------------------
# Outstanding non-publish responses (CONNACK / SUBACK / UNSUBACK / PINGRESP)
# ---------------------------------------------------------------------------


class PendingResponse:
    """A non-publish response we're waiting for.

    SUBACK / UNSUBACK / CONNACK / PINGRESP all share this shape:
    a single tag (:class:`Awaiting`) plus an optional callback that
    fires once on receipt + a deadline.  Multiple of these can be
    in flight at once — Decision 0029 Phase 6 calls out that the
    original client's broad ``_waiting_state`` lock blocked unrelated
    work; the rewrite tracks each pending response independently.
    """

    __slots__ = ("awaiting", "callback", "deadline_ticks", "packet_id")

    def __init__(self, awaiting, deadline_ticks, packet_id=None, callback=None):
        self.awaiting = awaiting
        self.deadline_ticks = deadline_ticks
        self.packet_id = packet_id
        self.callback = callback
