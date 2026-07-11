"""Dispatch a stable-promotion wave strictly one run at a time.

The ``release`` concurrency group keeps one RUNNING plus at most one
PENDING run; queuing another run silently CANCELS the previously
pending one.  Bulk-dispatching N promotions therefore loses all but
two with no failure signal.  This script closes that trap: it refuses
to start while a release/promotion is active, orders the tags so every
package follows its intra-workspace dependencies (the bundle overlay
and stable PyPI both need deps published first — the first wave starts
from an empty bundle repo), then for each tag dispatches promote.yml
and watches the run to completion before dispatching the next.

Usage::

    python scripts/promote_wave.py \
        chumicro-timing-v0.8.0-experimental \
        chumicro-mqtt-v0.26.0-experimental [...]

    python scripts/promote_wave.py --dry-run <tags...>   # print the plan

Requires the ``gh`` CLI on PATH, authenticated with workflow-dispatch
rights.  A failed promotion stops the wave immediately; resume by
re-running with the remaining tags after fixing the failure.
"""

from __future__ import annotations

import argparse
import subprocess
import time

from promote_validate import PromoteValidationError, _parse_tag
from repo_layout import (
    ROOT,
    find_publishable_packages,
    load_tomllib,
    order_libraries_by_dependency,
    strip_pip_dependency_version,
)

_WATCHED_WORKFLOWS = ("promote.yml", "release.yml")


def _deps_by_basename() -> dict[str, list[str]]:
    """Map each publishable package basename to its intra-workspace deps.

    Reads every publishable package's ``pyproject.toml`` once, maps the
    PyPI project names back to directory basenames, and resolves each
    package's ``chumicro-*`` dependencies to basenames.  Parked packages
    are included so a tag for one still orders correctly instead of
    KeyErroring.
    """
    tomllib = load_tomllib()
    name_to_basename: dict[str, str] = {}
    raw_deps: dict[str, list[str]] = {}
    for relative_path in find_publishable_packages(include_parked=True):
        package_dir = ROOT / relative_path
        with (package_dir / "pyproject.toml").open("rb") as pyproject_file:
            project = tomllib.load(pyproject_file).get("project", {})
        pypi_name = project.get("name", "")
        basename = package_dir.name
        name_to_basename[pypi_name] = basename
        raw_deps[basename] = [
            strip_pip_dependency_version(dependency)
            for dependency in project.get("dependencies", [])
            if strip_pip_dependency_version(dependency).startswith("chumicro-")
        ]
    return {
        basename: [
            name_to_basename[dep] for dep in deps if dep in name_to_basename
        ]
        for basename, deps in raw_deps.items()
    }


def order_tags_for_promotion(tags: list[str]) -> list[str]:
    """Return *tags* topologically ordered by intra-workspace dependencies.

    Raises:
        PromoteValidationError: If a tag doesn't match the experimental
            tag format or names a package the workspace doesn't have.
    """
    deps = _deps_by_basename()
    tag_by_basename: dict[str, str] = {}
    for tag in tags:
        basename = _parse_tag(tag)["library_name"]
        if basename not in deps:
            raise PromoteValidationError(
                f"Tag {tag!r} names unknown package {basename!r}. "
                f"Known: {', '.join(sorted(deps))}."
            )
        tag_by_basename[basename] = tag
    ordered_basenames = order_libraries_by_dependency(
        sorted(tag_by_basename), lambda name: deps.get(name, []),
    )
    return [tag_by_basename[basename] for basename in ordered_basenames]


def _run_gh(*arguments: str) -> subprocess.CompletedProcess:
    """Run a ``gh`` subprocess from the repository root, capturing text."""
    return subprocess.run(
        ["gh", *arguments], cwd=ROOT, capture_output=True, text=True, check=False,
    )


def _active_run_count(workflow: str) -> int:
    """Return the number of queued/in-progress runs of *workflow*."""
    count = 0
    for status in ("queued", "in_progress", "waiting"):
        result = _run_gh(
            "run", "list", "--workflow", workflow, "--status", status,
            "--json", "databaseId", "--jq", "length",
        )
        if result.returncode == 0 and result.stdout.strip().isdigit():
            count += int(result.stdout.strip())
    return count


def _dispatch_and_watch(tag: str) -> bool:
    """Dispatch one promotion and block until its run completes.

    Returns True when the run concluded successfully.
    """
    dispatch = _run_gh(
        "workflow", "run", "promote.yml", "-f", f"experimental_tag={tag}",
    )
    if dispatch.returncode != 0:
        print(f"FAIL: dispatch for {tag}: {dispatch.stderr.strip()}")
        return False

    # The dispatch API returns before the run exists; poll for it.
    run_id = ""
    for _ in range(12):
        time.sleep(5)
        result = _run_gh(
            "run", "list", "--workflow", "promote.yml", "--limit", "1",
            "--json", "databaseId,status", "--jq", ".[0].databaseId",
        )
        if result.returncode == 0 and result.stdout.strip():
            run_id = result.stdout.strip()
            break
    if not run_id:
        print(f"FAIL: dispatched {tag} but no run appeared within 60s.")
        return False

    print(f"Watching run {run_id} for {tag} ...")
    watch = subprocess.run(
        ["gh", "run", "watch", run_id, "--exit-status", "--interval", "30"],
        cwd=ROOT, check=False,
    )
    if watch.returncode != 0:
        print(f"FAIL: promotion of {tag} (run {run_id}) did not succeed.")
        return False
    print(f"OK: {tag} (run {run_id})")
    return True


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Dispatch stable promotions one at a time, dependency-ordered.",
    )
    parser.add_argument(
        "tags", nargs="+",
        help="Experimental tags to promote (chumicro-<name>-v<version>-experimental).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the dispatch order without dispatching anything.",
    )
    args = parser.parse_args(argv)

    try:
        ordered = order_tags_for_promotion(args.tags)
    except (PromoteValidationError, ValueError) as error:
        print(f"FAIL: {error}")
        return 1

    print("Promotion order (dependencies first):")
    for position, tag in enumerate(ordered, start=1):
        print(f"  {position:2}. {tag}")
    if args.dry_run:
        return 0

    for workflow in _WATCHED_WORKFLOWS:
        if _active_run_count(workflow) > 0:
            print(
                f"FAIL: {workflow} has queued or running runs.  The shared "
                "'release' concurrency group cancels pending runs, so the "
                "wave must start idle.  Wait for them to finish and re-run."
            )
            return 1

    for position, tag in enumerate(ordered, start=1):
        print(f"--- [{position}/{len(ordered)}] {tag}")
        if not _dispatch_and_watch(tag):
            remaining = ordered[position - 1 :]
            print()
            print("Wave stopped.  Resume after fixing with:")
            print(f"  python scripts/promote_wave.py {' '.join(remaining)}")
            return 1

    print(f"Wave complete: {len(ordered)} promotions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
