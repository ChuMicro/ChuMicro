"""``WifiConfig`` — typed connection settings + flat-key factory.

Reads from the flat-key runtime config produced by
``chumicro_workspace.compose_runtime_config``: keys ``wifi.ssid``,
``wifi.password``, ``wifi.hostname``, etc. live at the top of the
flat dict, joined to their values by dots.
"""

from chumicro_config import load_section, try_load_section


class WifiConfig:
    """Connection configuration for ``WifiService``.

    Args:
        ssid: AP SSID to associate with.  Required.
        password: WPA passphrase.  Required.
        hostname: Hostname advertised on the AP.  Optional.
        connect_timeout_ms: Maximum wait for a single
            ``connect()`` attempt to complete.  Optional;
            defaults to 15 s.
        reconnect_backoff_start_ms: Initial delay between
            reconnect attempts after a link drop.  Optional;
            defaults to 1 s.
        reconnect_backoff_max_ms: Cap on the exponential
            reconnect backoff.  Optional; defaults to 60 s.
        reconnect_max: Maximum number of reconnect attempts before
            entering ``FAILED``.  ``None`` (default) means
            unlimited.
        power_save: Whether to leave the radio's power-save mode
            enabled.  ``False`` (default) disables power-save on
            backends that support it (Pi Pico W CYW43); ignored
            on backends that don't expose the knob.
    """

    #: Optional flat keys read by ``from_config`` / ``try_from_config``,
    #: mapped to their default when absent.  Kept in sync with the
    #: ``__init__`` signature defaults; the signature stays the
    #: documentation surface for direct construction.
    _OPTIONAL_DEFAULTS = {
        "hostname": None,
        "connect_timeout_ms": 15_000,
        "reconnect_backoff_start_ms": 1_000,
        "reconnect_backoff_max_ms": 60_000,
        "reconnect_max": None,
        "power_save": False,
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
    ) -> None:
        self.ssid = ssid
        self.password = password
        self.hostname = hostname
        self.connect_timeout_ms = connect_timeout_ms
        self.reconnect_backoff_start_ms = reconnect_backoff_start_ms
        self.reconnect_backoff_max_ms = reconnect_backoff_max_ms
        self.reconnect_max = reconnect_max
        self.power_save = power_save

    @classmethod
    def from_config(cls, config: object) -> "WifiConfig":
        """Build a ``WifiConfig`` from the flat runtime config.

        Reads ``wifi.ssid`` / ``wifi.password`` (required) plus any
        present ``wifi.<optional>`` keys from *config*.  Delegates to
        ``chumicro_config.load_section`` for uniform missing-required /
        missing-optional / non-dict semantics.

        Args:
            config: A :class:`chumicro_config.RuntimeConfig` (typically
                ``chumicro_config.config``) or plain flat dict.

        Raises:
            chumicro_config.MissingConfigKey: ``wifi.ssid`` or
                ``wifi.password`` is absent from *config*.
            chumicro_config.InvalidConfigType: *config* is ``None`` or
                not a mapping — use :meth:`try_from_config` for the
                soft path.
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
        """Soft-load a ``WifiConfig`` — return ``None`` when not configured.

        Returns ``None`` whenever :meth:`from_config` would raise:
        *config* is ``None``, *config* isn't a mapping, or any required
        ``wifi.*`` key is missing.

        Use this as a "skip if not configured" gate in app or test
        code::

            from chumicro_config import config
            from chumicro_wifi import WifiConfig, WifiService

            wifi_cfg = WifiConfig.try_from_config(config)
            if wifi_cfg is None:
                return  # not configured — skip / use defaults
            service = WifiService(wifi_cfg)

        Args:
            config: A :class:`chumicro_config.RuntimeConfig`, plain
                flat dict, or ``None``.

        Returns:
            A ``WifiConfig`` instance, or ``None`` if any short-circuit
            "skip" path fires.
        """
        return try_load_section(
            cls,
            config,
            prefix="wifi",
            required=("ssid", "password"),
            optional=cls._OPTIONAL_DEFAULTS,
        )
