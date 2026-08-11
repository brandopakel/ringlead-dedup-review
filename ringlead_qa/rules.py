"""The checks that decide whether a group needs human eyes.

Findings come in three severities:

    critical     -- something is demonstrably wrong with the merge output
    review       -- can't be settled from the data; a person has to look
    contributor  -- suspicious but common; only matters in combination

A group lands in the review queue if it has any critical or review finding, or if
its contributors add up past REVIEW_THRESHOLD. This tiering is what keeps the queue
small: signals like "the duplicates point at different Accounts" fire on 160 of 460
groups, so promoting them to triggers would defeat the purpose of the tool.

Every finding carries structured `evidence` rather than burying the specifics in
prose, so the report can render all findings the same way.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

from . import fields as F
from . import normalize as N
from .loader import Group, Record

CRITICAL, REVIEW, CONTRIB = "critical", "review", "contributor"

# Contributor points needed to pull a group into the queue on their own.
#
# Weighting rule of thumb: a contributor that fires on more than a quarter of the file
# is describing the routine merge shape, not evidence of a problem, so it gets weight 0
# -- it still renders in the report as context but can never push a group into the
# queue. In the sample export that zeroes owner_change (250/460), account_conflict
# (160), original_source_overwritten (169) and high_value_loss (135), leaving the
# genuinely unusual signals to do the work.
REVIEW_THRESHOLD = 6


@dataclass
class Correction:
    """What a field on the surviving record *should* say.

    RingLead's "After merge" column is a prediction of what will happen, defects
    included -- it is not a target. A Correction is the target: attach one only when
    the right value can be named from the data, never as a guess. These drive the
    "Should be" column in the report and the Salesforce correction sheet.
    """

    column: str
    value: str
    why: str


@dataclass
class MasterChange:
    """A different record should be the master.

    Categorically different from a Correction. A Correction edits a field on the
    record that survives; a MasterChange changes *which record survives*, so the
    surviving Lead ID itself changes and every field correction computed against the
    current merge preview becomes stale. It is a pre-merge change in RingLead, never
    a post-merge field update, which is why groups carrying one are held back from
    the Salesforce correction sheet.
    """

    record: Record
    why: str
    corroborated: bool = False  # independent signals agree, not just one


@dataclass
class Finding:
    code: str
    severity: str
    title: str
    detail: str
    weight: int = 0
    fields: list[str] = dc_field(default_factory=list)  # columns to surface in the report
    # (label, value) rows rendered as a uniform grid in the report. Keep labels to
    # one or two words so they align across findings.
    evidence: list[tuple[str, str]] = dc_field(default_factory=list)
    corrections: list[Correction] = dc_field(default_factory=list)
    master_change: MasterChange | None = None


# --------------------------------------------------------------------------
# Recency
# --------------------------------------------------------------------------
# Calibrated against ground truth -- the record whose email domain matches Company --
# across 251 groups, asking which timestamp identifies that record:
#
#     max(activity, created)   71%
#     created alone            69%
#     Last Modified            51%   <- a coin flip
#     ZoomInfo Last Updated    48%   <- worse than chance
#
# Last Modified and the ZoomInfo stamps move whenever an automated process writes to
# a record, so they measure enrichment traffic rather than whether the record still
# describes the person. Both are excluded. Activity is the sharpest signal but sits
# on only 34% of records; Created Date carries the rest.

def recency(rec: Record) -> str:
    """How recently this record was genuinely relevant. ISO strings sort correctly."""
    return max(rec.get(F.F_ACTIVITY)[:10], rec.get(F.F_CREATED)[:10])


def freshest(records: list[Record]) -> Record | None:
    """The most recently touched record, or None if they cannot be ranked apart."""
    ranked = sorted(records, key=recency, reverse=True)
    if len(ranked) < 2 or recency(ranked[0]) == recency(ranked[-1]):
        return None
    return ranked[0]


# --------------------------------------------------------------------------
# Identity: is this one human?
# --------------------------------------------------------------------------

# Normalizers referenced by EntitySpec.identity, resolved by name so the catalog
# stays declarative.
NORMALIZERS = {
    "linkedin": N.linkedin,
    "lower": N.lower,
    "phone_digits": N.phone_digits,
    "domain_only": N.domain_only,
}

#: Signals whose values can be non-comparable rather than merely different.
COMPARABILITY = {"linkedin": N.linkedin_forms_comparable}

#: Identifiers minted by a third party rather than observed about the person. When
#: one record is enriched from two different vendor records these disagree without
#: the people differing, so they are not allowed to declare "different people" on
#: their own if the group looks like a double import.
VENDOR_SIGNALS = {F.F_ZI_CONTACT, F.F_ZI_COMPANY, F.F_MOBILE, F.F_PHONE}


def same_import(g: Group) -> bool:
    """Do these records look like one entity loaded twice?

    Identical creation instant plus identical title and company. Salesforce stamps
    Created Date to the second, so two records sharing it came from one load -- and
    across the sample export every such group with comparable LinkedIn profiles
    agreed on identity.
    """
    created = {r.get(F.F_CREATED) for r in g.records if r.get(F.F_CREATED)}
    titles = {N.lower(r.get(F.F_TITLE)) for r in g.records if r.get(F.F_TITLE)}
    firms = {N.lower(r.get(F.F_COMPANY)) for r in g.records if r.get(F.F_COMPANY)}
    return len(created) == 1 and len(titles) == 1 and len(firms) == 1 and bool(created)


def check_identity(g: Group) -> list[Finding]:
    out: list[Finding] = []

    agreed, conflicted = [], []
    for logical, norm_name, name, strength in g.schema.identity_signals:
        fn = NORMALIZERS[norm_name]
        vals = [v for v in (fn(r.get(logical)) for r in g.records) if v]
        if len(vals) < 2:
            continue
        comparable = COMPARABILITY.get(norm_name)
        if comparable and not comparable(vals):
            continue  # different address forms for the same thing -- no evidence
        (conflicted if len(set(vals)) > 1 else agreed).append(
            (logical, name, sorted(set(vals)), strength)
        )

    # Phone numbers are compared as a set across Mobile and Phone: the same number
    # routinely lands in Mobile on one record and Phone on the other, and matching
    # field-to-field reads that as two different people.
    def numbers(rec):
        return {d for d in (N.phone_digits(rec.get(k))
                            for k in (F.F_MOBILE, F.F_PHONE)) if d}
    sets = [numbers(r) for r in g.records]
    shared = set.intersection(*sets) if all(sets) else set()
    # ...but only a personal line proves anything. Two colleagues share a company
    # switchboard, so a shared number counts only when it is somebody's Mobile.
    mobiles = {d for d in (N.phone_digits(r.get(F.F_MOBILE)) for r in g.records) if d}
    shared &= mobiles
    if shared:
        agreed.append((F.F_PHONE, "mobile number", sorted(shared), "weak"))

    # An exact email match is proof outright -- an address identifies one mailbox.
    emails = [e for e in (N.email(r.get(F.F_EMAIL)) for r in g.records) if e]
    if len(emails) >= 2 and len(set(emails)) == 1:
        agreed.append((F.F_EMAIL, "email address", [emails[0]]))
    elif len(emails) >= 2:
        # Across a job change the domain necessarily differs, but a local part that
        # spells out this person's name carrying over is real corroboration.
        locals_ = {N.email_localpart(e) for e in emails}
        name = g.surviving.get(F.F_FULL_NAME)
        if len(locals_) == 1 and N.localpart_matches_name(emails[0], name):
            agreed.append((F.F_EMAIL, "email name", sorted(emails)))

    double_import = same_import(g)
    for col, name, vals, strength in conflicted:
        # Something else about these records already matched. One signal disagreeing
        # against positive evidence is a contradiction for a human to resolve, not
        # grounds to declare two people -- and never grounds to skip a real merge.
        if agreed:
            out.append(Finding(
                code="identity_mixed",
                severity=REVIEW,
                title="Identifiers disagree, but others match",
                detail=(
                    f"{name.capitalize()} differs, while the "
                    f"{agreed[0][1]} matches across records."
                ),
                fields=[col],
                evidence=[
                    (g.schema.label(col), " vs ".join(vals[:3])),
                    ("Matches", " / ".join(agreed[0][2][:2])),
                ],
            ))
            continue
        # A vendor ID disagreeing inside an obvious double import says the vendor
        # holds two records for one person, not that there are two people.
        # A weak attribute disagreeing on its own is a question, not a verdict: a
        # person can hold two numbers, whereas a LinkedIn profile or vendor contact
        # ID names one person and is minted once.
        if strength == "weak":
            out.append(Finding(
                code="weak_identity_conflict",
                severity=REVIEW,
                title=f"{name.capitalize()} differs — check before merging",
                detail=(
                    "No stronger identifier is available either way, and one person "
                    "can legitimately have two of these."
                ),
                fields=[col],
                evidence=[(g.schema.label(col), " vs ".join(vals[:3]))],
            ))
            continue
        if double_import and col in VENDOR_SIGNALS:
            out.append(Finding(
                code="vendor_id_conflict",
                severity=REVIEW,
                title="Enrichment IDs disagree, but the records look like one import",
                detail=(
                    f"{name.capitalize()} differs, though both records share a "
                    "creation timestamp, title and company — the hallmark of one "
                    "person loaded from two vendor records."
                ),
                fields=[col],
                evidence=[
                    (g.schema.label(col), " vs ".join(vals[:3])),
                    ("Created", g.master.get(F.F_CREATED)[:19].replace("T", " ")),
                ],
            ))
            continue
        out.append(Finding(
            code="identity_conflict",
            severity=CRITICAL,
            title="Records may be different people",
            detail=f"{name.capitalize()} does not match. A shared name is not enough to merge on.",
            fields=[col],
            evidence=[(g.schema.label(col), " vs ".join(vals[:3]))],
        ))

    if not agreed and not conflicted:
        out.append(Finding(
            code="identity_unverified",
            severity=REVIEW,
            title="No way to confirm same person",
            detail="The match rests on name and company alone.",
            fields=[F.F_LINKEDIN, F.F_ZI_CONTACT, F.F_MOBILE, F.F_EMAIL],
            evidence=[("Missing", "LinkedIn, ZoomInfo Contact ID, mobile, matching email")],
        ))

    # Differing names are usually nicknames (Mike/Michael), so this only adds weight.
    # Skipped for Accounts, where the "name" is the company itself and is part of the
    # match key rather than evidence about it.
    names = {N.person_name(r.get(F.F_FULL_NAME)) for r in g.records if r.get(F.F_FULL_NAME)}
    if g.entity != "Account" and len(names) > 1 and not agreed:
        out.append(Finding(
            code="name_variant",
            severity=CONTRIB,
            title="Names are not identical",
            detail="Full name differs across records.",
            weight=3,
            fields=[F.F_FULL_NAME],
            evidence=[("Names", ", ".join(sorted(
                {r.get(F.F_FULL_NAME) for r in g.records if r.get(F.F_FULL_NAME)}
            )))],
        ))

    if len(g.records) > 2:
        out.append(Finding(
            code="large_group",
            severity=CONTRIB,
            title=f"{len(g.records)} records in group",
            detail="Larger groups compound the chance one member does not belong.",
            weight=2,
        ))

    # Weight 0 on purpose: 11 of the 13 groups this fires on are already flagged for
    # a stronger reason, and the other 2 carry positive identity confirmation. It
    # earns its place by naming a match-criteria fix, not by growing the queue.
    if N.is_placeholder_company(g.surviving.get(F.F_COMPANY)):
        out.append(Finding(
            code="placeholder_company",
            severity=CONTRIB,
            title="Company is a placeholder",
            detail="With no real Company, this group is matched on name alone.",
            weight=0,
            fields=[F.F_COMPANY],
            evidence=[("Company", g.surviving.get(F.F_COMPANY) or "(empty)")],
        ))

    generic = [r.get(F.F_EMAIL) for r in g.records if N.is_generic_email(r.get(F.F_EMAIL))]
    if generic:
        out.append(Finding(
            code="generic_email",
            severity=CONTRIB,
            title="Role-based email present",
            detail="An address like info@ identifies a mailbox, not a person.",
            weight=3,
            fields=[F.F_EMAIL],
            evidence=[("Address", ", ".join(generic))],
        ))

    return out


# --------------------------------------------------------------------------
# Employment freshness: does the survivor reflect the person's current job?
# --------------------------------------------------------------------------

def _titles_equivalent(a: str, b: str) -> bool:
    """Ignore punctuation-level rewrites of the same title."""
    ta, tb = N.name_tokens(a), N.name_tokens(b)
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= 0.8


def check_employment(g: Group) -> list[Finding]:
    out: list[Finding] = []
    company = g.surviving.get(F.F_COMPANY)
    kept = N.email(g.surviving.get(F.F_EMAIL))
    fresh = freshest(g.records)

    # --- the survivor's employer fields must agree with each other -----------
    # Email, Account link and Domain all describe one thing: where this person works
    # now. Deciding them by different tests produces an incoherent survivor -- an
    # NVIDIA address filed under the Amazon Account -- so the record whose email
    # matches Company is treated as *the* current-employer record and its employer
    # fields are taken as a set.
    if kept and company:
        kept_matches = N.company_matches_domain(company, N.email_domain(kept))
        current = next(
            (
                rec for rec in g.records
                if N.email(rec.get(F.F_EMAIL))
                and N.email(rec.get(F.F_EMAIL)) != kept
                and N.company_matches_domain(company, N.email_domain(rec.get(F.F_EMAIL)))
            ),
            None,
        )
        if not kept_matches and current is not None:
            addr = N.email(current.get(F.F_EMAIL))
            personal = N.is_free_email(kept)
            fixes = [Correction(
                F.F_EMAIL, addr, f"domain matches the current employer ({company})",
            )]
            # Carry the rest of that record's employer identity, but only where the
            # survivor actually disagrees -- a correction that changes nothing is noise.
            #
            # The Account link is carried only when it corroborates Company. That
            # record owning the right *email* does not mean it is filed under the
            # right *Account*, and recommending one wrong Account in place of another
            # is worse than leaving it alone.
            carry = [F.F_DOMAIN]
            if N.same_company(company, current.get(F.F_ACCOUNT_NAME)):
                carry = [F.F_ACCOUNT_ID, F.F_ACCOUNT_NAME, *carry]
            for logical in carry:
                theirs, survivors = current.get(logical), g.surviving.get(logical)
                if theirs and theirs != survivors:
                    fixes.append(Correction(
                        logical, theirs,
                        f"belongs with the {company} record that owns the kept email",
                    ))
            trailing = [g.schema.label(c.column) for c in fixes[1:]]
            # When two or more of the survivor's employer fields all have to be
            # overridden from one duplicate, that duplicate is the current-employer
            # record and promoting it is the real fix. Overriding Email, Account and
            # Domain by hand is the same change made three times, and it leaves
            # Account :: Name disagreeing with Company until every one is applied.
            promote = (
                MasterChange(
                    record=current,
                    why=(
                        f"holds the current {company} email and Account; promoting it "
                        f"settles {len(fixes)} fields at once"
                    ),
                    corroborated=True,
                )
                if current is not g.master and len(fixes) >= 2
                else None
            )
            out.append(Finding(
                code="stale_email_kept",
                severity=CRITICAL,
                title="Merge keeps the wrong primary email",
                master_change=promote,
                detail=(
                    f"The survivor works at {company} but keeps "
                    f"{'a personal address' if personal else 'a former employer’s address'}"
                    + (f", and {', '.join(trailing)} follow it." if trailing else ".")
                ),
                fields=[F.F_EMAIL, F.F_COMPANY, F.F_DOMAIN, F.F_ACCOUNT_ID, F.F_ACCOUNT_NAME],
                evidence=[("Company", company), ("Keeps", kept), ("Discards", addr)],
                corrections=fixes,
            ))

    # --- is the enriched employer corroborated by anything? -----------------
    # Company comes from enrichment, and enrichment goes stale. When not one address
    # in the group belongs to that employer there is nothing backing it up, which
    # also means any employer-based recommendation rests on an unverified premise.
    # Weight 0: this describes 31% of the file, so it is context, not evidence.
    if company and not N.is_placeholder_company(company):
        addresses = [N.email(r.get(F.F_EMAIL)) for r in g.records if N.email(r.get(F.F_EMAIL))]
        if addresses and not any(
            N.company_matches_domain(company, N.email_domain(a)) for a in addresses
        ):
            out.append(Finding(
                code="company_unconfirmed",
                severity=CONTRIB,
                title="No email backs up the stated employer",
                detail=(
                    f"Nothing in this group belongs to {company}, so the enriched "
                    "employer may be out of date."
                ),
                weight=0,
                fields=[F.F_COMPANY, F.F_EMAIL],
                evidence=[
                    ("Company", company),
                    ("Addresses", ", ".join(sorted({N.email_domain(a) for a in addresses}))),
                ],
            ))

    # --- the survivor's title should come from the freshest record ----------
    # A job title belongs to a job. Taking one from a record that works somewhere
    # else describes that other role -- on one group it recommended "Tupperware
    # consultant" for a survivor whose Company reads "payroll solutions iii".
    def same_employer(rec) -> bool:
        theirs = rec.get(F.F_COMPANY) or rec.get(F.F_ACCOUNT_NAME)
        return not (company and theirs) or N.same_company(company, theirs)

    titled = [
        (rec, rec.get(F.F_TITLE)) for rec in g.records
        if N.informative_title(rec.get(F.F_TITLE)) and same_employer(rec)
    ]
    if len(titled) >= 2:
        newest, fresh_title = max(titled, key=lambda rt: recency(rt[0]))
        kept_title = g.surviving.get(F.F_TITLE)
        if (
            kept_title and fresh_title
            and kept_title != fresh_title
            and not _titles_equivalent(kept_title, fresh_title)
        ):
            out.append(Finding(
                code="stale_title_kept",
                severity=REVIEW,
                title="Merge may keep an outdated job title",
                detail="A more recently updated record carries a different title.",
                fields=[F.F_TITLE],
                evidence=[
                    ("Keeps", kept_title),
                    ("Discards", fresh_title),
                    ("Fresher", f"{newest.label.lower()}, updated {recency(newest)[:10]}"),
                ],
                corrections=[Correction(
                    F.F_TITLE, fresh_title,
                    f"from the most recently updated record ({recency(newest)[:10]})",
                )],
            ))

    # --- the survivor's Account link should be the current employer's -------
    if fresh is not None:
        fresh_acct, kept_acct = fresh.get(F.F_ACCOUNT_ID), g.surviving.get(F.F_ACCOUNT_ID)
        # Recency alone is not licence to repoint the Account. On one group it named
        # Highmark as the Account for someone whose Company is Sidley Austin, purely
        # because an automated write had touched that record more recently. The
        # replacement has to agree with Company, and the incumbent has to not.
        kept_fits = N.same_company(company, g.surviving.get(F.F_ACCOUNT_NAME))
        fresh_fits = N.same_company(company, fresh.get(F.F_ACCOUNT_NAME))
        if fresh_acct and kept_acct and fresh_acct != kept_acct and fresh_fits and not kept_fits:
            out.append(Finding(
                code="stale_account_link",
                severity=CONTRIB,
                title="Survivor keeps an older Account link",
                detail="The most recently updated record points at a different Account.",
                weight=3,
                fields=[F.F_ACCOUNT_ID, F.F_ACCOUNT_NAME],
                evidence=[
                    ("Keeps", g.surviving.get(F.F_ACCOUNT_NAME) or kept_acct),
                    ("Discards", fresh.get(F.F_ACCOUNT_NAME) or fresh_acct),
                ],
                corrections=[
                    Correction(F.F_ACCOUNT_ID, fresh_acct, "Account on the most recently updated record"),
                    Correction(F.F_ACCOUNT_NAME, fresh.get(F.F_ACCOUNT_NAME),
                               "Account on the most recently updated record"),
                ],
            ))

        fresh_mob, kept_mob = N.phone_digits(fresh.get(F.F_MOBILE)), N.phone_digits(g.surviving.get(F.F_MOBILE))
        if fresh_mob and kept_mob and fresh_mob != kept_mob:
            out.append(Finding(
                code="stale_mobile_kept",
                severity=REVIEW,
                title="Merge keeps an older mobile number",
                detail="The most recently updated record has a different mobile.",
                fields=[F.F_MOBILE],
                evidence=[("Keeps", g.surviving.get(F.F_MOBILE)), ("Discards", fresh.get(F.F_MOBILE))],
                corrections=[Correction(
                    F.F_MOBILE, fresh.get(F.F_MOBILE),
                    "from the most recently updated record",
                )],
            ))

    # --- account links --------------------------------------------------------
    accounts = {r.get(F.F_ACCOUNT_ID) for r in g.records if r.get(F.F_ACCOUNT_ID)}
    if len(accounts) > 1:
        names = sorted({r.get(F.F_ACCOUNT_NAME) for r in g.records if r.get(F.F_ACCOUNT_NAME)})
        out.append(Finding(
            code="account_conflict",
            severity=CONTRIB,
            title="Duplicates point at different Accounts",
            detail="The merge keeps one Account link and drops the rest.",
            weight=0,
            fields=[F.F_ACCOUNT_ID, F.F_ACCOUNT_NAME],
            evidence=[("Accounts", ", ".join(names) or f"{len(accounts)} unnamed")],
        ))

    return out


# --------------------------------------------------------------------------
# Master choice: is the right record winning?
# --------------------------------------------------------------------------

def check_master_choice(g: Group) -> list[Finding]:
    out: list[Finding] = []

    master_act = g.master.get(F.F_ACTIVITY)
    master_born = g.master.get(F.F_CREATED)[:10]
    fresher = [
        (d, d.get(F.F_ACTIVITY))
        for d in g.duplicates
        if d.get(F.F_ACTIVITY) and (not master_act or d.get(F.F_ACTIVITY) > master_act)
        # An activity older than the master's own creation cannot show the duplicate
        # is the fresher record. Without this a 2024 touch on a 2024 record outranks
        # a record created in 2026 purely because the newer one has no activity yet.
        and (not master_born or d.get(F.F_ACTIVITY)[:10] >= master_born)
    ]
    if fresher:
        rec, when = max(fresher, key=lambda dv: dv[1])
        # When the composite timestamps agree with the activity dates, the master
        # really is the colder record rather than just the one missing activity data.
        corroborated = recency(rec) > recency(g.master)
        out.append(Finding(
            code="master_stale",
            severity=REVIEW,
            title="A duplicate is more active than the master",
            detail=(
                "Both activity and update timestamps favour the duplicate."
                if corroborated else
                "The livelier record may deserve to win."
            ),
            fields=[F.F_ACTIVITY, F.F_LAST_ACTIVITY],
            evidence=[
                ("Master", master_act or "no activity recorded"),
                ("Duplicate", when),
            ],
            master_change=MasterChange(
                record=rec,
                why=(
                    f"active {when}, against the master's "
                    f"{master_act or 'no recorded activity'}"
                ),
                corroborated=corroborated,
            ),
        ))

    master_owner_dead = N.lower(g.master.get(F.F_OWNER_ACTIVE)) == "false"
    live_dup = next((d for d in g.duplicates if N.truthy(d.get(F.F_OWNER_ACTIVE))), None)
    if master_owner_dead and live_dup is not None:
        out.append(Finding(
            code="master_owner_inactive",
            severity=REVIEW,
            title="Master is owned by a deactivated user",
            detail="The merge parks this lead with someone who has left.",
            fields=[F.F_OWNER_NAME, F.F_OWNER_ACTIVE],
            evidence=[
                ("Master owner", f"{g.master.get(F.F_OWNER_NAME) or 'unknown'} (inactive)"),
                ("Duplicate owner", f"{live_dup.get(F.F_OWNER_NAME) or 'unknown'} (active)"),
            ],
            master_change=MasterChange(
                record=live_dup,
                why=(
                    f"owned by {live_dup.get(F.F_OWNER_NAME) or 'an active user'}, "
                    f"who is still active"
                ),
                corroborated=True,
            ),
        ))
    elif g.surviving.get(F.F_OWNER_NAME) and len({
        r.get(F.F_OWNER_NAME) for r in g.records if r.get(F.F_OWNER_NAME)
    }) > 1:
        out.append(Finding(
            code="owner_change",
            severity=CONTRIB,
            title="Ownership changes on merge",
            detail="Records have different owners; the merge consolidates them.",
            weight=0,
            fields=[F.F_OWNER_NAME, F.F_AE_OWNER, F.F_BDR_OWNER],
        ))

    return out


# --------------------------------------------------------------------------
# Data loss: what does the merge destroy?
# --------------------------------------------------------------------------

def check_data_loss(g: Group) -> list[Finding]:
    out: list[Finding] = []

    # --- funnel regression ---------------------------------------------------
    kept_rank = F.LIFECYCLE_RANK.get(N.lower(g.surviving.get(F.F_LIFECYCLE)))
    ranked = [
        (r, F.LIFECYCLE_RANK[N.lower(r.get(F.F_LIFECYCLE))])
        for r in g.records
        if N.lower(r.get(F.F_LIFECYCLE)) in F.LIFECYCLE_RANK
    ]
    if kept_rank is not None and ranked:
        best_rec, best_rank = max(ranked, key=lambda rr: rr[1])
        if best_rank > kept_rank:
            out.append(Finding(
                code="lifecycle_regression",
                severity=CRITICAL,
                title="Merge demotes the lead's funnel stage",
                detail="Funnel progress is thrown away by the merge.",
                fields=[F.F_LIFECYCLE, F.F_LEAD_STATUS],
                evidence=[
                    ("Keeps", g.surviving.get(F.F_LIFECYCLE)),
                    ("Discards", f"{best_rec.get(F.F_LIFECYCLE)} (on the {best_rec.label.lower()})"),
                ],
                corrections=[Correction(
                    F.F_LIFECYCLE, best_rec.get(F.F_LIFECYCLE),
                    "furthest funnel stage reached by any record in the group",
                )],
            ))

    # --- the latest event outranks the first one ----------------------------
    # Lead Source Detail names the specific campaign or event. For event-sourced
    # records the most recent one is the useful fact -- which event they last
    # attended -- so recency wins there even though the surrounding fields are
    # first-touch history.
    detail_col = g.schema.col(F.F_LEAD_SOURCE_DETAIL)
    event_records = [
        r for r in g.records
        if F.EVENT_SOURCE_MARKER in N.lower(r.get(F.F_LEAD_SOURCE)) and r.get(F.F_LEAD_SOURCE_DETAIL)
    ]
    if detail_col and len(event_records) >= 1:
        latest = max(event_records, key=recency)
        kept_detail = g.surviving.get(F.F_LEAD_SOURCE_DETAIL)
        if kept_detail and latest.get(F.F_LEAD_SOURCE_DETAIL) != kept_detail:
            out.append(Finding(
                # Weight 0: the right value is derivable, so this needs applying
                # rather than judging. It reaches the reviewer as a "Should be" value
                # and reaches the criteria owner as a survivorship change.
                code="stale_event_kept",
                severity=CONTRIB,
                weight=0,
                title="Merge keeps an older event",
                detail="The most recent event attended is the more useful record.",
                fields=[F.F_LEAD_SOURCE_DETAIL],
                evidence=[
                    ("Keeps", kept_detail),
                    ("Discards", latest.get(F.F_LEAD_SOURCE_DETAIL)),
                ],
                corrections=[Correction(
                    F.F_LEAD_SOURCE_DETAIL, latest.get(F.F_LEAD_SOURCE_DETAIL),
                    "most recent event attended",
                )],
            ))

    # --- attribution: the oldest *informative* source, not merely the oldest ----
    # Chronology alone made this rule destructive: it pushed "Paid Digital" back to
    # "Sales Generated" whenever the rep-created row happened to be older, which was
    # half of everything it recommended. A rep-generated value records that someone
    # keyed the row in, not where the lead came from, so a real source outranks it
    # regardless of age. Age decides only among sources of equal standing.
    def source_rank(rec):
        return F.LEAD_SOURCE_RANK.get(
            N.lower(rec.get(F.F_LEAD_SOURCE)), F.DEFAULT_LEAD_SOURCE_RANK
        )

    sourced = [r for r in g.records if r.get(F.F_LEAD_SOURCE)]
    if sourced:
        best = max(source_rank(r) for r in sourced)
        # Oldest among the best-ranked records: that is the true first touch.
        attribution = min((r for r in sourced if source_rank(r) == best), key=recency)
        # Lead Source and its Detail describe one event and move together -- except
        # on event-sourced records, where the Detail names which event was attended
        # and the most recent one wins. Claiming it here too would hand back the
        # older event and undo that rule.
        columns = [F.F_LEAD_SOURCE]
        if not event_records:
            columns.append(F.F_LEAD_SOURCE_DETAIL)
        for logical in columns:
            theirs, kept = attribution.get(logical), g.surviving.get(logical)
            if theirs and kept and N.lower(theirs) != N.lower(kept):
                out.append(Finding(
                    code="original_source_overwritten",
                    severity=CONTRIB,
                    title="First-touch attribution is overwritten",
                    detail="The survivor reports a different source than the first real touch.",
                    weight=0,
                    fields=[g.schema.col(logical) or logical],
                    evidence=[
                        ("Field", g.schema.label(logical)),
                        ("Survivor", kept),
                        ("First touch", theirs),
                    ],
                    corrections=[Correction(
                        logical, theirs,
                        "earliest record carrying a real acquisition source",
                    )],
                ))

    oldest = min(g.records, key=recency) if len(g.records) > 1 else None
    if oldest is not None:
        # Lead Source Detail is excluded when the group is event-sourced: recency
        # already decided it just above, and both rules claiming the column would
        # emit contradictory targets.
        # Lead Source and Lead Source Detail are decided above, by standing rather
        # than by age alone; leaving them here too would emit contradictory targets.
        claimed = {g.schema.col(F.F_LEAD_SOURCE), g.schema.col(F.F_LEAD_SOURCE_DETAIL)}
        skip_detail = detail_col if event_records else None
        overwritten = [
            (col, oldest.get(col), g.surviving.get(col))
            for col in g.schema.historical_fields
            if col != skip_detail and col not in claimed
            and oldest.get(col) and g.surviving.get(col)
            # Case-insensitive: "ZoomInfo" surviving as "Zoominfo" is the same value
            # typed differently, not first-touch attribution being overwritten.
            and N.lower(oldest.get(col)) != N.lower(g.surviving.get(col))
        ]
        if overwritten:
            col, was, now = overwritten[0]
            out.append(Finding(
                code="original_source_overwritten",
                severity=CONTRIB,
                title="First-touch attribution is overwritten",
                detail="The survivor reports a later source than the original record.",
                weight=0,
                fields=[c for c, _, _ in overwritten],
                evidence=[("Field", g.schema.label(col)), ("Original", was), ("Survivor", now)],
                corrections=[
                    Correction(c, old, "first-touch attribution belongs to the original record")
                    for c, old, _ in overwritten
                ],
            ))

    # --- tier is earned; a merge must not hand back a weaker one -------------
    kept_tier = F.LEAD_TIER_RANK.get(N.lower(g.surviving.get(F.F_LEAD_TIER)))
    tiered = [
        (r, F.LEAD_TIER_RANK[N.lower(r.get(F.F_LEAD_TIER))])
        for r in g.records if N.lower(r.get(F.F_LEAD_TIER)) in F.LEAD_TIER_RANK
    ]
    if kept_tier is not None and tiered:
        best_rec, best = max(tiered, key=lambda rt: rt[1])
        if best > kept_tier:
            out.append(Finding(
                # Weight 0, like the other derivable-value rules: the strongest tier
                # in the group is not a judgement call, so this ships as a "Should
                # be" value and a survivorship change rather than 93 reviews.
                code="lead_tier_downgrade",
                severity=CONTRIB,
                weight=0,
                title="Merge lands on a weaker lead tier",
                detail=(
                    "Tier is derived and Salesforce re-evaluates it automatically, so "
                    "do not set it by hand — check that the surviving email and Account "
                    "are right and the tier follows."
                ),
                fields=[F.F_LEAD_TIER],
                evidence=[
                    ("Preview", g.surviving.get(F.F_LEAD_TIER)),
                    ("Available", f"{best_rec.get(F.F_LEAD_TIER)} (on the {best_rec.label.lower()})"),
                ],
            ))

    # --- narrative fields are unrecoverable once merged ----------------------
    for col in (F.F_NOTES, F.F_DESCRIPTION, F.F_UNQUALIFIED):
        lost = g.lost_values(col)
        if lost and not g.surviving.get(col):
            rec, val = lost[0]
            out.append(Finding(
                code="narrative_loss",
                severity=REVIEW,
                title=f"{g.schema.label(col)} is destroyed by the merge",
                detail=f"The survivor keeps no {g.schema.label(col).lower()}.",
                fields=[col],
                evidence=[("On the", rec.label.lower()), ("Lost text", val[:200])],
            ))

    # --- a second reachable address at the same employer --------------------
    emails = [e for e in (N.email(r.get(F.F_EMAIL)) for r in g.records) if e]
    kept = N.email(g.surviving.get(F.F_EMAIL))
    same_domain_alias = [
        e for e in emails
        if e != kept and kept and N.email_domain(e) == N.email_domain(kept)
    ]
    if same_domain_alias:
        out.append(Finding(
            code="email_alias_loss",
            severity=CONTRIB,
            title="A working address at the same domain is dropped",
            detail="It shares a domain with the kept address, so it is likely deliverable.",
            weight=2,
            fields=[F.F_EMAIL],
            evidence=[("Dropped", ", ".join(same_domain_alias))],
        ))

    # --- everything else worth counting -------------------------------------
    high_lost = [
        col for col in g.populated_columns()
        if g.schema.tier(col) == "high"
        and col not in {F.F_NOTES, F.F_DESCRIPTION, F.F_UNQUALIFIED, F.F_EMAIL, F.F_LIFECYCLE}
        and g.lost_values(col)
    ]
    if len(high_lost) >= 4:
        out.append(Finding(
            code="high_value_loss",
            severity=CONTRIB,
            title=f"{len(high_lost)} high-value fields lose data",
            detail="Values present on a duplicate do not survive the merge.",
            weight=0,
            fields=high_lost[:10],
            evidence=[("Fields", ", ".join(g.schema.label(c) for c in high_lost[:8]))],
        ))

    return out


# --------------------------------------------------------------------------
# Projection: what the merge produces under a different master
# --------------------------------------------------------------------------

def project(g: Group, new_master: Record) -> Group:
    """Rebuild the group as if `new_master` had won.

    Mirrors RingLead's observed survivorship: the master's value wins, and where
    the master is blank the value is filled from a duplicate. Recommending a master
    change and then computing field fixes against the *old* preview would send the
    reviewer round an export/re-import loop, so the fixes are derived from this
    projection instead -- the state RingLead will compute once the master is changed.
    """
    others = [r for r in g.records if r is not new_master]
    data = {}
    for col in g.schema.columns:
        value = new_master.data.get(col, "")
        if not N.clean(value):
            for other in others:
                if N.clean(other.data.get(col, "")):
                    value = other.data.get(col)
                    break
        data[col] = value
    return Group(
        group_id=g.group_id, schema=g.schema,
        surviving=Record("surviving", data, g.schema),
        master=new_master, duplicates=others,
    )


# --------------------------------------------------------------------------

ALL_CHECKS = (check_identity, check_employment, check_master_choice, check_data_loss)


@dataclass
class Verdict:
    group: Group
    findings: list[Finding]
    #: The same group re-evaluated under the recommended master, when one is
    #: recommended. Field fixes are read from here so a reviewer sees one coherent
    #: end state rather than two rounds of changes.
    projected: "Verdict | None" = None

    @property
    def critical(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == CRITICAL]

    @property
    def review(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == REVIEW]

    @property
    def contributors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == CONTRIB]

    @property
    def contributor_score(self) -> int:
        return sum(f.weight for f in self.contributors)

    @property
    def status(self) -> str:
        # Ranked before "critical" because the action is categorically different:
        # every other flagged group gets merged with corrections, this one should
        # not be merged at all until a human confirms the records are one person.
        if self.corrections_blocked:
            return "skip"
        if self.critical:
            return "critical"
        if self.review or self.contributor_score >= REVIEW_THRESHOLD:
            return "review"
        return "ok"

    @property
    def needs_review(self) -> bool:
        return self.status != "ok"

    @property
    def sort_key(self) -> tuple:
        rank = {"skip": 0, "critical": 1, "review": 2, "ok": 3}[self.status]
        return (rank, -len(self.critical), -len(self.review), -self.contributor_score, self.group.group_id)

    @property
    def headline(self) -> str:
        if self.status == "skip":
            return "Do not merge — may be different people"
        for f in self.findings:
            if f.severity in (CRITICAL, REVIEW):
                return f.title
        return "Clean merge"

    @property
    def corrections_blocked(self) -> str:
        """Why no field recommendations are offered, or "" if they are.

        Every correction assumes the group is one entity whose fields can be pooled.
        When identity is contradicted that premise is gone: copying the other
        record's email and employer onto the survivor would fuse two different
        people. The right output there is "look at this", not "set these values".
        """
        if any(f.code == "identity_conflict" for f in self.findings):
            return (
                "These records may not be the same person, so no values are "
                "recommended — confirm the match first."
            )
        return ""

    @property
    def corrections(self) -> list[Correction]:
        """What the surviving record should say, one entry per field.

        First finding to claim a column wins, and findings are already sorted
        critical-first, so a demonstrable defect outranks a softer suggestion.
        """
        if self.corrections_blocked:
            return []
        # After a master change RingLead recomputes the survivor itself, so the only
        # values worth listing are the ones still wrong afterwards.
        source = self.projected.findings if self.projected else self.findings
        seen: dict[str, Correction] = {}
        for f in source:
            for c in f.corrections:
                if c.value and c.column not in seen:
                    seen[c.column] = c
        return list(seen.values())

    @property
    def master_change(self) -> MasterChange | None:
        """The record that should be master instead, if the data names one.

        Findings are sorted critical-first, and a corroborated recommendation
        outranks a single-signal one.
        """
        if self.corrections_blocked:
            return None
        candidates = [f.master_change for f in self.findings if f.master_change]
        if not candidates:
            return None
        return max(candidates, key=lambda m: m.corroborated)

    def highlight_fields(self) -> list[str]:
        seen, out = set(), []
        for f in self.findings:
            for c in f.fields:
                if c not in seen:
                    seen.add(c)
                    out.append(c)
        return out


def _run_checks(group: Group) -> list[Finding]:
    findings: list[Finding] = []
    for check in ALL_CHECKS:
        findings.extend(check(group))
    order = {CRITICAL: 0, REVIEW: 1, CONTRIB: 2}
    findings.sort(key=lambda f: (order[f.severity], -f.weight))
    return findings


def evaluate(group: Group) -> Verdict:
    verdict = Verdict(group=group, findings=_run_checks(group))
    change = verdict.master_change
    if change is not None:
        # Evaluated once, without projecting again -- the recommendation is already
        # applied, so a second round would have nothing left to change.
        projected = project(group, change.record)
        verdict.projected = Verdict(group=projected, findings=_run_checks(projected))
    return verdict


def surviving_record_id(v: Verdict) -> str:
    """The record that will actually survive, honouring a recommended master change.

    Reads the recommendation directly rather than relying on the projection, so the
    answer holds however the verdict was assembled.
    """
    if v.projected is not None:
        return v.projected.group.master.record_id
    if v.master_change is not None:
        return v.master_change.record.record_id
    return v.group.surviving.record_id
