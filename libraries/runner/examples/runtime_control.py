"""Change jobs while they run: speed one up, run one once, remove another.

For the first 10 s the program logs a reading every second and checks the
Wi-Fi every 2 s.  At 10 s a one-shot job switches to fast mode: logging
speeds up to every 250 ms and the Wi-Fi check goes away.  Fast logging then
carries on forever.

Each ``add_periodic`` call returns a ``TaskHandle`` for its job.  Keep it,
and you can change the job later: ``set_period()`` gives it a new period and
``remove()`` takes it off the runner.  ``run_count=1`` registers a job that
runs once and then removes itself.

Setup:
1. Install ``chumicro_runner`` and ``chumicro_timing``.
2. Run ``python runtime_control.py`` on your computer, or save this file as
   ``code.py`` (CircuitPython) or ``main.py`` (MicroPython) on a board.

Example output::

    Logging every 1 s, Wi-Fi check every 2 s...
    logged a reading
    logged a reading
    Wi-Fi: connected
    logged a reading
    logged a reading
    Wi-Fi: connected
    ...
    >> fast mode: logging every 250 ms, Wi-Fi check removed
    logged a reading
    logged a reading
    logged a reading
    ...

Runs on CPython, MicroPython, and CircuitPython.
"""

from chumicro_runner import Runner


def log_reading(now_ms: int) -> None:
    """Print a log line."""
    print("logged a reading")


def check_wifi(now_ms: int) -> None:
    """Print a pretend Wi-Fi status line."""
    print("Wi-Fi: connected")


def switch_to_fast_mode(now_ms: int) -> None:
    """Speed up logging and drop the Wi-Fi check.

    ``now_ms`` is the time of the current tick in milliseconds.  Passing it to
    ``set_period()`` counts the new 250 ms from this tick.
    """
    print(">> fast mode: logging every 250 ms, Wi-Fi check removed")
    log_job.set_period(250, now_ms)
    wifi_job.remove()


runner = Runner()
log_job = runner.add_periodic(log_reading, period_ms=1000)
wifi_job = runner.add_periodic(check_wifi, period_ms=2000)
runner.add_periodic(switch_to_fast_mode, period_ms=10000, run_count=1)   # once, at 10 s

print("Logging every 1 s, Wi-Fi check every 2 s...")

while True:
    now_ms = runner.tick()   # run every job that is due right now
    runner.wait(now_ms)      # sleep until the next job is due
