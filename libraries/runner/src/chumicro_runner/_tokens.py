"""Wait-token vocabulary for ``Runner.add_generator``.

Generator-driven services yield one of these tokens to suspend until
a condition holds.  The runner inspects each token's ``ready(now_ms)``
during ``tick()`` to decide when to ``.send()`` the generator back
into motion; the value from ``result(now_ms)`` is what the generator
receives at the resume site.

Tokens are intentionally tiny data carriers — a helper looping on
``yield ready`` constructs one token outside the loop and reuses it,
keeping steady-state allocation at zero.  Constructing a fresh
``ReadReady(sock)`` inside the loop body allocates per tick and
breaks the per-tick allocation budget.

``ReadReady`` / ``WriteReady``'s ``ready()`` always returns True:
the runner's ``wait()`` ipoll wake-up is what gates an idle generator
from spinning, and the EAGAIN-loop pattern (generator re-yields the
same token when the socket returns ``EAGAIN``) handles unsuccessful
attempts.  ``Sleep.ready()`` compares ``now_ms`` against ``until_ms``
via ``chumicro_timing.ticks_diff`` so wrap is handled correctly.

Tokens do **not** implement ``__await__``.  They are yielded directly
via ``yield token`` from a ``def`` generator function, never via
``await token``.
"""

from chumicro_timing.ticks import ticks_diff


class ReadReady:
    """Yielded by a generator to wait until ``sock`` is readable.

    Args:
        sock: A socket-like object the generator will read from when
            resumed.  Exposed as ``self.sock`` so the wrapper can
            register it with the runner's poll set.
    """

    def __init__(self, sock: object) -> None:
        self.sock = sock

    def ready(self, now_ms: int) -> bool:
        return True

    def result(self, now_ms: int) -> object:
        return self.sock


class WriteReady:
    """Yielded by a generator to wait until ``sock`` is writable.

    Args:
        sock: A socket-like object the generator will write to when
            resumed.  Exposed as ``self.sock`` so the wrapper can
            register it with the runner's poll set.
    """

    def __init__(self, sock: object) -> None:
        self.sock = sock

    def ready(self, now_ms: int) -> bool:
        return True

    def result(self, now_ms: int) -> object:
        return self.sock


class Sleep:
    """Yielded by a generator to wait until the absolute tick ``until_ms``.

    Args:
        until_ms: Absolute ``ticks_ms`` value at which the generator
            should resume.  The caller computes it as
            ``ticks_add(now_ms, delay_ms)``; this class stores it as
            given and the wrap-safe comparison happens in ``ready``.
    """

    def __init__(self, until_ms: int) -> None:
        self.until_ms = until_ms

    def ready(self, now_ms: int) -> bool:
        return ticks_diff(now_ms, self.until_ms) >= 0

    def result(self, now_ms: int) -> int:
        return now_ms
