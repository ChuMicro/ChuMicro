"""Every shipped library appears in both hand-written library matrices.

The root ``README.md`` and ``libraries/README.md`` list libraries by
hand, and nothing tied them to the ``libraries/`` tree: two libraries
shipped, released, and reached PyPI before a person noticed neither
matrix mentioned them.  This test parametrizes over the shipped
libraries and fails the matrix that omits one.
"""

import pytest
from repo_layout import ROOT, is_parked


def _shipped_libraries() -> list[str]:
    """Return the names of non-parked libraries with a pyproject."""
    names = []
    for library_dir in sorted((ROOT / "libraries").iterdir()):
        if not (library_dir / "pyproject.toml").is_file():
            continue
        if is_parked(library_dir):
            continue
        names.append(library_dir.name)
    return names


_LIBRARIES = _shipped_libraries()


def test_the_scan_found_the_fleet() -> None:
    """A discovery that returns almost nothing would pass every row below."""
    assert len(_LIBRARIES) >= 10


@pytest.mark.parametrize("library", _LIBRARIES)
def test_root_readme_matrix_lists_the_library(library: str) -> None:
    """README.md's matrix links every shipped library."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"[{library}](libraries/{library}/)" in readme, (
        f"README.md's library matrix has no row for {library!r}"
    )


@pytest.mark.parametrize("library", _LIBRARIES)
def test_libraries_readme_matrix_lists_the_library(library: str) -> None:
    """libraries/README.md's matrix links every shipped library."""
    readme = (ROOT / "libraries" / "README.md").read_text(encoding="utf-8")
    assert f"[{library}]({library}/)" in readme, (
        f"libraries/README.md's matrix has no row for {library!r}"
    )
