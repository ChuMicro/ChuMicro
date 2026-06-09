#!/usr/bin/env python3
"""regen-comments — genre detection.

A file's GENRE selects a triage aim and a writer shape; it is orthogonal to ``--voice``. The four genres:

  code             production / library code   -> trap triage + behavior-and-contract docstrings (the default)
  test             unit tests                  -> per-test CLAIM docstrings, no Args/Returns, no body
  functional_test  end-to-end / on-device      -> same, at scenario altitude
  example          tutorial scripts            -> dense near-line annotation (what each line does + why)

Detection is from the repo's path convention (functional_tests/, tests/ or test_*.py, examples/), defaulting
to code. The orchestrator states the detected genre at the gate; the human overrides with ``--kind <genre>``.

Usage: genre.py detect <path>   # prints the detected genre
"""
import os
import sys

GENRES = ("code", "test", "functional_test", "example")


def detect_genre(path):
    """Return the genre for a target path from the repo's directory / filename conventions."""
    parts = path.replace(os.sep, "/").split("/")
    base = parts[-1]
    # functional_tests/ is checked before tests/ so a nested functional test never reads as a unit test
    if "functional_tests" in parts or "functional_test" in parts:
        return "functional_test"
    if "tests" in parts or base.startswith("test_") or base.endswith("_test.py"):
        return "test"
    if "examples" in parts or base.startswith("example_") or base.endswith("_example.py"):
        return "example"
    return "code"


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "detect":
        print(detect_genre(sys.argv[2]))
    else:
        sys.exit("usage: genre.py detect <path>")


if __name__ == "__main__":
    main()
