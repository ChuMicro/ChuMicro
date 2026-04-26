"""Firmware URL derivation per Decision 0029 §5.

Two runtimes, two strategies:

* **CircuitPython** — list the Adafruit S3 bucket via
  ``?prefix=bin/<board_id>/<language>/``, parse the XML, pick the
  highest stable version.  Zero catalog maintained on the project
  side; Adafruit's release upload is the source of truth.
* **MicroPython** — micropython.org publishes per-build dated
  filenames that can't be derived from a version label, and the
  ``machine`` string a board reports doesn't always map cleanly to
  the published BOARD name.  Strategy: ship a hand-curated
  ``machine`` → BOARD map (extended from periodic
  ``micropython.org/download/`` scrapes); on cache miss, the CLI
  prompts for an explicit URL and caches it on the device entry as
  ``hardware.firmware_source``.

Custom forks: any device entry whose ``hardware.firmware_source``
field is set short-circuits the lookup — the value is returned
verbatim.  Vendor builds, locally-compiled firmware, mirrored
URLs all pass through.

Network access is via an injectable ``url_opener`` callable so tests
exercise the XML-parsing + version-picking logic without hitting
the real bucket.  Production code calls :func:`derive_firmware_url`
without injection; the default opener is :func:`urllib.request.urlopen`.
"""

from __future__ import annotations

import re
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any
from xml.etree import ElementTree

#: S3 bucket where Adafruit publishes CircuitPython firmware.  The
#: front-end CDN at ``downloads.circuitpython.org`` strips query
#: parameters, so we hit the bucket directly for listing.  Stable
#: since the bucket was created; mirrored across the Adafruit
#: tooling ecosystem.
CIRCUITPYTHON_S3_BUCKET_URL = "https://adafruit-circuit-python.s3.amazonaws.com/"

#: Adafruit's CDN download URL — used for the actual firmware
#: download (lower latency than the bucket URL).  Listing happens on
#: the bucket; download happens on the CDN.
CIRCUITPYTHON_DOWNLOAD_TEMPLATE = (
    "https://downloads.circuitpython.org/bin/{board_id}/{language}/"
    "adafruit-circuitpython-{board_id}-{language}-{version}.uf2"
)

#: S3 ``ListBucketResult`` XML namespace — every element in the
#: response carries this namespace, so XPath needs the prefix.
_S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"

#: Pattern that pulls the version out of an Adafruit firmware
#: filename.  The version sits between the trailing language code
#: and the ``.uf2`` extension::
#:
#:     adafruit-circuitpython-raspberry_pi_pico_w-en_US-10.1.4.uf2
#:                                                       ^^^^^^^
#:     adafruit-circuitpython-raspberry_pi_pico_w-en_US-10.2.0-rc.0.uf2
#:                                                       ^^^^^^^^^^^^
#:
#: Anchored on the SemVer-shaped digit prefix (``\d+\.\d+\.\d+``)
#: so the greedy ``[^/]+`` board-id-plus-language match never bleeds
#: into the version capture.  Pre-release suffixes (``-rc.0`` /
#: ``-beta.1`` / ``-alpha.0``) are optional.
_CIRCUITPYTHON_FILENAME_VERSION = re.compile(
    r"adafruit-circuitpython-[^/]+-"
    r"(?P<version>\d+\.\d+\.\d+(?:-[a-z]+\.\d+)?)"
    r"\.uf2$",
)

#: Pattern for stable versions: ``<major>.<minor>.<patch>`` with no
#: pre-release label.  Pre-releases like ``10.2.0-rc.0`` /
#: ``10.2.0-beta.1`` /  ``10.2.0-alpha.0`` carry an extra ``-`` plus
#: tag and won't match.
_STABLE_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")

