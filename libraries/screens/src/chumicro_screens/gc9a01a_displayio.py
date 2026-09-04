"""GC9A01A on CircuitPython: the 240x240 round color TFT via displayio.

CircuitPython renders displays in firmware: ``busdisplay.BusDisplay``
repaints changed regions from C in the background, so ScreenService is
not involved.  The repaint runs from the firmware's background hook and
stalls the app loop for the whole transfer, so a 5 ms tick budget does
not hold under ``auto_refresh``; an app that needs the budget passes
``auto_refresh=False`` and calls ``display.refresh()`` from a handler
of its own choosing.  ``make_display`` feeds the panel's initialization
sequence into that machinery and returns the ``BusDisplay``; from there
the app uses displayio directly: build a ``displayio.Group``, assign it
to ``root_group``, and mutate bitmaps or palettes to draw.

The app owns the bus.  Release any prior displays, construct the SPI
bus and a ``fourwire.FourWire`` around it, and pass the FourWire in.
The numbers are MCU GPIO numbers, which ``chumicro_compat.wiring``
resolves; a hand-built ``busio.SPI`` and ``board`` pins work too::

    import displayio
    import fourwire
    from chumicro_compat.wiring import gpio_pin, spi_bus
    from chumicro_screens.gc9a01a_displayio import make_display

    displayio.release_displays()
    spi = spi_bus(1, sck=7, mosi=11)
    display = make_display(fourwire.FourWire(
        spi, command=gpio_pin(9), chip_select=gpio_pin(12),
        reset=gpio_pin(5), baudrate=40_000_000))
"""

__chumicro_runtimes__ = ("circuitpython",)

WIDTH = 240
HEIGHT = 240

_INIT_SEQUENCE = (
    b"\xfe\x00"
    b"\xef\x00"
    b"\xb6\x02\x00\x00"
    b"\x36\x01\x48"
    b"\x3a\x01\x05"
    b"\xc3\x01\x13"
    b"\xc4\x01\x13"
    b"\xc9\x01\x22"
    b"\xf0\x06\x45\x09\x08\x08\x26\x2a"
    b"\xf1\x06\x43\x70\x72\x36\x37\x6f"
    b"\xf2\x06\x45\x09\x08\x08\x26\x2a"
    b"\xf3\x06\x43\x70\x72\x36\x37\x6f"
    b"\x66\x0a\x3c\x00\xcd\x67\x45\x45\x10\x00\x00\x00"
    b"\x67\x0a\x00\x3c\x00\x00\x00\x01\x54\x10\x32\x98"
    b"\x74\x07\x10\x85\x80\x00\x00\x4e\x00"
    b"\x98\x02\x3e\x07"
    b"\x35\x00"
    b"\x21\x00"
    b"\x11\x80\x78"
    b"\x29\x80\x14"
)


def make_display(display_bus: object, *, rotation: int = 0,
                 auto_refresh: bool = True) -> object:
    """Build the ``busdisplay.BusDisplay`` driving a GC9A01A panel.

    Args:
        display_bus: ``fourwire.FourWire`` wired to the panel.
        rotation: Display rotation in degrees, 0, 90, 180, or 270.
        auto_refresh: Whether displayio repaints in the background.
            Pass ``False`` to refresh manually via
            ``display.refresh()``.

    Returns:
        The ``busdisplay.BusDisplay`` for the panel, ready for a
        ``root_group``.
    """
    # Function-scope import: keeps the module importable on runtimes
    # without displayio.
    import busdisplay
    return busdisplay.BusDisplay(display_bus, _INIT_SEQUENCE,
                                 width=WIDTH, height=HEIGHT,
                                 rotation=rotation,
                                 auto_refresh=auto_refresh)
