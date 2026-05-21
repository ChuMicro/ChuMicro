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
    """
    workspace = _resolve_workspace(args)
    quality = load_quality_config(workspace.workspace_yaml)
    quality_flags: list[str] = []
    if quality.coverage_threshold is not None:
        quality_flags.append(f"--cov-fail-under={quality.coverage_threshold}")
    completed = args._env.subprocess_runner(  # noqa: S603 - args fully controlled
        [sys.executable, "-m", "pytest", *quality_flags, *args.pytest_args],
        cwd=workspace.root,
        check=False,
    )
    return completed.returncode


def _cmd_lint(args: argparse.Namespace) -> int:
    """Run ``ruff check`` plus ``chumicro-checks`` across the workspace.

    Picks up the workspace's ``[tool.ruff]`` config from
    ``pyproject.toml`` automatically.  The workspace template ships
    a pre-configured ruff block.  Extra args after ``--`` forward to
    ruff (e.g. ``--fix``, ``--select`` overrides).

    After ruff, runs ``chumicro-checks`` for the workspace-internal
    rules ruff can't express.  Each rule self-scopes (silent
    no-op in repos where its target paths don't exist), so most
    don't fire in a user workspace.  The upstream-derivative-leak
    detector typically does.  ``chumicro-checks`` reads its own
    ``[tool.chumicro-checks]`` config from ``pyproject.toml``.

    No-op (exit 0 with a hint) when either ``ruff`` or
    ``chumicro-checks`` isn't installed, so the command stays
    discoverable in workspaces that haven't pulled the ``[dev]``
    extra yet.

    ``workspace.yml``'s ``quality.lint`` knobs flow through.
    ``enabled = false`` skips the entire phase.  ``tools`` selects
    which tools run (default ``["ruff", "chumicro-checks"]``, drop
    one to disable that tool only).  ``select`` prepends a
    ``--select <comma list>`` flag for ruff.  ``chumicro-checks``
    ignores it (its rule selection is via its own config and CLI flags).
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
                "ruff is not installed in this venv.  Install the dev "
                "extras with:\n"
                "    .venv/bin/pip install -e .[dev]\n"
                "or add ruff to your workspace's pyproject.toml deps.",
            )
            return 0
        quality_flags: list[str] = []
        if quality.lint.select:
            quality_flags.extend(["--select", ",".join(quality.lint.select)])
        ruff_completed = args._env.subprocess_runner(  # noqa: S603 - args fully controlled
            [
                sys.executable, "-m", "ruff", "check",
                *quality_flags, *args.ruff_args, ".",
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
                "chumicro-checks is not installed in this venv.  Install "
                "it (or the dev extras) to run the CHU0NN rules:\n"
                "    .venv/bin/pip install chumicro-checks\n"
                "or add it to your workspace's pyproject.toml dev deps.",
            )
            return 0
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
