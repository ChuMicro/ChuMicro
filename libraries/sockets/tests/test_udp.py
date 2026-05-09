"""Cross-runtime tests for chumicro_sockets UDP support.

Two layers exercised here:

* :class:`FakeUDPSocket` — the in-memory protocol-conformance fake.
  Every assertion runs on CPython, MicroPython unix-port, and
  CircuitPython unix-port.
* Factory routing — confirm ``udp_socket`` dispatches to the right
  adapter when ``_runtime_name`` is swapped.  Uses a tiny manual
  ``_SwapAttribute`` context manager (mirrors the same pattern in
  ``libraries/websockets/tests/test_sockets_factory.py``) instead of
  ``unittest.mock.patch``, which doesn't exist on MP / CP.

The CPython-loopback tests (real ``socket.socket()``, ``getsockopt``,
``SO_BROADCAST``) live in ``test_udp_pytest.py`` because they depend
on stdlib ``socket`` directly — CP unix-port doesn't ship it (real
CP boards use ``socketpool`` instead) and MP unix-port has it but
the cross-runtime contract is already covered by ``FakeUDPSocket``
plus the on-device functional tests.

Cross-runtime files (no ``_pytest`` suffix) must not import pytest /
unittest / etc., and run unmodified under CPython + MicroPython +
CircuitPython unix-ports via the ``chumicro_test_harness`` runner.
"""

import chumicro_sockets
from chumicro_sockets import UDPSocket, udp_socket
from chumicro_sockets.testing import FakeUDPSocket
from chumicro_test_harness.assertions import raises


class _SwapAttribute:
    """Context manager — swap ``module.name`` with a stand-in, restore on exit.

    Cross-runtime stand-in for ``unittest.mock.patch.object``: ``unittest``
    isn't available on MicroPython / CircuitPython unix-ports.
    """

    def __init__(self, module: object, name: str, replacement: object) -> None:
        self.module = module
        self.name = name
        self.replacement = replacement
        self._original: object = None
        self._had_attr: bool = False

    def __enter__(self) -> "_SwapAttribute":
        self._had_attr = hasattr(self.module, self.name)
        if self._had_attr:
            self._original = getattr(self.module, self.name)
        setattr(self.module, self.name, self.replacement)
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback) -> bool:
        if self._had_attr:
            setattr(self.module, self.name, self._original)
        else:
            delattr(self.module, self.name)
        return False


class _SwapItem:
    """Context manager — swap ``mapping[key]`` with a stand-in, restore on exit.

    Cross-runtime stand-in for ``unittest.mock.patch.dict``.  Used here
    to stub ``sys.modules['<dotted-path>']`` so an ``import`` that
    would otherwise fail on a runtime missing the underlying module
    instead picks up our fake.
    """

    def __init__(self, mapping: dict, key: str, replacement: object) -> None:
        self.mapping = mapping
        self.key = key
        self.replacement = replacement
        self._original: object = None
        self._had_key: bool = False

    def __enter__(self) -> "_SwapItem":
        self._had_key = self.key in self.mapping
        if self._had_key:
            self._original = self.mapping[self.key]
        self.mapping[self.key] = self.replacement
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback) -> bool:
        if self._had_key:
            self.mapping[self.key] = self._original
        else:
            del self.mapping[self.key]
        return False


# ---------------------------------------------------------------------------
# Public-surface checks
# ---------------------------------------------------------------------------


def test_udp_socket_factory_in_public_namespace() -> None:
    assert hasattr(chumicro_sockets, "udp_socket")
    assert hasattr(chumicro_sockets, "UDPSocket")
    assert chumicro_sockets.UDPSocket is UDPSocket


# ---------------------------------------------------------------------------
# FakeUDPSocket
# ---------------------------------------------------------------------------


