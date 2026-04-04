"""Device-facing tests for the cross-runtime timing helpers."""

import time

from chumicro_timing.ticks import ticks_diff, ticks_ms


def _sleep_ms(duration_ms):
	"""Sleep for the requested duration using the best available runtime API."""
	runtime_sleep_ms = getattr(time, "sleep_ms", None)
	if callable(runtime_sleep_ms):
		runtime_sleep_ms(duration_ms)
		return

	time.sleep(duration_ms / 1000)


def test_ticks_progress_on_runtime():
	"""The active runtime should expose forward-moving monotonic ticks."""
	start_ms = ticks_ms()
	_sleep_ms(20)
	end_ms = ticks_ms()

	assert ticks_diff(end_ms, start_ms) >= 1

