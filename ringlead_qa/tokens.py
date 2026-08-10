"""The design token contract.

Every colour, radius and type size the report renders comes from here. Nothing
downstream is allowed to invent a value: stylesheets reference tokens by name
(``hsl(var(--muted-foreground))``) and never write a literal colour.

This exists because a stylesheet assembled ad-hoc drifts -- a seventh grey appears,
a card picks up a radius nothing else uses, and the page stops reading as one system.
``tests/test_tokens.py`` enforces the contract mechanically: every token a stylesheet
references must be defined here, LIGHT and DARK must define exactly the same names,
and stylesheets must not contain raw colour literals.

Palette values are unquoted HSL channels so they compose with alpha at the point of
use -- ``hsl(var(--destructive)/.1)`` gives a tinted background from the same token as
the solid colour, which is what keeps tints in step with their base.
"""

from __future__ import annotations

# --- Neutral + semantic roles -------------------------------------------------
# Structural roles are named for their job, not their colour, so a re-theme is a
# change here and nowhere else. The palette is shadcn/ui's zinc scale.
LIGHT: dict[str, str] = {
    # surfaces and text
    "background": "0 0% 100%",
    "foreground": "240 10% 3.9%",
    "card": "0 0% 100%",
    "muted": "240 4.8% 95.9%",
    "muted-foreground": "240 3.8% 46.1%",
    # lines and controls
    "border": "240 5.9% 90%",
    "input": "240 5.9% 90%",
    "ring": "240 5.9% 10%",
    "primary": "240 5.9% 10%",
    "primary-foreground": "0 0% 98%",
    "accent": "240 4.8% 95.9%",
    "accent-foreground": "240 5.9% 10%",
    # status. Separate from the accent hue on purpose: severity must never be
    # confused with "this is interactive".
    "destructive": "0 72% 51%",
    "warning": "35 92% 40%",
    "success": "142 71% 33%",
    "info": "221 83% 53%",
    # "do not merge" -- a distinct action from "fix a value", so a distinct hue
    "skip": "271 76% 45%",
    # domain colours -- RingLead's own language for a merge outcome
    "survive-bg": "142 60% 94%",
    "lost-bg": "349 90% 96%",
    # Text drawn on top of a solid status fill. It flips between themes rather than
    # staying white: the dark palette lifts the status hues, and white on a lifted
    # green falls below readable contrast.
    "on-status": "0 0% 100%",
}

DARK: dict[str, str] = {
    "background": "240 10% 3.9%",
    "foreground": "0 0% 98%",
    "card": "240 10% 5.5%",
    "muted": "240 3.7% 15.9%",
    "muted-foreground": "240 5% 64.9%",
    "border": "240 3.7% 17%",
    "input": "240 3.7% 17%",
    "ring": "240 4.9% 83.9%",
    "primary": "0 0% 98%",
    "primary-foreground": "240 5.9% 10%",
    "accent": "240 3.7% 15.9%",
    "accent-foreground": "0 0% 98%",
    # Status hues lift in darkness rather than inverting -- the same colour at the
    # same lightness reads muddy on a dark ground.
    "destructive": "0 72% 62%",
    "warning": "35 92% 60%",
    "success": "142 65% 50%",
    "info": "217 91% 68%",
    "skip": "271 85% 74%",
    "survive-bg": "142 45% 12%",
    "lost-bg": "349 60% 14%",
    "on-status": "240 10% 3.9%",
}

# --- Scales -------------------------------------------------------------------
# One radius, one spacing rhythm, one type ramp. Values outside these are the drift
# the contract exists to prevent.
SCALE: dict[str, str] = {
    "radius": "0.5rem",
}

#: Font stacks by role. No webfonts -- the report must render offline from disk.
FONTS = {
    "sans": 'ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif',
    "mono": "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace",
}

#: Type ramp, in px, for reference when editing stylesheets.
TYPE_SCALE = {"xs": 10, "sm": 11, "base": 12, "md": 13, "lg": 14, "xl": 20, "display": 26}


def css_variables() -> str:
    """Emit the token block: light on bare :root, dark for both theme states.

    Three states matter, not two. An explicit choice stamps ``data-theme`` on the
    root; the default "system" setting stamps nothing, so an un-stamped document with
    a dark OS is resolved only by ``prefers-color-scheme``. Defining the full light
    palette on bare ``:root`` and overriding tokens in both dark selectors covers all
    three -- and means no colour is ever defined *only* inside a conditional block,
    which is the classic unreadable-page bug.
    """
    def block(palette: dict[str, str], extra: dict[str, str] | None = None) -> str:
        rows = [f"  --{name}:{value};" for name, value in palette.items()]
        rows += [f"  --{k}:{v};" for k, v in (extra or {}).items()]
        return "\n".join(rows)

    return (
        ":root{\n" + block(LIGHT, SCALE) + "\n}\n"
        "@media (prefers-color-scheme:dark){:root:not([data-theme=light]){\n"
        + block(DARK) + "\n}}\n"
        ":root[data-theme=dark]{\n" + block(DARK) + "\n}\n"
    )


def defined_tokens() -> set[str]:
    """Every token name a stylesheet is allowed to reference."""
    return set(LIGHT) | set(SCALE)
