"""``test`` / ``lint`` / ``preflight`` subcommands.

Workspace-side gates: pytest with workspace.yml's coverage threshold,
ruff + chumicro-checks with the [quality.lint] knobs, and a preflight
that composes both.
"""

from __future__ import annotations

import argparse
import sys

from chumicro_workspace.cli._common import (
    _add_workspace_arg,
    _resolve_workspace,
)
from chumicro_workspace.quality import load_quality_config

# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _cmd_test(args: argparse.Namespace) -> int:
    """Run the workspace's pytest suite.

    Shells out to ``pytest`` so users get the standard pytest UX
    (``-k``, ``-x``, ``-v``, etc.) without re-implementing argument
    forwarding.  Extra args after ``--`` are passed through verbatim.

    When ``workspace.yml``'s ``quality.coverage_threshold`` is set,
    prepend ``--cov-fail-under=<n>`` so the workspace-level gate
    kicks in.  User passthrough args (after ``--``) win over the
    workspace default, since pytest takes the last occurrence.

    Fails loudly (nonzero, with a ``python3 run.py setup`` pointer)
    when pytest itself is missing rather than shelling out to a raw
    "No module named pytest" traceback: a workspace that never ran
    ``setup``'s ``[dev]`` install has no test runner to reach.
    """
    workspace = _resolve_workspace(args)
    try:
        import pytest  # noqa: F401, PLC0415 - availability probe
    except ImportError:
        print(
            "test: pytest is not installed in this venv.  Run "
            "`python3 run.py setup` to install the workspace's [dev] "
            "extra (pytest, pytest-cov, ruff, chumicro-checks).",
            file=sys.stderr,
        )
        return 1
    quality = load_quality_config(workspace.workspace_yaml)
    quality_flags: list[str] = []
    if quality.coverage_threshold is not None:
        quality_flags.append(f"--cov-fail-under={quality.coverage_threshold}")
    # argparse.REMAINDER keeps the `--` separator the help tells users
    # to type, and pytest reads everything after a literal `--` as
    # file or directory paths, so a forwarded separator makes every
    # flag behind it a "file or directory not found" error.  Strip it.
    pytest_args = args.pytest_args
    if pytest_args and pytest_args[0] == "--":
        pytest_args = pytest_args[1:]
    completed = args._env.subprocess_runner(  # noqa: S603 - args fully controlled
        [sys.executable, "-m", "pytest", *quality_flags, *pytest_args],
        cwd=workspace.root,
        check=False,
    )
    return completed.returncode


def _cmd_lint(args: argparse.Namespace) -> int:
    """Run ``ruff check`` plus ``chumicro-checks`` across the workspace.

    Each tool reads its own config from ``pyproject.toml``
    (``[tool.ruff]`` and ``[tool.chumicro-checks]``).  Extra args
    after ``--`` forward to ruff.  Either tool missing from the venv
    fails loudly (nonzero, with a ``python3 run.py setup`` pointer)
    rather than green-washing: a lint that lints nothing must not
    report success on a workspace that never installed the ``[dev]``
    extra.

    ``workspace.yml``'s ``quality.lint`` knobs flow through.
    ``enabled = false`` skips the phase.  ``tools`` selects which
    tools run.  ``select`` prepends a ``--select <comma list>`` flag
    to ruff and is ignored by chumicro-checks.
    """
    workspace = _resolve_workspace(args)
    quality = load_quality_config(workspace.workspace_yaml)
    if not quality.lint.enabled:
        print(
            "lint: disabled in workspace.yml ([quality.lint] enabled = false).",
        )
        return 0
    if not quality.lint.tools:
        print(
            "lint: no tools selected in workspace.yml ([quality.lint] tools = []).",
        )
        return 0
    if "ruff" in quality.lint.tools:
        try:
            import ruff  # noqa: F401, PLC0415 - availability probe
        except ImportError:
            print(
                "lint: ruff is not installed in this venv.  Run "
                "`python3 run.py setup` to install the workspace's [dev] "
                "extra (ruff, chumicro-checks, pytest).",
                file=sys.stderr,
            )
            return 1
        quality_flags: list[str] = []
        if quality.lint.select:
            quality_flags.extend(["--select", ",".join(quality.lint.select)])
        # argparse.REMAINDER keeps the `--` the help tells users to type,
        # and ruff reads everything after its OWN `--` as file paths — so
        # forwarding the separator turned `lint -- --fix` into a hunt for a
        # file named `--fix` (a bogus E902 on top of the real findings),
        # which meant the documented passthrough worked for no flag at all.
        ruff_args = args.ruff_args
        if ruff_args and ruff_args[0] == "--":
            ruff_args = ruff_args[1:]
        ruff_completed = args._env.subprocess_runner(  # noqa: S603 - args fully controlled
            [
                sys.executable, "-m", "ruff", "check",
                *quality_flags, *ruff_args, ".",
            ],
            cwd=workspace.root,
            check=False,
        )
        if ruff_completed.returncode != 0:
            return ruff_completed.returncode
    if "chumicro-checks" in quality.lint.tools:
        try:
            import chumicro_checks  # noqa: F401, PLC0415 - availability probe
        except ImportError:
            print(
                "lint: chumicro-checks is not installed in this venv.  Run "
                "`python3 run.py setup` to install the workspace's [dev] "
                "extra (ruff, chumicro-checks, pytest).",
                file=sys.stderr,
            )
            return 1
        checks_completed = args._env.subprocess_runner(  # noqa: S603 - args fully controlled
            [sys.executable, "-m", "chumicro_checks", "--root", str(workspace.root)],
            cwd=workspace.root,
            check=False,
        )
        if checks_completed.returncode != 0:
            return checks_completed.returncode
    return 0


