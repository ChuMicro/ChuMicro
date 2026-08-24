"""Drive CharLcd against a recording transport and decode the traffic.

No hardware: the recording transport captures every raw PCF8574 byte
and the testing decoder folds the enable pulses back into HD44780
commands, which is also how downstream tests assert display behavior.

Example output::

    write('Hi', row=1) sent:
      command 0xc0
      data    0x48
      data    0x69
    backlight off byte: 0x00
"""
from chumicro_charlcd import CharLcd
from chumicro_charlcd.testing import RecordingTransport, decode_bytes

transport = RecordingTransport()
sleeps = []
lcd = CharLcd(transport, sleep_ms=sleeps.append)

del transport.raw[:]
lcd.write("Hi", row=1)

print("write('Hi', row=1) sent:")
for register_select, value in decode_bytes(transport.raw):
    kind = "data   " if register_select else "command"
    print(f"  {kind} 0x{value:02x}")

del transport.raw[:]
lcd.backlight = False
print(f"backlight off byte: 0x{transport.raw[0]:02x}")
