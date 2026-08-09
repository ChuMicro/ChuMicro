"""Cross-runtime public-surface tests for the sockets factories.

``UnsupportedSSLConfigError`` must stage and import on every runtime — a
CP-rp2 board raises it up-front from ``listener(tls=True)`` — so these
checks pin the exception's reachability and its ``RuntimeError`` lineage
without touching a per-runtime adapter, a real socket, or stdlib ``ssl``.
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
