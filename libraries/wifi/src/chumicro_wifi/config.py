"""``WifiConfig`` holds the network credentials and retry timing that ``WifiService`` uses."""


class WifiConfig:
    """``WifiConfig`` holds the network name, password, and retry timing for ``WifiService``.

    Build one directly, or load one from deployed settings with
    ``from_config``.  Each argument stays readable as an attribute of the same
    name.

    Args:
        ssid: Name of the network to join.
        password: WPA passphrase for that network.
        hostname: Name the board announces to the network, or ``None`` to keep
            the firmware's name.
        connect_timeout_ms: Time one join attempt gets, in ms.  On
            CircuitPython each attempt holds the main loop for up to this long.
        first_connect_timeout_ms: Time the first join attempt gets, in ms, or
            ``None`` to use ``connect_timeout_ms``.  A radio's first join after
            power-up takes longer than later ones.
        reconnect_backoff_start_ms: Pause after the first failed attempt, in
            ms.  Each further failure doubles the pause.
        reconnect_backoff_max_ms: Longest pause between attempts, in ms.
        reconnect_max: Failed attempts in a row after which the service stops
            in ``WifiState.FAILED``, or ``None`` to retry forever.
        power_save: ``False`` turns the radio's power-save mode off on
            MicroPython.  ``True`` leaves the firmware setting.  CircuitPython
            ignores it.
        tx_power_dbm: Transmit power in dBm, or ``None`` for the firmware
            default.  A board without the setting ignores it.
    """

    # Flat keys read by the factory methods; keep in sync with the __init__ defaults.
    _OPTIONAL_DEFAULTS = {
        "hostname": None,
        "connect_timeout_ms": 15_000,
        "first_connect_timeout_ms": None,
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
        first_connect_timeout_ms: int | None = None,
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
        self.first_connect_timeout_ms = first_connect_timeout_ms
        self.reconnect_backoff_start_ms = reconnect_backoff_start_ms
        self.reconnect_backoff_max_ms = reconnect_backoff_max_ms
        self.reconnect_max = reconnect_max
        self.power_save = power_save
        self.tx_power_dbm = tx_power_dbm

    @classmethod
    def from_config(cls, config: object) -> "WifiConfig":
        """Build a ``WifiConfig`` from the ``wifi.*`` keys of deployed settings.

        ``wifi.ssid`` and ``wifi.password`` are required.  Every other
        argument reads the key of the same name, such as
        ``wifi.connect_timeout_ms``, and falls back to the constructor default.

        Args:
            config: Flat settings dict or ``chumicro_config.RuntimeConfig``.

        Returns:
            The loaded ``WifiConfig``.

        Raises:
            chumicro_config.MissingConfigKey: ``wifi.ssid`` or ``wifi.password`` is absent.
            chumicro_config.InvalidConfigType: ``config`` is ``None``, or
                neither a dict nor a ``RuntimeConfig``.
        """
        from chumicro_config import (
            load_section,  # noqa: PLC0415 - lazy: keeps chumicro_config off deploys that construct WifiConfig directly
        )

        return load_section(
            cls,
            config,
            prefix="wifi",
            required=("ssid", "password"),
            optional=cls._OPTIONAL_DEFAULTS,
        )

    @classmethod
    def try_from_config(cls, config: object) -> "WifiConfig | None":
        """Return the ``WifiConfig`` that ``from_config`` builds, or ``None`` when wifi is not configured.

        Args:
            config: Flat settings dict, ``chumicro_config.RuntimeConfig``, or ``None``.

        Returns:
            The loaded ``WifiConfig``, or ``None`` when ``config`` lacks
                ``wifi.ssid`` or ``wifi.password``, or is neither a dict nor a
                ``RuntimeConfig``.
        """
        from chumicro_config import (
            try_load_section,  # noqa: PLC0415 - lazy: keeps chumicro_config off deploys that construct WifiConfig directly
        )

        return try_load_section(
            cls,
            config,
            prefix="wifi",
            required=("ssid", "password"),
            optional=cls._OPTIONAL_DEFAULTS,
        )
