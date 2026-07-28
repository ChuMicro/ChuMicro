"""Create chumicro-style library and workbench package trees.

The output layout::

    libraries/<name>/
    ├── VERSION
    ├── pyproject.toml
    ├── mkdocs.yml
    ├── README.md
    ├── src/<import_name>/
    │   ├── __init__.py
    │   ├── core.py
    │   └── testing.py
    ├── tests/
    │   ├── conftest.py
    │   └── test_<name>.py
    ├── functional_tests/
    │   └── .gitkeep
    ├── docs/
    │   ├── index.md, guide.md, api.md, testing.md
    └── examples/
        └── basic_usage.py

Templates ship beside this module under ``_payloads/library_template/``
and travel with the wheel.  ``package_kind="workbench"`` swaps the
four ``docs/`` templates for a workbench-flavored set under
``_payloads/workbench_template/``.  Every other file renders from the
one shared template set, with the kind steering the fragments that
differ: install lines, bundle links, source paths, and the README's
platform claim.

``python3 run.py new --library <name>`` is the usual entry point.
Callers that need finer control call :func:`scaffold_library`
directly with an explicit target directory.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: Default template root.  Holds pyproject, README, mkdocs, src/,
#: tests/, examples/, and the library-flavored docs/ templates.
#: Every scaffold reads from here unless explicitly overridden.
_LIBRARY_TEMPLATE_DIR = (
    Path(__file__).resolve().parent / "_payloads" / "library_template"
)

#: Override root for workbench-kind packages.  Carries only the
#: four docs/ templates (index.md, guide.md, api.md, testing.md).
#: Every other file in a workbench scaffold still loads from
#: :data:`_LIBRARY_TEMPLATE_DIR`.
_WORKBENCH_TEMPLATE_DIR = (
    Path(__file__).resolve().parent / "_payloads" / "workbench_template"
)


class LibraryAlreadyExistsError(FileExistsError):
    """Raised when the scaffold target directory already exists.

    Carries the path so callers can construct a precise message
    without re-deriving it.
    """


def _load_template(
    filename: str, *, template_dir: Path = _LIBRARY_TEMPLATE_DIR,
) -> str:
    """Read a scaffolding template by filename.

    Defaults to :data:`_LIBRARY_TEMPLATE_DIR`.  Pass
    *template_dir=_WORKBENCH_TEMPLATE_DIR* for the workbench-flavored
    docs templates.  Pure filesystem read, no caching, no formatting.
    """
    template_path = template_dir / filename
    if not template_path.is_file():
        raise FileNotFoundError(
            f"library scaffold template missing at {template_path}: "
            "chumicro-workspace install may be broken; reinstall.",
        )
    return template_path.read_text()


def _import_name(distribution: str) -> str:
    """Map a distribution name to its import name (hyphens → underscores)."""
    return distribution.replace("-", "_")


def _class_name(name: str) -> str:
    """Map ``my-project`` → ``MyProject`` for the starter class."""
    return "".join(
        part.capitalize()
        for part in name.replace("-", "_").split("_")
    )


def _display_name(name: str) -> str:
    """Map ``my-project`` → ``My Project`` for human-readable docstrings."""
    return name.replace("-", " ").replace("_", " ").title()


@dataclass(frozen=True)
class ScaffoldBranding:
    """Upstream project identity stamped into a scaffolded package.

    A scaffold rendered with ``CHUMICRO_BRANDING`` points its README
    banner, docs footers, ``[project.urls]``, and mkdocs ``repo_url`` at
    the ChuMicro repositories, bundle, and docs site where those packages
    actually live.  A scaffold rendered for a downstream
    ``chumicro-workspace new --library`` run uses the default,
    ``NEUTRAL_BRANDING``: the package owns itself, so the banner, family
    note, bundle install, project URLs, and docs footers are dropped rather
    than pointing the package owner at an upstream that isn't theirs.

    A ``None`` field selects the self-owned rendering for the text derived
    from it.  ``NEUTRAL_BRANDING`` leaves every field ``None``; a fully
    populated instance renders the branded form.

    ``distribution_prefix`` prepends the family name to the package's
    distribution and import names (``timing`` → ``chumicro-timing`` /
    ``chumicro_timing``).  The neutral default is empty: a downstream
    package is named by its owner, not stamped with someone else's brand.
    """

    author: str | None = None
    repo_url: str | None = None
    docs_base_url: str | None = None
    bundle_slug: str | None = None
    experimental_bundle_slug: str | None = None
    banner_image_url: str | None = None
    install_guide_url: str | None = None
    distribution_prefix: str = ""


#: Self-owned default.  A downstream scaffold carries no upstream identity.
NEUTRAL_BRANDING = ScaffoldBranding()

#: The mono-repo's own identity, passed by its ``new-library`` wrapper so
#: its scaffolds point at the repos, bundle, and docs site where ChuMicro
#: libraries actually live.
CHUMICRO_BRANDING = ScaffoldBranding(
    author="ChuMicro",
    repo_url="https://github.com/ChuMicro/ChuMicro",
    docs_base_url="https://chumicro.github.io/ChuMicro",
    bundle_slug="ChuMicro/ChuMicro-Bundle",
    experimental_bundle_slug="ChuMicro/ChuMicro-Bundle-Experimental",
    banner_image_url=(
        "https://raw.githubusercontent.com/ChuMicro/ChuMicro/main"
        "/support/docs/chumicro_tip.png"
    ),
    install_guide_url="https://github.com/ChuMicro/ChuMicro/blob/main/INSTALL.md",
    distribution_prefix="chumicro-",
)

#: Fragment keys every template references.  Both branding builders return
#: exactly this set so a template never hits a missing-key format error, and
#: passing the whole dict to every template is safe (unused keys are ignored).
_FRAGMENT_KEYS: tuple[str, ...] = (
    "banner",
    "family_note",
    "install_block",
    "platform_section",
    "contributing_intro",
    "docs_section",
    "find_section",
    "license_body",
    "author",
    "project_urls",
    "mkdocs_urls",
    "footer_index",
    "footer_page",
    "examples_url_base",
)


#: README "Contributing" body for a self-owned package.  The branded
#: rendering points contributors at the upstream repo's guide; a
#: self-owned package has no upstream, so the dev loop lives here.
_NEUTRAL_CONTRIBUTING = (
    "Set up a development install:\n"
    "\n"
    "```bash\n"
    "pip install -e .[test]\n"
    "pytest tests/                  # host-side tests\n"
    "pytest functional_tests/       # on-device tests (needs a board "
    "registered in devices.yml)\n"
    "```\n"
    "\n"
    "Register a board before running functional tests: "
    "`chumicro-workspace add-device <id> --address <port>`."
)


def _platform_section(package_kind: str) -> str:
    """Build the README's platform block for *package_kind*.

    A device library states the three runtimes it runs on and leaves a
    prompt for runtime quirks.  A workbench package gets nothing: it is
    host-only CPython, so a "runs on CircuitPython" claim would be false,
    and its host prerequisites belong in the Install section next to the
    ``pip install`` line.
    """
    if package_kind == "workbench":
        return ""
    return (
        "## Platform support\n"
        "\n"
        "Works on CPython, MicroPython, and CircuitPython.\n"
        "\n"
        "<!-- If the library has a runtime quirk (CircuitPython on rp2 has "
        "no TLS\n"
        "     server, `wifi.radio.connect` blocks on CircuitPython, the "
        "native\n"
        "     msgpack module ships only on CircuitPython firmware), add a\n"
        "     `### <Quirk name>` subsection here that names the constraint "
        "and\n"
        "     tells the reader what to do about it.  Don't bury the "
        "surprise in\n"
        "     a docstring. -->\n"
        "\n"
    )


def _neutral_fragments(distribution: str, package_kind: str) -> dict[str, str]:
    """Build the self-owned fragment set: no upstream banner, URLs, or footers.

    The emitted package installs from PyPI under its own name, carries a
    plain MIT license line, and leaves author + URL metadata for the owner
    to fill in.  Every ChuMicro repo, bundle, and docs-site reference the
    branded rendering would add is omitted.
    """
    fragments = {
        "banner": "",
        "family_note": "",
        "install_block": f"```bash\npip install {distribution}\n```\n\n",
        "platform_section": _platform_section(package_kind),
        "contributing_intro": _NEUTRAL_CONTRIBUTING,
        "docs_section": "",
        "find_section": "",
        "license_body": "MIT",
        "author": "TODO: your name",
        "project_urls": "",
        "mkdocs_urls": "",
        "footer_index": "",
        "footer_page": "",
        "examples_url_base": "examples/",
    }
    assert set(fragments) == set(_FRAGMENT_KEYS), (
        "neutral fragments must cover exactly _FRAGMENT_KEYS"
    )
    return fragments


def _branded_fragments(
    branding: ScaffoldBranding,
    name: str,
    distribution: str,
    import_name: str,
    package_kind: str,
) -> dict[str, str]:
    """Build the upstream-branded fragment set from *branding*'s URLs + names.

    Every source link (README, docs footers, pyproject ``Source``, mkdocs
    ``repo_url``, examples) resolves under the package kind's own tree,
    ``libraries/<name>`` or ``workbench/<name>``.  The install block, the
    "Find this library" rows, and the family note also follow the kind:
    workbench tools are host-only CPython, so they never enter the device
    bundle and never claim a device runtime.
    """
    tree_dir = "workbench" if package_kind == "workbench" else "libraries"
    bundle_url = f"https://github.com/{branding.bundle_slug}"
    bundle_name = branding.bundle_slug.rsplit("/", 1)[-1]
    experimental_bundle_url = f"https://github.com/{branding.experimental_bundle_slug}"
    experimental_bundle_name = branding.experimental_bundle_slug.rsplit("/", 1)[-1]
    pypi_url = f"https://pypi.org/project/{distribution}/"
    source_url = f"{branding.repo_url}/tree/main/{tree_dir}/{name}"
    issues_url = f"{branding.repo_url}/issues"

    if package_kind == "workbench":
        link_row = (
            f"[Source]({source_url}) · \\\n"
            f"[PyPI]({pypi_url}) · \\\n"
            f"[Issues]({issues_url})"
        )
        index_backlink = "[← All ChuMicro Packages](../../)"
        project_urls = (
            "[project.urls]\n"
            f'Homepage = "{branding.repo_url}"\n'
            f'Documentation = "{branding.docs_base_url}/{name}/stable/"\n'
            f'Source = "{source_url}"\n'
            f'Issues = "{issues_url}"\n'
            "\n"
        )
        family_note = (
            '<br clear="left">\n\n'
            f"> Part of the [ChuMicro]({branding.repo_url}) family: small, "
            "focused Python libraries for microcontrollers and laptops. "
            "[Browse all workbench tools.]"
            f"({branding.repo_url}/tree/main/workbench)\n"
            "> This is a [workbench tool]"
            f"({branding.repo_url}/blob/main/docs/contributing/workbench.md): "
            "it runs on your laptop, not on the board."
            "\n\n"
        )
        install_block = (
            "```bash\n"
            f"pip install {distribution}\n"
            "```\n\n"
            "<!-- INSTALL: a workbench tool is host-only, so PyPI is the "
            "whole story.\n"
            "     Add a sentence naming any host prerequisite the user "
            "installs\n"
            "     themselves (a binary on PATH, a Python floor) and any "
            "platform\n"
            "     that isn't supported. -->\n\n"
        )
        find_section = (
            "## Find this library\n\n"
            f"- **PyPI:** [{distribution}]({pypi_url})\n"
            f"- **Source:** [{tree_dir}/{name}]({source_url})\n\n"
        )
    else:
        link_row = (
            f"[Source]({source_url}) · \\\n"
            f"[PyPI]({pypi_url}) · \\\n"
            f"[Bundle]({bundle_url}) · \\\n"
            f"[Experimental Bundle]({experimental_bundle_url})"
        )
        index_backlink = "[← All ChuMicro Libraries](../../)"
        project_urls = (
            "[project.urls]\n"
            f'Homepage = "{branding.repo_url}"\n'
            f'Documentation = "{branding.docs_base_url}/{name}/stable/"\n'
            f'Source = "{source_url}"\n'
            f'Issues = "{issues_url}"\n'
            f'Bundle = "{bundle_url}"\n'
            "\n"
        )
        family_note = (
            '<br clear="left">\n\n'
            f"> Part of the [ChuMicro]({branding.repo_url}) family: small, "
            "focused Python libraries for microcontrollers and laptops. "
            f"[Browse all libraries.]({branding.repo_url}/tree/main/libraries)"
            "\n\n"
        )
        install_block = (
            "<!-- INSTALL: leave this block as it renders.  It is the "
            "standard\n"
            "     three-runtime install pattern; only edit it if your "
            "library has\n"
            "     unusual install requirements (rare). -->\n\n"
            "```bash\n"
            f"# CircuitPython (after `circup bundle-add {branding.bundle_slug}`)\n"
            f"circup install {import_name}\n\n"
            "# MicroPython\n"
            f"mpremote mip install github:{branding.bundle_slug}/{import_name}\n\n"
            "# CPython\n"
            f"pip install {distribution}\n"
            "```\n\n"
            "For bundle setup, pre-compiled `.mpy` bundles, the experimental "
            "channel, and details on PyPI naming, see the [chumicro INSTALL "
            f"guide]({branding.install_guide_url}).\n\n"
        )
        find_section = (
            "## Find this library\n\n"
            f"- **PyPI:** [{distribution}]({pypi_url})\n"
            f"- **Bundle:** [{bundle_name}]({bundle_url}/tree/main/{import_name}) "
            "(CircuitPython & MicroPython)\n"
            f"- **Experimental bundle:** [{experimental_bundle_name}]"
            f"({experimental_bundle_url}/tree/main/{import_name})\n"
            f"- **Source:** [{tree_dir}/{name}]({source_url})\n\n"
        )

    footer_open = '\n---\n\n<div class="chumicro-footer" markdown>\n\n'
    footer_index = f"{footer_open}{index_backlink}\n\n{link_row}\n\n</div>"
    footer_page = f"{footer_open}[← Home](index.md)\n\n{link_row}\n\n</div>"

    fragments = {
        "banner": (
            f'<img src="{branding.banner_image_url}"\n'
            'align="left" width="64" '
            'style="margin-right: 16px; margin-bottom: 8px;">\n\n'
        ),
        "family_note": family_note,
        "install_block": install_block,
        "platform_section": _platform_section(package_kind),
        "contributing_intro": (
            "Issues, bug reports, and pull requests are welcome, and so is "
            '"I ran it on this board and here\'s what happened", some of '
            "the most useful feedback a hardware project can get.  "
            f"Development happens in the [ChuMicro repository]"
            f"({branding.repo_url}), whose contributing guide covers setup "
            "and the test workflow."
        ),
        "docs_section": (
            "## Docs\n\n"
            f"📖 **[Stable docs]({branding.docs_base_url}/{name}/stable/)** · "
            f"**[Experimental docs]({branding.docs_base_url}/{name}/experimental/)**"
            "\n\n"
        ),
        "find_section": find_section,
        "license_body": f"[MIT]({branding.repo_url}/blob/main/LICENSE)",
        "author": branding.author,
        "project_urls": project_urls,
        "mkdocs_urls": (
            f"site_url: {branding.docs_base_url}/{name}/\n"
            f"repo_url: {source_url}\n"
            "repo_name: Source\n"
        ),
        "footer_index": footer_index,
        "footer_page": footer_page,
        "examples_url_base": (
            f"{branding.repo_url}/blob/main/{tree_dir}/{name}/examples/"
        ),
    }
    assert set(fragments) == set(_FRAGMENT_KEYS), (
        "branded fragments must cover exactly _FRAGMENT_KEYS"
    )
    return fragments


def _branding_fragments(
    branding: ScaffoldBranding,
    name: str,
    distribution: str,
    import_name: str,
    package_kind: str,
) -> dict[str, str]:
    """Return the fragment dict the README / pyproject / mkdocs / docs use.

    Dispatches to the self-owned or upstream-branded builder.  ``repo_url``
    is the tell: ``None`` (the neutral default) yields self-owned output.
    """
    if branding.repo_url is None:
        return _neutral_fragments(distribution, package_kind)
    return _branded_fragments(
        branding, name, distribution, import_name, package_kind,
    )


def scaffold_library(
    target_dir: Path,
    name: str,
    *,
    package_kind: str = "library",
    branding: ScaffoldBranding = NEUTRAL_BRANDING,
) -> Path:
    """Create a library tree at ``target_dir / name``.

    Args:
        target_dir: Parent directory.  Created if missing.
        name: Library short name (e.g. ``"gpio"``).  The branding's
            ``distribution_prefix`` prepends to form the distribution
            name, and hyphens convert to underscores for the import
            path (neutral ``my-project`` → ``my_project``; branded
            ``timing`` → ``chumicro-timing`` / ``chumicro_timing``).
        package_kind: ``"library"`` (default) for cross-runtime
            device packages.  Produces the standard chumicro library
            shape with no extras.  ``"workbench"`` for host-only
            CPython tools uses a workbench-flavored pyproject
            template with a ``[project.scripts]`` block (CLI entry
            point), and pulls the four ``docs/`` templates from
            ``_payloads/workbench_template/`` (no Runner pattern,
            no Memory notes, no Bundle footer link).  The rest of
            the tree (src/tests/examples/README/mkdocs) renders from
            the shared templates, with the kind steering the README's
            install block, "Find this library" rows, family note, and
            platform claim, plus every source URL's tree.
        branding: Upstream identity stamped into the README banner,
            docs footers, ``[project.urls]``, and mkdocs ``repo_url``.
            Defaults to ``NEUTRAL_BRANDING`` so a downstream scaffold
            owns itself; the mono-repo's own ``new-library`` flow passes
            ``CHUMICRO_BRANDING`` to point its packages at the ChuMicro
            repos, bundle, and docs site.

    Returns:
        Path to the created library directory.

    Raises:
        LibraryAlreadyExistsError: When the target dir already
            exists.  Caller decides whether to delete + retry or
            bail.
        ValueError: When *package_kind* isn't one of the supported
            values.
    """
    if package_kind not in ("library", "workbench"):
        raise ValueError(
            f"package_kind must be 'library' or 'workbench', "
            f"got {package_kind!r}",
        )

    library_dir = target_dir / name
    if library_dir.exists():
        raise LibraryAlreadyExistsError(library_dir)

    distribution = f"{branding.distribution_prefix}{name}"
    import_name = _import_name(distribution)
    class_name = _class_name(name)
    display_name = _display_name(name)
    test_name = name.replace("-", "_")
    branding_fragments = _branding_fragments(
        branding, name, distribution, import_name, package_kind,
    )

    (library_dir / "src" / import_name).mkdir(parents=True)
    (library_dir / "tests").mkdir()
    (library_dir / "functional_tests").mkdir()
    (library_dir / "docs").mkdir()
    (library_dir / "examples").mkdir()
    (library_dir / "functional_tests" / ".gitkeep").touch()

    # VERSION
    (library_dir / "VERSION").write_text("0.1.0\n")

    pyproject_template = (
        "pyproject.workbench.toml.template"
        if package_kind == "workbench"
        else "pyproject.toml.template"
    )
    (library_dir / "pyproject.toml").write_text(
        _load_template(pyproject_template).format(
            name=name, distribution=distribution,
            import_name=import_name, **branding_fragments,
        ),
    )
    (library_dir / "mkdocs.yml").write_text(
        _load_template("mkdocs.yml.template").format(
            name=name, distribution=distribution, **branding_fragments,
        ),
    )
    (library_dir / "README.md").write_text(
        _load_template("readme.md.template").format(
            name=name, distribution=distribution,
            import_name=import_name, **branding_fragments,
        ),
    )

    # docs/.  Workbench-kind packages pull from _WORKBENCH_TEMPLATE_DIR.
    docs_template_dir = (
        _WORKBENCH_TEMPLATE_DIR
        if package_kind == "workbench"
        else _LIBRARY_TEMPLATE_DIR
    )
    (library_dir / "docs" / "index.md").write_text(
        _load_template(
            "index.md.template", template_dir=docs_template_dir,
        ).format(
            name=name, distribution=distribution,
            import_name=import_name, **branding_fragments,
        ),
    )
    (library_dir / "docs" / "guide.md").write_text(
        _load_template(
            "guide.md.template", template_dir=docs_template_dir,
        ).format(
            name=name, distribution=distribution,
            import_name=import_name, **branding_fragments,
        ),
    )
    (library_dir / "docs" / "api.md").write_text(
        _load_template(
            "api.md.template", template_dir=docs_template_dir,
        ).format(
            name=name, distribution=distribution,
            import_name=import_name, **branding_fragments,
        ),
    )
    (library_dir / "docs" / "testing.md").write_text(
        _load_template(
            "testing.md.template", template_dir=docs_template_dir,
        ).format(
            name=name, distribution=distribution,
            import_name=import_name, **branding_fragments,
        ),
    )

    (library_dir / "examples" / "basic_usage.py").write_text(
        _load_template("basic_usage.py.template").format(
            name=name,
            display_name=display_name,
            import_name=import_name,
            class_name=class_name,
        ),
    )

    # examples/helpers.py: standalone wifi-up + msgpack-decoder helper
    # for libraries whose examples bring wifi up.  No template variables.
    (library_dir / "examples" / "helpers.py").write_text(
        _load_template("helpers.py.template"),
    )

    # src/<package>/__init__.py: absolute imports only.  CircuitPython
    # RAM-mode `exec()`s library modules without a `__package__`, so
    # leading-dot relatives break at deploy.
    (library_dir / "src" / import_name / "__init__.py").write_text(
        f'"""Public exports for the {distribution} package."""\n'
        f"\n"
        f"from {import_name}.core import {class_name}\n"
        f"\n"
        f'__all__ = ["{class_name}"]\n',
    )
    (library_dir / "src" / import_name / "core.py").write_text(
        _load_template("core.py.template").format(
            name=name, distribution=distribution, class_name=class_name,
        ),
    )
    (library_dir / "src" / import_name / "testing.py").write_text(
        _load_template("testing.py.template").format(
            name=name, distribution=distribution, import_name=import_name,
        ),
    )

    # tests/.  No __init__.py, which keeps test module names from
    # colliding across libraries when pytest collects.
    (library_dir / "tests" / "conftest.py").write_text(
        f'"""Test configuration for the {distribution} package."""\n',
    )
    (library_dir / "tests" / f"test_{test_name}.py").write_text(
        _load_template("test_library.py.template").format(
            import_name=import_name, class_name=class_name,
        ),
    )

    return library_dir
