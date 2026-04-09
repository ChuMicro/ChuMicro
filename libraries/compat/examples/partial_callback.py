"""Wire a callback with frozen context using partial.

A common embedded pattern: bind a hardware pin or device reference
into a callback so the handler doesn't need global state.  The
runner or scheduler passes the remaining arguments at call time.

Example output::

    button on pin 0 pressed at 1000 ms
    button on pin 4 pressed at 2500 ms

Runs on CPython, MicroPython, and CircuitPython.
"""

from chumicro_compat.functools import partial


def on_button_press(pin_number: int, event_ms: int) -> None:
    """Handle a button press on *pin_number* at *event_ms*.

    Args:
        pin_number: GPIO pin that triggered the event.
        event_ms: Tick value when the press occurred.
    """
    print(f"button on pin {pin_number} pressed at {event_ms} ms")


# Create one handler per button, freezing the pin number.
# In a real project these would be registered with a runner.
handle_button_0 = partial(on_button_press, 0)
handle_button_4 = partial(on_button_press, 4)

# Simulate the runner calling each handler with a timestamp.
handle_button_0(1000)
handle_button_4(2500)
