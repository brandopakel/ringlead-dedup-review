"""Normalization helpers.

Comparisons in this tool are almost never raw string equality: "DRW Holdings" and
"drw.com" are the same employer, "(612) 304-6073" and "6123046073" are the same
phone, and a LinkedIn URL can carry or omit the scheme, the www, and a trailing
slash. Everything that decides whether two values "agree" funnels through here.
"""

from __future__ import annotations

import difflib
import re

FREE_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "yahoo.co.in",
    "hotmail.com", "hotmail.co.uk", "outlook.com", "live.com", "msn.com",
    "aol.com", "icloud.com", "me.com", "mac.com", "protonmail.com", "proton.me",
    "gmx.com", "gmx.de", "mail.com", "yandex.com", "zoho.com", "qq.com",
    "163.com", "126.com", "naver.com", "comcast.net", "verizon.net", "att.net",
    "sbcglobal.net", "bellsouth.net", "cox.net", "charter.net", "earthlink.net",
    "rediffmail.com", "web.de", "orange.fr", "free.fr", "wanadoo.fr",
}

# Dropped when tokenizing a company name so "Acme Inc" matches "Acme".
_COMPANY_STOPWORDS = {
    "inc", "llc", "ltd", "limited", "corp", "corporation", "company", "co",
    "the", "and", "group", "holdings", "holding", "technologies", "technology",
    "tech", "solutions", "systems", "services", "international", "global",
    "worldwide", "software", "labs", "partners", "plc", "gmbh", "sa", "sas",
    "ag", "bv", "nv", "pty", "pte", "srl", "spa", "as", "ab", "oy", "kk",
    "usa", "us", "na", "america", "american",
}

_GENERIC_LOCALPARTS = {
    "info", "sales", "support", "admin", "contact", "hello", "help", "team",
    "marketing", "billing", "office", "enquiries", "inquiries", "noreply",
    "no-reply", "webmaster", "postmaster", "careers", "jobs", "hr", "legal",
}

# Company values that carry no employer signal. A group matched on name plus one of
# these is matched on name alone, which is why they are 6.5x more likely to be
# unverifiable than a group with a real Company.
PLACEHOLDER_COMPANIES = {
    "", "[not provided]", "not provided", "unknown", "n/a", "na", "none", "null",
    "-", "--", "test", "tbd", "no company", "self", "self employed", "student",
    "personal", "individual",
}

# Titles that carry no employment signal, so they must never win a freshness contest.
UNINFORMATIVE_TITLES = {
    "", "other", "n/a", "na", "none", "unknown", "-", "--", "test",
    "not provided", "not specified", "employee", "professional",
}


def blank(value) -> bool:
    return value is None or str(value).strip() == ""


def clean(value) -> str:
    return "" if value is None else str(value).strip()


def lower(value) -> str:
    return clean(value).lower()


def email(value) -> str:
    """Lowercased address, or "" if it isn't shaped like one."""
    v = lower(value)
    return v if "@" in v and "." in v.split("@")[-1] else ""


def email_domain(value) -> str:
    v = email(value)
    return v.split("@")[-1] if v else ""


def email_localpart(value) -> str:
    v = email(value)
    return v.split("@")[0] if v else ""


def localpart_matches_name(value, full_name) -> bool:
    """Does an address's local part spell out this person's name?

    "siddartha.reddy@anthem.com" and "siddartha.reddy@capitalone.com" share a local
    part that is demonstrably this person's name, which is meaningful corroboration
    across a job change. A shared "info" or "jsmith" is not, so the local part has to
    contain a name token of length 3+ to count.
    """
    parts = {p for p in re.split(r"[^a-z0-9]+", email_localpart(value)) if len(p) > 2}
    toks = {t for t in name_tokens(full_name) if len(t) > 2}
    return bool(parts and toks and parts & toks)


def name_coverage(value, tokens) -> int:
    """How much of a person's name an address actually spells out.

    Counts the name tokens present in the local part, so elisa.delmonte@ scores
    three against {elisa, del, monte} while elisad@ scores one. Departmental and
    role mailboxes -- info@, softcat@, dg75-se20-gestion-et-suivi-des-achats@ --
    score zero, which is what makes them lose to a person's own address.
    """
    local = re.sub(r"[^a-z]", "", email_localpart(value))
    if not local:
        return 0
    return sum(1 for t in tokens if len(t) > 2 and t in local)


