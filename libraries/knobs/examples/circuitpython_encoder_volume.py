"""A rotary encoder for volume and a potentiometer for brightness, on CircuitPython.

Turning the encoder walks a volume figure between 0 and 20 and stops at either
end, so the number never runs off into nonsense.  The potentiometer reports a
brightness step out of 10, held still by the deadband so a parked wiper stops
reporting a new number every pass of the loop.

Setup:
1. Install ``chumicro_knobs`` (``circup install chumicro_knobs``).
2. Wire the encoder's two signal pins to the chosen GPIOs and its common pin to
   **GND**.  The internal pull-ups are switched on for you.  On RP2040 boards the
   two signal pins must be **next to each other** in GPIO numbering.
3. Wire the potentiometer's outer legs to **3V3** and **GND**, and its wiper to
   an analog-capable pin such as ``board.A0``.
4. Save this file as ``code.py`` on the board.

The push switch built into most encoders is a button on its own pin.  Read it
with a button library alongside this one; it has nothing to do with the shaft.

Example output::

    Turn the encoder for volume.  Turn the pot for brightness.

      volume 3
      volume 4
      brightness 7
      volume 5

Runs on CircuitPython.
"""

#: CircuitPython-only.  Uses ``board`` (CP API).
#: Pair: ``micropython_encoder_volume.py`` for the MP equivalent.
__chumicro_runtimes__ = ("circuitpython",)

import board
from chumicro_knobs import AnalogKnob, Encoder
from chumicro_timing import ticks_ms

# Set these to the pin attributes on the `board` module for your wiring.
ENCODER_PIN_A = "GP16"
ENCODER_PIN_B = "GP17"
BRIGHTNESS_PIN = "A0"

volume = Encoder(
    getattr(board, ENCODER_PIN_A),
    getattr(board, ENCODER_PIN_B),
    bounds=(0, 20),
)
brightness = AnalogKnob(getattr(board, BRIGHTNESS_PIN), steps=10)

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
