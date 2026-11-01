# Maintainer Runbook

<img src="https://chumicro.com/assets/chumicro-head.png" alt="" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

ChuMicro's public process rests on repository settings, on levers only a maintainer can pull, and on a bypass path for emergencies. A contributor sees the same process through [CONTRIBUTING.md](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md), [Creating a Pull Request](pull-requests.md), and [Releases and Promotion](releases.md).

<br clear="left">

## The contract

- `main` takes squash-merged pull requests only, with review threads resolved and the [required checks](pull-requests.md#ci-checks) green.  The ruleset binds the maintainer too.  Bypass exists for emergencies and works only through a pull request's merge button.
- A merged `VERSION` bump publishes an experimental release, as [What happens on merge](releases.md#what-happens-on-merge) describes, so merging a bump is a release decision.  Read `VERSION` diffs with that weight.
- A maintainer promotes stable by hand: run `promote.yml` from `main` with the experimental tag list, usually in answer to a [promotion request issue](https://github.com/ChuMicro/ChuMicro/issues/new?template=stable_promotion.yml).  [Releases § For maintainers](releases.md#for-maintainers) covers the workflow inputs.

## Repository settings that carry the process

These settings live in the GitHub UI and API, out of a code review's sight, so they can drift unnoticed.  Re-verify them after any settings change.

| Setting | Required value | Why |
|---|---|---|
| Ruleset "main branch required rules" | PR required, squash only, the five required checks, every bypass actor in "pull request" mode | Nobody direct-pushes `main`, including admins |
| Ruleset "gh-pages required rules" | All updates blocked, with bypass for DeployKey and admins only | Only the docs workflows write gh-pages, over `GH_PAGES_DEPLOY_KEY` |
| Actions: default workflow permissions | Read repository contents | Every workflow declares its own permissions, and the read default backstops future files |
| Actions: approval for fork PR workflows | Required for all outside collaborators | A human reads the diff, workflow edits included, before repo CI runs it |
| Actions: "Allow GitHub Actions to create and approve pull requests" | Off | No workflow, AI review included, can ever count toward a merge |
| Environment `pypi` | Deployments from `main` only | The PyPI trusted-publisher exchange is unreachable from any other ref |
| Private vulnerability reporting | Enabled | SECURITY.md offers it as the reporting channel |

These commands read the settings back, from a checkout with `gh` authenticated:

```bash
gh api repos/ChuMicro/ChuMicro/rulesets --jq '.[] | {name, enforcement}'
gh api repos/ChuMicro/ChuMicro/actions/permissions/workflow
gh api repos/ChuMicro/ChuMicro/actions/permissions/fork-pr-contributor-approval
gh api repos/ChuMicro/ChuMicro/private-vulnerability-reporting
```

## Reviewing an outside pull request

1. **Read the diff before approving the CI run.**  A fork pull request that edits `.github/workflows/ci.yml` runs its edited version on itself, so its green check means nothing until a maintainer reads the CI it ran.  Fork runs get a read-only token and no secrets either way.  The approval gate guards compute, and keeps the repository's green checkmark off unreviewed automation.
2. Approve the workflow run.  The required checks gate the merge from there.
3. Optionally comment `@claude /review` for a first pass from Claude, as [AI review](#ai-review-design-and-abuse-model) describes.
4. Check any `VERSION` change, since the merge publishes it.  `check-version` fails preflight when a needed bump is missing.
5. Squash-merge.  The branch deletes itself, and `release.yml` fires when a `VERSION` changed.

## AI review: design and abuse model

`ai-review.yml` lets Claude review a pull request when a maintainer comments `@claude /review` on it.  The design guards against the drive-by pull request: one opened only to make a public "free review" spend tokens on the maintainer's account.

- **A pull request alone spends nothing.**  The workflow triggers on comments, not on pull requests.  Opening a pull request, editing it, pushing to it, or commenting on it as an outsider starts no run: the job filters the commenter's repository association, and the action separately verifies that the actor has write access.  The maintainer's own `@claude /review` comment is the one trigger that spends money: one review per comment, 20 minutes at most per run.
- **The pull request is data, not code.**  `issue_comment` workflows run the file from the default branch, so a pull request editing `ai-review.yml` leaves its own review unchanged.  The pull request's head sits in `pr-head/` and is only read.  No step installs, builds, imports, or tests it, so malicious code in it never executes in the job that holds the API key.
- **Injection has a small blast radius.**  The action strips hidden HTML, invisible characters, and similar smuggling paths from pull request content, and the prompt orders Claude to treat that text as data.  An injection that lands anyway gets a token that can post comments and nothing else: contents are read-only, and the repository setting that would let Actions approve pull requests is off.  The worst case is a misleading review comment, which a human reads with the same skepticism as any review.
- **The key is scoped and capped.**  `ANTHROPIC_API_KEY` exists only for this workflow.  Set a monthly spend cap on that key in the Anthropic console, so a runaway is bounded in dollars as well as minutes.

To retire the whole mechanism, disable the workflow in the Actions tab.  The comment command then does nothing.

GitHub's Copilot code review composes with this one.  It is a settings-page toggle, runs entirely on GitHub's side with GitHub's billing, and can take an always-on first pass on every pull request.  `@claude /review` stays the deeper pass a maintainer summons deliberately.  With the settings above, neither reviewer can approve a pull request or count toward a merge.

## Secrets inventory

| Secret | Reaches | Notes |
|---|---|---|
| `BUNDLE_DEPLOY_KEY`, `EXPERIMENTAL_BUNDLE_DEPLOY_KEY` | The two bundle repos, git-level | Single-repo SSH deploy keys |
| `LIBRARIES_DEPLOY_KEY`, `EXPERIMENTAL_LIBRARIES_DEPLOY_KEY` | The two libraries-channel repos | Single-repo SSH deploy keys |
| `GH_PAGES_DEPLOY_KEY` | This repo's `gh-pages` | The docs workflows push over it, so their token stays read-only |
| `BUNDLE_TOKEN` | GitHub API, bundle-release creation | A PAT.  Keep it fine-grained and scoped to the two bundle repos with Contents and Releases only.  A classic `repo` PAT reaches everything the account can |
| `ANTHROPIC_API_KEY` | The AI review workflow | Spend-capped in the Anthropic console |

PyPI itself needs no secret: both publish workflows use trusted publishing (OIDC) through the `pypi` environment.

## Action pinning

Every action in `.github/workflows/` is pinned to a commit SHA, with the version in a trailing comment.  Dependabot bumps the SHAs monthly.  Several of these actions hold deploy keys or tag-creation rights, and a moved tag on one of them compromises the whole release chain.  Turn down any pull request that reverts a SHA pin to a tag.

## Emergencies

- **`main` is broken and the fix cannot pass a required check**, because the check itself broke, for example: open the fix as a pull request anyway, and use ruleset bypass at merge time.
- **A required check is stuck on infrastructure**, such as a runner outage or cache corruption: re-run the job first.  Bypassing a merge on a red check stays rare enough to feel uncomfortable.
- **A release run half-finished:** every leg is safe to run twice and the git tag is written last, so re-dispatching the same run with the same inputs finishes what remains.  [Releases and Promotion § For maintainers](releases.md#for-maintainers) has the detail for each failure, including first-release PyPI bootstrapping.
- **Settings drift or emergency loosening:** admins can always edit rulesets and Actions policy.  Treat any loosening as temporary, and restore the table above when the incident closes.
