"""``WifiService``: state machine + reconnect supervisor.

Drives the substrate adapter through connect, monitor, and
reconnect, and tracks state in the runner's tick loop.

State machine (``WifiState`` constants)::

    DISCONNECTED -> CONNECTING -> CONNECTED
                        |            |
                        |            v
                        |       RECONNECTING (on link drop)
                        |            |
                        v            v
                     FAILED <--- backoff exhausted (only when reconnect_max set)

Runner contract: ``check(now_ms)`` returns ``True`` when the next
event is due (initial connect, reconnect attempt, link-down
detection).  ``handle(now_ms)`` does one tick of substrate work.
"""

import sys

from chumicro_timing import ticks as _DEFAULT_TICKS

from chumicro_wifi.config import WifiConfig


class WifiState:
    """String-sentinel state names for :class:`WifiService`.

    Plain strings, because :mod:`enum` is unavailable on some
    MicroPython boards.  Compare via ``state == WifiState.CONNECTED``.
    Do not instantiate.
    """

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


def _select_adapter():
    """Pick the runtime-appropriate adapter.

    CP and MP branches lazy-import the substrate-specific module so
    a board only parses the adapter it actually uses.
    ``MpWifiAdapter`` auto-detects ESP-IDF vs CYW43 internally, so
    the dispatch here is a clean three-way (CP / MP / fake).
    CPython falls back to ``FakeWifiAdapter`` from the host-only
    :mod:`chumicro_wifi.testing` module, which is fine because the
    fallback only fires on the host.
    """
    runtime_name = sys.implementation.name
    if runtime_name == "circuitpython":  # pragma: no cover - CP runtime path
        from chumicro_wifi._adapters.cp import CpWifiAdapter
        return CpWifiAdapter()
    if runtime_name == "micropython":  # pragma: no cover - MP runtime path
        from chumicro_wifi._adapters.mp import MpWifiAdapter
        return MpWifiAdapter()
    # CPython host fallback: testing.py owns the fake.
    from chumicro_wifi.testing import FakeWifiAdapter
    return FakeWifiAdapter()


