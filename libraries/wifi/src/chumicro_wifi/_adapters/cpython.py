"""Host adapter: stands in for a radio when the app runs on CPython."""

__chumicro_runtimes__ = ("cpython",)

from chumicro_wifi._adapters.base import WifiAdapter


class CpythonWifiAdapter(WifiAdapter):
    """Reports success immediately: the operating system owns real
    networking on a host, so there is no radio to drive and the loopback
    address stands in for an assigned IP."""

    name = "cpython"

    def __init__(self, *, ip="127.0.0.1"):
        self._ip = ip
        self._linked = False

    def configure(self, config):
        return None

    def connect(self, config):
        self._linked = True
        return True

    def is_linked(self):
        return self._linked

    def ip(self):
        return self._ip if self._linked else None
