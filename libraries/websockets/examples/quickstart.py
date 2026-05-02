"""Frame-level quickstart for chumicro-websockets — slice 1 demo.

Until WebSocketClient + WebSocketServer land in slices 2 + 3, the
useful public surface is the wire layer.  This example shows the
round-trip: encode a frame, parse it back, recover the payload.

Runs on CPython, MicroPython, and CircuitPython.

Example output::

    Encoded text frame: 9 bytes -> 81 85 6d 61 73 6b 0d 0d 0d
    Parser sees: opcode=1 fin=True payload=b'hello'

    Encoded close frame: 5 bytes
    Parsed close: code=1000 reason='bye'
"""

from chumicro_websockets import (
    CLOSE_NORMAL,
    OPCODE_CLOSE,
    OPCODE_TEXT,
    FrameParser,
    encode_close_payload,
    encode_frame,
    parse_close_payload,
)

mask_key = b"mask"
text_frame = encode_frame(OPCODE_TEXT, b"hello", mask=mask_key)
print(
    f"Encoded text frame: {len(text_frame)} bytes -> "
    f"{' '.join(f'{byte:02x}' for byte in text_frame)}",
)

parser = FrameParser()
parser.feed(text_frame)
print(
    f"Parser sees: opcode={parser.opcode} fin={parser.fin} "
    f"payload={parser.payload!r}",
)
print()

close_body = encode_close_payload(CLOSE_NORMAL, "bye")
close_frame = encode_frame(OPCODE_CLOSE, close_body)
print(f"Encoded close frame: {len(close_frame)} bytes")

parser.reset()
parser.feed(close_frame)
code, reason = parse_close_payload(parser.payload)
print(f"Parsed close: code={code} reason={reason!r}")
