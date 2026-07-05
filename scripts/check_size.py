"""Size-regression gate: fail when a device library outgrows its budget.

A committed budget file (``size-budgets.toml`` at the repo root) pins a
per-library ceiling on two host-measurable dimensions, and this gate
fails preflight the moment a library's measured size crosses either
ceiling.  It stops unchecked flash-footprint growth now; the ceilings
ratchet DOWN as cut rounds land (see the budget file header for the
contract).

Two measured dimensions per library, both summed over the *shipped*
package files under ``libraries/<name>/src/chumicro_<name>`` (test-support
modules — ``testing.py`` and anything :func:`is_test_support_module`
flags — are excluded, mirroring how the deploy walkers skip them in
``chumicro_deploy/sources.py``):

- ``stripped`` — UTF-8 bytes after running the real deploy pipeline's
  :func:`strip_source` (Decision 0090: blanks docstrings/comments,
  parse-tree-equivalence guarded) over each ``.py`` module.  Tracks the
  source bytes a board actually receives, not the prose that drifts with
  every rewrite.
- ``mpy`` — bytes of the ``.mpy`` bytecode after compiling each stripped
  module with the prepared MicroPython ``mpy-cross`` at
  ``.tools/micropython-<version>/mpy-cross/build/mpy-cross``.  Tracks the
  compiled flash footprint.

On-device import heap is deliberately NOT gated here — that lives in the
sweeps.  This gate is host-only, hermetic (no boards, no network), and
fast (strip + mpy-cross of the whole fleet is well under a second).

If the prepared ``mpy-cross`` is missing the gate FAILs with the
``prepare-mpy-cross`` remedy rather than skipping silently — a skipped
size gate is a silent cap, and silent caps are how footprint creeps back.

Usage::

    python scripts/run.py check-size
    python scripts/check_size.py [--budget-file PATH]

Exits 0 when every library sits at or under both ceilings.  Exits 1 on
any violation (over budget, a library missing a budget entry, a stale
budget entry, a missing/malformed budget file, or a missing mpy-cross).
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from chumicro_deploy.runtime_marker import is_test_support_module
from chumicro_deploy.source_minify import strip_source
from repo_layout import (
    ROOT,
    TOOLS,
    discover_library_dirs,
    find_package_dir,
    load_tomllib,
    read_runtime_versions,
)

#: The committed budget file.  Top-level TOML tables keyed by library
#: name, each carrying integer ``stripped`` and ``mpy`` byte ceilings.
BUDGET_FILE = ROOT / "size-budgets.toml"

#: The two measured dimensions, in report order.
DIMENSIONS: tuple[str, ...] = ("stripped", "mpy")

#: Directory / file names that never ship to a board.  Mirrors
#: ``DirectorySource.DEFAULT_EXCLUDED`` so the size walk sees the same
#: files the deploy walk does.
_EXCLUDED_NAMES: frozenset[str] = frozenset(
    {"__pycache__", ".DS_Store", ".git", ".pytest_cache", ".mypy_cache"},
)

#: Printed whenever the prepared mpy-cross can't be found.  The gate
#: needs the exact pinned compiler so its .mpy numbers match the
#: committed ceilings; a PATH mpy-cross of another version would flap
#: the gate, so there is no PATH fallback here (unlike
#: ``shared.resolve_mp_mpy_cross``).
MPY_CROSS_REMEDY = "Run `python scripts/run.py prepare-mpy-cross` to build it."

#: Printed under any violation.  Names the ratchet-down contract so an
#: author knows a raise is not the default move.
RATCHET_REMEDY = (
    "Size budgets in size-budgets.toml ratchet DOWN only.  Cut the library "
    "back under its ceiling, or — with a measured justification in the commit "
    "— raise the ceiling in size-budgets.toml (mirrors the heap-override "
    "convention in target-runtimes.toml)."
)


class BudgetError(Exception):
    """Raised when ``size-budgets.toml`` is missing or malformed.

    Carries a human-readable message naming the file and the specific
    defect (syntax error, non-table entry, missing / non-integer
    dimension) so the gate can print it verbatim.
    """


class MpyCompileError(Exception):
    """Raised when ``mpy-cross`` rejects a stripped module.

    Names the offending source file and the compiler's stderr.  Should
    not happen for valid shipped source (the deploy pipeline compiles
    the same stripped bytes), so it surfaces a real toolchain or source
    problem rather than being swallowed.
    """

    def __init__(self, source_file: Path, stderr: str) -> None:
        self.source_file = source_file
        self.stderr = stderr
        super().__init__(f"mpy-cross failed on {source_file}:\n{stderr}")


def prepared_mpy_cross() -> Path | None:
    """Return the pinned MicroPython mpy-cross path, or ``None`` if absent.

    Resolves the prepared compiler under ``.tools/`` from the version
    pinned in ``target-runtimes.toml``.  Returns ``None`` when the
    version can't be read or the binary hasn't been built — the gate
    turns that into a FAIL with the ``prepare-mpy-cross`` remedy.  No
    PATH fallback: the committed ceilings are calibrated to this exact
    compiler.
    """
    version = read_runtime_versions().get("micropython", {}).get("version")
    if not version:
        return None
    candidate = TOOLS / f"micropython-{version}" / "mpy-cross" / "build" / "mpy-cross"
    return candidate if candidate.exists() else None


def load_budgets(path: Path) -> dict[str, dict[str, int]]:
    """Parse *path* into ``{library_name: {"stripped": int, "mpy": int}}``.

    Every top-level TOML table is a library budget with a non-negative
    integer ceiling for each dimension in :data:`DIMENSIONS`.

    Raises:
        BudgetError: If the file is missing, not valid TOML, has a
            non-table entry, or is missing / has a non-integer value for
            any dimension.
    """
    tomllib = load_tomllib()
    try:
        with path.open("rb") as budget_file:
            raw = tomllib.load(budget_file)
    except FileNotFoundError as error:
        raise BudgetError(f"size-budget file not found: {path}") from error
    except tomllib.TOMLDecodeError as error:
        raise BudgetError(
            f"size-budget file is not valid TOML ({path}): {error}",
        ) from error

    budgets: dict[str, dict[str, int]] = {}
    for name, table in raw.items():
        if not isinstance(table, dict):
            raise BudgetError(
                f"size-budget entry [{name}] must be a table, "
                f"got {type(table).__name__}.",
            )
        entry: dict[str, int] = {}
        for dimension in DIMENSIONS:
            if dimension not in table:
                raise BudgetError(
                    f"size-budget entry [{name}] is missing '{dimension}'.",
                )
            value = table[dimension]
            # bool is an int subclass; a stray ``mpy = true`` must not
            # sail through as 1.
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise BudgetError(
                    f"size-budget entry [{name}].{dimension} must be a "
                    f"non-negative integer, got {value!r}.",
                )
            entry[dimension] = value
        budgets[name] = entry
    return budgets


def shipped_source_files(package_dir: Path) -> list[Path]:
    """Return the ``.py`` files under *package_dir* that ship to a board.

    Walks *package_dir* recursively and keeps every ``.py`` file except
    those in an excluded directory (:data:`_EXCLUDED_NAMES`) or flagged
    as a test-support module by :func:`is_test_support_module` (a
    library's ``testing.py`` fakes, which never reach a product).
    Mirrors the deploy walk in ``chumicro_deploy/sources.py`` so the
    budgeted set matches the shipped set.
    """
    files: list[Path] = []
    for source_file in sorted(package_dir.rglob("*.py")):
        relative_parts = source_file.relative_to(package_dir).parts
        if any(part in _EXCLUDED_NAMES for part in relative_parts):
            continue
        if is_test_support_module(source_file):
            continue
        files.append(source_file)
    return files


def measure_library(
    package_dir: Path, src_root: Path, mpy_cross: str,
) -> dict[str, int]:
    """Measure *package_dir*'s ``stripped`` and ``mpy`` byte totals.

    For each shipped module (see :func:`shipped_source_files`): strip it
    with the real deploy :func:`strip_source`, count the stripped UTF-8
    bytes, compile the stripped bytes with *mpy_cross*, and count the
    ``.mpy`` bytes.  Both totals sum over the library's shipped modules.

    The compile uses ``-s <package-relative path>`` so the embedded
    source name (and thus the ``.mpy`` size) is deterministic regardless
    of the temp directory the compile runs in.

    Args:
        package_dir: The ``.../src/chumicro_<name>`` package directory.
        src_root: The library's ``src/`` directory, used to derive the
            package-relative ``-s`` name for each module.
        mpy_cross: Path to the MicroPython mpy-cross binary.

    Raises:
        MpyCompileError: If mpy-cross rejects a stripped module.
    """
    stripped_total = 0
    mpy_total = 0
    with tempfile.TemporaryDirectory() as temp_root:
        temp_dir = Path(temp_root)
        for index, source_file in enumerate(shipped_source_files(package_dir)):
            source = source_file.read_text(encoding="utf-8")
            stripped = strip_source(source)
            stripped_total += len(stripped.encode("utf-8"))

            source_name = source_file.relative_to(src_root).as_posix()
            temp_py = temp_dir / f"module_{index}.py"
            temp_py.write_text(stripped, encoding="utf-8")
            temp_mpy = temp_dir / f"module_{index}.mpy"
            result = subprocess.run(
                [mpy_cross, "-s", source_name, "-o", str(temp_mpy), str(temp_py)],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                raise MpyCompileError(source_file, result.stderr.strip())
            mpy_total += temp_mpy.stat().st_size
    return {"stripped": stripped_total, "mpy": mpy_total}


def _check(
    *,
    budget_path: Path,
    library_dirs: list[Path],
    mpy_cross: str | None,
) -> int:
    """Run the size gate; return an exit code (0 pass, 1 fail).

    Measures every library under *library_dirs*, compares each against
    its entry in the budget file at *budget_path*, and reports one FAIL
    line per violation.  A library with no budget entry, a budget entry
    with no matching library, a missing / malformed budget file, and a
    missing *mpy_cross* all fail — none are skipped silently.

    Args:
        budget_path: Path to the size-budget TOML file.
        library_dirs: Library root directories to measure.
        mpy_cross: Path to the MicroPython mpy-cross binary, or ``None``
            when it could not be resolved.
    """
    if mpy_cross is None:
        print("FAIL: prepared mpy-cross not found — cannot measure .mpy size.")
        print(f"      {MPY_CROSS_REMEDY}")
        return 1

    try:
        budgets = load_budgets(budget_path)
    except BudgetError as error:
        print(f"FAIL: {error}")
        return 1

    # Measure every library first so the pass summary can report fleet
    # totals and a missing-entry message can quote the measured numbers.
    measured: dict[str, dict[str, int]] = {}
    for library_dir in sorted(library_dirs, key=lambda path: path.name):
        package_dir = find_package_dir(library_dir)
        if package_dir is None:
            continue
        measured[library_dir.name] = measure_library(
            package_dir, library_dir / "src", mpy_cross,
        )

    violations: list[str] = []
    for name in sorted(measured):
        budget = budgets.get(name)
        if budget is None:
            sizes = measured[name]
            violations.append(
                f"FAIL: {name} — no size-budget entry in {budget_path.name}; "
                f"measured stripped={sizes['stripped']} B, mpy={sizes['mpy']} B. "
                f"Add a [{name}] section with these as ceilings.",
            )
            continue
        for dimension in DIMENSIONS:
            actual = measured[name][dimension]
            ceiling = budget[dimension]
            if actual > ceiling:
                violations.append(
                    f"FAIL: {name} {dimension} {actual} B > ceiling "
                    f"{ceiling} B (over by {actual - ceiling} B).",
                )

    for name in sorted(set(budgets) - set(measured)):
        violations.append(
            f"FAIL: {name} — size-budget entry has no matching library; "
            f"remove the [{name}] section from {budget_path.name}.",
        )

    if violations:
        for line in violations:
            print(line)
        print()
        print(RATCHET_REMEDY)
        return 1

    stripped_total = sum(sizes["stripped"] for sizes in measured.values())
    mpy_total = sum(sizes["mpy"] for sizes in measured.values())
    print(
        f"OK: {len(measured)} libraries within size budgets "
        f"(stripped {stripped_total} B, mpy {mpy_total} B).",
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Command-line arguments (defaults to ``sys.argv``).
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Check device libraries against committed size budgets.",
    )
    parser.add_argument(
        "--budget-file",
        default=str(BUDGET_FILE),
        help=f"path to the size-budget TOML (default: {BUDGET_FILE.name})",
    )
    args = parser.parse_args(argv)

    prepared = prepared_mpy_cross()
    return _check(
        budget_path=Path(args.budget_file),
        library_dirs=discover_library_dirs(),
        mpy_cross=str(prepared) if prepared is not None else None,
    )


if __name__ == "__main__":
    raise SystemExit(main())
