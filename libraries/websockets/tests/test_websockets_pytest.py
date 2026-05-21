"""CPython-only tests for chumicro_websockets._wire SHA1 dispatch.

The two-tier ``_sha1_digest`` dispatcher prefers ``hashlib.sha1(...)``
and falls back to ``hashlib.new("sha1", ...)``.  The fast path is
exercised on every runtime by the rest of the websockets test suite
(every handshake test calls into it).  The fallback path is what
this test verifies — by deleting ``hashlib.sha1`` and re-calling.

The fallback path can't be exercised on MP / CP unix-ports because
``hashlib.new`` doesn't exist there either: enabling
``MICROPY_PY_SSL=1`` + ``MICROPY_SSL_AXTLS=1`` (per
``scripts/prepare_circuitpython.py``) wires up ``hashlib.sha1``
directly, but doesn't add ``new()``.  So the simulation only works
on CPython.

Live-board verified on Pi Pico W CP — see commit ``b7a98b8`` for the
probe transcript.
"""

#: CPython-only lane (pytest fixtures / host stdlib).  Not cross-runtime.
__chumicro_runtimes__ = ("cpython",)

from chumicro_websockets import _wire


class TestSha1Dispatch:
    """The two-tier dispatch hits the right backend on every runtime."""

    def test_dispatcher_uses_hashlib_new_when_sha1_attr_missing(self):
        """CircuitPython simulation: ``hashlib.sha1`` absent, ``hashlib.new`` present."""
        import hashlib as real_hashlib

        original_sha1 = getattr(real_hashlib, "sha1", None)
        try:
            if hasattr(real_hashlib, "sha1"):
                del real_hashlib.sha1
            digest = _wire._sha1_digest(b"abc")
            assert digest == bytes.fromhex(
                "a9993e364706816aba3e25717850c26c9cd0d89d",
            )
        finally:
            if original_sha1 is not None:
                real_hashlib.sha1 = original_sha1
