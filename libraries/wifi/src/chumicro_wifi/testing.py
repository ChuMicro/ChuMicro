"""Test helpers for libraries that depend on ``chumicro-wifi``.

Hosts the test fakes :class:`FakeWifi` and :class:`FakeWifiAdapter`.
"""

# Source bundle / sdist only; never lands on a device.
__chumicro_test_support__ = True

from chumicro_wifi._adapters.base import WifiAdapter
from chumicro_wifi.config import WifiConfig
from chumicro_wifi.service import WifiService


class FakeWifiAdapter(WifiAdapter):
    """In-memory adapter with explicit hooks for test scenarios."""

    name = "fake"

    def __init__(self, *, ip="192.168.0.42"):
        self._ip = ip
        self._linked = False
        self._configured_with = None
        self._connect_outcomes = []
        self._default_connect_outcome = True
        # Deferred join: connect() returns False, is_linked() flips True after this many polls.
        self._link_after = None
        self._pending_polls = 0
        self.connect_blocks = True
        self.calls = []

    def configure(self, config):
        self._configured_with = config
        self.calls.append(("configure", config))

    def connect(self, config):
        self.calls.append(("connect", config))
        if self._link_after is not None:
            self._pending_polls = self._link_after
            return False
        outcome = self._next_outcome()
        if outcome is True:
            self._linked = True
            return True
        if outcome is False:
            self._linked = False
            return False
        raise outcome("simulated connect failure")

    def is_linked(self):
        if self._link_after is not None and self._pending_polls > 0:
            self._pending_polls -= 1
            if self._pending_polls == 0:
                self._linked = True
        return self._linked

    def ip(self):
        return self._ip if self._linked else None

    def set_connect_outcome(self, outcome: object) -> None:
        """Control what the next :meth:`connect` call returns or raises.

        Args:
            outcome: ``True`` (success), ``False`` (clean refusal), or an exception class to raise.
        """
        self._default_connect_outcome = outcome

    def set_connect_outcomes(self, outcomes: object) -> None:
        """Queue a one-shot sequence of outcomes.

        Args:
            outcomes: Iterable of outcome values consumed in order, then falls back to the default.
        """
        self._connect_outcomes = list(outcomes)

    def set_connect_blocks(self, blocks: bool) -> None:
        """Toggle the blocking (CP) vs non-blocking (MP) ``connect`` model."""
        self.connect_blocks = blocks

    def set_deferred_link(self, *, link_after: int) -> None:
        """Model a non-blocking join that links after *link_after* polls."""
        self._link_after = link_after
        self.connect_blocks = False

    def drop_link(self):
        """Simulate a link-down event without disconnecting cleanly."""
        self._linked = False

    def restore_link(self):
        """Simulate the AP coming back on its own (no ``connect`` call)."""
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

    Args:
        ticks: A tick source, typically a :class:`chumicro_timing.testing.FakeTicks`.
        config: Optional :class:`WifiConfig`; ``None`` uses a fast-backoff default.
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
        """List of recorded adapter calls."""
        return self.adapter.calls

    def tick(self):
        """Run one runner-style ``check`` + ``handle`` cycle."""
        now = self._ticks_source.ticks_ms()
        if self.check(now):
            self.handle(now)
