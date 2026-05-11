"""Core implementation for chumicro-ntp.

See ``__init__`` for the public API summary.  This module is pure-Python
and identical on every supported runtime.

The client speaks **SNTP** — a strict subset of NTPv4 sufficient for
"what time is it?" queries against any standard NTP server.  Stratum,
dispersion, and round-trip-delay are not modelled; clients that want
them should use a full NTP implementation (out of scope for embedded).

Wire format reference: RFC 4330 §4.
"""

from chumicro_timing import ticks_diff
from chumicro_timing import ticks_ms as _module_ticks_ms

#: Seconds between the NTP epoch (1900-01-01T00:00:00Z) and the
#: Unix epoch (1970-01-01T00:00:00Z).  Constant since both epochs
#: are fixed.
_NTP_TO_UNIX = 2208988800

#: SNTP packet length in bytes.  Fixed by the protocol — every
#: request and every response is exactly 48 bytes.
_PACKET_SIZE = 48

#: First byte of an SNTP **request**: LI=0 (no warning), VN=4
#: (NTPv4), Mode=3 (client).
_CLIENT_FIRST_BYTE = 0x23

#: First byte of an SNTP **response** has Mode=4 (server) in the
#: low three bits.  Tests check the mode rather than the whole
#: byte because some servers echo VN!=4.
_SERVER_MODE = 4


class NTPError(OSError):
    """SNTP exchange failed.

    Subclasses ``OSError`` so callers that catch ``except OSError``
    (the typical pattern for transport-layer errors) catch it
    automatically.  Distinct subclass so callers who care about NTP
    specifics can ``except NTPError``.
    """


def _build_request() -> bytes:
    """Render an SNTP client request — 48 zero bytes with the first
    byte set to ``_CLIENT_FIRST_BYTE`` (LI=0, VN=4, Mode=3)."""
    packet = bytearray(_PACKET_SIZE)
    packet[0] = _CLIENT_FIRST_BYTE
    return bytes(packet)


def _parse_response(packet: bytes) -> int:
    """Parse an SNTP server response into Unix-epoch seconds.

    Args:
        packet: The bytes returned by ``recvfrom_into``.  Must be
            exactly :data:`_PACKET_SIZE` bytes long.

    Returns:
        Integer Unix-epoch seconds (UTC) read from the server's
        transmit-timestamp field.  Sub-second fractional bits are
        discarded — embedded uses overwhelmingly want second
        granularity.

    Raises:
        NTPError: Packet too short, mode not "server", or stratum
            kiss-of-death (stratum=0).
    """
    if len(packet) < _PACKET_SIZE:
        raise NTPError(f"short SNTP response ({len(packet)} bytes)")
    mode = packet[0] & 0b111
    if mode != _SERVER_MODE:
        raise NTPError(f"unexpected SNTP mode {mode} (want {_SERVER_MODE})")
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
    return seconds_1900 - _NTP_TO_UNIX


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
        self._done = False
        self._unix_seconds: int | None = None
        self._error: Exception | None = None

    @property
    def ticks_started_ms(self) -> int:
        """Tick value at which the request was issued."""
        return self._ticks_started_ms

    @property
    def done(self) -> bool:
        """``True`` once the exchange completes (success or failure)."""
        return self._done

    @property
    def unix_seconds(self) -> int:
        """Server's transmit timestamp converted to Unix-epoch seconds.

        Raises:
            NTPError: The exchange ended in failure — read
                :attr:`error` for the underlying exception.
            RuntimeError: The exchange has not finished yet.
        """
        if not self._done:
            raise RuntimeError("NTP request still in flight")
        if self._error is not None:
            raise self._error
        return self._unix_seconds  # type: ignore[return-value]

    @property
    def error(self) -> Exception | None:
        """The exception that ended the exchange, or ``None`` on success."""
        return self._error

    def _complete(self, unix_seconds: int) -> None:
        """Mark the request done with a successful timestamp."""
        self._unix_seconds = unix_seconds
        self._done = True

    def _fail(self, exception: Exception) -> None:
        """Mark the request done with an error."""
        self._error = exception
        self._done = True


