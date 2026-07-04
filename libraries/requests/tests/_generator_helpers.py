"""Shared driver for the one-shot fetch generator suites.

Underscore-prefixed so pytest does not collect it as a test module; the
tests' own directory is on ``sys.path`` on host, unix-port, and device,
so ``from _generator_helpers import _drive`` resolves everywhere.
"""


def _drive(gen, ticks, *, advance_ms=1, max_steps=200):
    """Pump *gen* the way the runner would, advancing the fake clock per resume.

    Returns the generator's return value (the ``Response``) on
    ``StopIteration``; advances *ticks* after each yield so deadline
    math progresses.
    """
    value = None
    for _ in range(max_steps):
        try:
            gen.send(value)
        except StopIteration as stop:
            return stop.value
        ticks.advance(advance_ms)
        value = ticks.ticks_ms()
    raise AssertionError("fetch did not complete within max_steps")
