"""Core implementation for chumicro-events.

See ``__init__`` for the public API summary.  This module is pure-Python,
imports only ``collections.deque``, and is identical on every supported
runtime.

The event queue is a ``deque(iterable, maxlen)`` rather than a list:
``append`` and ``popleft`` are O(1) and the deque's native ``maxlen``
enforcement gives drop-oldest behavior without the O(n) shift cost
that ``list.pop(0)`` carries on small VMs.
"""

from collections import deque


class Subscription:
    """Opaque handle returned by ``EventBus.subscribe``.

    Carry it back to ``EventBus.unsubscribe`` to detach the handler.
    Subscriptions are not interchangeable across buses — each bus
    issues its own (tracked via the private ``_bus_id`` field, which
    callers should not touch).

    Args:
        bus_id: Identity of the issuing bus (``id(bus)``).
        token: Per-bus monotonic token.
        topic: The topic the subscription was registered against.
    """

    def __init__(self, bus_id: int, token: int, topic: str) -> None:
        self._bus_id = bus_id
        self.token = token
        self.topic = topic

    def __repr__(self) -> str:
        return f"Subscription(topic={self.topic!r}, token={self.token})"


class EventBus:
    """In-process pub/sub bus with bounded queueing and runner-shaped drain.

    Topics are exact-match strings — there is no wildcard or hierarchy
    matching.  Publishers call ``publish(topic, payload)`` (or use a
    callable returned by ``publisher(topic)``) which enqueues a
    ``(topic, payload)`` record.  Subscribers attach via ``subscribe``;
    handlers run when ``handle(now_ms)`` drains the queue.

    The bus does *not* dispatch synchronously.  This decouples
    publishers from subscribers and prevents subscriber callbacks from
    re-entering into the publisher's tick.  Dispatch happens once per
    runner tick when ``handle`` runs; subscribers always observe a
    consistent snapshot of the event stream.

    When the queue is full, ``deque(maxlen)`` drops the **oldest**
    record on append and ``dropped`` is incremented; see ``publish``
    for the rationale.

    Subscriber exceptions never escape ``handle`` — they increment
    ``handler_errors`` and are otherwise swallowed.  A misbehaving
    subscriber must not crash the application.

    Args:
        capacity: Maximum buffered records before drop-oldest kicks
            in.  Must be >= 1.

    Raises:
        ValueError: If *capacity* < 1.
    """

    def __init__(self, capacity: int = 64) -> None:
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self.capacity = capacity
        self._queue = deque((), capacity)
        self._subscribers: dict = {}
        self._next_token = 0
        self.dropped = 0
        self.handler_errors = 0
        self.drained = 0
        self.delivered = 0

    @property
    def buffered(self) -> int:
        """Records currently buffered, awaiting dispatch."""
        return len(self._queue)

    def topics(self) -> tuple:
        """Snapshot of currently-subscribed topics."""
        return tuple(self._subscribers.keys())

    def subscriber_count(self, topic: str) -> int:
        """Number of subscribers currently attached to *topic*.

        Args:
            topic: An exact topic string.
        """
        bucket = self._subscribers.get(topic)
        return len(bucket) if bucket else 0

    def subscribe(self, topic: str, handler: object) -> Subscription:
        """Register *handler* on *topic*.

        The handler is called as ``handler(topic, payload)`` for every
        record matching *topic* that drains through ``handle``.  The
        same handler may be registered against multiple topics; each
        registration produces a distinct ``Subscription`` and a
        distinct dispatch.

        Topics are matched **literally** — no wildcards, no hierarchy
        matching.  A subscription to ``"wifi.state"`` does not see
        records published to ``"wifi.connected"``.  This keeps
        dispatch O(1) per record and avoids the cost of pattern
        compilation; consumers wanting MQTT-style topic filters wire
        them at the publish site instead.

        Args:
            topic: Exact topic string.
            handler: Callable accepting ``(topic, payload)``.

        Returns:
            A ``Subscription`` token.  Pass it to ``unsubscribe`` to
            detach.
        """
        token = self._next_token
        self._next_token += 1
        bucket = self._subscribers.get(topic)
        if bucket is None:
            bucket = []
            self._subscribers[topic] = bucket
        bucket.append((token, handler))
        return Subscription(bus_id=id(self), token=token, topic=topic)

    def unsubscribe(self, subscription: Subscription) -> bool:
        """Detach the subscription.

        Args:
            subscription: A token returned by ``subscribe`` on this
                same bus.

        Returns:
            ``True`` if the subscription was found and removed,
            ``False`` if it was already gone or issued by a different
            bus.
        """
        if subscription._bus_id != id(self):
            return False
        bucket = self._subscribers.get(subscription.topic)
        if not bucket:
            return False
        target = subscription.token
        for index, (token, _handler) in enumerate(bucket):
            if token == target:
                bucket.pop(index)
                if not bucket:
                    del self._subscribers[subscription.topic]
                return True
        return False

    def publish(self, topic: str, *args: object) -> None:
        """Enqueue a record on *topic* with *args* as the payload.

        The record is **not** dispatched immediately.  Subscribers see
        it the next time ``handle`` runs.  When the queue is full,
        ``deque(maxlen)`` drops the **oldest** record on append and
        ``dropped`` is incremented — newest data wins, on the
        assumption that aged-out records are stale and recent events
        are more actionable than ancient backlog.

        The payload is normalized so subscribers see a single
        ``(topic, payload)`` shape regardless of how many positional
        arguments were passed:

        - zero args → ``payload`` is ``None``
        - one arg → ``payload`` is that value (unchanged)
        - two or more args → ``payload`` is the args tuple

        This lets a publisher closure adapt to any service-callback
        arity at the wiring site without forcing subscribers to use
        ``*args``.

        Args:
            topic: Exact topic string.
            *args: Any objects — not interpreted by the bus.
        """
        if len(self._queue) >= self.capacity:
            self.dropped += 1
        if len(args) == 1:
            payload = args[0]
        elif not args:
            payload = None
        else:
            payload = args
        self._queue.append((topic, payload))

    def publisher(self, topic: str) -> object:
        """Return a callable bound to *topic*.

        Useful for wiring service callbacks of any arity into the
        bus.  The returned callable accepts ``*args`` and forwards
        them to ``publish``::

            # service exposes `on_state_change(callback)`; callback
            # is invoked as `callback(old_state, new_state)`.
            wifi.on_state_change(bus.publisher("wifi.state"))

            # service exposes `on_connect` as a replaceable attr;
            # invoked with no arguments.
            mqtt.on_connect = bus.publisher("mqtt.connected")

        Subscribers always see ``handler(topic, payload)``; ``publish``
        packs multi-arg calls into a tuple payload (see ``publish``).

        Args:
            topic: Exact topic string the callable will publish to.
        """
        def _publish(*args: object) -> None:
            self.publish(topic, *args)
        return _publish

    def check(self, now_ms: int) -> bool:
        """Return ``True`` when records are pending dispatch.

        Args:
            now_ms: Current tick value (unused; required by the runner
                contract).
        """
        return len(self._queue) > 0

    def handle(self, now_ms: int) -> int:
        """Drain the queue and dispatch every record to its subscribers.

        Subscribers attached at the moment of dispatch see the event;
        subscribers added later in the same handler call fall past
        the length snapshot and won't fire for the current record.
        Subscriber exceptions are swallowed and counted in
        ``handler_errors``.  Calling ``unsubscribe`` from inside a
        running handler may cause sibling subscribers on the same
        topic to be skipped for the current record — unsubscribe
        outside dispatch to avoid this.

        Args:
            now_ms: Current tick value (unused; required by the runner
                contract).

        Returns:
            The number of records drained from the queue.
        """
        drained = 0
        delivered = 0
        while self._queue:
            topic, payload = self._queue.popleft()
            bucket = self._subscribers.get(topic)
            if bucket:
                # Snapshot the length so subscribers added during
                # dispatch don't fire for this record.  The min()
                # bounds-check covers same-record unsubscribe shrinking
                # the bucket — no IndexError, just a possible skip.
                snapshot_count = len(bucket)
                index = 0
                while index < snapshot_count and index < len(bucket):
                    _token, handler = bucket[index]
                    try:
                        handler(topic, payload)
                    except Exception:  # noqa: BLE001
                        self.handler_errors += 1
                    delivered += 1
                    index += 1
            drained += 1
        self.drained += drained
        self.delivered += delivered
        return drained

    def clear(self) -> None:
        """Drop every queued record without dispatching.

        Resets ``buffered`` to zero.  Subscriptions and counters
        (``dropped``, ``handler_errors``, ``drained``, ``delivered``)
        are not affected.
        """
        # Reassign rather than calling .clear() — MicroPython's deque
        # does not implement clear() in every build.
        self._queue = deque((), self.capacity)
