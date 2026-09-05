"""Test fakes and decoders for the chumicro-charlcd transport seam."""

__chumicro_test_support__ = True

#: The PCF8574 bit map the core drives, mirrored here so a test can
#: assert on raw bytes: register select, enable, and backlight.
REGISTER_SELECT = 0x01
ENABLE = 0x04
BACKLIGHT = 0x08


class RecordingTransport:
    """Transport fake that records every raw PCF8574 byte."""

    def __init__(self) -> None:
        self.raw: list[int] = []

    def write_byte(self, value: int) -> None:
        """Record the byte instead of touching a bus."""
        self.raw.append(value)


def decode_nibbles(raw: list) -> list:
    """Fold (enable high, enable low) byte pairs into (rs, nibble) pairs.

    Asserts the HD44780 bus discipline while folding: enable pulses
    high then low, and only the enable bit changes within a pair.

    Args:
        raw: The byte stream a ``RecordingTransport`` captured.

    Returns:
        One ``(register_select, nibble)`` tuple per enable pulse.
    """
    assert len(raw) % 2 == 0, "every nibble is exactly two bus writes"
    nibbles = []
    for pair_index in range(0, len(raw), 2):
        high = raw[pair_index]
        low = raw[pair_index + 1]
        assert high & ENABLE, "first write of a pair must pulse enable high"
        assert not low & ENABLE, "second write must drop enable"
        assert high & ~ENABLE == low, "only the enable bit may change"
        nibbles.append((low & REGISTER_SELECT, low >> 4))
    return nibbles


def decode_bytes(raw: list) -> list:
    """Fold nibble pairs into (rs, byte) pairs; use on post-init traffic.

    Args:
        raw: The byte stream a ``RecordingTransport`` captured, starting
            at a full-byte boundary (after the 4-bit mode-force dance).

    Returns:
        One ``(register_select, value)`` tuple per HD44780 command or
        data byte.
    """
    nibbles = decode_nibbles(raw)
    assert len(nibbles) % 2 == 0, "post-init traffic is full bytes"
    decoded = []
    for pair_index in range(0, len(nibbles), 2):
        select_high, high = nibbles[pair_index]
        select_low, low = nibbles[pair_index + 1]
        assert select_high == select_low, "both nibbles of a byte carry the same RS"
        decoded.append((select_high, (high << 4) | low))
    return decoded
