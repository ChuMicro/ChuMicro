"""Shared abstractions and test fakes for the ChuMicro workspace.

This package provides injectable time sources for support packages
and scripts.  It is workspace infrastructure — not a published library.

- ``FakeTime`` — deterministic fake for host-side tests: stable clock,
  ``sleep()`` auto-advances, ``advance()`` for explicit control.

Production code accepts a ``time`` dependency via constructor injection
and defaults to Python's ``time`` module.  Tests inject ``FakeTime()``
to eliminate wall-clock waits.
"""

from chumicro_abstractions.fake_time import FakeTime

__all__ = ["FakeTime"]
