# Testing Helpers

`chumicro_charlcd.testing` provides `RecordingTransport`, a transport fake that captures every raw PCF8574 byte, plus two decoders that fold the enable-pulse pairs back into HD44780 commands.  Tests assert protocol (`(register_select, value)` tuples) instead of brittle golden byte lists, and the decoders check the bus discipline (enable pulses high then low, only the enable bit changing) while they fold.  The module is test support and never lands on a device.

## Usage

```python
from chumicro_charlcd import CharLcd
from chumicro_charlcd.testing import RecordingTransport, decode_bytes

def test_status_row_positions_and_writes():
    transport = RecordingTransport()
    lcd = CharLcd(transport, sleep_ms=[].append)
    del transport.raw[:]

    lcd.write("OK", row=1)

    assert decode_bytes(transport.raw) == [
        (0, 0x80 | 0x40), (1, ord("O")), (1, ord("K"))]
```

## Test hooks

| Hook | What it does |
|---|---|
| `RecordingTransport.raw` | Every byte the core put on the bus, in order. |
| `decode_nibbles(raw)` | Folds (enable high, enable low) pairs into `(register_select, nibble)` tuples; use on init traffic, which starts in 4-bit mode-force nibbles. |
| `decode_bytes(raw)` | Folds nibble pairs into `(register_select, value)` tuples; use on post-init traffic. |
| `REGISTER_SELECT` / `ENABLE` / `BACKLIGHT` | The PCF8574 bit map, for asserting on raw bytes such as a backlight toggle. |

Passing `sleep_ms=[].append` (or any recorder) at construction keeps tests from actually waiting out the controller's timed delays.

## Using these fakes in your own tests

Install `chumicro-charlcd` and import the fakes straight into your test suite:

```python
from chumicro_charlcd.testing import RecordingTransport, decode_bytes
```

Project convention: libraries that expose injectable services ship their own test fakes alongside the production code.

## API Reference

::: chumicro_charlcd.testing

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/charlcd) · \
[PyPI](https://pypi.org/project/chumicro-charlcd/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
