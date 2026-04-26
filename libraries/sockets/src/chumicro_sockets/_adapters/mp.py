"""MicroPython adapter — stdlib ``socket`` + ``ssl`` (mbedTLS-backed).

One MP adapter covers every supported port.  Decision 0031 §1
flagged "no TLS on Pico W" as folklore from the pre-mbedTLS era;
current MP (1.26+) ships ``MICROPY_SSL_MBEDTLS=1`` on both ESP32 and
RP2 ports, so the socket+ssl story is unified.  Two split adapters
(mp_esp32 + mp_rp2) would be substring-clones of each other; this
file is the consolidation.

MP's ``socket`` module mirrors stdlib closely enough that
``recv_into`` and ``send`` work as documented.  Older builds without
``recv_into`` aren't a concern for the runtimes this library targets
(Decision 0015 minimum supported class — RP2040, ESP32, ESP32-Sx,
all on current MP).

TLS quirk: MP's ``ssl.wrap_socket`` accepts either ``server_hostname``
or no hostname (TLS-without-SNI).  We always pass *host* as
``server_hostname`` — the TLS contract is "verify the cert matches
the host the user named", and SNI-less verification breaks against
modern brokers.
"""

from __future__ import annotations

# ``socket`` and ``ssl`` are MicroPython stdlib modules — they exist
# only when this code runs under MP.  CPython tests never import this
# adapter; the factory routes around it via sys.implementation.name.
import socket  # type: ignore[import]
import ssl as _ssl  # type: ignore[import]
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover — type-only
    from chumicro_sockets.protocol import TCPClientSocket


def connect_tcp(host: str, port: int) -> TCPClientSocket:  # pragma: no cover - device only
    """Open a plain TCP connection on MicroPython.

    Uses ``socket.getaddrinfo`` + ``socket.socket`` + ``connect`` —
    MP's ``create_connection`` shim is missing on some builds, so
    we do the dance explicitly.
    """
    address_info = socket.getaddrinfo(host, port)[0]
    sock = socket.socket(address_info[0], address_info[1])
    sock.connect(address_info[-1])
    return sock  # type: ignore[return-value]


def connect_tls(
    host: str,
    port: int,
    *,
    context: object = None,
) -> TCPClientSocket:  # pragma: no cover - device only
    """Open a TLS connection on MicroPython.

    *context* is an MP ``ssl.SSLContext`` (or ``None`` for the
    default).  When ``None``, ``ssl.wrap_socket`` is called with
    ``server_hostname=host`` so the TLS handshake validates the
    cert chain against the system trust store.

    Older MP builds expose ``ssl.wrap_socket`` as a free function
    rather than a context method — this adapter calls the free
    function so it works on both shapes.
    """
    address_info = socket.getaddrinfo(host, port)[0]
    sock = socket.socket(address_info[0], address_info[1])
    sock.connect(address_info[-1])
    if context is None:
        return _ssl.wrap_socket(sock, server_hostname=host)  # type: ignore[no-any-return]
    return context.wrap_socket(sock, server_hostname=host)  # type: ignore[attr-defined,no-any-return]


def ssl_context_with_ca(ca_pem: bytes) -> object:  # pragma: no cover - device only
    """Build an MP ``ssl.SSLContext`` that trusts only *ca_pem*.

    MP's ``ssl.SSLContext`` accepts ``load_verify_locations`` with
    ``cadata`` (string).  Modern MP builds (1.24+) implement the
    same call shape as CPython, so the helper is a near-clone of
    the CPython one.
    """
    context = _ssl.SSLContext(_ssl.PROTOCOL_TLS_CLIENT)  # type: ignore[attr-defined]
    context.load_verify_locations(cadata=ca_pem.decode("ascii"))
    return context
