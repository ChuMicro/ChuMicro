"""Core implementation for chumicro-ntp.

Speaks SNTP, the subset of NTPv4 that answers "what time is it?" against
a standard NTP server. Wire format reference: RFC 4330 §4.
"""

import errno

try:
    from micropython import const
except ImportError:
    def const(value):
        return value


#: Seconds between the NTP epoch (1900-01-01T00:00:00Z) and the
#: Unix epoch (1970-01-01T00:00:00Z).
NTP_TO_UNIX = const(2208988800)

#: SNTP packet length in bytes (fixed by the protocol at 48).
PACKET_SIZE = const(48)

#: First byte of an SNTP **request**: LI=0 (no warning), VN=4
#: (NTPv4), Mode=3 (client).
CLIENT_FIRST_BYTE = const(0x23)

#: SNTP mode value for a server response (low three bits of byte 0).
SERVER_MODE = const(4)

# The complete 48-byte SNTP client request, reused for every query.
_CLIENT_REQUEST = bytes([CLIENT_FIRST_BYTE]) + b"\x00" * (PACKET_SIZE - 1)

# Errnos meaning "no datagram ready yet", not a failed exchange. Every
# runtime defines EAGAIN; only some (e.g. CPython) also define EWOULDBLOCK.
_WOULD_BLOCK_ERRNOS = (errno.EAGAIN,)
if hasattr(errno, "EWOULDBLOCK"):
    _WOULD_BLOCK_ERRNOS = (errno.EAGAIN, errno.EWOULDBLOCK)


class NTPError(OSError):
    """SNTP exchange failed."""

    # Subclasses OSError so `except OSError` (the usual transport-error
    # pattern) catches it, while `except NTPError` still isolates NTP.


def _parse_response(packet: bytes | memoryview) -> int:
    """Parse an SNTP server response into Unix-epoch seconds."""
    if len(packet) < PACKET_SIZE:
        raise NTPError(f"short SNTP response ({len(packet)} bytes)")
    # Match the mode (low three bits) only; some servers echo VN != 4.
    mode = packet[0] & 0b111
    if mode != SERVER_MODE:
        raise NTPError(f"unexpected SNTP mode {mode} (want {SERVER_MODE})")
    stratum = packet[1]
    if stratum == 0:
        # RFC 4330 §5: stratum=0 is a "kiss-of-death"; the timestamp is
        # not trustworthy, so raise and let the caller back off.
        raise NTPError("SNTP kiss-of-death (stratum=0)")
    # Transmit timestamp is bytes 40-47: high 32 bits are seconds since
    # 1900-01-01, low 32 bits are fractional seconds (discarded).
    seconds_1900 = (
        (packet[40] << 24)
        | (packet[41] << 16)
        | (packet[42] << 8)
        | packet[43]
    )
    if seconds_1900 == 0:
        # RFC 4330 §5: a zero transmit timestamp is invalid. Reject it
        # before the era lift below, which would turn it into a bogus 2036.
        raise NTPError("SNTP zero transmit timestamp")
    # NTP era 0 ends 2036 when the 32-bit field wraps. A value below the
    # 1900->1970 offset is era 1, so lift it by 2**32 (holds until ~2106).
    if seconds_1900 < NTP_TO_UNIX:
        seconds_1900 += 0x100000000
    return seconds_1900 - NTP_TO_UNIX


class NTPResult:
    """Handle for a single in-flight SNTP exchange.

    Poll :attr:`done` each tick; once ``True``, read :attr:`unix_seconds`
    for the timestamp or :attr:`error` for the failure that ended it.

    Args:
        ticks_started_ms: Tick value when the request was issued, used to
            detect timeouts.
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
            Exception: Re-raises the stored :attr:`error` when the exchange
                failed (an :class:`NTPError` for a protocol, timeout, or
                cancellation failure, or the raw ``OSError`` from send/recv).
            RuntimeError: The exchange has not finished yet.
        """
        if not self.done:
            raise RuntimeError("NTP request still in flight")
        if self.error is not None:
            raise self.error
        return self._unix_seconds  # type: ignore[return-value]

    def _fail(self, exception: Exception) -> None:
        self.error = exception
        self.done = True


