"""Cross-runtime tests for ``Screen`` and its items over the fakes in ``chumicro_screens.testing``.

The fake strip records every primitive call with the band it was
painted in, and the fake panel records every strip write, so the
asserts read which bands a flush painted, in what order, with which
items, and what each item asked the strip to draw.
"""

from chumicro_screens import Box, Line, Rect, Ring, Screen, ScreenService, Sprite, Text
from chumicro_screens.testing import FakeScreenPanel
from chumicro_timing.testing import FakeTicks


def drain(screen: Screen) -> int:
    """Run one whole flush and return how many advances it took."""
    advances = 0
    flush = screen.flush()
    if flush is None:
        return 0
    while True:
        try:
            next(flush)
        except StopIteration:
            return advances
        advances += 1


def calls(panel: FakeScreenPanel, name: str) -> list:
    """The recorded strip calls of one primitive."""
    return [call for call in panel.strip.calls if call[0] == name]


def test_a_new_screen_flushes_nothing() -> None:
    panel = FakeScreenPanel()
    screen = Screen(panel)

    assert drain(screen) == 0
    assert panel.writes == []


def test_add_paints_only_the_bands_the_item_covers() -> None:
    """A 4-row rectangle at rows 10 to 14 paints the second band alone, cleared first."""
    panel = FakeScreenPanel(width=32, height=32, rows=8)
    screen = Screen(panel, background=3)
    screen.add(Rect(2, 10, 5, 4, 9))

    assert drain(screen) == 1
    assert panel.writes == [(8, 8)]
    assert panel.strip.calls == [("clear", 8, 3), ("fill_rect", 8, 2, 10, 5, 4, 9)]


def test_an_item_across_a_band_edge_paints_both_bands() -> None:
    panel = FakeScreenPanel(width=32, height=32, rows=8)
    screen = Screen(panel)
    screen.add(Rect(0, 6, 4, 4, 1))

    assert drain(screen) == 2
    assert panel.writes == [(0, 8), (8, 8)]
    assert [call[1] for call in calls(panel, "fill_rect")] == [0, 8]


def test_items_paint_in_the_order_added_and_only_where_they_cross_the_band() -> None:
    panel = FakeScreenPanel(width=32, height=32, rows=8)
    screen = Screen(panel)
    screen.add(Rect(0, 0, 32, 32, 1))
    screen.add(Rect(0, 24, 8, 8, 2))
    screen.add(Line(0, 0, 4, 4, 3))
    drain(screen)

    band_calls = [call for call in panel.strip.calls if call[1] == 24 and call[0] != "clear"]
    assert band_calls == [("fill_rect", 24, 0, 0, 32, 32, 1), ("fill_rect", 24, 0, 24, 8, 8, 2)]
    first_band = [call for call in panel.strip.calls if call[1] == 0 and call[0] != "clear"]
    assert first_band == [("fill_rect", 0, 0, 0, 32, 32, 1), ("line", 0, 0, 0, 4, 4, 3)]


def test_mark_repaints_where_the_item_was_and_where_it_is() -> None:
    """Moving a rectangle from the first band to the last repaints both, not the bands between."""
    panel = FakeScreenPanel(width=32, height=32, rows=8)
    screen = Screen(panel)
    rect = Rect(0, 0, 4, 4, 1)
    screen.add(rect)
    drain(screen)
    del panel.writes[:]
    del panel.strip.calls[:]

    rect.y = 28
    screen.mark(rect)
    drain(screen)

    assert panel.writes == [(0, 8), (8, 8), (16, 8), (24, 8)]
    assert [call[1] for call in calls(panel, "fill_rect")] == [24]


def test_remove_repaints_where_the_item_was_painted() -> None:
    panel = FakeScreenPanel(width=32, height=32, rows=8)
    screen = Screen(panel)
    rect = Rect(0, 16, 4, 4, 1)
    screen.add(rect)
    drain(screen)
    del panel.writes[:]

    painted = len(calls(panel, "fill_rect"))
    screen.remove(rect)
    drain(screen)

    assert panel.writes == [(16, 8)]
    assert len(calls(panel, "fill_rect")) == painted


def test_mark_all_paints_every_band_including_a_short_last_one() -> None:
    panel = FakeScreenPanel(width=32, height=20, rows=8)
    screen = Screen(panel)
    screen.mark_all()

    assert drain(screen) == 3
    assert panel.writes == [(0, 8), (8, 8), (16, 4)]


