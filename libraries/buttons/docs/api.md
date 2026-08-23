# API Reference

## `chumicro_buttons.core`

`Button` reads one momentary button or switch: a debounced level, the edges either side of it, and the durations built on top (long press, auto-repeat, click counting).  `Buttons` reads several keys on one scan and hands you each as a `Button`.

::: chumicro_buttons.core

## `chumicro_buttons.matrix`

`KeyMatrix` reads a keypad wired as rows by columns.  Keys are numbered row-major and carry the same readings and callbacks as any other button.

::: chumicro_buttons.matrix

## `chumicro_buttons.testing`

`FakeButtonSource` stands in for the hardware so button logic can be tested on a host.  Queue the edges, tick the button, assert on what it made of them.

::: chumicro_buttons.testing

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/buttons) · \
[PyPI](https://pypi.org/project/chumicro-buttons/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
