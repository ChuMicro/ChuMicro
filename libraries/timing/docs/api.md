# API Reference

## `chumicro_timing.ticks`

Wrap-safe millisecond arithmetic.  `ticks_ms()` reads the runtime's own counter, and `ticks_diff` and `ticks_add` compare and advance those readings correctly across a rollover.

::: chumicro_timing.ticks

## `chumicro_timing.deadline`

The value objects re-exported from `chumicro_timing`: `Deadline` (a single armed timeout) and `Rate` (a drift-free periodic cadence).

::: chumicro_timing.deadline

## `chumicro_timing.waits`

The completion-wait vocabulary for generator flows: `Signal` connects a callback-style service to a generator task, and `wait_for` suspends the generator until the signal is set or its deadline passes.  Import it explicitly from `chumicro_timing.waits`.

::: chumicro_timing.waits

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing) · \
[PyPI](https://pypi.org/project/chumicro-timing/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
