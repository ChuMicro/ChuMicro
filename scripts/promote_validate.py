"""Parse + validate an experimental tag for promotion to stable.

Reads ``$TAG``, parses ``chumicro-<name>-v<version>-experimental``, locates
the source package under ``libraries/<name>/`` or ``workbench/<name>/``,
and verifies promotion preconditions: experimental tag exists, stable tag
does not, source archive is attached to the experimental GitHub Release.

Usage::

    TAG=chumicro-timing-v0.3.0-experimental python scripts/promote_validate.py

Writes ``library_name``, ``version``, ``stable_tag``, ``source_zip``,
``library_dir``, and ``package_kind`` to ``$GITHUB_OUTPUT`` when set,
otherwise to stdout in ``key=value`` format.  Exits non-zero on a
malformed tag, missing source package, or unmet preconditions.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

from repo_layout import ROOT

#: Strict regex for experimental tags.  The promote workflow only accepts
#: tags created by release.yml's experimental path.
_TAG_PATTERN = re.compile(
    r"^chumicro-(?P<library_name>[a-z][a-z0-9_-]*)-v(?P<version>\d+\.\d+\.\d+)-experimental$",
)


class PromoteValidationError(RuntimeError):
    """Raised when the experimental tag or preconditions are invalid."""


def _parse_tag(tag: str) -> dict[str, str]:
    """Return library_name / version / stable_tag / source_zip for a valid tag."""
    match = _TAG_PATTERN.match(tag)
    if match is None:
        raise PromoteValidationError(
            "Expected an experimental tag "
            f"(e.g. chumicro-timing-v0.3.0-experimental), got {tag!r}.",
        )
    library_name = match.group("library_name")
    version = match.group("version")
    return {
        "library_name": library_name,
        "version": version,
        "stable_tag": f"chumicro-{library_name}-v{version}",
        "source_zip": f"chumicro-{library_name}-v{version}-source.zip",
    }


def _locate_package(library_name: str) -> dict[str, str]:
    """Return library_dir + package_kind for the package being promoted."""
    library_path = ROOT / "libraries" / library_name
    workbench_path = ROOT / "workbench" / library_name

    if library_path.is_dir():
        return {
            "library_dir": f"libraries/{library_name}",
            "package_kind": "library",
        }
    if workbench_path.is_dir():
        return {
            "library_dir": f"workbench/{library_name}",
            "package_kind": "workbench",
        }
    raise PromoteValidationError(
        f"No package found at libraries/{library_name}/ or workbench/{library_name}/.",
    )


def _tag_exists(tag: str) -> bool:
    """Return whether the given git ref exists."""
    result = subprocess.run(
        ["git", "rev-parse", f"refs/tags/{tag}"],
        capture_output=True,
        cwd=ROOT,
        check=False,
    )
    return result.returncode == 0


def _release_has_source_archive(tag: str, source_zip: str) -> bool:
    """Return whether the experimental release carries the source archive."""
    result = subprocess.run(
        ["gh", "release", "view", tag, "--json", "assets", "-q", ".assets[].name"],
        capture_output=True,
        cwd=ROOT,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        return False
    return source_zip in result.stdout.splitlines()


def _check_preconditions(experimental_tag: str, parsed: dict[str, str]) -> None:
    """Raise if any precondition is unmet."""
    if not _tag_exists(experimental_tag):
        raise PromoteValidationError(
            f"Experimental tag {experimental_tag} does not exist.",
        )
    if _tag_exists(parsed["stable_tag"]):
        raise PromoteValidationError(
            f"Stable tag {parsed['stable_tag']} already exists.",
        )
    if not _release_has_source_archive(experimental_tag, parsed["source_zip"]):
        raise PromoteValidationError(
            f"Source archive {parsed['source_zip']} not found in release {experimental_tag}.  "
            f"Was the experimental release created before Decision 0023?",
        )


def _write_outputs(outputs: dict[str, str]) -> None:
    """Write key=value lines to $GITHUB_OUTPUT or stdout."""
    payload = "".join(f"{key}={value}\n" for key, value in outputs.items())
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with Path(github_output).open("a", encoding="utf-8") as handle:
            handle.write(payload)
    else:
        sys.stdout.write(payload)


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Parse + validate an experimental tag for promotion.",
    )
    parser.add_argument(
        "--tag", default=os.environ.get("TAG", ""),
        help="Experimental tag (default: $TAG environment variable).",
    )
    parser.add_argument(
        "--skip-release-check", action="store_true",
        help="Skip the gh-release source-archive check (for tests).",
    )
    args = parser.parse_args(argv)

    if not args.tag:
        print("::error::No tag provided (set --tag or $TAG).", file=sys.stderr)
        return 1

    try:
        parsed = _parse_tag(args.tag)
        located = _locate_package(parsed["library_name"])
        if not args.skip_release_check:
            _check_preconditions(args.tag, parsed)
    except PromoteValidationError as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1

    outputs = {**parsed, **located}
    _write_outputs(outputs)
    print(
        f"✓ Promoting {parsed['library_name']} v{parsed['version']} "
        f"from experimental to stable ({located['package_kind']})",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
