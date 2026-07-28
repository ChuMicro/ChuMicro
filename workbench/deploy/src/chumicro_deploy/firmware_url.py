"""Firmware URL derivation for CircuitPython and MicroPython boards.

CircuitPython URLs come from listing the Adafruit S3 bucket and
picking the latest stable build.  MicroPython URLs come from
scraping ``micropython.org/download/<BOARD>/`` and picking the most
recent build of the latest stable version, with the reported
``machine`` string mapped to a published BOARD name via the curated
:data:`MICROPYTHON_BOARD_BY_MACHINE` table.  A device entry with
``hardware.firmware_source`` set short-circuits both lookups and is
returned verbatim, which covers vendor builds and local firmware.

Network calls go through an injectable ``url_opener`` so parsing
and version-picking logic runs without hitting the real bucket or
download page.
"""

from __future__ import annotations

import re
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any
from xml.etree import ElementTree

#: S3 bucket where Adafruit publishes CircuitPython firmware.  The
#: front-end CDN at ``downloads.circuitpython.org`` strips query
#: parameters, so we hit the bucket directly for listing.
CIRCUITPYTHON_S3_BUCKET_URL = "https://adafruit-circuit-python.s3.amazonaws.com/"

#: URL template for the CircuitPython firmware download.  Adafruit's
#: CDN serves the firmware blobs with lower latency than the S3
#: bucket the listing comes from.
CIRCUITPYTHON_FIRMWARE_URL_TEMPLATE = (
    "https://downloads.circuitpython.org/bin/{board_id}/{language}/"
    "adafruit-circuitpython-{board_id}-{language}-{version}.uf2"
)

#: S3 ``ListBucketResult`` XML namespace.  Every element in the
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
#: pre-release label.  See :data:`_CIRCUITPYTHON_FILENAME_VERSION` for
#: the pre-release-suffix grammar this filter excludes.
_STABLE_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")

#: Hand-curated subset of the MicroPython ``machine`` → BOARD map.
#: Boards not in this table return ``None`` from
#: :func:`micropython_board_for_machine`.
#:
#: Vendor-published Adafruit boards (Feather ESP32-S2 / S3 etc.)
#: deliberately *aren't* in the map: Adafruit ships their own
#: MicroPython builds outside ``micropython.org/download/``, so a
#: scrape against the upstream URL 404s.  Set
#: ``hardware.firmware_source`` on those entries to point at the
#: vendor build.
MICROPYTHON_BOARD_BY_MACHINE: dict[str, str] = {
    "Raspberry Pi Pico W with rp2040": "RPI_PICO_W",
    "Raspberry Pi Pico with rp2040": "RPI_PICO",
    "Raspberry Pi Pico 2 W with rp2350": "RPI_PICO2_W",
    "Raspberry Pi Pico 2 with rp2350": "RPI_PICO2",
    "ESP32-S2 module with ESP32S2": "ESP32_GENERIC_S2",
    "ESP32-S3 module with ESP32S3": "ESP32_GENERIC_S3",
    "ESP32 module with ESP32": "ESP32_GENERIC",
}

#: Concrete callable shape the network layer expects.  Same as
#: :func:`urllib.request.urlopen`'s sync signature.  A conforming
#: fake returns a context manager wrapping in-memory bytes.
UrlOpener = Callable[[str], Any]


class UnresolvedFirmwareError(Exception):
    """Raised when no firmware URL can be derived for the inputs.

    Carries the diagnosis so the CLI can surface a helpful message:

    - ``cause="no_board_id"``: CP path needs ``hardware.board_id``
      (or :func:`resolve_firmware_url` was called with empty
      ``board_id``).
    - ``cause="no_version"``: :func:`resolve_firmware_url` was
      called with an empty ``version`` argument.
    - ``cause="no_machine"``: MP path needs ``hardware.machine``.
    - ``cause="machine_not_in_map"``: MP machine string isn't in
      the curated map, and no ``hardware.firmware_source`` is set.
    - ``cause="no_versions_listed"``: the S3 bucket returned no
      uf2 keys for the prefix.  Wrong board id, or the language
      isn't published for that board.
    - ``cause="no_stable_versions"``: the listing has only
      pre-release / unstable versions.  Pass ``allow_prerelease=True``.
    - ``cause="no_mp_builds_listed"``: the
      ``micropython.org/download/<BOARD>/`` page returned no parsable
      firmware anchors.  Likely a wrong BOARD name or a board that
      moved upstream.
    - ``cause="unsupported_runtime"``: runtime isn't ``circuitpython``
      or ``micropython``.
    - ``cause="micropython_needs_listing"``: caller invoked
      :func:`resolve_firmware_url` (the pure URL formatter) with
      runtime=micropython, which embeds a per-build date that can't
      be inferred from version alone.  Use
      :func:`derive_firmware_url` or :func:`latest_micropython_url`
      for the listing-based path instead.
    """

    def __init__(self, message: str, *, cause: str = "") -> None:
        super().__init__(message)
        self.cause = cause


