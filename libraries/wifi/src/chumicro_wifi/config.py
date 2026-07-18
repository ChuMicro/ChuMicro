"""``WifiConfig``: typed connection settings and a flat-key factory.

Reads the flat runtime config where dotted keys ``wifi.ssid``,
``wifi.password``, ``wifi.hostname`` and the like map to their values.
"""

from chumicro_config import load_section, try_load_section


class WifiConfig:
    """Connection configuration for ``WifiService``.

    Args:
        ssid: AP SSID to associate with. Required.
        password: WPA passphrase. Required.
        hostname: Hostname advertised on the AP, or ``None`` to skip it.
        connect_timeout_ms: Maximum wait for a single ``connect()``
            attempt, in milliseconds. Defaults to 15 s.
        reconnect_backoff_start_ms: Initial delay between reconnect
            attempts after a link drop. Defaults to 1 s.
        reconnect_backoff_max_ms: Cap on the exponential reconnect
            backoff. Defaults to 60 s.
        reconnect_max: Consecutive failed attempts (the initial connect
            plus every reconnect since the last link) before the service
            enters the terminal ``FAILED`` state. ``None`` (default)
            retries forever with capped backoff, which is what lets an
            unattended device ride out an outage without a board restart.
            Set a finite cap only when exhaustion should escalate, since
            ``FAILED`` is terminal and recovery then needs a restart.
        power_save: Whether to leave the radio's power-save mode enabled.
            ``False`` (default) disables it on backends that support the
            knob (Pi Pico W CYW43) and is ignored on backends that don't.
        tx_power_dbm: Radio transmit power in dBm, or ``None`` (default)
            to leave the radio at its firmware default. Set a reduced
            value (e.g. ``15``) for boards unstable at full TX power; the
            adapter applies it before the connect attempt, and a build
            without the knob ignores it.
    """

    #: Optional flat keys read by ``from_config`` / ``try_from_config``,
    #: mapped to their default when absent. Kept in sync with the
    #: ``__init__`` signature defaults.
    _OPTIONAL_DEFAULTS = {
        "hostname": None,
        "connect_timeout_ms": 15_000,
        "reconnect_backoff_start_ms": 1_000,
        "reconnect_backoff_max_ms": 60_000,
        "reconnect_max": None,
        "power_save": False,
        "tx_power_dbm": None,
    }

    def __init__(
        self,
        ssid: str,
        password: str,
        hostname: str | None = None,
        connect_timeout_ms: int = 15_000,
        reconnect_backoff_start_ms: int = 1_000,
        reconnect_backoff_max_ms: int = 60_000,
        reconnect_max: int | None = None,
        power_save: bool = False,
        tx_power_dbm: int | None = None,
    ) -> None:
        self.ssid = ssid
        self.password = password
        self.hostname = hostname
        self.connect_timeout_ms = connect_timeout_ms
        self.reconnect_backoff_start_ms = reconnect_backoff_start_ms
        self.reconnect_backoff_max_ms = reconnect_backoff_max_ms
        self.reconnect_max = reconnect_max
        self.power_save = power_save
        self.tx_power_dbm = tx_power_dbm

    @classmethod
    def from_config(cls, config: object) -> "WifiConfig":
        """Build a ``WifiConfig`` from the flat runtime config.

        Reads ``wifi.ssid`` and ``wifi.password`` (required) plus any
        present optional ``wifi.*`` keys from *config*.

        Args:
            config: A :class:`chumicro_config.RuntimeConfig` (typically
                ``chumicro_config.config``) or plain flat dict.

        Raises:
            chumicro_config.MissingConfigKey: ``wifi.ssid`` or
                ``wifi.password`` is absent from *config*.
            chumicro_config.InvalidConfigType: *config* is ``None`` or
                not a mapping. Use :meth:`try_from_config` for the soft
                path.
        """
        return load_section(
            cls,
            config,
            prefix="wifi",
            required=("ssid", "password"),
            optional=cls._OPTIONAL_DEFAULTS,
        )

    @classmethod
    def try_from_config(cls, config: object) -> "WifiConfig | None":
        """Soft-load a ``WifiConfig``, returning ``None`` when not configured.

        Returns ``None`` whenever :meth:`from_config` would raise:
        *config* is ``None``, isn't a mapping, or is missing a required
        ``wifi.*`` key. Use it as a "skip if not configured" gate.

        Args:
            config: A :class:`chumicro_config.RuntimeConfig`, plain flat
                dict, or ``None``.

        Returns:
            A ``WifiConfig`` instance, or ``None`` when the section is
            not configured.
        """
        return try_load_section(
            cls,
            config,
            prefix="wifi",
            required=("ssid", "password"),
            optional=cls._OPTIONAL_DEFAULTS,
        )
