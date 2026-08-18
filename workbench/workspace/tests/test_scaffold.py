"""Tests for the library scaffolder."""

from __future__ import annotations

from pathlib import Path

import pytest
from chumicro_workspace.scaffold import (
    CHUMICRO_BRANDING,
    NEUTRAL_BRANDING,
    LibraryAlreadyExistsError,
    _class_name,
    _display_name,
    _import_name,
    scaffold_library,
)


class TestNameHelpers:
    """Tiny helpers map a hyphenated short-name to its derived forms."""

    def test_import_name_underscores(self) -> None:
        assert _import_name("gpio") == "gpio"
        assert _import_name("chumicro-my-project") == "chumicro_my_project"
        assert _import_name("my_project") == "my_project"

    def test_class_name_camel_case(self) -> None:
        assert _class_name("gpio") == "Gpio"
        assert _class_name("my-project") == "MyProject"
        assert _class_name("my_project") == "MyProject"

    def test_display_name_title_case(self) -> None:
        assert _display_name("gpio") == "Gpio"
        assert _display_name("my-project") == "My Project"
        assert _display_name("my_project") == "My Project"


class TestRegisterInvocationInReadme:
    """The generated README's add-device instruction adapts to its home."""

    def test_names_the_shim_inside_a_template_workspace(
        self, tmp_path: Path,
    ) -> None:
        (tmp_path / "workspace.yml").write_text("# machinery only\n")
        (tmp_path / "run.py").write_text("# dispatcher shim\n")
        created = scaffold_library(tmp_path / "libraries", "gpio")
        readme_text = (created / "README.md").read_text()
        assert "python3 run.py add-device" in readme_text
        assert "chumicro-workspace add-device" not in readme_text

    def test_names_the_cli_in_a_bare_workspace(self, tmp_path: Path) -> None:
        (tmp_path / "workspace.yml").write_text("# machinery only\n")
        created = scaffold_library(tmp_path / "libraries", "gpio")
        readme_text = (created / "README.md").read_text()
        assert "chumicro-workspace add-device" in readme_text

    def test_names_the_cli_outside_any_workspace(self, tmp_path: Path) -> None:
        created = scaffold_library(tmp_path / "libraries", "gpio")
        readme_text = (created / "README.md").read_text()
        assert "chumicro-workspace add-device" in readme_text


