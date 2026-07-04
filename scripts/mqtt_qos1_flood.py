#!/usr/bin/env python3
"""QoS-1 publish flood driver for MQTT negative-testing bakes.

Publishes N small QoS-1 PUBLISH messages per second to a topic, through a
broker (or, for the negative-testing suite, through the controllable proxy
in ``mqtt_negative_proxy.py`` — point ``--port`` at the proxy's listen
port).  Drives scenarios A3 (drop-puback) and D2 (high-rate burst): the
flood keeps publishing while the proxy eats acks or stalls the stream, so
the board / broker behaviour under load is observable.

Transport choice: a self-contained stdlib-socket MQTT 3.1.1 client rather
than shelling out to ``mosquitto_pub``.  ``mosquitto_pub`` at
``/opt/homebrew/bin`` would work for a single publish, but this driver
needs ONE persistent connection held open at a precise rate while it reads
and counts the returning PUBACKs — exactly the ack stream the drop-puback
scenario suppresses.  A subprocess-per-message loop reconnects each time
(no ack visibility, wrong load shape); ``mosquitto_pub -l`` keeps the
connection but hides the acks.  The stdlib client is ~120 lines, keeps the
rate/size/count/topic knobs exact, and makes the acked-vs-sent gap the
headline signal.

Host CPython 3.11+, stdlib only.  Example::

    python scripts/mqtt_qos1_flood.py --port 18830 --topic bake/flood \
        --rate 20 --count 200 --size 32
"""

from __future__ import annotations

import argparse
import select
import socket
import struct
import sys
import time

_CONNACK_LEN = 4  # 0x20, remaining-length 2, session-present, return-code.


def encode_remaining_length(length: int) -> bytes:
    """Encode *length* as an MQTT variable-length integer (1-4 bytes)."""
    out = bytearray()
    while True:
        digit = length & 0x7F
        length >>= 7
        if length:
            digit |= 0x80
        out.append(digit)
        if not length:
            return bytes(out)


def encode_string(value: str | bytes) -> bytes:
    """Encode *value* as MQTT ``2-byte length || UTF-8 bytes``."""
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return struct.pack(">H", len(raw)) + raw


def build_connect(
    client_id: str,
    keepalive: int,
    *,
    clean_session: bool = True,
    username: str | None = None,
    password: str | None = None,
) -> bytes:
    """Build a CONNECT packet (protocol level 4 == MQTT 3.1.1)."""
    flags = 0
    if clean_session:
        flags |= 0x02
    if username is not None:
        flags |= 0x80
    if password is not None:
        flags |= 0x40
    body = bytearray(b"\x00\x04MQTT\x04")
    body.append(flags)
    body += struct.pack(">H", keepalive)
    body += encode_string(client_id)
    if username is not None:
        body += encode_string(username)
    if password is not None:
        body += encode_string(password)
    return bytes([0x10]) + encode_remaining_length(len(body)) + bytes(body)


def build_publish_qos1(topic: str, payload: bytes, packet_id: int, *, dup: bool = False) -> bytes:
    """Build a QoS-1 PUBLISH packet carrying *payload* under *packet_id*."""
    first_byte = 0x30 | 0x02  # PUBLISH | (qos1 << 1)
    if dup:
        first_byte |= 0x08
    variable = encode_string(topic) + struct.pack(">H", packet_id)
    body = variable + payload
    return bytes([first_byte]) + encode_remaining_length(len(body)) + body


def build_payload(sequence: int, size: int) -> bytes:
    """Build a *size*-byte payload tagged with a decodable sequence number."""
    tag = f"{sequence:08d}:".encode()
    if size <= len(tag):
        return tag[:size]
    return tag + b"x" * (size - len(tag))


def _next_packet_id(current: int) -> int:
    """Advance a 16-bit packet id, wrapping 65535 -> 1 (0 is reserved)."""
    return current + 1 if current < 0xFFFF else 1


