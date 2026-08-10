"""Normalization helpers.

Comparisons in this tool are almost never raw string equality: "DRW Holdings" and
"drw.com" are the same employer, "(612) 304-6073" and "6123046073" are the same
phone, and a LinkedIn URL can carry or omit the scheme, the www, and a trailing
slash. Everything that decides whether two values "agree" funnels through here.
"""

from __future__ import annotations

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


def company_matches_domain(company, domain) -> bool:
    """Does this email domain plausibly belong to this employer?

    Handles three shapes seen in the export: exact token overlap (Intuit/intuit.com),
    concatenation (DRW Holdings/drwholdings.com), and truncation (Fortescue/fmgl.com.au
    fails here by design -- an alias that shares no letters can't be inferred).
    """
    ctoks, dtoks = company_tokens(company), domain_tokens(domain)
    if not ctoks or not dtoks:
        return False
    if ctoks & dtoks:
        return True
    # "drwholdings" contains "drw"; "sidleyaustin" contains "sidley".
    cjoined, djoined = "".join(sorted(ctoks)), "".join(sorted(dtoks))
    for d in dtoks:
        for c in ctoks:
            if len(c) >= 3 and len(d) >= 3 and (c in d or d in c):
                return True
    return cjoined in djoined or djoined in cjoined


def domain_only(value) -> str:
    """Bare registrable host from a URL, email or domain -- an Account's identity.

    "https://www.Northwind-Logistics.com/about" and "northwind-logistics.com" are the
    same company; comparing the raw Website strings would say otherwise.
    """
    v = lower(value).split("@")[-1]
    v = re.sub(r"^https?://", "", v).split("/")[0].split("?")[0]
    v = re.sub(r"^www\.", "", v).strip(". ")
    return v if "." in v else ""


def informative_title(value) -> bool:
    return lower(value) not in UNINFORMATIVE_TITLES


def truthy(value) -> bool:
    return lower(value) in {"true", "1", "yes", "y"}
