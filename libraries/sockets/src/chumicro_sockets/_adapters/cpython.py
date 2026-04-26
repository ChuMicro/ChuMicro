"""CPython adapter — stdlib ``socket`` + ``ssl``.

Used:

* on CPython directly (host-side tests, sim runs, downstream libs
  imported on a laptop without a board);
* as the test substrate for :class:`chumicro_sockets.testing.FakeSocket`
  conformance — every protocol method routes to a real CPython
  socket call here, so a passing test against this adapter establishes
  the contract every other adapter implements.

stdlib ``socket.create_connection`` does the dial-and-connect dance
and raises :class:`OSError` on connect failure, which downstream
libs already handle.  TLS uses stdlib ``ssl.SSLContext.wrap_socket``;
``context=None`` means "default-CA stdlib context" via
``ssl.create_default_context()``.
"""

from __future__ import annotations

import socket
import ssl as _ssl
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover — type-only
    from chumicro_sockets.protocol import TCPClientSocket


def connect_tcp(host: str, port: int) -> TCPClientSocket:
    """Open a plain TCP connection.

    Returns a real :class:`socket.socket` — already satisfies
    :class:`TCPClientSocket` structurally (stdlib's surface is a
    superset of our protocol).
    """
    return socket.create_connection((host, port))  # type: ignore[return-value]


def connect_tls(
    host: str,
    port: int,
    *,
    context: _ssl.SSLContext | None = None,
) -> TCPClientSocket:
    """Open a TLS connection.

    *context=None* uses :func:`ssl.create_default_context` — system
    default CA bundle, hostname check enabled, modern cipher defaults.
    Pass a pre-configured context for custom CAs / mTLS / pinned
    cipher suites.
    """
    raw = socket.create_connection((host, port))
    resolved_context = (
        context if context is not None else _ssl.create_default_context()
    )
    return resolved_context.wrap_socket(  # type: ignore[return-value]
        raw, server_hostname=host,
    )


def ssl_context_with_ca(ca_pem: bytes) -> _ssl.SSLContext:
    """Build an SSLContext that trusts only the CA(s) in *ca_pem*.

    Uses :meth:`ssl.SSLContext.load_verify_locations` with the PEM
    bytes — stdlib accepts a string or bytes via ``cadata``.  The
    context still enforces hostname verification and modern cipher
    defaults; only the trust anchor is replaced.
    """
    context = _ssl.create_default_context()
    context.load_verify_locations(cadata=ca_pem.decode("ascii"))
    return context
