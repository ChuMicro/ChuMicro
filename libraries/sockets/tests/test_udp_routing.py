"""Host-only tests for ``udp_socket`` runtime routing.

Each test swaps ``chumicro_sockets._adapter`` to a named per-runtime
adapter (or a ``FakeModule`` stand-in) and asserts that ``udp_socket``
dispatched there with the expected bind / radio / broadcast kwargs.
A named adapter module only stages on its matching runtime, so these
pass on CPython + the MicroPython / CircuitPython unix-ports but never
on real silicon — routing is a host-verified concern as a category.

``SwapAttribute`` from ``chumicro_test_harness.patching`` replaces
``unittest.mock.patch`` so the tests run on the MP / CP unix-ports,
which ship neither ``unittest`` nor ``types``.

The ``FakeUDPSocket`` protocol-conformance tests and the public-surface
check stay in the cross-runtime ``test_udp.py``; the CPython-loopback
tests live in ``test_udp_pytest.py``.
"""

#: Host-only lane: fakes a runtime identity and asserts the
#: ``udp_socket`` adapter route, so it runs on every host interpreter
#: (CPython + MP/CP unix-port) but never on real silicon.
__chumicro_host_only__ = True

import sys

from _swap_helpers import BareStub, SocketpoolStub

# ``socketpool`` is a firmware module absent from every host interpreter,
# so the cp-adapter import always needs the stub.
sys.modules.setdefault("socketpool", SocketpoolStub())
# ``socket`` / ``ssl`` / ``select`` are real, importable stdlib on
# CPython, and pytest's own machinery (``selectors`` needs
# ``select.select``) depends on them — stubbing them via
# ``setdefault`` in an interpreter that hasn't imported them yet
# poisons ``sys.modules`` for the whole session.  Only the
# MicroPython / CircuitPython unix-ports lack an adapter-ready copy,
# so install the placeholders there alone.
if sys.implementation.name != "cpython":
    sys.modules.setdefault("socket", BareStub())
    sys.modules.setdefault("ssl", BareStub())
    sys.modules.setdefault("select", BareStub())


import chumicro_sockets  # noqa: E402 — load-order dependency on the stubs above
from chumicro_sockets import udp_socket  # noqa: E402
from chumicro_test_harness.patching import FakeModule, SwapAttribute  # noqa: E402


class TestUDPFactoryRouting:
    """Verify ``udp_socket`` picks the right adapter via ``_runtime_name``.

    ``SwapAttribute`` replaces ``unittest.mock.patch`` so the tests run
    on MP / CP unix-ports too.  The CP / MP adapter modules might not be
    importable on the host (the CP adapter does ``import socketpool`` at
    call time; the MP adapter does ``import socket``), so we install a
    synthetic ``udp_socket`` attribute on the module before the call.
    """

    def test_routes_to_circuitpython(self) -> None:
        sentinel = object()
        calls: list = []

        def fake_cp_udp_socket(**kwargs):
            calls.append(kwargs)
            return sentinel

        # Ensure the cp adapter module is importable before we patch on it.
        from chumicro_sockets._adapters import cp as cp_adapter

        with SwapAttribute(chumicro_sockets, "_adapter", cp_adapter), \
                SwapAttribute(cp_adapter, "udp_socket", fake_cp_udp_socket):
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

        # Build a bare module-shaped object exposing the one attribute
        # the package factory reaches for.
        fake_mp_module = FakeModule()
        fake_mp_module.udp_socket = fake_mp_udp_socket

        with SwapAttribute(chumicro_sockets, "_adapter", fake_mp_module):
            result = udp_socket("1.2.3.4", 9, broadcast=True)

        assert result is sentinel
        assert calls == [{
            "bind_host": "1.2.3.4",
            "bind_port": 9,
            "radio": None,
            "broadcast": True,
        }]

    def test_routes_to_cpython_for_unknown_runtime(self) -> None:
        sentinel = object()
        calls: list = []

        def fake_cpython_udp_socket(**kwargs):
            calls.append(kwargs)
            return sentinel

        from chumicro_sockets._adapters import cpython as cpython_adapter

        with SwapAttribute(chumicro_sockets, "_adapter", cpython_adapter), \
                SwapAttribute(cpython_adapter, "udp_socket", fake_cpython_udp_socket):
            result = udp_socket()

        assert result is sentinel
        assert calls == [{
            "bind_host": "0.0.0.0",
            "bind_port": 0,
            "radio": None,
            "broadcast": False,
        }]
