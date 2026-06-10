#!/usr/bin/env python3
"""Load a voice's real-text excerpt for writer-prompt injection: excerpt prose only, never the header.

`voice_samples/<key>.md` holds a short sample of real text by the person a voice was drawn from. Each
file opens with attribution bullets (person, source, register, rights) that must stay OUT of prompts —
the registry's personas are deliberately name-free — so `load_voice_sample` returns only the text under
the ``## Excerpt`` headings. A missing file or empty excerpt returns ``""``, which the writer template
treats as sample-off.
"""
import os
import re

VOICES_DIR = os.path.dirname(os.path.abspath(__file__))


def load_voice_sample(voice_key):
    """Return the excerpt text from voice_samples/<voice_key>.md, or "" when there is none."""
    path = os.path.join(VOICES_DIR, "voice_samples", f"{voice_key}.md")
    if not os.path.exists(path):
        return ""
    kept = []
    in_excerpt = False
    for line in open(path, encoding="utf-8"):
        if line.startswith("## "):
            in_excerpt = line[3:].strip().lower().startswith("excerpt")
            continue
        if in_excerpt:
            kept.append(line.rstrip("\n"))
    # a skipped "## Excerpt 2" heading leaves its surrounding blank lines behind; collapse the stack
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


if __name__ == "__main__":
    import sys

    print(load_voice_sample(sys.argv[1]))