class MqttFlooder:
    """Minimal MQTT 3.1.1 QoS-1 publisher over a raw socket."""

    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self._recv_buffer = bytearray()
        self.sent = 0
        self.acked = 0

    def connect(
        self,
        client_id: str,
        keepalive: int,
        *,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        """Send CONNECT and block until a success CONNACK arrives."""
        self.sock.sendall(
            build_connect(client_id, keepalive, username=username, password=password)
        )
        self.sock.settimeout(10.0)
        while len(self._recv_buffer) < _CONNACK_LEN:
            chunk = self.sock.recv(1024)
            if not chunk:
                raise ConnectionError("broker closed before CONNACK")
            self._recv_buffer += chunk
        if self._recv_buffer[0] & 0xF0 != 0x20:
            raise ConnectionError(f"expected CONNACK, got byte {self._recv_buffer[0]:#04x}")
        return_code = self._recv_buffer[3]
        if return_code != 0:
            raise ConnectionError(f"CONNACK refused, return code {return_code}")
        del self._recv_buffer[:_CONNACK_LEN]
        self.sock.setblocking(False)

    def publish(self, topic: str, payload: bytes, packet_id: int) -> None:
        """Send one QoS-1 PUBLISH (blocking send, non-blocking socket)."""
        self.sock.setblocking(True)
        self.sock.sendall(build_publish_qos1(topic, payload, packet_id))
        self.sock.setblocking(False)
        self.sent += 1

    def drain_acks(self) -> int:
        """Read and count any PUBACKs currently available without blocking."""
        found = 0
        while True:
            ready, _, _ = select.select([self.sock], [], [], 0)
            if not ready:
                break
            try:
                chunk = self.sock.recv(4096)
            except (BlockingIOError, InterruptedError):
                break
            if not chunk:
                break
            self._recv_buffer += chunk
            found += self._consume_pubacks()
        return found

    def _consume_pubacks(self) -> int:
        """Pop every complete frame from the recv buffer, counting PUBACKs."""
        found = 0
        while len(self._recv_buffer) >= 2:
            remaining, consumed = _decode_len(self._recv_buffer, 1)
            if consumed == 0:
                break  # Fixed header not fully arrived yet.
            frame_len = 1 + consumed + remaining
            if len(self._recv_buffer) < frame_len:
                break  # Body not fully arrived yet.
            if self._recv_buffer[0] & 0xF0 == 0x40:  # PUBACK
                found += 1
                self.acked += 1
            del self._recv_buffer[:frame_len]
        return found


def _decode_len(data: bytearray, start: int) -> tuple[int, int]:
    """Decode an MQTT remaining-length varint; ``(0, 0)`` when incomplete."""
    value = 0
    for index in range(4):
        offset = start + index
        if offset >= len(data):
            return 0, 0
        digit = data[offset]
        value |= (digit & 0x7F) << (7 * index)
        if not (digit & 0x80):
            return value, index + 1
    return 0, 0


def run_flood(args: argparse.Namespace) -> int:
    """Open one connection and publish at the configured rate/size/count."""
    sock = socket.create_connection((args.host, args.port), timeout=10.0)
    flooder = MqttFlooder(sock)
    try:
        flooder.connect(
            args.client_id, args.keepalive, username=args.username, password=args.password
        )
        interval = 1.0 / args.rate if args.rate > 0 else 0.0
        deadline = args.duration and (time.monotonic() + args.duration)
        packet_id = 0
        sequence = 0
        next_send = time.monotonic()
        while args.count == 0 or sequence < args.count:
            now = time.monotonic()
            if next_send > now:
                time.sleep(next_send - now)
            packet_id = _next_packet_id(packet_id)
            flooder.publish(args.topic, build_payload(sequence, args.size), packet_id)
            sequence += 1
            flooder.drain_acks()
            next_send += interval
            if deadline and time.monotonic() >= deadline:
                break
        _grace_drain(flooder, args.ack_grace)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
    finally:
        _print_summary(flooder)
        sock.close()
    return 0


def _grace_drain(flooder: MqttFlooder, grace_seconds: float) -> None:
    """Keep reading PUBACKs for *grace_seconds* after the last publish."""
    end = time.monotonic() + grace_seconds
    while time.monotonic() < end and flooder.acked < flooder.sent:
        flooder.drain_acks()
        time.sleep(0.02)


def _print_summary(flooder: MqttFlooder) -> None:
    print(f"sent={flooder.sent} acked={flooder.acked} unacked={flooder.sent - flooder.acked}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--port", type=int, default=18830, help="broker or proxy listen port"
    )
    parser.add_argument("--topic", default="bake/flood")
    parser.add_argument("--rate", type=float, default=10.0, help="messages per second")
    parser.add_argument(
        "--count", type=int, default=100, help="total messages (0 = until Ctrl-C / duration)"
    )
    parser.add_argument("--size", type=int, default=32, help="payload bytes")
    parser.add_argument(
        "--duration", type=float, default=0.0, help="stop after this many seconds (0 = off)"
    )
    parser.add_argument("--client-id", default="flood-driver")
    parser.add_argument("--username", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--keepalive", type=int, default=60)
    parser.add_argument(
        "--ack-grace", type=float, default=2.0, help="seconds to drain PUBACKs after last publish"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    return run_flood(_build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