def _cmd_preflight(args: argparse.Namespace) -> int:
    """Run lint + tests as a single sanity gate.

    Runs :func:`_cmd_lint` then :func:`_cmd_test` against the same
    workspace with no extra args, picking up the ``quality:`` knobs
    from ``workspace.yml`` (``lint.enabled`` / ``lint.select`` /
    ``coverage_threshold``).  Workspaces without CI use this as the
    pre-push sanity gate.

    Short-circuits on the first failing step so a lint failure
    doesn't cost a test run.  Both steps respect their disable
    knobs.  ``lint.enabled = false`` skips lint silently.  No
    equivalent disable exists for tests today.
    """
    workspace = _resolve_workspace(args)
    print(f"preflight: {workspace.root}")

    print("\npreflight: --- lint ---")
    lint_args = argparse.Namespace(
        workspace_dir=args.workspace_dir,
        ruff_args=[],
        _env=args._env,
    )
    lint_exit = _cmd_lint(lint_args)
    if lint_exit != 0:
        print(f"\npreflight: lint failed (exit {lint_exit})")
        return lint_exit

    print("\npreflight: --- test ---")
    test_args = argparse.Namespace(
        workspace_dir=args.workspace_dir,
        pytest_args=[],
        _env=args._env,
    )
    test_exit = _cmd_test(test_args)
    if test_exit != 0:
        print(f"\npreflight: tests failed (exit {test_exit})")
        return test_exit

    print("\npreflight: lint + tests both passed.")
    return 0


# ---------------------------------------------------------------------------
# Parser wiring
# ---------------------------------------------------------------------------


def _add_quality_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Register ``test`` / ``lint`` / ``preflight``."""
    test_parser = subparsers.add_parser(
        "test",
        help="Run pytest in the workspace root.  Extra args pass through.",
    )
    _add_workspace_arg(test_parser)
    test_parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Args forwarded verbatim to pytest (place after `--`).",
    )
    test_parser.set_defaults(func=_cmd_test)

    lint_parser = subparsers.add_parser(
        "lint",
        help="Run `ruff check` across the workspace.  Extra args pass through.",
    )
    _add_workspace_arg(lint_parser)
    lint_parser.add_argument(
        "ruff_args",
        nargs=argparse.REMAINDER,
        help="Args forwarded verbatim to ruff (place after `--`).",
    )
    lint_parser.set_defaults(func=_cmd_lint)

    preflight_parser = subparsers.add_parser(
        "preflight",
        help=(
            "Run lint + tests as a single sanity gate (the same shape "
            "chumicro itself uses, scaled down for workspaces without "
            "CI).  Respects workspace.yml's `quality:` knobs."
        ),
    )
    _add_workspace_arg(preflight_parser)
    preflight_parser.set_defaults(func=_cmd_preflight)
