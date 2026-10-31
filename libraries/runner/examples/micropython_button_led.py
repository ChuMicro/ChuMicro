"""Toggle the built-in LED each time you press a button.

Every press flips the LED and prints a line on the serial console.  Holding
the button down counts as one press.  The program keeps watching the button
forever.

``ButtonToggle`` is a service: the runner calls ``check()`` every 20 ms to
ask "was the button just pressed?", and calls ``handle()`` to flip the LED
only when the answer is yes.  Reading the button every 20 ms also debounces
it: a switch stops bouncing well inside that window, so one press reads as
one press.

Setup:
1. Install ``chumicro_runner`` and ``chumicro_timing`` on the board
   (``mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_runner``,
   or copy both packages into ``lib/``).
2. The defaults suit most ESP32 dev boards: GPIO 0 is the BOOT button and
   pin 2 is the built-in LED, so nothing needs wiring.  On another board,
   wire a push button between a GPIO pin and GND and set ``BUTTON_PIN`` to
   it; set ``LED_PIN`` to your LED (``"LED"`` on a Pico W).
3. Save this file as ``main.py`` on the board.

Example output::

    Press the button to toggle the LED.
    press 1: LED on
    press 2: LED off
    press 3: LED on
    ...

Runs on MicroPython.
"""

#: MicroPython-only.  Uses ``machine.Pin`` (MP API).
#: Pair: ``circuitpython_button_led.py`` for the CP equivalent (``board`` + ``digitalio``).
__chumicro_runtimes__ = ("micropython",)

from chumicro_runner import Runner
from machine import Pin

BUTTON_PIN = 0   # the BOOT button on most ESP32 dev boards
LED_PIN = 2      # the built-in LED on most ESP32 dev boards

led = Pin(LED_PIN, Pin.OUT)
button = Pin(BUTTON_PIN, Pin.IN, Pin.PULL_UP)   # reads 0 while the button is held


class ButtonToggle:
    """Flip the LED once per button press."""

    def __init__(self) -> None:
        self.was_pressed = False
        self.presses = 0

    def check(self, now_ms: int) -> bool:
        """Return ``True`` only on the read where the button goes from up to down.

        The runner passes ``now_ms``, the time of the current tick in
        milliseconds.  This service has no use for it.
        """
        pressed = not button.value()
        just_pressed = pressed and not self.was_pressed
        self.was_pressed = pressed
        return just_pressed

    def handle(self, now_ms: int) -> None:
        """Flip the LED and print the press count."""
        led.value(not led.value())
        self.presses += 1
        state = "on" if led.value() else "off"
        print(f"press {self.presses}: LED {state}")


runner = Runner()
runner.add(ButtonToggle(), period_ms=20)   # read the button every 20 ms

print("Press the button to toggle the LED.")

while True:
    now_ms = runner.tick()   # check every service that is due right now
    runner.wait(now_ms)      # sleep until the next button read is due
