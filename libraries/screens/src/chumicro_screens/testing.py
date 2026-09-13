"""Test fakes for the chumicro-screens panel and strip protocols."""

__chumicro_test_support__ = True


class FakePanel:
    """Panel fake whose flush performs a configurable number of transfers.

    Implements the flush protocol ``ScreenService`` drives: ``flush()``
    returns an iterator and each advance performs one bus transfer.
    Counters record how the service paced the work.

    Set ``fail_on_transfer`` to an index to raise ``OSError`` in place
    of that transfer, simulating a bus fault mid-frame.

    Args:
        transfers_per_flush: Bus transfers one frame needs; the frame
            completes after that many iterator advances.
    """

    def __init__(self, transfers_per_flush: int = 1) -> None:
        self.transfers_per_flush = transfers_per_flush
        self.fail_on_transfer: int | None = None
        self.flushes_started = 0
        self.flushes_completed = 0
        self.transfers_completed = 0

    def flush(self) -> object:
        """Return the frame's transfer iterator and count the start."""
        self.flushes_started += 1
        return self._run_flush()

    def _run_flush(self) -> object:
        for transfer_index in range(self.transfers_per_flush):
            if transfer_index > 0:
                yield
            if transfer_index == self.fail_on_transfer:
                raise OSError("injected bus fault")
            self.transfers_completed += 1
        self.flushes_completed += 1


class FakeStrip:
    """Strip canvas fake that records every primitive call with the strip's ``top`` at the time.

    ``calls`` holds one tuple per call: the primitive's name, the
    ``top`` the strip had, then the arguments as given, so a test can
    assert which items painted into which band and with what.  The
    built-in font is 8 by 8, as framebuf's is.

    Args:
        width: Strip width in pixels.
        rows: Strip height in pixels.
    """

    glyph_width = 8
    glyph_height = 8

    def __init__(self, width: int = 32, rows: int = 8) -> None:
        self.width = width
        self.rows = rows
        self.top = 0
        self.calls: list = []
        self.prepared: list = []

    def clear(self, value: int) -> None:
        self.calls.append(("clear", self.top, value))

    def fill_rect(self, x: int, y: int, width: int, height: int, value: int) -> None:  # noqa: CHU001 - framebuf's own names
        self.calls.append(("fill_rect", self.top, x, y, width, height, value))

    def box(self, x: int, y: int, width: int, height: int, value: int) -> None:  # noqa: CHU001 - framebuf's own names
        self.calls.append(("box", self.top, x, y, width, height, value))

    def line(self, x0: int, y0: int, x1: int, y1: int, value: int) -> None:
        self.calls.append(("line", self.top, x0, y0, x1, y1, value))

    def prepare_ring(self, x_center: int, y_center: int, radius: int, cache: dict) -> None:
        self.prepared.append(("ring", x_center, y_center, radius))

    def ring(self, x_center: int, y_center: int, radius: int, value: int,
             cache: dict) -> None:
        self.calls.append(("ring", self.top, x_center, y_center, radius, value))

    def prepare_text(self, string: str, value: int, font: object | None, cache: list) -> None:
        self.prepared.append(("text", string, value, font))

    def text(self, string: str, x: int, y: int, value: int, font: object | None,  # noqa: CHU001 - framebuf's own names
             cache: list) -> None:
        self.calls.append(("text", self.top, string, x, y, value, font))

    def blit(self, source: object, x: int, y: int, key: int) -> None:  # noqa: CHU001 - framebuf's own names
        self.calls.append(("blit", self.top, source, x, y, key))


class FakeScreenPanel:
    """Panel fake for a ``Screen``: a ``FakeStrip`` and a record of every strip write.

    ``writes`` holds one ``(top, count)`` pair per ``write_strip`` call,
    and ``fail_on_write`` set to an index raises ``OSError`` in place of
    that write.

    Args:
        width: Panel width in pixels.
        height: Panel height in pixels.
        rows: Strip height in pixels.
    """

    def __init__(self, width: int = 32, height: int = 32, rows: int = 8) -> None:
        self.width = width
        self.height = height
        self.strip = FakeStrip(width, rows)
        self.writes: list = []
        self.fail_on_write: int | None = None

    def write_strip(self, top: int, count: int) -> None:
        if len(self.writes) == self.fail_on_write:
            raise OSError("injected bus fault")
        self.writes.append((top, count))
