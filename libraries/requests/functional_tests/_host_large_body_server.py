"""Host-side HTTP server serving a deterministic large body for stream tests.

Spawned as a subprocess by ``conftest.py`` (one process per pytest
session).  Serves ``GET /stream?size=<n>&framing=<length|chunked>`` — a
body of *n* bytes whose value at absolute offset *i* is ``i % 256`` (a
0..255 repeating ramp).  The pattern is generated per-block, never held
whole, so the host stays flat too; and because every byte is a pure
function of its offset, the board can verify integrity incrementally
without buffering the body or a reference copy.

Two framings, selected by the ``framing`` query param:

* ``length`` (default) — ``Content-Length: <n>``, body written in
  fixed blocks.
* ``chunked`` — ``Transfer-Encoding: chunked``, body written in
  deliberately 256-unaligned chunks so the pattern crosses both chunk
  and period boundaries, exercising the client's chunked decoder + the
  board's incremental verify across those seams.

Built on the stdlib ``http.server`` only — a third-party counterparty
independent of :class:`chumicro_requests.HttpClient`, so client framing
bugs surface as interoperability failures rather than shared mistakes.

Invoked with two args: ``<bind_host> <bind_port>``.  Prints
``READY <bind_host>:<bind_port>`` to stdout once listening so the
parent can wait for liveness (it also probes the port directly).
"""

from __future__ import annotations

import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

#: One period of the ramp.  The whole body is this repeated; slicing a
#: tiling of it yields any offset window without a per-byte loop.
_PERIOD = bytes(range(256))

#: Body-write block size for the ``length`` framing.  A multiple of the
#: 256-byte period keeps block generation a clean repeat.
_BLOCK_SIZE = 4096

#: Chunk size for the ``chunked`` framing.  Deliberately NOT a multiple
#: of 256, so decoded pattern bytes straddle chunk boundaries and the
#: board's verify is tested across them.
_CHUNK_SIZE = 1000


def _pattern_block(start: int, length: int) -> bytes:
    """Return *length* body bytes beginning at absolute offset *start*.

    Byte *k* of the result is ``(start + k) % 256``.  Built by tiling
    :data:`_PERIOD` and slicing at the phase — no per-byte Python loop.
    """
    phase = start % 256
    reps = (phase + length + 255) // 256 + 1
    return (_PERIOD * reps)[phase:phase + length]


class _LargeBodyHandler(BaseHTTPRequestHandler):
    """Serve the deterministic ramp under ``Content-Length`` or chunked."""

    # HTTP/1.1 is required for Transfer-Encoding: chunked, and lets the
    # client rely on framing (Content-Length / terminator chunk) rather
    # than connection close to find end-of-body.
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
        """Dispatch ``GET /stream`` by ``size`` / ``framing`` query params."""
        parsed = urlparse(self.path)
        if parsed.path != "/stream":
            self.send_error(404, "only /stream is served")
            return
        params = parse_qs(parsed.query)
        try:
            size = int(params.get("size", ["0"])[0])
        except ValueError:
            self.send_error(400, "size must be an integer")
            return
        framing = params.get("framing", ["length"])[0]
        try:
            if framing == "chunked":
                self._serve_chunked(size)
            elif framing == "length":
                self._serve_length(size)
            else:
                self.send_error(400, "framing must be 'length' or 'chunked'")
        except (BrokenPipeError, ConnectionResetError):
            # Board hung up mid-transfer (e.g. a cancel() past a byte
            # ceiling).  Not a server fault — drop it quietly.
            return

    def _serve_length(self, size: int) -> None:
        """Send *size* bytes framed by ``Content-Length``."""
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(size))
        self.end_headers()
        offset = 0
        while offset < size:
            count = min(_BLOCK_SIZE, size - offset)
            self.wfile.write(_pattern_block(offset, count))
            offset += count

    def _serve_chunked(self, size: int) -> None:
        """Send *size* bytes framed by ``Transfer-Encoding: chunked``."""
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        offset = 0
        while offset < size:
            count = min(_CHUNK_SIZE, size - offset)
            self.wfile.write(b"%x\r\n" % count)
            self.wfile.write(_pattern_block(offset, count))
            self.wfile.write(b"\r\n")
            offset += count
        self.wfile.write(b"0\r\n\r\n")

    def log_message(self, *args: object) -> None:  # noqa: ARG002 - silence access log
        """Suppress per-request stderr logging (keeps the sweep output clean)."""


def main() -> int:
    """Serve forever on ``argv[1]:argv[2]`` until SIGTERM from the parent."""
    bind_host = sys.argv[1]
    bind_port = int(sys.argv[2])
    httpd = ThreadingHTTPServer((bind_host, bind_port), _LargeBodyHandler)
    sys.stdout.write(f"READY {bind_host}:{bind_port}\n")
    sys.stdout.flush()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
