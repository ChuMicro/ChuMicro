"""Shared test fakes and helpers for the ChuMicro workspace.

This package provides deterministic fakes that are useful across
multiple support packages and scripts tests.  It is workspace
infrastructure — not a published library.

Available fakes:

- ``FakeTime`` — deterministic seconds-domain time source that
  bundles ``monotonic()`` and ``sleep()`` behind a single injectable.
"""

from chumicro_testing.fake_time import FakeTime

__all__ = ["FakeTime"]

