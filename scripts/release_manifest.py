"""Project a release into the channel's ``releases.json`` correlation index.

A release stamps three identifiers that nothing otherwise ties together
(Decision 0112): PyPI semver per package, the device-bundle date tag, and
the libraries-channel timestamp tag.  This maintains one cumulative index,
served from the bundle repo at a stable raw URL the same way the libraries
channel serves ``index.json`` (Decision 0078), so a bundle or libraries tag
resolves to the exact package versions it carries and a package version
resolves back to the snapshots that shipped it.

It is a lookup laid over the independent channels (Decision 0101), not a
version solver: the release already computes every field (the release
matrix, the two channel tags), so this only writes them down.

Index shape (newest release first)::

    {
      "releases": [
        {
          "channel": "experimental",
          "bundle_tag": "20260718",
          "libraries_tag": "20260718.153658",
          "published_at": "2026-07-18T15:38:00Z",
          "packages": {"http_server": "0.18.1", "wifi": "0.8.0"}
        }
      ]
    }

Usage::

    python scripts/release_manifest.py \
        --index .bundle-repo/releases.json \
        --channel experimental \
        --matrix "$LIBRARY_MATRIX_JSON" \
        --bundle-tag 20260718 \
        --libraries-tag 20260718.153658 \
        --published-at 2026-07-18T15:38:00Z
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

#: One entry per (channel, bundle_tag): a re-run with the same bundle tag
#: replaces its entry in place rather than appending a duplicate, so the
#: index stays idempotent under the workflow's re-run safety.
INDEX_KEY = ("channel", "bundle_tag")


def build_entry(
    matrix: dict,
    channel: str,
    bundle_tag: str,
    libraries_tag: str,
    published_at: str,
) -> dict:
    """Return one release-index entry from the release matrix and tags.

    Args:
        matrix: The release matrix (``{"include": [{library_name, version,
            ...}]}``) — the library-only matrix, since only library releases
            produce a bundle and libraries snapshot.
        channel: ``"experimental"`` or ``"stable"``.
        bundle_tag: The device-bundle snapshot tag (e.g. ``"20260718"``).
        libraries_tag: The libraries-channel snapshot tag.
        published_at: An ISO-8601 UTC timestamp for the release.
    """
    packages = {
        entry["library_name"]: entry["version"]
        for entry in matrix.get("include", [])
    }
    return {
        "channel": channel,
        "bundle_tag": bundle_tag,
        "libraries_tag": libraries_tag,
        "published_at": published_at,
        "packages": packages,
    }


def update_index(existing: dict | None, entry: dict) -> dict:
    """Return the index with *entry* inserted, newest first, de-duplicated.

    An entry matching *entry* on :data:`INDEX_KEY` is replaced in place (a
    re-run of the same release rewrites its row); otherwise the entry is
    added.  The result is sorted by ``published_at`` descending so the most
    recent release reads first.

    Args:
        existing: The current index, or ``None`` / ``{}`` for a fresh one.
        entry: The entry from :func:`build_entry`.
    """
    releases = list((existing or {}).get("releases", []))
    key = tuple(entry[field] for field in INDEX_KEY)
    kept = [
        release
        for release in releases
        if tuple(release.get(field) for field in INDEX_KEY) != key
    ]
    kept.append(entry)
    kept.sort(key=lambda release: release.get("published_at", ""), reverse=True)
    return {"releases": kept}


def _load_index(index_path: Path) -> dict | None:
    """Return the parsed index at *index_path*, or ``None`` when absent."""
    if not index_path.is_file():
        return None
    return json.loads(index_path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Update a channel's releases.json correlation index.",
    )
    parser.add_argument("--index", required=True, help="Path to releases.json.")
    parser.add_argument(
        "--channel", required=True, choices=("experimental", "stable"),
    )
    parser.add_argument(
        "--matrix", required=True,
        help="The library release matrix JSON ({\"include\": [...]}).",
    )
    parser.add_argument("--bundle-tag", required=True)
    parser.add_argument("--libraries-tag", required=True)
    parser.add_argument(
        "--published-at", required=True,
        help="ISO-8601 UTC timestamp (the workflow passes `date -u`).",
    )
    args = parser.parse_args(argv)

    # argparse's `required` only proves the flag was passed, and every tag
    # here arrives as a workflow expression: an unset job output, a renamed
    # step id, or a skipped upstream job all expand to the empty string
    # rather than failing.  Without this check the run records a row keyed
    # on "" and prints a success line, which reads as a published manifest
    # while resolving nothing -- the same silent-success shape as a docs
    # job that commits and never pushes.
    for flag, value in (
        ("--bundle-tag", args.bundle_tag),
        ("--libraries-tag", args.libraries_tag),
        ("--published-at", args.published_at),
    ):
        if not value.strip():
            parser.error(
                f"{flag} is empty.  It comes from a workflow job output; "
                "check that the producing job ran and still exports it.",
            )

    matrix = json.loads(args.matrix)
    entry = build_entry(
        matrix,
        args.channel,
        args.bundle_tag,
        args.libraries_tag,
        args.published_at,
    )
    # An entry with no packages correlates nothing.  The workflows gate this
    # job on having library releases, so an empty matrix here means that gate
    # and this call disagree; say so instead of committing a hollow row.
    if not entry["packages"]:
        parser.error(
            "--matrix carries no packages, so there is nothing to correlate.  "
            "This job should be gated on the channel having library releases.",
        )
    index_path = Path(args.index)
    index = update_index(_load_index(index_path), entry)
    # Trailing newline so the committed file is POSIX-clean and diffs sanely.
    index_path.write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    print(
        f"release-manifest: recorded {args.channel} {args.bundle_tag} "
        f"({len(entry['packages'])} package(s)) in {index_path}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
