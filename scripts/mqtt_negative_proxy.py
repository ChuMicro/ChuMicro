#!/usr/bin/env python3
"""Controllable TCP proxy for MQTT negative-testing bakes.

The negative-testing suite's A-series scenarios were originally designed
around host firewall control (``pfctl``), which needs root.  This proxy
replaces that: a board dials the proxy instead of the broker directly,
and the proxy forwards the byte streams both ways.  A tiny line-oriented
TCP control port lets the bake harness provoke failures on demand:

* ``blackhole on|off`` — silently stop forwarding BOTH directions while
  keeping the sockets open.  Bytes are received and discarded, so the
  board's TCP sends still succeed but nothing arrives at the far end and
  nothing comes back — the NAT-silent-drop simulation (scenario B1).  The
  board hits ``ack_timeout``, transitions to FAILED, and self-heals with a
  fresh connection once the blackhole is lifted.
* ``drop-puback on|off`` — forward everything EXCEPT broker->client PUBACK
  frames (scenario A3).  Publishes flow through untouched; the acks are
  eaten, so the client's in-flight deadline eventually rearms / retries.
* ``kill`` — hard-close (RST) both sockets of every active connection
  (scenario A1's abrupt broker death).
* ``stat`` — bytes / frames forwarded per direction, connection counts.

The proxy is single-threaded and selectors-based: the data plane and the
control plane share one selector, so flag mutations from a control command
are seen by the next pump with no locks.  New inbound connections are
accepted at any time, so a self-healing client that abandons a dead socket
and reconnects is handled transparently (each connection owns a fresh
frame filter).

Host CPython 3.11+, stdlib only.  Run directly::

    python scripts/mqtt_negative_proxy.py \
        --listen-port 18830 --broker-port 1883 --control-port 18831

then drive it from another process::

    printf 'drop-puback on\n' | nc 127.0.0.1 18831
"""

from __future__ import annotations

import argparse
import selectors
import socket
import struct
import sys
import time
from dataclasses import dataclass, field

# Size of each recv() pull.  Large enough to swallow a 4 KB PUBLISH plus
# header in one read on localhost, small enough to stay frame-streaming.
RECV_CHUNK = 65536

# MQTT fixed-header packet-type nibbles (high nibble of the first byte).
_PUBACK_TYPE = 0x40  # (0x4 << 4); the acks drop-puback eats.


class ProxyFrameError(Exception):
    """A broker->client byte stream was not frame-alignable MQTT.

    Raised only by the PUBACK filter when a remaining-length varint runs
    past MQTT 3.1.1's four-byte cap — a malformed stream the proxy cannot
    stay aligned on.  The connection is torn down when this surfaces.
    """


def decode_remaining_length(data: bytes | bytearray, start: int = 0) -> tuple[int | None, int]:
    """Decode an MQTT variable-length remaining-length field.

    Reads the varint beginning at *start*.  Returns ``(value, consumed)``
    where *consumed* is the number of bytes the varint occupied.  Returns
    ``(None, 0)`` when the buffer does not yet hold a complete varint
    (the caller should pull more bytes and retry).  Raises
    :class:`ProxyFrameError` when the varint continues past four bytes,
    which MQTT 3.1.1 forbids.
    """
    value = 0
    for index in range(4):  # MQTT 3.1.1 caps the remaining-length varint at 4 bytes.
        offset = start + index
        if offset >= len(data):
            return None, 0  # Incomplete: need more bytes.
        digit = data[offset]
        value |= (digit & 0x7F) << (7 * index)
        if not (digit & 0x80):
            return value, index + 1
    raise ProxyFrameError("remaining-length varint exceeds 4 bytes")


