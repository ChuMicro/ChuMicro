"""Spread a frame's flush across loop passes with ScreenService.

ConsolePanel stands in for a real display driver: each advance of its
flush iterator "transfers" one row by printing it, the way a real
driver sends one page or strip per advance.  The loop draws a frame,
marks it with ``show()``, and stays responsive while the flush
progresses one row per pass.

Example output::

    row 0 -> hello
    loop pass 0 advanced the flush
    row 1 -> from chumicro-screens
    loop pass 1 advanced the flush
    row 2 -> one row per pass
    loop pass 2 advanced the flush
    loop pass 3 free for other work
    loop pass 4 free for other work
"""

from chumicro_screens import ScreenService
from chumicro_timing import ticks_ms


class ConsolePanel:
    """Panel whose flush prints one row of text per iterator advance."""

    def __init__(self) -> None:
        self.rows = ["", "", ""]

    def flush(self) -> object:
        """Return an iterator that transfers one row per advance."""
        for row_index in range(len(self.rows)):
            if row_index > 0:
                yield
            print("row", row_index, "->", self.rows[row_index])


panel = ConsolePanel()
screen = ScreenService(panel, refresh_interval_ms=0)

panel.rows[0] = "hello"
panel.rows[1] = "from chumicro-screens"
panel.rows[2] = "one row per pass"
screen.show()

loop_pass = 0
while loop_pass < 5:
    now_ms = ticks_ms()
    if screen.check(now_ms):
        screen.handle(now_ms)
        print("loop pass", loop_pass, "advanced the flush")
    else:
        print("loop pass", loop_pass, "free for other work")
    loop_pass += 1
