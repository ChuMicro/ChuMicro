#!/usr/bin/env python3
"""Add a voice to the registry (`--create-voice`): generate a persona, then persist it + its preview.

Voices are DATA, not agents — adding one means adding a line to voices.json. Two modes:

  create_voice.py gen "<person name>"      -> draft a one-line persona in the registry's house style
                                              (clean-room claude -p), printed for the human to edit
  create_voice.py add <key> "<persona>"    -> append the (human-approved) persona to voices.json and
                                              generate its pick-menu preview

The interactive flow (orchestrator): gen a draft -> human edits it -> test it on a target the human
supplies (the normal pipeline with --voice <key>, no write-back) -> on accept, `add` to persist. Testing on
a fresh user-supplied target (not a baked fixture) is deliberate: it never goes stale.

Usage: see modes above.
"""
import json
import os
import subprocess
import sys
import tempfile

SKILL = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILL)
from preflight import require_claude  # noqa: E402


def _examples(voices, n=3):
    out = []
    for k in list(voices)[:n]:
        out.append(f'  "{k}": "{voices[k]}"')
    return "\n".join(out)


def gen(name):
    """Draft a persona sentence for <name> in the registry's house style (clean-room)."""
    require_claude()
    voices = json.load(open(os.path.join(SKILL, "voices.json")))["voices"]
    room = tempfile.mkdtemp(prefix="regen-cv-")
    prompt = (
        "Write ONE persona line for a code docstring/comment writer, capturing how " + name + " would write "
        "code comments. Match the EXACT house style of these existing entries (a single sentence, the frame "
        "\"Write the docstrings and comments as <who> would: <one-clause disposition>\", concrete, no "
        "decoration):\n" + _examples(voices) + "\n\n"
        "Hard rules: ONE clause after the colon; a named person or a clear disposition; NO writing rules "
        "baked in (do not mention Args, em-dashes, length, banned words — those live elsewhere). Write ONLY "
        "the persona line (plain text) to ./persona.txt and reply DONE."
    )
    subprocess.run(
        ["claude", "-p", prompt, "--allowedTools", "Read", "Write",
         "--permission-mode", "acceptEdits", "--model", "opus"],
        cwd=room, capture_output=True, text=True,
    )
    p = os.path.join(room, "persona.txt")
    if not os.path.exists(p):
        sys.exit("persona generation produced nothing — try again or write the persona yourself.")
    persona = open(p).read().strip()
    print("=== DRAFT PERSONA ===")
    print(persona)
    print("\n  Show this to the human to edit, then: create_voice.py add <key> \"<final persona>\"")


def add(key, persona):
    vpath = os.path.join(SKILL, "voices.json")
    data = json.load(open(vpath))
    if key in data["voices"]:
        sys.exit(f"voice {key!r} already exists — pick another key or edit voices.json directly.")
    persona = persona.strip()
    if len(persona) < 20:
        sys.exit("persona looks too short — give a full one-line persona sentence.")
    if "would:" not in persona:
        print("  WARNING: persona does not match the 'Write ... as <who> would: ...' house style; storing as-is.")
    data["voices"][key] = persona
    json.dump(data, open(vpath, "w"), indent=2, ensure_ascii=False)
    print(f"=== ADDED voice {key!r} to voices.json ===")
    # generate the pick-menu preview for the new voice (fills only the missing one)
    subprocess.run([sys.executable, os.path.join(SKILL, "gen_voice_previews.py")], check=False)
    print(f"  voice {key!r} is now usable: --voice {key}. Preview cached for the pick menu.")


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "gen":
        gen(sys.argv[2])
    elif len(sys.argv) >= 4 and sys.argv[1] == "add":
        add(sys.argv[2], sys.argv[3])
    else:
        sys.exit('usage: create_voice.py gen "<name>"  |  create_voice.py add <key> "<persona>"')


if __name__ == "__main__":
    main()
