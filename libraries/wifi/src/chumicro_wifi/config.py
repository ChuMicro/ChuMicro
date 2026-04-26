"""``WifiConfig`` — typed connection settings + ``from_dict`` factory.

The required / optional vocabulary is duplicated between ``__init__``
parameter defaults and ``from_dict``'s call: both construction paths
(direct kwargs in tests, dict-based in production) must agree, and
writing them twice is clearer than deriving one from the other.
"""

from chumicro_config import load_section


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
    def from_dict(cls, data: dict) -> "WifiConfig":
        """Build a ``WifiConfig`` from a section dict.

        Delegates to ``chumicro_config.load_section`` for uniform
        missing-required / missing-optional / non-dict semantics.

        Args:
            data: The ``"wifi"`` section dict, typically
                ``config["wifi"]`` from
                :func:`chumicro_config.load_runtime_config`.
        """
        return load_section(
            cls,
            data,
            required=("ssid", "password"),
            optional={
                "hostname": None,
                "connect_timeout_ms": 15_000,
                "reconnect_backoff_start_ms": 1_000,
                "reconnect_backoff_max_ms": 60_000,
                "reconnect_max": None,
                "power_save": False,
            },
        )
