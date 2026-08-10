"""Enforcement for the design token contract.

A token module nobody checks is a style guide, and style guides drift. These tests
are what make `ringlead_qa/tokens.py` binding: a stylesheet cannot reference a token
the contract doesn't define, cannot hard-code a colour, and cannot define a colour
only inside a dark-theme block — the bug that renders one theme's text on the other
theme's background.
"""

import re

import pytest

from ringlead_qa import report, tokens

# `hsl(var(--x))`, `var(--x)`, `hsl(var(--x)/.1)`
TOKEN_REF = re.compile(r"var\((--[a-z0-9-]+)\)")
# Colour literals a stylesheet must not contain: #hex, rgb(), hsl() with raw numbers.
RAW_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
RAW_FUNC = re.compile(r"\b(?:rgb|rgba|hsla)\(")
# hsl( that isn't wrapping a var() -- i.e. a literal channel triplet
RAW_HSL = re.compile(r"hsl\(\s*(?!var\()")


class TestContract:
    def test_light_and_dark_define_the_same_names(self):
        """A token in one theme but not the other renders unstyled in that theme."""
        assert set(tokens.LIGHT) == set(tokens.DARK)

    def test_every_token_has_a_value(self):
        assert all(v.strip() for v in {**tokens.LIGHT, **tokens.DARK}.values())

    def test_palette_values_are_bare_hsl_channels(self):
        """Bare channels are what let `hsl(var(--x)/.1)` derive a tint from a base."""
        for name, value in tokens.LIGHT.items():
            assert not value.startswith(("#", "hsl", "rgb")), f"{name} is not bare channels"
            assert value.count("%") == 2, f"{name} should be 'H S% L%', got {value!r}"


class TestStylesheetObeysTheContract:
    def test_no_undefined_tokens(self):
        """The drift guard: using a token nobody defined fails here, not in a browser."""
        used = set(TOKEN_REF.findall(report.STYLES))
        undefined = {t for t in used if t.lstrip("-") not in tokens.defined_tokens()}
        assert not undefined, f"stylesheet references undefined tokens: {sorted(undefined)}"

    @pytest.mark.parametrize("pattern,label", [
        (RAW_HEX, "hex colour"),
        (RAW_FUNC, "rgb()/rgba()/hsla()"),
        (RAW_HSL, "literal hsl() channels"),
    ])
    def test_no_raw_colours(self, pattern, label):
        """Every colour must come from the contract, so a re-theme is one file."""
        found = pattern.findall(report.STYLES)
        assert not found, f"stylesheet hard-codes {label}: {found[:5]}"

    def test_single_radius_scale(self):
        """One radius, optionally stepped down. A third value is drift."""
        radii = set(re.findall(r"border-radius:\s*([^;}]+)", report.STYLES))
        allowed = {"var(--radius)", "calc(var(--radius) - 2px)", "999px", "50%",
                   "4px", "6px", "2px"}
        assert radii <= allowed, f"unexpected radius values: {sorted(radii - allowed)}"


class TestEmittedCss:
    def test_light_palette_lands_on_bare_root(self):
        """No colour may be defined only inside a media query or [data-theme] block."""
        css = tokens.css_variables()
        bare = css[css.index(":root{"):css.index("}", css.index(":root{"))]
        for name in tokens.LIGHT:
            assert f"--{name}:" in bare, f"{name} is missing from the bare :root block"

    def test_both_dark_selectors_are_emitted(self):
        """Covers the un-stamped 'system' state and an explicit dark toggle."""
        css = tokens.css_variables()
        assert "@media (prefers-color-scheme:dark){:root:not([data-theme=light])" in css
        assert ":root[data-theme=dark]{" in css

    def test_body_paints_an_explicit_background(self):
        """A transparent body borrows the host page's ground and breaks in one theme."""
        body = re.search(r"\bbody\{[^}]*\}", report.STYLES)
        assert body and "background:hsl(var(--background))" in body.group()
