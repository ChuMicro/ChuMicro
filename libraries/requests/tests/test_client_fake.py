"""requests client: host-only FakeHttpClient mirrors the real surface."""

from chumicro_requests import (
    HttpBusyError,
    HttpError,
    HttpTimeoutError,
)
from chumicro_test_harness.assertions import raises


class TestFakeHttpClient:
    """The host-only :class:`FakeHttpClient` mirrors the real client surface."""

    def test_scripted_response_completes_after_handle(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_response(
            status=200,
            body=b'{"temp_f": 72}',
            headers={"Content-Type": "application/json"},
        )
        handle = fake.get("http://api.example.test/weather")
        assert not handle.done
        assert fake.busy is True
        assert fake.check(now_ms=0) is True

        fake.handle(now_ms=0)
        assert handle.done
        assert fake.busy is False
        response = handle.result
        assert response.status_code == 200
        assert response.body == b'{"temp_f": 72}'
        assert response.headers["content-type"] == "application/json"
        assert response.url == "http://api.example.test/weather"

    def test_call_recording(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_response(body=b"")
        fake.get("http://example.test/", headers={"X-Foo": "bar"}, timeout_ms=99)

        assert len(fake.calls) == 1
        call = fake.calls[0]
        assert call.method == "GET"
        assert call.url == "http://example.test/"
        assert call.headers == {"X-Foo": "bar"}
        assert call.timeout_ms == 99

    def test_scripted_error_propagates(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_error(HttpTimeoutError("simulated timeout"))
        handle = fake.get("http://example.test/")
        fake.handle(now_ms=0)
        assert handle.done
        assert isinstance(handle.error, HttpTimeoutError)
        with raises(HttpTimeoutError, match="simulated"):
            _ = handle.result

    def test_enqueue_error_rejects_non_http_error(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        with raises(TypeError, match="HttpError"):
            fake.enqueue_error(ValueError("not an HttpError"))

    def test_get_without_scripted_response_raises(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        with raises(HttpError, match="no scripted responses"):
            fake.get("http://example.test/")

    def test_busy_during_in_flight(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_response(body=b"")
        fake.get("http://example.test/")
        with raises(HttpBusyError, match="busy"):
            fake.get("http://example.test/two")

    def test_check_false_when_idle(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        assert fake.check(now_ms=0) is False

    def test_handle_when_idle_is_noop(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.handle(now_ms=0)  # safe no-op
        # ``handle`` on an idle client must not accidentally start work.
        assert fake.check(now_ms=0) is False

    def test_responses_consumed_fifo(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_response(status=200, body=b"first")
        fake.enqueue_response(status=404, body=b"")

        handle_one = fake.get("http://example.test/one")
        fake.handle(now_ms=0)
        assert handle_one.result.body == b"first"

        handle_two = fake.get("http://example.test/two")
        fake.handle(now_ms=0)
        assert handle_two.result.status_code == 404

    def test_headers_as_iterable(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_response(headers=[("X-Custom", "v"), ("Server", "nginx")])
        handle = fake.get("http://example.test/")
        fake.handle(now_ms=0)
        assert handle.result.headers["x-custom"] == "v"
        assert handle.result.headers["server"] == "nginx"

    def test_oversized_dropped_flag_round_trip(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_response(status=200, body=b"", oversized_dropped=True)
        handle = fake.get("http://example.test/")
        fake.handle(now_ms=0)
        assert handle.result.oversized_dropped is True

    def test_post_records_body_and_method(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_response(body=b"created")
        handle = fake.post("http://api.example.test/widgets", body=b"payload")
        fake.handle(now_ms=0)
        assert handle.result.body == b"created"
        assert fake.calls[0].method == "POST"
        assert fake.calls[0].body == b"payload"
        assert fake.calls[0].json is None

    def test_post_records_json_payload(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_response(body=b"")
        fake.post("http://api.example.test/", json={"key": "value"})
        assert fake.calls[0].json == {"key": "value"}
        assert fake.calls[0].body is None

    def test_post_body_and_json_mutually_exclusive(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        with raises(ValueError, match="not both"):
            fake.post("http://api.example.test/", body=b"x", json={"k": "v"})

    def test_put_body_and_json_mutually_exclusive(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        with raises(ValueError, match="not both"):
            fake.put("http://api.example.test/", body=b"x", json={"k": "v"})

    def test_patch_body_and_json_mutually_exclusive(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        with raises(ValueError, match="not both"):
            fake.patch("http://api.example.test/", body=b"x", json={"k": "v"})

    def test_put_records_method(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_response(body=b"")
        fake.put("http://api.example.test/r/42", body=b"updated")
        assert fake.calls[0].method == "PUT"
        assert fake.calls[0].body == b"updated"

    def test_patch_records_method(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_response(body=b"")
        fake.patch("http://api.example.test/r/42", json={"name": "x"})
        assert fake.calls[0].method == "PATCH"
        assert fake.calls[0].json == {"name": "x"}

    def test_delete_records_method_no_body(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_response(body=b"")
        fake.delete("http://api.example.test/r/42")
        assert fake.calls[0].method == "DELETE"
        assert fake.calls[0].body is None
        assert fake.calls[0].json is None

    def test_on_done_fires_after_handle(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_response(body=b"hi")
        received = []
        handle = fake.get("http://api.example.test/", on_done=received.append)
        assert received == []
        fake.handle(now_ms=0)
        assert received == [handle]
        assert received[0].result.body == b"hi"

    def test_on_done_fires_on_error(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_error(HttpTimeoutError("simulated"))
        received = []
        fake.post(
            "http://api.example.test/", body=b"x", on_done=received.append,
        )
        fake.handle(now_ms=0)
        assert len(received) == 1
        assert isinstance(received[0].error, HttpTimeoutError)

    def test_max_redirects_passed_through_to_call_record(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_response(body=b"")
        fake.get("http://api.example.test/", max_redirects=3)
        assert fake.calls[0].max_redirects == 3

    def test_busy_blocks_any_verb(self):
        from chumicro_requests.testing import FakeHttpClient

        fake = FakeHttpClient()
        fake.enqueue_response(body=b"")
        fake.post("http://api.example.test/one", body=b"x")
        with raises(HttpBusyError):
            fake.delete("http://api.example.test/two")
