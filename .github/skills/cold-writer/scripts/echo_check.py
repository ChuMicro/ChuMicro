"""Measure how much of a draft's prose relays its brief word for word.

`echo_check.py --brief brief.md --draft draft.md` counts the draft's prose
sentences that share a run of words with the brief and exits 1 when their share
exceeds `--max-share`. Commands, code, output lines, link targets, headings, and
frontmatter are not prose and never count. The default threshold sits at half
the share measured on a draft the owner rejected for relaying its brief;
recalibrate it from owner-approved pages once those exist.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_RUN = 6
DEFAULT_MAX_SHARE = 0.15
MIN_SENTENCE_WORDS = 6

FENCE = re.compile(r"^\s*(```|~~~)")
HEADING = re.compile(r"^\s*#")
INLINE_CODE = re.compile(r"`[^`]*`")
LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
AUTOLINK = re.compile(r"<https?://[^>]*>|https?://\S+")
LINE_MARKER = re.compile(r"^\s*(?:>\s*|[-*+]\s+|\d+\.\s+)+")
WORD = re.compile(r"[a-z0-9']+")


def prose(text: str) -> str:
    """Return the explanatory prose of a Markdown document, one line per source line.

    Frontmatter, fenced code, headings, inline code, and link targets are removed;
    list and blockquote markers are stripped so their text still counts.
    """
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                lines = lines[index + 1:]
                break
    kept = []
    fenced = False
    for line in lines:
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced or HEADING.match(line):
            continue
        line = LINE_MARKER.sub("", line)
        line = INLINE_CODE.sub(" ", line)
        line = LINK.sub(r"\1", line)
        line = AUTOLINK.sub(" ", line)
        kept.append(line)
    return "\n".join(kept)


def words(text: str) -> list[str]:
    """Return the lowercase word tokens of a text."""
    return WORD.findall(text.lower())


def sentences(text: str) -> list[str]:
    """Split prose into sentences at sentence-ending punctuation and line breaks, keeping those with enough words."""
    pieces = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [piece.strip() for piece in pieces if len(words(piece)) >= MIN_SENTENCE_WORDS]


def longest_shared_run(tokens: list[str], brief_tokens: list[str], minimum: int, grams: dict) -> int:
    """Return the longest run of at least `minimum` consecutive tokens that also appears in the brief, else 0."""
    for length in range(len(tokens), minimum - 1, -1):
        if length not in grams:
            grams[length] = {
                tuple(brief_tokens[start:start + length])
                for start in range(len(brief_tokens) - length + 1)
            }
        if any(tuple(tokens[start:start + length]) in grams[length]
               for start in range(len(tokens) - length + 1)):
            return length
    return 0


def measure(brief: str, draft: str, run: int) -> dict:
    """Return the echoed share of the draft's prose sentences and each echoed sentence with its longest shared run."""
    draft_sentences = sentences(prose(draft))
    if not draft_sentences:
        raise ValueError("draft has no prose sentences; check the draft path and its Markdown")
    brief_tokens = words(prose(brief))
    grams: dict[int, set[tuple[str, ...]]] = {}
    echoes = []
    for sentence in draft_sentences:
        shared = longest_shared_run(words(sentence), brief_tokens, run, grams)
        if shared:
            echoes.append({"words": shared, "sentence": sentence})
    echoes.sort(key=lambda echo: echo["words"], reverse=True)
    return {
        "run": run,
        "sentences": len(draft_sentences),
        "echoed": len(echoes),
        "share": round(len(echoes) / len(draft_sentences), 3),
        "echoes": echoes,
    }


def main(argv: list[str] | None = None) -> int:
    """Print the echo report as JSON and return 0 under the threshold, 1 above it, 2 for unusable input."""
    parser = argparse.ArgumentParser(
        description="Count draft prose sentences that relay the brief. Exit 1 above --max-share, 2 on bad input.",
    )
    parser.add_argument("--brief", required=True, type=Path, help="the reviewed writer brief")
    parser.add_argument("--draft", required=True, type=Path, help="the writer's Markdown draft")
    parser.add_argument("--run", type=int, default=DEFAULT_RUN,
                        help=f"consecutive shared words that make an echo (default {DEFAULT_RUN})")
    parser.add_argument("--max-share", type=float, default=DEFAULT_MAX_SHARE,
                        help=f"largest passing share of echoed prose sentences (default {DEFAULT_MAX_SHARE})")
    arguments = parser.parse_args(argv)
    try:
        if arguments.run < 2:
            raise ValueError("--run must be at least 2")
        if not 0 <= arguments.max_share <= 1:
            raise ValueError("--max-share must be between 0 and 1")
        report = measure(
            arguments.brief.read_text(encoding="utf-8"),
            arguments.draft.read_text(encoding="utf-8"),
            arguments.run,
        )
    except (OSError, ValueError) as error:
        print(f"input error: {error}", file=sys.stderr)
        return 2
    report["max_share"] = arguments.max_share
    report["passed"] = report["share"] <= arguments.max_share
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
