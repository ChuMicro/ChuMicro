"""Build + docs lanes: ``build``, ``docs``, ``docs-preview``, ``docs-deploy``."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from repo_layout import ROOT, discover_doc_dirs, find_publishable_packages
from shared import run_command, stream_subprocess

from run_tasks._dispatch import (
    _DEFAULT_PACKAGE_PARALLEL_WORKERS,
    PYTHON,
    _pick_dispatcher,
    _run_parallel_phases,
    _Sink,
)


def docs_deploy(channel: str, libraries: list[str] | None = None) -> int:
    """Deploy versioned docs for the selected libraries."""
    from docs_deploy import docs_deploy as _docs_deploy
    return _docs_deploy(channel, libraries=libraries)


def build(
    *,
    package_workers: int = _DEFAULT_PACKAGE_PARALLEL_WORKERS,
    quiet: bool = False,
) -> int:
    """Build all publishable package distributions.

    Uses ``--no-isolation`` to skip creating fresh virtual environments
    for each build, which dramatically speeds up builds (~10x faster).
    This is safe because the development environment already has
    ``hatchling`` installed via ``requirements-dev.txt``.

    Builds are fanned out across *package_workers* threads.  Each
    ``python -m build`` is an independent subprocess with its own
    per-package ``dist/`` output, no shared state.
    """
    packages = find_publishable_packages()
    if not packages:
        print("No publishable packages found (no VERSION + pyproject.toml pairs).")
        return 1

    def build_one(package: str) -> Callable[[_Sink], int]:
        command = [PYTHON, "-m", "build", "--no-isolation", package]

        def run(sink: _Sink) -> int:
            sink.line(f"+ {' '.join(command)}")
            exit_code, _ = stream_subprocess(command, cwd=ROOT, on_line=sink.line)
            if exit_code != 0:
                sink.line(f"Build failed: {package}")
            return exit_code

        return run

    phases = [(f"build {package}", build_one(package)) for package in packages]
    result, _failing_label, _phase_results = _run_parallel_phases(
        phases,
        dispatcher=_pick_dispatcher(quiet=quiet),
        max_workers=package_workers,
    )
    if result != 0:
        return result

    from sdist_content import check_all_library_sdists

    library_dirs = [
        ROOT / package
        for package in packages
        if package.startswith("libraries/")
    ]
    sdist_problems = check_all_library_sdists(library_dirs)
    if sdist_problems:
        print("Library sdist content check failed:")
        for problem in sdist_problems:
            print(f"  - {problem}")
        return 1

    print(f"Built {len(packages)} package(s): {', '.join(packages)}")
    return 0


def docs(
    package_dirs: list[Path],
    *,
    serve: bool = False,
    package_workers: int = _DEFAULT_PACKAGE_PARALLEL_WORKERS,
    quiet: bool = False,
) -> int:
    """Build docs for selected libraries using Zensical.

    If *serve* is True, starts a live-reload dev server for the first
    selected library instead of building static output.

    The build captures stderr and fails if griffe emits any warnings
    (e.g. missing type annotations or malformed docstrings).  This
    enforces Decision 0021 (type documentation policy).
    """
    # Keep only packages that have a mkdocs.yml
    doc_dirs = discover_doc_dirs(package_dirs)
    if not doc_dirs:
        print("No libraries with mkdocs.yml found for the selected packages.")
        return 0

    from docs_deploy import copy_shared_docs_assets
    copy_shared_docs_assets(doc_dirs)

    if serve:
        # Serve the first selected library
        library_dir = doc_dirs[0]
        relative_path = library_dir.relative_to(ROOT)
        print(f"Serving docs for {relative_path} (Ctrl+C to stop)...")
        return run_command(
            [PYTHON, "-m", "zensical", "serve",
             "-f", str(library_dir / "mkdocs.yml")],
        )

    # Each library's zensical build is an independent subprocess with
    # its own mkdocs.yml + site/ output, so we fan out across
    # *package_workers* to amortize the per-process warm-up.  The
    # serial loop took ~25-30 s on an 18-package workspace; at 4-way
    # fan-out it lands closer to 2-3 s.
    phases: list[tuple[str, Callable[[_Sink], int]]] = [
        (
            f"docs {library_dir.relative_to(ROOT)}",
            _build_one_library_docs_factory(library_dir),
        )
        for library_dir in doc_dirs
    ]
    exit_code, _failing_label, _phase_results = _run_parallel_phases(
        phases,
        dispatcher=_pick_dispatcher(quiet=quiet),
        max_workers=package_workers,
    )
    if exit_code != 0:
        return exit_code

    # The guides site publishes alongside the library docs and its URLs
    # ride in the sitemap, so a build that breaks here has to fail a PR
    # rather than surface as a 404 after deploy.
    exit_code = build_guides_site()
    if exit_code != 0:
        return exit_code

    # The host-root site carries robots.txt and the verification files
    # for the whole host, and it reads the same package list as the
    # landing page, so a rename that breaks it should fail here too.
    return build_site_root()


def build_site_root() -> int:
    """Build the host-root site into ``.site-root/``.

    Returns:
        Process exit status: 0 when the site builds.
    """
    from generate_site_root import SITE_DIR, build

    print(f"docs {SITE_DIR.relative_to(ROOT)}")
    build(SITE_DIR)
    return 0


def build_guides_site() -> int:
    """Build the guides site, or skip when there is none.

    Returns 0 when the config is absent, which keeps a workspace
    without a guides site from failing the docs phase.
    """
    from docs_deploy import GUIDES_CONFIG
    from docs_deploy import build_guides_site as _build

    if not GUIDES_CONFIG.is_file():
        return 0
    print(f"docs {GUIDES_CONFIG.relative_to(ROOT)}")
    return _build()


def _build_one_library_docs_factory(
    library_dir: Path,
) -> Callable[[_Sink], int]:
    """Return a phase callable that runs zensical on *library_dir*.

    The closure streams every line of zensical output through the
    sink, then post-processes the captured transcript to fail on
    griffe warnings (Decision 0021).  Streaming means the dispatcher
    sees output the moment zensical emits it, with no buffer-and-replay
    delay even on slow library builds.
    """
    def build_one(sink: _Sink) -> int:
        relative_path = library_dir.relative_to(ROOT)
        site_dir = library_dir / "site"
        # mkdocstrings + griffe cache parsed-AST results in
        # ``<library>/.cache/``.  When cached entries are reused, griffe
        # does not re-emit warnings on stdout, and the warning-scan
        # below would silently pass.  Always wipe the cache so each
        # docs build re-parses every source file from scratch.
        cache_dir = library_dir / ".cache"
        if cache_dir.is_dir():
            for cache_entry in cache_dir.iterdir():
                if cache_entry.name == ".gitignore":
                    continue
                if cache_entry.is_dir():
                    shutil.rmtree(cache_entry)
                else:
                    cache_entry.unlink()
        command = [
            PYTHON, "-m", "zensical", "build",
            "-f", str(library_dir / "mkdocs.yml"),
        ]
        sink.line(f"+ {' '.join(command)}")
        exit_code, captured = stream_subprocess(
            command, cwd=ROOT, on_line=sink.line,
        )
        if exit_code != 0:
            sink.line(f"Docs build failed: {relative_path}")
            return exit_code

        # Fail on griffe warnings (Decision 0021).  Stderr is merged
        # into stdout in the streaming path, so scan the full transcript.
        griffe_warnings = [
            line for line in captured.splitlines()
            if "griffe" in line.lower()
        ]
        if griffe_warnings:
            sink.line(f"Docs build has griffe warnings: {relative_path}")
            for warning in griffe_warnings:
                sink.line(f"  {warning}")
            return 1

        sink.line(f"  Built: {site_dir.relative_to(ROOT)}/")
        return 0

    return build_one


def docs_preview(package_dirs: list[Path]) -> int:
    """Build docs from the current working tree and serve a local preview.

    The preview branch is seeded from ``gh-pages`` (if it exists) so that
    already-deployed stable versions appear alongside the current working
    tree content.  The working tree is then deployed on top as
    ``dev`` / ``experimental``.

    For each library, ``mike deploy`` with ``--deploy-prefix`` mirrors the
    production layout (Decision 0013).  The landing page is injected via a
    git-plumbing commit.  ``mike serve`` then serves the result.
    """
    preview_branch = "_docs-preview"
    source_branch = "gh-pages"

    doc_dirs = discover_doc_dirs(package_dirs)
    if not doc_dirs:
        print("No libraries with mkdocs.yml found for the selected packages.")
        return 0

    from docs_deploy import MIKE, copy_shared_docs_assets, inject_landing_page
    copy_shared_docs_assets(doc_dirs)

    # Delete any previous preview branch so we start fresh.
    subprocess.run(
        ["git", "branch", "-D", preview_branch],
        capture_output=True, cwd=ROOT,
    )

    # Fetch the latest gh-pages from origin so the preview reflects
    # recently promoted versions (CI pushes directly to gh-pages).
    fetch_result = subprocess.run(
        ["git", "fetch", "origin", source_branch],
        capture_output=True, cwd=ROOT,
    )
    if fetch_result.returncode == 0:
        # Fast-forward the local tracking branch to match the remote.
        subprocess.run(
            ["git", "branch", "-f", source_branch, f"origin/{source_branch}"],
            capture_output=True, cwd=ROOT,
        )

    # Seed from gh-pages so existing stable/versioned deploys are present.
    # If gh-pages doesn't exist yet, mike's --allow-empty will create the
    # branch from scratch (first-time setup).
    has_source = subprocess.run(
        ["git", "rev-parse", "--verify", source_branch],
        capture_output=True, cwd=ROOT,
    ).returncode == 0

    if has_source:
        subprocess.run(
            ["git", "branch", preview_branch, source_branch],
            capture_output=True, cwd=ROOT, check=True,
        )
        print(f"Seeded {preview_branch} from {source_branch}.")

    # Per-library deploys are sequential because every ``mike deploy``
    # commits to the same ``_docs-preview`` git branch.  Running them
    # concurrently would race on the git index lock.  Unlike ``docs``
    # (which fans out per library because each writes to its own
    # ``site/`` directory), the ``mike`` workflow serializes onto one
    # git index.  Worktree-per-library would let us parallelize, but
    # the wall time of an interactive ``docs-preview`` is dominated by
    # ``mike serve`` afterwards, so the speedup wouldn't be visible to
    # the user.
    for library_dir in doc_dirs:
        relative_path = library_dir.relative_to(ROOT)
        library_name = library_dir.name
        print(f"== deploy {relative_path} ==")
        # --deploy-prefix puts each library's docs in a subdirectory
        # (e.g. /timing/) matching the production gh-pages layout.
        # --allow-empty lets mike create the branch from scratch when
        # gh-pages doesn't exist yet.  "dev" is the version label,
        # "experimental" is the URL alias.
        deploy_args = [
            MIKE, "deploy",
            "--deploy-prefix", library_name,
            "-b", preview_branch,
            "-F", str(library_dir / "mkdocs.yml"),
            "--alias-type", "redirect",
            "--update-aliases",
            "dev", "experimental",
        ]
        # Only needed when gh-pages doesn't exist and the branch is new.
        if not has_source:
            deploy_args.append("--allow-empty")

        exit_code = run_command(deploy_args)
        if exit_code != 0:
            print(f"Docs deploy failed: {relative_path}")
            return exit_code

    inject_landing_page(preview_branch)

    return run_command([
        MIKE, "serve",
        "-b", preview_branch,
        "-F", str(doc_dirs[0] / "mkdocs.yml"),
    ])


def register(subparsers, parents):
    """Register the build / docs subcommands."""
    scope = parents["scope"]
    build_parser = subparsers.add_parser(
        "build", help="build all publishable packages",
    )
    build_parser.add_argument(
        "--package-workers", type=int, metavar="N",
        default=_DEFAULT_PACKAGE_PARALLEL_WORKERS,
        help=(
            f"cap on concurrent per-package build subprocesses "
            f"(default: {_DEFAULT_PACKAGE_PARALLEL_WORKERS} for this host)"
        ),
    )
    build_parser.add_argument(
        "--quiet", action="store_true",
        help="buffer per-phase output; replay full transcript at end",
    )
    deploy_parser = subparsers.add_parser(
        "docs-deploy",
        help="deploy versioned docs to gh-pages (used by CI)",
    )
    deploy_parser.add_argument(
        "--channel", choices=["experimental", "stable"],
        required=True,
        help="docs channel to deploy",
    )
    deploy_parser.add_argument(
        "--libraries",
        help="comma-separated list of libraries to deploy (default: all)",
    )
    docs_parser = subparsers.add_parser("docs", parents=[scope], help="build library docs")
    docs_parser.add_argument(
        "--serve", action="store_true", help="start live-reload dev server",
    )
    docs_parser.add_argument(
        "--package-workers", type=int, metavar="N",
        default=_DEFAULT_PACKAGE_PARALLEL_WORKERS,
        help=(
            f"cap on concurrent per-library docs builds "
            f"(default: {_DEFAULT_PACKAGE_PARALLEL_WORKERS} for this host)"
        ),
    )
    docs_parser.add_argument(
        "--quiet", action="store_true",
        help="buffer per-phase output; replay full transcript at end",
    )
    subparsers.add_parser(
        "docs-preview", parents=[scope],
        help="deploy docs to local gh-pages and serve versioned site",
    )
