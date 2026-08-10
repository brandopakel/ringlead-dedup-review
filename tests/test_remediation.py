"""Tests for what gets recommended, and where it is allowed to land.

The safety-critical rule here: a group whose master should change must never appear
in the Salesforce correction sheet. Its surviving Lead ID is about to change, so an
`Id` written from the current preview would target a record that is not going to
survive — updating a soon-to-be-deleted row and leaving the real survivor untouched.
"""

import pytest

from ringlead_qa import fields as F
from ringlead_qa.loader import Group, Record
from ringlead_qa.remediation import correction_sheet, master_change_sheet
from ringlead_qa.rules import Correction, Finding, MasterChange, Verdict, evaluate


# Every logical field the fixtures set, resolved against a Lead schema.
LEAD_COLS = [F.GROUP_ID, F.RECORD_ACTION, F.ENTITY_TYPE] + [
    F.LEAD.prefix + label
    for labels in F.LEAD.fields.values() for label in labels
]
SCHEMA = F.Schema.build("Lead", LEAD_COLS)


def rec(role, **vals):
    """Build a record from logical field names, e.g. rec("master", **{F.F_EMAIL: ...})."""
    data = {F.RECORD_ACTION: role, F.GROUP_ID: "g1"}
    data.update({SCHEMA.col(k) or k: v for k, v in vals.items()})
    return Record(role, data, SCHEMA)


def group(master, dups, surviving):
    return Group(group_id="g1", schema=SCHEMA, surviving=surviving,
                 master=master, duplicates=dups)


@pytest.fixture
def stale_email_group():
    """Survivor works at Intuit but keeps a former employer's address."""
    common = {F.F_COMPANY: "Intuit", F.F_FULL_NAME: "Sangjin Lee", F.F_LINKEDIN: "in/slee"}
    master = rec("master", **common, **{
        F.F_EMAIL: "slee@apple.com", F.F_RECORD_ID: "00Q_MASTER",
        F.F_MODIFIED: "2024-01-01T00:00:00.000Z",
    })
    dup = rec("duplicate", **common, **{
        F.F_EMAIL: "sangjin_lee@intuit.com", F.F_RECORD_ID: "00Q_DUP",
        F.F_MODIFIED: "2026-01-01T00:00:00.000Z",
    })
    surv = rec("surviving", **common, **{
        F.F_EMAIL: "slee@apple.com", F.F_RECORD_ID: "00Q_MASTER",
    })
    return group(master, [dup], surv)


class TestCorrections:
    def test_names_the_right_email(self, stale_email_group):
        v = evaluate(stale_email_group)
        fix = next(c for c in v.corrections if c.column == F.F_EMAIL)
        assert fix.value == "sangjin_lee@intuit.com"

    def test_one_correction_per_column(self):
        """Two findings touching the same column must not both emit a target."""
        v = Verdict(group=None, findings=[
            Finding("a", "critical", "t", "d",
                    corrections=[Correction(F.F_EMAIL, "right@x.com", "critical says so")]),
            Finding("b", "review", "t", "d",
                    corrections=[Correction(F.F_EMAIL, "other@x.com", "review says so")]),
        ])
        assert [c.value for c in v.corrections] == ["right@x.com"]

    def test_employer_fields_move_together(self):
        """An NVIDIA email must not be recommended alongside an Amazon Account.

        Email, Account and Domain all describe one thing -- where the person works
        now. Deciding them by different tests once produced an incoherent survivor,
        which is what this pins.
        """
        common = {F.F_FULL_NAME: "Shruti Koparkar", F.F_COMPANY: "NVIDIA",
                  F.F_LINKEDIN: "in/skoparkar"}
        master = rec("master", **common, **{
            F.F_RECORD_ID: "00Q_M", F.F_EMAIL: "koparkars@amazon.com",
            F.F_ACCOUNT_NAME: "Amazon", F.F_ACCOUNT_ID: "001_AMZN",
            F.F_DOMAIN: "amazon.com",
            # The stale record is also the freshest, so a recency-based account rule
            # stays silent here -- that is exactly how the two rules disagreed.
            F.F_MODIFIED: "2026-07-30T00:00:00.000Z",
        })
        dup = rec("duplicate", **common, **{
            F.F_RECORD_ID: "00Q_D", F.F_EMAIL: "skoparkar@nvidia.com",
            F.F_ACCOUNT_NAME: "NVIDIA", F.F_ACCOUNT_ID: "001_NVDA",
            F.F_DOMAIN: "nvidia.com",
            F.F_MODIFIED: "2026-06-26T00:00:00.000Z",
        })
        surv = rec("surviving", **common, **{
            F.F_RECORD_ID: "00Q_M", F.F_EMAIL: "koparkars@amazon.com",
            F.F_ACCOUNT_NAME: "Amazon", F.F_ACCOUNT_ID: "001_AMZN",
            F.F_DOMAIN: "amazon.com",
        })
        fixes = {c.column: c.value for c in evaluate(group(master, [dup], surv)).corrections}
        assert fixes[F.F_EMAIL] == "skoparkar@nvidia.com"
        assert fixes[F.F_ACCOUNT_NAME] == "NVIDIA", "Account must follow the email"
        assert fixes[F.F_ACCOUNT_ID] == "001_NVDA"
        assert fixes[F.F_DOMAIN] == "nvidia.com"

    def test_agreeing_employer_fields_are_not_restated(self):
        """A correction that changes nothing is noise; only disagreements surface."""
        common = {F.F_FULL_NAME: "Dana Reyes", F.F_COMPANY: "Northwind",
                  F.F_LINKEDIN: "in/dreyes", F.F_ACCOUNT_NAME: "Northwind"}
        master = rec("master", **common, **{
            F.F_RECORD_ID: "00Q_M", F.F_EMAIL: "d.reyes@oldco.com"})
        dup = rec("duplicate", **common, **{
            F.F_RECORD_ID: "00Q_D", F.F_EMAIL: "dreyes@northwind.com"})
        surv = rec("surviving", **common, **{
            F.F_RECORD_ID: "00Q_M", F.F_EMAIL: "d.reyes@oldco.com"})
        cols = {c.column for c in evaluate(group(master, [dup], surv)).corrections}
        assert F.F_EMAIL in cols
        assert F.F_ACCOUNT_NAME not in cols, "already Northwind on both sides"

    def test_blank_targets_are_dropped(self):
        v = Verdict(group=None, findings=[
            Finding("a", "review", "t", "d", corrections=[Correction(F.F_TITLE, "", "no value")]),
        ])
        assert v.corrections == []