# ---------------------------------------------------------------------------
# CircuitPython: S3 listing
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
    :func:`latest_circuitpython_version`.  This function returns
    everything published, in the order S3 returns it (typically
    chronological-ish, but not guaranteed).

    Args:
        board_id: Adafruit board identifier (e.g.
            ``"raspberry_pi_pico_w"``).
        language: Adafruit language code; default ``"en_US"``.
        url_opener: Injectable network opener.  When ``None``, uses
            :func:`urllib.request.urlopen`.

    Raises:
        UnresolvedFirmwareError: The S3 prefix lookup returned no
            ``.uf2`` keys (wrong board id, or the language isn't
            published for that board).
    """
    if not board_id:
        raise UnresolvedFirmwareError(
            "board_id is required for CircuitPython firmware lookup",
            cause="no_board_id",
        )
    opener = url_opener if url_opener is not None else urllib.request.urlopen
    prefix = f"bin/{board_id}/{language}/"
    listing_url = f"{CIRCUITPYTHON_S3_BUCKET_URL}?prefix={prefix}"
    body = _read_url(opener, listing_url)
    versions = _parse_circuitpython_versions(body, prefix=prefix)
    if not versions:
        raise UnresolvedFirmwareError(
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

    Stable-only by default.  Pre-releases (``-rc.0``, ``-beta.1``,
    ``-alpha.0`` suffixes) are filtered out unless
    *allow_prerelease* is ``True``.  The user-facing knob matches
    what Adafruit's release pipeline produces.

    Sort order is SemVer-style numeric:
    ``(major, minor, patch)`` ascending, and the last element wins.

    Raises:
        UnresolvedFirmwareError: No matching versions after the
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
        raise UnresolvedFirmwareError(
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
    """Return the CDN download URL for the latest version."""
    version = latest_circuitpython_version(
        board_id,
        language=language,
        allow_prerelease=allow_prerelease,
        url_opener=url_opener,
    )
    return CIRCUITPYTHON_FIRMWARE_URL_TEMPLATE.format(
        board_id=board_id, language=language, version=version,
    )


# ---------------------------------------------------------------------------
# MicroPython: machine → BOARD map
# ---------------------------------------------------------------------------


def micropython_board_for_machine(machine_string: str) -> str | None:
    """Return the published MP BOARD name for *machine_string*, or ``None``.

    Lookup is exact-match against :data:`MICROPYTHON_BOARD_BY_MACHINE`,
    a hand-curated map.
    """
    if not machine_string:
        return None
    return MICROPYTHON_BOARD_BY_MACHINE.get(machine_string)


# ---------------------------------------------------------------------------
# MicroPython: micropython.org listing scrape
# ---------------------------------------------------------------------------

#: micropython.org's per-board download landing page URL.  Stable
#: shape; the page lists every published build for the board with
#: anchors pointing at firmware files under ``/resources/firmware/``.
MICROPYTHON_DOWNLOAD_URL_TEMPLATE = "https://micropython.org/download/{board}/"

#: Resolves relative anchors (``/resources/firmware/...``) into
#: absolute download URLs.  micropython.org serves the firmware
#: blobs from the same origin as the listing.
MICROPYTHON_FIRMWARE_BASE_URL = "https://micropython.org"

#: Pattern that pulls the date + version out of an MP firmware
#: filename.  MP's filename grammar::
#:
#:     <BOARD>-<DATE>-<VERSION>.<ext>                       # stable
#:     <BOARD>-<DATE>-<VERSION>-<PRERELEASE>.<ext>          # newer preview shape
#:     <BOARD>-<DATE>-unstable-<VERSION>-<COMMIT>.<ext>     # legacy unstable shape
#:
#: where:
#:   - ``<BOARD>`` is upper-snake-case (``RPI_PICO_W``); on ESP32
#:     family ports it can carry feature suffixes like
#:     ``ESP32_GENERIC_S3-SPIRAM_OCT``.
#:   - ``<DATE>`` is YYYYMMDD (e.g. ``20240222``).
#:   - ``<VERSION>`` is ``v1.22.2`` for stable;
#:     ``v1.29.0-preview.69.g8a56be6660`` for a preview build (newer
#:     shape, no leading ``unstable-``).  Legacy builds prepend
#:     ``unstable-`` and append a commit suffix
#:     (e.g. ``unstable-v1.23.0-preview-32-g1a2b3c4d5``).
#:   - ``<ext>`` is one of ``uf2`` / ``bin`` / ``hex`` / ``elf``
#:     / ``dfu``.
#:
#: Capture groups: ``date`` (8 digits), ``unstable`` ("unstable-" or
#: empty, the legacy marker), ``version`` (the ``v1.x.y`` portion),
#: ``prerelease`` (the post-version ``-preview.69.gSHA``-shaped
#: suffix; empty for stable builds), ``ext`` (filename extension).
_MICROPYTHON_FILENAME_PATTERN = re.compile(
    r"(?P<date>\d{8})-"
    r"(?P<unstable>unstable-)?"
    r"(?P<version>v\d+\.\d+(?:\.\d+)?)"
    r"(?P<prerelease>-[A-Za-z0-9.-]+)?"
    r"\.(?P<ext>uf2|bin|hex|elf|dfu)",
)

#: Pattern that picks <a href="..."> values out of a typical MP
#: download listing.  Browsers tolerate single-quoted, unquoted, and
#: attribute-order-shuffled HTML, but the upstream page is well-formed
#: enough that a forgiving regex is plenty, and we don't want a full
#: HTML parser dep just for this.  Uses case-insensitive matching for
#: the ``HREF=`` form.
_HTML_HREF_PATTERN = re.compile(
    r"""<a\b[^>]*\bhref\s*=\s*(?P<quote>["'])(?P<url>[^"']+)(?P=quote)""",
    re.IGNORECASE,
)

#: Pattern for stable MP versions: ``v<major>.<minor>(.<patch>)?``
#: with no pre-release suffix.  ``v1.22.2`` matches; ``v1.23.0-preview``
#: doesn't.  The optional patch handles the historical ``v1.20`` /
#: ``v1.21`` releases that omit the patch field.
_MP_STABLE_VERSION_PATTERN = re.compile(r"^v\d+\.\d+(?:\.\d+)?$")


def list_micropython_builds(
    board: str,
    *,
    url_opener: UrlOpener | None = None,
    file_extension: str = "uf2",
) -> list[tuple[str, str, str, str, str]]:
    """Scrape ``micropython.org/download/<board>/`` for firmware builds.

    Returns ``(date, version, unstable_marker, prerelease_suffix,
    absolute_url)`` tuples for every published build whose filename
    matches :data:`_MICROPYTHON_FILENAME_PATTERN` and ends in the
    requested *file_extension*.  ``date`` is YYYYMMDD.  ``version`` is
    the raw ``v1.x.y`` (or ``v1.x``) portion.  ``unstable_marker`` is
    ``"unstable-"`` for legacy unstable builds (empty for stable +
    new-shape preview).  ``prerelease_suffix`` is ``"-preview.69.gSHA"``
    or similar for new-shape preview builds (empty for stable).
    A build is "stable" iff both markers are empty.

    Order follows the order anchors appear in the page (newest
    first, by convention).  Sort downstream when ordering matters,
    since the listing's order is not guaranteed.

    Args:
        board: Upper-snake-case BOARD name (``"RPI_PICO_W"``).
            See :data:`MICROPYTHON_BOARD_BY_MACHINE` for the
            machine-string ↔ BOARD mapping.
        file_extension: Filter to firmware files with this
            extension.  Defaults to ``"uf2"``; pass ``"bin"`` for
            ESP32 / ESP32-Sx, ``"hex"`` for older MicroPython
            ports, etc.  Strip the leading dot.
        url_opener: Injectable network opener.  When ``None``, uses
            :func:`urllib.request.urlopen`.

    Raises:
        UnresolvedFirmwareError: ``board`` is empty, or the page
            returned no parsable firmware anchors for the chosen
            file extension.
    """
    if not board:
        raise UnresolvedFirmwareError(
            "BOARD is required for MicroPython firmware lookup",
            cause="no_machine",
        )
    opener = url_opener if url_opener is not None else urllib.request.urlopen
    listing_url = MICROPYTHON_DOWNLOAD_URL_TEMPLATE.format(board=board)
    body = _read_url(opener, listing_url)
    builds = _parse_micropython_builds(
        body, board=board, file_extension=file_extension,
    )
    if not builds:
        raise UnresolvedFirmwareError(
            f"micropython.org/download/{board}/ returned no .{file_extension} "
            f"build anchors (wrong BOARD name, board moved upstream, or this "
            f"port doesn't publish .{file_extension} firmware; try another "
            f"file_extension).",
            cause="no_mp_builds_listed",
        )
    return builds


def latest_micropython_url(
    board: str,
    *,
    allow_prerelease: bool = False,
    file_extension: str = "uf2",
    url_opener: UrlOpener | None = None,
) -> str:
    """Pick the most recent MP build for *board* and return its URL.

    Stable-only by default.  Unstable / preview builds are filtered
    out unless *allow_prerelease* is ``True``.  Sort is by
    ``(version, date)`` with the newest pair winning, so an old-
    date build of a newer version doesn't lose to a recent build
    of an older version.

    Raises:
        UnresolvedFirmwareError: No matching builds after the
            stable filter (``cause="no_stable_versions"``) or no
            anchors at all (``cause="no_mp_builds_listed"``).
    """
    builds = list_micropython_builds(
        board, url_opener=url_opener, file_extension=file_extension,
    )
    if allow_prerelease:
        candidates = builds
    else:
        # Stable iff: no `unstable-` legacy prefix (build[2]),
        # no `-preview.X.gSHA` new-shape suffix (build[3]), and the
        # version itself is the bare `vN.M(.P)?` shape.
        candidates = [
            build for build in builds
            if not build[2]
            and not build[3]
            and _MP_STABLE_VERSION_PATTERN.match(build[1]) is not None
        ]
    if not candidates:
        raise UnresolvedFirmwareError(
            f"No stable MicroPython builds found for {board!r} "
            "(pass allow_prerelease=True to include unstable / preview).",
            cause="no_stable_versions",
        )
    candidates.sort(key=_micropython_build_sort_key)
    return candidates[-1][4]


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

    1. When ``hardware.firmware_source`` is set, return it verbatim
       (custom URL or local path, vendor forks live here).
    2. When the runtime is ``circuitpython``, query the Adafruit S3
       bucket for ``hardware.board_id`` and return the latest CDN URL.
    3. When the runtime is ``micropython``, map ``hardware.machine``
       to a curated board name, then return the latest
       micropython.org download URL for that board (the file
       extension honors ``hardware.firmware_extension`` and defaults
       to ``.uf2``).  When ``hardware.machine`` is unset or not in
       the curated map, raises so the caller can set an explicit
       ``hardware.firmware_source``.

    Args:
        device_entry: A devices.yml device dict (typical fields:
            ``id``, ``runtime``, ``address``, ``hardware``).
        language: CP-only Adafruit language code.
        allow_prerelease: Include CP pre-release versions.
        url_opener: Injectable network opener.  When ``None``, uses
            :func:`urllib.request.urlopen`.

    Raises:
        UnresolvedFirmwareError: When no path through the
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
            raise UnresolvedFirmwareError(
                "MicroPython firmware lookup needs hardware.machine "
                "(set automatically by `add-device`'s probe; check "
                "that the entry was registered against a live board)",
                cause="no_machine",
            )
        board = micropython_board_for_machine(machine_string)
        if board is None:
            raise UnresolvedFirmwareError(
                f"machine {machine_string!r} is not in the curated "
                "BOARD map.  Set hardware.firmware_source to an "
                "explicit firmware URL (or path) and re-run.",
                cause="machine_not_in_map",
            )
        # `hardware.firmware_extension` overrides the default `.uf2`
        # for boards whose port doesn't publish UF2 (ESP32 family →
        # `.bin`, micro:bit → `.hex`).  Falls back to "uf2" when
        # absent, which covers RP2040 / RP2350 / SAMD51 / nRF52840
        # / TinyUF2, the majority of the boards the workspace
        # template targets.
        file_extension = hardware.get("firmware_extension") or "uf2"
        return latest_micropython_url(
            board,
            allow_prerelease=allow_prerelease,
            file_extension=file_extension,
            url_opener=url_opener,
        )
    raise UnresolvedFirmwareError(
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
    via :data:`_CIRCUITPYTHON_FILENAME_VERSION`.  Drops duplicate
    version strings while preserving first-seen order.

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

    Stable releases (``10.1.4``) sort as ``(10, 1, 4, 1, 0, 0)``.
    The ``1`` in slot 4 lifts them above any pre-release of the
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


def _parse_micropython_builds(
    body: bytes,
    *,
    board: str,
    file_extension: str,
) -> list[tuple[str, str, str, str, str]]:
    """Walk the HTML body, yield 5-tuples for every parseable build.

    Tuple shape: ``(date, version, unstable_marker, prerelease_suffix, url)``.

    Two-pass: pull every ``<a href=...>`` value with
    :data:`_HTML_HREF_PATTERN`, then filter to the ones whose
    URL filename matches :data:`_MICROPYTHON_FILENAME_PATTERN`
    against the requested *file_extension* and is namespaced by
    *board* (the URL must contain ``/<BOARD>-``).

    Anchors that don't decode as UTF-8 are skipped.  micropython.org
    serves UTF-8, so failure here means the response was something
    other than an HTML page (a redirect-loop body, a 404 placeholder
    served as 200 etc.).

    De-duplicates while preserving first-seen order, because listing
    pages sometimes repeat the same build under multiple sections.
    """
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return []

    seen_urls: set[str] = set()
    builds: list[tuple[str, str, str, str, str]] = []
    expected_filename_prefix = "/" + board + "-"
    for href_match in _HTML_HREF_PATTERN.finditer(text):
        url = href_match.group("url")
        if expected_filename_prefix not in url:
            continue
        if not url.endswith("." + file_extension):
            continue
        absolute = (
            url
            if url.startswith(("http://", "https://"))
            else MICROPYTHON_FIRMWARE_BASE_URL + url
        )
        if absolute in seen_urls:
            continue
        filename_match = _MICROPYTHON_FILENAME_PATTERN.search(url)
        if filename_match is None:
            continue
        if filename_match.group("ext") != file_extension:
            continue
        seen_urls.add(absolute)
        builds.append((
            filename_match.group("date"),
            filename_match.group("version"),
            filename_match.group("unstable") or "",
            filename_match.group("prerelease") or "",
            absolute,
        ))
    return builds


def _micropython_build_sort_key(
    build: tuple[str, str, str, str, str],
) -> tuple[int, int, int, int, int]:
    """Sort key: ``(version_major, version_minor, version_patch, date, stable_rank)``.

    Stable wins over unstable at the same version+date.  stable_rank
    is ``1`` for stable, ``0`` for unstable, so the last-element-wins
    comparison picks the stable build.

    Unparseable version components fall back to ``0`` so a
    malformed entry sorts below well-formed ones rather than
    raising.
    """
    date_string, version_string, unstable_marker, prerelease_suffix, _url = build
    raw_version = version_string.lstrip("v")
    parts = raw_version.split(".")
    while len(parts) < 3:
        parts.append("0")
    major = _safe_int(parts[0])
    minor = _safe_int(parts[1])
    patch = _safe_int(parts[2])
    date_int = _safe_int(date_string)
    # Stable iff neither the legacy `unstable-` prefix nor the new-
    # shape `-preview.X.gSHA` suffix is present.  Stable wins over
    # preview at the same version + date.
    stable_rank = 0 if (unstable_marker or prerelease_suffix) else 1
    return (major, minor, patch, date_int, stable_rank)
