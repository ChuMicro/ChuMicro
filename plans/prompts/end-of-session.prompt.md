# Prompt: End-of-session checklist

Use this prompt at the end of every working session to ensure nothing is left
uncommitted and planning docs are current.

## Checklist

1. **Check for uncommitted work.**
   ```zsh
   git status --short
   ```
   If there are changes, commit them. Every session must end with a clean tree.

2. **Run preflight.**
   ```zsh
   python scripts/run.py preflight
   ```
   Do not commit code that fails lint, tests, or build.

3. **Check planning docs.** If this session made significant changes (new
   library, new decision, version bump, new task), run the
   [plans-sync prompt](./plans-sync.prompt.md) to update stale docs.

4. **Verify clean tree one last time.**
   ```zsh
   git status --short
   ```
   Should produce no output.

## Why this exists

Agent sessions can end abruptly (context window limits, timeouts, user closing
the session). Uncommitted work is invisible to the next session. Stale planning
docs mislead the next agent. This checklist prevents both failure modes.

