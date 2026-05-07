"""Cross-runtime skip primitive for the lightweight test harness.

A test that genuinely cannot run on the current device (missing
host-side fixture, runtime-only feature absent, etc.) calls
``chumicro_test_harness.skip(reason)`` to surface a visible SKIP
line.  The runner catches the sentinel exception and emits
``SKIP <name> (<reason>)`` — the same shape
``chumicro_pytest_device.result_parser`` already understands, so
host-side pytest reports the test as skipped (not silently
passed).

A bare ``return`` from a test body is reported as PASS by the
runner.  Tests must use this primitive, never ``return``, for any
condition that means "this test didn't actually execute its
assertions."
"""


class _SkipException(Exception):
    """Sentinel raised by :func:`skip`.

    Caught by :func:`chumicro_test_harness.runner.run_module` so the
    test reports as ``SKIP`` rather than ``PASS`` / ``FAIL``.  Not a
    public type — tests should call :func:`skip` instead of raising
    directly.
    """


def skip(reason):
    """Mark the current test as skipped with *reason*.

    Raises a sentinel exception that the harness runner catches and
    reports as ``SKIP <test_name> (<reason>)``.  The reason string
    surfaces in pytest output so the human reading the run knows
    exactly which prerequisite was missing.

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
