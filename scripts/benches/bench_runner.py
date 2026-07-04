"""Benches for the runner reactor loop (``chumicro_runner``).

Measures the cost of one ``tick()`` + ``wait()`` cycle — the reactor's
per-loop overhead — at 3, 10, and 30 registered no-op services.  This is
the "tick discipline" number: the reactor scans every registered service
each tick, so the per-cycle cost sets the floor under an app's tick
budget (the ≤5 ms discipline).

A no-op service's ``check(now_ms)`` returns ``True`` (so its ``handle``
is dispatched every tick) and ``handle(now_ms)`` does nothing — exercising
both the check scan and the batched-handler dispatch.  No service exposes
a socket or a deadline, so ``wait()`` syncs an empty poll set and returns
immediately (no wall-time sleep pollutes the CPU number).
"""

import sys

sys.path.insert(0, "scripts/benches")

from _harness import register  # noqa: E402
from chumicro_runner import Runner  # noqa: E402


class _NoOpService:
    """Fires every tick, does nothing — pure reactor overhead per service."""

    def check(self, now_ms):
        return True

    def handle(self, now_ms):
        pass


def _make_setup(service_count):
    def setup():
        runner = Runner()
        for _ in range(service_count):
            runner.add(_NoOpService())
        return runner

    return setup


def _tick_wait_cycle(runner):
    now_ms = runner.tick()
    runner.wait(now_ms)


for _count in (3, 10, 30):
    register(
        f"reactor_tick_{_count}svc",
        setup=_make_setup(_count),
        op=_tick_wait_cycle,
        note=f"tick()+wait() cycle, {_count} no-op services",
    )