class TestScaffoldLibrary:
    def test_creates_canonical_layout(self, tmp_path: Path) -> None:
        created = scaffold_library(tmp_path / "libraries", "gpio")
        # Returned path matches the new tree.
        assert created == tmp_path / "libraries" / "gpio"
        assert created.is_dir()
        # Top-level file shape.
        assert (created / "VERSION").read_text() == "0.1.0\n"
        assert (created / "pyproject.toml").is_file()
        assert (created / "mkdocs.yml").is_file()
        assert (created / "README.md").is_file()
        # src/<package>/.
        # Neutral default: no chumicro- prefix on a downstream package.
        package_dir = created / "src" / "gpio"
        assert (package_dir / "__init__.py").is_file()
        assert (package_dir / "core.py").is_file()
        assert (package_dir / "testing.py").is_file()
        # tests/.
        assert (created / "tests" / "conftest.py").is_file()
        assert (created / "tests" / "test_gpio.py").is_file()
        # functional_tests/ + .gitkeep so empty dir survives git.
        assert (created / "functional_tests" / ".gitkeep").is_file()
        # docs/.
        for doc_filename in ("index.md", "guide.md", "api.md", "testing.md"):
            assert (created / "docs" / doc_filename).is_file()
        # examples/.
        assert (created / "examples" / "basic_usage.py").is_file()
        helpers_text = (created / "examples" / "helpers.py").read_text()
        assert "def wifi_up" in helpers_text
        assert "def runtime_config" in helpers_text
        assert "def _msgpack_unpack" in helpers_text

    def test_init_py_imports_starter_class(self, tmp_path: Path) -> None:
        """The package's __init__.py wires `from <pkg>.core import <Class>`."""
        created = scaffold_library(tmp_path / "libraries", "gpio")
        init_text = (created / "src" / "gpio" / "__init__.py").read_text()
        assert "from gpio.core import Gpio" in init_text
        assert '__all__ = ["Gpio"]' in init_text

    def test_hyphen_name_translates_to_snake_case_imports(
        self, tmp_path: Path,
    ) -> None:
        """`my-project` → package `my_project`, class `MyProject`."""
        created = scaffold_library(tmp_path / "libraries", "my-project")
        # Filesystem uses hyphenated short-name (chumicro convention).
        assert created.name == "my-project"
        # Package + module name use snake_case.
        package_init = (
            created / "src" / "my_project" / "__init__.py"
        )
        assert package_init.is_file()
        text = package_init.read_text()
        assert "from my_project.core import MyProject" in text
        # Test file uses snake_case basename.
        assert (created / "tests" / "test_my_project.py").is_file()

    def test_creates_target_parent_when_missing(self, tmp_path: Path) -> None:
        """Parent dirs are auto-created — no need to pre-mkdir libraries/."""
        target_parent = tmp_path / "deep" / "nested" / "libraries"
        created = scaffold_library(target_parent, "gpio")
        assert created.is_dir()
        assert target_parent.is_dir()

    def test_existing_target_raises(self, tmp_path: Path) -> None:
        scaffold_library(tmp_path / "libraries", "gpio")
        with pytest.raises(LibraryAlreadyExistsError) as caught:
            scaffold_library(tmp_path / "libraries", "gpio")
        assert "gpio" in str(caught.value)

    def test_unknown_package_kind_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="package_kind"):
            scaffold_library(
                tmp_path / "libraries", "gpio", package_kind="firmware",
            )

    def test_missing_template_names_the_path(self) -> None:
        from chumicro_workspace.scaffold import _load_template

        with pytest.raises(FileNotFoundError, match="not-a-template"):
            _load_template("not-a-template.template")

    def test_workbench_kind_scaffolds_workbench_flavored_docs(
        self, tmp_path: Path,
    ) -> None:
        """`package_kind="workbench"` pulls docs from the workbench template.

        Workbench packages aren't cross-runtime and don't ship via
        bundles, so their docs should not carry the library shape's
        Runner pattern / Memory notes sections or the Bundle footer
        link.  Also call out that the branded source URL points at
        ``workbench/<name>/``, not ``libraries/<name>/``.
        """
        created = scaffold_library(
            tmp_path / "workbench", "trinket", package_kind="workbench",
            branding=CHUMICRO_BRANDING,
        )
        guide_text = (created / "docs" / "guide.md").read_text()
        index_text = (created / "docs" / "index.md").read_text()
        api_text = (created / "docs" / "api.md").read_text()
        testing_text = (created / "docs" / "testing.md").read_text()

        # Library-flavored headings + footer link must be absent.
        # (The workbench guide's GENERATION INSTRUCTIONS block names
        # the missing sections by their bare titles, so match the
        # heading form explicitly.)
        for doc_text in (guide_text, index_text, api_text, testing_text):
            assert "## Runner pattern" not in doc_text
            assert "## Memory notes" not in doc_text
            assert "ChuMicro-Bundle" not in doc_text

        # Workbench source URLs replace the library path.
        for doc_text in (guide_text, index_text, api_text, testing_text):
            assert "tree/main/workbench/trinket" in doc_text
            assert "tree/main/libraries/trinket" not in doc_text

        # Index footer relabel: "Libraries" → "Packages".
        assert "All ChuMicro Packages" in index_text
        assert "All ChuMicro Libraries" not in index_text

    def test_workbench_kind_readme_is_host_only(
        self, tmp_path: Path,
    ) -> None:
        """A workbench README installs from PyPI and claims no device runtime.

        Host tools never enter the CircuitPython / MicroPython bundle, so
        the install block is a plain ``pip install``, the "Find this
        library" list drops both bundle rows, and the library shape's
        "Platform support" claim is omitted rather than promising a
        laptop-only tool runs on a board.
        """
        created = scaffold_library(
            tmp_path / "workbench", "trinket", package_kind="workbench",
            branding=CHUMICRO_BRANDING,
        )
        readme_text = (created / "README.md").read_text()
        assert "pip install chumicro-trinket" in readme_text
        assert "circup" not in readme_text
        assert "mip install" not in readme_text
        assert "**Bundle:**" not in readme_text
        assert "**Experimental bundle:**" not in readme_text
        assert "## Platform support" not in readme_text
        assert "Works on CPython, MicroPython, and CircuitPython" not in readme_text
        assert "- **Source:** [workbench/trinket]" in readme_text
        # Family note sends the reader to the workbench index, not the
        # library one.
        assert "Browse all workbench tools." in readme_text

    def test_rendered_files_carry_no_em_dashes(self, tmp_path: Path) -> None:
        """Every rendered file is em-dash free, in all three flavors.

        The style guide bans the em-dash everywhere, including code
        comments and table cells, and a scaffold is the first draft of a
        package's published docs.
        """
        roots = (
            scaffold_library(
                tmp_path / "branded", "gpio", branding=CHUMICRO_BRANDING,
            ),
            scaffold_library(tmp_path / "neutral", "my-project"),
            scaffold_library(
                tmp_path / "workbench", "trinket",
                package_kind="workbench", branding=CHUMICRO_BRANDING,
            ),
        )
        for root in roots:
            for path in sorted(root.rglob("*")):
                if not path.is_file():
                    continue
                assert "—" not in path.read_text(), f"em-dash in {path}"

    def test_library_kind_keeps_library_flavored_docs(
        self, tmp_path: Path,
    ) -> None:
        """Branded `package_kind="library"` keeps the library doc shape."""
        created = scaffold_library(
            tmp_path / "libraries", "gpio", branding=CHUMICRO_BRANDING,
        )
        guide_text = (created / "docs" / "guide.md").read_text()
        index_text = (created / "docs" / "index.md").read_text()

        # Library shape includes Runner pattern + Memory notes
        # sections and the Bundle footer link.
        assert "Runner pattern" in guide_text
        assert "Memory notes" in guide_text
        assert "ChuMicro-Bundle" in guide_text

        # Library source URL.
        assert "tree/main/libraries/gpio" in guide_text
        assert "All ChuMicro Libraries" in index_text


