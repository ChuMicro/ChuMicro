# Testing Helpers

`chumicro_logging.testing` provides handler fakes so your tests can assert against logger output without writing one-off mocks. The fakes stay on the host: `chumicro-deploy` reads the test-support marker at the top of the module and leaves it out of every device bundle it builds.

## RecordingHandler

Captures every emitted record in a list for assertions. Calls to `emit(level, name, message)` append a `(level, name, message)` tuple to `records`. Pass the handler to a `Logger` and assert against its output.

```python
from chumicro_logging import INFO, Logger
from chumicro_logging.testing import RecordingHandler


def test_logger_emits_at_info():
    handler = RecordingHandler()
    logger = Logger("subsystem", level=INFO, handlers=[handler])

    logger.info("up")

    assert handler.records == [(INFO, "subsystem", "up")]
```

`RecordingHandler` respects an optional `level` threshold of its own: records below it are dropped without being captured, which is how you check that a logger filters at a particular level. Call `clear()` between assertions to reset.

## FailingHandler

Raises a configured exception on every `emit` call. Useful for verifying that a misbehaving handler never crashes the logger:

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

The default exception is `RuntimeError("handler boom")`. Pass a custom exception via the `exception=` keyword to simulate specific failure modes, and read `calls` to count how many times the handler was reached.

## Using these fakes in your own tests

Nothing else in ChuMicro logs through this library, so these fakes are for your own tests: build a `Logger`, attach a handler, and assert on what came out.

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
