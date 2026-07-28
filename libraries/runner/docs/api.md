# API Reference

## `chumicro_runner`

::: chumicro_runner

## `chumicro_runner.generators`

Suspension helper for generators registered with `Runner.add_generator`.  `yield from sleep_until(until_ms)` parks the generator until the clock reaches that absolute tick, and the runner keeps serving every other service meanwhile.  Registration hands back a `GeneratorHandle` carrying `.done`, `.error`, and `.cancel()`.  Import this module explicitly; a program with no generators never loads it.

::: chumicro_runner.generators

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner) · \
[PyPI](https://pypi.org/project/chumicro-runner/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
