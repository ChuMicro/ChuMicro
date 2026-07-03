"""Bounded in-process publish/subscribe bus with deferred handler dispatch."""

from collections import deque


class Subscription:
    """Subscription handle returned by EventBus.subscribe; pass back to unsubscribe."""

    def __init__(self, bus_id: int, token: int, topic: str) -> None:
        self._bus_id = bus_id
        self.token = token
        self.topic = topic

    def __repr__(self) -> str:
        return f"Subscription(topic={self.topic!r}, token={self.token})"


class EventBus:
    """Queues published events and dispatches them to per-topic handlers on ``handle()``.

    Register as a Runner service: ``check(now_ms)`` reports queued work, ``handle(now_ms)``
    drains. ``now_ms`` is accepted for protocol compliance and unused here.
    """

    # Process-wide monotonic counter giving every bus a distinct id.
    # id(self) would recycle a GC'd bus's address, letting a stale
    # Subscription (its per-bus token restarts at 0) match an unrelated
    # new bus and unsubscribe the wrong handler.
    _bus_counter = 0

    def __init__(self, capacity: int = 64) -> None:
        """Builds a bus that buffers up to ``capacity`` pending events.

        Args:
            capacity: Maximum queued events before ``publish`` counts drops.

        Raises:
            ValueError: When ``capacity`` is less than 1.
        """
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        EventBus._bus_counter += 1
        self._bus_id = EventBus._bus_counter
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
        """Pending event count waiting for ``handle()`` to drain."""
        return len(self._queue)

    def topics(self) -> tuple:
        """Returns a snapshot of every topic with at least one subscriber."""
        return tuple(self._subscribers.keys())

    def subscriber_count(self, topic: str) -> int:
        """Reports how many handlers are currently subscribed to ``topic``."""
        bucket = self._subscribers.get(topic)
        return len(bucket) if bucket else 0

    def subscribe(self, topic: str, handler: object) -> Subscription:
        """Registers ``handler`` against ``topic`` and returns a ``Subscription`` for later removal.

        Args:
            topic: Topic string the handler listens on.
            handler: Callable invoked as ``handler(topic, payload)`` during ``handle()``.

        Returns:
            A ``Subscription`` bound to this bus; pass it to ``unsubscribe`` to remove the handler.
        """
        token = self._next_token
        self._next_token += 1
        bucket = self._subscribers.get(topic)
        if bucket is None:
            bucket = []
            self._subscribers[topic] = bucket
        bucket.append((token, handler))
        return Subscription(bus_id=self._bus_id, token=token, topic=topic)

    def unsubscribe(self, subscription: Subscription) -> bool:
        """Removes the handler bound to ``subscription`` from this bus.

        Args:
            subscription: Handle returned by ``subscribe`` on this bus.

        Returns:
            ``True`` when the handler was found and removed.
            ``False`` when the subscription is foreign to this bus or already gone.
        """
        if subscription._bus_id != self._bus_id:
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
        """Enqueues an event for ``topic`` and increments ``dropped`` when the queue is full.

        Args:
            topic: Topic string subscribers match against.
            *args: Zero args yields a ``None`` payload, one passes through, more pack into a tuple.
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
        """Returns a closure that publishes to ``topic`` on this bus when called."""
        def _publish(*args: object) -> None:
            self.publish(topic, *args)
        return _publish

    def check(self, now_ms: int) -> bool:
        """Returns ``True`` when at least one event is queued for ``handle()`` to drain."""
        return len(self._queue) > 0

    def handle(self, now_ms: int) -> int:
        """Drains the events queued at entry, invokes matching handlers, and returns the drain count.

        Handler exceptions are swallowed and bump ``handler_errors``.
        An event a handler publishes during dispatch is left for the
        next ``handle()`` call, so a handler that republishes to its own
        topic cannot loop this call forever.
        """
        drained = 0
        delivered = 0
        # Snapshot the drain budget: only events already queued at entry
        # are drained this call.  Draining while the queue is non-empty
        # would dispatch events a handler publishes mid-call in the same
        # call, and a self-republishing handler would never let handle()
        # return.
        pending = len(self._queue)
        for _ in range(pending):
            topic, payload = self._queue.popleft()
            bucket = self._subscribers.get(topic)
            if bucket:
                # Dispatch from an immutable snapshot so subscription
                # changes a handler makes mid-dispatch don't shift the
                # iteration: a handler subscribed now is absent from the
                # snapshot (waits for the next event), and a handler
                # unsubscribed now (itself or a peer) is dropped before
                # its turn by the liveness check below rather than
                # shifting a later handler out of its slot.
                for token, handler in tuple(bucket):
                    live = False
                    for current_token, _current_handler in bucket:
                        if current_token == token:
                            live = True
                            break
                    if not live:
                        continue
                    try:
                        handler(topic, payload)
                    except Exception:  # noqa: BLE001
                        self.handler_errors += 1
                    delivered += 1
            drained += 1
        self.drained += drained
        self.delivered += delivered
        return drained

    def clear(self) -> None:
        """Empties the pending queue without invoking any handler; lifetime counters survive."""
        # Drain in place rather than rebinding a fresh deque: MicroPython
        # and CircuitPython deques have no clear(), and reallocating the
        # ring buffer mid-runtime churns the heap.
        queue = self._queue
        while queue:
            queue.popleft()
