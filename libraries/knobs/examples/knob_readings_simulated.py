"""A rotary encoder and a potentiometer on a laptop, with no board attached.

Drives an ``Encoder`` and an ``AnalogKnob`` from the hand-driven sources the
library's own tests use, so this runs the identical code path a real board
takes.  Watch the encoder count detents and then stop dead at the top of its
range, and watch the deadband hold the analog reading still while the raw
number underneath keeps wandering.

It also writes out the two-step contract a runner uses: ``check`` folds the
new readings in and reports whether anything happened, ``handle`` calls the
callbacks that news earned.

This is how you write knob logic before the hardware arrives, and how you keep
testing it afterwards without turning a shaft ten thousand times.

Example output::

    Simulated knob readings...

      volume  3  (+3)
      volume  5  (+2)
      volume  9  (+4)
      volume 10  (+1)
      brightness  6  (raw 20000)
      volume  9  (-1)
      brightness 13  (raw 45000)

Runs on CPython.
"""

#: CPython-only.  Uses the test-support fakes in place of real pins.
#: Pair: ``circuitpython_encoder_volume.py`` / ``micropython_encoder_volume.py``
#: for the same two knobs on real hardware.
__chumicro_runtimes__ = ("cpython",)

from chumicro_knobs import AnalogKnob, Encoder
from chumicro_knobs.testing import FakeAnalogSource, FakeEncoderSource

shaft = FakeEncoderSource()
wiper = FakeAnalogSource()

volume = Encoder(source=shaft, bounds=(0, 10))
brightness = AnalogKnob(source=wiper, steps=20)


def volume_changed(detents: int) -> None:
    """Print where the volume landed and how many detents moved it there."""
    print(f"  volume {volume.position:2d}  ({detents:+d})")


def brightness_changed(step: int) -> None:
    """Print the step the knob settled on and the raw reading behind it."""
    print(f"  brightness {step:2d}  (raw {brightness.raw})")


volume.on_change = volume_changed
brightness.on_change = brightness_changed

# What the hands do, tick by tick: detents turned, and where the wiper sits.
# The 20120 and 19900 readings are the converter wandering under a still wiper.
TURNS = (0, 3, 2, 4, 4, 0, -1, 0, 0, 0)
WIPER_READINGS = (0, 0, 0, 0, 0, 20000, 20120, 19900, 45000, 45050)
TICK_STEP_MS = 20

print("Simulated knob readings...\n")

tick_index = 0
while tick_index < len(TURNS):
    now_ms = tick_index * TICK_STEP_MS
    shaft.turn(TURNS[tick_index])
    wiper.set_raw(WIPER_READINGS[tick_index])

    if volume.check(now_ms):
        volume.handle(now_ms)
    if brightness.check(now_ms):
        brightness.handle(now_ms)

    tick_index += 1
