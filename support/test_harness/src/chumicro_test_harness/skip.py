"""Cross-runtime skip primitive: see :func:`skip`.

Tests use :func:`skip` to mark themselves as skipped under both pytest
(host-side unit tests) and :func:`chumicro_test_harness.runner.run_module`
(on-device and unix-port runs) without importing pytest, which is not
available on MicroPython or CircuitPython.
"""

try:
    import pytest as _pytest
except ImportError:
    _pytest = None  # MicroPython / CircuitPython unix-ports: no pytest.

if _pytest is not None:
    #: Pytest's own ``Skipped`` exception. Aliasing _SkipException to
    #: ``pytest.skip.Exception`` whenever pytest is importable lets a
    #: single ``raise _SkipException(reason)`` register as SKIP under
    #: both pytest (which knows its own type) and the on-device runner
    #: (which catches this type explicitly).
    _SkipException = _pytest.skip.Exception
else:
    class _SkipException(Exception):
        """Fallback sentinel when pytest is not importable (MP / CP unix-ports, on-device runs).

        Caught by :func:`chumicro_test_harness.runner.run_module` to
        report the test as SKIP. Not part of the public API: call
        :func:`skip`.
        """


def skip(reason):
    """Mark the current test as skipped with *reason*.

    Raises a sentinel that both pytest (host-side unit tests) and
    :func:`chumicro_test_harness.runner.run_module` (on-device and
    unix-port runs) recognize as a SKIP, with *reason* as the message.

    A bare ``return`` from a test body is reported as PASS by both
    runners. Tests must use this primitive, never ``return``, for any
    condition that means "this test did not actually execute its
    assertions."

    Args:
        reason: Human-readable explanation of why the test was skipped.
            Surfaced verbatim in the harness output and in pytest's
            skip message.

    Example::

        from chumicro_test_harness import skip

        def test_real_udp_echo_round_trip():
            if config["sockets.echo.host"] is None:
                skip("host-side echo server not available")
            ...
    """
    raise _SkipException(reason)
