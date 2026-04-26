"""Application entrypoint for this thing.

The on-device boot module imports ``things.<name>.app`` and calls
``run()``.  Anything ``app.py`` does at import time runs on every
boot before ``run()`` is called — keep heavyweight setup inside
``run()`` so a slow init doesn't trip the boot watchdog.
"""


def run() -> None:
    """Main loop / one-shot for this thing."""
    print("hello from a ChuMicro thing")
