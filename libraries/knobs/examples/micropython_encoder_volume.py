"""A rotary encoder for volume and a potentiometer for brightness, on MicroPython.

Turning the encoder walks a volume figure between 0 and 20 and stops at either
end, so the number never runs off into nonsense.  The potentiometer reports a
brightness step out of 10, held still by the deadband so a parked wiper stops
reporting a new number every pass of the loop.

The library installs the quadrature interrupt for you.  A quick flick of the
shaft between two passes of this loop is still counted, which is the part that
is easy to get wrong by hand.

Setup:
1. Install ``chumicro_knobs``
   (``mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_knobs``).
2. Wire the encoder's two signal pins to the chosen GPIOs and its common pin to
   **GND**.  The internal pull-ups are switched on for you.
3. Wire the potentiometer's outer legs to **3V3** and **GND**, and its wiper to
   an analog-capable pin such as GPIO 26.
4. Copy this file to the board as ``main.py``.

The push switch built into most encoders is a button on its own pin.  Read it
with a button library alongside this one; it has nothing to do with the shaft.

Example output::

    Turn the encoder for volume.  Turn the pot for brightness.

      volume 3
      volume 4
      brightness 7
      volume 5

Runs on MicroPython.
"""

#: MicroPython-only.  Uses ``machine.Pin`` (MP API).
#: Pair: ``circuitpython_encoder_volume.py`` for the CP equivalent.
__chumicro_runtimes__ = ("micropython",)

from chumicro_knobs import AnalogKnob, Encoder
from chumicro_timing import ticks_ms
from machine import Pin

# Set these to the GPIO numbers your knobs are wired to.
ENCODER_PIN_A = 16
ENCODER_PIN_B = 17
BRIGHTNESS_PIN = 26

volume = Encoder(Pin(ENCODER_PIN_A), Pin(ENCODER_PIN_B), bounds=(0, 20))
brightness = AnalogKnob(Pin(BRIGHTNESS_PIN), steps=10)

print("Turn the encoder for volume.  Turn the pot for brightness.\n")

while True:
    now = ticks_ms()
    volume.check(now)
    brightness.check(now)

    if volume.just_moved:
        print(f"  volume {volume.position}")

    if brightness.just_moved:
        print(f"  brightness {brightness.value}")

    # Everything else your device does goes here, one small step at a time.