def is_free_email(value) -> bool:
    return email_domain(value) in FREE_EMAIL_DOMAINS


def is_generic_email(value) -> bool:
    """Role addresses (info@, sales@) identify a mailbox, not a person."""
    return email_localpart(value).split("+")[0] in _GENERIC_LOCALPARTS


def phone_digits(value) -> str:
    """Last 10 digits, so +1 country codes and formatting don't cause false splits."""
    digits = re.sub(r"\D", "", clean(value))
    return digits[-10:] if len(digits) >= 10 else ""


def linkedin(value) -> str:
    """Canonical profile slug: strip scheme, host variants, query and trailing slash."""
    v = lower(value)
    if not v:
        return ""
    v = re.sub(r"^https?://", "", v)
    v = re.sub(r"^([a-z]{2,3}\.)?linkedin\.com/", "", v.replace("www.", ""))
    v = v.split("?")[0].rstrip("/")
    return re.sub(r"^(in|pub)/", "", v)


#: LinkedIn's opaque member URN form, e.g. /in/ACwAABEzP9IBnVwlgpt2wic0t7nnxi5ymei3tek
_LINKEDIN_URN = re.compile(r"^ac[o-w]a[a-z0-9_-]{10,}$", re.I)


def is_linkedin_urn(value) -> bool:
    return bool(_LINKEDIN_URN.match(linkedin(value)))


def linkedin_forms_comparable(values) -> bool:
    """False when the values mix URN and vanity-slug forms.

    A profile can be addressed either way, so "ACwAABEzP9IB..." and
    "neil-miller-38278580" may well be the same person -- string comparison cannot
    tell. Treating that as a conflict manufactures false evidence of two people,
    so the signal is discarded instead.
    """
    forms = {"urn" if _LINKEDIN_URN.match(v) else "slug" for v in values if v}
    return len(forms) < 2


#: Name tokens that identify nothing -- form junk, placeholders, filenames that
#: landed in a Name field. They must not be treated as evidence either way.
JUNK_NAME_TOKENS = {
    "not", "provided", "unknown", "none", "null", "test", "attachment", "email",
    "contact", "sales", "info", "admin", "user", "person",
}


def meaningful_name_tokens(value) -> frozenset[str]:
    return frozenset(
        t for t in name_tokens(value) if len(t) > 2 and t not in JUNK_NAME_TOKENS
    )


def names_are_related(a, b) -> bool:
    """Do two names plausibly belong to the same person?

    True when they share any meaningful token, allowing for transliteration slips
    (Mohamed/Mohammed, Sorour/Srrour). Sharing the surname is what carries nicknames
    and reversed name order: Michael/Mike Dempsey and "Bhavin Dave"/"Dave Bhavin"
    both pass, while "Sneha Gopalakrishnan" and "Harsimran Singh" do not.

    Returns True when either side has nothing meaningful to compare -- absence of a
    name is not evidence of a different person.
    """
    ta, tb = meaningful_name_tokens(a), meaningful_name_tokens(b)
    if not ta or not tb:
        return True
    return any(
        x == y or difflib.SequenceMatcher(None, x, y).ratio() >= 0.82
        for x in ta for y in tb
    )


def person_name(value) -> str:
    """Letters only, so "Bhavin Dave" and "Dave, Bhavin" normalize toward each other."""
    return re.sub(r"[^a-z]", "", lower(value))


def name_tokens(value) -> frozenset[str]:
    return frozenset(t for t in re.split(r"[^a-z]+", lower(value)) if len(t) > 1)


def company_tokens(value) -> frozenset[str]:
    """Distinctive words in a company name, stopwords removed."""
    toks = {t for t in re.split(r"[^a-z0-9]+", lower(value)) if len(t) > 2}
    return frozenset(toks - _COMPANY_STOPWORDS)


