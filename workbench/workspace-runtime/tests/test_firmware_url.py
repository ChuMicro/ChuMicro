"""Tests for firmware URL derivation."""

from collections.abc import Callable
from contextlib import contextmanager
from io import BytesIO
from typing import Any

import pytest
from chumicro_workspace_runtime.firmware_url import (
    CIRCUITPYTHON_DOWNLOAD_TEMPLATE,
    MICROPYTHON_BOARD_BY_MACHINE,
    UnresolvableFirmwareError,
    derive_firmware_url,
    latest_circuitpython_url,
    latest_circuitpython_version,
    list_circuitpython_versions,
    micropython_board_for_machine,
)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _bucket_xml(keys: list[str]) -> bytes:
    """Synthesize an S3 ``ListBucketResult`` body containing *keys*."""
    contents_blocks = []
    for key in keys:
        contents_blocks.append(
            f"<Contents><Key>{key}</Key>"
            "<LastModified>2024-01-01T00:00:00.000Z</LastModified>"
            "<ETag>&quot;deadbeef&quot;</ETag>"
            "<Size>123</Size>"
            "<StorageClass>STANDARD</StorageClass>"
            "</Contents>"
        )
    body = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<ListBucketResult xmlns='http://s3.amazonaws.com/doc/2006-03-01/'>"
        "<Name>adafruit-circuit-python</Name>"
        "<Prefix></Prefix><Marker></Marker><MaxKeys>1000</MaxKeys>"
        "<IsTruncated>false</IsTruncated>"
        + "".join(contents_blocks)
        + "</ListBucketResult>"
    )
    return body.encode("utf-8")


def _make_opener(body: bytes) -> Callable[[str], Any]:
    """Build an injectable url_opener that returns *body* once."""
    captured: list[str] = []

    @contextmanager
    def _fake_response(url: str):
        captured.append(url)
        yield BytesIO(body)

    _fake_response.captured = captured  # type: ignore[attr-defined]
    return _fake_response


# ---------------------------------------------------------------------------
# list_circuitpython_versions
# ---------------------------------------------------------------------------