#: Hand-curated subset of the MicroPython ``machine`` → BOARD map.
#: Extends as new boards land; the project-workspace template will
#: ship periodic refreshes pulled from ``micropython.org/download/``.
#: Boards not in this table fall through to the prompt-and-cache
#: path.
MICROPYTHON_BOARD_BY_MACHINE: dict[str, str] = {
    "Raspberry Pi Pico W with rp2040": "RPI_PICO_W",
    "Raspberry Pi Pico with rp2040": "RPI_PICO",
    "Raspberry Pi Pico 2 W with rp2350": "RPI_PICO2_W",
    "Raspberry Pi Pico 2 with rp2350": "RPI_PICO2",
    "ESP32-S2 module with ESP32S2": "ESP32_GENERIC_S2",
    "ESP32-S3 module with ESP32S3": "ESP32_GENERIC_S3",
    "ESP32 module with ESP32": "ESP32_GENERIC",
    "Adafruit Feather ESP32-S2 with ESP32S2": "ADAFRUIT_FEATHER_ESP32S2",
    "Adafruit Feather ESP32-S3 with ESP32S3": "ADAFRUIT_FEATHER_ESP32S3",
}

#: Concrete callable shape the network layer expects.  Same as
#: :func:`urllib.request.urlopen`'s sync signature.  Tests inject a
#: fake that returns a context manager wrapping in-memory bytes.
UrlOpener = Callable[[str], Any]


class UnresolvableFirmwareError(RuntimeError):
    """Raised when no firmware URL can be derived for a device entry.

    Carries the diagnosis so the CLI can surface a helpful message:

    - ``cause="no_board_id"`` — CP path needs ``hardware.board_id``.
    - ``cause="no_machine"`` — MP path needs ``hardware.machine``.
    - ``cause="machine_not_in_map"`` — MP machine string isn't in
      the curated map, and no ``hardware.firmware_source`` is set.
    - ``cause="no_versions_listed"`` — the S3 bucket returned no
      uf2 keys for the prefix.  Wrong board id, or the language
      isn't published for that board.
    - ``cause="no_stable_versions"`` — the bucket has only
      pre-release versions; pass ``allow_prerelease=True``.
    """

    def __init__(self, message: str, *, cause: str) -> None:
        super().__init__(message)
        self.cause = cause


# ---------------------------------------------------------------------------
# CircuitPython — S3 listing
# ---------------------------------------------------------------------------


def list_circuitpython_versions(
    board_id: str,
    *,
    language: str = "en_US",
    url_opener: UrlOpener | None = None,
) -> list[str]:
    """Fetch the S3 listing and return every published version string.

    Pre-release versions (``10.2.0-rc.0`` etc.) appear alongside
    stable releases.  Filtering happens in
    :func:`latest_circuitpython_version` — this function returns
    everything published, in the order S3 returns it (typically
    chronological-ish, but not guaranteed).

    Args:
        board_id: Adafruit board identifier (e.g.
            ``"raspberry_pi_pico_w"``).
        language: Adafruit language code; default ``"en_US"``.
        url_opener: Inject a fake for tests.  Production callers
            leave it ``None`` and use :func:`urllib.request.urlopen`.

    Raises:
        UnresolvableFirmwareError: The S3 prefix lookup returned no
            ``.uf2`` keys (wrong board id, or the language isn't
            published for that board).
    """
    if not board_id:
        raise UnresolvableFirmwareError(
            "board_id is required for CircuitPython firmware lookup",
            cause="no_board_id",
        )
    opener = url_opener if url_opener is not None else urllib.request.urlopen
    prefix = f"bin/{board_id}/{language}/"
    listing_url = f"{CIRCUITPYTHON_S3_BUCKET_URL}?prefix={prefix}"
    body = _read_url(opener, listing_url)
    versions = _parse_circuitpython_versions(body, prefix=prefix)
    if not versions:
        raise UnresolvableFirmwareError(
            f"S3 listing for prefix {prefix!r} returned no .uf2 keys "
            f"(wrong board id, or language not published for this board)",
            cause="no_versions_listed",
        )
    return versions


