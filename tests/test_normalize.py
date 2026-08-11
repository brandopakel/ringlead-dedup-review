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

    def test_urn_form_is_recognised(self):
        """LinkedIn addresses a profile by vanity slug OR opaque member URN."""
        assert N.is_linkedin_urn(
            "https://www.linkedin.com/in/ACwAABEzP9IBnVwlgpt2wic0t7nnxi5ymei3tek")
        assert not N.is_linkedin_urn("https://www.linkedin.com/in/neil-miller-38278580")

    def test_urn_and_slug_are_not_comparable(self):
        """The bug this prevents: two forms of one profile read as two people."""
        assert not N.linkedin_forms_comparable([
            N.linkedin("linkedin.com/in/ACwAABEzP9IBnVwlgpt2wic0t7nnxi5ymei3tek"),
            N.linkedin("linkedin.com/in/neil-miller-38278580"),
        ])

    def test_two_slugs_stay_comparable(self):
        """Genuinely different vanity slugs must still be judged."""
        assert N.linkedin_forms_comparable([
            N.linkedin("linkedin.com/in/maryvarghese"),
            N.linkedin("linkedin.com/in/mathew-varghese-0b01b4228"),
        ])


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

    @pytest.mark.parametrize("company,domain", [
        ("Health Care Service Corporation", "hcsc.net"),
        ("National Oceanic and Atmospheric Administration", "noaa.gov"),
        ("Lawrence Livermore National Laboratory", "llnl.gov"),
        ("Susquehanna International Group", "sig.com"),
        ("New York Stock Exchange", "nyse.com"),
        ("George Washington University", "gwmail.gwu.edu"),
    ])
    def test_acronym_domains_match(self, company, domain):
        """Institutions use their initials as a domain; token overlap cannot see it."""
        assert N.company_matches_domain(company, domain)

    def test_acronyms_match_whole_tokens_only(self):
        """"sig" inside "signal.com" is a coincidence, not Susquehanna."""
        assert not N.company_matches_domain("Susquehanna International Group", "signal.com")

    def test_two_letter_initials_are_too_collidable(self):
        assert N.company_acronyms("General Electric") == frozenset()

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


class TestNameCoverage:
    """Among addresses at one domain, the fullest spelling of the name wins."""

    ELISA = {"elisa", "del", "monte"}

    def test_an_initial_scores_below_the_full_name(self):
        assert N.name_coverage("elisad@seacom.it", self.ELISA) < \
               N.name_coverage("elisa.delmonte@seacom.it", self.ELISA)

    def test_separators_do_not_matter(self):
        assert N.name_coverage("elisa_del_monte@x.com", self.ELISA) == \
               N.name_coverage("elisadelmonte@x.com", self.ELISA)

    @pytest.mark.parametrize("mailbox", [
        "info@valure-tech.com",
        "softcat@qbssoftware.com",
        "dg75-se20-gestion-et-suivi-des-achats@insee.fr",
    ])
    def test_departmental_mailboxes_score_nothing(self, mailbox):
        """Which is how a person's own address beats a team alias."""
        assert N.name_coverage(mailbox, {"olivier", "kremer"}) == 0

    def test_a_prefixed_address_still_counts_what_it_spells(self):
        assert N.name_coverage("ts-vikram.singh@rakuten.com", {"vikram", "singh"}) == 2


class TestNameRelatedness:
    """Enrichment mis-attaches identifiers, so names get an independent vote."""

    @pytest.mark.parametrize("a,b", [
        ("Michael Dempsey", "Mike Dempsey"),        # nickname, shared surname
        ("Bhavin Dave", "Dave Bhavin"),             # reversed order
        ("Mohamed Sorour", "Mohammed Srrour"),      # transliteration slips
        ("Thomas Wood", "Tom Wood"),
        ("Eric Ceccotti", "Eric _"),                # truncated but shared token
    ])
    def test_related_names(self, a, b):
        assert N.names_are_related(a, b)

    @pytest.mark.parametrize("a,b", [
        ("Sneha Gopalakrishnan", "Harsimran Singh"),
        ("Bev Tucker", "Diwakar Arumugam"),
        ("Joshua Deffibaugh", "Josh Davis"),        # nickname, different surname
        ("John Lu", "jack lee"),
        ("Kathy Weir", "CDPrasad ."),
    ])
    def test_unrelated_names(self, a, b):
        assert not N.names_are_related(a, b)

    @pytest.mark.parametrize("junk", ["[not provided]", "Sales", "_", ""])
    def test_placeholders_are_not_evidence(self, junk):
        """An absent name says nothing; it must not accuse anyone."""
        assert N.names_are_related("Eric Ceccotti", junk)


class TestTitles:
    @pytest.mark.parametrize("bad", ["", "Other", "n/a", "UNKNOWN", "-"])
    def test_placeholder_titles_rejected(self, bad):
        assert not N.informative_title(bad)

    def test_real_title_accepted(self):
        assert N.informative_title("Director of Software Engineering")
