"""``WifiService``: wifi state machine and reconnect supervisor.

Drives the substrate adapter through connect, monitor, and reconnect,
advancing a :class:`WifiState` machine from ``check`` / ``handle`` calls
in the runner's tick loop.
"""

import sys

from chumicro_timing import ticks as _DEFAULT_TICKS

from chumicro_wifi.config import WifiConfig


class WifiState:
    """State-name constants for :class:`WifiService`.

    Plain strings because :mod:`enum` is unavailable on some MicroPython
    boards. Compare via ``state == WifiState.CONNECTED``.
    """

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


def _select_adapter():
    # Lazy-import per runtime so a board only parses the adapter it uses.
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
    """Drives a wifi adapter through connect, monitor, and reconnect.

    On CircuitPython the connect step blocks: ``wifi.radio.connect`` has no
    non-blocking variant, so a connect attempt driven from ``handle()``
    stalls every co-scheduled runner service for up to
    ``connect_timeout_ms`` (default 15 s). MicroPython and CPython connect
    without stalling the loop, so keep ``connect_timeout_ms`` modest on CP.

    Args:
        config: A :class:`WifiConfig` with the credentials and tuning knobs.
        adapter: Optional :class:`WifiAdapter`. When ``None`` (default),
            :func:`_select_adapter` picks the runtime-appropriate one.
            Tests inject a :class:`FakeWifiAdapter`.
        ticks: Optional tick source exposing ``ticks_ms``, ``ticks_diff``,
            and ``ticks_add`` (the ``chumicro_timing.ticks`` shape).
            Defaults to that submodule (real clock); tests pass
            ``FakeTicks`` from ``chumicro_timing.testing``.
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
        # Absolute-tick deadline of an in-flight association on a non-blocking
        # adapter (MicroPython); ``None`` on blocking adapters and between attempts.
        self._attempt_deadline_ms = None
        self._state_callbacks = []

        # Apply hostname / power-save / static-IP once via the adapter.
        self.adapter.configure(self._config)

    # --- public state ------------------------------------------------

    @property
    def connected(self):
        """``True`` when the substrate is currently linked."""
        return self.state == WifiState.CONNECTED

    @property
    def ip(self):
        """Assigned IPv4 string, or ``None`` when not connected.

        Allocates on each access (the substrate builds a fresh string or
        tuple), so read it once after a connect and stash the result rather
        than polling it inside a tick loop.
        """
        return self.adapter.ip() if self.connected else None

    def on_state_change(self, callback: object) -> None:
        """Register a callback invoked on every state transition.

        Args:
            callback: Called as ``callback(old_state, new_state)``.
                Multiple callbacks fire in registration order.
        """
        self._state_callbacks.append(callback)

    # --- runner integration ------------------------------------------

    def check(self, now_ms):
        """Return ``True`` when the service has work to do this tick.

        Work is due when a connected link has dropped (time to reconnect)
        or when the backoff timer for the next connect attempt has elapsed.
        Returns ``False`` in the terminal ``FAILED`` state.
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
                # Update scheduling before the transition so a reentrant
                # callback sees a fresh backoff and due timer, not stale values.
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
        raised = False
        try:
            ok = self.adapter.connect(self._config)
        except Exception as error:  # noqa: BLE001 - adapter errors flow through last_error
            self.last_error = error
            ok = False
            raised = True

        if ok:
            self._mark_connected()
            return

        if raised:
            # connect() raised, so no join was dispatched: count a settled
            # failure and back off now rather than waiting out the timeout window.
            self._register_failed_attempt()
            return

        if not self.adapter.connect_blocks:
            # Non-blocking substrate: connect() dispatched but hasn't resolved.
            # Poll is_linked() over the timeout window before counting a failure.
            self._attempt_deadline_ms = self._ticks.ticks_add(
                now_ms, self._config.connect_timeout_ms,
            )
            return

        # Blocking substrate: connect() already waited, so False is a
        # settled failure.
        self._register_failed_attempt()

    def _poll_in_flight(self, now_ms):
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
        self._reconnect_attempts += 1
        if (
            self._config.reconnect_max is not None
            and self._reconnect_attempts >= self._config.reconnect_max
        ):
            self._transition(WifiState.FAILED)
            return

        # Schedule from the current clock, not a pre-attempt now_ms: a blocking
        # connect can burn the timeout window and cause back-to-back retries.
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
