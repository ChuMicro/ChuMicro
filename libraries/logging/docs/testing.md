# Testing Helpers

`chumicro_logging.testing` provides handler fakes that downstream
libraries and applications can use to assert against logger output
without writing one-off mocks.

## RecordingHandler

Captures every emitted record in a list for assertions.  Calls to
`emit(level, name, message)` append a `(level, name, message)` tuple
to `records`.  Pass the handler to a `Logger` and assert against its
output.

```python
from chumicro_logging import INFO, Logger
from chumicro_logging.testing import RecordingHandler


def test_logger_emits_at_info():
    handler = RecordingHandler()
    logger = Logger("subsystem", level=INFO, handlers=[handler])

    logger.info("up")

    assert handler.records == [(INFO, "subsystem", "up")]
```

`RecordingHandler` itself respects an optional `level` threshold —
records below the threshold are dropped without being captured —
which makes it easy to verify that a logger correctly filters at a
particular level.  Call `clear()` between assertions to reset.

## FailingHandler

Raises a configured exception on every `emit` call.  Useful for
verifying that misbehaving handlers never crash the logger:

```python
from chumicro_logging import Logger
from chumicro_logging.testing import FailingHandler, RecordingHandler


def test_failing_handler_is_swallowed():
    failing = FailingHandler()
    recorder = RecordingHandler()
    logger = Logger("alpha", handlers=[failing, recorder])

    logger.warning("survive me")

    assert logger.handler_errors == 1
    assert recorder.records[0][2] == "survive me"
```

The default exception is `RuntimeError("handler boom")`.  Pass a
custom exception via the `exception=` keyword to simulate specific
failure modes.

## Usage from other libraries

Libraries that depend on `chumicro-logging` can import the fakes directly:

```python
from chumicro_logging.testing import RecordingHandler
```

Project convention: libraries that expose injectable services ship their own test fakes alongside the production code.

## API Reference

::: chumicro_logging.testing

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/logging) · \
[PyPI](https://pypi.org/project/chumicro-logging/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
