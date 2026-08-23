"""Press a button while the board is busy fetching, and lose nothing.

This is the file that runs on the board.  It joins wifi, then fetches a
web page every few seconds, forever.  A button rides the same loop, and
a press lands whenever it happens, mid-fetch included: the edge is
captured by hardware underneath the loop, so the hold you read is
measured from the moment your finger landed, not from whenever the loop
got around to noticing.

What you will see::

    WIFI_OK ip=10.0.0.42
    FETCHED status=200 bytes=49
    FETCHED status=200 bytes=49
    PRESS count=1
    RELEASE held_ms=142
    DEMO_COMPLETE
    FETCHED status=200 bytes=49

Nothing stops after DEMO_COMPLETE.  The fetches keep coming and the
button keeps working, which is the point.

The UPPERCASE lines are for the script running on your laptop, which
reads them to follow how far the board got.  They are ordinary ``print``
calls in the ``NAME key=value`` shape.

Two things worth trying:

* Hold the button across a whole fetch and watch ``held_ms`` come back
  longer than the fetch took.
* Unplug your router mid-run.  The fetches turn into FETCH_FAILED lines
  and keep retrying; your presses keep landing exactly as before.
"""

from chumicro_buttons import Button
from chumicro_config import load_runtime_config
from chumicro_requests.generators import get
from chumicro_runner import Runner
from chumicro_runner.generators import sleep_until
from chumicro_sockets.sockets_factory import connector_factory
from chumicro_timing import ticks
from chumicro_timing.waits import Signal, wait_for
from chumicro_wifi import WifiConfig, WifiService, WifiState


def fetch_forever(wifi, link_up, url):
    """Fetch the page every three seconds, forever.

    Each ``yield from`` is a place this pauses and the rest of the board
    runs, the button included.
    """
    yield from wait_for(link_up)
    print(f"WIFI_OK ip={wifi.ip}")

    factory = connector_factory(radio=wifi.adapter.radio)
    while True:
        try:
            response = yield from get(factory, url)
            print(f"FETCHED status={response.status_code} "
                  f"bytes={len(response.body)}")
        except Exception as error:
            print(f"FETCH_FAILED error={type(error).__name__}")
        yield from sleep_until(ticks.ticks_add(ticks.ticks_ms(), 3000))


def announce_press():
    """Runs the tick a press lands, however busy the fetch is."""
    global press_count
    press_count += 1
    print(f"PRESS count={press_count}")


def announce_release():
    """Reports how long the press was held, measured from its edge."""
    print(f"RELEASE held_ms={button.held_ms}")
    if press_count == 1:
        print("DEMO_COMPLETE")


def report_fault(entry, error):
    """Runs if a service raises.  The loop keeps going; this says so."""
    print(f"SERVICE_FAULT service={type(entry.service).__name__} "
          f"error={type(error).__name__}")
    print(f"  detail: {error!r}")


def signal_link_up(_old, new):
    """Tells the fetch it can start."""
    if new == WifiState.CONNECTED:
        link_up.set(new)


config = load_runtime_config()

# MicroPython names a pin by its number; CircuitPython by a board attribute.
pin_name = config["buttons.demo.pin"]
try:
    from machine import Pin
    button_pin = Pin(int(pin_name))
except ImportError:
    import board
    button_pin = getattr(board, pin_name)

press_count = 0
button = Button(pin=button_pin, ticks=ticks)
button.on_press = announce_press
button.on_release = announce_release

wifi = WifiService(WifiConfig.from_config(config))
link_up = Signal()
wifi.on_state_change(signal_link_up)

runner = Runner(on_handler_error=report_fault)
runner.add(wifi)
runner.add(button)
runner.add_generator(fetch_forever(wifi, link_up, config["requests.fetch.url"]))

# The main loop.  tick() gives every registered service one small step,
# and wait() then parks the CPU until the next event or timer deadline;
# the button publishes its timers, so even a long press fires on time.
# It never ends, which is what a board program does.  Your own project's
# loop looks exactly like this one.
while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
