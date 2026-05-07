"""Cross-runtime skip primitive for the lightweight test harness.

A test that genuinely cannot run on the current device (missing
host-side fixture, runtime-only feature absent, etc.) calls
``chumicro_test_harness.skip(reason)`` to surface a visible SKIP
line.  Two runtime contexts call into the same primitive:

* The lightweight runner (``run_module``) used by the cross-runtime
  test path on CPython, MicroPython unix-port, and CircuitPython
  unix-port — and on real devices via :mod:`chumicro_pytest_device`.
  The runner catches :data:`_SkipException` and emits
  ``SKIP <name> (<reason>)``.

* Host-side pytest, when running these same files as ordinary
  Python unit tests on CPython.  Pytest catches its own ``Skipped``
  exception type and reports the test as skipped.

Both paths converge by aliasing :data:`_SkipException` to
``pytest.skip.Exception`` whenever pytest is importable, and falling
back to a plain ``Exception`` subclass when it isn't (the
unix-ports / on-device runtimes).  A test that calls :func:`skip`
gets a visible skip in either path, never a fake PASS via bare
``return``.
"""

try:
    import pytest as _pytest
except ImportError:
    _pytest = None  # MicroPython / CircuitPython unix-ports — no pytest.

if _pytest is not None:
    #: Pytest's own ``Skipped`` exception, exposed as ``pytest.skip.Exception``
    #: for `pytest.raises` patterns.  Aliased here so a single ``raise``
    #: works in both the test_harness runner (which catches this type)
    #: and pytest's test machinery (which knows to report SKIP for it).
    _SkipException = _pytest.skip.Exception
else:
    class _SkipException(Exception):
        """Sentinel raised by :func:`skip` on runtimes without pytest.

        Caught by :func:`chumicro_test_harness.runner.run_module` so the
        test reports as ``SKIP`` rather than ``PASS`` / ``FAIL``.  Not a
        public type — tests should call :func:`skip` instead of raising
        directly.
        """


def skip(reason):
    """Mark the current test as skipped with *reason*.

    Raises an exception that whichever runner is driving the test
    catches and reports as a visible skip:

    * Under the lightweight :func:`chumicro_test_harness.runner.run_module`
      (cross-runtime + on-device path), the runner emits
      ``SKIP <test_name> (<reason>)``.
    * Under pytest (CPython unit-test path), pytest reports the test
      as skipped with *reason* as the message.

    A bare ``return`` from a test body is reported as PASS by both
    runners.  Tests must use this primitive, never ``return``, for
    any condition that means "this test didn't actually execute its
    assertions."

    Args:
        reason: Human-readable explanation of why the test was
            skipped.  Surfaced verbatim in the harness output and in
            pytest's skip message.

    Example::

        from chumicro_test_harness import skip

        def test_real_udp_echo_round_trip():
            if config["sockets.echo.host"] is None:
                skip("host-side echo server not available")
            ...
    """
    raise _SkipException(reason)