class NTPClient:
    """Runner-shaped SNTP client over an injected UDP socket.

    Handles one query at a time: calling :meth:`query` while :attr:`busy`
    raises ``RuntimeError``. The client does not own the socket; the
    caller creates and closes it. See :meth:`from_config` to build one
    from ``runtime_config.msgpack``.

    Args:
        socket: A non-blocking UDP-shaped object exposing
            ``sendto(payload, host, port)``, ``recvfrom_into(buffer)``,
            ``close()``, and ``setblocking(flag)``. ``sendto`` and
            ``recvfrom_into`` raise ``OSError(EAGAIN | EWOULDBLOCK)`` when
            the buffer is full or empty. :func:`chumicro_sockets.udp_socket`
            produces one; tests inject
            :class:`chumicro_sockets.testing.FakeUDPSocket`. A raw stdlib
            ``socket.socket(SOCK_DGRAM)`` does not fit, since its
            ``sendto`` takes ``(data, address)`` not ``(data, host, port)``.
        server: NTP server hostname. Defaults to ``"pool.ntp.org"``.
        port: NTP server UDP port. Defaults to ``123``.
        timeout_ms: Tick budget for the recv side of the exchange.
            Defaults to ``5000``.
        ticks: Optional tick source exposing ``ticks_ms``, ``ticks_diff``,
            and ``ticks_add`` (the ``chumicro_timing.ticks`` shape).
            Defaults to the real clock; tests pass ``FakeTicks``.

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
        transport_factory: object | None = None,
    ) -> "NTPClient":
        """Build an :class:`NTPClient` from runtime config.

        Reads optional ``ntp.server`` / ``ntp.port`` / ``ntp.timeout_ms``,
        falling back to ``pool.ntp.org`` on port 123 when absent (an empty
        ``config`` is valid). Passing *socket* or *transport_factory*
        overrides the auto-built UDP factory.
        """
        if socket is None and transport_factory is None:
            try:
                from chumicro_ntp.sockets_factory import (  # noqa: PLC0415
                    chumicro_sockets_factory,
                )
            except ImportError as exception:
                raise RuntimeError(
                    "chumicro_ntp.sockets_factory not available "
                    "(excluded via __chumicro_skip_factories__ or "
                    "not on the board), pass socket= or "
                    "transport_factory= explicitly.",
                ) from exception

            def transport_factory():
                # Deferred: the UDP socket opens on the first query(), not
                # at construction, so building a client is free.
                udp_socket = chumicro_sockets_factory(radio=radio)
                # Runner-shaped clients require non-blocking recv.
                udp_socket.setblocking(False)
                return udp_socket

        return cls(
            socket=socket,
            transport_factory=transport_factory,
            server=config.get("ntp.server", "pool.ntp.org"),
            port=config.get("ntp.port", 123),
            timeout_ms=config.get("ntp.timeout_ms", 5_000),
        )

    def __init__(
        self,
        socket: object | None = None,
        *,
        transport_factory: object | None = None,
        server: str = "pool.ntp.org",
        port: int = 123,
        timeout_ms: int = 5_000,
        ticks: object | None = None,
    ) -> None:
        if timeout_ms <= 0:
            raise ValueError("timeout_ms must be positive")
        if (socket is None) == (transport_factory is None):
            raise ValueError(
                "provide exactly one of socket= or transport_factory= "
                "(the factory defers the UDP open to the first query)"
            )
        self.socket = socket
        self._transport_factory = transport_factory
        self.server = server
        self.port = port
        self.timeout_ms = timeout_ms
        if ticks is None:
            from chumicro_timing import ticks  # noqa: PLC0415 - DI fallback
        self._ticks = ticks
        self._result: NTPResult | None = None
        # Pre-allocate the receive buffer so the hot path never allocates.
        self._recv_buffer = bytearray(PACKET_SIZE)

    @property
    def busy(self) -> bool:
        """``True`` between :meth:`query` and result completion."""
        return self._result is not None and not self._result.done

    def query(self) -> NTPResult:
        """Issue a single SNTP query.

        Opens the UDP socket on first use when built with
        *transport_factory*, sends the 48-byte request, then arms the
        recv path that ``check`` / ``handle`` drain on later ticks. A
        synchronous ``sendto`` failure is not raised: it is delivered on
        the returned result (already ``done`` with ``error`` set).

        Returns:
            An :class:`NTPResult` the caller polls.

        Raises:
            RuntimeError: A query is already in flight (``busy``).
        """
        if self.busy:
            raise RuntimeError(
                "NTP query already in flight; await result before re-querying",
            )
        if self.socket is None:
            self.socket = self._transport_factory()
        # Discard datagrams buffered from a previous (timed-out or
        # cancelled) exchange, so a stale reply isn't mistaken for this one.
        self._drain_socket()
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

    def _drain_socket(self) -> None:
        while True:
            try:
                received_count, _sender = self.socket.recvfrom_into(
                    self._recv_buffer,
                )
            except OSError:
                return  # would-block / no more data buffered
            if received_count == 0:
                return

    def check(self, now_ms: int) -> bool:
        """Return ``True`` when the runner should call :meth:`handle`.

        Args:
            now_ms: Current tick value (unused; required by the runner).
        """
        return self.busy

    def handle(self, now_ms: int) -> None:
        """Drain one tick of work for the in-flight query.

        Tries to receive a response; on no data, checks the timeout.
        Either way marks the result ``done`` once the exchange ends.

        Args:
            now_ms: Current tick value, used for timeout detection.
        """
        result = self._result
        if result is None or result.done:
            return
        try:
            received_count, _sender = self.socket.recvfrom_into(
                self._recv_buffer,
            )
        except OSError as recv_error:
            if recv_error.errno in _WOULD_BLOCK_ERRNOS:
                # No data this tick; check the timeout instead.
                self._check_timeout(result, now_ms)
                return
            # Any other socket error fails the exchange.
            result._fail(recv_error)
            return
        if received_count == 0:
            # No data and no error: still waiting.
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
