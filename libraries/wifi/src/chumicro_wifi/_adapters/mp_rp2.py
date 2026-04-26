"""MicroPython Pi Pico W (CYW43 / RP2040) ``network.WLAN`` adapter.

Wraps the MP ``network.WLAN(network.STA_IF)`` station-mode handle
on the CYW43 wifi chip that the Pi Pico W (and other CYW43-based
MP boards) ships with.

**No firmware-level supervisor exists** on the CYW43 — the library
is the sole owner of reconnect by default (Decision 0029
§wifi-ownership-stance), so this adapter is simpler than the ESP32
sibling: no `wlan.config(reconnects=0)` call needed.  What it
*does* add is the **power-save knob**: `wlan.config(pm=0xa11140)`
disables CYW43's idle power-save mode, eliminating the responsiveness
hit community reports describe (~30-100 ms tick spikes on chip
wake-up).  Applied when ``WifiConfig.power_save`` is ``False``
(default); skipped when the user explicitly opts in to power-save.

Constructor injection (Decision 0010): ``wlan`` defaults to a
fresh ``network.WLAN(network.STA_IF)`` on MicroPython but accepts
an injected fake on hosts.

Shares most of its surface with :class:`MpEsp32WifiAdapter` (the
non-blocking ``connect``, ``isconnected``-driven link state, the
``ifconfig()[0]`` IP read with ``"0.0.0.0"`` post-association-
pre-DHCP sentinel handling).  Two adapters rather than one shared
class because:

* ESP32 needs the firmware-supervisor-off knob; CYW43 doesn't.
* CYW43 needs the power-save knob; ESP32 doesn't expose one at
  the same layer.
* Decisions about what ``OSError``-tolerance to extend to which
  knob are substrate-specific.

Following the per-runtime-adapter convention from the lazy-loading
research keeps each substrate's quirks in one file.
"""

#: Bundle pipeline marker — Decision 0037.  This file ships to the
#: MP-mpy bundle and the source bundle; excluded from CP-mpy.
__chumicro_runtimes__ = ("micropython",)

from chumicro_wifi._adapters.base import WifiAdapter

#: Magic value disabling CYW43 idle power-save mode.  From CYW43
#: vendor docs + community measurements; the library applies it
#: when ``WifiConfig.power_save`` is ``False`` (the default).
CYW43_PM_DISABLE = 0xA11140


class MpRp2WifiAdapter(WifiAdapter):
    """MP CYW43 (Pi Pico W et al.) ``network.WLAN`` adapter.

    Args:
        wlan: Optional WLAN substrate.  When ``None`` (default),
            constructs ``network.WLAN(network.STA_IF)`` — only
            available under MicroPython on a board with a CYW43
            chip.  Tests inject a fake matching the WLAN surface
            the adapter touches: ``active(state=None)``,
            ``connect(ssid, password)``, ``disconnect()``,
            ``isconnected()``, ``ifconfig()``,
            ``config(**kwargs)``.
    """

    name = "mp_rp2"

    def __init__(self, wlan=None):
        if wlan is None:
            wlan = self._acquire_runtime_wlan()
        self._wlan = wlan

    @staticmethod
    def _acquire_runtime_wlan():
        """Build ``network.WLAN(network.STA_IF)`` or raise a clear error."""
        try:
            import network  # pragma: no cover - MP runtime path
        except ImportError as error:
            raise RuntimeError(
                "MpRp2WifiAdapter requires MicroPython with a network module. "
                "On a host, pass `wlan=<fake>` to test the wire format."
            ) from error
        return network.WLAN(network.STA_IF)  # pragma: no cover - MP runtime path

    def configure(self, config):
        """Activate the radio + apply hostname + apply power-save knob.

        Unlike the ESP32 adapter, the power-save knob can be set at
        any time (it's stateless from the substrate's perspective —
        affects the chip's next idle window, not its current state).
        Applied here at configure time so the first link is already
        in the user's preferred mode.
        """
        self._wlan.active(True)
        if config.hostname is not None:
            try:
                self._wlan.config(dhcp_hostname=config.hostname)
            except (OSError, ValueError):
                # Some MP builds reject hostname mid-flight; tolerate
                # the failure rather than blocking deploy.
                pass
        if not config.power_save:
            try:
                self._wlan.config(pm=CYW43_PM_DISABLE)
            except (OSError, ValueError):
                # Older MP firmware may not expose the pm knob; we
                # proceed without it.  Power-save stays at the
                # firmware default — user code may notice idle
                # latency spikes but the connection still works.
                pass

    def connect(self, config):
        """Begin / drive the association via ``wlan.connect``.

        MP's ``connect`` is non-blocking — returns immediately
        after dispatching the request; ``isconnected()`` flips to
        ``True`` once the AP responds.  No firmware supervisor on
        CYW43 means we don't need a supervisor-off call (unlike
        the ESP32 adapter).
        """
        self._wlan.connect(config.ssid, config.password)
        return bool(self._wlan.isconnected())

    def disconnect(self):
        """Drop the active association.  Idempotent on the substrate."""
        self._wlan.disconnect()

    def is_linked(self):
        """``True`` while ``isconnected()`` reports an active association."""
        return bool(self._wlan.isconnected())

    def ip(self):
        """Return the IPv4 string from ``ifconfig()``, or ``None``.

        Same shape as :meth:`MpEsp32WifiAdapter.ip` — the
        substrate API is identical between the two MP wifi stacks.
        Returns ``None`` for the ``"0.0.0.0"`` post-association-
        pre-DHCP sentinel.
        """
        if not self._wlan.isconnected():
            return None
        ifconfig = self._wlan.ifconfig()
        if not ifconfig:
            return None
        address = ifconfig[0]
        if not address or address == "0.0.0.0":
            return None
        return address
