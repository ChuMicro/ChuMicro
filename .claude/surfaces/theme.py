"""One light/dark theming contract for every surfaces surface.

THEME_KEY is the single localStorage namespace every page reads and writes its light/dark choice
under, so a human who toggles dark on one surface still lands in dark on the next one the agent hands
them. assert_full_dark_override is the half-theme guard: every color custom property a page defines
for light on :root must be re-defined under :root[data-theme=dark], or that page renders light text
on a light background in dark mode. page() (kit.py) runs it on the HTML it is about to emit and
raises instead of shipping the broken page.

Pure stdlib: a regex pass over the emitted CSS. A non-color custom property such as --pagew:920px
is ignored; only color-valued properties must carry a dark override.
"""
from __future__ import annotations

import re

# The localStorage key every surfaces surface persists its light/dark choice under. One key means the
# choice follows the human across surfaces; per-surface keys would leave a dark toggle on one page
# invisible to the next.
THEME_KEY = "chumicro:theme"

_LIGHT_ROOT = re.compile(r":root\s*\{([^}]*)\}")                       # plain :root{...} (light)
_DARK_ROOT = re.compile(r":root\[data-theme=dark\]\s*\{([^}]*)\}")     # :root[data-theme=dark]{...}
_VAR = re.compile(r"(--[\w-]+)\s*:\s*([^;]+)")
_COLOR = re.compile(r"#[0-9a-fA-F]{3,8}|rgba?\(|hsla?\(|color-mix\(", re.I)
_BAD_MEDIA = re.compile(r"@media[^{]*prefers-color-scheme")


class ThemeContractError(ValueError):
    """The dark-override theming contract is violated, so the page would render a half-theme."""


def _vars(css, pattern):
    """{--name: value} for every custom property under every block matching `pattern`."""
    out = {}
    for body in pattern.findall(css):
        for name, value in _VAR.findall(body):
            out[name] = value.strip()
    return out


def theme_problems(css):
    """Return human-readable dark-override violations in `css` (empty list means clean). Pure."""
    light = _vars(css, _LIGHT_ROOT)
    color_light = {name: value for name, value in light.items() if _COLOR.search(value)}
    if not color_light:
        return []                                  # no themeable color vars: nothing to enforce
    problems = []
    dark = _vars(css, _DARK_ROOT)
    if not dark:
        problems.append("defines color custom properties on :root but has no "
                        ":root[data-theme=dark] override block (the half-theme trap)")
    else:
        missing = sorted(name for name in color_light if name not in dark)
        if missing:
            problems.append("color vars defined for light but not overridden under "
                            f":root[data-theme=dark]: {', '.join(missing)}")
    if _BAD_MEDIA.search(css):
        problems.append("an @media(prefers-color-scheme ...) block overrides theming; drive every "
                        "color through data-theme so the toggle and the saved choice always win")
    return problems


def assert_full_dark_override(css, *, label="page"):
    """Raise ThemeContractError when `css` (or a full HTML page) violates the dark-override
    contract. Returns the sorted color-var names it verified on success."""
    problems = theme_problems(css)
    if problems:
        raise ThemeContractError(f"{label}: " + "; ".join(problems))
    return sorted(name for name, value in _vars(css, _LIGHT_ROOT).items() if _COLOR.search(value))
