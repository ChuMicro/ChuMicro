"""Test helpers for libraries that depend on ``chumicro-wifi``.

Hosts the test fakes (:class:`FakeWifi`, :class:`FakeWifiAdapter`) that
downstream libraries drive instead of hand-rolling a wifi mock, plus the
CPython-default adapter ``WifiService`` falls back to off-device.
"""

#: Source bundle / sdist only. Never lands on a device.
__chumicro_test_support__ = True

from chumicro_wifi._adapters.base import WifiAdapter
from chumicro_wifi.config import WifiConfig
from chumicro_wifi.service import WifiService


class FakeWifiAdapter(WifiAdapter):
    """In-memory adapter with explicit hooks for test scenarios.

    Drive the connection lifecycle with :meth:`set_connect_outcome` /
    :meth:`set_connect_outcomes` (what ``connect`` returns or raises),
    :meth:`drop_link` / :meth:`restore_link` (model a flapping link), and
    :meth:`set_deferred_link` (model a non-blocking MicroPython join). Every
    adapter call is recorded in ``self.calls`` for assertions.

    ``connect_blocks`` defaults to ``True`` (blocking substrate: a
    ``connect() == False`` is a settled failure). Flip it with
    :meth:`set_connect_blocks` or :meth:`set_deferred_link` to model the
    non-blocking MicroPython substrate.
    """

    name = "fake"

    def __init__(self, *, ip="192.168.0.42"):
        self._ip = ip
        self._linked = False
        self._configured_with = None
        self._connect_outcomes = []
        self._default_connect_outcome = True
        # Deferred (non-blocking) association: when set, connect() returns False
        # and is_linked() flips True after this many polls. ``None`` = blocking.
        self._link_after = None
        self._pending_polls = 0
        self.connect_blocks = True
        self.calls = []

    # --- WifiAdapter implementation ----------------------------------

    def configure(self, config):
        self._configured_with = config
        self.calls.append(("configure", config))

    def connect(self, config):
        self.calls.append(("connect", config))
        if self._link_after is not None:
            # Non-blocking deferred join: dispatched but not yet linked.
            # is_linked() resolves it over the next few polls.
            self._pending_polls = self._link_after
            return False
        outcome = self._next_outcome()
        if outcome is True:
            self._linked = True
            return True
        if outcome is False:
            self._linked = False
            return False
        # Anything else is treated as an exception class.
        raise outcome("simulated connect failure")

    def is_linked(self):
        if self._link_after is not None and self._pending_polls > 0:
            self._pending_polls -= 1
            if self._pending_polls == 0:
                self._linked = True
        return self._linked

    def ip(self):
        return self._ip if self._linked else None

    # --- test hooks --------------------------------------------------

    def set_connect_outcome(self, outcome: object) -> None:
        """Control what the next :meth:`connect` call returns or raises.

        Args:
            outcome: ``True`` (success), ``False`` (clean refusal), or an
                exception class to raise.
        """
        self._default_connect_outcome = outcome

    def set_connect_outcomes(self, outcomes: object) -> None:
        """Queue a one-shot sequence of outcomes.

        Args:
            outcomes: Iterable of outcome values consumed in order by
                successive :meth:`connect` calls. After the queue drains,
                falls back to the default from :meth:`set_connect_outcome`.
        """
        self._connect_outcomes = list(outcomes)

    def set_connect_blocks(self, blocks: bool) -> None:
        """Toggle the blocking (CP) vs non-blocking (MP) ``connect`` model.

        ``True`` (default): a ``connect() == False`` is a settled failure.
        ``False``: it means "join dispatched, still in flight", so the
        service polls :meth:`is_linked` over its ``connect_timeout_ms``
        window before counting a failure.
        """
        self.connect_blocks = blocks

    def set_deferred_link(self, *, link_after: int) -> None:
        """Model a non-blocking join that links after *link_after* polls.

        Puts the adapter in non-blocking mode (``connect_blocks = False``):
        the next :meth:`connect` dispatches and returns ``False``, and
        :meth:`is_linked` reports ``True`` on the *link_after*-th poll,
        matching a real MicroPython ``wlan.connect()`` that settles over
        seconds.
        """
        self._link_after = link_after
        self.connect_blocks = False

    def drop_link(self):
        """Simulate a link-down event without disconnecting cleanly."""
        self._linked = False

    def restore_link(self):
        """Simulate the AP coming back on its own (no ``connect`` call).

        Complement to :meth:`drop_link`: flips :meth:`is_linked` back to
        ``True`` so tests can model a flapping link.
        """
        self._linked = True

    @property
    def configured_with(self):
        """The :class:`WifiConfig` last passed to :meth:`configure`."""
        return self._configured_with

    def _next_outcome(self):
        if self._connect_outcomes:
            return self._connect_outcomes.pop(0)
        return self._default_connect_outcome


class FakeWifi(WifiService):
    """``WifiService`` wrapping a :class:`FakeWifiAdapter` for tests.

    Bundles the service and adapter so tests don't wire them by hand, and
    re-exposes the adapter's test hooks (``set_connect_outcome``,
    ``drop_link``, ``calls``) on the wrapper.

    Args:
        ticks: A tick source, typically a
            :class:`chumicro_timing.testing.FakeTicks` the test advances.
        config: Optional :class:`WifiConfig`. When ``None``, a fast-backoff
            default is used (ssid="testnet", password="password").
    """

    def __init__(self, ticks: object, *, config: WifiConfig | None = None) -> None:
        if config is None:
            config = WifiConfig(
                ssid="testnet",
                password="password",
                reconnect_backoff_start_ms=10,
                reconnect_backoff_max_ms=100,
            )
        self._fake_adapter = FakeWifiAdapter()
        super().__init__(config, adapter=self._fake_adapter, ticks=ticks)
        self._ticks_source = ticks

    # --- exposing adapter hooks for test ergonomics ------------------

    def set_connect_outcome(self, outcome):
        """Forward to the underlying :class:`FakeWifiAdapter`."""
        self._fake_adapter.set_connect_outcome(outcome)

    def set_connect_outcomes(self, outcomes):
        """Forward to the underlying :class:`FakeWifiAdapter`."""
        self._fake_adapter.set_connect_outcomes(outcomes)

    def drop_link(self):
        """Forward to the underlying :class:`FakeWifiAdapter`."""
        self._fake_adapter.drop_link()

    def restore_link(self):
        """Forward to the underlying :class:`FakeWifiAdapter`."""
        self._fake_adapter.restore_link()

    def set_connect_blocks(self, blocks):
        """Forward to the underlying :class:`FakeWifiAdapter`."""
        self._fake_adapter.set_connect_blocks(blocks)

    def set_deferred_link(self, *, link_after):
        """Forward to the underlying :class:`FakeWifiAdapter`."""
        self._fake_adapter.set_deferred_link(link_after=link_after)

    @property
    def calls(self):
        """List of recorded adapter calls. Assertion target for tests."""
        return self.adapter.calls

    # --- convenience for tick-driven tests ---------------------------

    def tick(self):
        """Run one runner-style ``check`` + ``handle`` cycle.

        Condenses the inner loop a ``Runner`` would run so tests don't need
        to wire a full ``Runner``.
        """
        now = self._ticks_source.ticks_ms()
        if self.check(now):
            self.handle(now)
