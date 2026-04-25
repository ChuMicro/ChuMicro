"""``FakeWifiAdapter`` — deterministic stand-in for tests + CPython default.

Mirrors the substrate behaviors ``WifiService`` cares about
without touching real hardware.  Tests construct one via
:class:`chumicro_wifi.testing.FakeWifi` (which wraps it for nicer
ergonomics) or pass it directly via the ``adapter=`` constructor
arg.
"""

from chumicro_wifi._adapters.base import WifiAdapter


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

    def set_connect_outcome(self, outcome):
        """Control what the next :meth:`connect` call returns / raises.

        Args:
            outcome: ``True`` (success), ``False`` (clean refusal),
                or an exception class to raise.
        """
        self._default_connect_outcome = outcome

    def set_connect_outcomes(self, outcomes):
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
