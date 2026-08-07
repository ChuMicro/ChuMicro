"""Build the promotion-job matrix from a list of experimental tags.

``promote.yml`` promotes a whole wave in one run (Decision 0117).  This
script is to that workflow what ``release_matrix.py`` is to
``release.yml``: it turns the dispatch input into the matrices the
downstream jobs fan out over, and it is the single place a tag is
rejected before anything publishes.

Per-tag validation is not reimplemented here.  Every tag goes through
``promote_validate``'s own parse / locate / precondition / monotonicity
checks, so a single-tag promotion and a seventeen-tag wave apply
identical rules.

Emits to ``$GITHUB_OUTPUT`` (or stdout when unset):

``has_promotions`` / ``matrix``
    Every package to promote, each entry carrying ``library_name``,
    ``library_dir``, ``version``, ``experimental_tag``, ``stable_tag``,
    ``source_zip``, ``package_kind`` and ``gate_commit``.
``has_library_promotions`` / ``library_matrix``
    The ``kind == "library"`` subset.  Workbench and support packages
    ship to PyPI only, so the bundle and mip-validation jobs filter
    them out (Decisions 0032 and 0111).
``has_docs_promotions`` / ``docs_libraries``
    Comma-separated names of packages carrying a ``mkdocs.yml``, for
    the single batched ``docs-deploy --channel stable`` pass.
``gate_commits``
    Matrix of the *distinct* commits the tags point at.  A wave cut
    from one push gates once instead of once per package; a wave
    mixing commits gates once per commit.

A tag whose stable tag already exists drops out with a printed notice
rather than failing the wave, so re-dispatching a partially-failed
wave's tag list is the resume path.  ``--include-tagged`` overrides
that for a deliberate re-publish.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import promote_validate
from promote_validate import PromoteValidationError
from repo_layout import run_git


def _split_tags(raw: str) -> list[str]:
    """Return the tag list parsed from a comma / whitespace separated string."""
    parts = [part.strip() for part in raw.replace("\n", ",").split(",")]
    return [part for part in parts if part]


def _gate_commit(tag: str) -> str:
    """Return the commit *tag* points at.

    The preflight gate checks out the experimental tag's tree rather
    than ``main`` (Decision 0023), so this is what the gate matrix
    deduplicates on.
    """
    result = run_git("rev-list", "-n1", tag)
    if result.returncode != 0:
        raise PromoteValidationError(f"cannot resolve commit for tag {tag}")
    return result.stdout.strip()


def _build_entries(
    tags: list[str],
    *,
    allow_downgrade: bool,
    include_tagged: bool,
) -> list[dict[str, str]]:
    """Validate every tag and return one matrix entry per promotable package.

    Raises:
        PromoteValidationError: If any tag fails validation.  A wave is
            all-or-nothing at this stage: publishing half of it because
            the other half was malformed is worse than not starting.
    """
    entries: list[dict[str, str]] = []
    seen: set[str] = set()

    for tag in tags:
        if tag in seen:
            print(f"Tag {tag} listed twice — keeping the first.")
            continue
        seen.add(tag)

        parsed = promote_validate._parse_tag(tag)
        located = promote_validate._locate_package(parsed["library_name"])

        # Already promoted → drop out rather than fail, so re-dispatching
        # a failed wave's full tag list finishes only what is left.
        stable_exists = promote_validate._tag_exists(parsed["stable_tag"])
        if stable_exists and not include_tagged:
            print(
                f"Stable tag {parsed['stable_tag']} already exists — "
                f"skipping {parsed['library_name']}."
            )
            continue

        # A package that survives with its stable tag present is a
        # deliberate re-publish, which is exactly the shape
        # promote_validate calls `resume`: the stable-tag precondition
        # inverts to "must exist", and the monotonicity guard excludes
        # the package's own stable tag so its own release does not read
        # as a downgrade of itself.
        promote_validate._check_preconditions(tag, parsed, resume=stable_exists)
        promote_validate._check_monotonicity(
            parsed, allow_downgrade=allow_downgrade, resume=stable_exists,
        )

        entries.append({
            **parsed,
            **located,
            "experimental_tag": tag,
            "gate_commit": _gate_commit(tag),
            "has_docs": (
                "true"
                if promote_validate._has_docs(located["library_dir"], tag)
                else "false"
            ),
        })

    return entries


def _emit_outputs(entries: list[dict[str, str]]) -> str:
    """Build the GitHub Actions output payload as a newline-joined string."""
    library_entries = [e for e in entries if e["package_kind"] == "library"]
    docs_names = [e["library_name"] for e in entries if e["has_docs"] == "true"]
    gate_commits = sorted({e["gate_commit"] for e in entries})

    lines: list[str] = []

    if entries:
        lines.append("has_promotions=true")
        lines.append(f"matrix={json.dumps({'include': entries})}")
    else:
        lines.append("has_promotions=false")
        lines.append('matrix={"include":[]}')

    if library_entries:
        lines.append("has_library_promotions=true")
        lines.append(f"library_matrix={json.dumps({'include': library_entries})}")
    else:
        lines.append("has_library_promotions=false")
        lines.append('library_matrix={"include":[]}')

    lines.append(f"has_docs_promotions={'true' if docs_names else 'false'}")
    lines.append(f"docs_libraries={','.join(docs_names)}")

    lines.append(
        "gate_commits="
        + json.dumps({"include": [{"commit": c} for c in gate_commits]})
    )
    return "\n".join(lines)


def _write_outputs(payload: str) -> None:
    """Write *payload* to ``$GITHUB_OUTPUT`` when set, otherwise stdout."""
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with Path(github_output).open("a", encoding="utf-8") as handle:
            handle.write(payload + "\n")
    else:
        sys.stdout.write(payload + "\n")


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Build the promotion matrix from experimental tags.",
    )
    parser.add_argument(
        "--tags", default=os.environ.get("TAGS", ""),
        help="Comma-separated experimental tags (default: $TAGS).",
    )
    parser.add_argument(
        "--allow-downgrade", action="store_true",
        default=promote_validate._env_flag("ALLOW_DOWNGRADE"),
        help="Suppress the version-monotonicity guard (default: $ALLOW_DOWNGRADE).",
    )
    parser.add_argument(
        "--include-tagged", action="store_true",
        default=promote_validate._env_flag("INCLUDE_TAGGED"),
        help="Keep packages whose stable tag already exists (default: $INCLUDE_TAGGED).",
    )
    args = parser.parse_args(argv)

    tags = _split_tags(args.tags)
    if not tags:
        print("::error::No tags provided (set --tags or $TAGS).", file=sys.stderr)
        return 1

    try:
        entries = _build_entries(
            tags,
            allow_downgrade=args.allow_downgrade,
            include_tagged=args.include_tagged,
        )
    except PromoteValidationError as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1

    _write_outputs(_emit_outputs(entries))

    if entries:
        gate_count = len({e["gate_commit"] for e in entries})
        print(
            f"✓ {len(entries)} package(s) to promote, "
            f"{gate_count} distinct commit(s) to gate:"
        )
        for entry in entries:
            print(
                f"    {entry['library_name']} v{entry['version']} "
                f"({entry['package_kind']})"
            )
    else:
        print("Nothing to promote — every listed tag is already on stable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
