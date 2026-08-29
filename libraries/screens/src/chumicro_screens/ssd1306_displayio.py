"""SSD1306 on CircuitPython: the monochrome OLED via displayio.

CircuitPython renders displays in firmware: ``busdisplay.BusDisplay``
repaints changed regions from C in the background, inside the tick
budget, so ScreenService is not involved and the page-paced flush the
MicroPython driver needs has no counterpart here.  ``make_display``
feeds the panel's initialization sequence into that machinery and
returns the ``BusDisplay``; from there the app uses displayio directly:
build a ``displayio.Group``, assign it to ``root_group``, and mutate
bitmaps or palettes to draw.

One bit per pixel and a palette of two, so a ``displayio.Bitmap``
built with ``value_count=2`` and a two-entry ``displayio.Palette``
covers the panel.

The app owns the bus.  Release any prior displays, construct the I2C
bus and an ``i2cdisplaybus.I2CDisplayBus`` around it, and pass that
in::

    import board
    import busio
    import displayio
    import i2cdisplaybus
    from chumicro_screens.ssd1306_displayio import make_display

    displayio.release_displays()
    i2c = busio.I2C(board.IO35, board.IO33)
    display = make_display(i2cdisplaybus.I2CDisplayBus(i2c, device_address=0x3C))
"""

__chumicro_runtimes__ = ("circuitpython",)

WIDTH = 128
HEIGHT = 64

_PAGE_HEIGHT = 8


def _init_sequence(height: int) -> bytes:
    """Pack the power-on commands displayio replays at construction.

    The table is displayio's own format, each entry a command byte, a
    length byte, then that many data bytes.  Multiplex ratio is the row
    count less one, and the COM pin configuration selects sequential or
    alternating pins, which is the one place a 32-row panel differs
    from a 64-row one.
    """
    com_pins = 0x02 if height == 32 else 0x12
    return bytes((
        0xAE, 0x00,                 # display off while configuring
        0x20, 0x01, 0x00,           # horizontal addressing, windows auto-advance
        0x81, 0x01, 0xCF,           # contrast
        0xA1, 0x00,                 # column 0 maps to segment 127
        0xA6, 0x00,                 # normal, not inverted
        0xC8, 0x00,                 # scan rows bottom to top
        0xA8, 0x01, height - 1,     # multiplex ratio
        0xD5, 0x01, 0x80,           # default divide, ~370 kHz oscillator
        0xD9, 0x01, 0xF1,           # pre-charge period
        0xDA, 0x01, com_pins,       # COM pin configuration
        0xDB, 0x01, 0x40,           # VCOMH deselect level
        0x8D, 0x01, 0x14,           # enable the internal DC/DC
        0xAF, 0x00,                 # display on
    ))


def make_display(display_bus: object, *, width: int = WIDTH,
                 height: int = HEIGHT, rotation: int = 0,
                 auto_refresh: bool = True) -> object:
    """Build the ``busdisplay.BusDisplay`` driving an SSD1306 panel.

    The display bus is injected: the app constructs the I2C bus and
    wraps it in an ``i2cdisplaybus.I2CDisplayBus`` naming the panel's
    address, then passes that in, so this module never touches
    ``board`` or ``busio``.

    The panel differs from a color TFT in ways displayio needs told:
    one bit per pixel against a single color, bytes stacking their
    pixels down a column rather than along a row, its own column and
    page address commands, bounds that fit in single bytes, and an
    address stream where the parameters travel as commands rather than
    as data.

    Args:
        display_bus: ``i2cdisplaybus.I2CDisplayBus`` wired to the panel,
            or a ``fourwire.FourWire`` on an SPI part.
        width: Panel width in pixels.
        height: Panel height in pixels; a multiple of 8.
        rotation: Display rotation in degrees, 0, 90, 180, or 270.
        auto_refresh: Whether displayio repaints in the background.
            Pass ``False`` to refresh manually via
            ``display.refresh()``.

    Returns:
        The ``busdisplay.BusDisplay`` for the panel, ready for a
        ``root_group``.
    """
    if height % _PAGE_HEIGHT:
        raise ValueError(f"height {height} is not a multiple of 8")
    # Function-scope import: keeps the module importable on runtimes
    # without displayio, where only the constants are reachable.
    import busdisplay
    return busdisplay.BusDisplay(display_bus, _init_sequence(height),
                                 width=width, height=height,
                                 rotation=rotation,
                                 auto_refresh=auto_refresh,
                                 color_depth=1,
                                 grayscale=True,
                                 pixels_in_byte_share_row=False,
                                 set_column_command=0x21,
                                 set_row_command=0x22,
                                 data_as_commands=True,
                                 brightness_command=0x81,
                                 single_byte_bounds=True)