class PubackFilter:
    """Streaming MQTT frame classifier for one broker->client direction.

    Feed it the bytes arriving from the broker; it returns the subset to
    forward to the board, dropping any complete PUBACK frame when asked.
    It stays frame-aligned across arbitrary TCP segmentation by parsing
    each frame's fixed header (type byte + remaining-length varint) and
    then streaming exactly ``remaining_length`` body bytes before looking
    for the next header — so a header split mid-varint, or a body split
    across three segments, both classify correctly.

    The drop decision is read from the ``drop_pubacks`` argument at the
    moment a frame's header completes and is then latched for that whole
    frame, so toggling the flag mid-body never truncates a frame.

    One filter instance belongs to one connection; a reconnect gets a
    fresh instance that starts aligned on the new stream's first frame
    (a CONNACK).
    """

    def __init__(self) -> None:
        self._header = bytearray()  # Fixed-header bytes accumulated so far (type + varint).
        self._in_body = False  # True while streaming a classified frame's body.
        self._body_remaining = 0  # Body bytes still to stream for the current frame.
        self._body_drop = False  # Latched: is the current frame being dropped?
        self._body_is_puback = False  # Latched: is the current frame a PUBACK?
        self.frames_forwarded = 0
        self.frames_dropped = 0

    def feed(self, data: bytes, drop_pubacks: bool) -> bytes:
        """Classify *data* and return the bytes to forward downstream.

        *drop_pubacks* selects behaviour for PUBACK frames whose header
        completes within this call: dropped when True, forwarded when
        False.  Every non-PUBACK frame is always forwarded.
        """
        out = bytearray()
        index = 0
        size = len(data)
        while index < size:
            if self._in_body:
                take = min(self._body_remaining, size - index)
                if not self._body_drop:
                    out += data[index : index + take]
                index += take
                self._body_remaining -= take
                if self._body_remaining == 0:
                    self._finish_frame()
                continue

            # Header-accumulation state: consume one byte and retry the parse.
            self._header.append(data[index])
            index += 1
            remaining = self._parse_header()
            if remaining is None:
                continue  # Header (type or varint) still incomplete.

            is_puback = (self._header[0] & 0xF0) == _PUBACK_TYPE
            drop = is_puback and drop_pubacks
            if not drop:
                out += self._header
            self._body_is_puback = is_puback
            self._body_drop = drop
            self._body_remaining = remaining
            self._in_body = True
            self._header = bytearray()
            if remaining == 0:
                self._finish_frame()
        return bytes(out)

    def _parse_header(self) -> int | None:
        """Return the current frame's remaining-length, or None if incomplete."""
        if len(self._header) < 2:
            return None  # Need the type byte plus at least one varint byte.
        value, consumed = decode_remaining_length(self._header, 1)
        if consumed == 0:
            return None  # Varint still incomplete (decode raises on malformed).
        return value

    def _finish_frame(self) -> None:
        """Tally a completed frame and return to header-accumulation."""
        if self._body_drop:
            self.frames_dropped += 1
        else:
            self.frames_forwarded += 1
        self._in_body = False


@dataclass
class Controller:
    """Live control flags and forwarding counters, shared by all connections.

    Single-threaded: the control command handler and the data pumps run in
    the same selector loop, so a flag flipped by a command is seen by the
    next pump without locking.
    """

    blackhole: bool = False
    drop_puback: bool = False
    bytes_c2b_recv: int = 0  # board->broker bytes received by the proxy
    bytes_c2b_fwd: int = 0  # board->broker bytes actually forwarded
    bytes_b2c_recv: int = 0  # broker->board bytes received by the proxy
    bytes_b2c_fwd: int = 0  # broker->board bytes actually forwarded (post-filter)
    frames_forwarded: int = 0  # broker->board MQTT frames forwarded
    frames_dropped: int = 0  # broker->board PUBACK frames eaten by drop-puback
    connections_total: int = 0
    connections_active: int = 0

    def stat_line(self) -> str:
        """One-line, machine-parseable snapshot for the ``stat`` command."""
        return (
            f"blackhole={'on' if self.blackhole else 'off'} "
            f"drop_puback={'on' if self.drop_puback else 'off'} "
            f"conns_active={self.connections_active} "
            f"conns_total={self.connections_total} "
            f"c2b_recv={self.bytes_c2b_recv} c2b_fwd={self.bytes_c2b_fwd} "
            f"b2c_recv={self.bytes_b2c_recv} b2c_fwd={self.bytes_b2c_fwd} "
            f"frames_fwd={self.frames_forwarded} pubacks_dropped={self.frames_dropped}"
        )


@dataclass
class ProxyConnection:
    """One board<->broker connection pair and its broker->client frame filter."""

    conn_id: int
    board: socket.socket
    broker: socket.socket
    controller: Controller
    filter: PubackFilter = field(default_factory=PubackFilter)
    _last_forwarded: int = 0
    _last_dropped: int = 0

    def pump(self, ready: socket.socket) -> bool:
        """Move data for whichever socket signalled readable.

        Returns True to keep the connection, False when it should be torn
        down (peer closed or socket error).
        """
        if ready is self.board:
            return self._pump_board_to_broker()
        return self._pump_broker_to_client()

    def _pump_board_to_broker(self) -> bool:
        try:
            data = self.board.recv(RECV_CHUNK)
        except OSError:
            return False
        if not data:
            return False  # Board closed its side.
        self.controller.bytes_c2b_recv += len(data)
        if self.controller.blackhole:
            return True  # Silent drop: received and discarded, socket stays open.
        try:
            self.broker.sendall(data)
        except OSError:
            return False
        self.controller.bytes_c2b_fwd += len(data)
        return True

    def _pump_broker_to_client(self) -> bool:
        try:
            data = self.broker.recv(RECV_CHUNK)
        except OSError:
            return False
        if not data:
            return False  # Broker closed its side.
        self.controller.bytes_b2c_recv += len(data)
        if self.controller.blackhole:
            return True  # Silent drop.
        try:
            forward = self.filter.feed(data, self.controller.drop_puback)
        except ProxyFrameError:
            return False  # Unalignable stream: tear down.
        if forward:
            try:
                self.board.sendall(forward)
            except OSError:
                return False
            self.controller.bytes_b2c_fwd += len(forward)
        self._sync_frame_counts()
        return True

    def _sync_frame_counts(self) -> None:
        """Fold this connection's new frame tallies into the shared counters."""
        self.controller.frames_forwarded += self.filter.frames_forwarded - self._last_forwarded
        self.controller.frames_dropped += self.filter.frames_dropped - self._last_dropped
        self._last_forwarded = self.filter.frames_forwarded
        self._last_dropped = self.filter.frames_dropped