class TestListCircuitpythonVersions:
    def test_returns_versions_in_listing_order(self) -> None:
        opener = _make_opener(
            _bucket_xml(
                [
                    "bin/raspberry_pi_pico_w/en_US/"
                    "adafruit-circuitpython-raspberry_pi_pico_w-en_US-10.1.4.uf2",
                    "bin/raspberry_pi_pico_w/en_US/"
                    "adafruit-circuitpython-raspberry_pi_pico_w-en_US-10.2.0-rc.0.uf2",
                    "bin/raspberry_pi_pico_w/en_US/"
                    "adafruit-circuitpython-raspberry_pi_pico_w-en_US-10.0.3.uf2",
                ],
            ),
        )
        versions = list_circuitpython_versions(
            "raspberry_pi_pico_w", url_opener=opener,
        )
        assert versions == ["10.1.4", "10.2.0-rc.0", "10.0.3"]

    def test_passes_correct_prefix_to_opener(self) -> None:
        opener = _make_opener(_bucket_xml([]))
        with pytest.raises(UnresolvableFirmwareError):
            list_circuitpython_versions("some_board", url_opener=opener)
        # The captured URL must include the prefix=bin/<board_id>/<lang>/.
        captured = opener.captured  # type: ignore[attr-defined]
        assert "prefix=bin/some_board/en_US/" in captured[0]

    def test_language_override_changes_prefix(self) -> None:
        opener = _make_opener(_bucket_xml([]))
        with pytest.raises(UnresolvableFirmwareError):
            list_circuitpython_versions(
                "some_board", language="fr", url_opener=opener,
            )
        assert "prefix=bin/some_board/fr/" in opener.captured[0]  # type: ignore[attr-defined]

    def test_de_duplicates(self) -> None:
        """Mirror keys (CDN cache duplicates) collapse to one version."""
        opener = _make_opener(
            _bucket_xml(
                [
                    "bin/board/en_US/adafruit-circuitpython-board-en_US-10.1.4.uf2",
                    "bin/board/en_US/adafruit-circuitpython-board-en_US-10.1.4.uf2",
                ],
            ),
        )
        assert list_circuitpython_versions("board", url_opener=opener) == ["10.1.4"]

    def test_skips_unrelated_keys(self) -> None:
        """Other-prefix entries in the same bucket don't pollute."""
        opener = _make_opener(
            _bucket_xml(
                [
                    "bin/board/en_US/adafruit-circuitpython-board-en_US-10.1.4.uf2",
                    "bin/different_board/en_US/adafruit-circuitpython-different_board-en_US-9.0.0.uf2",
                    "bin/board/de_DE/adafruit-circuitpython-board-de_DE-10.1.4.uf2",
                    "adabot/some-report.txt",
                ],
            ),
        )
        versions = list_circuitpython_versions("board", url_opener=opener)
        assert versions == ["10.1.4"]

    def test_skips_non_uf2_keys(self) -> None:
        opener = _make_opener(
            _bucket_xml(
                [
                    "bin/board/en_US/adafruit-circuitpython-board-en_US-10.1.4.uf2",
                    "bin/board/en_US/adafruit-circuitpython-board-en_US-10.1.4.bin",
                    "bin/board/en_US/checksums.txt",
                ],
            ),
        )
        assert list_circuitpython_versions("board", url_opener=opener) == ["10.1.4"]

    def test_empty_listing_raises(self) -> None:
        opener = _make_opener(_bucket_xml([]))
        with pytest.raises(UnresolvableFirmwareError) as caught:
            list_circuitpython_versions("board", url_opener=opener)
        assert caught.value.cause == "no_versions_listed"

    def test_empty_board_id_raises(self) -> None:
        with pytest.raises(UnresolvableFirmwareError) as caught:
            list_circuitpython_versions("", url_opener=lambda _url: None)
        assert caught.value.cause == "no_board_id"


# ---------------------------------------------------------------------------
# latest_circuitpython_version
# ---------------------------------------------------------------------------


class TestLatestCircuitpythonVersion:
    def test_picks_highest_stable(self) -> None:
        opener = _make_opener(
            _bucket_xml(
                [
                    "bin/b/en_US/adafruit-circuitpython-b-en_US-10.0.3.uf2",
                    "bin/b/en_US/adafruit-circuitpython-b-en_US-10.1.4.uf2",
                    "bin/b/en_US/adafruit-circuitpython-b-en_US-10.0.4.uf2",
                ],
            ),
        )
        assert latest_circuitpython_version("b", url_opener=opener) == "10.1.4"

    def test_filters_pre_release_by_default(self) -> None:
        opener = _make_opener(
            _bucket_xml(
                [
                    "bin/b/en_US/adafruit-circuitpython-b-en_US-10.1.4.uf2",
                    "bin/b/en_US/adafruit-circuitpython-b-en_US-10.2.0-rc.0.uf2",
                ],
            ),
        )
        # Without allow_prerelease, 10.2.0-rc.0 is filtered out.
        assert latest_circuitpython_version("b", url_opener=opener) == "10.1.4"

    def test_allow_prerelease_includes_rc(self) -> None:
        opener = _make_opener(
            _bucket_xml(
                [
                    "bin/b/en_US/adafruit-circuitpython-b-en_US-10.1.4.uf2",
                    "bin/b/en_US/adafruit-circuitpython-b-en_US-10.2.0-rc.0.uf2",
                ],
            ),
        )
        assert (
            latest_circuitpython_version("b", url_opener=opener, allow_prerelease=True)
            == "10.2.0-rc.0"
        )

    def test_pre_release_ordering(self) -> None:
        """rc > beta > alpha when prerelease is allowed."""
        opener = _make_opener(
            _bucket_xml(
                [
                    "bin/b/en_US/adafruit-circuitpython-b-en_US-10.2.0-alpha.0.uf2",
                    "bin/b/en_US/adafruit-circuitpython-b-en_US-10.2.0-beta.0.uf2",
                    "bin/b/en_US/adafruit-circuitpython-b-en_US-10.2.0-rc.0.uf2",
                ],
            ),
        )
        assert (
            latest_circuitpython_version("b", url_opener=opener, allow_prerelease=True)
            == "10.2.0-rc.0"
        )

    def test_stable_beats_prerelease_of_same_base(self) -> None:
        """10.2.0 stable beats 10.2.0-rc.0 even with allow_prerelease."""
        opener = _make_opener(
            _bucket_xml(
                [
                    "bin/b/en_US/adafruit-circuitpython-b-en_US-10.2.0-rc.0.uf2",
                    "bin/b/en_US/adafruit-circuitpython-b-en_US-10.2.0.uf2",
                ],
            ),
        )
        assert (
            latest_circuitpython_version("b", url_opener=opener, allow_prerelease=True)
            == "10.2.0"
        )

    def test_no_stable_versions_raises(self) -> None:
        opener = _make_opener(
            _bucket_xml(
                [
                    "bin/b/en_US/adafruit-circuitpython-b-en_US-10.2.0-rc.0.uf2",
                    "bin/b/en_US/adafruit-circuitpython-b-en_US-10.2.0-beta.0.uf2",
                ],
            ),
        )
        with pytest.raises(UnresolvableFirmwareError) as caught:
            latest_circuitpython_version("b", url_opener=opener)
        assert caught.value.cause == "no_stable_versions"


