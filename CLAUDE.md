# project memory

## Asking and showing (the surfaces toolkit)

Rich interaction with the human goes through `.claude/surfaces/`: one surface hub per repo
(`python3 -m surfaces.hub`, one server, one browser tab; questions have a lifecycle), the
decision picker, media hand-off on any card, and structured fields including uploads the
human hands back. The `surfaces` skill is the router and the full reference; read it
before building a surface and route by shape, never by habit. `AskUserQuestion` is
hook-gated; an ask that outgrows the widget renders a surface.

The package and its skill are a generated unit shared with the other repos that carry
them. The canonical copy lives upstream, outside this repo, and is synced by
`sync-surfaces`. Fix the canonical, never this copy: the next emit overwrites it. A
fix that starts here is harvested upstream first, then emitted back.

## Docs voice

When writing or editing any prose documentation in this repo (READMEs, guides, contributing pages), follow "Documentation tone" and its "Voice" subsection in docs/contributing/style-guide.md. The short version: no em-dashes, plain words over clever ones, state the project's opinions straight, concrete measured claims only, no staccato over-compression, behavior over mechanics.
