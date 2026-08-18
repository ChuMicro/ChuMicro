"""Deploy docs and push to gh-pages, retrying on conflict.

Shares the ``documentation-deploy`` concurrency group with
push-triggered experimental deploys.  When a concurrent deploy lands
between fetch and push, retry with the new gh-pages head so mike's
commit lands on top.

Usage::

    python scripts/docs_deploy_retry.py \
        --channel stable \
        --libraries timing \
        [--max-attempts 3] \
        [--retry-delay 10]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import index_now
from repo_layout import ROOT


def _run(command: list[str], cwd: Path = ROOT) -> int:
    """Run a subprocess and return its exit code."""
    result = subprocess.run(command, cwd=cwd, check=False)
    return result.returncode


def _fetch_gh_pages() -> None:
    """Pull the latest gh-pages so mike rebuilds on top of remote state."""
    subprocess.run(
        ["git", "fetch", "origin", "gh-pages:gh-pages", "--force"],
        cwd=ROOT, check=False, capture_output=True,
    )


def deploy_with_retry(
    channel: str,
    libraries: str | None,
    max_attempts: int,
    retry_delay: float,
) -> int:
    """Run ``run.py docs-deploy`` and ``git push`` with retry-on-conflict."""
    deploy_command = [
        sys.executable, "scripts/run.py", "docs-deploy",
        "--channel", channel,
    ]
    if libraries:
        deploy_command.extend(["--libraries", libraries])

    for attempt in range(1, max_attempts + 1):
        print(f"::group::Attempt {attempt} of {max_attempts}")
        _fetch_gh_pages()

        deploy_status = _run(deploy_command)
        if deploy_status != 0:
            print("::endgroup::")
            print(f"::error::docs-deploy failed with exit code {deploy_status}.")
            return deploy_status

        push_status = _run(["git", "push", "origin", "gh-pages"])
        print("::endgroup::")
        if push_status == 0:
            label = libraries or channel
            print(f"✓ {channel.capitalize()} docs deployed ({label}).")
            # The pages are live; tell the engines that read IndexNow
            # rather than waiting for their own crawl schedule.  A
            # failed ping is reported and does not fail the deploy.
            index_now.ping()
            return 0

        if attempt < max_attempts:
            print(f"Push failed (likely concurrent update), retrying in {retry_delay}s...")
            time.sleep(retry_delay)

    print(f"::error::Failed to deploy {channel} docs after {max_attempts} attempts.")
    return 1


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Deploy docs and push to gh-pages with retry-on-conflict.",
    )
    parser.add_argument("--channel", required=True, choices=["experimental", "stable"])
    parser.add_argument("--libraries", default="", help="Comma-separated library filter.")
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--retry-delay", type=float, default=10.0)
    args = parser.parse_args(argv)

    return deploy_with_retry(
        channel=args.channel,
        libraries=args.libraries or None,
        max_attempts=args.max_attempts,
        retry_delay=args.retry_delay,
    )


if __name__ == "__main__":
    raise SystemExit(main())
