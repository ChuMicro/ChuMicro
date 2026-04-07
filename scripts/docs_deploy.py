"""Deploy versioned documentation to a git branch using mike.

Centralises library discovery, shared-CSS copy, mike deploy loop, and
landing-page injection that the CI workflow and local preview share.

Called as ``python scripts/run.py docs-deploy --channel <channel>``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from discovery import ROOT, discover_package_dirs

# Absolute path to the mike CLI installed alongside the active interpreter.
# mike manages versioned MkDocs deployments on a git branch (gh-pages).
MIKE = str(Path(sys.executable).parent / "mike")


def discover_doc_dirs() -> list[Path]:
    """Return publishable library directories that contain a ``mkdocs.yml``."""
    return [
        d for d in discover_package_dirs()
        if d.parent.name == "libraries" and (d / "mkdocs.yml").exists()
    ]


def copy_shared_docs_assets(doc_dirs: list[Path]) -> None:
    """Copy shared doc assets into each library's ``docs/`` tree.

    Copies ``support/docs/extra.css`` to ``docs/stylesheets/`` and
    ``support/docs/favicon.png`` to ``docs/img/``.
    Zensical does not support mkdocs hooks, so we handle this before building.
    The generated copies are gitignored.
    """
    shared_dir = ROOT / "support" / "docs"
    for pkg_dir in doc_dirs:
        css_src = shared_dir / "extra.css"
        if css_src.exists():
            css_dest = pkg_dir / "docs" / "stylesheets" / "extra.css"
            css_dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(css_src, css_dest)

        favicon_src = shared_dir / "favicon.png"
        if favicon_src.exists():
            fav_dest = pkg_dir / "docs" / "img" / "favicon.png"
            fav_dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(favicon_src, fav_dest)


def inject_landing_page(branch: str) -> None:
    """Generate the landing page and commit it to *branch*.

    Uses a temporary git index to add ``index.html`` and
    ``assets/images/favicon.png`` to the root of *branch* without
    touching the working tree or requiring a checkout.
    """
    try:
        from generate_landing_page import generate
    except Exception as exc:
        print(f"  Landing page skipped: {exc}")
        return

    html = generate()

    # Hash the landing-page HTML as a git blob.
    html_blob = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        input=html.encode(), capture_output=True, cwd=ROOT,
    ).stdout.strip().decode()

    # Hash the favicon if it exists.
    favicon_src = ROOT / "support" / "docs" / "favicon.png"
    favicon_blob = None
    if favicon_src.exists():
        favicon_blob = subprocess.run(
            ["git", "hash-object", "-w", str(favicon_src)],
            capture_output=True, cwd=ROOT,
        ).stdout.strip().decode()

    # Build an updated tree using a temporary index so nested paths
    # (assets/images/favicon.png) are handled automatically.
    fd, temp_index = tempfile.mkstemp(suffix=".idx")
    os.close(fd)
    env = {**os.environ, "GIT_INDEX_FILE": temp_index}
    try:
        # Seed the temp index with the current branch tree.
        subprocess.run(
            ["git", "read-tree", f"{branch}^{{tree}}"],
            env=env, cwd=ROOT, check=True,
        )

        # Upsert index.html at the root.
        subprocess.run(
            ["git", "update-index", "--add", "--cacheinfo",
             f"100644,{html_blob},index.html"],
            env=env, cwd=ROOT, check=True,
        )

        # Upsert the favicon.
        if favicon_blob:
            subprocess.run(
                ["git", "update-index", "--add", "--cacheinfo",
                 f"100644,{favicon_blob},assets/images/favicon.png"],
                env=env, cwd=ROOT, check=True,
            )

        # Write the tree from the index.
        new_tree = subprocess.run(
            ["git", "write-tree"],
            env=env, capture_output=True, cwd=ROOT, check=True,
        ).stdout.strip().decode()
    finally:
        Path(temp_index).unlink(missing_ok=True)

    # Create a commit and fast-forward the branch — only if the tree changed.
    parent = subprocess.run(
        ["git", "rev-parse", branch],
        capture_output=True, cwd=ROOT,
    ).stdout.strip().decode()

    old_tree = subprocess.run(
        ["git", "rev-parse", f"{branch}^{{tree}}"],
        capture_output=True, cwd=ROOT,
    ).stdout.strip().decode()

    if new_tree == old_tree:
        print("  Landing page unchanged — skipping commit.")
        return

    commit = subprocess.run(
        ["git", "commit-tree", new_tree, "-p", parent,
         "-m", "Regenerate landing page"],
        capture_output=True, cwd=ROOT,
    ).stdout.strip().decode()

    subprocess.run(
        ["git", "update-ref", f"refs/heads/{branch}", commit],
        cwd=ROOT, check=True,
    )


def _run(command: list[str]) -> int:
    """Run a command from the repo root and return its exit code."""
    print(f"+ {' '.join(command)}")
    return subprocess.run(command, cwd=ROOT, check=False).returncode


def _read_version(lib_dir: Path) -> str | None:
    """Read a library's ``VERSION`` file, or return ``None``."""
    version_file = lib_dir / "VERSION"
    if not version_file.exists():
        return None
    return version_file.read_text().strip() or None


def docs_deploy(
    channel: str,
    *,
    branch: str = "gh-pages",
    libraries: list[str] | None = None,
) -> int:
    """Deploy docs for libraries to *branch*.

    *channel* is ``"experimental"`` or ``"stable"``:

    - **experimental** → version ``dev``, alias ``experimental``.
    - **stable** → version from each library's ``VERSION`` file,
      alias ``stable``.  Libraries without a ``VERSION`` deploy as
      ``dev`` / ``experimental``.

    When *libraries* is provided, only deploy those library names
    (e.g. ``["timing", "runner"]``).  When ``None``, deploy all.

    After deploying, injects the generated landing page into *branch*.
    """
    doc_dirs = discover_doc_dirs()
    if libraries:
        doc_dirs = [d for d in doc_dirs if d.name in libraries]
    if not doc_dirs:
        print("No libraries with mkdocs.yml found.")
        return 1

    copy_shared_docs_assets(doc_dirs)

    for lib_dir in doc_dirs:
        lib_name = lib_dir.name

        # Determine the version label and URL alias for this library.
        # Stable channel reads the actual version from the VERSION file;
        # experimental always deploys as "dev" with an "experimental" alias.
        if channel == "stable":
            version = _read_version(lib_dir)
            if version:
                alias = "stable"
            else:
                version = "dev"
                alias = "experimental"
        else:
            version = "dev"
            alias = "experimental"

        print(f"== deploy {lib_name} {version} ({alias}) ==")
        exit_code = _run([
            MIKE, "deploy",
            "--deploy-prefix", lib_name,
            "-b", branch,
            "-F", str(lib_dir / "mkdocs.yml"),
            "--alias-type", "redirect",
            "--update-aliases",
            version, alias,
        ])
        if exit_code != 0:
            print(f"Docs deploy failed: {lib_name}")
            return exit_code

    # For stable deploys, set the "stable" alias as the default landing
    # page for each library so bare URLs (e.g. /timing/) redirect to the
    # latest stable version.
    if channel == "stable":
        for lib_dir in doc_dirs:
            lib_name = lib_dir.name
            exit_code = _run([
                MIKE, "set-default",
                "--deploy-prefix", lib_name,
                "-b", branch,
                "-F", str(lib_dir / "mkdocs.yml"),
                "stable",
            ])
            if exit_code != 0:
                print(f"set-default failed: {lib_name}")
                return exit_code

    inject_landing_page(branch)

    return 0
