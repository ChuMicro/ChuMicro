#!/usr/bin/env python3
"""Controllable TCP proxy for MQTT negative-testing bakes.

The negative-testing suite's A-series scenarios were originally designed
around host firewall control (``pfctl``), which needs root.  This proxy
replaces that: a board dials the proxy instead of the broker directly,
and the proxy forwards the byte streams both ways.  A tiny line-oriented
TCP control port lets the bake harness provoke failures on demand:

* ``blackhole on|off`` — silently stop forwarding BOTH directions (ALL
  connections) while keeping the sockets open.  Bytes are received and
  discarded, so the board's TCP sends still succeed but nothing arrives at
  the far end and nothing comes back — the NAT-silent-drop simulation
  (scenario B1).  The board hits ``ack_timeout``, transitions to FAILED,
  and self-heals with a fresh connection once the blackhole is lifted.
* ``drop-puback on|off`` — forward everything EXCEPT broker->client PUBACK
  frames (scenario A3).  Publishes flow through untouched; the acks are
  eaten, so the client's in-flight deadline eventually rearms / retries.
* ``delay <ms>|off [b2c|c2b|both]`` — release forwarded data ``<ms>``
  milliseconds after receipt instead of immediately, ordering preserved,
  sockets kept healthy (scenario A9, the slow-but-alive broker).  The
  direction defaults to ``both``; ``delay 4000 b2c`` models late acks
  (board->broker publishes flow at line rate, broker->board PUBACKs come
  back ~4 s late).  ``delay 0`` / ``delay off`` clears the delay for the
  named direction (or both when none is named).  Delayed bytes ride the
  same selector as the data plane — the loop simply shortens its select
  timeout to the next release instant, so nothing busy-spins and no
  connection is stalled by another's delay.
* ``freeze-existing`` / ``thaw`` — ``freeze-existing`` freezes only the
  connections active at the instant it is issued (bytes discarded BOTH
  directions, sockets held open); connections opened afterwards pass
  through unfaulted.  Unlike the global ``blackhole``, a board that
  re-dials after a freeze reaches the broker cleanly — the topology
  scenario A7 needs (a frozen half-open ghost while a same-``client_id``
  re-dial forces the broker's MQTT 3.1.4 takeover).  ``thaw`` clears the
  freeze on every connection.
* ``kill`` — hard-close (RST) both sockets of every active connection
  (scenario A1's abrupt broker death).
* ``stat`` — a global summary line (flags, delays, per-direction byte /
  frame counters, connection counts) followed by one ``conn id=... `` line
  per active connection (id, frozen flag, per-connection byte counts,
  pending delayed-byte depth).  ``conns_active=N`` on the summary line says
  exactly how many per-connection lines follow.

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
from collections import deque
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
    delay_c2b_ms: int = 0  # board->broker forward latency, milliseconds (0 = off)
    delay_b2c_ms: int = 0  # broker->board forward latency, milliseconds (0 = off)
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
            f"delay_c2b={self.delay_c2b_ms} delay_b2c={self.delay_b2c_ms} "
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
    # Per-connection freeze (scenario A7): when set, this connection discards
    # BOTH directions with the sockets held open, exactly like ``blackhole``
    # but scoped to this one connection so a fresh re-dial is unaffected.
    frozen: bool = False
    # Set when the board abandons a FROZEN connection (its self-heal closes
    # the dead socket).  The broker leg is held open regardless — the literal
    # A7 half-open ghost — so the broker still owns a stale session for the
    # client_id until it evicts it (MUST_DISCONNECT_EXISTING) or ``thaw``
    # tears the remnant down.  Without this, the board-side FIN would
    # propagate and kill the ghost before the re-dial arrives.
    board_gone: bool = False
    # Per-connection byte tallies, so ``stat`` can attribute traffic to a
    # specific connection (the controller counters are cumulative across all
    # connections, including closed ones).
    bytes_c2b_recv: int = 0
    bytes_c2b_fwd: int = 0
    bytes_b2c_recv: int = 0
    bytes_b2c_fwd: int = 0
    # Delayed-release queues (scenario A9).  Each entry is ``(release_monotonic,
    # chunk)``; enqueued in arrival order and released strictly FIFO so ordering
    # is preserved even if the delay is retuned mid-flight.
    _pending_c2b: deque[tuple[float, bytes]] = field(default_factory=deque)
    _pending_b2c: deque[tuple[float, bytes]] = field(default_factory=deque)
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
            if self.frozen:
                self.board_gone = True
                return True  # Hold the broker leg open (A7 half-open ghost).
            return False
        if not data:
            if self.frozen:
                self.board_gone = True
                return True  # Hold the broker leg open (A7 half-open ghost).
            return False  # Board closed its side.
        self.controller.bytes_c2b_recv += len(data)
        self.bytes_c2b_recv += len(data)
        if self.controller.blackhole or self.frozen:
            return True  # Silent drop: received and discarded, socket stays open.
        return self._forward_to_broker(data)

    def _pump_broker_to_client(self) -> bool:
        try:
            data = self.broker.recv(RECV_CHUNK)
        except OSError:
            return False
        if not data:
            return False  # Broker closed its side.
        self.controller.bytes_b2c_recv += len(data)
        self.bytes_b2c_recv += len(data)
        if self.controller.blackhole or self.frozen:
            return True  # Silent drop.
        try:
            forward = self.filter.feed(data, self.controller.drop_puback)
        except ProxyFrameError:
            return False  # Unalignable stream: tear down.
        alive = self._forward_to_client(forward) if forward else True
        self._sync_frame_counts()
        return alive

    # -- forwarding (immediate or delayed release) -------------------------

    def _forward_to_broker(self, data: bytes) -> bool:
        if self.controller.delay_c2b_ms > 0:
            release = time.monotonic() + self.controller.delay_c2b_ms / 1000.0
            self._pending_c2b.append((release, data))
            return True
        return self._send_to_broker(data)

    def _forward_to_client(self, data: bytes) -> bool:
        if self.controller.delay_b2c_ms > 0:
            release = time.monotonic() + self.controller.delay_b2c_ms / 1000.0
            self._pending_b2c.append((release, data))
            return True
        return self._send_to_client(data)

    def _send_to_broker(self, data: bytes) -> bool:
        try:
            self.broker.sendall(data)
        except OSError:
            return False
        self.controller.bytes_c2b_fwd += len(data)
        self.bytes_c2b_fwd += len(data)
        return True

    def _send_to_client(self, data: bytes) -> bool:
        try:
            self.board.sendall(data)
        except OSError:
            return False
        self.controller.bytes_b2c_fwd += len(data)
        self.bytes_b2c_fwd += len(data)
        return True

    def flush_due(self, now: float) -> bool:
        """Release any delayed chunks whose hold time has elapsed.

        Returns True to keep the connection, False when a send failed and it
        should be torn down.  Released FIFO so ordering is preserved.
        """
        while self._pending_c2b and self._pending_c2b[0][0] <= now:
            if not self._send_to_broker(self._pending_c2b.popleft()[1]):
                return False
        while self._pending_b2c and self._pending_b2c[0][0] <= now:
            if not self._send_to_client(self._pending_b2c.popleft()[1]):
                return False
        return True

    def next_release(self) -> float | None:
        """Earliest pending release instant across both directions, or None."""
        heads = []
        if self._pending_c2b:
            heads.append(self._pending_c2b[0][0])
        if self._pending_b2c:
            heads.append(self._pending_b2c[0][0])
        return min(heads) if heads else None

    def stat_line(self) -> str:
        """Per-connection snapshot line for the ``stat`` command."""
        return (
            f"conn id={self.conn_id} frozen={1 if self.frozen else 0} "
            f"half_open={1 if self.board_gone else 0} "
            f"c2b_recv={self.bytes_c2b_recv} c2b_fwd={self.bytes_c2b_fwd} "
            f"b2c_recv={self.bytes_b2c_recv} b2c_fwd={self.bytes_b2c_fwd} "
            f"pend_c2b={len(self._pending_c2b)} pend_b2c={len(self._pending_b2c)}"
        )

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
    "commands: blackhole on|off | drop-puback on|off | "
    "delay <ms>|off [b2c|c2b|both] | freeze-existing | thaw | kill | "
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
                for key, _mask in self.selector.select(timeout=self._select_timeout()):
                    handler = key.data
                    handler(key.fileobj)
                self._flush_delayed()
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
            return
        if conn.board_gone and sock is conn.board:
            # Frozen ghost: the board's leg is dead but the broker leg stays
            # open.  Drop the dead socket from the selector so its perpetual
            # EOF-readable state can't spin the loop.
            try:
                self.selector.unregister(conn.board)
            except (KeyError, ValueError):
                pass
            try:
                conn.board.close()
            except OSError:
                pass
            self._log(
                f"conn {conn.conn_id} board leg closed; broker leg held "
                f"(frozen half-open ghost)"
            )

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

    # -- delayed release (scenario A9) -------------------------------------

    def _select_timeout(self) -> float:
        """How long the next ``select`` may block.

        Normally 1 s (the housekeeping cadence).  When any connection holds a
        delayed chunk, shorten it to the nearest release instant so the loop
        wakes exactly in time to forward — riding the existing selector rather
        than sleeping in the forward path, and never busy-spinning: once the
        queues drain the timeout returns to 1 s.
        """
        earliest: float | None = None
        for conn in self._connections.values():
            release = conn.next_release()
            if release is not None and (earliest is None or release < earliest):
                earliest = release
        if earliest is None:
            return 1.0
        return max(0.0, min(1.0, earliest - time.monotonic()))

    def _flush_delayed(self) -> None:
        """Release every delayed chunk whose hold time has elapsed."""
        now = time.monotonic()
        for conn in list(self._connections.values()):
            if not conn.flush_due(now):
                self._teardown(conn)

    def _freeze_existing(self) -> int:
        """Freeze every currently-active connection (scenario A7).

        Connections opened after this call are untouched, so a same-client_id
        re-dial reaches the broker cleanly while the ghost stays frozen.
        """
        frozen = 0
        for conn in self._connections.values():
            conn.frozen = True
            frozen += 1
        self._log(f"freeze-existing -> {frozen} connection(s) frozen")
        return frozen

    def _thaw_all(self) -> int:
        """Clear the freeze on every connection; returns how many were frozen.

        Half-open ghosts (board leg already abandoned while frozen) cannot
        resume — their broker leg is torn down instead of thawed.
        """
        thawed = 0
        for conn in list(self._connections.values()):
            if conn.frozen:
                thawed += 1
                if conn.board_gone:
                    self._teardown(conn)
                else:
                    conn.frozen = False
        self._log(f"thaw -> {thawed} connection(s) thawed")
        return thawed

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
        if command == "delay":
            direction = parts[2].lower() if len(parts) > 2 else "both"
            return self._set_delay(argument, direction)
        if command == "freeze-existing":
            return f"ok froze {self._freeze_existing()}"
        if command == "thaw":
            return f"ok thawed {self._thaw_all()}"
        if command == "kill":
            return f"ok killed {self._kill_all()}"
        if command == "stat":
            return self._stat_report()
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

    _DELAY_USAGE = "err usage: delay <ms>|off [b2c|c2b|both]"

    def _set_delay(self, value: str | None, direction: str) -> str:
        """Set (or clear) the per-direction forward latency in milliseconds."""
        if direction not in ("b2c", "c2b", "both"):
            return self._DELAY_USAGE
        if value is None:
            return self._DELAY_USAGE
        if value == "off":
            milliseconds = 0
        else:
            try:
                milliseconds = int(value)
            except ValueError:
                return self._DELAY_USAGE
            if milliseconds < 0:
                return self._DELAY_USAGE
        if direction in ("c2b", "both"):
            self.controller.delay_c2b_ms = milliseconds
        if direction in ("b2c", "both"):
            self.controller.delay_b2c_ms = milliseconds
        self._log(f"delay -> {milliseconds}ms {direction}")
        return f"ok delay {milliseconds} {direction}"

    def _stat_report(self) -> str:
        """Global summary line followed by one line per active connection."""
        lines = [self.controller.stat_line()]
        for conn in sorted(self._connections.values(), key=lambda entry: entry.conn_id):
            lines.append(conn.stat_line())
        return "\n".join(lines)

    def _reset_stats(self) -> None:
        for attribute in (
            "bytes_c2b_recv", "bytes_c2b_fwd", "bytes_b2c_recv", "bytes_b2c_fwd",
            "frames_forwarded", "frames_dropped", "connections_total",
        ):
            setattr(self.controller, attribute, 0)
        for conn in self._connections.values():
            conn.bytes_c2b_recv = conn.bytes_c2b_fwd = 0
            conn.bytes_b2c_recv = conn.bytes_b2c_fwd = 0
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
