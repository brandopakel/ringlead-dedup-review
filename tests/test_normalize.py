"""Tests for the comparison primitives.

Every "do these two records agree?" decision in the tool runs through normalize, so a
regression here silently changes which groups get auto-approved. The cases below are
taken from the real export rather than invented.
"""

import pytest

from ringlead_qa import normalize as N


class TestLinkedIn:
    @pytest.mark.parametrize("raw", [
        "https://www.linkedin.com/in/jeff-goedert-727173305/",
        "http://linkedin.com/in/jeff-goedert-727173305",
        "www.linkedin.com/in/jeff-goedert-727173305/",
        "https://uk.linkedin.com/in/jeff-goedert-727173305?trk=profile",
    ])
    def test_url_variants_collapse_to_one_slug(self, raw):
        assert N.linkedin(raw) == "jeff-goedert-727173305"

    def test_distinct_profiles_stay_distinct(self):
        assert N.linkedin("linkedin.com/in/waltersun") != N.linkedin("linkedin.com/in/walter-sun-2")

    def test_blank(self):
        assert N.linkedin("") == ""


class TestPhone:
    def test_formatting_ignored(self):
        assert N.phone_digits("(612) 304-6073") == N.phone_digits("6123046073")

    def test_country_code_ignored(self):
        assert N.phone_digits("+1 612-304-6073") == N.phone_digits("612.304.6073")

    def test_too_short_is_unusable(self):
        # A 4-digit extension must not be treated as a matching identifier.
        assert N.phone_digits("x4821") == ""


class TestCompanyDomainMatching:
    @pytest.mark.parametrize("company,domain", [
        ("Intuit", "intuit.com"),
        ("DRW Holdings", "drw.com"),            # truncation
        ("DRW Holdings", "drwholdings.com"),    # concatenation
        ("Sidley Austin", "sidley.com"),
        ("Capital One", "capitalone.com"),
        ("Microchip Technology", "microchip.com"),
        ("Bank of Oklahoma", "bankofoklahoma.com"),
        ("KeyShot", "keyshot.com"),
        ("Advarra", "advarra.com"),
    ])
    def test_matches(self, company, domain):
        assert N.company_matches_domain(company, domain)

    @pytest.mark.parametrize("company,domain", [
        ("Intuit", "apple.com"),
        ("Advarra", "veeva.com"),
        ("Capital One", "barclays.com"),
        ("Amgen", "t-mobile.com"),
        ("Sidley Austin", "gmail.com"),
        ("Microchip Technology", "microsemi.com"),  # acquired brand, still a former employer
    ])
    def test_non_matches(self, company, domain):
        assert not N.company_matches_domain(company, domain)

    def test_stopwords_do_not_create_false_matches(self):
        # "Technologies" is shared by thousands of companies and must not link them.
        assert not N.company_matches_domain("Acme Technologies", "globex-technologies.com")

    def test_blank_inputs(self):
        assert not N.company_matches_domain("", "intuit.com")
        assert not N.company_matches_domain("Intuit", "")


class TestEmail:
    def test_domain_and_localpart(self):
        assert N.email_domain("Sangjin_Lee@Intuit.com") == "intuit.com"
        assert N.email_localpart("Sangjin_Lee@Intuit.com") == "sangjin_lee"

    def test_free_providers(self):
        assert N.is_free_email("rezafmk@gmail.com")
        assert not N.is_free_email("reza.mokhtari@cerebras.net")

    def test_role_addresses(self):
        assert N.is_generic_email("info@acme.com")
        assert not N.is_generic_email("jeff.murr@genworth.com")

    def test_garbage_is_not_an_email(self):
        assert N.email("not an address") == ""
        assert N.email_domain("n/a") == ""


class TestNames:
    def test_ordering_and_punctuation_ignored(self):
        assert N.person_name("Dave, Bhavin") == N.person_name("dave bhavin")

    def test_different_people_differ(self):
        assert N.person_name("Chris Shifflett") != N.person_name("Christopher Shifflett")


class TestTitles:
    @pytest.mark.parametrize("bad", ["", "Other", "n/a", "UNKNOWN", "-"])
    def test_placeholder_titles_rejected(self, bad):
        assert not N.informative_title(bad)

    def test_real_title_accepted(self):
        assert N.informative_title("Director of Software Engineering")
