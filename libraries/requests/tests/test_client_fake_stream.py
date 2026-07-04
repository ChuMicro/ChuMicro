"""``FakeHttpClient`` — streamed requests and ``cancel`` mirror the real client."""

from chumicro_requests import HttpError
from chumicro_requests.testing import FakeHttpClient


class TestFakeHttpClientStream:
    """A stream=True request drains its scripted body via read_body_into."""

    def test_streamed_request_drains_scripted_body(self):
        fake = FakeHttpClient()
        fake.enqueue_response(status=200, body=b"scripted-firmware-bytes")

        handle = fake.get("http://example.test/blob", stream=True)
        assert fake.busy is True
        fake.handle(now_ms=0)

        assert handle.done is True
        response = handle.result
        assert response.streamed is True
        assert response.body == b""
        scratch = bytearray(8)
        collected = bytearray()
        while True:
            count = handle.read_body_into(scratch)
            if count == 0:
                break
            collected.extend(scratch[:count])
        assert bytes(collected) == b"scripted-firmware-bytes"
        # Drained: every further read reports end of body.
        assert handle.read_body_into(scratch) == 0

    def test_call_records_stream_flag(self):
        fake = FakeHttpClient()
        fake.enqueue_response(body=b"x")
        fake.enqueue_response(body=b"y")
        fake.get("http://example.test/a", stream=True)
        fake.handle(now_ms=0)
        fake.get("http://example.test/b")
        assert fake.calls[0].stream is True
        assert fake.calls[1].stream is False

    def test_request_method_mirrors_generic_entry(self):
        fake = FakeHttpClient()
        fake.enqueue_response(status=204)
        handle = fake.request("PURGE", "http://example.test/cache")
        fake.handle(now_ms=0)
        assert handle.result.status_code == 204
        assert fake.calls[0].method == "PURGE"


class TestFakeHttpClientCancel:
    """``cancel`` fails the in-flight request the way the real client does."""

    def test_cancel_fails_handle_and_fires_on_done(self):
        fake = FakeHttpClient()
        fake.enqueue_response(body=b"never-delivered")
        completions = []
        handle = fake.get("http://example.test/", on_done=completions.append)

        fake.cancel()

        assert handle.done is True
        assert isinstance(handle.error, HttpError)
        assert "cancelled" in str(handle.error)
        assert completions == [handle]
        assert fake.busy is False

    def test_cancel_when_idle_is_noop(self):
        fake = FakeHttpClient()
        fake.cancel()
        assert fake.busy is False
