# Prompts

This folder stores useful prompts that help rebuild the workspace context or preserve the history of how the workspace was planned.

These prompts are written for both human contributors and AI agents. They exist because agent sessions lose context between conversations. Without them, each new session would have to re-discover the repo structure, design decisions, and technical patterns from scratch.

Use it only for prompt artifacts that are worth keeping around for future sessions.

Keep prompts small, dated or clearly named, and focused on planning or workspace build-up history.

## Current prompt set

- `workspace-resume.prompt.md` — **start here** for new sessions; quickly rehydrate planning and implementation context
- `workspace-rebuild.prompt.md` — rebuild the current proven workspace shape from a sparse starting point; includes key technical patterns
- `workspace-history.prompt.md` — preserve and extend the workspace build-up timeline, design principles, and rejected approaches
- `workstream-planning.prompt.md` — refresh planning from the current verified workspace state

## When to use which prompt

| Situation | Prompt |
|-----------|--------|
| New session, need to pick up where you left off | `workspace-resume` |
| Context loss mid-session, need to recover | `workspace-resume` → "Context recovery" section |
| Need to understand why the workspace looks this way | `workspace-history` |
| Recreating the workspace from scratch or a sparse clone | `workspace-rebuild` |
| Planning the next slice of work | `workstream-planning` |