class ControlSession:
    """Line-buffered state for one open control connection."""

    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self.buffer = bytearray()


@dataclass
class ProxyConfig:
    listen_host: str = "127.0.0.1"
    listen_port: int = 18830
    broker_host: str = "127.0.0.1"
    broker_port: int = 1883
    control_host: str = "127.0.0.1"
    control_port: int = 18831
    connect_timeout: float = 10.0
    blackhole: bool = False
    drop_puback: bool = False
    verbose: bool = False


_CONTROL_HELP = (
    "commands: blackhole on|off | drop-puback on|off | kill | "
    "stat | reset-stats | help | quit"
)


class NegativeProxy:
    """Selectors-driven controllable TCP proxy (see module docstring)."""

    def __init__(self, config: ProxyConfig) -> None:
        self.config = config
        self.controller = Controller(
            blackhole=config.blackhole, drop_puback=config.drop_puback
        )
        self.selector = selectors.DefaultSelector()
        self._connections: dict[int, ProxyConnection] = {}
        self._next_conn_id = 1
        self._data_server: socket.socket | None = None
        self._control_server: socket.socket | None = None

    # -- lifecycle ---------------------------------------------------------

    def run(self) -> None:
        self._data_server = self._listen(self.config.listen_host, self.config.listen_port)
        self._control_server = self._listen(self.config.control_host, self.config.control_port)
        self.selector.register(self._data_server, selectors.EVENT_READ, self._accept_data)
        self.selector.register(self._control_server, selectors.EVENT_READ, self._accept_control)
        self._log(
            f"listening data {self.config.listen_host}:{self.config.listen_port} "
            f"-> broker {self.config.broker_host}:{self.config.broker_port}; "
            f"control {self.config.control_host}:{self.config.control_port}"
        )
        try:
            while True:
                for key, _mask in self.selector.select(timeout=1.0):
                    handler = key.data
                    handler(key.fileobj)
        except KeyboardInterrupt:
            self._log("interrupted, shutting down")
        finally:
            self.close()

    def close(self) -> None:
        for conn in list(self._connections.values()):
            self._teardown(conn)
        for server in (self._data_server, self._control_server):
            if server is not None:
                self.selector.unregister(server)
                server.close()
        self.selector.close()
        self._data_server = None
        self._control_server = None

    @staticmethod
    def _listen(host: str, port: int) -> socket.socket:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((host, port))
        server.listen(16)
        server.setblocking(False)
        return server

    # -- data plane --------------------------------------------------------

    def _accept_data(self, server: socket.socket) -> None:
        try:
            board, address = server.accept()
        except OSError:
            return
        try:
            broker = socket.create_connection(
                (self.config.broker_host, self.config.broker_port),
                timeout=self.config.connect_timeout,
            )
        except OSError as error:
            self._log(f"broker dial failed for {address}: {error}")
            board.close()
            return
        board.setblocking(True)
        broker.setblocking(True)
        conn = ProxyConnection(
            conn_id=self._next_conn_id, board=board, broker=broker, controller=self.controller
        )
        self._next_conn_id += 1
        self._connections[conn.conn_id] = conn
        self.controller.connections_total += 1
        self.controller.connections_active += 1
        self.selector.register(board, selectors.EVENT_READ, self._service_connection)
        self.selector.register(broker, selectors.EVENT_READ, self._service_connection)
        self._log(f"conn {conn.conn_id} up: board {address} <-> broker")

    def _service_connection(self, sock: socket.socket) -> None:
        conn = self._find_connection(sock)
        if conn is None:
            return
        if not conn.pump(sock):
            self._teardown(conn)

    def _find_connection(self, sock: socket.socket) -> ProxyConnection | None:
        for conn in self._connections.values():
            if sock is conn.board or sock is conn.broker:
                return conn
        return None

    def _teardown(self, conn: ProxyConnection, *, hard: bool = False) -> None:
        if conn.conn_id not in self._connections:
            return
        del self._connections[conn.conn_id]
        self.controller.connections_active -= 1
        for sock in (conn.board, conn.broker):
            try:
                self.selector.unregister(sock)
            except (KeyError, ValueError):
                pass
            if hard:
                _set_abortive_close(sock)
            try:
                sock.close()
            except OSError:
                pass
        self._log(f"conn {conn.conn_id} down{' (killed)' if hard else ''}")

    def _kill_all(self) -> int:
        killed = 0
        for conn in list(self._connections.values()):
            self._teardown(conn, hard=True)
            killed += 1
        return killed

    # -- control plane -----------------------------------------------------

    def _accept_control(self, server: socket.socket) -> None:
        try:
            sock, _address = server.accept()
        except OSError:
            return
        sock.setblocking(True)
        session = ControlSession(sock)
        self.selector.register(sock, selectors.EVENT_READ, self._service_control(session))
        self._send(sock, _CONTROL_HELP)

    def _service_control(self, session: ControlSession):
        def handle(sock: socket.socket) -> None:
            try:
                data = sock.recv(4096)
            except OSError:
                data = b""
            if not data:
                self._close_control(session)
                return
            session.buffer += data
            while b"\n" in session.buffer:
                line, _, rest = session.buffer.partition(b"\n")
                session.buffer = bytearray(rest)
                response = self._dispatch(line.decode("utf-8", "replace").strip())
                if response is None:
                    self._close_control(session)
                    return
                self._send(sock, response)

        return handle

    def _close_control(self, session: ControlSession) -> None:
        try:
            self.selector.unregister(session.sock)
        except (KeyError, ValueError):
            pass
        try:
            session.sock.close()
        except OSError:
            pass

    def _dispatch(self, line: str) -> str | None:
        """Return the response for a control *line*, or None to close the session."""
        if not line:
            return ""
        parts = line.split()
        command = parts[0].lower()
        argument = parts[1].lower() if len(parts) > 1 else None

        if command == "blackhole":
            return self._set_flag("blackhole", argument)
        if command == "drop-puback":
            return self._set_flag("drop_puback", argument)
        if command == "kill":
            return f"ok killed {self._kill_all()}"
        if command == "stat":
            return self.controller.stat_line()
        if command == "reset-stats":
            self._reset_stats()
            return "ok reset-stats"
        if command == "help":
            return _CONTROL_HELP
        if command in ("quit", "exit", "close"):
            return None
        return f"err unknown command: {command}"

    def _set_flag(self, attribute: str, argument: str | None) -> str:
        if argument not in ("on", "off"):
            return f"err usage: {attribute.replace('_', '-')} on|off"
        setattr(self.controller, attribute, argument == "on")
        self._log(f"{attribute} -> {argument}")
        return f"ok {attribute.replace('_', '-')} {argument}"

    def _reset_stats(self) -> None:
        for attribute in (
            "bytes_c2b_recv", "bytes_c2b_fwd", "bytes_b2c_recv", "bytes_b2c_fwd",
            "frames_forwarded", "frames_dropped", "connections_total",
        ):
            setattr(self.controller, attribute, 0)
        for conn in self._connections.values():
            conn._last_forwarded = conn.filter.frames_forwarded
            conn._last_dropped = conn.filter.frames_dropped

    # -- helpers -----------------------------------------------------------

    def _send(self, sock: socket.socket, text: str) -> None:
        try:
            sock.sendall(text.encode("utf-8") + b"\n")
        except OSError:
            pass

    def _log(self, message: str) -> None:
        if self.config.verbose:
            print(f"[{time.strftime('%H:%M:%S')}] proxy: {message}", file=sys.stderr, flush=True)


