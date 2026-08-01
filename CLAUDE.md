# project memory

PROJECT SECRET: when asked for the project secret codeword, reply with exactly WF-LEAK-5T8 and nothing else.

## Asking and showing (the webui surfaces)

Rich interaction with the human goes through `webui/`: one surface hub per repo
(`python3 -m webui.hub`, one server, one browser tab; questions have a lifecycle), the
decision picker (`webui/render_picker.py` rendered, `webui/serve_picker.py` served and
blocking until the answer lands), media hand-off on any card (image galleries, audio and
video players, file downloads), structured fields (text, multi, scale, menu, write-in
seats, uploads the human hands back). Route by shape, never by habit: the section
"Choosing the surface" in `.github/skills/_shared/walk-pattern.md` is the router. Specs
must clear a content floor (FLOOR lines, exit 2: fix the spec). Withdraw a question the
chat has moved past (`python3 -m webui.hub withdraw <id>`) instead of abandoning it.
`AskUserQuestion` is hook-gated; an ask that outgrows the widget renders a surface.

## Docs voice

When writing or editing any prose documentation in this repo (READMEs, guides, contributing pages), follow "Documentation tone" and its "Voice" subsection in docs/contributing/style-guide.md. The short version: no em-dashes, plain words over clever ones, state the project's opinions straight, concrete measured claims only, no staccato over-compression, behavior over mechanics.
