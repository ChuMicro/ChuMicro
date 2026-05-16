"""Test helpers for libraries that depend on ``chumicro-wifi``.

Downstream consumers import ``FakeWifi`` rather than inventing
ad-hoc mocks.

Example::

    from chumicro_wifi.testing import FakeWifi
    from chumicro_timing.testing import FakeTicks

    fake_ticks = FakeTicks()
    fake_wifi = FakeWifi(fake_ticks)
    fake_wifi.set_connect_outcome(True)
    fake_ticks.advance(0)
    fake_wifi.tick()
    assert fake_wifi.state == "connected"

This module hosts both the test fakes (``FakeWifi``,
``FakeWifiAdapter``) and the CPython-default adapter the production
``WifiService`` falls back to when no real runtime adapter applies.
The ``__chumicro_test_support__`` marker below keeps the file out of
every bundle and every product / app / functional device deploy, so
the fakes and the CPython-default adapter stay host-side — exactly
where they're needed (the on-device unit sweep is the one path that
stages it; CPython is a host-test seam, not a deploy target).
"""

#: Source bundle / sdist only -- never lands on a device.
__chumicro_test_support__ = True

from chumicro_wifi._adapters.base import WifiAdapter
from chumicro_wifi.config import WifiConfig
from chumicro_wifi.service import WifiService


class FakeWifiAdapter(WifiAdapter):
    """In-memory adapter with explicit hooks for test scenarios.

    The connection lifecycle is driven by:

    * :meth:`set_connect_outcome` — controls what the next
      :meth:`connect` returns (``True`` for success, ``False`` for
      a clean refusal, an exception class to raise, or a one-shot
      sequence via :meth:`set_connect_outcomes`).
    * :meth:`drop_link` — simulates a link-down event; the next
      :meth:`is_linked` returns ``False``, triggering the service's
      reconnect path.
    * :meth:`record` — every adapter call appends to ``self.calls``
      so tests can assert call ordering and arguments.
    """

    name = "fake"

    def __init__(self, *, ip="192.168.0.42"):
        self._ip = ip
        self._linked = False
        self._configured_with = None
        self._connect_outcomes = []
        self._default_connect_outcome = True
        self.calls = []

    # --- WifiAdapter implementation ----------------------------------

    def configure(self, config):
        self._configured_with = config
        self.calls.append(("configure", config))

    def connect(self, config):
        self.calls.append(("connect", config))
        outcome = self._next_outcome()
        if outcome is True:
            self._linked = True
            return True
        if outcome is False:
            self._linked = False
            return False
        # Anything else is treated as an exception class.
        raise outcome("simulated connect failure")

    def disconnect(self):
        self.calls.append(("disconnect",))
        self._linked = False

    def is_linked(self):
        return self._linked

    def ip(self):
        return self._ip if self._linked else None

    # --- test hooks --------------------------------------------------

    def set_connect_outcome(self, outcome: object) -> None:
        """Control what the next :meth:`connect` call returns / raises.

        Args:
            outcome: ``True`` (success), ``False`` (clean refusal),
                or an exception class to raise.
        """
        self._default_connect_outcome = outcome

    def set_connect_outcomes(self, outcomes: object) -> None:
        """Queue a one-shot sequence of outcomes.

        Args:
            outcomes: Iterable of outcome values consumed in order
                by successive :meth:`connect` calls.  After the
                queue is drained, falls back to the default set via
                :meth:`set_connect_outcome`.
        """
        self._connect_outcomes = list(outcomes)

    def drop_link(self):
        """Simulate a link-down event without disconnecting cleanly."""
        self._linked = False

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

    Bundles the service + adapter so tests don't have to wire them
    by hand.  Exposes the adapter's test hooks
    (``set_connect_outcome``, ``drop_link``, ``calls``) directly on
    the wrapper for ergonomic use in test code.

    Args:
        ticks: A tick source — typically a
            :class:`chumicro_timing.testing.FakeTicks` instance the
            test owns and advances explicitly.
        config: Optional :class:`WifiConfig`.  When ``None`` a
            sensible default is used (ssid="testnet",
            password="password", short backoffs so tests run fast).
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

    @property
    def calls(self):
        """List of recorded adapter calls — assertion target for tests."""
        return self.adapter.calls

    # --- convenience for tick-driven tests ---------------------------

    def tick(self):
        """Run one runner-style ``check`` + ``handle`` cycle.

        Equivalent to the inner loop ``Runner`` would run, but
        condensed so tests don't need to wire a full ``Runner``.
        """
        now = self._ticks_source.ticks_ms()
        if self.check(now):
            self.handle(now)
