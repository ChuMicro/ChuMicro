"""Logger + StreamHandler — minimal end-to-end logging.

The simplest end-to-end shape: a logger writing to stdout via a
``StreamHandler``.  Records below the logger's level are dropped silently.

Runs on CPython, MicroPython, and CircuitPython.

Example output::

    INFO:boot:hello
    WARNING:boot:something is off
    ERROR:boot:something broke
"""

from chumicro_logging import DEBUG, INFO, Logger, StreamHandler

handler = StreamHandler()
logger = Logger("boot", level=INFO, handlers=[handler])

logger.debug("invisible — below INFO")
logger.info("hello")
logger.warning("something is off")
logger.error("something broke")

# Lower the threshold and the previously-dropped record now emits.
logger.level = DEBUG
logger.debug("now visible")
