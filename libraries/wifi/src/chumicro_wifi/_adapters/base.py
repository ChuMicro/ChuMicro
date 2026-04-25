"""``WifiAdapter`` — minimum protocol every concrete adapter satisfies.

Adapters wrap the runtime's wifi stack (`wifi.radio` on CP,
`network.WLAN` on MP).  ``WifiService`` drives them; users never
touch them directly.

Six methods cover the substrate's lifecycle:

* :meth:`configure` — apply hostname / power-save / static-IP
  settings (called once at construction, before the first connect).
* :meth:`connect` — non-blocking attempt to associate.  Adapters
  whose substrate's connect call is blocking budget the call against
  ``connect_timeout_ms`` and return when done.
* :meth:`disconnect` — drop the association if any.
* :meth:`is_linked` — return ``True`` while the substrate reports
  an active association.
* :meth:`ip` — return the assigned IPv4 string, or ``None`` when
  not linked.
* :meth:`name` — stable identifier for the adapter ("cp",
  "mp_esp32", "mp_rp2", "fake").  Used by
  :attr:`WifiService.adapter_name`.
"""


class WifiAdapter:
    """Concrete adapters inherit and override the six members below.

    Class rather than ``Protocol`` because library code cannot
    import ``typing`` (Decision 0021).
    """

    name = "base"

    def configure(self, config):
        """Apply hostname / power-save / static-IP settings.

        Args:
            config: The ``WifiConfig`` instance the service was
                constructed with.
        """
        raise NotImplementedError

    def connect(self, config):
        """Begin association with the AP.

        Args:
            config: The ``WifiConfig`` instance the service was
                constructed with.

        Returns:
            ``True`` if the connect call succeeded (linked), ``False``
            if it timed out or the substrate refused.

        Raises:
            Exception: Adapter-specific failures propagate; the
                service catches and stores them as ``last_error``.
        """
        raise NotImplementedError

    def disconnect(self):
        """Drop any active association."""
        raise NotImplementedError

    def is_linked(self):
        """Return whether the substrate currently reports an association."""
        raise NotImplementedError

    def ip(self):
        """Return the assigned IPv4 string, or ``None``."""
        raise NotImplementedError