# ---------------------------------------------------------------------------
# latest_circuitpython_url
# ---------------------------------------------------------------------------


class TestLatestCircuitpythonUrl:
    def test_combines_template_with_latest_version(self) -> None:
        opener = _make_opener(
            _bucket_xml(
                [
                    "bin/b/en_US/adafruit-circuitpython-b-en_US-10.1.4.uf2",
                ],
            ),
        )
        url = latest_circuitpython_url("b", url_opener=opener)
        assert url == CIRCUITPYTHON_DOWNLOAD_TEMPLATE.format(
            board_id="b", language="en_US", version="10.1.4",
        )


# ---------------------------------------------------------------------------
# MicroPython lookup
# ---------------------------------------------------------------------------


class TestMicropythonBoardForMachine:
    def test_known_machine_returns_board(self) -> None:
        assert micropython_board_for_machine(
            "Raspberry Pi Pico W with rp2040",
        ) == "RPI_PICO_W"

    def test_unknown_machine_returns_none(self) -> None:
        assert micropython_board_for_machine("Made-up Board with FAKE-CPU") is None

    def test_empty_machine_returns_none(self) -> None:
        assert micropython_board_for_machine("") is None

    def test_curated_map_covers_common_boards(self) -> None:
        """Sanity check the canonical entries didn't drift."""
        for machine in (
            "Raspberry Pi Pico W with rp2040",
            "Raspberry Pi Pico with rp2040",
            "ESP32-S2 module with ESP32S2",
            "ESP32-S3 module with ESP32S3",
        ):
            assert MICROPYTHON_BOARD_BY_MACHINE.get(machine), (
                f"Curated map regression: {machine}"
            )


# ---------------------------------------------------------------------------
# derive_firmware_url — top-level resolver
# ---------------------------------------------------------------------------


