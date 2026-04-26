"""Test helpers for libraries that depend on ``chumicro-wifi``.

Ships with the library per Decision 0010.  Downstream consumers
import ``FakeWifi`` rather than inventing ad-hoc mocks.

Example::

    from chumicro_wifi.testing import FakeWifi
    from chumicro_timing.testing import FakeTicks

    fake_ticks = FakeTicks()
    fake_wifi = FakeWifi(fake_ticks)
    fake_wifi.set_connect_outcome(True)
    fake_ticks.advance(0)
    fake_wifi.tick()
    assert fake_wifi.state == "connected"
"""

from chumicro_wifi._adapters.fake import FakeWifiAdapter
from chumicro_wifi.config import WifiConfig
from chumicro_wifi.service import WifiService


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
        return self._fake_adapter.calls

    @property
    def adapter(self):
        """The underlying :class:`FakeWifiAdapter` for direct inspection."""
        return self._fake_adapter

    # --- convenience for tick-driven tests ---------------------------

    def tick(self):
        """Run one runner-style ``check`` + ``handle`` cycle.

        Equivalent to the inner loop ``Runner`` would run, but
        condensed so tests don't need to wire a full ``Runner``.
        """
        now = self._ticks_source.ticks_ms()
        if self.check(now):
            self.handle(now)
