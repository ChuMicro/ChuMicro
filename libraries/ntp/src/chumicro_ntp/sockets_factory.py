"""Default UDP-socket wiring for :class:`NTPClient`.

Opt-in submodule — the package's ``__init__.py`` does not import it,
so users who pass their own UDP socket never pull
:mod:`chumicro_sockets` into the deploy graph.
"""

from chumicro_sockets import udp_socket


def chumicro_sockets_factory(*, radio=None) -> object:
    """Return a bound UDP socket on an ephemeral port.

    Wires :func:`chumicro_sockets.udp_socket`.  Apps that need
    ``SO_BROADCAST`` (e.g. LAN server discovery, which NTP itself
    doesn't need) call :func:`chumicro_sockets.udp_socket` with
    ``broadcast=True`` directly.
    """
    return udp_socket(radio=radio)