class TestFakeUDPSocket:
    """In-memory protocol conformance tests."""

    def test_default_state(self) -> None:
        sock = FakeUDPSocket()
        assert sock.sent == []
        assert sock.pending_recv_chunks == 0
        assert sock.closed is False
        assert sock.blocking is True
        assert sock.timeout is None

    def test_sendto_records_data_and_destination(self) -> None:
        sock = FakeUDPSocket()
        n_sent = sock.sendto(b"hello", "10.0.0.1", 1234)
        assert n_sent == 5
        assert sock.sent == [(b"hello", "10.0.0.1", 1234)]

    def test_sendto_accepts_bytes_like(self) -> None:
        sock = FakeUDPSocket()
        sock.sendto(bytearray(b"a"), "h", 1)
        sock.sendto(memoryview(b"b"), "h", 1)
        assert [data for data, _, _ in sock.sent] == [b"a", b"b"]

    def test_recvfrom_into_pops_queued_datagram(self) -> None:
        sock = FakeUDPSocket()
        sock.enqueue_recv(b"reply", host="10.0.0.5", port=5353)
        buffer = bytearray(64)
        n_received, address = sock.recvfrom_into(buffer)
        assert n_received == 5
        assert bytes(buffer[:5]) == b"reply"
        assert address == ("10.0.0.5", 5353)

    def test_recvfrom_into_truncates_to_buffer(self) -> None:
        sock = FakeUDPSocket()
        sock.enqueue_recv(b"abcdefghij")
        buffer = bytearray(4)
        n_received, _address = sock.recvfrom_into(buffer)
        assert n_received == 4
        assert bytes(buffer) == b"abcd"

    def test_recvfrom_into_respects_explicit_nbytes(self) -> None:
        sock = FakeUDPSocket()
        sock.enqueue_recv(b"abcdefghij")
        buffer = bytearray(64)
        n_received, _address = sock.recvfrom_into(buffer, nbytes=3)
        assert n_received == 3
        assert bytes(buffer[:3]) == b"abc"

    def test_recvfrom_into_empty_queue_returns_zero(self) -> None:
        sock = FakeUDPSocket()
        buffer = bytearray(16)
        n_received, address = sock.recvfrom_into(buffer)
        assert n_received == 0
        assert address == ("0.0.0.0", 0)

    def test_recvfrom_into_zero_capacity_returns_zero(self) -> None:
        sock = FakeUDPSocket()
        sock.enqueue_recv(b"reply")
        buffer = bytearray(0)
        n_received, _address = sock.recvfrom_into(buffer)
        assert n_received == 0

    def test_enqueue_recv_rejects_non_bytes_like(self) -> None:
        sock = FakeUDPSocket()
        with raises(TypeError):
            sock.enqueue_recv("not bytes")  # type: ignore[arg-type]

    def test_eagain_for_send(self) -> None:
        sock = FakeUDPSocket()
        sock.enqueue_eagain_for_send(2)
        with raises(OSError) as first:
            sock.sendto(b"x", "h", 1)
        assert first.value.args[0] == 11
        with raises(OSError):
            sock.sendto(b"x", "h", 1)
        # Third send succeeds.
        sock.sendto(b"x", "h", 1)
        assert len(sock.sent) == 1

    def test_eagain_for_recv(self) -> None:
        sock = FakeUDPSocket()
        sock.enqueue_eagain_for_recv(1)
        sock.enqueue_recv(b"x")
        buffer = bytearray(8)
        with raises(OSError) as raised:
            sock.recvfrom_into(buffer)
        assert raised.value.args[0] == 11
        n_received, _address = sock.recvfrom_into(buffer)
        assert n_received == 1

    def test_close_and_subsequent_calls_raise_ebadf(self) -> None:
        sock = FakeUDPSocket()
        sock.close()
        assert sock.closed is True
        with raises(OSError) as send_raised:
            sock.sendto(b"x", "h", 1)
        assert send_raised.value.args[0] == 9
        buffer = bytearray(8)
        with raises(OSError):
            sock.recvfrom_into(buffer)
        # Repeated close is idempotent.
        sock.close()

    def test_setblocking_and_settimeout_track_state(self) -> None:
        sock = FakeUDPSocket()
        sock.setblocking(False)
        assert sock.blocking is False
        assert sock.timeout == 0.0
        sock.settimeout(2.5)
        assert sock.timeout == 2.5
        assert sock.blocking is False
        sock.settimeout(None)
        assert sock.timeout is None
        assert sock.blocking is True

    def test_getsockname_reports_bind_address(self) -> None:
        sock = FakeUDPSocket(bind_host="192.168.1.10", bind_port=1234)
        assert sock.getsockname() == ("192.168.1.10", 1234)

    def test_fileno_default_is_positive(self) -> None:
        sock = FakeUDPSocket()
        assert sock.fileno() >= 0

    def test_fileno_can_be_overridden(self) -> None:
        sock = FakeUDPSocket()
        sock.set_fileno(-1)
        assert sock.fileno() == -1

    def test_pending_recv_chunks_counts_queue(self) -> None:
        sock = FakeUDPSocket()
        sock.enqueue_recv(b"a")
        sock.enqueue_recv(b"b")
        assert sock.pending_recv_chunks == 2