class TestScaffoldBranding:
    """Branded scaffolds point at the upstream repos; neutral scaffolds don't.

    The mono-repo passes ``CHUMICRO_BRANDING`` so its packages resolve at
    the ChuMicro repos, bundle, and docs site; a downstream
    ``chumicro-workspace new --library`` run leaves the neutral default so
    the emitted package owns itself.
    """

    def test_neutral_is_the_default(self, tmp_path: Path) -> None:
        """No branding argument means the self-owned rendering.

        A scaffold with no ``branding=`` carries none of the ChuMicro
        banner, family blockquote, bundle, repository, or docs-site URLs
        that the branded rendering adds.  (Worked-example body prose that
        names sibling chumicro libraries is shared template content the
        owner rewrites, and is out of scope here.)
        """
        created = scaffold_library(tmp_path / "libraries", "gpio")
        readme_text = (created / "README.md").read_text()
        assert "chumicro_tip.png" not in readme_text
        assert "Part of the [ChuMicro]" not in readme_text
        assert "ChuMicro-Bundle" not in readme_text
        assert "chumicro.com" not in readme_text
        assert "chumicro.github.io" not in readme_text
        # No branding-derived URL survives.  The one ChuMicro URL left is
        # the worked example's link to chumicro-timing under "Where this
        # fits": README links are absolute because relative sibling paths
        # render broken on PyPI, and the owner rewrites that prose.
        assert "github.com/ChuMicro/ChuMicro/issues" not in readme_text
        assert "github.com/ChuMicro/ChuMicro/blob/main/LICENSE" not in readme_text
        assert readme_text.count("github.com/ChuMicro") == 1
        assert "libraries/timing) for tick arithmetic" in readme_text

    def test_neutral_readme_installs_from_pypi_only(
        self, tmp_path: Path,
    ) -> None:
        """The neutral README install block is a plain PyPI install.

        A user's own library isn't in the ChuMicro bundle, so the circup /
        mip bundle lines and the mono-repo INSTALL-guide link are dropped;
        only ``pip install chumicro-<name>`` remains.
        """
        created = scaffold_library(tmp_path / "libraries", "gpio")
        readme_text = (created / "README.md").read_text()
        assert "pip install gpio" in readme_text
        assert "circup" not in readme_text
        assert "mip install" not in readme_text
        assert "Clone the [mono-repo]" not in readme_text

    def test_neutral_pyproject_omits_project_urls_and_author(
        self, tmp_path: Path,
    ) -> None:
        """The neutral pyproject drops the ChuMicro URLs and authorship.

        ``[project.urls]`` is omitted entirely (no Homepage / Source /
        Issues / Bundle pointing at ChuMicro) and the author is a TODO
        placeholder rather than "ChuMicro".
        """
        created = scaffold_library(tmp_path / "libraries", "gpio")
        pyproject_text = (created / "pyproject.toml").read_text()
        assert "[project.urls]" not in pyproject_text
        assert "github.com/ChuMicro" not in pyproject_text
        assert 'name = "ChuMicro"' not in pyproject_text
        assert "TODO" in pyproject_text

    def test_neutral_mkdocs_omits_site_and_repo_urls(
        self, tmp_path: Path,
    ) -> None:
        """The neutral mkdocs.yml keeps site_name but drops the ChuMicro URLs."""
        created = scaffold_library(tmp_path / "libraries", "gpio")
        mkdocs_text = (created / "mkdocs.yml").read_text()
        assert "site_name: gpio" in mkdocs_text
        assert "repo_url:" not in mkdocs_text
        assert "chumicro.com" not in mkdocs_text
        assert "chumicro.github.io" not in mkdocs_text

    def test_neutral_docs_drop_the_branded_footer(
        self, tmp_path: Path,
    ) -> None:
        """Neutral docs carry no upstream footer link block."""
        created = scaffold_library(tmp_path / "libraries", "gpio")
        for doc_filename in ("index.md", "guide.md", "api.md", "testing.md"):
            doc_text = (created / "docs" / doc_filename).read_text()
            assert "chumicro-footer" not in doc_text
            assert "github.com/ChuMicro" not in doc_text

    def test_branded_readme_carries_upstream_identity(
        self, tmp_path: Path,
    ) -> None:
        """`CHUMICRO_BRANDING` restores the banner, family note, and bundle.

        The mono-repo's own scaffolds keep the ChuMicro hero banner, the
        "Part of the ChuMicro family" note, the bundle install lines, and
        the MIT-into-monorepo license link.
        """
        created = scaffold_library(
            tmp_path / "libraries", "gpio", branding=CHUMICRO_BRANDING,
        )
        readme_text = (created / "README.md").read_text()
        assert "chumicro_tip.png" in readme_text
        assert "Part of the [ChuMicro]" in readme_text
        assert "circup install chumicro_gpio" in readme_text
        assert "github.com/ChuMicro/ChuMicro/blob/main/LICENSE" in readme_text
        # Device libraries keep the three-runtime platform claim and both
        # bundle rows; the workbench kind drops them.
        assert "## Platform support" in readme_text
        assert "**Experimental bundle:**" in readme_text

    def test_branded_and_neutral_share_the_body(self, tmp_path: Path) -> None:
        """Both flavors render from one template set: shared body is identical.

        The quick-example and API-summary body a user rewrites is the same
        under either branding; only the upstream-identity fragments differ.
        """
        branded = scaffold_library(
            tmp_path / "branded", "gpio", branding=CHUMICRO_BRANDING,
        )
        neutral = scaffold_library(
            tmp_path / "neutral", "gpio", branding=NEUTRAL_BRANDING,
        )
        for text in (
            (branded / "README.md").read_text(),
            (neutral / "README.md").read_text(),
        ):
            assert "**A single-shot timer that fires once after N milliseconds.**" in text
            assert "## Quick example" in text
