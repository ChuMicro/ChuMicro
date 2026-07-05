"""``WifiConfig``: typed connection settings + flat-key factory.

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
            ``connect()`` attempt to complete.  Optional,
            defaults to 15 s.  On CircuitPython the CP adapter passes
            it to ``radio.connect(timeout=...)`` (a blocking wait); on
            MicroPython the service uses it as the in-flight association
            window — after the non-blocking ``wlan.connect()`` dispatch
            it polls ``isconnected()`` until this deadline before
            counting the attempt as failed.
        reconnect_backoff_start_ms: Initial delay between
            reconnect attempts after a link drop.  Optional,
            defaults to 1 s.
        reconnect_backoff_max_ms: Cap on the exponential
            reconnect backoff.  Optional, defaults to 60 s.
        reconnect_max: Maximum number of consecutive failed attempts —
            counting the initial connect plus every reconnect since the
            last successful link — before the service enters the
            terminal ``FAILED`` state.  ``None`` (default) means
            unlimited: the service retries forever with capped backoff
            and never gives up, which is what lets an unattended device
            ride out an outage and re-establish the link with no board
            restart.  Set a finite cap only when a caller wants
            exhaustion to escalate (e.g. to a hardware watchdog reset or
            deep-sleep) — ``FAILED`` is terminal, so nothing in the
            service leaves it, and recovery then needs a board restart or
            a fresh ``WifiService``.  Because the count includes the
            initial connect, a low cap can fail permanently in the
            power-restore race where the board boots faster than the AP.
            Leave it ``None`` for always-on devices.
        power_save: Whether to leave the radio's power-save mode
            enabled.  ``False`` (default) disables power-save on
            backends that support it (Pi Pico W CYW43), and is
            ignored on backends that don't expose the knob.
        tx_power_dbm: Radio transmit power, in dBm.  ``None``
            (default) leaves the radio at its firmware default — the
            library never imposes a power.  Set a reduced value (e.g.
            ``15``) for boards that are unstable at full TX power: on
            CircuitPython the CP adapter applies it via
            ``wifi.radio.tx_power`` and on MicroPython the MP adapter
            via ``sta.config(txpower=...)``, both before the connect
            attempt.  A build that doesn't expose the knob ignores it
            and stays at its default power.  The canonical use case is
            Unexpected Maker P4-revision ESP32-S3 boards, which are
            vendor-documented unstable at full 20 dBm; the deployer
            sets this in config for those boards — the library carries
            no board-specific knowledge.
    """

    #: Optional flat keys read by ``from_config`` / ``try_from_config``,
    #: mapped to their default when absent.  Kept in sync with the
    #: ``__init__`` signature defaults.  The signature stays the
    #: documentation surface for direct construction.
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
                not a mapping.  Use :meth:`try_from_config` for the
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
        """Soft-load a ``WifiConfig``, returning ``None`` when not configured.

        Returns ``None`` whenever :meth:`from_config` would raise:
        *config* is ``None``, *config* isn't a mapping, or any required
        ``wifi.*`` key is missing.

        Use this as a "skip if not configured" gate in app or test
        code::

            from chumicro_config import config
            from chumicro_wifi import WifiConfig, WifiService

            wifi_cfg = WifiConfig.try_from_config(config)
            if wifi_cfg is None:
                return  # not configured, skip / use defaults
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