def latest_circuitpython_version(
    board_id: str,
    *,
    language: str = "en_US",
    allow_prerelease: bool = False,
    url_opener: UrlOpener | None = None,
) -> str:
    """Pick the newest version from the S3 listing.

    Stable-only by default — pre-releases (``-rc.0``, ``-beta.1``,
    ``-alpha.0`` suffixes) are filtered out unless
    *allow_prerelease* is ``True``.  The user-facing knob matches
    what Adafruit's release pipeline produces.

    Sort order is canonical SemVer-style numeric:
    ``(major, minor, patch)`` ascending; the last element wins.

    Raises:
        UnresolvableFirmwareError: No matching versions after the
            stable filter.
    """
    versions = list_circuitpython_versions(
        board_id, language=language, url_opener=url_opener,
    )
    if allow_prerelease:
        candidates = versions
    else:
        candidates = [version for version in versions if _STABLE_VERSION_PATTERN.match(version)]
    if not candidates:
        raise UnresolvableFirmwareError(
            f"No stable versions found for {board_id!r} "
            f"(pass allow_prerelease=True to include pre-releases)",
            cause="no_stable_versions",
        )
    candidates.sort(key=_version_sort_key)
    return candidates[-1]


def latest_circuitpython_url(
    board_id: str,
    *,
    language: str = "en_US",
    allow_prerelease: bool = False,
    url_opener: UrlOpener | None = None,
) -> str:
    """Return the canonical CDN download URL for the latest version."""
    version = latest_circuitpython_version(
        board_id,
        language=language,
        allow_prerelease=allow_prerelease,
        url_opener=url_opener,
    )
    return CIRCUITPYTHON_DOWNLOAD_TEMPLATE.format(
        board_id=board_id, language=language, version=version,
    )


# ---------------------------------------------------------------------------
# MicroPython — machine → BOARD map
# ---------------------------------------------------------------------------


def micropython_board_for_machine(machine_string: str) -> str | None:
    """Return the published MP BOARD name for *machine_string*, or ``None``.

    Lookup is exact-match against :data:`MICROPYTHON_BOARD_BY_MACHINE`.
    The map is hand-curated; entries appear here as new boards land,
    refreshed from periodic ``micropython.org/download/`` scrapes.
    """
    if not machine_string:
        return None
    return MICROPYTHON_BOARD_BY_MACHINE.get(machine_string)


# ---------------------------------------------------------------------------
# Top-level resolver
# ---------------------------------------------------------------------------