def test_bounds_outside_the_panel_clip_and_an_empty_mark_is_ignored() -> None:
    panel = FakeScreenPanel(width=32, height=32, rows=8)
    screen = Screen(panel)
    screen.add(Rect(-10, -10, 4, 4, 1))
    assert drain(screen) == 0

    screen.add(Rect(30, 30, 40, 40, 1))
    assert panel.writes == []
    assert drain(screen) == 1
    assert panel.writes == [(24, 8)]


def test_a_flush_clears_the_dirty_rectangle_so_the_next_is_empty() -> None:
    panel = FakeScreenPanel()
    screen = Screen(panel)
    screen.add(Rect(0, 0, 4, 4, 1))
    drain(screen)

    assert drain(screen) == 0


def test_a_failed_write_propagates_and_the_next_flush_starts_clean() -> None:
    panel = FakeScreenPanel(width=32, height=32, rows=8)
    panel.fail_on_write = 1
    screen = Screen(panel)
    screen.mark_all()
    flush = screen.flush()
    next(flush)
    try:
        next(flush)
    except OSError:
        pass
    else:
        raise AssertionError("the injected fault did not propagate")

    assert drain(screen) == 0


def test_screen_service_drives_a_screen_one_band_per_handle() -> None:
    panel = FakeScreenPanel(width=32, height=32, rows=8)
    screen = Screen(panel)
    service = ScreenService(screen, refresh_interval_ms=0, ticks=FakeTicks())
    screen.mark_all()
    service.show()

    for tick in range(4):
        assert service.check(tick)
        service.handle(tick)
    assert panel.writes == [(0, 8), (8, 8), (16, 8), (24, 8)]
    assert service.check(4)
    service.handle(4)
    assert not service.check(5)


def test_rect_box_line_and_ring_bounds() -> None:
    strip = FakeScreenPanel().strip
    rect = Rect(2, 3, 4, 5, 1)
    rect.layout(strip)
    assert (rect.left, rect.top, rect.right, rect.bottom) == (2, 3, 6, 8)
    box = Box(2, 3, 4, 5, 1)
    box.layout(strip)
    assert (box.left, box.top, box.right, box.bottom) == (2, 3, 6, 8)
    line = Line(9, 1, 2, 7, 1)
    line.layout(strip)
    assert (line.left, line.top, line.right, line.bottom) == (2, 1, 10, 8)
    ring = Ring(10, 12, 4, 1)
    ring.layout(strip)
    assert (ring.left, ring.top, ring.right, ring.bottom) == (6, 8, 15, 17)


def test_ring_and_text_layout_prepare_their_strip_pieces() -> None:
    panel = FakeScreenPanel()
    screen = Screen(panel)
    ring = Ring(10, 12, 4, 1)
    text = Text(1, 2, "hi", 1)
    screen.add(ring)
    screen.add(text)

    assert panel.strip.prepared == [("ring", 10, 12, 4), ("text", "hi", 1, None)]


def test_text_bounds_come_from_the_strip_font_or_the_given_font() -> None:
    strip = FakeScreenPanel().strip

    class WideFont:
        height = 20

        def width(self, string):
            return 11 * len(string)

    built_in = Text(3, 4, "abc", 1)
    built_in.layout(strip)
    assert (built_in.right, built_in.bottom) == (3 + 24, 4 + 8)
    proportional = Text(3, 4, "abc", 1, WideFont())
    proportional.layout(strip)
    assert (proportional.right, proportional.bottom) == (3 + 33, 4 + 20)


def test_items_draw_through_the_strip_primitives() -> None:
    panel = FakeScreenPanel()
    strip = panel.strip
    strip.top = 8
    source = object()
    for item in (Rect(1, 9, 2, 3, 4), Box(1, 9, 2, 3, 4), Line(0, 8, 3, 11, 5),
                 Ring(5, 12, 2, 6), Text(1, 9, "x", 7), Sprite(2, 10, source, 3, 3, 0)):
        item.draw(strip)

    assert strip.calls == [
        ("fill_rect", 8, 1, 9, 2, 3, 4),
        ("box", 8, 1, 9, 2, 3, 4),
        ("line", 8, 0, 8, 3, 11, 5),
        ("ring", 8, 5, 12, 2, 6),
        ("text", 8, "x", 1, 9, 7, None),
        ("blit", 8, source, 2, 10, 0),
    ]


def test_sprite_bounds_are_its_size() -> None:
    sprite = Sprite(4, 5, object(), 6, 7)
    sprite.layout(FakeScreenPanel().strip)
    assert (sprite.left, sprite.top, sprite.right, sprite.bottom) == (4, 5, 10, 12)
    assert sprite.key == -1
