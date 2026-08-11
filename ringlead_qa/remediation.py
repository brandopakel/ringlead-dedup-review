"""Handoff artifacts generated alongside every report.

Two audiences, because the fixes land in two different places:

* `survivorship_changelist` -> for whoever owns the RingLead resolution criteria.
  Settings to change once, with the group count each change clears. Most defects in
  a run collapse into a handful of these, so this is the higher-leverage document.
* `correction_sheet` -> for whoever has Salesforce write access. One row per
  surviving record with the fields that need correcting *after* the merge runs,
  shaped for Data Loader.

Neither requires credentials to produce.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime

import pandas as pd

from . import fields as F
from .rules import Verdict, surviving_record_id

# code -> (setting to change in RingLead, what to change it to)
#
# Split matters: field survivorship decides which *value* wins, master selection
# decides which *record* wins. They are different screens and different fixes.
SURVIVORSHIP_RULES = {
    "stale_email_kept": (
        "Field survivorship — Email",
        "Prefer the address whose domain matches Company, instead of always taking "
        "the master record's value.",
    ),
    "original_source_overwritten": (
        "Field survivorship — Lead Source, Lead Source Detail, Original Source",
        "Prefer the OLDEST record. First-touch attribution is history; taking the "
        "newer value destroys the answer rather than refreshing it.",
    ),
    "stale_account_link": (
        "Field survivorship — Account",
        "Prefer the most recently updated record, so the survivor points at the "
        "current employer's Account.",
    ),
    "stale_event_kept": (
        "Field survivorship — Lead Source Detail on event-sourced records",
        "For records whose Lead Source is an event, prefer the MOST RECENT record's "
        "Lead Source Detail. Which event someone last attended is the actionable "
        "fact; the surrounding first-touch fields stay oldest-wins.",
    ),
    "stale_title_kept": (
        "Field survivorship — Title",
        "Prefer the most recently updated record.",
    ),
    "stale_mobile_kept": (
        "Field survivorship — Mobile",
        "Prefer the most recently updated record.",
    ),
    "lead_tier_downgrade": (
        "No survivorship change — Lead Tier is derived",
        "Do NOT set a survivorship rule for Lead Tier. The Marketing Field Dictionary "
        "(p3) states it is automatically re-evaluated whenever target-account status, "
        "email, title or country changes, so Salesforce recomputes it after the merge. "
        "A weaker tier in the preview means the wrong record is surviving — fix the "
        "Email and Account rules above and the tier corrects itself.",
    ),
    "lifecycle_regression": (
        "Field survivorship — Lifecycle Stage",
        "Prefer the furthest funnel stage reached by any record in the group, so a "
        "merge can never demote a lead.",
    ),
    "master_owner_inactive": (
        "Master selection — owner is active",
        "Add “owner is active” as a criterion, so leads stop landing with reps who "
        "have left.",
    ),
    "master_stale": (
        "Master selection — activity recency",
        "Weight Most Recent Activity Date more heavily when choosing the master.",
    ),
    "placeholder_company": (
        "Match criteria — placeholder Company values",
        "Exclude records whose Company is a placeholder ([not provided], unknown, "
        "n/a, blank) from name+company matching, or require a second identifier for "
        "them. With no real Company the rule collapses to name-only: in the sample "
        "export 85% of these groups could not be verified as the same person, "
        "against 13% of groups with a real Company — 6.5x the rate.",
    ),
    "identity_unverified": (
        "Match criteria — require a second identifier",
        "These groups match on name and company alone. Require a second identifier — "
        "LinkedIn Profile, ZoomInfo Contact ID, or Mobile — to group records.",
    ),
}


def survivorship_changelist(verdicts: list[Verdict], *, source: str) -> str:
    """Markdown change-list for the person who owns the RingLead criteria."""
    by_code: dict[str, list[Verdict]] = defaultdict(list)
    for v in verdicts:
        if not v.needs_review:
            continue
        for code in {f.code for f in v.findings}:
            if code in SURVIVORSHIP_RULES:
                by_code[code].append(v)

    ranked = sorted(by_code.items(), key=lambda kv: -len(kv[1]))
    total = len(verdicts)
    covered = len({v.group.group_id for vs in by_code.values() for v in vs})
    generated = datetime.now().strftime("%b %-d, %Y")

    lines = [
        "# RingLead survivorship changes",
        "",
        f"From `{source}` — {total} groups, generated {generated}.",
        "",
        f"These settings changes address **{covered} of {total} groups**. Each is a "
        "one-time configuration change; none require editing groups individually.",
        "",
    ]

    if not ranked:
        lines += ["No systemic settings changes are indicated for this export.", ""]
        return "\n".join(lines)

    for i, (code, vs) in enumerate(ranked, 1):
        setting, change = SURVIVORSHIP_RULES[code]
        examples = vs[:3]
        lines += [
            f"## {i}. {setting}",
            "",
            f"**Affects {len(vs)} groups.** ({code})",
            "",
            f"{change}",
            "",
        ]
        # Only findings that can name a target value get an examples table. Match-criteria
        # and master-selection changes have no per-field correction, so they'd otherwise
        # render an empty table with headers and nothing under them.
        examples_rows = [
            f"| `{v.group.group_id}` | {v.group.surviving.get(c.column) or '(empty)'} "
            f"| **{c.value}** |"
            for v in examples
            for c in v.corrections
            if any(c.column in f.fields for f in v.findings if f.code == code)
        ]
        if examples_rows:
            lines += [
                "| Group | Currently merges to | Should be |",
                "|---|---|---|",
                *examples_rows,
                "",
            ]
        else:
            ids = ", ".join(f"`{v.group.group_id}`" for v in examples)
            lines += [f"Examples: {ids}", ""]

    lines += [
        "---",
        "",
        "## What is *not* covered here",
        "",
        "Groups flagged as possibly-different-people, or where the master choice needs "
        "a judgement call, cannot be fixed by a settings change. Those stay in the "
        "review queue in the HTML report.",
        "",
    ]
    return "\n".join(lines)


def correction_sheet(verdicts: list[Verdict]) -> pd.DataFrame:
    """One row per surviving record needing post-merge field corrections.

    Shaped for Salesforce Data Loader: an Id column plus one column per field to
    update. Only groups with at least one derivable correction appear.
    """
    rows = []
    for v in verdicts:
        corrections = v.corrections
        if not corrections:
            continue
        # Groups needing a master change are no longer held back. Their corrections
        # are computed against the projected survivor, so the Id here is the record
        # that will actually survive -- provided the master change is made first,
        # which the flag column states outright.
        row = {
            "Id": surviving_record_id(v),
            "Group ID": v.group.group_id,
            "Status": v.status,
            "Requires master change first": "YES" if v.master_change else "",
            "Name": v.group.surviving.get(F.F_FULL_NAME),
            "Company": v.group.surviving.get(F.F_COMPANY),
        }
        for c in corrections:
            label = v.group.schema.label(c.column)
            row[label] = c.value
            row[f"[was] {label}"] = v.group.surviving.get(c.column)
        rows.append(row)

    if not rows:
        return pd.DataFrame(columns=["Id", "Group ID", "Status",
                                     "Requires master change first", "Name", "Company"])

    df = pd.DataFrame(rows)
    lead = ["Id", "Group ID", "Status", "Requires master change first", "Name", "Company"]
    rest = sorted(c for c in df.columns if c not in lead)
    # Keep each field beside its [was] column so a reviewer can eyeball the change.
    return df[lead + rest]


def skip_sheet(verdicts: list[Verdict]) -> pd.DataFrame:
    """Groups that should not be merged at all.

    A separate action from everything else in the queue: these are worked in
    RingLead with Skip rather than Merge, so they get their own list to run down
    rather than being buried among groups needing a field corrected.
    """
    rows = []
    for v in verdicts:
        if v.status != "skip":
            continue
        conflicts = [f for f in v.findings if f.code == "identity_conflict"]
        rows.append({
            "Group ID": v.group.group_id,
            "Action": "SKIP — do not merge",
            "Name": v.group.surviving.get(F.F_FULL_NAME),
            "Company": v.group.surviving.get(F.F_COMPANY),
            "Signals that disagree": len(conflicts),
            "Evidence": " | ".join(
                f"{label}: {value}" for f in conflicts for label, value in f.evidence
            ),
            "Record IDs": ", ".join(r.record_id for r in v.group.records),
        })
    cols = ["Group ID", "Action", "Name", "Company", "Signals that disagree",
            "Evidence", "Record IDs"]
    return pd.DataFrame(rows, columns=cols)


def master_change_sheet(verdicts: list[Verdict]) -> pd.DataFrame:
    """Groups where a different record should be the master.

    Kept separate from the correction sheet on purpose: this is a pre-merge change
    made in RingLead, not a Salesforce field update. Applying the two together would
    write field values onto a record that is not going to survive.
    """
    rows = []
    for v in verdicts:
        mc = v.master_change
        if mc is None:
            continue
        rows.append({
            "Group ID": v.group.group_id,
            "Status": v.status,
            "Name": v.group.surviving.get(F.F_FULL_NAME),
            "Company": v.group.surviving.get(F.F_COMPANY),
            "Current master": v.group.master.record_id,
            "Should be master": mc.record.record_id,
            "Why": mc.why,
            "Confidence": "corroborated" if mc.corroborated else "single signal",
            "Field fixes to apply after": len(v.corrections),
        })
    cols = ["Group ID", "Status", "Name", "Company", "Current master",
            "Should be master", "Why", "Confidence", "Field fixes to apply after"]
    return pd.DataFrame(rows, columns=cols)


def correction_summary(verdicts: list[Verdict]) -> Counter:
    """How many records need each field corrected."""
    return Counter(
        v.group.schema.label(c.column) for v in verdicts for c in v.corrections
    )
