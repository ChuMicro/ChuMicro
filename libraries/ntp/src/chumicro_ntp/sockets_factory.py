"""Default UDP-socket wiring for :class:`NTPClient`."""

from chumicro_sockets import udp_socket


def chumicro_sockets_factory(*, radio=None) -> object:
    """Return a bound UDP socket on an ephemeral port."""
    return udp_socket(radio=radio)