class TestDeriveFirmwareUrl:
    def test_firmware_source_short_circuits(self) -> None:
        entry = {
            "id": "x",
            "runtime": "circuitpython",
            "hardware": {"firmware_source": "https://my-mirror/custom.uf2"},
        }
        # No url_opener — must NOT call S3 because firmware_source wins first.
        assert derive_firmware_url(entry) == "https://my-mirror/custom.uf2"

    def test_firmware_source_works_for_unsupported_runtime(self) -> None:
        """Vendor forks with arbitrary runtime labels still resolve."""
        entry = {
            "id": "x",
            "runtime": "vendor-fork-py",
            "hardware": {"firmware_source": "/local/path/to/fw.bin"},
        }
        assert derive_firmware_url(entry) == "/local/path/to/fw.bin"

    def test_circuitpython_uses_s3_listing(self) -> None:
        entry = {
            "id": "pico",
            "runtime": "circuitpython",
            "hardware": {"board_id": "raspberry_pi_pico_w"},
        }
        opener = _make_opener(
            _bucket_xml(
                [
                    "bin/raspberry_pi_pico_w/en_US/"
                    "adafruit-circuitpython-raspberry_pi_pico_w-en_US-10.1.4.uf2",
                ],
            ),
        )
        url = derive_firmware_url(entry, url_opener=opener)
        assert "raspberry_pi_pico_w" in url
        assert "10.1.4" in url

    def test_circuitpython_no_board_id_raises(self) -> None:
        entry = {"id": "x", "runtime": "circuitpython", "hardware": {}}
        with pytest.raises(UnresolvableFirmwareError) as caught:
            derive_firmware_url(entry, url_opener=lambda _url: None)
        assert caught.value.cause == "no_board_id"

    def test_micropython_no_machine_raises(self) -> None:
        entry = {"id": "x", "runtime": "micropython", "hardware": {}}
        with pytest.raises(UnresolvableFirmwareError) as caught:
            derive_firmware_url(entry)
        assert caught.value.cause == "no_machine"

    def test_micropython_unknown_machine_raises(self) -> None:
        entry = {
            "id": "x",
            "runtime": "micropython",
            "hardware": {"machine": "Made-up Board with FAKE-CPU"},
        }
        with pytest.raises(UnresolvableFirmwareError) as caught:
            derive_firmware_url(entry)
        assert caught.value.cause == "machine_not_in_map"

    def test_micropython_known_machine_still_raises_for_dated_url(self) -> None:
        """MP needs the dated URL — even with BOARD known we can't auto-pick."""
        entry = {
            "id": "x",
            "runtime": "micropython",
            "hardware": {"machine": "Raspberry Pi Pico W with rp2040"},
        }
        with pytest.raises(UnresolvableFirmwareError) as caught:
            derive_firmware_url(entry)
        assert caught.value.cause == "no_micropython_dated_url"
        # Error message must name the BOARD so the user can navigate
        # to the right download page.
        assert "RPI_PICO_W" in str(caught.value)

    def test_no_hardware_block_is_handled_as_empty(self) -> None:
        entry = {"id": "x", "runtime": "circuitpython"}
        with pytest.raises(UnresolvableFirmwareError) as caught:
            derive_firmware_url(entry, url_opener=lambda _url: None)
        assert caught.value.cause == "no_board_id"

    def test_unsupported_runtime_raises(self) -> None:
        entry = {"id": "x", "runtime": "totally-made-up", "hardware": {}}
        with pytest.raises(UnresolvableFirmwareError) as caught:
            derive_firmware_url(entry)
        assert caught.value.cause == "unsupported_runtime"

    def test_allow_prerelease_passes_through(self) -> None:
        """allow_prerelease=True flows to the CP path."""
        entry = {
            "id": "pico",
            "runtime": "circuitpython",
            "hardware": {"board_id": "b"},
        }
        opener = _make_opener(
            _bucket_xml(
                [
                    "bin/b/en_US/adafruit-circuitpython-b-en_US-10.1.4.uf2",
                    "bin/b/en_US/adafruit-circuitpython-b-en_US-10.2.0-rc.0.uf2",
                ],
            ),
        )
        url = derive_firmware_url(entry, url_opener=opener, allow_prerelease=True)
        assert "10.2.0-rc.0" in url
