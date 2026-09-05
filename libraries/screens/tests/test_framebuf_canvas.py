"""Host-lane tests for ``chumicro_screens.framebuf_canvas.FramebufCanvas``.

Runs on CPython and both unix ports.  Where the runtime ships
``framebuf`` (the MicroPython port) the real C class is subclassed and
draws, which is the path a board takes; elsewhere the shared stub
stands in.  Every assert reads the bounds the canvas recorded and the
indexes framebuf left in an 8-bit frame.
"""

__chumicro_host_only__ = True

import array
import sys

from _screen_stubs import FramebufStub

try:
    import framebuf
except ImportError:
    framebuf = FramebufStub()
    sys.modules["framebuf"] = framebuf

from chumicro_screens.framebuf_canvas import FramebufCanvas  # noqa: E402

WIDTH = 20
HEIGHT = 8


def make_canvas() -> tuple:
    buffer = bytearray(WIDTH * HEIGHT)
    return FramebufCanvas(buffer, WIDTH, HEIGHT, framebuf.GS8), buffer


def drained() -> tuple:
    """A canvas whose construction-time dirt has been taken, as after a first flush."""
    canvas, buffer = make_canvas()
    canvas.take_dirty()
    return canvas, buffer


def test_a_new_canvas_is_wholly_dirty_until_taken() -> None:
    """Construction dirties the whole frame once; a second take finds nothing."""
    canvas, _ = make_canvas()
    assert (canvas.width, canvas.height) == (WIDTH, HEIGHT)
    assert canvas.take_dirty() == (0, 0, WIDTH, HEIGHT)
    assert canvas.take_dirty() is None


def test_fill_rect_records_its_clipped_bounds_and_draws() -> None:
    """A rectangle past the top-left corner records and draws its visible part only."""
    canvas, buffer = drained()
    canvas.fill_rect(-5, -5, 10, 10, 3)
    assert canvas.take_dirty() == (0, 0, 5, 5)
    assert buffer[0] == 3
    assert buffer[4 * WIDTH + 4] == 3
    assert buffer[5] == 0
    assert buffer[5 * WIDTH] == 0
    canvas.fill_rect(18, 6, 50, 50, 2)
    assert canvas.take_dirty() == (18, 6, WIDTH, HEIGHT)
    canvas.fill_rect(30, 30, 2, 2, 2)
    canvas.fill_rect(1, 1, 0, 4, 2)
    assert canvas.take_dirty() is None


def test_fill_and_scroll_dirty_the_whole_frame() -> None:
    """fill and scroll touch every pixel and say so."""
    canvas, buffer = drained()
    canvas.fill(4)
    assert canvas.take_dirty() == (0, 0, WIDTH, HEIGHT)
    assert buffer[WIDTH * HEIGHT - 1] == 4
    canvas.pixel(0, 0, 9)
    canvas.take_dirty()
    canvas.scroll(1, 0)
    assert canvas.take_dirty() == (0, 0, WIDTH, HEIGHT)
    assert buffer[1] == 9


def test_pixel_write_records_one_pixel_and_a_read_records_nothing() -> None:
    """A set pixel dirties its own cell; reads and out-of-range writes dirty nothing."""
    canvas, buffer = drained()
    canvas.pixel(3, 4, 7)
    assert canvas.take_dirty() == (3, 4, 4, 5)
    assert canvas.pixel(3, 4) == 7
    assert buffer[4 * WIDTH + 3] == 7
    assert canvas.take_dirty() is None
    canvas.pixel(WIDTH, 0, 7)
    canvas.pixel(0, -1, 7)
    assert canvas.take_dirty() is None
    assert canvas.pixel(WIDTH, 0) is None


def test_the_line_helpers_and_rect_record_their_extent() -> None:
    """hline, vline, an outline rect, and a reversed diagonal each record the pixels they span."""
    canvas, buffer = drained()
    canvas.hline(2, 3, 5, 1)
    assert canvas.take_dirty() == (2, 3, 7, 4)
    assert buffer[3 * WIDTH + 6] == 1
    assert buffer[3 * WIDTH + 7] == 0
    canvas.vline(9, 1, 4, 1)
    assert canvas.take_dirty() == (9, 1, 10, 5)
    canvas.rect(10, 2, 4, 3, 1)
    assert canvas.take_dirty() == (10, 2, 14, 5)
    assert buffer[2 * WIDTH + 13] == 1
    assert buffer[3 * WIDTH + 11] == 0
    canvas.line(6, 6, 1, 1, 1)
    assert canvas.take_dirty() == (1, 1, 7, 7)
    assert buffer[1 * WIDTH + 1] == 1
    assert buffer[6 * WIDTH + 6] == 1


