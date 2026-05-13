"""On-device bench validation for WhenOversized.DROP_WITH_EVENT.

Audit-embedded question (2026-05-12): when an inbound multi-frame
message exceeds ``max_message_bytes`` under ``DROP_WITH_EVENT``, does
the device (a) drain every oversize-payload byte from the socket so
the framing stream stays aligned, and (b) keep the websocket OPEN so
the very next message arrives intact?

Test shape mirrors ``test_real_loopback.py``: a ``WebSocketServer`` and
a ``WebSocketClient`` on the same board exchange frames over real wifi
loopback.  The server reaches into its own ``Connection._socket`` to
push manually-encoded frame bytes — the standard ``send_text`` /
``send_binary`` API always emits ``fin=True`` single frames, so a
fragmented-oversize sequence has to bypass the public surface.  The
client is configured with ``max_message_bytes=400`` + ``DROP_WITH_EVENT``
and observes which callbacks fire.

Single-device loopback is unsupported on Pi Pico W (rp2 lwIP /
CP USB-wedge cluster — same skip the existing loopback test applies).
Runs on the ESP32 family.
"""

import sys
import time

from chumicro_config import config
from chumicro_sockets import tcp_client_socket, tcp_listening_socket
from chumicro_test_harness import skip
from chumicro_timing import ticks_ms as _ticks_ms
from chumicro_websockets import (
    OPCODE_CONTINUATION,
    OPCODE_TEXT,
    WebSocketClient,
    WebSocketServer,
    WebSocketState,
    WhenOversized,
)
from chumicro_websockets._wire import encode_frame
from chumicro_wifi import WifiConfig, WifiService, WifiState

_LISTEN_PORT = 8767
_DEADLINE_MS = 30_000
_WIFI_CONNECT_TIMEOUT_MS = 15_000
_MAX_MESSAGE_BYTES = 400


def _sleep_ms(duration_ms: int) -> None:
    runtime_sleep_ms = getattr(time, "sleep_ms", None)
    if callable(runtime_sleep_ms):
        runtime_sleep_ms(duration_ms)
        return
    time.sleep(duration_ms / 1000)


def _bring_wifi_up(wifi_config: WifiConfig) -> WifiService:
    wifi_config.connect_timeout_ms = _WIFI_CONNECT_TIMEOUT_MS
    wifi = WifiService(wifi_config)
    deadline = _ticks_ms() + _WIFI_CONNECT_TIMEOUT_MS
    while wifi.state != WifiState.CONNECTED:
        if _ticks_ms() > deadline:
            raise AssertionError(
                f"wifi did not link within {_WIFI_CONNECT_TIMEOUT_MS} ms; "
                f"state={wifi.state}",
            )
        if wifi.check(_ticks_ms()):
            wifi.handle(_ticks_ms())
        _sleep_ms(50)
    return wifi


def _is_pi_pico_w_rp2() -> bool:
    """Single-device loopback unsupported on rp2 (same cluster as
    ``test_real_loopback.py``).
    """
    return sys.platform.lower().startswith("rp2")


def _push_raw_to_client(connection, frame_bytes: bytes) -> None:
    """Send pre-encoded frame bytes through the server-side socket.

    Bypasses ``send_text`` / ``send_binary`` so the test can emit a
    fragmented sequence — the public outbound API always sends
    ``fin=True`` single frames.
    """
    offset = 0
    while offset < len(frame_bytes):
        sent = connection._socket.send(frame_bytes[offset:])  # noqa: SLF001 — test-only reach
        if sent is None or sent == 0:
            _sleep_ms(10)
            continue
        offset += sent