def _build_default_socket_factory(*, radio=None):
    """Return a socket factory that opens a non-blocking UDP socket via
    ``chumicro_ntp.sockets_factory.chumicro_sockets_factory``.

    Used by :meth:`NTPClient.from_config` when the caller doesn't pass
    a pre-built socket or a custom factory.  Reads no config keys —
    the SNTP server hostname/port live on the ``NTPClient`` itself,
    not on the socket — so the factory never raises ``MissingConfigKey``.
    """
    def factory():
        from chumicro_ntp.sockets_factory import chumicro_sockets_factory  # noqa: PLC0415
        sock = chumicro_sockets_factory(radio=radio)
        # Runner-shaped clients require non-blocking recv.  Guarded so
        # test fakes without setblocking() still work.
        if hasattr(sock, "setblocking"):
            sock.setblocking(False)
        return sock

    return factory


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
        socket: Any UDP socket satisfying ``UDPSocket``.  In tests
            inject ``FakeUDPSocket`` from ``chumicro_sockets.testing``.
        server: NTP server hostname.  Defaults to ``"pool.ntp.org"``.
            Resolution is delegated to the runtime's name resolver.
        port: NTP server UDP port.  Defaults to ``123``.
        timeout_ms: Maximum tick budget for the recv side of the
            exchange.  Defaults to ``5000``.
        ticks_ms: Callable returning the current tick value.  Defaults
            to ``time.ticks_ms`` when available, ``time.monotonic *
            1000`` otherwise.

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

        Reads the ``[tool.chumicro.config]`` keys declared in
        ``libraries/ntp/pyproject.toml`` — **all optional** with
        sensible defaults:

        * ``ntp.server`` → ``"pool.ntp.org"`` (the public NTP pool
          maintained for unkeyed client use).
        * ``ntp.port`` → 123 (NTP standard).
        * ``ntp.timeout_ms`` → 5000.

        Unlike :meth:`chumicro_mqtt.MQTTClient.from_config`, which
        refuses to silently dial a third-party broker, this factory
        *does* fall back to the public NTP pool.  The pool is
        purpose-built for unkeyed clients with sensible-default
        behaviour; an MQTT broker is typically private infrastructure,
        so the asymmetry is deliberate.  No key in the ntp manifest
        is required, and the auto-built socket factory reads zero
        config keys, so an empty ``config`` dict is valid input.

        When *socket* or *socket_factory* is supplied, the caller
        owns the connection.  When neither is supplied, an auto-built
        factory creates a UDP socket via
        ``chumicro_ntp.sockets_factory.chumicro_sockets_factory(radio=radio)``
        and sets it non-blocking before passing it to the client.

        Args:
            config: A :class:`chumicro_config.RuntimeConfig` (typically
                ``chumicro_config.config``) or plain flat dict.  Keys
                read are flat dotted strings (``"ntp.server"``).
            radio: WiFi radio for the auto-built socket factory —
                CircuitPython needs this; MicroPython auto-detects.
                Ignored when *socket* or *socket_factory* is passed
                directly.
            socket: Pre-built UDP socket.  When supplied, the
                auto-built factory is skipped — caller owns the
                connection.
            socket_factory: Custom ``callable() -> UDPSocket``.  When
                supplied, called once during ``from_config`` to
                produce the socket.  Useful for custom socket options
                or non-default radio wiring.

        Returns:
            A configured ``NTPClient`` ready for ``query()``.
        """
        if socket is None and socket_factory is None:
            socket_factory = _build_default_socket_factory(radio=radio)
        if socket is None:
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
        ticks_ms: object | None = None,
    ) -> None:
        if timeout_ms <= 0:
            raise ValueError("timeout_ms must be positive")
        self._socket = socket
        self._server = server
        self._port = port
        self._timeout_ms = timeout_ms
        self._ticks_ms = ticks_ms if ticks_ms is not None else _module_ticks_ms
        self._result: NTPResult | None = None
        # Pre-allocate the receive buffer so the hot path doesn't
        # allocate.  48 bytes is the SNTP packet size; larger buffers
        # would just hold tail bytes nobody wants.
        self._recv_buffer = bytearray(_PACKET_SIZE)

    @property
    def server(self) -> str:
        """Configured NTP server hostname."""
        return self._server

    @property
    def port(self) -> int:
        """Configured NTP server UDP port."""
        return self._port

    @property
    def timeout_ms(self) -> int:
        """Per-request recv-side timeout."""
        return self._timeout_ms

    @property
    def busy(self) -> bool:
        """``True`` between :meth:`query` and result completion."""
        return self._result is not None and not self._result.done

    @property
    def socket(self) -> object:
        """The injected UDP socket.  Exposed for introspection only."""
        return self._socket

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
        now_ms = self._ticks_ms()
        result = NTPResult(ticks_started_ms=now_ms)
        request = _build_request()
        try:
            self._socket.sendto(request, self._server, self._port)
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
            received_count, _sender = self._socket.recvfrom_into(
                self._recv_buffer,
            )
        except OSError as recv_error:
            errno = recv_error.args[0] if recv_error.args else None
            if errno in (11, 35, 10035):
                # EAGAIN / EWOULDBLOCK / WSAEWOULDBLOCK — no data
                # this tick.  Check the timeout instead.
                elapsed_ms = ticks_diff(now_ms, result.ticks_started_ms)
                if elapsed_ms >= self._timeout_ms:
                    result._fail(
                        NTPError(
                            f"SNTP query timed out after {elapsed_ms} ms",
                        ),
                    )
                return
            # Any other socket error — fail the exchange.
            result._fail(recv_error)
            return
        if received_count == 0:
            # No data and no error — treat as "still waiting".
            elapsed_ms = ticks_diff(now_ms, result.ticks_started_ms)
            if elapsed_ms >= self._timeout_ms:
                result._fail(
                    NTPError(
                        f"SNTP query timed out after {elapsed_ms} ms",
                    ),
                )
            return
        try:
            # ``bytes(memoryview(buf)[:n])`` is one copy; the prior
            # ``bytes(buf[:n])`` was two (slice creates a new bytearray,
            # bytes() copies that).
            unix_seconds = _parse_response(
                bytes(memoryview(self._recv_buffer)[:received_count]),
            )
        except NTPError as parse_error:
            result._fail(parse_error)
            return
        result._complete(unix_seconds)

    def cancel(self) -> bool:
        """Abort an in-flight query.

        Returns:
            ``True`` if a query was in flight (now marked errored
            with ``NTPError("cancelled")``); ``False`` if the client
            was idle.
        """
        if not self.busy:
            return False
        self._result._fail(NTPError("cancelled"))
        return True
