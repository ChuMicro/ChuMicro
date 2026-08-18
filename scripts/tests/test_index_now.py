"""Tests for index_now.py — the instant-indexing ping.

Nothing here touches the network: the urlopen seam is replaced, and
what the tests assert is the payload, because that payload is what a
search engine reads.
"""

from __future__ import annotations

import email.message
import io
import json
import urllib.error

import index_now
import pytest


@pytest.fixture
def recorded_request(monkeypatch) -> list:
    """Capture the request instead of sending it."""
    sent: list = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=None):
        sent.append(request)
        return Response()

    monkeypatch.setattr(index_now.urllib.request, "urlopen", fake_urlopen)
    return sent


class TestReadKey:
    """The key comes from the repository, or the ping is skipped."""

    def test_missing_key_file_reads_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(index_now, "KEY_FILE", tmp_path / "absent.txt")
        assert index_now.read_key() == ""

    def test_key_is_stripped(self, tmp_path, monkeypatch):
        key_file = tmp_path / "indexnow-key.txt"
        key_file.write_text("abc123\n")
        monkeypatch.setattr(index_now, "KEY_FILE", key_file)
        assert index_now.read_key() == "abc123"

    def test_key_filename_is_the_key(self):
        assert index_now.key_filename("abc123") == "abc123.txt"


class TestPing:
    """What the engines receive."""

    def test_payload_carries_key_location_and_urls(
        self, tmp_path, monkeypatch, recorded_request,
    ):
        key_file = tmp_path / "indexnow-key.txt"
        key_file.write_text("abc123\n")
        monkeypatch.setattr(index_now, "KEY_FILE", key_file)
        monkeypatch.setattr(
            index_now, "site_urls",
            lambda: ["https://chumicro.github.io/ChuMicro/"],
        )

        assert index_now.ping() is True
        payload = json.loads(recorded_request[0].data)
        assert payload["key"] == "abc123"
        assert payload["keyLocation"].endswith("/abc123.txt")
        assert payload["urlList"] == ["https://chumicro.github.io/ChuMicro/"]
        assert payload["host"] == "chumicro.github.io"

    def test_no_key_skips_the_ping(self, tmp_path, monkeypatch, recorded_request):
        monkeypatch.setattr(index_now, "KEY_FILE", tmp_path / "absent.txt")
        assert index_now.ping() is True
        assert recorded_request == []

    def test_rejected_ping_is_reported_not_raised(
        self, tmp_path, monkeypatch, capsys,
    ):
        key_file = tmp_path / "indexnow-key.txt"
        key_file.write_text("abc123\n")
        monkeypatch.setattr(index_now, "KEY_FILE", key_file)

        def fake_urlopen(request, timeout=None):
            # A real body and header object: HTTPError with fp=None
            # leaves a temp-file closer that raises on deallocation,
            # which `pytest -W error` turns into a failure.
            raise urllib.error.HTTPError(
                "url", 422, "Unprocessable Entity",
                email.message.Message(), io.BytesIO(b""),
            )

        monkeypatch.setattr(index_now.urllib.request, "urlopen", fake_urlopen)
        assert index_now.ping() is False
        assert "WARNING" in capsys.readouterr().out

    def test_network_failure_is_reported_not_raised(
        self, tmp_path, monkeypatch, capsys,
    ):
        key_file = tmp_path / "indexnow-key.txt"
        key_file.write_text("abc123\n")
        monkeypatch.setattr(index_now, "KEY_FILE", key_file)

        def fake_urlopen(request, timeout=None):
            raise OSError("connection reset")

        monkeypatch.setattr(index_now.urllib.request, "urlopen", fake_urlopen)
        assert index_now.ping() is False
        assert "WARNING" in capsys.readouterr().out
