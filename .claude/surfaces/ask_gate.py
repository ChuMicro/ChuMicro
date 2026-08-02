#!/usr/bin/env python3
"""PreToolUse gate: holds every AskUserQuestion call to a wording floor a cold reader can
decide from: context in the question text, a full-sentence description on every option,
no shorthand fragments glued with dashes or arrows. Wired in .claude/settings.json
(hooks → PreToolUse on AskUserQuestion).

Reads the hook event JSON from stdin and exits 0 silently when the ask passes. On a
failure it prints a PreToolUse deny whose reason lists each defect plus the full floor;
Claude Code shows that reason to the asking agent, which rewrites the same ask and
re-fires: the gate is mechanical, the rewrite stays the model's. Quoted spans
("…", “…”, `…`) are exempt from the joiner scan so an ask may quote prose that itself
contains an em-dash. The authoring guidance behind the floor lives in the surfaces skill,
"Wording the ask".
"""
import json
import re
import sys

MIN_QUESTION_CHARACTERS = 80
MIN_DESCRIPTION_WORDS = 8
JOINER_NAMES = {
    "-": "an em-dash",
    " -- ": "' -- '",
    "→": "an arrow",
    "·": "a middot",
}
QUOTED_SPANS = re.compile(r'"[^"\n]*"|“[^”\n]*”|`[^`\n]*`')

FLOOR = (
    "The floor for every ask: the question text opens with one or two plain sentences "
    "naming the concrete thing being decided and what hangs on the choice (at least "
    f"{MIN_QUESTION_CHARACTERS} characters); every option description is a full sentence "
    f"of at least {MIN_DESCRIPTION_WORDS} words saying what picking it does and when it "
    "is the right pick; labels stay short, with the substance in the description; no "
    "em-dash, ' -- ', arrow, or middot gluing fragments outside quoted spans; candidate "
    "text being compared goes in per-option preview fields (single-select only)."
)


def first_joiner(text):
    """The first banned fragment-joiner in text with quoted spans blanked out, or None.
    Blanking the quoted spans first lets an ask quote prose that legitimately carries one."""
    scannable = QUOTED_SPANS.sub(" ", text)
    for token, name in JOINER_NAMES.items():
        if token in scannable:
            return name
    return None


def question_failures(question):
    """Every floor violation in one question dict, as one plain sentence per defect."""
    failures = []
    header = (question.get("header") or "").strip() or "(no header)"
    text = (question.get("question") or "").strip()
    if len(text) < MIN_QUESTION_CHARACTERS:
        failures.append(
            f"[{header}] question text is {len(text)} characters: open with a sentence "
            "or two of context (what is being decided, what hangs on it) before the "
            "question itself"
        )
    joiner = first_joiner(text)
    if joiner:
        failures.append(
            f"[{header}] question text glues fragments with {joiner}: write plain "
            "sentences; quoted spans are exempt"
        )
    multi_select = bool(question.get("multiSelect"))
    for option in question.get("options") or []:
        label = (option.get("label") or "").strip()
        description = (option.get("description") or "").strip()
        word_count = len(description.split())
        if word_count < MIN_DESCRIPTION_WORDS:
            failures.append(
                f"[{header}] option \"{label}\": description is {word_count} word(s): "
                "write one full sentence on what picking it does and when it is the "
                "right pick"
            )
        if description and description.lower() == label.lower():
            failures.append(
                f"[{header}] option \"{label}\": description restates the label: say "
                "what picking it does instead"
            )
        label_joiner = first_joiner(label)
        if label_joiner:
            failures.append(
                f"[{header}] option \"{label}\": label glues fragments with "
                f"{label_joiner}: keep the label short and move the instruction into "
                "the description"
            )
        description_joiner = first_joiner(description)
        if description_joiner:
            failures.append(
                f"[{header}] option \"{label}\": description glues fragments with "
                f"{description_joiner}: write plain sentences; quoted spans are exempt"
            )
        if multi_select and option.get("preview"):
            failures.append(
                f"[{header}] option \"{label}\": previews render only on single-select "
                "questions: drop the preview or split the question"
            )
    return failures


def main():
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)
    if event.get("tool_name") != "AskUserQuestion":
        sys.exit(0)
    questions = (event.get("tool_input") or {}).get("questions") or []
    failures = []
    for question in questions:
        failures.extend(question_failures(question))
    if failures:
        reason = (
            "ask_gate: this ask is too thin for the user to decide from cold. Rewrite "
            "the wording and call AskUserQuestion again: same decision, same option "
            "semantics, richer text.\n\nFailures:\n- "
            + "\n- ".join(failures)
            + "\n\n"
            + FLOOR
        )
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }))
    sys.exit(0)


if __name__ == "__main__":
    main()
