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
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import index_now
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


#: A search engine's file-based proof of ownership belongs at the root
#: of the property.  Anything dropped in here is published there
#: verbatim; the directory's README explains each method.
VERIFICATION_DIR = ROOT / "support" / "docs" / "site-verification"


def _hash_blob(content: bytes) -> str:
    """Write *content* as a git blob and return its hash."""
    return subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        input=content, capture_output=True, cwd=ROOT, check=True,
    ).stdout.strip().decode()


#: A published IndexNow key file: 32 hex characters and ``.txt``.
INDEXNOW_KEY_FILE_PATTERN = re.compile(r"^[0-9a-f]{32}\.txt$")


def _stale_key_files(branch: str, current: str) -> list[str]:
    """Return published key files that are no longer the current key.

    Rotating the key leaves the old file at the docs root, where it
    would go on authorizing pings from whoever still holds it.  The
    deploy removes it instead.
    """
    listing = subprocess.run(
        ["git", "ls-tree", "--name-only", branch],
        capture_output=True, cwd=ROOT, check=True,
    ).stdout.decode().split()
    return [
        name for name in listing
        if INDEXNOW_KEY_FILE_PATTERN.match(name) and name != current
    ]


def _verification_file_blobs() -> list[tuple[str, str]]:
    """Return ``(blob, path)`` for each file published at the docs root.

    Covers both engines' file methods (`google<hash>.html`,
    `BingSiteAuth.xml`) and the IndexNow key, which is published as
    ``<key>.txt`` so a crawler can check the ping against it.
    """
    blobs: list[tuple[str, str]] = []
    for verification_file in sorted(VERIFICATION_DIR.glob("*.html")):
        blobs.append((_hash_file(verification_file), verification_file.name))
    for verification_file in sorted(VERIFICATION_DIR.glob("*.xml")):
        blobs.append((_hash_file(verification_file), verification_file.name))

    key = index_now.read_key()
    if key:
        blobs.append((_hash_blob(f"{key}\n".encode()), index_now.key_filename(key)))
    return blobs


def _hash_file(path: Path) -> str:
    """Write *path* as a git blob and return its hash."""
    return subprocess.run(
        ["git", "hash-object", "-w", str(path)],
        capture_output=True, cwd=ROOT, check=True,
    ).stdout.strip().decode()


#: The guides site's config.  Its pages are repository prose (questions,
#: troubleshooting, wiring), published beside the per-library docs.
GUIDES_CONFIG = ROOT / "guides.mkdocs.yml"

#: Where the guides site lands on the docs branch.
GUIDES_PREFIX = "guides"


#: Where the guides build lands.  The generator takes its output path
#: from the config's ``site_dir`` rather than a flag, so this mirrors it.
GUIDES_SITE_DIR = ROOT / ".guides-site"


def build_guides_site() -> int:
    """Build the guides site into :data:`GUIDES_SITE_DIR`."""
    shutil.rmtree(GUIDES_SITE_DIR, ignore_errors=True)
    return run_command([
        sys.executable, "-m", "zensical", "build",
        "-f", str(GUIDES_CONFIG),
    ])


def _guides_blobs(destination: Path) -> list[tuple[str, str]]:
    """Return ``(blob, path)`` for every file of the built guides site."""
    blobs: list[tuple[str, str]] = []
    for built_file in sorted(destination.rglob("*")):
        if built_file.is_file():
            relative = built_file.relative_to(destination).as_posix()
            blobs.append((_hash_file(built_file), f"{GUIDES_PREFIX}/{relative}"))
    return blobs


def _published_guides_paths(branch: str) -> list[str]:
    """Return the guides files currently published on *branch*."""
    listing = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", branch, "--", f"{GUIDES_PREFIX}/"],
        capture_output=True, cwd=ROOT, check=True,
    ).stdout.decode().split()
    return listing


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
        from generate_landing_page import (
            generate,
            generate_llms_txt,
            generate_sitemap,
        )
    except Exception as error:
        print(f"  Landing page skipped: {error}")
        return

    html = generate()

    # Hash the landing-page HTML as a git blob.
    html_blob = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        input=html.encode(), capture_output=True, cwd=ROOT, check=True,
    ).stdout.strip().decode()

    # The sitemap and llms.txt ride along with the landing page: all
    # three describe the same set of packages, one for crawlers, one
    # for answer engines, one for people.
    sitemap_blob = _hash_blob(generate_sitemap().encode())
    llms_blob = _hash_blob(generate_llms_txt().encode())

    # The guides site is built fresh each deploy and replaces whatever
    # was published before, so a page dropped from its nav stops being
    # served instead of lingering as an orphan.
    guides_blobs: list[tuple[str, str]] = []
    stale_guides: list[str] = []
    if GUIDES_CONFIG.is_file():
        if build_guides_site() != 0:
            # The sitemap advertises these pages, so publishing the rest
            # without them would ship a sitemap full of 404s.
            raise RuntimeError("guides site failed to build")
        guides_blobs = _guides_blobs(GUIDES_SITE_DIR)
        published = set(_published_guides_paths(branch))
        stale_guides = sorted(published - {path for _, path in guides_blobs})

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

        # Upsert index.html, sitemap.xml, and any Search Console
        # verification files at the root.
        root_files = [
            (html_blob, "index.html"),
            (sitemap_blob, "sitemap.xml"),
            (llms_blob, "llms.txt"),
        ]
        root_files.extend(_verification_file_blobs())
        root_files.extend(guides_blobs)
        for blob, path in root_files:
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

        # Drop guides pages the site no longer builds.
        for stale in stale_guides:
            subprocess.run(
                ["git", "update-index", "--force-remove", stale],
                env=index_environment, cwd=ROOT, check=True,
            )

        # Drop a rotated key's file so only the live key authorizes pings.
        for stale in _stale_key_files(branch, index_now.key_filename(index_now.read_key())):
            subprocess.run(
                ["git", "update-index", "--force-remove", stale],
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
         "-m", "Regenerate landing page, sitemap, llms.txt, and guides"],
        capture_output=True, cwd=ROOT, check=True,
    ).stdout.strip().decode()

    subprocess.run(
        ["git", "update-ref", f"refs/heads/{branch}", new_commit],
        cwd=ROOT, check=True,
    )