class TestMasterChange:
    def test_corroborated_recommendation_wins(self):
        weak = MasterChange(record=rec("duplicate", **{F.F_RECORD_ID: "00Q_WEAK"}),
                            why="one signal", corroborated=False)
        strong = MasterChange(record=rec("duplicate", **{F.F_RECORD_ID: "00Q_STRONG"}),
                              why="two signals", corroborated=True)
        v = Verdict(group=None, findings=[
            Finding("a", "review", "t", "d", master_change=weak),
            Finding("b", "review", "t", "d", master_change=strong),
        ])
        assert v.master_change.record.record_id == "00Q_STRONG"

    def test_absent_when_nothing_recommends_one(self, stale_email_group):
        assert evaluate(stale_email_group).master_change is None


class TestSheetRouting:
    def test_field_fixes_reach_the_correction_sheet(self, stale_email_group):
        v = evaluate(stale_email_group)
        sheet = correction_sheet([v])
        assert list(sheet["Id"]) == ["00Q_MASTER"]
        assert list(sheet["Email"]) == ["sangjin_lee@intuit.com"]
        assert list(sheet["[was] Email"]) == ["slee@apple.com"]

    def test_master_change_holds_the_group_back(self, stale_email_group):
        """The whole point: a changing survivor must not get post-merge field writes."""
        v = evaluate(stale_email_group)
        v.findings.append(Finding(
            "master_stale", "review", "t", "d",
            master_change=MasterChange(record=stale_email_group.duplicates[0],
                                       why="more active", corroborated=True),
        ))
        assert v.corrections, "still has field fixes"
        assert correction_sheet([v]).empty, "but they must not be applied post-merge"

        masters = master_change_sheet([v])
        assert list(masters["Current master"]) == ["00Q_MASTER"]
        assert list(masters["Should be master"]) == ["00Q_DUP"]
        assert list(masters["Field fixes held back"]) == [len(v.corrections)]

    def test_clean_groups_produce_no_rows(self):
        common = {F.F_COMPANY: "Acme", F.F_FULL_NAME: "Jo Doe",
                  F.F_EMAIL: "jo@acme.com", F.F_LINKEDIN: "in/jodoe",
                  F.F_MODIFIED: "2026-01-01T00:00:00.000Z"}
        m = rec("master", **common, **{F.F_RECORD_ID: "00Q_A"})
        d = rec("duplicate", **common, **{F.F_RECORD_ID: "00Q_B"})
        s = rec("surviving", **common, **{F.F_RECORD_ID: "00Q_A"})
        v = evaluate(group(m, [d], s))
        assert correction_sheet([v]).empty
        assert master_change_sheet([v]).empty