def domain_tokens(value) -> frozenset[str]:
    """Distinctive words in a domain, public suffix and stopwords removed.

    "drwholdings.com" -> {"drwholdings"}; the substring check in
    :func:`company_matches_domain` is what connects that back to "DRW Holdings".
    """
    host = lower(value).split("@")[-1]
    host = re.sub(r"^(www|mail|email|corp)\.", "", host)
    parts = host.split(".")
    # Drop the public suffix, incl. two-part ones like .com.au / .co.uk.
    if len(parts) > 2 and parts[-2] in {"com", "co", "net", "org", "gov", "edu", "ac"}:
        parts = parts[:-2]
    elif len(parts) > 1:
        parts = parts[:-1]
    toks = {t for t in parts if len(t) > 2}
    return frozenset(toks - _COMPANY_STOPWORDS)


def company_acronyms(value) -> frozenset[str]:
    """Initials a company is plausibly known by.

    Institutions overwhelmingly use their acronym as a domain -- hcsc.net, noaa.gov,
    llnl.gov -- and token overlap is structurally blind to that: "hcsc" shares no
    word with "Health Care Service Corporation". Two forms are produced, initials of
    every word and of the distinctive words alone, so both "hcsc" and "hcs" match.
    Three letters minimum, since two-letter initials collide with far too much.
    """
    words = [w for w in re.split(r"[^a-z0-9]+", lower(value)) if w]
    if len(words) < 2:
        return frozenset()
    forms = {"".join(w[0] for w in words)}
    distinctive = [w for w in words if w in company_tokens(value)]
    if len(distinctive) >= 2:
        forms.add("".join(w[0] for w in distinctive))
    return frozenset(f for f in forms if len(f) >= 3)


def company_matches_domain(company, domain) -> bool:
    """Does this email domain plausibly belong to this employer?

    Handles four shapes seen in the export: exact token overlap (Intuit/intuit.com),
    concatenation (DRW Holdings/drwholdings.com), acronyms (Health Care Service
    Corporation/hcsc.net), and truncation (Fortescue/fmgl.com.au fails here by design
    -- an alias that shares no letters can't be inferred).
    """
    ctoks, dtoks = company_tokens(company), domain_tokens(domain)
    if not ctoks or not dtoks:
        return False
    if ctoks & dtoks:
        return True
    # Acronyms are matched whole, never as substrings: "sig" inside "signal.com"
    # would be a coincidence, whereas sig.com is Susquehanna International Group.
    if company_acronyms(company) & dtoks:
        return True
    # "drwholdings" contains "drw"; "sidleyaustin" contains "sidley".
    cjoined, djoined = "".join(sorted(ctoks)), "".join(sorted(dtoks))
    for d in dtoks:
        for c in ctoks:
            if len(c) >= 3 and len(d) >= 3 and (c in d or d in c):
                return True
    return cjoined in djoined or djoined in cjoined


def same_company(a, b) -> bool:
    """Do two company names refer to the same employer?

    Distinct from :func:`company_matches_domain`, which compares a name to a web
    domain. Used to check that an Account link actually corroborates the employer
    before it gets recommended -- "Sail by the Numbers" must not be offered as the
    Account for someone at Microsoft.
    """
    ta, tb = company_tokens(a), company_tokens(b)
    if not ta or not tb:
        return False
    if ta & tb:
        return True
    ja, jb = "".join(sorted(ta)), "".join(sorted(tb))
    return ja in jb or jb in ja


def domain_only(value) -> str:
    """Bare registrable host from a URL, email or domain -- an Account's identity.

    "https://www.Northwind-Logistics.com/about" and "northwind-logistics.com" are the
    same company; comparing the raw Website strings would say otherwise.
    """
    v = lower(value).split("@")[-1]
    v = re.sub(r"^https?://", "", v).split("/")[0].split("?")[0]
    v = re.sub(r"^www\.", "", v).strip(". ")
    return v if "." in v else ""


def is_placeholder_company(value) -> bool:
    """True when Company says nothing about where the person works."""
    return lower(value) in PLACEHOLDER_COMPANIES


def informative_title(value) -> bool:
    return lower(value) not in UNINFORMATIVE_TITLES


def truthy(value) -> bool:
    return lower(value) in {"true", "1", "yes", "y"}
