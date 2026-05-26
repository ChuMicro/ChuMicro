"""Wait-token vocabulary behavior — ``ReadReady`` / ``WriteReady`` / ``Sleep``.

Cross-runtime: runs on CPython (via pytest), MicroPython and CircuitPython
(via chumicro_test_harness).  Asserts the ``ready(now_ms)`` /
``result(now_ms)`` contract each token honors, plus the cache-and-reuse
identity that lets a helper hoist one token outside its loop.
"""

from chumicro_runner import ReadReady, Sleep, WriteReady


class _Sock:
    """Tiny stand-in for a socket-like object.  Identity is what matters
    to ``ReadReady`` / ``WriteReady`` — the token stores the reference and
    hands it back via ``result``; no behaviour is invoked on it."""


def test_read_ready_always_reports_ready():
    # ``ready`` is True regardless of now_ms — ipoll wake-ups gate the
    # idle wait in ``Runner.wait``, and an EAGAIN-loop re-yielding the
    # same token retries on the next tick until the socket cooperates.
    sock = _Sock()
    token = ReadReady(sock)
    assert token.ready(0) is True
    assert token.ready(1_000_000) is True


def test_read_ready_result_returns_the_socket():
    sock = _Sock()
    token = ReadReady(sock)
    assert token.result(0) is sock
    assert token.result(1_000_000) is sock


def test_read_ready_exposes_sock_attribute():
    # ``Runner.wait``'s ``_sync_poll_set`` reads ``service.io_socket``
    # via getattr; the wrapper forwards that to ``self._wait.sock``,
    # so the public attribute name is part of the contract.
    sock = _Sock()
    assert ReadReady(sock).sock is sock


def test_write_ready_always_reports_ready():
    sock = _Sock()
    token = WriteReady(sock)
    assert token.ready(0) is True
    assert token.ready(1_000_000) is True


def test_write_ready_result_returns_the_socket():
    sock = _Sock()
    token = WriteReady(sock)
    assert token.result(0) is sock
    assert token.result(1_000_000) is sock


def test_write_ready_exposes_sock_attribute():
    sock = _Sock()
    assert WriteReady(sock).sock is sock


def test_sleep_not_ready_before_deadline():
    token = Sleep(until_ms=1000)
    assert token.ready(999) is False
    assert token.ready(500) is False
    assert token.ready(0) is False


def test_sleep_ready_at_and_after_deadline():
    # >= comparison: now_ms exactly at the deadline is "fire now".
    token = Sleep(until_ms=1000)
    assert token.ready(1000) is True
    assert token.ready(1001) is True
    assert token.ready(5000) is True


def test_sleep_handles_tick_wrap():
    # ticks_diff treats values as signed 30-bit; a deadline near rollover
    # with now_ms freshly past zero is still "in the future" until the
    # wrap-safe delta turns non-negative.  Picks values around the
    # 30-bit signed midpoint (2**29 = 536_870_912) on the runtimes where
    # ticks_ms wraps; CPython's ticks_diff is a plain subtraction but
    # the math agrees at these magnitudes.
    near_wrap_deadline = 1_073_741_800
    just_after_wrap_now = 1_073_741_795
    token = Sleep(until_ms=near_wrap_deadline)
    assert token.ready(just_after_wrap_now) is False
    assert token.ready(near_wrap_deadline) is True


def test_sleep_result_returns_now_ms():
    # The generator gets the resume timestamp back so a long-running
    # state machine can advance its internal deadlines without a
    # second ticks_ms() call.
    token = Sleep(until_ms=1000)
    assert token.result(1234) == 1234
    assert token.result(1_000_000) == 1_000_000


def test_sleep_exposes_until_ms_attribute():
    assert Sleep(until_ms=42).until_ms == 42


def test_tokens_are_cacheable_across_yields():
    # The implementation rule that makes steady-state allocation zero:
    # a helper looping on ``yield ready`` constructs the token once
    # outside the loop and reuses it.  Identity is preserved across
    # repeated ``ready`` / ``result`` calls so the cached reuse is
    # mechanical.
    sock = _Sock()
    read_token = ReadReady(sock)
    for _ in range(10):
        assert read_token.ready(0) is True
        assert read_token.result(0) is sock

    sleep_token = Sleep(until_ms=100)
    for now_ms in range(0, 200, 10):
        expected = now_ms >= 100
        assert sleep_token.ready(now_ms) is expected
