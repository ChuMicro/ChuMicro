"""Shared ``sys.modules`` stubs for the cross-runtime sockets tests.

Several cross-runtime test files drive runtime-specific adapter source
through host fakes.  The cp adapter does ``import socketpool`` at module
top; the cpython adapter does ``import socket`` / ``ssl`` / ``select``
at module top.  None of those modules exist on host runtimes the way the
adapters expect (CPython has ``socket`` / ``ssl`` / ``select`` but not
``socketpool``; the MP and CP unix-ports ship none of them as adapter-
ready).  Each test file seeds ``sys.modules`` with these stubs before
importing ``chumicro_sockets`` so the module-load imports succeed;
per-test fakes then overwrite the adapter modules' attributes directly.

Plain classes rather than ``types.ModuleType`` instances because the MP
and CP unix-ports omit the ``types`` module.

This module is staged onto the device next to the importing test file by
the pytest-device staging path (underscore-prefixed sibling modules ride
along as ``extra_modules``); on the host and unix-port runs the test
file's directory is on ``sys.path`` so ``from _swap_helpers import ...``
resolves there too.  The generic swap context managers
(``SwapAttribute`` / ``SwapItem`` / ``FakeModule``) live in
``chumicro_test_harness.patching``; this file holds only the
sockets-specific module stubs.
"""

#: Host-only support module: stubs runtime-specific firmware/stdlib
#: imports so off-target adapter source loads on host interpreters.
#: Carries no runtime marker — it ships alongside the test files that
#: import it and never runs standalone.
__chumicro_test_support__ = True


class SocketpoolStub:
    """Stand-in for the ``socketpool`` firmware module on host runtimes.

    Production CircuitPython boards expose ``socketpool`` from firmware;
    host runtimes do not.  The cp adapter imports ``socketpool`` at
    module top, so this stub must be in ``sys.modules`` before any test
    reaches that import.  The class attributes mirror the address-family
    and socket-option constants the adapter reads off the module.

    The nested :class:`SocketPool` raises on construction: it is a
    tripwire for the case where a test invokes the cp adapter without
    first overriding ``cp_adapter.socketpool`` with a per-test fake.
    """

    AF_INET = 2
    SOCK_STREAM = 1
    SOCK_DGRAM = 2
    SOL_SOCKET = 0
    SO_REUSEADDR = 4
    SO_BROADCAST = 6

    class SocketPool:
        def __init__(self, _radio):
            raise RuntimeError(
                "SocketpoolStub.SocketPool reached — a test invoked the "
                "cp adapter without overriding ``cp_adapter.socketpool`` "
                "with a per-test fake first.",
            )


class BareStub:
    """Empty ``sys.modules`` placeholder for a stdlib name the cpython adapter imports.

    Stands in for ``socket`` / ``ssl`` / ``select`` at the cpython
    adapter's module-load time on host runtimes that don't ship a usable
    copy.  Carries no surface: routing tests overwrite the adapter
    module's attributes directly, so the placeholder only needs to make
    the bare ``import`` succeed.
    """
