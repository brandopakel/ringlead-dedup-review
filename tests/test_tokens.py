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


class TestBrandTypography:
    """The template treats Geist as brand-approved, not as a preference."""

    def test_faces_are_embedded_not_linked(self):
        from ringlead_qa import fonts
        rules = fonts.face_rules()
        assert rules.count("@font-face") == 2
        assert "data:font/woff2;base64," in rules
        assert "http" not in rules, "a linked font breaks the offline guarantee"

    def test_both_stacks_fall_back_to_system_faces(self):
        """A checkout without the binaries must still render something sane."""
        from ringlead_qa import fonts
        assert fonts.SANS.startswith('"Geist"') and "sans-serif" in fonts.SANS
        assert fonts.MONO.startswith('"Geist Mono"') and "monospace" in fonts.MONO

    def test_stylesheet_names_no_font_family_directly(self):
        """Families come from tokens, the same discipline the colours follow."""
        import re
        from ringlead_qa import report
        for decl in re.findall(r"font-family:([^;}]+)", report.STYLES):
            assert "var(--" in decl, f"hard-coded family: {decl.strip()}"


class TestPartialMergeTable:
    """An unchecked record must not be dressed as a merge participant."""

    def _partial_report(self):
        from ringlead_qa.loader import Group, Record
        from ringlead_qa.rules import evaluate
        from ringlead_qa import fields as F, report as R
        cols = [F.GROUP_ID, F.RECORD_ACTION, F.ENTITY_TYPE] + [
            F.LEAD.prefix + lab for labs in F.LEAD.fields.values() for lab in labs
        ]
        schema = F.Schema.build("Lead", cols)

        def rec(role, **vals):
            data = {F.RECORD_ACTION: role, F.GROUP_ID: "g1"}
            data.update({schema.col(k) or k: v for k, v in vals.items()})
            return Record(role, data, schema)

        odd = rec("master", **{F.F_RECORD_ID: "00Q_ODD", F.F_FULL_NAME: "Mana Kawaguchi"})
        a = rec("duplicate", **{F.F_RECORD_ID: "00Q_A", F.F_FULL_NAME: "Watanabe Hikaru"})
        b = rec("duplicate", **{F.F_RECORD_ID: "00Q_B", F.F_FULL_NAME: "Watanabe Hikaru"})
        surv = rec("surviving", **{F.F_RECORD_ID: "00Q_ODD", F.F_FULL_NAME: "Mana Kawaguchi"})
        g = Group(group_id="g1", schema=schema, surviving=surv, master=odd, duplicates=[a, b])
        return R.render([evaluate(g)], source="t.csv", total_rows=4)

    def test_excluded_columns_say_uncheck(self):
        html = self._partial_report()
        assert ">Uncheck<span" in html
        assert "col-excluded" in html

    def test_no_record_is_still_called_master_or_duplicate(self):
        """Those labels describe RingLead's proposal, which is being overridden."""
        html = self._partial_report()
        assert ">Master<span" not in html
        assert ">Duplicate<span" not in html

    def test_the_preview_column_is_relabelled(self):
        """"After merge" would promise an outcome the recommendation prevents."""
        html = self._partial_report()
        assert "As proposed" in html


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
