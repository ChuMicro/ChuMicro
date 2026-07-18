"""``WifiAdapter``: the contract every concrete wifi adapter satisfies.

Adapters wrap the runtime's wifi stack (``wifi.radio`` on CircuitPython,
``network.WLAN`` on MicroPython); ``WifiService`` drives them and users
never touch them directly.
"""


class WifiAdapter:
    """Concrete adapters inherit this and override its members.

    A plain class rather than a ``Protocol`` because MicroPython has no
    ``typing`` module for library code to import.
    """

    name = "base"

    #: Whether :meth:`connect` blocks until the association resolves
    #: (``True``, CircuitPython) or dispatches a non-blocking join that
    #: ``is_linked`` reports later (``False``, MicroPython). ``WifiService``
    #: reads this to tell a settled failure from an attempt still in flight.
    connect_blocks = True

    #: Runtime-specific radio handle, meaningful only on CircuitPython where
    #: downstream libraries route a ``radio=`` argument through the socketpool.
    #: ``None`` on MicroPython / CPython so ``wifi.adapter.radio`` reads
    #: uniformly across runtimes.
    radio = None

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
            ``True`` if the connect call succeeded (linked), ``False`` if
            it timed out or the substrate refused.

        Raises:
            Exception: Adapter-specific failures propagate. The service
                catches and stores them as ``last_error``.
        """
        raise NotImplementedError

    def is_linked(self):
        raise NotImplementedError

    def ip(self):
        raise NotImplementedError
