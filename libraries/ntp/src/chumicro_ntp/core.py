"""Core implementation for chumicro-ntp."""

import errno

try:
    from micropython import const
except ImportError:
    def const(value):
        return value


# Seconds from the NTP epoch (1900) to the Unix epoch (1970).
NTP_TO_UNIX = const(2208988800)

PACKET_SIZE = const(48)

# SNTP request byte 0: LI=0, VN=4 (NTPv4), Mode=3 (client).
CLIENT_FIRST_BYTE = const(0x23)

SERVER_MODE = const(4)

_CLIENT_REQUEST = bytes([CLIENT_FIRST_BYTE]) + b"\x00" * (PACKET_SIZE - 1)

# Only some runtimes (e.g. CPython) also define EWOULDBLOCK.
_WOULD_BLOCK_ERRNOS = (errno.EAGAIN,)
if hasattr(errno, "EWOULDBLOCK"):
    _WOULD_BLOCK_ERRNOS = (errno.EAGAIN, errno.EWOULDBLOCK)


class NTPError(OSError):
    """SNTP exchange failed."""


def _parse_response(packet: bytes | memoryview) -> int:
    if len(packet) < PACKET_SIZE:
        raise NTPError(f"short SNTP response ({len(packet)} bytes)")
    # Match mode (low 3 bits) only; some servers echo VN != 4.
    mode = packet[0] & 0b111
    if mode != SERVER_MODE:
        raise NTPError(f"unexpected SNTP mode {mode} (want {SERVER_MODE})")
    stratum = packet[1]
    if stratum == 0:
        # RFC 4330 §5: stratum 0 is a kiss-of-death, not a usable time.
        raise NTPError("SNTP kiss-of-death (stratum=0)")
    # Transmit timestamp: bytes 40-43 are seconds since 1900; 44-47 fraction, discarded.
    seconds_1900 = (
        (packet[40] << 24)
        | (packet[41] << 16)
        | (packet[42] << 8)
        | packet[43]
    )
    if seconds_1900 == 0:
        # RFC 4330 §5: reject a zero timestamp before the era lift makes it 2036.
        raise NTPError("SNTP zero transmit timestamp")
    # Below the epoch offset means NTP era 1 (post-2036); lift by 2**32.
    if seconds_1900 < NTP_TO_UNIX:
        seconds_1900 += 0x100000000
    return seconds_1900 - NTP_TO_UNIX


class NTPResult:
    """Handle for a single in-flight SNTP exchange.

    Args:
        ticks_started_ms: Tick value when the request was issued.
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
            Exception: Re-raises the stored :attr:`error` when the exchange failed.
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

    Args:
        socket: Non-blocking UDP object with sendto/recvfrom_into/close/setblocking.
        server: NTP server hostname. Defaults to ``"pool.ntp.org"``.
        port: NTP server UDP port. Defaults to ``123``.
        timeout_ms: Tick budget for the recv side. Defaults to ``5000``.
        ticks: Optional tick source (``chumicro_timing.ticks`` shape); defaults to the real clock.

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
        """Build an :class:`NTPClient` from runtime config."""
        if socket is None and transport_factory is None:
            try:
                from chumicro_sockets.sockets_factory import (  # noqa: PLC0415
                    udp_socket_factory,
                )
            except ImportError as exception:
                raise RuntimeError(
                    "chumicro_sockets.sockets_factory not available "
                    "(excluded via __chumicro_skip_factories__ or "
                    "not on the board), pass socket= or "
                    "transport_factory= explicitly.",
                ) from exception

            base_factory = udp_socket_factory(radio=radio)

            def transport_factory():
                udp_socket = base_factory()
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
        self._recv_buffer = bytearray(PACKET_SIZE)

    @property
    def busy(self) -> bool:
        """``True`` between :meth:`query` and result completion."""
        return self._result is not None and not self._result.done

    def query(self) -> NTPResult:
        """Issue a single SNTP query.

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
        # Discard stale datagrams from a previous timed-out or cancelled query.
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
                return
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
                self._check_timeout(result, now_ms)
                return
            result._fail(recv_error)
            return
        if received_count == 0:
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
        elapsed_ms = self._ticks.ticks_diff(now_ms, result._ticks_started_ms)  # noqa: SLF001
        if elapsed_ms >= self.timeout_ms:
            result._fail(
                NTPError(f"SNTP query timed out after {elapsed_ms} ms"),
            )

    def cancel(self) -> bool:
        """Abort an in-flight query.

        Returns:
            ``True`` if a query was in flight, ``False`` if the client was idle.
        """
        if not self.busy:
            return False
        self._result._fail(NTPError("canceled"))
        return True
