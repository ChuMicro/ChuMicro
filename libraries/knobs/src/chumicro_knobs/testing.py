"""Host-test helpers: ``FakeEncoderSource`` and ``FakeAnalogSource``, knob sources a test moves by hand."""

__chumicro_test_support__ = True


class FakeEncoderSource:
    """An encoder source for host tests, turned by the test in place of a shaft.

    Pass it as ``Encoder(source=FakeEncoderSource())``, call ``turn``, then call the
    encoder's ``check(now_ms)``.  ``turn`` counts whole detents, the unit the real sources
    report.  Several turns before one ``check`` add up.

    Args:
        raw_position: The detent count the source starts at.

    Attributes:
        raw_position: Detents turned since the source was built, which ``turn`` changes.
        poll_calls: How many times an encoder asked the source to capture.
        last_poll_ms: The ``now_ms`` of the last capture request.
        deinit_calls: How many times an encoder released the source.
    """

    def __init__(self, raw_position: int = 0) -> None:
        self.raw_position = raw_position
        self.poll_calls = 0
        self.last_poll_ms = 0
        self.deinit_calls = 0

    def turn(self, detents: int) -> None:
        """Turn the shaft ``detents`` clicks, negative for the other direction."""
        self.raw_position += detents

    def poll(self, now_ms: int) -> None:
        """Count the call in ``poll_calls`` and keep ``now_ms`` in ``last_poll_ms``."""
        self.poll_calls += 1
        self.last_poll_ms = now_ms

    def deinit(self) -> None:
        """Count the call in ``deinit_calls``."""
        self.deinit_calls += 1


class FakeAnalogSource:
    """An analog source for host tests, set by the test in place of a wiper.

    Pass it as ``AnalogKnob(source=FakeAnalogSource())``, call ``set_raw``, then call the
    knob's ``check(now_ms)``.  ``set_raw`` takes the 0 to 65535 scale the real sources
    report, so a small move between checks exercises the deadband.

    Args:
        raw: The reading the source starts at.

    Attributes:
        raw: The current reading, which ``set_raw`` changes.
        poll_calls: How many times a knob asked the source to convert.
        last_poll_ms: The ``now_ms`` of the last conversion request.
        deinit_calls: How many times a knob released the source.
    """

    def __init__(self, raw: int = 0) -> None:
        self.raw = raw
        self.poll_calls = 0
        self.last_poll_ms = 0
        self.deinit_calls = 0

    def set_raw(self, raw: int) -> None:
        """Move the wiper to ``raw`` on the 0 to 65535 scale."""
        self.raw = raw

    def poll(self, now_ms: int) -> None:
        """Count the call in ``poll_calls`` and keep ``now_ms`` in ``last_poll_ms``."""
        self.poll_calls += 1
        self.last_poll_ms = now_ms

    def deinit(self) -> None:
        """Count the call in ``deinit_calls``."""
        self.deinit_calls += 1
