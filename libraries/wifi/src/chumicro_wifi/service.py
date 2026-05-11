"""``WifiService`` — state machine + reconnect supervisor.

Library is the sole supervisor on every runtime — no
``CIRCUITPY_WIFI_*`` keys, no firmware-level auto-reconnect.  This
class drives the substrate adapter and tracks state in the runner's
tick loop.

State machine (`state.py` constants)::

    DISCONNECTED -> CONNECTING -> CONNECTED
                        |            |
                        |            v
                        |       RECONNECTING (on link drop)
                        |            |
                        v            v
                     FAILED <--- backoff exhausted (only when reconnect_max set)

Runner contract: ``check(now_ms)`` returns ``True`` when the next
event is due (initial connect, reconnect attempt, link-down
detection); ``handle(now_ms)`` does one tick of substrate work.
"""

import sys

from chumicro_timing import ticks as _DEFAULT_TICKS
from chumicro_wifi.config import WifiConfig
from chumicro_wifi.state import WifiState


def _select_adapter():
    """Pick the runtime-appropriate adapter.

    CP / MP branches lazy-import the substrate-specific module so the
    board only parses the adapter it actually uses.  ``MpWifiAdapter``
    auto-detects ESP-IDF vs CYW43 internally, so the dispatch here
    is a clean three-way (CP / MP / fake).  CPython falls back to
    ``FakeWifiAdapter`` from :mod:`chumicro_wifi.testing` — testing.py
    is host-only, but the CPython branch is the only place the
    fallback fires.
    """
    runtime_name = sys.implementation.name
    if runtime_name == "circuitpython":  # pragma: no cover - CP runtime path
        from chumicro_wifi._adapters.cp import CpWifiAdapter
        return CpWifiAdapter()
    if runtime_name == "micropython":  # pragma: no cover - MP runtime path
        from chumicro_wifi._adapters.mp import MpWifiAdapter
        return MpWifiAdapter()
    # CPython host fallback — testing.py owns the fake.
    from chumicro_wifi.testing import FakeWifiAdapter
    return FakeWifiAdapter()


class WifiService:
    """Drives a wifi adapter through connect / monitor / reconnect.

    Args:
        config: A :class:`WifiConfig` with the credentials + tuning
            knobs.  Required.
        adapter: Optional :class:`WifiAdapter` instance.  When
            ``None`` (default), :func:`_select_adapter` picks the
            runtime-appropriate one.  Tests inject a
            :class:`FakeWifiAdapter` to drive the state machine
            deterministically.
        ticks: Optional tick source — any object exposing
            ``ticks_ms``, ``ticks_diff``, ``ticks_add`` (matches the
            ``chumicro_timing.ticks`` submodule shape).  Defaults to
            that submodule (real clock); tests pass ``FakeTicks``
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
        self._adapter = adapter if adapter is not None else _select_adapter()
        self._ticks = ticks if ticks is not None else _DEFAULT_TICKS

        self._state = WifiState.DISCONNECTED
        self._last_error = None
        self._next_attempt_due_ms = self._ticks.ticks_ms()
        self._current_backoff_ms = config.reconnect_backoff_start_ms
        self._reconnect_attempts = 0
        self._state_callbacks = []

        # Apply hostname / power-save / static-IP once; the adapter
        # is responsible for the substrate-specific knobs.
        self._adapter.configure(self._config)

    # --- public state ------------------------------------------------

    @property
    def state(self):
        """Current state (one of :class:`WifiState`'s constants)."""
        return self._state

    @property
    def connected(self):
        """``True`` when the substrate is currently linked."""
        return self._state == WifiState.CONNECTED

    @property
    def ip(self):
        """Assigned IPv4 string, or ``None`` when not connected."""
        return self._adapter.ip() if self.connected else None

    @property
    def last_error(self):
        """Most recent exception from the adapter, or ``None``."""
        return self._last_error

    @property
    def adapter_name(self):
        """Stable identifier for the active adapter."""
        return self._adapter.name

    @property
    def adapter(self):
        """The active :class:`~chumicro_wifi._adapters.base.WifiAdapter`.

        Exposed so consumers needing a per-runtime substrate handle
        — typically CircuitPython's radio — can write
        ``radio=wifi.adapter.radio`` uniformly across every runtime.
        On MP / CPython the base class supplies ``radio = None`` so
        the same line is well-defined and harmless.
        """
        return self._adapter

    def on_state_change(self, callback: object) -> None:
        """Register a callback invoked on every state transition.

        Args:
            callback: Called as ``callback(old_state, new_state)``.
                Multiple callbacks may be registered; they fire in
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
        if self._state == WifiState.FAILED:
            return False
        if self._state == WifiState.CONNECTED:
            return not self._adapter.is_linked()
        return self._ticks.ticks_diff(now_ms, self._next_attempt_due_ms) >= 0

    def handle(self, now_ms):
        """Drive the state machine forward.

        Idempotent within a tick — if ``check`` returned ``False``
        and ``handle`` is called anyway, this is a no-op.
        """
        if self._state == WifiState.CONNECTED:
            if not self._adapter.is_linked():
                self._transition(WifiState.RECONNECTING)
                self._reset_backoff()
                self._next_attempt_due_ms = now_ms
            return

        if self._state == WifiState.FAILED:
            return

        if self._state == WifiState.DISCONNECTED:
            self._transition(WifiState.CONNECTING)

        # CONNECTING or RECONNECTING — attempt the substrate connect.
        if self._ticks.ticks_diff(now_ms, self._next_attempt_due_ms) < 0:
            return  # too early; checked once more next tick

        self._attempt_connect(now_ms)

    # --- internals ---------------------------------------------------

    def _attempt_connect(self, now_ms):
        try:
            ok = self._adapter.connect(self._config)
        except Exception as error:  # noqa: BLE001 - adapter errors flow through last_error
            self._last_error = error
            ok = False

        if ok:
            self._last_error = None
            self._reset_backoff()
            self._reconnect_attempts = 0
            self._transition(WifiState.CONNECTED)
            return

        # Failed attempt: schedule the next one with exponential backoff.
        self._reconnect_attempts += 1
        if (
            self._config.reconnect_max is not None
            and self._reconnect_attempts >= self._config.reconnect_max
        ):
            self._transition(WifiState.FAILED)
            return

        self._next_attempt_due_ms = self._ticks.ticks_add(now_ms, self._current_backoff_ms)
        self._current_backoff_ms = min(
            self._current_backoff_ms * 2,
            self._config.reconnect_backoff_max_ms,
        )

    def _transition(self, new_state):
        if new_state == self._state:
            return
        old_state = self._state
        self._state = new_state
        for callback in self._state_callbacks:
            callback(old_state, new_state)

    def _reset_backoff(self):
        self._current_backoff_ms = self._config.reconnect_backoff_start_ms
