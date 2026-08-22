"""Test-support helpers: a hand-turned :class:`FakeEncoderSource` and :class:`FakeAnalogSource`."""

__chumicro_test_support__ = True


class FakeEncoderSource:
    """Quadrature source a test turns by hand instead of by wrist.

    ``turn`` moves it by whole detents, which is what the runtime sources publish once they
    have divided the quadrature steps down.  Several turns before one tick add up.

    Args:
        raw_position: Detent count the source starts from.
    """

    def __init__(self, raw_position: int = 0) -> None:
        self.raw_position = raw_position
        #: How many times a knob asked this source to capture.
        self.poll_calls = 0
        #: Tick of the last capture, which proves the knob passes the loop's timestamp down.
        self.last_poll_ms = 0
        #: How many times a knob released this source.
        self.deinit_calls = 0

    def turn(self, detents: int) -> None:
        """Move the shaft ``detents`` clicks, negative for the other direction."""
        self.raw_position += detents

    def poll(self, now_ms: int) -> None:
        """Record that a capture step was asked for; the count is moved by the test."""
        self.poll_calls += 1
        self.last_poll_ms = now_ms

    def deinit(self) -> None:
        """Record that the knob released this source."""
        self.deinit_calls += 1


class FakeAnalogSource:
    """Converter a test sets a reading on instead of turning a wiper.

    ``set_raw`` takes the 0 to 65535 scale every runtime reports on, so small moves between
    ticks exercise the deadband.

    Args:
        raw: Reading the source starts from.
    """

    def __init__(self, raw: int = 0) -> None:
        self.raw = raw
        #: How many times a knob asked this source to convert.
        self.poll_calls = 0
        #: Tick of the last conversion, which proves the knob passes the loop's timestamp down.
        self.last_poll_ms = 0
        #: How many times a knob released this source.
        self.deinit_calls = 0

    def set_raw(self, raw: int) -> None:
        """Park the wiper at ``raw`` on the 0 to 65535 scale."""
        self.raw = raw

    def poll(self, now_ms: int) -> None:
        """Record that a conversion was asked for; the reading is set by the test."""
        self.poll_calls += 1
        self.last_poll_ms = now_ms

    def deinit(self) -> None:
        """Record that the knob released this source."""
        self.deinit_calls += 1
