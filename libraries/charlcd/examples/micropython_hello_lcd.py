"""Hello on a 16x2 backpacked LCD from MicroPython.

Wiring for a LOLIN S2 Mini: SDA=IO33, SCL=IO35, backpack VCC to 5 V
(VBUS) for full contrast, GND to GND.  Any board works with its own
I2C pins; the backpack's default address is 0x27.

Example output::

    lcd ready
"""
__chumicro_runtimes__ = ("micropython",)

from chumicro_charlcd import CharLcd, MicropythonTransport
from machine import I2C, Pin

bus = I2C(0, sda=Pin(33), scl=Pin(35))
lcd = CharLcd(MicropythonTransport(bus))

lcd.write("chumicro charlcd", row=0)
lcd.write("hello!", row=1, column=5)
print("lcd ready")
