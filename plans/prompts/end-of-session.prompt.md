# Prompt: End-of-session checklist

Use this prompt at the end of every working session to ensure nothing is left
uncommitted and planning docs are current.

## Checklist

1. **Run preflight.**
   ```zsh
   python scripts/run.py preflight
   ```
   Do not commit code that fails lint, tests, or build.

2. **Check VERSION bumps.** If this session changed any library under
   `libraries/`, check whether the change affects the published surface area
   (new API, changed behavior, bug fix). If so, verify the library's `VERSION`
   file was bumped with the smallest correct semantic-version increment.

3. **Commit with good messages.** Check for uncommitted work:
   ```zsh
   git status --short
   ```
   If there are changes, commit them. Write commit messages that aid context
   recovery — summarise *what* in the subject, explain *why* in the body when
   non-trivial, and name affected libraries or decisions. See AGENTS.md
   § Contributing for full guidance.

4. **Check planning docs.** If this session made significant changes (new
   library, new decision, version bump, new task), run the
   [plans-sync prompt](./plans-sync.prompt.md) to update stale docs. Even for
   smaller sessions, consider adding a one-line timeline entry to
   [workspace-history.prompt.md](./workspace-history.prompt.md) so the next
   agent can see what happened.

5. **Verify clean tree one last time.**
   ```zsh
   git status --short
   ```
   Should produce no output.

## Why this exists

Agent sessions can end abruptly (context window limits, timeouts, user closing
the session). Uncommitted work is invisible to the next session. Stale planning
docs mislead the next agent. This checklist prevents both failure modes.