#: A version directory named after a release, e.g. ``0.30.1``.  These
#: are the URLs that used to hold content and now redirect to the
#: channel that ships them.
RELEASE_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


def _list_deployed(library_name: str, library_dir: Path, branch: str) -> list[dict]:
    """Return what mike has deployed under *library_name*, or ``[]``."""
    listing = subprocess.run(
        [MIKE, "list", "-j", "--deploy-prefix", library_name, "-b", branch,
         "-F", str(library_dir / "mkdocs.yml")],
        capture_output=True, cwd=ROOT, check=False,
    )
    if listing.returncode != 0:
        # No deployed docs for this prefix yet.
        return []
    try:
        return json.loads(listing.stdout or b"[]")
    except json.JSONDecodeError:
        return []


def _retire_conflicting_names(
    library_name: str,
    library_dir: Path,
    branch: str,
    *,
    version: str,
    aliases: list[str],
) -> tuple[int, list[str]]:
    """Delete deployed names that block the channel-named layout.

    Docs deployed before the channel-name layout put the release
    number in the version slot (``0.30.0``) and the channel in the
    alias slot (``stable``), which is exactly backwards from what
    :func:`docs_deploy` writes now.  mike refuses to turn a version
    into an alias, so retire the old entry first.  Deleting a version
    takes its aliases with it, so one delete usually clears both
    conflicts, and later runs find nothing to do.

    Returns ``(exit_code, retired)``: 0 when the branch is ready to
    deploy onto, and the version names that went away, so the caller
    can hand their URLs back as redirects.
    """
    deployed = _list_deployed(library_name, library_dir, branch)
    stale = [
        entry["version"] for entry in deployed
        if entry.get("version") in aliases or version in entry.get("aliases", [])
    ]
    if not stale:
        return 0, []

    print(f"== retire {library_name} {', '.join(stale)} (pre-channel layout) ==")
    exit_code = run_command([
        MIKE, "delete",
        "--deploy-prefix", library_name,
        "-b", branch,
        "-F", str(library_dir / "mkdocs.yml"),
        *stale,
    ])
    return exit_code, stale


def _fold_release_urls_into_redirects(
    library_name: str,
    library_dir: Path,
    branch: str,
    *,
    version: str,
    retired: list[str],
) -> int:
    """Point every release-numbered URL at *version*'s living docs.

    A reader who bookmarked ``/mqtt/0.28.1/`` and a search engine that
    indexed it both land on the current docs instead of a 404 or a
    frozen copy of an old release.  Release-numbered directories that
    still hold content are deleted and handed back as redirect
    aliases; *retired* names, already deleted by
    :func:`_retire_conflicting_names`, are re-added the same way.
    """
    deployed = _list_deployed(library_name, library_dir, branch)
    existing_aliases = {
        alias for entry in deployed for alias in entry.get("aliases", [])
    }
    holding_content = [
        entry["version"] for entry in deployed
        if RELEASE_VERSION_PATTERN.match(entry.get("version", ""))
    ]
    if holding_content:
        print(f"== fold {library_name} {', '.join(holding_content)} into redirects ==")
        exit_code = run_command([
            MIKE, "delete",
            "--deploy-prefix", library_name,
            "-b", branch,
            "-F", str(library_dir / "mkdocs.yml"),
            *holding_content,
        ])
        if exit_code != 0:
            return exit_code

    wanted = sorted(set(holding_content + retired) - existing_aliases)
    if not wanted:
        return 0
    return run_command([
        MIKE, "alias",
        "--deploy-prefix", library_name,
        "-b", branch,
        "-F", str(library_dir / "mkdocs.yml"),
        "--alias-type", "redirect",
        "--update-aliases",
        version, *wanted,
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

        exit_code, retired = _retire_conflicting_names(
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

        # Release numbers belong to the stable channel, so only a stable
        # deploy folds them.  An experimental deploy leaves them alone.
        if version == "stable":
            exit_code = _fold_release_urls_into_redirects(
                library_name, library_dir, branch, version=version, retired=retired,
            )
            if exit_code != 0:
                print(f"Redirect fold failed: {library_name}")
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

    try:
        inject_landing_page(branch)
    except RuntimeError as error:
        print(f"Docs deploy failed: {error}")
        return 1

    return 0
