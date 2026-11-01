"""``NTPClient`` sends SNTP requests over UDP and parses each reply into Unix seconds."""

import errno
import struct

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

# Max stale datagrams query() discards before sending.  The cap keeps a flooded socket from spinning.
_DRAIN_LIMIT = const(8)

# How often next_deadline asks for a turn while a reply is outstanding.
_REPLY_POLL_MS = const(20)

_CLIENT_REQUEST = bytes([CLIENT_FIRST_BYTE]) + b"\x00" * (PACKET_SIZE - 1)

# Only some runtimes (e.g. CPython) also define EWOULDBLOCK.
_WOULD_BLOCK_ERRNOS = (errno.EAGAIN,)
if hasattr(errno, "EWOULDBLOCK"):
    _WOULD_BLOCK_ERRNOS = (errno.EAGAIN, errno.EWOULDBLOCK)


class NTPError(OSError):
    """Error stored in ``NTPResult.error`` when a query times out, is canceled, or gets a bad reply.

    ``NTPError`` subclasses ``OSError``, so ``except OSError`` also catches
    the socket errors a failed send or receive stores in the same place.
    """


def _parse_response(packet: bytes | memoryview) -> int:
    if len(packet) < PACKET_SIZE:
        raise NTPError(f"short SNTP response ({len(packet)} bytes)")
    # Check only the mode (low 3 bits).  Some servers reply with a version other than 4.
    mode = packet[0] & 0b111
    if mode != SERVER_MODE:
        raise NTPError(f"unexpected SNTP mode {mode} (want {SERVER_MODE})")
    stratum = packet[1]
    if stratum == 0:
        # RFC 4330 §5: stratum 0 is a kiss-of-death, not a usable time.
        raise NTPError("SNTP kiss-of-death (stratum=0)")
    # Transmit timestamp: bytes 40-43 hold whole seconds since 1900.  The fraction in 44-47 is dropped.
    seconds_1900 = struct.unpack_from(">I", packet, 40)[0]
    if seconds_1900 == 0:
        # RFC 4330 §5: reject a zero timestamp before the era lift makes it 2036.
        raise NTPError("SNTP zero transmit timestamp")
    # A count below the epoch offset belongs to NTP era 1 (after 2036), so add 2**32.
    if seconds_1900 < NTP_TO_UNIX:
        seconds_1900 += 0x100000000
    return seconds_1900 - NTP_TO_UNIX


