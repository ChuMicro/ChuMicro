"""Core implementation for chumicro-ntp.

See ``__init__`` for the public API summary.  This module is pure-Python
and identical on every supported runtime.

The client speaks **SNTP** — a strict subset of NTPv4 sufficient for
"what time is it?" queries against any standard NTP server.  Stratum,
dispersion, and round-trip-delay are not modeled; clients that want
them should use a full NTP implementation (out of scope for embedded).

Wire format reference: RFC 4330 §4.
"""

try:
    from micropython import const
except ImportError:
    def const(value):
        return value

def _is_eagain(error):
    return getattr(error, "errno", None) in (11, 35)


#: Seconds between the NTP epoch (1900-01-01T00:00:00Z) and the
#: Unix epoch (1970-01-01T00:00:00Z).  Constant since both epochs
#: are fixed.
NTP_TO_UNIX = const(2208988800)

#: SNTP packet length in bytes.  Fixed by the protocol — every
#: request and every response is exactly 48 bytes.
PACKET_SIZE = const(48)

#: First byte of an SNTP **request**: LI=0 (no warning), VN=4
#: (NTPv4), Mode=3 (client).
CLIENT_FIRST_BYTE = const(0x23)

#: First byte of an SNTP **response** has Mode=4 (server) in the
#: low three bits.  Tests check the mode rather than the whole
#: byte because some servers echo VN!=4.
SERVER_MODE = const(4)

#: The complete 48-byte SNTP client request — first byte is
#: ``CLIENT_FIRST_BYTE`` (LI=0, VN=4, Mode=3), the rest zero.
#: Identical for every query, so we send the same object instead of
#: rebuilding a fresh packet each call.
_CLIENT_REQUEST = bytes([CLIENT_FIRST_BYTE]) + b"\x00" * (PACKET_SIZE - 1)


class NTPError(OSError):
    """SNTP exchange failed.

    Subclasses ``OSError`` so callers that catch ``except OSError``
    (the typical pattern for transport-layer errors) catch it
    automatically.  Distinct subclass so callers who care about NTP
    specifics can ``except NTPError``.
    """


def _parse_response(packet: bytes | memoryview) -> int:
    """Parse an SNTP server response into Unix-epoch seconds.

    Args:
        packet: The bytes returned by ``recvfrom_into``.  Must be
            exactly :data:`PACKET_SIZE` bytes long.

    Returns:
        Integer Unix-epoch seconds (UTC) read from the server's
        transmit-timestamp field.  Sub-second fractional bits are
        discarded — embedded uses overwhelmingly want second
        granularity.

    Raises:
        NTPError: Packet too short, mode not "server", or stratum
            kiss-of-death (stratum=0).
    """
    if len(packet) < PACKET_SIZE:
        raise NTPError(f"short SNTP response ({len(packet)} bytes)")
    mode = packet[0] & 0b111
    if mode != SERVER_MODE:
        raise NTPError(f"unexpected SNTP mode {mode} (want {SERVER_MODE})")
    stratum = packet[1]
    if stratum == 0:
        # RFC 4330 §5: stratum=0 is a "kiss-of-death" — don't trust
        # the timestamp, raise so caller can back off.
        raise NTPError("SNTP kiss-of-death (stratum=0)")
    # Transmit timestamp lives at bytes 40-47.  The high 32 bits are
    # seconds since 1900-01-01; the low 32 bits are 2^-32 fractional
    # seconds (we discard them).
    seconds_1900 = (
        (packet[40] << 24)
        | (packet[41] << 16)
        | (packet[42] << 8)
        | packet[43]
    )
    # NTP era 0 ends 2036-02-07 when the 32-bit field wraps.  A value
    # below the 1900->1970 offset must be era 1; lift it by 2**32.
    # Heuristic holds until ~2106, then the hard upper bound.
    if seconds_1900 < NTP_TO_UNIX:
        seconds_1900 += 0x100000000
    return seconds_1900 - NTP_TO_UNIX


