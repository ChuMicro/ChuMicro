"""Default UDP-socket wiring for :class:`NTPClient`.

Opt-in submodule: the package's ``__init__.py`` does not import it, so
users who bring their own UDP socket never pull :mod:`chumicro_sockets`
into the deploy graph.
"""

from chumicro_sockets import udp_socket


def chumicro_sockets_factory(*, radio=None) -> object:
    """Return a bound UDP socket on an ephemeral port."""
    return udp_socket(radio=radio)
