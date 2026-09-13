"""Hello on a 16x2 backpacked LCD from MicroPython.

Wiring for a Pi Pico W: SDA=GP4, SCL=GP5, backpack VCC to VBUS for
full contrast, GND to GND.  For a LOLIN S2 Mini use SDA=IO33,
SCL=IO35 and VCC to 5 V.  The backpack's default address is 0x27, and
its SDA and SCL lines want 4.7 kOhm pull-ups to 3V3 if the board does
not carry them.

Example output::

    lcd ready
"""
__chumicro_runtimes__ = ("micropython",)

from chumicro_charlcd import CharLcd, MicroPythonTransport
from chumicro_compat.wiring import i2c_bus

# The PCF8574 is a 100 kHz part, so the bus is pinned there rather than
# left at the 400 kHz default.
bus = i2c_bus(0, scl=5, sda=4, frequency=100_000)
lcd = CharLcd(MicroPythonTransport(bus))

lcd.write("chumicro charlcd", row=0)
lcd.write("hello!", row=1, column=5)
print("lcd ready")
