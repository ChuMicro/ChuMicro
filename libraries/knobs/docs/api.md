# API Reference

## `chumicro_knobs.encoder`

`Encoder` reads one rotary encoder: detents counted into a running `position`, the signed `delta` for each tick, and the optional `bounds` and `wrap` that keep the count inside a range you choose.

::: chumicro_knobs.encoder

## `chumicro_knobs.analog`

`AnalogKnob` reads one potentiometer or slider: a converter held still by a deadband and quantized into steps, published as `value`, `delta`, and the settled `raw` reading behind them.

::: chumicro_knobs.analog

## `chumicro_knobs.testing`

`FakeEncoderSource` and `FakeAnalogSource` stand in for the hardware so knob logic can be tested on a host.  Turn the shaft or park the wiper, tick the knob, assert on what it made of them.

::: chumicro_knobs.testing

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/knobs) · \
[PyPI](https://pypi.org/project/chumicro-knobs/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