class NTPResult:
    """One SNTP query, returned by ``NTPClient.query()`` before the reply arrives.

    ``done`` turns ``True`` when the query finishes.  A finished query holds
    either the time in ``unix_seconds`` or the cause of failure in ``error``.

    Args:
        ticks_started_ms: ``ticks_ms()`` reading when the request went out.
            ``NTPClient`` measures ``timeout_ms`` from it.

    Attributes:
        done: ``True`` once the query has a time or an error.
        error: ``None`` until the query fails, then the exception that ended
            it.  A timeout, ``NTPClient.cancel()``, or a malformed reply
            stores an ``NTPError``.  A failed send or receive stores the
            socket's ``OSError``.
    """

    def __init__(self, ticks_started_ms: int) -> None:
        self._ticks_started_ms = ticks_started_ms
        self.done = False
        self._unix_seconds: int | None = None
        self.error: Exception | None = None

    @property
    def unix_seconds(self) -> int:
        """Server's clock at the moment it sent the reply, in whole seconds since 1 January 1970 UTC.

        Read it once ``done`` is ``True`` and ``error`` is ``None``.  The
        fraction of a second in the reply is dropped.

        Raises:
            RuntimeError: The query has not finished.
            OSError: The query failed.  The stored ``error`` is raised again.
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
    """Asks a time server for the current time, one non-blocking step per pass of the main loop.

    ``query()`` sends the request and returns an ``NTPResult`` at once.  On
    each pass of the loop, ``check(now_ms)`` returns ``True`` while the reply
    is pending.  ``handle(now_ms)`` then reads the reply once it arrives.
    ``now_ms`` is the millisecond count from ``chumicro_timing.ticks_ms()``.
    A ``chumicro_runner.Runner`` makes both calls itself after
    ``runner.add(client)``.  One query runs at a time.

    Args:
        socket: Non-blocking UDP socket with ``sendto(payload, host, port)``,
            ``recvfrom_into(buffer)``, and ``close()``.  Pass ``socket`` or
            ``transport_factory``, never both.
        transport_factory: Zero-argument callable that returns such a socket.
            The client calls it at the first ``query()`` and at the first
            ``query()`` after each ``close()``.
        server: Host name or IP address of the time server.
        port: UDP port of the time server.
        timeout_ms: Milliseconds from ``query()`` until ``handle()`` fails
            the query with ``NTPError``.
        ticks: Clock object with ``ticks_ms()``, ``ticks_add()``, and
            ``ticks_diff()``.  ``None`` selects ``chumicro_timing.ticks``.

    Raises:
        ValueError: ``timeout_ms`` is zero or negative, or the call passed
            both or neither of ``socket`` and ``transport_factory``.
    """

    @classmethod
    def from_config(
        cls,
        config: object,
        *,
        radio: object | None = None,
        socket: object | None = None,
        transport_factory: object | None = None,
        ticks: object | None = None,
        **constructor_kwargs: object,
    ) -> "NTPClient":
        """Build a client from a flat config mapping, with a UDP socket that opens at the first query.

        With neither ``socket`` nor ``transport_factory`` given, the client
        opens its socket through ``chumicro_sockets.sockets_factory`` and
        reopens it after ``close()``.

        Args:
            config: A ``dict`` or other mapping with ``get()``.  The client
                reads ``ntp.server`` (default ``"pool.ntp.org"``),
                ``ntp.port`` (default ``123``), and ``ntp.timeout_ms``
                (default ``5000``).
            radio: The CircuitPython radio, such as ``wifi.radio``, for the
                default socket.  MicroPython and CPython ignore it.
            socket: Ready UDP socket to use instead of the default one.
            transport_factory: Zero-argument callable that returns a UDP
                socket, used instead of the default one.
            ticks: Clock object, passed to the constructor.
            **constructor_kwargs: Any other constructor argument.  A keyword
                given here wins over the config value.

        Returns:
            A new ``NTPClient`` with no query in flight.

        Raises:
            RuntimeError: Neither ``socket`` nor ``transport_factory`` was
                given, and ``chumicro_sockets.sockets_factory`` is missing
                from the board.
        """
        if socket is None and transport_factory is None:
            try:
                from chumicro_sockets.sockets_factory import (  # noqa: PLC0415 - lazy: keeps chumicro_sockets off BYO-transport deploys
                    udp_socket_factory,
                )
            except ImportError as exception:
                raise RuntimeError(
                    "chumicro_sockets.sockets_factory not available "
                    "(excluded via __chumicro_skip_factories__ or "
                    "not on the board); pass transport_factory= or "
                    "socket= explicitly.",
                ) from exception

            transport_factory = udp_socket_factory(radio=radio)

        kwargs = {
            "socket": socket,
            "transport_factory": transport_factory,
            "server": config.get("ntp.server", "pool.ntp.org"),
            "port": config.get("ntp.port", 123),
            "timeout_ms": config.get("ntp.timeout_ms", 5_000),
            "ticks": ticks,
        }
        kwargs.update(constructor_kwargs)
        return cls(**kwargs)

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
        self._recv_view = memoryview(self._recv_buffer)

    @property
    def busy(self) -> bool:
        """``True`` from ``query()`` until that query's ``NTPResult`` is done."""
        return self._result is not None and not self._result.done

    def query(self) -> NTPResult:
        """Send one SNTP request and return its ``NTPResult`` without waiting for the reply.

        ``handle()`` fills in the result on a later pass of the loop.  The
        client first throws away any late replies to an earlier query.  With
        the default socket, a host name in ``server`` costs a DNS lookup
        inside this call that blocks until the resolver answers.
        A failed send comes back as a result that is already done, with the
        socket's ``OSError`` in ``error``.

        Returns:
            The ``NTPResult`` for this query.

        Raises:
            RuntimeError: A query is already in flight (``busy`` is
                ``True``), or ``close()`` ran on a client built with
                ``socket=``.
        """
        if self.busy:
            raise RuntimeError(
                "NTP query already in flight; await result before re-querying",
            )
        if self.socket is None:
            if self._transport_factory is None:
                raise RuntimeError(
                    "socket closed; pass transport_factory= to reopen on demand",
                )
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
        for _ in range(_DRAIN_LIMIT):
            try:
                received_count, _sender = self.socket.recvfrom_into(
                    self._recv_buffer,
                )
            except OSError:
                return
            if received_count == 0:
                return

    def check(self, now_ms: int) -> bool:
        """Return ``True`` when ``handle()`` has work to do: a query waits for its reply.

        Args:
            now_ms: Current ``ticks_ms()`` reading.  The client ignores it and
                accepts it to match the runner's calling convention.
        """
        return self.busy

    def next_deadline(self, now_ms: int) -> int | None:
        """Return the ``ticks_ms()`` value by which ``handle()`` must run next, or ``None`` when idle.

        ``Runner.wait()`` sleeps no later than the earliest deadline its
        services report.  While a reply is pending, the client asks for a
        turn 20 ms after ``now_ms``.  ``handle()`` checks the socket on that
        turn.

        Args:
            now_ms: Current ``ticks_ms()`` reading.
        """
        if self.busy:
            return self._ticks.ticks_add(now_ms, _REPLY_POLL_MS)
        return None

    def handle(self, now_ms: int) -> None:
        """Read the reply to the query in flight if it has arrived, and finish the query.

        A valid reply sets ``unix_seconds`` on the result.  A malformed reply,
        a socket error, or ``timeout_ms`` passing with no reply sets
        ``error``.  Either way the result's ``done`` turns ``True``.  Each
        call reads at most one datagram and returns at once when none has
        arrived.

        Args:
            now_ms: Current ``ticks_ms()`` reading, compared against the time
                the query went out.
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
                self._recv_view[:received_count],
            )
        except NTPError as parse_error:
            result._fail(parse_error)
            return
        result._unix_seconds = unix_seconds  # noqa: SLF001 - own result type
        result.done = True

    def _check_timeout(self, result: "NTPResult", now_ms: int) -> None:
        elapsed_ms = self._ticks.ticks_diff(now_ms, result._ticks_started_ms)  # noqa: SLF001 - own result type
        if elapsed_ms >= self.timeout_ms:
            result._fail(
                NTPError(f"SNTP query timed out after {elapsed_ms} ms"),
            )

    def cancel(self) -> bool:
        """End the query in flight with ``NTPError("canceled")`` and free the client for the next one.

        Returns:
            ``True`` when a query was in flight, ``False`` when the client
                was idle.
        """
        if not self.busy:
            return False
        self._result._fail(NTPError("canceled"))
        return True

    def close(self) -> None:
        """Close the UDP socket.

        A client built with ``transport_factory`` opens a fresh socket at the
        next ``query()``.  A client built with ``socket=`` has no way to open
        another, so its next ``query()`` raises ``RuntimeError``.
        """
        if self.socket is None:
            return
        try:
            self.socket.close()
        except OSError:
            pass
        self.socket = None
