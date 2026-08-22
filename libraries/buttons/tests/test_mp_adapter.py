"""Host-lane tests for the MicroPython adapter's module surface.

The capture sources here need ``machine.Pin`` and a real interrupt, so their
behaviour is covered by ``functional_tests/`` on a board.  What a host can check is
the ring depth the capture handler is sized against, which is a plain constant and
the one number a caller may want to raise for a panel that bounces hard.

The module is MicroPython-marked, so a CircuitPython deploy never carries it; this
file stays on the host lane where importing it always resolves.
"""

#: Host-lane only: imports a MicroPython-marked module, which a CircuitPython
#: deploy does not carry.  Never staged to a device.
__chumicro_host_only__ = True

from chumicro_buttons._adapters.mp import DEFAULT_RING_DEPTH


def test_the_capture_ring_holds_a_full_press_and_release_of_bounce() -> None:
    """The default ring is 32 slots, enough for both bounce bursts of one tap."""
    assert DEFAULT_RING_DEPTH == 32
