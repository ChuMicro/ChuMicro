# Plans

This directory is the long-lived planning area for Chumicro.

## Planning model

Chumicro uses a lightweight planning structure:

- `roadmap.md` for milestone sequencing
- `next-up.md` for the active kanban-style queue
- `workstreams/` for durable bodies of work
- `decisions/` for short decision records that explain why the workspace is shaped a certain way
- `prompts/` for useful prompts that help rebuild the workspace context or preserve build-up history

## Status vocabulary

Use these states consistently in planning documents:

- `proposed`
- `in-progress`
- `blocked`
- `done`
- `deferred`

## Update rules

- Keep documents small and link between them instead of repeating detail.
- Record decisions when tradeoffs matter or when future agents will otherwise have to rediscover context.
- Use `next-up.md` as the working queue; workstreams should stay stable and higher level.
- Prefer milestone language over formal scrum ceremony.

## Review loop

These plans are expected to evolve with direct maintainer feedback.

When a plan is enhanced, review should explicitly answer:

- what is right and should stay
- what is wrong and should change
- what is missing
- what is too detailed or not detailed enough

Future plan updates should preserve open questions instead of silently guessing.

## Current planning set

- `roadmap.md`
- `next-up.md`
- `prompts/`
- `workstreams/workspace-foundation.md`
- `workstreams/timing-library.md`
- `workstreams/ci-release.md`
- `workstreams/device-validation.md`
- `decisions/` (0001–0020)

`prompts/` should contain only durable prompts that help future sessions rebuild workspace context or understand workspace build-up history.
