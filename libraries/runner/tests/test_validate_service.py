"""Cross-runtime tests for ``chumicro_runner.testing.validate_service``.

Plain asserts plus the harness ``raises``, no pytest fixtures, so the
suite runs on the MicroPython and CircuitPython unix ports as well as
CPython. The rules under test come from ``chumicro_runner.core``:
``check`` and ``handle`` are both required, ``io_socket`` and
``io_interest`` come as a pair, and ``io_error`` requires ``io_socket``.
"""

from chumicro_runner.testing import validate_service
from chumicro_test_harness import raises


class _CheckHandle:
    """Minimal valid service: the required check/handle pair."""

    def check(self, now_ms):
        return False

    def handle(self, now_ms):
        pass


def test_check_handle_service_passes():
    assert validate_service(_CheckHandle()) is None


def test_handle_without_check_fails():
    class Bad:
        def handle(self, now_ms):
            pass

    with raises(ValueError, match="check"):
        validate_service(Bad())


def test_check_without_handle_fails():
    class Bad:
        def check(self, now_ms):
            return False

    with raises(ValueError, match="handle"):
        validate_service(Bad())


def test_inert_object_fails():
    with raises(ValueError):
        validate_service(object())


def test_io_socket_without_interest_fails():
    class Bad(_CheckHandle):
        io_socket = None

    with raises(ValueError, match="io_interest"):
        validate_service(Bad())


def test_io_interest_without_socket_fails():
    class Bad(_CheckHandle):
        def io_interest(self, now_ms):
            return 0

    with raises(ValueError, match="io_socket"):
        validate_service(Bad())


def test_io_socket_interest_pair_passes():
    class Good(_CheckHandle):
        io_socket = None

        def io_interest(self, now_ms):
            return 0

    assert validate_service(Good()) is None


def test_io_error_without_socket_fails():
    class Bad(_CheckHandle):
        def io_error(self, now_ms, eventmask):
            pass

    with raises(ValueError, match="io_socket"):
        validate_service(Bad())


def test_next_deadline_alone_passes():
    class Good(_CheckHandle):
        def next_deadline(self, now_ms):
            return None

    assert validate_service(Good()) is None
