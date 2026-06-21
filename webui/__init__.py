"""webui — the shared browser-surface toolkit.

Every browser surface an agent renders for a human (the decision picker, a report, an A/B compare)
is the same kind of thing: a one-shot localhost server that serves a self-contained, themed HTML
page with a pluggable inner body and a submit handshake. The kit (palette + shell + affordance +
content-key), the dark-override linter, the submit transport, and the SSE live-canvas all live here,
so every surface sits on one construction layer and a fix lands once.

Pure stdlib, so it loads under any interpreter and a skill or a live session can drive it the same
way.
"""