class NTPResult:
    """Handle for a single in-flight SNTP exchange.

    Yielded by :meth:`NTPClient.query`.  Callers poll :attr:`done`
    each tick; when ``True`` they read :attr:`unix_seconds` for the
    timestamp or :attr:`error` for the exception that ended the
    exchange.

    Args:
        ticks_started_ms: The tick value at which the request was
            issued.  Used by the client to detect timeouts.
    """

    def __init__(self, ticks_started_ms: int) -> None:
        self._ticks_started_ms = ticks_started_ms
        self.done = False
        self._unix_seconds: int | None = None
        self.error: Exception | None = None

    @property
    def unix_seconds(self) -> int:
        """Server's transmit timestamp converted to Unix-epoch seconds.

        Raises:
            NTPError: The exchange ended in failure — read
                :attr:`error` for the underlying exception.
            RuntimeError: The exchange has not finished yet.
        """
        if not self.done:
            raise RuntimeError("NTP request still in flight")
        if self.error is not None:
            raise self.error
        return self._unix_seconds  # type: ignore[return-value]

    def _fail(self, exception: Exception) -> None:
        """Mark the request done with an error."""
        self.error = exception
        self.done = True


class NTPClient:
    """Runner-shaped SNTP client over an injected UDP socket.

    Single in-flight request at a time — calling :meth:`query` while
    :attr:`busy` is ``True`` raises ``RuntimeError`` (mirrors
    ``HttpClient.busy``).  Apps wanting parallel queries instantiate
    multiple clients on distinct sockets.

    The socket is **not owned** by the client — caller passes it in
    and is responsible for closing it.  The ``sockets_factory``
    submodule provides a one-line default wiring against
    ``chumicro-sockets``.

    For config-driven construction, see :meth:`from_config` —
    one-line factory that reads server / port / timeout from
    ``runtime_config.msgpack`` with sensible fall-back defaults.

    Args:
        socket: A non-blocking UDP-shaped object.  Must expose:

            * ``sendto(payload: bytes, address) -> int`` — sends the
              packet to *address* (a ``(host, port)`` tuple).
              Raises ``OSError(EAGAIN | EWOULDBLOCK)`` when the send
              buffer is full.
            * ``recvfrom_into(buffer) -> (nbytes, address)`` — reads
              into *buffer*, returning the byte count and sender.
              Raises ``OSError(EAGAIN | EWOULDBLOCK)`` on no data.
            * ``close() -> None``
            * ``setblocking(flag: bool) -> None`` — best-effort;
              absence is tolerated.

            :func:`chumicro_sockets.udp_socket` is one valid
            producer; stdlib ``socket.socket(SOCK_DGRAM)`` after
            ``setblocking(False)`` is another.  Tests inject
            :class:`chumicro_sockets.testing.FakeUDPSocket`.
        server: NTP server hostname.  Defaults to ``"pool.ntp.org"``.
            Resolution is delegated to the runtime's name resolver.
        port: NTP server UDP port.  Defaults to ``123``.
        timeout_ms: Maximum tick budget for the recv side of the
            exchange.  Defaults to ``5000``.
        ticks: Optional tick source — any object exposing
            ``ticks_ms``, ``ticks_diff``, ``ticks_add`` (matches the
            ``chumicro_timing.ticks`` submodule shape).  Defaults to
            that submodule (real clock); tests pass ``FakeTicks``
            from ``chumicro_timing.testing``.

    Raises:
        ValueError: ``timeout_ms`` is non-positive.
    """

    @classmethod
    def from_config(
        cls,
        config: object,
        *,
        radio: object | None = None,
        socket: object | None = None,
        socket_factory: object | None = None,
    ) -> "NTPClient":
        """Build an :class:`NTPClient` from runtime config.

        Reads optional ``ntp.server`` / ``ntp.port`` / ``ntp.timeout_ms``
        — empty ``config`` is valid input (defaults to ``pool.ntp.org``
        on port 123).  A *socket* or *socket_factory* override bypasses
        the auto-built UDP factory; the auto path sets the socket
        non-blocking before passing it to the client.
        """
        if socket is None:
            if socket_factory is None:
                try:
                    from chumicro_ntp.sockets_factory import (  # noqa: PLC0415
                        chumicro_sockets_factory,
                    )
                except ImportError as exception:
                    raise RuntimeError(
                        "chumicro_ntp.sockets_factory not available "
                        "(excluded via __chumicro_skip_factories__ or "
                        "not on the board) — pass socket= or "
                        "socket_factory= explicitly.",
                    ) from exception

                socket = chumicro_sockets_factory(radio=radio)
                # Runner-shaped clients require non-blocking recv.  Guarded so
                # test fakes without setblocking() still work.
                if hasattr(socket, "setblocking"):
                    socket.setblocking(False)
            else:
                socket = socket_factory()
        return cls(
            socket=socket,
            server=config.get("ntp.server", "pool.ntp.org"),
            port=config.get("ntp.port", 123),
            timeout_ms=config.get("ntp.timeout_ms", 5_000),
        )

    def __init__(
        self,
        socket: object,
        *,
        server: str = "pool.ntp.org",
        port: int = 123,
        timeout_ms: int = 5_000,
        ticks: object | None = None,
    ) -> None:
        if timeout_ms <= 0:
            raise ValueError("timeout_ms must be positive")
        self.socket = socket
        self.server = server
        self.port = port
        self.timeout_ms = timeout_ms
        if ticks is None:
            from chumicro_timing import ticks  # noqa: PLC0415 - DI fallback
        self._ticks = ticks
        self._result: NTPResult | None = None
        # Pre-allocate the receive buffer so the hot path doesn't
        # allocate.  48 bytes is the SNTP packet size; larger buffers
        # would just hold tail bytes nobody wants.
        self._recv_buffer = bytearray(PACKET_SIZE)

    @property
    def busy(self) -> bool:
        """``True`` between :meth:`query` and result completion."""
        return self._result is not None and not self._result.done

    def query(self) -> NTPResult:
        """Issue a single SNTP query.

        Sends the 48-byte client request immediately, then arms the
        runner-shaped recv path.  Subsequent ticks of
        ``check`` / ``handle`` drain the response from the socket.

        Returns:
            An :class:`NTPResult` the caller polls.

        Raises:
            RuntimeError: A query is already in flight (``busy``).
            OSError: The synchronous ``sendto`` call failed.
        """
        if self.busy:
            raise RuntimeError(
                "NTP query already in flight; await result before re-querying",
            )
        now_ms = self._ticks.ticks_ms()
        result = NTPResult(ticks_started_ms=now_ms)
        try:
            self.socket.sendto(_CLIENT_REQUEST, self.server, self.port)
        except OSError as send_error:
            result._fail(send_error)
            self._result = result
            return result
        self._result = result
        return result

    def check(self, now_ms: int) -> bool:
        """Return ``True`` when the runner should call :meth:`handle`.

        ``True`` while a query is in flight — covers both the
        recv-side polling and timeout detection.

        Args:
            now_ms: Current tick value (unused; required by runner).
        """
        return self.busy

    def handle(self, now_ms: int) -> None:
        """Drain one tick of work for the in-flight query.

        Tries to receive an SNTP response; if the socket has no data
        ready, checks whether the timeout has elapsed.  Either way,
        marks the result ``done`` once the exchange terminates.

        Args:
            now_ms: Current tick value used for timeout detection.
        """
        result = self._result
        if result is None or result.done:
            return
        try:
            received_count, _sender = self.socket.recvfrom_into(
                self._recv_buffer,
            )
        except OSError as recv_error:
            if _is_eagain(recv_error):
                # No data this tick.  Check the timeout instead.
                self._check_timeout(result, now_ms)
                return
            # Any other socket error — fail the exchange.
            result._fail(recv_error)
            return
        if received_count == 0:
            # No data and no error — treat as "still waiting".
            self._check_timeout(result, now_ms)
            return
        try:
            unix_seconds = _parse_response(
                memoryview(self._recv_buffer)[:received_count],
            )
        except NTPError as parse_error:
            result._fail(parse_error)
            return
        result._unix_seconds = unix_seconds  # noqa: SLF001
        result.done = True

    def _check_timeout(self, result: "NTPResult", now_ms: int) -> None:
        """Fail *result* with a timeout ``NTPError`` if the deadline has elapsed."""
        elapsed_ms = self._ticks.ticks_diff(now_ms, result._ticks_started_ms)  # noqa: SLF001
        if elapsed_ms >= self.timeout_ms:
            result._fail(
                NTPError(f"SNTP query timed out after {elapsed_ms} ms"),
            )

    def cancel(self) -> bool:
        """Abort an in-flight query.

        Returns:
            ``True`` if a query was in flight (now marked errored
            with ``NTPError("canceled")``); ``False`` if the client
            was idle.
        """
        if not self.busy:
            return False
        self._result._fail(NTPError("canceled"))
        return True