def _set_abortive_close(sock: socket.socket) -> None:
    """Arm SO_LINGER(0) so the following close() sends a RST, not a FIN.

    Mirrors a broker hard-kill / NAT RST, which is what scenario A1 needs
    the client to observe rather than a graceful FIN.
    """
    try:
        sock.setsockopt(
            socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)
        )
    except OSError:
        pass


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=18830)
    parser.add_argument("--broker-host", default="127.0.0.1")
    parser.add_argument("--broker-port", type=int, default=1883)
    parser.add_argument("--control-host", default="127.0.0.1")
    parser.add_argument("--control-port", type=int, default=18831)
    parser.add_argument("--connect-timeout", type=float, default=10.0)
    parser.add_argument(
        "--blackhole", action="store_true", help="start with blackhole engaged"
    )
    parser.add_argument(
        "--drop-puback", action="store_true", help="start with PUBACK-drop engaged"
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    config = ProxyConfig(
        listen_host=args.listen_host,
        listen_port=args.listen_port,
        broker_host=args.broker_host,
        broker_port=args.broker_port,
        control_host=args.control_host,
        control_port=args.control_port,
        connect_timeout=args.connect_timeout,
        blackhole=args.blackhole,
        drop_puback=args.drop_puback,
        verbose=args.verbose,
    )
    NegativeProxy(config).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
