# API Reference

`chumicro_runner` exports `Runner`, `TaskHandle`, `GeneratorHandle`, `ReentrantTickError`, and the `IO_READ` and `IO_WRITE` bits.  Start with `Runner`: `add_periodic`, `add`, and `add_generator` register jobs on it, and `tick` and `wait` run the loop.  `add_generator` describes the `GeneratorHandle` it returns.  `sleep_until`, the pause a generator task yields from, imports from `chumicro_runner.generators`.

## `chumicro_runner`

::: chumicro_runner

## `chumicro_runner.generators`

::: chumicro_runner.generators

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner) · \
[PyPI](https://pypi.org/project/chumicro-runner/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