# ---------------------------------------------------------------------------
# Factory routing — confirm udp_socket dispatches by runtime
# ---------------------------------------------------------------------------


class TestUDPFactoryRouting:
    """Verify ``udp_socket`` picks the right adapter via ``_runtime_name``.

    Manual ``_SwapAttribute`` context manager replaces
    ``unittest.mock.patch`` so the tests run on MP / CP unix-ports too.
    The CP / MP adapter modules might not be importable on the host
    (the CP adapter does ``import socketpool`` at call time; the MP
    adapter does ``import socket``), so we install a synthetic
    ``udp_socket`` attribute on the module before the call.
    """

    def test_routes_to_circuitpython(self) -> None:
        sentinel = object()
        calls: list = []

        def fake_cp_udp_socket(**kwargs):
            calls.append(kwargs)
            return sentinel

        # Ensure the cp adapter module is importable before we patch on it.
        from chumicro_sockets._adapters import cp as cp_adapter

        with _SwapAttribute(chumicro_sockets, "_runtime_name", lambda: "circuitpython"), \
                _SwapAttribute(cp_adapter, "udp_socket", fake_cp_udp_socket):
            result = udp_socket(
                "0.0.0.0",
                1234,
                radio="radio-stub",
                broadcast=True,
            )

        assert result is sentinel
        assert calls == [{
            "bind_host": "0.0.0.0",
            "bind_port": 1234,
            "radio": "radio-stub",
            "broadcast": True,
        }]

    def test_routes_to_micropython(self) -> None:
        sentinel = object()
        calls: list = []

        def fake_mp_udp_socket(**kwargs):
            calls.append(kwargs)
            return sentinel

        # The MP adapter module imports stdlib ``socket`` at module-load
        # time — works on the MP unix-port and on CPython, raises
        # ``ImportError`` on the CP unix-port.  Stub it via
        # ``sys.modules`` AND on the ``_adapters`` package object so
        # the dispatcher's ``from chumicro_sockets._adapters import mp``
        # picks up the stub.  ``from … import mp`` checks the package
        # object's attribute first (which a previous test may have
        # bound to the real module), then falls back to ``sys.modules``.
        #
        # ``types.ModuleType`` doesn't exist on MP / CP unix-ports —
        # use a bare ``_FakeModule`` class with the one attribute the
        # dispatcher reaches for.
        import sys

        from chumicro_sockets import _adapters as adapters_package

        class _FakeModule:
            udp_socket = staticmethod(fake_mp_udp_socket)

        fake_mp_module = _FakeModule()

        with _SwapAttribute(chumicro_sockets, "_runtime_name", lambda: "micropython"), \
                _SwapItem(sys.modules, "chumicro_sockets._adapters.mp", fake_mp_module), \
                _SwapAttribute(adapters_package, "mp", fake_mp_module):
            result = udp_socket("1.2.3.4", 9, broadcast=True)

        assert result is sentinel
        assert calls == [{
            "bind_host": "1.2.3.4",
            "bind_port": 9,
            "broadcast": True,
        }]

    def test_routes_to_cpython_for_unknown_runtime(self) -> None:
        sentinel = object()
        calls: list = []

        def fake_cpython_udp_socket(**kwargs):
            calls.append(kwargs)
            return sentinel

        from chumicro_sockets._adapters import cpython as cpython_adapter

        with _SwapAttribute(chumicro_sockets, "_runtime_name", lambda: "pypy"), \
                _SwapAttribute(cpython_adapter, "udp_socket", fake_cpython_udp_socket):
            result = udp_socket()

        assert result is sentinel
        assert calls == [{
            "bind_host": "0.0.0.0",
            "bind_port": 0,
            "broadcast": False,
        }]