class WifiService:
    """Drives a wifi adapter through connect / monitor / reconnect.

    On CircuitPython the connect step blocks: ``wifi.radio.connect`` has
    no non-blocking variant, so a connect attempt driven from
    ``handle()`` stalls every co-scheduled runner service for up to
    ``WifiConfig.connect_timeout_ms`` (default 15 s).  MicroPython and
    CPython connect without stalling the loop.  Keep ``connect_timeout_ms``
    modest on CP, or accept the stall during the infrequent connect /
    reconnect windows.

    Args:
        config: A :class:`WifiConfig` with the credentials + tuning
            knobs.  Required.
        adapter: Optional :class:`WifiAdapter` instance.  When
            ``None`` (default), :func:`_select_adapter` picks the
            runtime-appropriate one.  Tests inject a
            :class:`FakeWifiAdapter` to drive the state machine
            deterministically.
        ticks: Optional tick source: any object exposing
            ``ticks_ms``, ``ticks_diff``, ``ticks_add`` (matches the
            ``chumicro_timing.ticks`` submodule shape).  Defaults to
            that submodule (real clock).  Tests pass ``FakeTicks``
            from ``chumicro_timing.testing``.
    """

    def __init__(
        self,
        config: WifiConfig,
        *,
        adapter: object | None = None,
        ticks: object | None = None,
    ) -> None:
        self._config = config
        self.adapter = adapter if adapter is not None else _select_adapter()
        self._ticks = ticks if ticks is not None else _DEFAULT_TICKS

        self.state = WifiState.DISCONNECTED
        self.last_error = None
        self._next_attempt_due_ms = self._ticks.ticks_ms()
        self._current_backoff_ms = config.reconnect_backoff_start_ms
        self._reconnect_attempts = 0
        # Deadline (absolute tick) of an in-flight association on a
        # non-blocking adapter (MicroPython): while set, handle() polls
        # is_linked() each tick until the link comes up or the deadline
        # elapses, so the association's normal seconds-long settle isn't
        # miscounted as a burst of failed attempts.  ``None`` on blocking
        # adapters (CircuitPython) and between attempts.
        self._attempt_deadline_ms = None
        self._state_callbacks = []

        # Apply hostname / power-save / static-IP once.  The adapter
        # is responsible for the substrate-specific knobs.
        self.adapter.configure(self._config)

    # --- public state ------------------------------------------------

    @property
    def connected(self):
        """``True`` when the substrate is currently linked."""
        return self.state == WifiState.CONNECTED

    @property
    def ip(self):
        """Assigned IPv4 string, or ``None`` when not connected.

        Allocates per access: CircuitPython stringifies its
        ``IPv4Address`` object, MicroPython's ``ifconfig()`` builds a
        fresh 4-tuple inside the substrate.  Read once after a
        connect / on the ``CONNECTED`` callback and stash the result.
        Don't poll inside a ``runner.tick`` loop or repeat in a
        debug-log path.  The state never updates the IP in place, so
        re-reading after a transition (or after a DHCP renewal) is
        correct.  The allocation cost is the price of seeing changes.
        """
        return self.adapter.ip() if self.connected else None

    def on_state_change(self, callback: object) -> None:
        """Register a callback invoked on every state transition.

        Args:
            callback: Called as ``callback(old_state, new_state)``.
                Multiple callbacks may be registered.  They fire in
                registration order.
        """
        self._state_callbacks.append(callback)

    # --- runner integration ------------------------------------------

    def check(self, now_ms):
        """Return ``True`` when the service has work to do this tick.

        Three cases:

        1. We're connected and the link is still up: nothing to do.
        2. We're connected and the link dropped: transition to
           ``RECONNECTING`` on the next ``handle``.
        3. We're between attempts (``CONNECTING`` / ``RECONNECTING``)
           and the backoff timer is due.
        """
        if self.state == WifiState.FAILED:
            return False
        if self.state == WifiState.CONNECTED:
            return not self.adapter.is_linked()
        if self._attempt_deadline_ms is not None:
            return True  # in-flight association: poll every tick
        return self._ticks.ticks_diff(now_ms, self._next_attempt_due_ms) >= 0

    def handle(self, now_ms):
        """Drive the state machine forward.

        If ``check`` returned ``False`` and ``handle`` is called
        anyway, returns without changing state.
        """
        if self.state == WifiState.CONNECTED:
            if not self.adapter.is_linked():
                # Update scheduling before firing the transition so a
                # reentrant callback observes a consistent state (a fresh
                # backoff and a due timer), not stale RECONNECTING values.
                self._reset_backoff()
                self._next_attempt_due_ms = now_ms
                self._attempt_deadline_ms = None
                self._transition(WifiState.RECONNECTING)
            return

        if self.state == WifiState.FAILED:
            return

        if self.state == WifiState.DISCONNECTED:
            self._transition(WifiState.CONNECTING)

        # An in-flight association (non-blocking adapter) is polled every
        # tick, independent of the backoff gate.
        if self._attempt_deadline_ms is not None:
            self._poll_in_flight(now_ms)
            return

        # CONNECTING or RECONNECTING: start the next attempt once the
        # backoff timer is due.
        if self._ticks.ticks_diff(now_ms, self._next_attempt_due_ms) < 0:
            return  # too early, checked once more next tick

        self._attempt_connect(now_ms)

    # --- internals ---------------------------------------------------

    def _attempt_connect(self, now_ms):
        try:
            ok = self.adapter.connect(self._config)
        except Exception as error:  # noqa: BLE001 - adapter errors flow through last_error
            self.last_error = error
            ok = False

        if ok:
            self._mark_connected()
            return

        if not self.adapter.connect_blocks:
            # Non-blocking substrate: connect() dispatched the join and
            # returned before it resolved.  Poll is_linked() over the
            # connect_timeout_ms window before counting a failure, so a
            # normal seconds-long association isn't read as a failed
            # attempt on every tick.
            self._attempt_deadline_ms = self._ticks.ticks_add(
                now_ms, self._config.connect_timeout_ms,
            )
            return

        # Blocking substrate: connect() already waited, so False is a
        # settled failure.
        self._register_failed_attempt()

    def _poll_in_flight(self, now_ms):
        """Poll an in-flight non-blocking association toward link-up or timeout."""
        if self.adapter.is_linked():
            self._mark_connected()
            return
        if self._ticks.ticks_diff(now_ms, self._attempt_deadline_ms) >= 0:
            self._attempt_deadline_ms = None
            self._register_failed_attempt()

    def _mark_connected(self):
        self.last_error = None
        self._reset_backoff()
        self._reconnect_attempts = 0
        self._attempt_deadline_ms = None
        self._transition(WifiState.CONNECTED)

    def _register_failed_attempt(self):
        """Count a settled failed attempt: back off, or fail terminally."""
        self._reconnect_attempts += 1
        if (
            self._config.reconnect_max is not None
            and self._reconnect_attempts >= self._config.reconnect_max
        ):
            self._transition(WifiState.FAILED)
            return

        # Schedule the next attempt from the current clock, not a
        # pre-attempt now_ms: a blocking connect can burn most of
        # connect_timeout_ms, which would leave now_ms + backoff already
        # in the past and retry back-to-back with no gap.
        self._next_attempt_due_ms = self._ticks.ticks_add(
            self._ticks.ticks_ms(), self._current_backoff_ms,
        )
        self._current_backoff_ms = min(
            self._current_backoff_ms * 2,
            self._config.reconnect_backoff_max_ms,
        )

    def _transition(self, new_state):
        if new_state == self.state:
            return
        old_state = self.state
        self.state = new_state
        for callback in self._state_callbacks:
            # A raising callback must not abort the remaining callbacks
            # or escape into the runner tick; record it and continue.
            try:
                callback(old_state, new_state)
            except Exception as error:  # noqa: BLE001 - callbacks are user code
                self.last_error = error

    def _reset_backoff(self):
        self._current_backoff_ms = self._config.reconnect_backoff_start_ms
