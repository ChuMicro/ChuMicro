"""Cross-runtime public-surface tests for the sockets factories.

What's left here is runtime-independent: it touches no per-runtime
adapter module, no real loopback sockets, no ``cryptography`` library,
and no stdlib ``ssl`` / ``socket``.  It runs unmodified on CPython,
MicroPython unix-port, CircuitPython unix-port, and real boards.

Fake-runtime routing tests — which swap ``chumicro_sockets._adapter``
to a named adapter and assert the dispatch target — moved to the
host-only ``test_factories_routing.py``: a named adapter only stages
on the matching runtime, so those can't run on real silicon.  The
CPython-only tests (real TLS handshakes, ``cryptography``-minted certs,
stdlib ``ssl`` / ``socket`` patching) live in ``test_factories_pytest.py``.
"""

from chumicro_sockets import UnsupportedSSLConfigError
from chumicro_test_harness.assertions import raises

# ---------------------------------------------------------------------------
# UnsupportedSSLConfigError — public surface
# ---------------------------------------------------------------------------


class TestUnsupportedSSLConfigErrorIsAvailable:
    def test_class_is_a_runtime_error(self) -> None:
        assert issubclass(UnsupportedSSLConfigError, RuntimeError)

    def test_class_is_raisable(self) -> None:
        with raises(UnsupportedSSLConfigError):
            raise UnsupportedSSLConfigError("placeholder")
