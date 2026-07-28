"""Self-signed cert helper + daemon-thread TLS echo server for sockets demos.

Two entry points:

* `generate_self_signed_cert(workdir, common_name="localhost")` writes a
  fresh RSA self-signed cert + private key into *workdir* and returns the
  two paths. SubjectAlternativeName covers the CN as a DNS entry and
  127.0.0.1 as an IP, so handshakes against either name succeed.
* `start_tls_echo_server(bind_host, cert_path, key_path)` wraps the
  TCP echo pattern from `tcp_echo` in `ssl.SSLContext.wrap_socket(...,
  server_side=True)` using the supplied cert + key, and returns
  `(host, port, stop_event)`.

Workbench-only (CPython). The cert helper imports the `cryptography`
library lazily; it's a declared dependency of `chumicro-pytest-device`.
"""

from __future__ import annotations

import socket
import ssl
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

_RECV_CHUNK = 4096


def generate_self_signed_cert(
    workdir: Path,
    common_name: str = "localhost",
) -> tuple[Path, Path]:
    """Write a self-signed cert + key into *workdir*; return `(cert_path, key_path)`.

    The cert covers `common_name` as a DNS SAN and 127.0.0.1 as an IP
    SAN. Validity window: 2000-01-01 to +1 day. The notBefore sits at
    the MicroPython epoch because a board with an unset RTC boots
    there, and mbedTLS rejects a cert whose validity "starts in the
    future" (found on a real Pico W bake; a -5min skew window only
    covered host-side clocks). The short notAfter keeps a stale cert
    from a prior session from escaping notice on the host side.
    """
    from datetime import UTC, datetime, timedelta  # noqa: PLC0415
    from ipaddress import IPv4Address  # noqa: PLC0415

    from cryptography import x509  # noqa: PLC0415
    from cryptography.hazmat.primitives import hashes, serialization  # noqa: PLC0415
    from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: PLC0415
    from cryptography.x509.oid import NameOID  # noqa: PLC0415

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime(2000, 1, 1, tzinfo=UTC))
        .not_valid_after(datetime.now(UTC) + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName(common_name),
                x509.IPAddress(IPv4Address("127.0.0.1")),
            ]),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )

    cert_path = workdir / "cert.pem"
    key_path = workdir / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ),
    )
    return cert_path, key_path


def start_tls_echo_server(
    bind_host: str,
    cert_path: Path,
    key_path: Path,
) -> tuple[str, int, threading.Event]:
    """Bind a TLS echo socket on *bind_host*; return `(host, port, stop_event)`.

    Sequential-accept TLS server. `wrap_socket(server_side=True)`
    drives the handshake synchronously inside `accept`; the inner
    loop then echoes every plaintext byte received until the client
    closes or `stop_event` fires.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=cert_path, keyfile=key_path)

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((bind_host, 0))
    listener.listen(4)
    listener.settimeout(0.05)
    host, port = listener.getsockname()
    stop = threading.Event()

    def _serve() -> None:  # pragma: no cover - daemon thread, exercised by sockets demos
        while not stop.is_set():
            try:
                raw, _peer = listener.accept()
            except (TimeoutError, OSError):
                continue
            # The accepted socket would inherit the listener's 50 ms
            # stop-poll timeout; the TLS handshake and echo conversation
            # get their own budget.
            raw.settimeout(5.0)
            try:
                tls_sock = context.wrap_socket(raw, server_side=True)
            except (ssl.SSLError, OSError):
                try:
                    raw.close()
                except OSError:
                    pass
                continue
            try:
                while not stop.is_set():
                    chunk = tls_sock.recv(_RECV_CHUNK)
                    if not chunk:
                        break
                    tls_sock.sendall(chunk)
            except (ssl.SSLError, OSError):
                pass
            finally:
                try:
                    tls_sock.unwrap()
                except (ssl.SSLError, OSError):
                    pass
                try:
                    tls_sock.close()
                except OSError:
                    pass
        listener.close()

    thread = threading.Thread(target=_serve, name="tls-echo-server", daemon=True)
    thread.start()
    return host, port, stop
