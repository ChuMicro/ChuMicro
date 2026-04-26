"""Tests for firmware URL derivation."""

from collections.abc import Callable
from contextlib import contextmanager
from io import BytesIO
from typing import Any

import pytest
from chumicro_workspace_runtime.firmware_url import (
    CIRCUITPYTHON_DOWNLOAD_TEMPLATE,
    MICROPYTHON_BOARD_BY_MACHINE,
    MICROPYTHON_DOWNLOAD_URL_TEMPLATE,
    MICROPYTHON_FIRMWARE_BASE_URL,
    UnresolvableFirmwareError,
    derive_firmware_url,
    latest_circuitpython_url,
    latest_circuitpython_version,
    latest_micropython_url,
    list_circuitpython_versions,
    list_micropython_builds,
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
# MicroPython scrape — list_micropython_builds + latest_micropython_url
# ---------------------------------------------------------------------------


def _mp_download_html(
    *,
    board: str,
    builds: list[tuple[str, str, bool, str]],
    extra_anchors: list[str] | None = None,
) -> bytes:
    """Synthesize a minimal micropython.org/download/<board>/ HTML body.

    Each *builds* entry is ``(date, version, unstable, ext)``.
    Filenames are constructed in the canonical
    ``<BOARD>-<DATE>-[unstable-]<VERSION>[-<commit>]?.<ext>`` shape.
    Extra anchors get included verbatim — useful for testing that
    unrelated links don't pollute the parse.
    """
    anchors: list[str] = []
    for build_date, version, unstable, file_extension in builds:
        if unstable:
            filename = f"{board}-{build_date}-unstable-{version}-1234.{file_extension}"
        else:
            filename = f"{board}-{build_date}-{version}.{file_extension}"
        anchors.append(
            f'<a href="/resources/firmware/{filename}">{filename}</a>',
        )
    if extra_anchors:
        anchors.extend(extra_anchors)
    return (
        "<!DOCTYPE html><html><body>"
        + "".join(anchors)
        + "</body></html>"
    ).encode("utf-8")


class TestListMicropythonBuilds:
    def test_returns_parsed_builds(self) -> None:
        opener = _make_opener(
            _mp_download_html(
                board="RPI_PICO_W",
                builds=[
                    ("20240222", "v1.22.2", False, "uf2"),
                    ("20240301", "v1.23.0", True, "uf2"),
                ],
            ),
        )
        builds = list_micropython_builds("RPI_PICO_W", url_opener=opener)
        assert len(builds) == 2
        # (date, version, unstable_marker, absolute_url)
        assert builds[0][0] == "20240222"
        assert builds[0][1] == "v1.22.2"
        assert builds[0][2] == ""  # stable
        assert builds[0][3].startswith(MICROPYTHON_FIRMWARE_BASE_URL)
        assert builds[1][2] == "unstable-"

    def test_passes_correct_url_to_opener(self) -> None:
        opener = _make_opener(
            _mp_download_html(board="RPI_PICO_W", builds=[
                ("20240301", "v1.22.2", False, "uf2"),
            ]),
        )
        list_micropython_builds("RPI_PICO_W", url_opener=opener)
        assert opener.captured[0] == MICROPYTHON_DOWNLOAD_URL_TEMPLATE.format(
            board="RPI_PICO_W",
        )

    def test_filters_by_file_extension(self) -> None:
        """ESP32 .bin shouldn't pollute an RP2040 .uf2 lookup."""
        opener = _make_opener(
            _mp_download_html(
                board="RPI_PICO_W",
                builds=[
                    ("20240301", "v1.22.2", False, "uf2"),
                    ("20240301", "v1.22.2", False, "bin"),
                    ("20240301", "v1.22.2", False, "hex"),
                ],
            ),
        )
        builds = list_micropython_builds("RPI_PICO_W", url_opener=opener)
        assert all(build[3].endswith(".uf2") for build in builds)
        assert len(builds) == 1

    def test_explicit_extension_override(self) -> None:
        opener = _make_opener(
            _mp_download_html(
                board="ESP32_GENERIC",
                builds=[
                    ("20240301", "v1.22.2", False, "bin"),
                    ("20240301", "v1.22.2", False, "uf2"),
                ],
            ),
        )
        builds = list_micropython_builds(
            "ESP32_GENERIC", url_opener=opener, file_extension="bin",
        )
        assert all(build[3].endswith(".bin") for build in builds)

    def test_skips_unrelated_anchors(self) -> None:
        """Other-page links + non-firmware anchors get filtered out."""
        opener = _make_opener(
            _mp_download_html(
                board="RPI_PICO_W",
                builds=[("20240301", "v1.22.2", False, "uf2")],
                extra_anchors=[
                    '<a href="/about/">About</a>',
                    '<a href="/resources/firmware/RPI_PICO-20240301-v1.22.2.uf2">'
                    'wrong board</a>',
                    '<a href="https://github.com/micropython/micropython">repo</a>',
                ],
            ),
        )
        builds = list_micropython_builds("RPI_PICO_W", url_opener=opener)
        assert len(builds) == 1
        assert "RPI_PICO_W" in builds[0][3]

    def test_de_duplicates(self) -> None:
        """Listing pages sometimes repeat the same build under multiple sections."""
        same_filename = "RPI_PICO_W-20240301-v1.22.2.uf2"
        body = (
            "<a href='/resources/firmware/" + same_filename + "'>a</a>"
            "<a href='/resources/firmware/" + same_filename + "'>b</a>"
        ).encode("utf-8")
        opener = _make_opener(body)
        builds = list_micropython_builds("RPI_PICO_W", url_opener=opener)
        assert len(builds) == 1

    def test_empty_listing_raises(self) -> None:
        opener = _make_opener(b"<html><body>no builds yet</body></html>")
        with pytest.raises(UnresolvableFirmwareError) as caught:
            list_micropython_builds("RPI_PICO_W", url_opener=opener)
        assert caught.value.cause == "no_mp_builds_listed"

    def test_non_utf8_body_returns_empty(self) -> None:
        """Garbage body (e.g. binary 404 served as 200) produces no builds."""
        opener = _make_opener(b"\xff\xfe\x00\x00binary garbage")
        with pytest.raises(UnresolvableFirmwareError) as caught:
            list_micropython_builds("RPI_PICO_W", url_opener=opener)
        assert caught.value.cause == "no_mp_builds_listed"

    def test_empty_board_raises(self) -> None:
        with pytest.raises(UnresolvableFirmwareError) as caught:
            list_micropython_builds("", url_opener=lambda _url: None)
        assert caught.value.cause == "no_machine"

    def test_absolute_url_anchors_preserved(self) -> None:
        """Anchors that already give an absolute URL should pass through."""
        body = (
            b'<a href="https://cdn.example/firmware/RPI_PICO_W-20240301-v1.22.2.uf2">'
            b"build</a>"
        )
        opener = _make_opener(body)
        builds = list_micropython_builds("RPI_PICO_W", url_opener=opener)
        assert builds[0][3] == (
            "https://cdn.example/firmware/RPI_PICO_W-20240301-v1.22.2.uf2"
        )


class TestLatestMicropythonUrl:
    def test_picks_newest_stable_build(self) -> None:
        opener = _make_opener(
            _mp_download_html(
                board="RPI_PICO_W",
                builds=[
                    ("20231201", "v1.21.0", False, "uf2"),
                    ("20240222", "v1.22.2", False, "uf2"),
                    ("20240115", "v1.22.0", False, "uf2"),
                ],
            ),
        )
        url = latest_micropython_url("RPI_PICO_W", url_opener=opener)
        assert "v1.22.2" in url
        assert "20240222" in url

    def test_filters_unstable_by_default(self) -> None:
        opener = _make_opener(
            _mp_download_html(
                board="RPI_PICO_W",
                builds=[
                    ("20240222", "v1.22.2", False, "uf2"),
                    ("20240301", "v1.23.0", True, "uf2"),
                ],
            ),
        )
        url = latest_micropython_url("RPI_PICO_W", url_opener=opener)
        # Stable wins even though the unstable build is newer.
        assert "v1.22.2" in url
        assert "unstable" not in url

    def test_allow_prerelease_includes_unstable(self) -> None:
        opener = _make_opener(
            _mp_download_html(
                board="RPI_PICO_W",
                builds=[
                    ("20240222", "v1.22.2", False, "uf2"),
                    ("20240301", "v1.23.0", True, "uf2"),
                ],
            ),
        )
        url = latest_micropython_url(
            "RPI_PICO_W", url_opener=opener, allow_prerelease=True,
        )
        assert "v1.23.0" in url
        assert "unstable" in url

    def test_no_stable_versions_raises(self) -> None:
        opener = _make_opener(
            _mp_download_html(
                board="RPI_PICO_W",
                builds=[("20240301", "v1.23.0", True, "uf2")],
            ),
        )
        with pytest.raises(UnresolvableFirmwareError) as caught:
            latest_micropython_url("RPI_PICO_W", url_opener=opener)
        assert caught.value.cause == "no_stable_versions"

    def test_newer_date_at_same_version_wins(self) -> None:
        opener = _make_opener(
            _mp_download_html(
                board="RPI_PICO_W",
                builds=[
                    ("20240222", "v1.22.2", False, "uf2"),
                    ("20240315", "v1.22.2", False, "uf2"),
                ],
            ),
        )
        url = latest_micropython_url("RPI_PICO_W", url_opener=opener)
        assert "20240315" in url

    def test_stable_beats_unstable_at_same_version(self) -> None:
        """allow_prerelease=True still prefers stable over unstable of same v.date."""
        opener = _make_opener(
            _mp_download_html(
                board="RPI_PICO_W",
                builds=[
                    ("20240301", "v1.22.2", True, "uf2"),
                    ("20240301", "v1.22.2", False, "uf2"),
                ],
            ),
        )
        url = latest_micropython_url(
            "RPI_PICO_W", url_opener=opener, allow_prerelease=True,
        )
        assert "unstable" not in url

    def test_two_dot_version_handled(self) -> None:
        """Some early MP releases ship as v1.20 with no patch number."""
        opener = _make_opener(
            _mp_download_html(
                board="OLDER_BOARD",
                builds=[("20230501", "v1.20", False, "uf2")],
            ),
        )
        url = latest_micropython_url("OLDER_BOARD", url_opener=opener)
        assert "v1.20" in url


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

    def test_micropython_known_machine_uses_scrape(self) -> None:
        """MP path scrapes micropython.org/download/<BOARD>/."""
        entry = {
            "id": "x",
            "runtime": "micropython",
            "hardware": {"machine": "Raspberry Pi Pico W with rp2040"},
        }
        opener = _make_opener(
            _mp_download_html(
                board="RPI_PICO_W",
                builds=[
                    ("20240222", "v1.22.2", False, "uf2"),
                    ("20240301", "v1.22.2", False, "uf2"),
                ],
            ),
        )
        url = derive_firmware_url(entry, url_opener=opener)
        # Latest of the two stable builds wins.
        assert "RPI_PICO_W-20240301-v1.22.2.uf2" in url

    def test_micropython_firmware_extension_override(self) -> None:
        """ESP32 boards need .bin not .uf2 — hardware.firmware_extension override."""
        entry = {
            "id": "x",
            "runtime": "micropython",
            "hardware": {
                "machine": "ESP32-S3 module with ESP32S3",
                "firmware_extension": "bin",
            },
        }
        opener = _make_opener(
            _mp_download_html(
                board="ESP32_GENERIC_S3",
                builds=[("20240301", "v1.22.2", False, "bin")],
            ),
        )
        url = derive_firmware_url(entry, url_opener=opener)
        assert url.endswith("ESP32_GENERIC_S3-20240301-v1.22.2.bin")

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
