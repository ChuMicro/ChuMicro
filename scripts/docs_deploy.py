"""Deploy versioned documentation to a git branch using mike.

Centralizes library discovery, shared-CSS copy, mike deploy loop, and
landing-page injection that the CI workflow and local preview share.

Called as ``python scripts/run.py docs-deploy --channel <channel>``.

This module manages the ``gh-pages`` branch layout where each library
gets its own deploy prefix (subdirectory).  For example, the timing
library's stable docs live at ``/timing/stable/`` on gh-pages.  The
``mike`` tool handles versioned deployments within each prefix.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from repo_layout import ROOT, discover_doc_dirs, read_version
from shared import run_command

# Absolute path to the mike CLI installed alongside the active interpreter.
# mike manages versioned MkDocs deployments on a git branch (gh-pages).
# We use the absolute path rather than just "mike" to ensure we pick up
# the correct installation even when the venv is not activated.
MIKE = str(Path(sys.executable).parent / "mike")


def copy_shared_docs_assets(doc_dirs: list[Path]) -> None:
    """Copy shared doc assets into each library's ``docs/`` tree.

    Copies ``support/docs/extra.css`` to ``docs/stylesheets/`` and
    ``support/docs/favicon.png`` to ``docs/img/``.
    Zensical does not support mkdocs hooks, so we handle this before building.
    The generated copies are gitignored.

    Args:
        doc_dirs: Library directories that contain a ``mkdocs.yml``.
    """
    shared_dir = ROOT / "support" / "docs"
    for library_dir in doc_dirs:
        css_source_file = shared_dir / "extra.css"
        if css_source_file.exists():
            css_dest_file = library_dir / "docs" / "stylesheets" / "extra.css"
            css_dest_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(css_source_file, css_dest_file)

        favicon_source_file = shared_dir / "favicon.png"
        if favicon_source_file.exists():
            favicon_dest_file = library_dir / "docs" / "img" / "favicon.png"
            favicon_dest_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(favicon_source_file, favicon_dest_file)


def inject_landing_page(branch: str) -> None:
    """Generate the landing page and commit it to *branch*.

    Uses git plumbing commands (hash-object, update-index, write-tree,
    commit-tree, update-ref) to add ``index.html`` and
    ``assets/images/favicon.png`` to the root of *branch* without
    touching the working tree or requiring a checkout.

    Args:
        branch: Git branch to commit the landing page to.
    """
    try:
        from generate_landing_page import generate, generate_sitemap
    except Exception as error:
        print(f"  Landing page skipped: {error}")
        return

    html = generate()

    # Hash the landing-page HTML as a git blob.
    html_blob = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        input=html.encode(), capture_output=True, cwd=ROOT, check=True,
    ).stdout.strip().decode()

    # The sitemap rides along with the landing page: both describe the
    # same set of packages, and a search engine reads the sitemap to
    # find the per-package docs that the landing page links.
    sitemap_blob = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        input=generate_sitemap().encode(), capture_output=True, cwd=ROOT, check=True,
    ).stdout.strip().decode()

    # Hash the favicon if it exists.
    favicon_source_file = ROOT / "support" / "docs" / "favicon.png"
    favicon_blob = None
    if favicon_source_file.exists():
        favicon_blob = subprocess.run(
            ["git", "hash-object", "-w", str(favicon_source_file)],
            capture_output=True, cwd=ROOT, check=True,
        ).stdout.strip().decode()

    # Build an updated tree using a temporary index so nested paths
    # (assets/images/favicon.png) are handled automatically.  A temporary
    # index file isolates these operations from the user's working tree:
    # git commands that read GIT_INDEX_FILE operate on this file instead
    # of the default .git/index.
    file_descriptor, temp_index_file = tempfile.mkstemp(suffix=".idx")
    os.close(file_descriptor)
    index_environment = {**os.environ, "GIT_INDEX_FILE": temp_index_file}
    try:
        # Seed the temp index with the current branch tree.
        subprocess.run(
            ["git", "read-tree", f"{branch}^{{tree}}"],
            env=index_environment, cwd=ROOT, check=True,
        )

        # Upsert index.html and sitemap.xml at the root.
        for blob, path in ((html_blob, "index.html"), (sitemap_blob, "sitemap.xml")):
            subprocess.run(
                ["git", "update-index", "--add", "--cacheinfo",
                 f"100644,{blob},{path}"],
                env=index_environment, cwd=ROOT, check=True,
            )

        # Upsert the favicon.
        if favicon_blob:
            subprocess.run(
                ["git", "update-index", "--add", "--cacheinfo",
                 f"100644,{favicon_blob},assets/images/favicon.png"],
                env=index_environment, cwd=ROOT, check=True,
            )

        # Write the tree from the index.
        new_tree = subprocess.run(
            ["git", "write-tree"],
            env=index_environment, capture_output=True, cwd=ROOT, check=True,
        ).stdout.strip().decode()
    finally:
        Path(temp_index_file).unlink(missing_ok=True)

    # Create a commit and fast-forward the branch, only if the tree changed.
    parent_commit = subprocess.run(
        ["git", "rev-parse", branch],
        capture_output=True, cwd=ROOT, check=True,
    ).stdout.strip().decode()

    old_tree = subprocess.run(
        ["git", "rev-parse", f"{branch}^{{tree}}"],
        capture_output=True, cwd=ROOT, check=True,
    ).stdout.strip().decode()

    if new_tree == old_tree:
        print("  Landing page unchanged — skipping commit.")
        return

    new_commit = subprocess.run(
        ["git", "commit-tree", new_tree, "-p", parent_commit,
         "-m", "Regenerate landing page"],
        capture_output=True, cwd=ROOT, check=True,
    ).stdout.strip().decode()

    subprocess.run(
        ["git", "update-ref", f"refs/heads/{branch}", new_commit],
        cwd=ROOT, check=True,
    )


def _retire_conflicting_names(
    library_name: str,
    library_dir: Path,
    branch: str,
    *,
    version: str,
    aliases: list[str],
) -> int:
    """Delete deployed names that block the channel-named layout.

    Docs deployed before the channel-name layout put the release
    number in the version slot (``0.30.0``) and the channel in the
    alias slot (``stable``), which is exactly backwards from what
    :func:`docs_deploy` writes now.  mike refuses to turn a version
    into an alias, so retire the old entry first.  Deleting a version
    takes its aliases with it, so one delete usually clears both
    conflicts, and later runs find nothing to do.

    Returns an exit code: 0 when the branch is ready to deploy onto.
    """
    listing = subprocess.run(
        [MIKE, "list", "-j", "--deploy-prefix", library_name, "-b", branch,
         "-F", str(library_dir / "mkdocs.yml")],
        capture_output=True, cwd=ROOT, check=False,
    )
    if listing.returncode != 0:
        # No deployed docs for this prefix yet: nothing to retire.
        return 0
    try:
        deployed = json.loads(listing.stdout or b"[]")
    except json.JSONDecodeError:
        return 0

    stale = [
        entry["version"] for entry in deployed
        if entry.get("version") in aliases or version in entry.get("aliases", [])
    ]
    if not stale:
        return 0

    print(f"== retire {library_name} {', '.join(stale)} (pre-channel layout) ==")
    return run_command([
        MIKE, "delete",
        "--deploy-prefix", library_name,
        "-b", branch,
        "-F", str(library_dir / "mkdocs.yml"),
        *stale,
    ])


def docs_deploy(
    channel: str,
    *,
    branch: str = "gh-pages",
    libraries: list[str] | None = None,
) -> int:
    """Deploy docs for libraries to *branch*.

    *channel* is ``"experimental"`` or ``"stable"``:

    - **experimental**: version ``dev``, alias ``experimental``.
    - **stable**: version from each library's ``VERSION`` file,
      alias ``stable``.

    After deploying, injects the generated landing page into *branch*.

    Args:
        channel: Release channel (``"experimental"`` or ``"stable"``).
        branch: Git branch to deploy to.
        libraries: Optional list of library names to deploy.
            When ``None``, deploys all.

    Returns:
        Exit code (0 for success, non-zero for failure).
    """
    # Deliberately no is_parked() filter here: a parked library (Decision
    # 0107) stays published on PyPI, and its released packages link these
    # docs.  Parking removes it from the landing page and the bundle, not
    # from the docs site.
    doc_dirs = discover_doc_dirs()
    if libraries:
        doc_dirs = [doc_dir for doc_dir in doc_dirs if doc_dir.name in libraries]
    if not doc_dirs:
        print("No libraries with mkdocs.yml found.")
        return 1

    copy_shared_docs_assets(doc_dirs)

    for library_dir in doc_dirs:
        library_name = library_dir.name

        # The channel name is the deployed version, so a library's docs
        # keep one address across releases: /<library>/stable/ and
        # /<library>/experimental/.  Search engines and anyone who
        # bookmarks a page land on the same URL after the next release,
        # and the release number rides along as a redirect alias so
        # older /<library>/<version>/ links still resolve.
        release = read_version(library_dir) if channel == "stable" else None
        if release:
            version, aliases = "stable", [release]
            title = f"stable ({release})"
        else:
            version, aliases = "experimental", ["dev"]
            title = "experimental"

        exit_code = _retire_conflicting_names(
            library_name, library_dir, branch, version=version, aliases=aliases,
        )
        if exit_code != 0:
            return exit_code

        print(f"== deploy {library_name} {version} ({', '.join(aliases)}) ==")
        exit_code = run_command([
            MIKE, "deploy",
            "--deploy-prefix", library_name,
            "-b", branch,
            "-F", str(library_dir / "mkdocs.yml"),
            "--alias-type", "redirect",
            "--update-aliases",
            "-t", title,
            version, *aliases,
        ])
        if exit_code != 0:
            print(f"Docs deploy failed: {library_name}")
            return exit_code

    # For stable deploys, set the "stable" alias as the default landing
    # page for each library so bare URLs (e.g. /timing/) redirect to the
    # latest stable version.
    if channel == "stable":
        for library_dir in doc_dirs:
            library_name = library_dir.name
            exit_code = run_command([
                MIKE, "set-default",
                "--deploy-prefix", library_name,
                "-b", branch,
                "-F", str(library_dir / "mkdocs.yml"),
                "stable",
            ])
            if exit_code != 0:
                print(f"set-default failed: {library_name}")
                return exit_code

    inject_landing_page(branch)

    return 0
