"""Default UDP-socket wiring for ``chumicro-ntp``.

Lives in its own submodule so callers with a custom UDP transport
never trigger the ``chumicro-sockets`` deploy.  Decision 0042
"core infrastructure" sub-rule: factory helpers must be importable
*only* by users who opt into the default wiring.

Import explicitly when you want the default::

    from chumicro_ntp import NTPClient
    from chumicro_ntp.sockets_factory import chumicro_sockets_factory

    sock = chumicro_sockets_factory()
    client = NTPClient(socket=sock, server="pool.ntp.org")

The deploy-graph walker only enters this module when the app
references ``chumicro_ntp.sockets_factory`` — apps that pass their
own UDP socket to ``NTPClient`` skip this import path entirely and
``chumicro-sockets`` never reaches their device.
"""

from chumicro_sockets import udp_socket


def chumicro_sockets_factory(*, radio=None, broadcast: bool = False) -> object:
    """Return a UDP socket wired through ``chumicro-sockets``.

    Args:
        radio: CP-only radio object.  Defaults to ``wifi.radio`` on CP
            (auto-detected); ignored on MP and CPython.  Pass explicitly
            for multi-radio prototypes or boards without a ``wifi`` module.
        broadcast: Set ``SO_BROADCAST`` on the underlying socket.
            Off by default — NTP doesn't need it.  Enable when
            building "discover any server on the LAN" patterns.

    Returns:
        A bound UDP socket on an ephemeral port, ready to pass to
        :class:`chumicro_ntp.NTPClient`.
    """
    return udp_socket(radio=radio, broadcast=broadcast)