def derive_firmware_url(
    device_entry: Mapping[str, Any],
    *,
    language: str = "en_US",
    allow_prerelease: bool = False,
    url_opener: UrlOpener | None = None,
) -> str:
    """Resolve a firmware URL for *device_entry*.

    Resolution order:

    1. ``hardware.firmware_source`` is set → return it verbatim
       (custom URL or local path; vendor forks live here).
    2. Runtime is ``circuitpython`` → look up
       ``hardware.board_id`` against the S3 bucket and return the
       latest CDN URL.
    3. Runtime is ``micropython`` → look up ``hardware.machine``
       against the curated map.  No MP URL is constructed — the
       caller (CLI) prompts for one and stores it via
       ``hardware.firmware_source`` for next time.

    Args:
        device_entry: A devices.yml device dict (typical fields:
            ``id``, ``runtime``, ``address``, ``hardware``).
        language: CP-only Adafruit language code.
        allow_prerelease: Include CP pre-release versions.
        url_opener: Inject for tests.

    Raises:
        UnresolvableFirmwareError: When no path through the
            resolution order produces a URL.  ``cause`` carries
            which step failed (no_board_id / no_machine /
            machine_not_in_map / no_versions_listed /
            no_stable_versions / unsupported_runtime).
    """
    hardware = device_entry.get("hardware") or {}
    firmware_source = hardware.get("firmware_source")
    if firmware_source:
        return str(firmware_source)

    runtime = device_entry.get("runtime", "")
    if runtime == "circuitpython":
        board_id = hardware.get("board_id", "")
        return latest_circuitpython_url(
            board_id,
            language=language,
            allow_prerelease=allow_prerelease,
            url_opener=url_opener,
        )
    if runtime == "micropython":
        machine_string = hardware.get("machine", "")
        if not machine_string:
            raise UnresolvableFirmwareError(
                "MicroPython firmware lookup needs hardware.machine "
                "(set automatically by `add-device`'s probe; check "
                "that the entry was registered against a live board)",
                cause="no_machine",
            )
        board = micropython_board_for_machine(machine_string)
        if board is None:
            raise UnresolvableFirmwareError(
                f"machine {machine_string!r} is not in the curated "
                "BOARD map.  Set hardware.firmware_source to an "
                "explicit firmware URL (or path) and re-run.",
                cause="machine_not_in_map",
            )
        # We know the BOARD name but not the per-build dated URL.
        # MP's micropython.org listing is the authoritative source;
        # we surface the BOARD name + a hint pointing the user at
        # the listing page so they can paste a URL.
        raise UnresolvableFirmwareError(
            f"MicroPython BOARD={board} resolved from machine "
            f"{machine_string!r}, but micropython.org/download/{board}/ "
            "publishes per-build dated filenames that aren't picked "
            "automatically — paste the .uf2 / .bin URL via "
            "`hardware.firmware_source` to cache it on this entry.",
            cause="no_micropython_dated_url",
        )
    raise UnresolvableFirmwareError(
        f"unsupported runtime {runtime!r} (expected 'circuitpython' "
        "or 'micropython')",
        cause="unsupported_runtime",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_url(opener: UrlOpener, url: str) -> bytes:
    """Open *url* via *opener* and read the full body."""
    with opener(url) as response:
        return response.read()


def _parse_circuitpython_versions(body: bytes, *, prefix: str) -> list[str]:
    """Pull version strings out of an S3 ``ListBucketResult`` body.

    Walks every ``Contents/Key`` element, filters to keys that
    start with *prefix* and end in ``.uf2``, extracts the version
    via :data:`_CIRCUITPYTHON_FILENAME_VERSION`.  Duplicates are
    de-duplicated while preserving first-seen order.

    Raises XML parse errors back to the caller as-is so a malformed
    bucket response is loud rather than silently empty.
    """
    root = ElementTree.fromstring(body)
    seen: set[str] = set()
    versions: list[str] = []
    for contents in root.findall(f"{_S3_NS}Contents"):
        key_element = contents.find(f"{_S3_NS}Key")
        if key_element is None or key_element.text is None:
            continue
        key = key_element.text
        if not key.startswith(prefix) or not key.endswith(".uf2"):
            continue
        match = _CIRCUITPYTHON_FILENAME_VERSION.search(key)
        if match is None:
            continue
        version = match.group("version")
        if version in seen:
            continue
        seen.add(version)
        versions.append(version)
    return versions


def _version_sort_key(version: str) -> tuple[int, int, int, int, int, int]:
    """Sort key for SemVer-shaped version strings.

    Stable releases (``10.1.4``) sort as ``(10, 1, 4, 1, 0, 0)`` —
    the ``1`` in slot 4 lifts them above any pre-release of the
    same base version.  Pre-releases (``10.2.0-rc.0``) sort as
    ``(10, 2, 0, 0, <label-rank>, <label-index>)`` so
    ``rc > beta > alpha`` orders cleanly.  Unknown pre-release
    labels rank below ``alpha``.
    """
    base, _, prerelease = version.partition("-")
    base_parts = [_safe_int(part) for part in base.split(".")]
    while len(base_parts) < 3:
        base_parts.append(0)
    major, minor, patch = base_parts[0], base_parts[1], base_parts[2]

    if not prerelease:
        return (major, minor, patch, 1, 0, 0)

    label, _, label_index = prerelease.partition(".")
    label_rank = {"alpha": -3, "beta": -2, "rc": -1}.get(label, -10)
    label_index_int = _safe_int(label_index) if label_index else 0
    return (major, minor, patch, 0, label_rank, label_index_int)


def _safe_int(text: str) -> int:
    """Best-effort int parse; returns 0 on non-numeric input."""
    try:
        return int(text)
    except ValueError:
        return 0