def test_drop_with_event_drains_oversize_and_stays_open() -> None:
    """Bench-validate the DROP_WITH_EVENT contract on a real board.

    Sequence: 3 × 200 B fragmented frames (assembled = 600 B, cap 400)
    followed by a 30 B normal frame.  Verifies on_oversized fires,
    state remains OPEN, and the next message reaches on_text intact.
    """
    wifi_cfg = WifiConfig.try_from_config(config)
    if wifi_cfg is None:
        raise AssertionError(
            "wifi runtime config missing — the conftest's "
            "`set_runtime_config(..., required_keys=...)` should have "
            "skipped this test at collection time.  Reaching this body "
            "means the conftest's required_keys list is incomplete.",
        )
    if _is_pi_pico_w_rp2():
        skip(
            "single-device loopback unsupported on rp2 "
            "(lwIP self-loopback + CP USB wedge cluster); run on ESP32 family",
        )

    wifi = _bring_wifi_up(wifi_cfg)
    print(f"WIFI_OK ip={wifi.ip}")

    # --- Server side ---------------------------------------------------
    accepted_connections = []
    raw_frames_pushed = []

    def on_connection(connection):
        accepted_connections.append(connection)

    listener = tcp_listening_socket(
        host="0.0.0.0",
        port=_LISTEN_PORT,
        radio=wifi.adapter.radio,
    )
    server = WebSocketServer(
        listener=listener,
        on_connection=on_connection,
        max_connections=1,
    )
    server.handle(_ticks_ms())
    _sleep_ms(50)
    print(f"SERVER_OK port={_LISTEN_PORT}")

    # --- Client side ---------------------------------------------------
    client_text = []
    client_oversized = []

    def make_socket(host, port, use_tls):  # noqa: ARG001 - protocol
        return tcp_client_socket(host, port, radio=wifi.adapter.radio)

    client = WebSocketClient(
        connection_factory=make_socket,
        max_message_bytes=_MAX_MESSAGE_BYTES,
        when_oversized=WhenOversized.DROP_WITH_EVENT,
    )
    client.on_text = lambda text: client_text.append(text)
    client.on_oversized = lambda reported_length: client_oversized.append(
        reported_length,
    )

    target_url = f"ws://{wifi.ip}:{_LISTEN_PORT}/loopback"
    client.connect(target_url, timeout_ms=10_000)
    print(f"CLIENT_CONNECT url={target_url}")

    # --- Drive both runners + LED counter ------------------------------
    led_counter = 0
    deadline = _ticks_ms() + _DEADLINE_MS
    while True:
        if _ticks_ms() > deadline:
            raise AssertionError(
                f"bench did not complete within {_DEADLINE_MS} ms; "
                f"client.state={client.state} oversized={client_oversized!r} "
                f"text={client_text!r}",
            )
        if wifi.check(_ticks_ms()):
            wifi.handle(_ticks_ms())
        if server.check(_ticks_ms()):
            server.handle(_ticks_ms())
        if client.check(_ticks_ms()):
            client.handle(_ticks_ms())

        # Once handshake completes server-side, push the fragmented
        # oversize sequence + a normal follow-up.  Server-to-client
        # frames must NOT be masked (RFC 6455 §5.1).
        if accepted_connections and not raw_frames_pushed:
            connection = accepted_connections[0]
            if connection.state == WebSocketState.OPEN:
                raw_frames_pushed.append(True)
                _push_raw_to_client(
                    connection,
                    encode_frame(OPCODE_TEXT, b"A" * 200, fin=False, mask=None)
                    + encode_frame(OPCODE_CONTINUATION, b"B" * 200, fin=False, mask=None)
                    + encode_frame(OPCODE_CONTINUATION, b"C" * 200, fin=True, mask=None)
                    + encode_frame(OPCODE_TEXT, b"after-oversize", fin=True, mask=None),
                )
                print("RAW_FRAMES_PUSHED total=660B oversize=3frames normal=1frame")

        if (
            client_oversized
            and client_text
            and client.state == WebSocketState.OPEN
        ):
            client.close()

        if (
            client.state == WebSocketState.CLOSED
            and server.connection_count == 0
        ):
            break

        led_counter += 1
        _sleep_ms(20)

    print(
        f"DROP_WITH_EVENT_OK oversized={client_oversized!r} "
        f"text={client_text!r} led_ticks={led_counter}",
    )

    # --- Real assertions -----------------------------------------------
    assert client_oversized, "on_oversized never fired"
    # reported_length is the size we observed before halting the extend
    # — somewhere ≤ max_message_bytes (parser stops appending at the cap)
    # and > 0 (at least the first frame landed in the buffer).
    assert all(0 < length <= _MAX_MESSAGE_BYTES for length in client_oversized), (
        f"reported_length out of expected (0, {_MAX_MESSAGE_BYTES}] range: "
        f"{client_oversized!r}"
    )
    assert client_text == ["after-oversize"], (
        f"next message after oversize lost or corrupted; got {client_text!r}"
    )
    assert led_counter > 5, (
        f"LED counter only ticked {led_counter} times — "
        f"somebody block-called during the drop-with-event cycle"
    )

    server.close()
