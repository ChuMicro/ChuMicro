"""Test-support helpers: a hand-turned :class:`FakeEncoderSource` and :class:`FakeAnalogSource`."""

__chumicro_test_support__ = True


class FakeEncoderSource:
    """Quadrature source a test turns by hand instead of by wrist.

    Turn it, then tick the encoder.  ``turn`` moves it by whole detents, which is what
    the runtime sources publish once they have divided the quadrature steps down:

        source = FakeEncoderSource()
        encoder = Encoder(source=source)
        source.turn(3)
        encoder.check(0)
        assert encoder.position == 3

    Several turns before one tick add up, which is how a test reproduces a fast spin
    during a loop that stalled.

    Args:
        raw_position: Detent count the source starts from.
    """

    def __init__(self, raw_position: int = 0) -> None:
        self.raw_position = raw_position
        #: How many times a knob asked this source to capture.
        self.poll_calls = 0
        #: Tick the last capture step was asked for, so a test can prove the knob hands
        #: the loop's shared timestamp down rather than fetching one of its own.
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

    Set the reading on the 0 to 65535 scale every runtime reports on, then tick the
    knob.  Small moves are how a test proves the deadband is doing its job:

        source = FakeAnalogSource()
        knob = AnalogKnob(source=source)
        source.set_raw(32768)
        knob.check(0)
        assert knob.value == 50

    Args:
        raw: Reading the source starts from.
    """

    def __init__(self, raw: int = 0) -> None:
        self.raw = raw
        #: How many times a knob asked this source to convert.
        self.poll_calls = 0
        #: Tick the last conversion was asked for, so a test can prove the knob hands the
        #: loop's shared timestamp down rather than fetching one of its own.
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
