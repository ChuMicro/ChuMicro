"""Hello on a 16x2 backpacked LCD from MicroPython.

Wiring for a Pi Pico W: SDA=GP4, SCL=GP5, backpack VCC to VBUS for
full contrast, GND to GND.  Any board works with its own I2C pins;
the backpack's default address is 0x27.

Example output::

    lcd ready
"""
__chumicro_runtimes__ = ("micropython",)

from chumicro_charlcd import CharLcd, MicropythonTransport
from machine import I2C, Pin

# The PCF8574 is a 100 kHz part and machine.I2C defaults to 400 kHz on
# rp2, so the frequency is pinned rather than inherited.
bus = I2C(0, sda=Pin(4), scl=Pin(5), freq=100_000)
lcd = CharLcd(MicropythonTransport(bus))

lcd.write("chumicro charlcd", row=0)
lcd.write("hello!", row=1, column=5)
print("lcd ready")
