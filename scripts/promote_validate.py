"""Parse + validate an experimental tag for promotion to stable.

Reads ``$TAG``, parses ``chumicro-<name>-v<version>-experimental``, locates
the source package under ``libraries/<name>/`` or ``workbench/<name>/``,
and verifies promotion preconditions: experimental tag exists, stable tag
does not, source archive is attached to the experimental GitHub Release,
and the version is newer than the newest existing stable release.

Two flags relax preconditions for exceptional promotions:

- ``--allow-downgrade`` (or ``$ALLOW_DOWNGRADE=true``) suppresses the
  version-monotonicity guard for hotfix promotions that intentionally
  republish an older version as stable.
- ``--resume`` (or ``$RESUME=true``) inverts the stable-tag precondition:
  the stable tag must EXIST, so a promotion that died after the tag write
  can be re-dispatched end to end (every downstream leg is idempotent).

The flags compose: a resumed promotion that has since been superseded by
a newer stable release still trips the monotonicity guard (finishing it
would downgrade the bundle and docs), and adding ``--allow-downgrade``
is the deliberate override for exactly that recovery.

Usage::

    TAG=chumicro-timing-v0.3.0-experimental python scripts/promote_validate.py

Writes ``library_name``, ``version``, ``stable_tag``, ``source_zip``,
``library_dir``, ``package_kind``, and ``has_docs`` to ``$GITHUB_OUTPUT``
when set, otherwise to stdout in ``key=value`` format.  Exits non-zero on
a malformed tag, missing source package, or unmet preconditions.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

from repo_layout import ROOT, release_tags, run_git

#: Strict regex for experimental tags.  The promote workflow only accepts
#: tags created by release.yml's experimental path.
_TAG_PATTERN = re.compile(
    r"^chumicro-(?P<library_name>[a-z][a-z0-9_-]*)-v(?P<version>\d+\.\d+\.\d+)-experimental$",
)

#: Bare numeric version portion of a stable tag (e.g. ``1.10.0``).  A tag
#: whose version portion doesn't match (another package sharing the glob
#: prefix) is not a stable release of this package.
_STABLE_VERSION_PATTERN = re.compile(r"^\d+(\.\d+)*$")


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
    """Return library_dir + package_kind for the package being promoted.

    Support packages (``support/``) promote as ``kind=support``: PyPI
    only, no device bundle, the same shape as workbench (Decision 0111).
    The bundle, libraries-channel, and mip-validate jobs gate on
    ``package_kind == 'library'``, so a non-library kind skips them.
    """
    for parent, kind in (
        ("libraries", "library"),
        ("workbench", "workbench"),
        ("support", "support"),
    ):
        if (ROOT / parent / library_name).is_dir():
            return {
                "library_dir": f"{parent}/{library_name}",
                "package_kind": kind,
            }
    raise PromoteValidationError(
        f"No package found at libraries/, workbench/, or support/ for {library_name!r}.",
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


def _check_preconditions(
    experimental_tag: str, parsed: dict[str, str], *, resume: bool = False,
) -> None:
    """Raise if any precondition is unmet.

    Args:
        experimental_tag: The experimental tag being promoted.
        parsed: Output of :func:`_parse_tag` for that tag.
        resume: Invert the stable-tag precondition: a resumed promotion
            already wrote the stable tag, so it must exist rather than
            be absent.
    """
    if not _tag_exists(experimental_tag):
        raise PromoteValidationError(
            f"Experimental tag {experimental_tag} does not exist.",
        )
    stable_exists = _tag_exists(parsed["stable_tag"])
    if resume and not stable_exists:
        raise PromoteValidationError(
            f"resume requires stable tag {parsed['stable_tag']} to exist, but it does not.  "
            "resume is only for re-running a promotion that died after the tag write; "
            "run a normal promotion instead.",
        )
    if not resume and stable_exists:
        raise PromoteValidationError(
            f"Stable tag {parsed['stable_tag']} already exists.  Promoting through "
            "promote.yml drops an already-promoted package from the wave instead; "
            "pass include_tagged to re-publish it deliberately.",
        )
    if not _release_has_source_archive(experimental_tag, parsed["source_zip"]):
        raise PromoteValidationError(
            f"Source archive {parsed['source_zip']} not found in release {experimental_tag}.  "
            f"Was the experimental release created before Decision 0023?",
        )


def _parse_version(version: str) -> tuple[int, ...]:
    """Return a numerically comparable tuple for a dotted version string."""
    return tuple(int(part) for part in version.split("."))


def _newest_stable_version(library_name: str, *, exclude_tag: str | None = None) -> str | None:
    """Return the highest released stable version, or ``None`` when none exist.

    Args:
        library_name: Package basename (e.g. ``"timing"``).
        exclude_tag: Stable tag to leave out of the comparison.  A resumed
            promotion's own stable tag already exists and must not count
            as the release it is compared against.
    """
    prefix = f"chumicro-{library_name}-v"
    versions = [
        tag[len(prefix):]
        for tag in release_tags(library_name, stable_only=True)
        if tag != exclude_tag and _STABLE_VERSION_PATTERN.match(tag[len(prefix):])
    ]
    if not versions:
        return None
    return max(versions, key=_parse_version)


def _check_monotonicity(
    parsed: dict[str, str], *, allow_downgrade: bool, resume: bool,
) -> None:
    """Raise when the promoted version is not newer than the newest stable release.

    Promoting an older experimental tag silently downgrades stable-facing
    state (bundle HEAD, docs), so a version <= the newest stable release
    fails unless ``allow_downgrade`` is set.

    Args:
        parsed: Output of :func:`_parse_tag`.
        allow_downgrade: Suppress the guard (intentional hotfix republish).
        resume: The promotion's own stable tag already exists; exclude it
            from the comparison so the re-run isn't rejected against itself.
    """
    exclude_tag = parsed["stable_tag"] if resume else None
    newest = _newest_stable_version(parsed["library_name"], exclude_tag=exclude_tag)
    if newest is None:
        return
    if _parse_version(parsed["version"]) > _parse_version(newest):
        return
    if allow_downgrade:
        print(
            f"allow_downgrade set: promoting v{parsed['version']} although the newest "
            f"stable release of {parsed['library_name']} is v{newest}.",
        )
        return
    raise PromoteValidationError(
        f"Version {parsed['version']} is not newer than the newest stable release "
        f"({newest}) of {parsed['library_name']}.  Promoting it would downgrade the "
        "stable bundle and docs.  Set allow_downgrade only for an intentional "
        "hotfix republish of an older version.",
    )


def _has_docs(library_dir: str, experimental_tag: str) -> bool:
    """Return whether the promoted source publishes docs.

    Docs presence means a ``mkdocs.yml`` at the package root (the same
    signal :func:`repo_layout.discover_doc_dirs` uses) — but checked in
    the EXPERIMENTAL TAG's tree, not the working tree: the docs job
    deploys the frozen source replayed from that tag, so a mkdocs.yml
    added to (or removed from) main after the tag was cut must not flip
    the gate.
    """
    result = run_git(
        "cat-file", "-e", f"{experimental_tag}:{library_dir}/mkdocs.yml",
    )
    return result.returncode == 0


def _env_flag(name: str) -> bool:
    """Return whether env var *name* is ``true`` (workflow boolean inputs)."""
    return os.environ.get(name, "").strip().lower() == "true"


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
        "--allow-downgrade", action="store_true", default=_env_flag("ALLOW_DOWNGRADE"),
        help="Suppress the version-monotonicity guard (default: $ALLOW_DOWNGRADE).",
    )
    parser.add_argument(
        "--resume", action="store_true", default=_env_flag("RESUME"),
        help="Require the stable tag to exist and re-run the promotion (default: $RESUME).",
    )
    args = parser.parse_args(argv)

    if not args.tag:
        print("::error::No tag provided (set --tag or $TAG).", file=sys.stderr)
        return 1

    try:
        parsed = _parse_tag(args.tag)
        located = _locate_package(parsed["library_name"])
        _check_preconditions(args.tag, parsed, resume=args.resume)
        _check_monotonicity(parsed, allow_downgrade=args.allow_downgrade, resume=args.resume)
    except PromoteValidationError as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1

    outputs = {
        **parsed,
        **located,
        "has_docs": "true" if _has_docs(located["library_dir"], args.tag) else "false",
    }
    _write_outputs(outputs)
    print(
        f"✓ Promoting {parsed['library_name']} v{parsed['version']} "
        f"from experimental to stable ({located['package_kind']})",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
