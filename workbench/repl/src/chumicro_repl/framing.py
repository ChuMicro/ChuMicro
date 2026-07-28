"""UTF-8 safe streaming decoder.

Serial reads arrive in arbitrary-sized chunks.  A single UTF-8
code-point can span up to four bytes, and a read boundary can fall in
the middle of a multi-byte sequence, so naive ``bytes.decode("utf-8")``
on each chunk raises :class:`UnicodeDecodeError` on anything above
ASCII.  :class:`Utf8StreamDecoder` buffers the tail bytes of a chunk
that look like the start of a not-yet-complete sequence and prepends
them to the next chunk.

Also forgives one class of garbage: if the stream emits invalid bytes
(e.g. an interrupted power glitch), the decoder replaces them with
``U+FFFD`` so the user sees a replacement character instead of a
crash.
"""

from __future__ import annotations

#: The maximum number of bytes that can form a single UTF-8 code point.
#: A chunk-tail longer than this cannot be "partial": it must contain
#: an invalid byte, so we flush it through the standard error-replace
#: path rather than holding it indefinitely.
_MAX_UTF8_SEQUENCE_BYTES = 4


def _utf8_continuation_start(chunk: bytes) -> int:
    """Return the byte index where a trailing incomplete UTF-8 sequence starts.

    Returns ``len(chunk)`` when the chunk ends on a complete sequence,
    so the caller can decode the whole chunk and keep nothing
    buffered.  Otherwise returns the position of the last leading
    byte, marking where to split so the incomplete tail can be
    prepended to the next chunk.

    Walks backward from the end of *chunk* up to
    :data:`_MAX_UTF8_SEQUENCE_BYTES` bytes looking for the most
    recent leading byte (any byte that does not match the
    ``0b10xxxxxx`` continuation pattern), then checks whether the
    remaining bytes from that position are enough to complete the
    sequence the leading byte introduces.
    """
    chunk_length = len(chunk)
    if chunk_length == 0:
        return 0
    walk_index = chunk_length - 1
    stop_at = max(0, chunk_length - _MAX_UTF8_SEQUENCE_BYTES)
    while walk_index >= stop_at:
        byte_value = chunk[walk_index]
        if (byte_value & 0b1100_0000) != 0b1000_0000:
            # Found the leading byte of the last sequence.
            if byte_value < 0x80:
                # ASCII, a one-byte sequence, complete by definition.
                return chunk_length
            if (byte_value & 0b1110_0000) == 0b1100_0000:
                expected_length = 2
            elif (byte_value & 0b1111_0000) == 0b1110_0000:
                expected_length = 3
            elif (byte_value & 0b1111_1000) == 0b1111_0000:
                expected_length = 4
            else:
                # Malformed leading byte: let decode error-replace it
                # on the next pass rather than buffering indefinitely.
                return chunk_length
            have_length = chunk_length - walk_index
            if have_length < expected_length:
                return walk_index
            return chunk_length
        walk_index -= 1
    # No leading byte found within the look-back window, so the chunk is all
    # continuation bytes, which is malformed.  Flush the lot and let
    # decode error-replace the garbage.
    return chunk_length


class Utf8StreamDecoder:
    """Incremental UTF-8 decoder with chunk-boundary buffering.

    One instance per live stream.  :meth:`decode` returns every
    fully-decodable code point in the chunk so far, holding any
    trailing incomplete sequence for the next call.  :meth:`flush`
    releases the remaining buffered bytes at end-of-stream.  Both
    methods decode with ``errors="replace"``, so a caller never sees
    :class:`UnicodeDecodeError`.

    Example::

        decoder = Utf8StreamDecoder()
        first_half = bytes([0xF0, 0x9F])  # start of "🙂" (4 bytes)
        second_half = bytes([0x99, 0x82])
        assert decoder.decode(first_half) == ""
        assert decoder.decode(second_half) == "🙂"
    """

    __slots__ = ("_buffer",)

    def __init__(self) -> None:
        self._buffer = bytearray()

    def decode(self, chunk: bytes | bytearray | memoryview) -> str:
        """Decode *chunk*, returning every fully-decodable code point.

        Bytes from the start of a not-yet-complete sequence are held
        over for the next call.  When *chunk* is empty the return
        value is an empty string.
        """
        if not chunk:
            return ""
        self._buffer.extend(chunk)
        cut_index = _utf8_continuation_start(bytes(self._buffer))
        decodable = bytes(self._buffer[:cut_index])
        del self._buffer[:cut_index]
        return decodable.decode("utf-8", errors="replace")

    def flush(self) -> str:
        """Return any buffered bytes, decoded with error replacement.

        Call at end-of-stream so a final incomplete sequence produces
        a :data:`~str` with the replacement character rather than
        silently dropping bytes.
        """
        if not self._buffer:
            return ""
        leftover = bytes(self._buffer)
        self._buffer.clear()
        return leftover.decode("utf-8", errors="replace")

    def pending(self) -> bytes:
        """Return the lead bytes held back awaiting their continuation.

        These are the start of an incomplete trailing code point the
        decoder has not emitted yet.  Returns a copy without consuming
        them, so a caller draining decoded text around a boundary can
        carry the partial sequence forward instead of dropping it; the
        buffer keeps holding the same bytes for the next :meth:`decode`.
        """
        return bytes(self._buffer)
