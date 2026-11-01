"""``WifiService`` joins a wifi network, watches the link, and rejoins after a drop."""

import sys

from chumicro_wifi.config import WifiConfig

#: How often ``next_deadline`` asks for a turn while a non-blocking join is
#: in flight, so ``handle()`` reads ``is_linked()`` soon after association lands.
_JOIN_POLL_MS = 100

#: How often ``next_deadline`` asks for a turn while connected, so a dropped
#: link is noticed within this window even when nothing else wakes the loop.
_LINK_POLL_MS = 1_000


class WifiState:
    """``WifiState`` names the values ``WifiService.state`` takes.

    Each value is a plain string, such as ``"connected"``.  ``DISCONNECTED``
    holds until the first ``handle`` call.  ``CONNECTING`` covers the first
    join and its retries.  ``CONNECTED`` means the board has joined.
    ``RECONNECTING`` covers rejoining after a lost link.  ``FAILED`` means
    ``reconnect_max`` attempts failed in a row, and the service has stopped.
    """

    # Plain strings, not an enum: some MicroPython boards lack the enum module.
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


def _select_adapter(radio=None):
    # Import per runtime so a board only parses the adapter it uses.
    # radio reaches only the CircuitPython adapter; the other runtimes
    # acquire their own station handle and ignore it.
    runtime_name = sys.implementation.name
    if runtime_name == "circuitpython":  # pragma: no cover - CP runtime path
        from chumicro_wifi._adapters.cp import CpWifiAdapter
        return CpWifiAdapter(radio=radio)
    if runtime_name == "micropython":  # pragma: no cover - MP runtime path
        from chumicro_wifi._adapters.mp import MpWifiAdapter
        return MpWifiAdapter()
    from chumicro_wifi._adapters.cpython import CpythonWifiAdapter
    return CpythonWifiAdapter()


