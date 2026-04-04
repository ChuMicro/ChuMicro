"""Tick-based service loop for the Chumicro ecosystem.

Provides a ``ServiceRunner`` that captures the current timestamp once
per tick and distributes it to all registered components.  This ensures
every component in a main loop sees the same moment in time, avoiding
drift between independent ``ticks_ms()`` calls.

Components that need per-tick work implement a duck-typed contract::

    def service(self, now_ms):
        \"\"\"Do one tick of work given the shared timestamp.\"\"\"

No base class or import from this library is required.
"""


class ServiceRunner:
    """Capture time once per tick and service all registered components.

    On each ``tick()`` call the runner reads ``ticks_ms()`` once and
    passes the resulting timestamp to every registered component's
    ``service(now_ms)`` method.  The same timestamp is returned so user
    code can use it for passive checks like ``Heartbeat.poll(now_ms)``.

    Args:
        services: Optional iterable of components with a ``service(now_ms)``
            method.  Components can also be added later via ``add()``.
        ticks: Optional tick source (must have a ``ticks_ms`` method).
            Defaults to ``chumicro_timing.ticks_ms``.
    """

    def __init__(self, services=None, ticks=None):
        """Create a runner with optional initial *services* and *ticks* source."""
        self._services = list(services) if services else []
        if ticks is not None:
            self._ticks_ms = ticks.ticks_ms
        else:
            from chumicro_timing import ticks_ms

            self._ticks_ms = ticks_ms

    def add(self, service):
        """Register *service* to be called on each tick."""
        self._services.append(service)

    def tick(self):
        """Capture time, service all components, and return the shared timestamp.

        Returns:
            The ``now_ms`` value passed to all components this tick.
        """
        now_ms = self._ticks_ms()
        for svc in self._services:
            svc.service(now_ms)
        return now_ms
