"""Set a volume with a rotary encoder and a brightness with a knob, on MicroPython.

Turning the encoder walks a volume number between 0 and 20, one step per
click of the shaft, and stops at either end.  Turning the potentiometer picks
a brightness from 0 to 9.  The console prints each new number once: a
potentiometer you have let go of keeps its number instead of flickering
between two.  The first line is usually the brightness, as the program reads
where the knob already sits.  The library installs the pin interrupts that
count a quick flick of the shaft between two passes of the loop.

Wiring on a Pi Pico W:

- Encoder: its two signal pins (often labelled CLK and DT, or A and B) to GP16
  and GP17, and its common pin (C or GND) to GND.  The internal pull-ups are
  switched on for you.  If the module has a ``+`` pin, wire it to 3V3.
- Potentiometer: the outer legs to 3V3 and GND, the middle leg to GP26.

On an ESP32-S2 board such as the Lolin S2 Mini, GPIO 16 and 17 work for the
encoder, and GPIO 3 for the potentiometer.  The brightness may top out below
9 there, because an ESP32's converter stops reading before 3.3 V.

Example output::

    Turn the encoder for volume.  Turn the knob for brightness.

      brightness 4
      volume 1
      volume 2
      volume 3
      brightness 5

Setup:
1. Install the libraries:
   ``mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_knobs`` and
   ``mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_timing``.
2. Copy this file to the board as ``main.py``.

The push switch built into many encoders is an ordinary button on its own pin.
Read it with ``chumicro_buttons``.

Runs on MicroPython.
"""

# ChuMicro's example tools read this line: this file needs MicroPython.
__chumicro_runtimes__ = ("micropython",)

from chumicro_knobs import AnalogKnob, Encoder
from chumicro_timing import ticks_ms
from machine import Pin

ENCODER_PIN_A = 16     # GP16 on a Pi Pico W, GPIO 16 on an ESP32-S2
ENCODER_PIN_B = 17     # GP17 on a Pi Pico W, GPIO 17 on an ESP32-S2
BRIGHTNESS_PIN = 26    # GP26 on a Pi Pico W.  3 on a Lolin S2 Mini.

# bounds holds the volume between 0 and 20.  If it takes two clicks to move
# the volume by one, your encoder sends 2 steps per click: add detent_steps=2.
volume = Encoder(Pin(ENCODER_PIN_A), Pin(ENCODER_PIN_B), bounds=(0, 20))

# steps divides the knob's travel, end to end, into 10 positions numbered 0 to 9.
brightness = AnalogKnob(Pin(BRIGHTNESS_PIN), steps=10)

print("Turn the encoder for volume.  Turn the knob for brightness.\n")

while True:
    now = ticks_ms()

    # Read both knobs.  Neither call waits.
    volume.check(now)
    brightness.check(now)

    # just_moved is True on exactly one pass per change.
    if volume.just_moved:
        print(f"  volume {volume.position}")

    if brightness.just_moved:
        print(f"  brightness {brightness.value}")

    # Nothing above waits, so code you add here runs on every pass.
