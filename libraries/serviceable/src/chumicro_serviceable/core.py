"""Core serviceable-pattern abstractions for the Chumicro ecosystem.

Provides two ways to register work with a ``ServiceRunner``:

1. **Gate-based** — a check function decides whether a handler fires.
   Register with ``add(check_fn, handler=fn)`` (both callables) or
   ``add(obj)`` where *obj* has ``.service(now_ms) -> bool`` and
   ``.handle(now_ms)`` methods.
2. **Periodic** — ``add_periodic(handler, period_ms)``: the handler fires
   every *period_ms* milliseconds with no check.

All classes are cross-runtime compatible (CPython, MicroPython, CircuitPython).
"""


class _ServiceEntry:
    """Internal record for a service registered with the runner."""

    __slots__ = ("check_fn", "handler_fn", "heartbeat", "active")

    def __init__(self, check_fn, handler_fn, heartbeat):
        """Create a service entry."""
        self.check_fn = check_fn
        self.handler_fn = handler_fn
        self.heartbeat = heartbeat
        self.active = True


class ServiceHandle:
    """Opaque handle returned by ``ServiceRunner.add()`` or ``add_periodic()``.

    Provides runtime mutation of a registered service: change its period
    or remove it from the runner entirely.

    Read-only properties expose the current state for inspection and
    testing.
    """

    __slots__ = ("_entry", "_runner")

    def __init__(self, entry, runner):
        """Create a handle wrapping *entry* owned by *runner*."""
        self._entry = entry
        self._runner = runner

    @property
    def period_ms(self):
        """Return the service period in milliseconds, or ``None``."""
        if self._entry.heartbeat is None:
            return None
        return self._entry.heartbeat.period_ms

    @property
    def active(self):
        """Return whether the service is still registered."""
        return self._entry.active

    def set_period(self, period_ms):
        """Add, change, or remove the period for this service.

        Pass ``None`` to remove an existing period (service runs every tick).
        A non-None value creates a new ``Heartbeat`` (resetting the timer).
        """
        if period_ms is None:
            self._entry.heartbeat = None
            return
        from chumicro_timing import Heartbeat

        self._entry.heartbeat = Heartbeat(
            period_ms, ticks=self._runner._ticks
        )

    def remove(self):
        """Remove this service from the runner."""
        self._runner._remove_entry(self._entry)

    def __repr__(self):
        """Return a developer-friendly representation."""
        status = "active" if self._entry.active else "removed"
        hb = self._entry.heartbeat
        period = hb.period_ms if hb is not None else None
        return f"ServiceHandle(period_ms={period}, {status})"


class ServiceRunner:
    """Run serviceable components on a tick-based schedule.

    Captures ``ticks_ms()`` once per ``service_once()`` call and passes
    the shared timestamp to every due component, ensuring all components
    see the same moment in time.

    Registration paths:

    - ``add(obj)`` — *obj* has ``.service(now_ms) -> bool`` and
      ``.handle(now_ms)``.  The runner calls ``.service()``; if ``True``,
      ``.handle()`` is queued.
    - ``add(check_fn, handler=fn)`` — callable check gates callable handler.
    - ``add(handler=fn)`` — handler fires every tick (or per period).
    - ``add_periodic(handler, period_ms)`` — fires ``handler(now_ms)``
      every *period_ms* milliseconds.

    ``service_once()`` runs in two phases:

    1. Check all entries (period gate, then check gate) and collect
       due handlers.
    2. Batch-fire all collected handlers.

    Args:
        ticks: Optional tick source (must have a ``ticks_ms`` method).
            Defaults to ``chumicro_timing.ticks_ms``.
    """

    def __init__(self, ticks=None):
        """Create a runner."""
        self._entries = []
        self._pending = []
        self._ticks = ticks
        if ticks is not None:
            self._ticks_ms = ticks.ticks_ms
        else:
            from chumicro_timing import ticks_ms

            self._ticks_ms = ticks_ms

    def add(self, service=None, handler=None, period_ms=None):
        """Register a service with the runner.

        **Object-based** (service only): *service* must have
        ``.service(now_ms) -> bool`` and ``.handle(now_ms)`` methods.

        **Callable-based** (service + handler): *service* is a callable
        ``check_fn(now_ms) -> bool`` that gates ``handler(now_ms)``.

        **Handler-only** (handler, no service): ``handler(now_ms)`` fires
        on every tick (or per period if *period_ms* is set).

        Returns a ``ServiceHandle`` for runtime mutation.

        Args:
            service: Object with ``.service()`` and ``.handle()``, or a
                callable ``check_fn(now_ms) -> bool``.
            handler: Optional callable ``handler(now_ms)``.
            period_ms: Optional interval in milliseconds.
        """
        if handler is not None:
            # Callable-based or handler-only.
            if service is not None and not callable(service):
                check_fn = service.service
            else:
                check_fn = service  # callable or None (handler-only)
            handler_fn = handler
        elif service is not None:
            # Object-based: must have .service() and .handle().
            check_fn = service.service
            handler_fn = service.handle
        else:
            raise ValueError(
                "Provide a service object (with .service() and .handle()) "
                "or a handler callable"
            )

        heartbeat = None
        if period_ms is not None:
            from chumicro_timing import Heartbeat

            heartbeat = Heartbeat(period_ms, ticks=self._ticks)

        entry = _ServiceEntry(check_fn, handler_fn, heartbeat)
        self._entries.append(entry)
        return ServiceHandle(entry, self)

    def add_periodic(self, handler, period_ms):
        """Register a periodic handler with no service check.

        ``handler(now_ms)`` is called every *period_ms* milliseconds.
        Returns a ``ServiceHandle`` for runtime mutation.

        Args:
            handler: Callable ``handler(now_ms)`` to fire periodically.
            period_ms: Interval in milliseconds (required).
        """
        from chumicro_timing import Heartbeat

        heartbeat = Heartbeat(period_ms, ticks=self._ticks)
        entry = _ServiceEntry(None, handler, heartbeat)
        self._entries.append(entry)
        return ServiceHandle(entry, self)

    def service_once(self):
        """Capture time, check services, then batch-fire handlers.

        1. Check each entry (period gate → check gate).
           Collect handlers that should fire.
        2. Batch-fire all collected handlers.

        Returns:
            The ``now_ms`` value used this tick.
        """
        now_ms = self._ticks_ms()
        pending = self._pending

        for entry in self._entries:
            if not entry.active:
                continue
            if entry.heartbeat is not None:
                if not entry.heartbeat.poll(now_ms):
                    continue

            if entry.check_fn is not None:
                if entry.check_fn(now_ms):
                    pending.append(entry.handler_fn)
            else:
                pending.append(entry.handler_fn)

        for handler in pending:
            handler(now_ms)
        pending.clear()

        return now_ms

    def _remove_entry(self, entry):
        """Remove *entry* from the runner (called by ``ServiceHandle``)."""
        entry.active = False
        try:
            self._entries.remove(entry)
        except ValueError:
            pass

