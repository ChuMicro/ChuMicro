"""Shared stubs for the split ``test_generator*.py`` suites.

Underscore-prefixed so the harness never collects it as a test module.
The harness puts each test file's directory on ``sys.path``, so the split
files import these with ``from _generator_helpers import ...`` on CPython,
MicroPython, and CircuitPython alike.

The wait shape is **duck-typed**: ``_Wait`` exposes the protocol surface
(``io_socket``, ``io_interest(now_ms)``, ``next_deadline``) so the tests
can assert the wrapper inspects it via ``getattr`` — no dependency on the
private wait classes in ``chumicro_runner.generators``.
"""

from chumicro_runner import IO_READ, IO_WRITE


class _Sock:
    """Stand-in for a socket-like object — identity is what matters."""


class _Wait:
    """Ad-hoc wait stub matching the wrapper's duck-typed protocol.

    Any object exposing this surface works as a wait — the wrapper reads
    it via ``getattr`` with defaults, so missing attributes degrade
    gracefully.  This stub sets all of them so tests can express any wait
    shape (socket-driven, deadline-driven, or both) with one constructor.
    """

    def __init__(self, *, sock=None, want_read=False, want_write=False, until_ms=None):
        self.io_socket = sock
        self._want_read = want_read
        self._want_write = want_write
        self._until_ms = until_ms

    def io_interest(self, now_ms):
        interest = 0
        if self._want_read:
            interest |= IO_READ
        if self._want_write:
            interest |= IO_WRITE
        return interest

    def next_deadline(self, now_ms):
        return self._until_ms