def test_ellipse_and_poly_record_their_bounding_boxes() -> None:
    """An ellipse records its radii box and a polygon its points' box, both clipped."""
    canvas, buffer = drained()
    canvas.ellipse(10, 4, 4, 3, 1)
    assert canvas.take_dirty() == (6, 1, 15, 8)
    assert buffer[4 * WIDTH + 6] == 1
    assert buffer[4 * WIDTH + 14] == 1
    assert buffer[1 * WIDTH + 10] == 1
    assert buffer[7 * WIDTH + 10] == 1
    assert buffer[4 * WIDTH + 10] == 0
    canvas.ellipse(2, 2, 6, 6, 2)
    assert canvas.take_dirty() == (0, 0, 9, HEIGHT)
    canvas.poly(5, 2, array.array("h", [0, 0, 4, 0, 4, 4]), 3)
    assert canvas.take_dirty() == (5, 2, 10, 7)
    assert buffer[2 * WIDTH + 7] == 3
    assert buffer[6 * WIDTH + 9] == 3


def test_blit_records_the_source_size_from_a_canvas_or_a_list() -> None:
    """A canvas source and framebuf's list-form source both dirty the pasted rectangle."""
    canvas, buffer = drained()
    sprite = FramebufCanvas(bytearray(b"\x05\x06\x07\x08"), 2, 2, framebuf.GS8)
    canvas.blit(sprite, 3, 3)
    assert canvas.take_dirty() == (3, 3, 5, 5)
    assert buffer[3 * WIDTH + 3] == 5
    assert buffer[4 * WIDTH + 4] == 8
    glyph = [b"\xc0\x40\x40", 2, 3, framebuf.MONO_HLSB]
    canvas.blit(glyph, 18, 6, 0)
    assert canvas.take_dirty() == (18, 6, WIDTH, HEIGHT)
    assert buffer[6 * WIDTH + 18] == 1
    assert buffer[6 * WIDTH + 19] == 1
    assert buffer[7 * WIDTH + 18] == 0
    assert buffer[7 * WIDTH + 19] == 1
    canvas.blit(sprite, -1, -1)
    assert canvas.take_dirty() == (0, 0, 1, 1)
    assert buffer[0] == 8
    canvas.blit(sprite, WIDTH, 0)
    assert canvas.take_dirty() is None


def test_a_bare_framebuffer_source_dirties_to_the_far_edges() -> None:
    """framebuf reports no size for a bare FrameBuffer, so its blit dirties from (x, y) onward."""
    canvas, buffer = drained()
    plain = framebuf.FrameBuffer(bytearray(b"\x09\x09"), 2, 1, framebuf.GS8)
    canvas.blit(plain, 4, 2)
    assert canvas.take_dirty() == (4, 2, WIDTH, HEIGHT)
    assert buffer[2 * WIDTH + 5] == 9


def test_text_records_eight_pixel_cells() -> None:
    """Two characters dirty a 16 by 8 block, clipped at the right edge."""
    canvas, buffer = drained()
    canvas.text("AB", 5, 1, 2)
    assert canvas.take_dirty() == (5, 1, WIDTH, HEIGHT)
    cell = [buffer[row * WIDTH + column] for row in range(1, HEIGHT) for column in range(5, 13)]
    assert 2 in cell


def test_drawing_unions_and_dirty_marks_by_hand() -> None:
    """Several primitives union into one box, and dirty() marks a region drawn behind the canvas's back."""
    canvas, buffer = drained()
    canvas.pixel(2, 6, 1)
    canvas.hline(10, 1, 3, 1)
    assert canvas.take_dirty() == (2, 1, 13, 7)
    buffer[7 * WIDTH + 19] = 4
    canvas.dirty(19, 7, 1, 1)
    assert canvas.take_dirty() == (19, 7, WIDTH, HEIGHT)
    canvas.dirty(-3, -3, 2, 2)
    assert canvas.take_dirty() is None


def test_the_canvas_is_a_framebuf_source_through_a_palette() -> None:
    """A strip blits a canvas row through a palette, which is what the panel's flush does."""
    canvas, _ = make_canvas()
    canvas.pixel(1, 1, 3)
    palette = framebuf.FrameBuffer(bytearray(256 * 2), 256, 1, framebuf.RGB565)
    palette.pixel(3, 0, 0xABCD)
    strip_buffer = bytearray(WIDTH * 2)
    strip = framebuf.FrameBuffer(strip_buffer, WIDTH, 1, framebuf.RGB565)
    strip.blit(canvas, 0, -1, -1, palette)
    assert bytes(strip_buffer[:4]) == b"\x00\x00\xcd\xab"
