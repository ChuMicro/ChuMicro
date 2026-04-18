"""Seconds-domain time source wrapping Python's ``time`` module.

``RealTime`` is the production counterpart to ``FakeTime``.  It
provides the same ``monotonic()`` / ``sleep()`` interface backed by
the real ``time`` module.

Production code accepts a generic time dependency via constructor
injection.  The default is ``RealTime()``; tests inject ``FakeTime()``
to eliminate wall-clock waits.
"""

import time as _time_module


class RealTime:
    """Thin wrapper around Python's ``time`` module.

    Provides ``monotonic()`` and ``sleep()`` — the same interface as
    ``FakeTime`` — so production code and test code can swap
    implementations via constructor injection.

    This is the default used when no fake is injected::

        from chumicro_abstractions import RealTime

        class MyService:
            def __init__(self, *, time=None):
                self._time = time or RealTime()
    """

    __slots__ = ()

    @staticmethod
    def monotonic() -> float:  # pragma: no cover
        """Return ``time.monotonic()``."""
        return _time_module.monotonic()  # type: ignore[attr-defined]

    @staticmethod
    def sleep(duration: float) -> None:  # pragma: no cover
        """Call ``time.sleep(duration)``."""
        _time_module.sleep(duration)  # type: ignore[attr-defined]