class WifiService:
    """``WifiService`` joins the network in ``config`` and rejoins it whenever the link drops.

    Create one at startup.  The main loop then calls ``check(now_ms)`` and
    ``handle(now_ms)``, or a ``Runner`` does after ``runner.add(service)``.
    Creating the service touches no radio.  After a failed join the service
    pauses ``reconnect_backoff_start_ms`` before the next attempt, and each
    further failure doubles the pause up to ``reconnect_backoff_max_ms``.

    On CircuitPython a join attempt holds ``handle`` until the board joins or
    ``connect_timeout_ms`` passes.  On MicroPython ``handle`` starts the join
    and returns, and later calls check whether it finished.  On CPython the
    service reports connected on the first ``handle`` call, with the address
    ``127.0.0.1``.

    Args:
        config: The network name, password, and retry timing.
        adapter: Radio driver to use, or ``None`` to pick the one for the
            running runtime.  Host tests pass
            ``chumicro_wifi.testing.FakeWifiAdapter``.
        ticks: Clock with ``ticks_ms``, ``ticks_diff``, and ``ticks_add``, or
            ``None`` for ``chumicro_timing.ticks``.

    Attributes:
        state: Current state, one of the ``WifiState`` values.
        last_error: Exception from the latest join attempt or state-change
            callback that raised, or ``None``.  A successful join clears it.
        adapter: The radio driver in use.  On CircuitPython ``adapter.radio``
            is the ``wifi.radio`` object that socket calls take as ``radio=``.
    """

    @classmethod
    def from_config(
        cls,
        config: object,
        *,
        radio: object | None = None,
        ticks: object | None = None,
        **constructor_kwargs: object,
    ) -> "WifiService":
        """Build a ``WifiService`` from the ``wifi.*`` keys of deployed settings.

        ``WifiConfig.from_config`` reads the keys.  Each keyword in
        ``constructor_kwargs`` passes straight to the constructor.

        Args:
            config: Flat settings dict or ``chumicro_config.RuntimeConfig``.
            radio: CircuitPython radio to drive, such as ``wifi.radio``, or
                ``None`` to let the service find it.  MicroPython and CPython
                ignore it, and an ``adapter=`` keyword replaces it.
            ticks: Clock passed to the constructor.
            **constructor_kwargs: Other constructor keywords, such as ``adapter=``.

        Returns:
            The new ``WifiService``.

        Raises:
            chumicro_config.MissingConfigKey: ``wifi.ssid`` or ``wifi.password`` is absent.
            chumicro_config.InvalidConfigType: ``config`` is ``None``, or
                neither a dict nor a ``RuntimeConfig``.
        """
        kwargs: dict = {"ticks": ticks}
        if radio is not None and "adapter" not in constructor_kwargs:
            kwargs["adapter"] = _select_adapter(radio=radio)
        kwargs.update(constructor_kwargs)
        return cls(WifiConfig.from_config(config), **kwargs)

    def __init__(
        self,
        config: WifiConfig,
        *,
        adapter: object | None = None,
        ticks: object | None = None,
    ) -> None:
        self._config = config
        self.adapter = adapter if adapter is not None else _select_adapter()
        if ticks is not None:
            self._ticks = ticks
        else:
            from chumicro_timing import (
                ticks as real_ticks,  # noqa: PLC0415 - DI fallback keeps the substrate off BYO-ticks deploys
            )
            self._ticks = real_ticks

        self.state = WifiState.DISCONNECTED
        self.last_error = None
        self._next_attempt_due_ms = self._ticks.ticks_ms()
        self._current_backoff_ms = config.reconnect_backoff_start_ms
        self._reconnect_attempts = 0
        # Absolute-tick deadline of an in-flight join on a non-blocking adapter; None otherwise.
        self._attempt_deadline_ms = None
        # True once the first adapter.connect() has been dispatched; gates the first-association grace.
        self._first_connect_dispatched = False
        self._state_callbacks = []
        # Radio I/O stays out of the constructor: configure() runs on the
        # first connect attempt, inside the tick loop.
        self._configured = False

    @property
    def connected(self):
        """``True`` while ``state`` is ``WifiState.CONNECTED``.

        The radio reports a lost link seconds late, so this stays ``True`` for
        that long after the network drops.
        """
        return self.state == WifiState.CONNECTED

    @property
    def ip(self):
        """The board's IPv4 address as a string, such as ``"192.168.1.42"``.

        ``None`` while not connected, and on MicroPython until DHCP assigns an
        address.
        """
        return self.adapter.ip() if self.connected else None

    def on_state_change(self, callback: object) -> None:
        """Register ``callback`` to run on every change of ``state``.

        ``handle`` calls each callback as ``callback(old_state, new_state)``,
        in registration order.  An exception from a callback lands in
        ``last_error`` when that holds ``None``, and the remaining callbacks
        still run.

        Args:
            callback: Function taking the old and new ``WifiState`` values.
        """
        self._state_callbacks.append(callback)

    def check(self, now_ms):
        """Return ``True`` when ``handle`` has work at ``now_ms``, the current time from ``ticks_ms()``.

        Work means a join attempt is due, a join is in flight, or the radio
        reports a lost link.  ``check`` returns ``False`` during a retry pause,
        while connected with the link up, and in ``WifiState.FAILED``.
        """
        if self.state == WifiState.FAILED:
            return False
        if self.state == WifiState.CONNECTED:
            return not self.adapter.is_linked()
        if self._attempt_deadline_ms is not None:
            return True
        return self._ticks.ticks_diff(now_ms, self._next_attempt_due_ms) >= 0

    def next_deadline(self, now_ms):
        """Return the tick by which ``handle`` must run next, or ``None`` in ``WifiState.FAILED``.

        ``Runner.wait`` sleeps until the earliest deadline its services
        report.  While connected the deadline is ``now_ms`` plus 1000 ms, so
        the service checks the link once a second.  While a join is in flight
        it is ``now_ms`` plus 100 ms, and the first check past the join's
        timeout counts the attempt as failed.  During a retry pause it is the
        tick of the next attempt.
        """
        if self.state == WifiState.FAILED:
            return None
        if self.state == WifiState.CONNECTED:
            return self._ticks.ticks_add(now_ms, _LINK_POLL_MS)
        if self._attempt_deadline_ms is not None:
            return self._ticks.ticks_add(now_ms, _JOIN_POLL_MS)
        return self._next_attempt_due_ms

    def handle(self, now_ms):
        """Take the next step of joining, watching the link, or waiting to retry.

        Call it when ``check(now_ms)`` returns ``True``.  The first join
        attempt applies ``hostname``, ``tx_power_dbm``, and ``power_save`` to
        the radio, and on MicroPython switches the radio on.  On
        CircuitPython a join attempt holds the call for up to
        ``connect_timeout_ms``.  On MicroPython the call starts the join and
        returns without waiting for it.
        """
        if self.state == WifiState.CONNECTED:
            if not self.adapter.is_linked():
                # Update scheduling before the transition so a reentrant callback sees fresh values.
                self._reset_backoff()
                self._next_attempt_due_ms = now_ms
                self._attempt_deadline_ms = None
                self._transition(WifiState.RECONNECTING)
            return

        if self.state == WifiState.FAILED:
            return

        if self.state == WifiState.DISCONNECTED:
            self._transition(WifiState.CONNECTING)

        if self._attempt_deadline_ms is not None:
            self._poll_in_flight(now_ms)
            return

        if self._ticks.ticks_diff(now_ms, self._next_attempt_due_ms) < 0:
            return

        self._attempt_connect(now_ms)

    def _attempt_connect(self, now_ms):
        timeout_ms = self._attempt_timeout_ms()
        raised = False
        try:
            if not self._configured:
                self.adapter.configure(self._config)
                self._configured = True
            self._first_connect_dispatched = True
            ok = self.adapter.connect(self._config, timeout_ms=timeout_ms)
        except Exception as error:  # noqa: BLE001 - adapter errors flow through last_error
            self.last_error = error
            ok = False
            raised = True

        if ok:
            self._mark_connected()
            return

        if raised:
            # connect() raised: no join was dispatched, so count a settled failure now.
            self._register_failed_attempt()
            return

        if not self.adapter.connect_blocks:
            # Non-blocking substrate: join dispatched, poll is_linked() over the timeout window.
            self._attempt_deadline_ms = self._ticks.ticks_add(
                now_ms, timeout_ms,
            )
            return

        # Blocking substrate: connect() already waited, so False is a settled failure.
        self._register_failed_attempt()

    def _attempt_timeout_ms(self):
        # first_connect_timeout_ms covers only the first dispatched join:
        # a cold radio's first association after power-up takes longer
        # than steady-state reconnects, and the first dial warms the
        # radio whatever its outcome.
        grace_ms = self._config.first_connect_timeout_ms
        if grace_ms is not None and not self._first_connect_dispatched:
            return grace_ms
        return self._config.connect_timeout_ms

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

        # Schedule from the current clock, not now_ms: a blocking connect can burn the timeout window.
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
            # A raising callback must not abort the others or escape into the runner tick.
            try:
                callback(old_state, new_state)
            except Exception as error:  # noqa: BLE001 - callbacks are user code
                # Record only into an empty slot: the adapter failure that
                # caused this transition must stay readable in last_error.
                if self.last_error is None:
                    self.last_error = error

    def _reset_backoff(self):
        self._current_backoff_ms = self._config.reconnect_backoff_start_ms
