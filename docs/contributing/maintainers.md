# Maintainer Runbook

<img src="../../support/docs/chumicro_tip.png" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

This page is the operational side of ChuMicro's public process: the settings that enforce it, the levers only a maintainer can pull, and what to do when something needs bypassing.  Contributors need nothing here; their view is [CONTRIBUTING.md](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md), [Creating a Pull Request](pull-requests.md), and [Releases and Promotion](releases.md).

<br clear="left">

## The contract

- `main` takes pull requests only: squash merge, review threads resolved, and the required checks green (`preflight`, `compatibility (3.11)`, `(3.12)`, `(3.13)`, `Validate mpy bytecode`).  The ruleset binds the maintainer too.  Bypass exists for emergencies and works only through a pull request, never a direct push.
- Merging a PR that bumps a `VERSION` file publishes an experimental release automatically.  Merging is a release decision, not only a code decision; read `VERSION` diffs with that weight.
- Stable is promoted, never automatic.  Run `promote.yml` from `main` with the experimental tag list, normally in response to a [promotion request issue](https://github.com/ChuMicro/ChuMicro/issues/new?template=stable_promotion.yml).

## Repository settings that carry the process

The workflow files enforce what they can, but these settings live in the GitHub UI and API, where a code review cannot see them drift.  Re-verify after any settings change.

| Setting | Required value | Why |
|---|---|---|
| Ruleset "main branch required rules" | PR required, squash only, the five required checks, every bypass actor in "pull request" mode | Nobody direct-pushes `main`, including admins |
| Ruleset "gh-pages required rules" | All updates blocked; bypass for DeployKey and admins only | Only the docs workflows write gh-pages, over `GH_PAGES_DEPLOY_KEY` |
| Actions: default workflow permissions | Read repository contents | Every workflow declares its own permissions; the read default backstops future files |
| Actions: approval for fork PR workflows | Required for all outside collaborators | A human reads the diff, including workflow edits, before repo CI runs it |
| Actions: "Allow GitHub Actions to create and approve pull requests" | Off | No workflow, AI review included, can ever count toward a merge |
| Environment `pypi` | Deployments from `main` only | The PyPI trusted-publisher exchange is unreachable from any other ref |
| Private vulnerability reporting | Enabled | It is the only reporting channel SECURITY.md offers |

Verification commands, from a checkout with `gh` authenticated:

```bash
gh api repos/ChuMicro/ChuMicro/rulesets --jq '.[] | {name, enforcement}'
gh api repos/ChuMicro/ChuMicro/actions/permissions/workflow
gh api repos/ChuMicro/ChuMicro/actions/permissions/fork-pr-contributor-approval
gh api repos/ChuMicro/ChuMicro/private-vulnerability-reporting
```

## Reviewing an outside pull request

1. **Read the diff before approving the CI run.**  A fork PR that edits `.github/workflows/ci.yml` runs its edited version on its own PR, so a green check on a fork PR means nothing until you have read what CI it actually ran.  Fork runs get a read-only token and no secrets either way; the approval gate is about compute and about not lending the repo's green checkmark to unreviewed automation.
2. Approve the workflow run.  The required checks gate the merge from there.
3. Optionally comment `@claude /review` on the PR for a Claude first pass (next section).
4. If a `VERSION` moved, remember the merge publishes an experimental release.  If one should have moved and did not, `check-version` fails preflight and says so.
5. Squash-merge.  The branch deletes itself, and `release.yml` fires if a `VERSION` changed.

## AI review: design and abuse model

`ai-review.yml` lets Claude review a PR when a maintainer comments `@claude /review` on it.  The threat that shaped the design is the drive-by PR: someone opens a PR that has nothing to do with the project, hoping a public "free review" spends tokens on the maintainer's account.  Here is why that and its neighbors do not work:

- **A PR alone spends nothing.**  The workflow triggers on comments, not on PRs.  Opening a PR, editing it, pushing to it, or commenting on it as an outsider starts no run: the job filters the commenter's repo association, and the action independently verifies the actor has write access before doing anything.  The only lever that spends money is the maintainer's own `@claude /review` comment, one review per comment, 20 minutes maximum per run.
- **The PR is data, not code.**  `issue_comment` workflows run the file from the default branch, so a PR editing `ai-review.yml` cannot change what reviews it.  The PR head sits in `pr-head/` and is only read; no step installs, builds, imports, or tests it, so malicious PR code never executes in the job that holds the API key.
- **Injection has a small blast radius.**  The action strips hidden HTML, invisible characters, and similar smuggling paths from PR content, and the prompt orders Claude to treat PR text as data.  If an injection lands anyway, the job's token can post comments and nothing else: contents are read-only, and the repository setting that would let Actions approve PRs is off.  The worst case is a misleading review comment that a human reads with the same skepticism as any review.
- **The key is scoped and capped.**  `ANTHROPIC_API_KEY` exists only for this workflow.  Set a monthly spend cap on that key in the Anthropic console so a runaway is bounded in dollars, not just minutes.

To retire the whole mechanism, disable the workflow in the Actions tab; the comment command becomes inert.

GitHub's Copilot code review composes with this rather than competing: it is a settings-page toggle, runs entirely on GitHub's side with GitHub's billing, and can take an always-on first pass on every PR, while `@claude /review` stays the deeper pass a maintainer summons deliberately.  With the settings above, neither reviewer can approve a PR or count toward a merge.

## Secrets inventory

| Secret | Reaches | Notes |
|---|---|---|
| `BUNDLE_DEPLOY_KEY`, `EXPERIMENTAL_BUNDLE_DEPLOY_KEY` | The two bundle repos, git-level | Single-repo SSH deploy keys |
| `LIBRARIES_DEPLOY_KEY`, `EXPERIMENTAL_LIBRARIES_DEPLOY_KEY` | The two libraries-channel repos | Single-repo SSH deploy keys |
| `GH_PAGES_DEPLOY_KEY` | This repo's `gh-pages` | The docs workflows push over it, so their token stays read-only |
| `BUNDLE_TOKEN` | GitHub API, bundle-release creation | A PAT.  Keep it fine-grained and scoped to the two bundle repos with Contents and Releases only; a classic `repo` PAT reaches everything the account can |
| `ANTHROPIC_API_KEY` | The AI review workflow | Spend-capped in the Anthropic console |

PyPI itself needs no secret: both publish workflows use trusted publishing (OIDC) through the `pypi` environment.

## Action pinning

Every action in `.github/workflows/` is pinned to a commit SHA with the version in a trailing comment.  Dependabot bumps the SHAs monthly.  Keep it that way: several of these actions hold deploy keys or tag-creation rights, and a moved tag on one of them is a supply-chain compromise of the release fabric.  Do not accept a PR that reverts a SHA pin to a tag.

## Emergencies

- **`main` is broken and the fix cannot pass a required check** (say, the check itself is what broke): open the fix as a PR anyway and use ruleset bypass at merge time.  Bypass works through the PR merge button only; direct pushes stay blocked even for admins.
- **A required check is stuck on infrastructure** (runner outage, cache corruption): re-run the job first.  Bypassing a merge on a red check should be rare enough to feel uncomfortable.
- **A release run half-finished:** every leg is idempotent and the git tag is written last, so re-dispatching the same run with the same inputs finishes what remains.  [Releases and Promotion](releases.md) has the per-failure-mode detail, including first-release PyPI bootstrapping.
- **Settings drift or emergency loosening:** admins can always edit rulesets and Actions policy.  Treat any loosening as temporary, and restore against the table above when the incident closes.
