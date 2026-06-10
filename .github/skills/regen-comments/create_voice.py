#!/usr/bin/env python3
"""Add a voice to the registry (`--create-voice`): persona + real-text sample check + preview.

Voices are DATA, not agents — adding one means a voices.json entry plus (normally) a real-text sample
file. Two modes:

  create_voice.py gen "<person or disposition>"  -> draft a one-sentence descriptive persona in the
                                                    registry's house style (clean-room claude -p),
                                                    printed for the human to edit
  create_voice.py add <key> "<persona>"          -> append the (human-approved) persona to voices.json,
                                                    check voice_samples/<key>.md, and generate the
                                                    pick-menu preview

House style (validated on real code; voices.json's _comment carries the rationale): one descriptive
sentence in the form 'A [traits/role] who ...' — qualities and dispositions only, NO person's proper
name, NO 'you are' / 'adopt' / imperative framing, NO writing-mechanics rules (those live in the writer
discipline, not the persona). The draft can come from `gen` or from any external drafting tool the human
prefers — `add` validates form, not authorship.

The interactive flow (orchestrator; full steps in SKILL.md 'Creating a voice'): draft -> human edits ->
source a real-text sample into voice_samples/<key>.md -> test on a target the human supplies (the normal
pipeline with --voice <key>, no write-back) -> on accept, `add` to persist. Testing on a fresh
user-supplied target (not a baked fixture) is deliberate: it never goes stale.

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
from voice_sample import load_voice_sample  # noqa: E402


def _examples(voices, n=3):
    out = []
    for key, persona in voices.items():
        if persona.strip():
            out.append(f'  "{key}": "{persona}"')
        if len(out) == n:
            break
    return "\n".join(out)


def gen(name):
    """Draft a persona sentence for <name> in the registry's house style (clean-room)."""
    require_claude()
    voices = json.load(open(os.path.join(SKILL, "voices.json")))["voices"]
    room = tempfile.mkdtemp(prefix="regen-cv-")
    prompt = (
        "Write ONE persona sentence for a code docstring/comment writer, capturing how " + name + " would "
        "write — WITHOUT naming them. Match the EXACT house style of these existing entries: a single "
        "descriptive sentence in the form 'A [traits/role] who ...', qualities and dispositions only:\n"
        + _examples(voices) + "\n\n"
        "Hard rules: ONE sentence starting 'A' or 'An'; NO proper names anywhere in it; NO 'you are' / "
        "'adopt' / 'write as' / imperative framing; NO writing-mechanics rules (sentence length, "
        "punctuation, em-dashes, format — those live elsewhere). Write ONLY the persona sentence (plain "
        "text) to ./persona.txt and reply DONE."
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
    print("\n  Show this to the human to edit (drafts from other tools are equally fine), then: "
          "create_voice.py add <key> \"<final persona>\"")


def add(key, persona):
    vpath = os.path.join(SKILL, "voices.json")
    data = json.load(open(vpath))
    if key in data["voices"]:
        sys.exit(f"voice {key!r} already exists — pick another key or edit voices.json directly.")
    persona = persona.strip()
    if len(persona) < 20:
        sys.exit("persona looks too short — give a full one-sentence descriptive persona.")
    lowered = persona.lower()
    if lowered.startswith(("you are", "adopt", "write")):
        print("  WARNING: persona uses an imperative or second-person frame; the validated house style is "
              "a descriptive 'A [traits/role] who ...' sentence (voices.json _comment). Storing as-is.")
    elif not lowered.startswith(("a ", "an ")):
        print("  WARNING: persona does not match the descriptive 'A [traits/role] who ...' house style; "
              "storing as-is.")
    data["voices"][key] = persona
    json.dump(data, open(vpath, "w"), indent=2, ensure_ascii=False)
    print(f"=== ADDED voice {key!r} to voices.json ===")
    sample_path = os.path.join(SKILL, "voice_samples", f"{key}.md")
    if not os.path.exists(sample_path):
        print(f"  NOTE: no voice_samples/{key}.md — the voice runs persona-only until a sample exists. "
              "Sourcing rules: voice_samples/README.md.")
    elif not load_voice_sample(key):
        print(f"  WARNING: voice_samples/{key}.md has no prose under an '## Excerpt' heading — the voice "
              "runs persona-only until that is fixed.")
    else:
        print(f"  voice sample found: voice_samples/{key}.md (excerpt loads clean).")
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
