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
# change here and nowhere else. The palette is MinIO's, sampled from the Marketing
# Field Dictionary: brand red #CF163D, the deep plum ground #100A30 behind the title
# slide, and the violet #5454E4 from its gradient. shadcn/ui's structure is kept;
# only the hues are ours.
LIGHT: dict[str, str] = {
    # surfaces and text. The plum bias in the neutrals is lifted from the deck's
    # ground (#100A30) so greys read as chosen rather than defaulted.
    "background": "0 0% 100%",
    "foreground": "250 24% 10%",
    "card": "0 0% 100%",
    "muted": "250 20% 96%",
    "muted-foreground": "250 10% 42%",
    # lines and controls
    "border": "250 16% 90%",
    "input": "250 16% 88%",
    "ring": "240 73% 58%",
    "primary": "250 24% 12%",
    "primary-foreground": "0 0% 100%",
    "accent": "250 20% 95%",
    "accent-foreground": "250 24% 12%",
    # status. Brand red carries "needs a fix" because attention is what it is for;
    # the interactive accent is the brand violet, so severity never reads as chrome.
    "destructive": "347 81% 45%",
    "warning": "35 92% 38%",
    "success": "142 71% 33%",
    "info": "240 73% 58%",
    "skip": "315 58% 44%",
    # domain colours -- RingLead's own language for a merge outcome
    "survive-bg": "142 55% 94%",
    "lost-bg": "347 85% 96%",
    # Text on a solid status fill; flips by theme so contrast holds on both.
    "on-status": "0 0% 100%",
}

DARK: dict[str, str] = {
    # The deck's title ground, desaturated enough to read a 460-row table against.
    "background": "250 42% 8%",
    "foreground": "250 20% 96%",
    "card": "250 34% 12%",
    "muted": "250 26% 17%",
    "muted-foreground": "250 12% 66%",
    "border": "250 24% 20%",
    "input": "250 24% 22%",
    "ring": "240 85% 74%",
    "primary": "250 20% 96%",
    "primary-foreground": "250 24% 12%",
    "accent": "250 26% 18%",
    "accent-foreground": "250 20% 96%",
    # Status hues lift on a dark ground rather than inverting.
    "destructive": "347 85% 66%",
    "warning": "35 92% 62%",
    "success": "152 62% 50%",
    "info": "240 85% 74%",
    "skip": "315 70% 68%",
    "survive-bg": "152 45% 13%",
    "lost-bg": "347 50% 16%",
    "on-status": "250 24% 10%",
}

# --- Scales -------------------------------------------------------------------
# One radius, one spacing rhythm, one type ramp. Values outside these are the drift
# the contract exists to prevent.
SCALE: dict[str, str] = {
    "radius": "0.5rem",
}

#: Type stacks, exposed as tokens so the stylesheet never names a family directly.
#: The faces themselves are embedded by `fonts.py`; these are the fallbacks around
#: them, and they keep the report readable if the assets are ever missing.
FONTS = {
    "sans": None,   # filled from fonts.SANS at emit time
    "mono": None,   # filled from fonts.MONO at emit time
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
    from . import fonts  # local import: tokens stays importable without the assets

    type_tokens = {"sans": fonts.SANS, "mono": fonts.MONO}

    def block(palette: dict[str, str], extra: dict[str, str] | None = None) -> str:
        rows = [f"  --{name}:{value};" for name, value in palette.items()]
        rows += [f"  --{k}:{v};" for k, v in (extra or {}).items()]
        return "\n".join(rows)

    return (
        ":root{\n" + block(LIGHT, {**SCALE, **type_tokens}) + "\n}\n"
        "@media (prefers-color-scheme:dark){:root:not([data-theme=light]){\n"
        + block(DARK) + "\n}}\n"
        ":root[data-theme=dark]{\n" + block(DARK) + "\n}\n"
    )


def defined_tokens() -> set[str]:
    """Every token name a stylesheet is allowed to reference."""
    return set(LIGHT) | set(SCALE) | set(FONTS)
