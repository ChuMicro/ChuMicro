"""Test helpers for libraries that use the service loop pattern.

Provides ``FakeService`` — a stub component that records every
``service(now_ms)`` call for assertion in host-side tests.

Usage::

    from chumicro_serviceable.testing import FakeService

    svc = FakeService()
    svc.service(42)
    assert svc.ticks == [42]
"""


class FakeService:
    """Stub component that records ``service(now_ms)`` calls.

    Useful for verifying that a ``ServiceRunner`` or custom loop
    calls ``service()`` with the expected shared timestamp.
    """

    def __init__(self):
        """Create a fake service with an empty tick history."""
        self.ticks = []

    def service(self, now_ms):
        """Record *now_ms* in the tick history."""
        self.ticks.append(now_ms)
