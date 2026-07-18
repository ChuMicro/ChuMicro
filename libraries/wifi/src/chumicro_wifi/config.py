"""``WifiConfig``: typed connection settings and a flat-key factory."""

from chumicro_config import load_section, try_load_section


class WifiConfig:
    """Connection configuration for ``WifiService``.

    Args:
        ssid: AP SSID to associate with.
        password: WPA passphrase.
        hostname: Hostname advertised on the AP, or ``None`` to skip it.
        connect_timeout_ms: Max wait for a single connect attempt, in ms (default 15 s).
        reconnect_backoff_start_ms: Initial delay between reconnect attempts (default 1 s).
        reconnect_backoff_max_ms: Cap on the exponential reconnect backoff (default 60 s).
        reconnect_max: Failed attempts before terminal ``FAILED``; ``None`` (default) retries forever.
        power_save: Whether to leave the radio's power-save mode enabled (default ``False``).
        tx_power_dbm: Radio transmit power in dBm, or ``None`` (default) for the firmware default.
    """

    # Flat keys read by the factory methods; keep in sync with the __init__ defaults.
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

        Args:
            config: A :class:`chumicro_config.RuntimeConfig` or plain flat dict.

        Raises:
            chumicro_config.MissingConfigKey: ``wifi.ssid`` or ``wifi.password`` is absent.
            chumicro_config.InvalidConfigType: *config* is ``None`` or not a mapping.
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

        Args:
            config: A :class:`chumicro_config.RuntimeConfig`, plain flat dict, or ``None``.

        Returns:
            A ``WifiConfig`` instance, or ``None`` when the section is not configured.
        """
        return try_load_section(
            cls,
            config,
            prefix="wifi",
            required=("ssid", "password"),
            optional=cls._OPTIONAL_DEFAULTS,
        )
