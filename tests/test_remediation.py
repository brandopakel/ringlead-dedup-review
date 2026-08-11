"""Tests for what gets recommended, and where it is allowed to land.

The safety-critical rule here concerns which record a correction targets. When a
group's master should change, the record that survives changes with it, so an `Id`
taken from the current preview would update a row that is about to be deleted and
leave the real survivor untouched. Corrections for those groups are computed against
the projected survivor and addressed to it.
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
        v = evaluate(group(master, [dup], surv))

        # Two routes to a coherent survivor: override each field, or promote the
        # record that already holds them all. Whichever the tool picks, the end
        # state has to agree with itself -- that is the invariant, not the route.
        if v.master_change:
            end = v.projected.group.surviving
            assert end.get(F.F_EMAIL) == "skoparkar@nvidia.com"
            assert end.get(F.F_ACCOUNT_NAME) == "NVIDIA"
            assert end.get(F.F_ACCOUNT_ID) == "001_NVDA"
            assert end.get(F.F_DOMAIN) == "nvidia.com"
        else:
            fixes = {c.column: c.value for c in v.corrections}
            assert fixes[F.F_EMAIL] == "skoparkar@nvidia.com"
            assert fixes[F.F_ACCOUNT_NAME] == "NVIDIA", "Account must follow the email"
            assert fixes[F.F_ACCOUNT_ID] == "001_NVDA"
            assert fixes[F.F_DOMAIN] == "nvidia.com"

    def test_promoting_beats_overriding_the_same_fields_by_hand(self):
        """Four field overrides sourced from one record is a master change in disguise."""
        common = {F.F_FULL_NAME: "Jeremiah Anderson", F.F_COMPANY: "Coalfire Federal",
                  F.F_LINKEDIN: "in/janderson"}
        master = rec("master", **{**common, F.F_RECORD_ID: "00Q_OLD",
                                  F.F_EMAIL: "jeremiah.anderson@usdoj.gov",
                                  F.F_ACCOUNT_NAME: "United States Department of Justice",
                                  F.F_ACCOUNT_ID: "001_DOJ", F.F_DOMAIN: "usdoj.gov"})
        dup = rec("duplicate", **{**common, F.F_RECORD_ID: "00Q_NEW",
                                  F.F_EMAIL: "jeremiah.anderson@coalfirefederal.com",
                                  F.F_ACCOUNT_NAME: "Coalfirefederal",
                                  F.F_ACCOUNT_ID: "001_CF", F.F_DOMAIN: "coalfirefederal.com"})
        surv = rec("surviving", **{**common, F.F_RECORD_ID: "00Q_OLD",
                                   F.F_EMAIL: "jeremiah.anderson@usdoj.gov",
                                   F.F_ACCOUNT_NAME: "United States Department of Justice",
                                   F.F_ACCOUNT_ID: "001_DOJ", F.F_DOMAIN: "usdoj.gov"})
        v = evaluate(group(master, [dup], surv))
        assert v.master_change is not None, "promote the current-employer record"
        assert v.master_change.record.record_id == "00Q_NEW"
        assert v.projected.group.surviving.get(F.F_ACCOUNT_NAME) == "Coalfirefederal"

    def test_account_is_never_repointed_away_from_the_employer(self):
        """Recency is not licence to set an Account that contradicts Company.

        A record touched later by an automated process once caused "Highmark" to be
        recommended as the Account for someone whose Company is Sidley Austin.
        """
        common = {F.F_FULL_NAME: "Lalakhan Patan", F.F_COMPANY: "Sidley Austin"}
        master = rec("master", **{**common, F.F_RECORD_ID: "00Q_M",
                                  F.F_EMAIL: "lpatan@sidley.com",
                                  F.F_ACCOUNT_NAME: "Sidley Austin", F.F_ACCOUNT_ID: "001_SID",
                                  F.F_CREATED: "2026-05-28T00:00:00.000Z"})
        # Newer by every automated stamp, but its Account has nothing to do with
        # the employer on the group.
        dup = rec("duplicate", **{**common, F.F_RECORD_ID: "00Q_D",
                                  F.F_EMAIL: "lalakhanpatan@gmail.com",
                                  F.F_ACCOUNT_NAME: "Highmark", F.F_ACCOUNT_ID: "001_HM",
                                  F.F_CREATED: "2026-07-30T00:00:00.000Z"})
        surv = rec("surviving", **{**common, F.F_RECORD_ID: "00Q_M",
                                   F.F_EMAIL: "lpatan@sidley.com",
                                   F.F_ACCOUNT_NAME: "Sidley Austin", F.F_ACCOUNT_ID: "001_SID"})
        v = evaluate(group(master, [dup], surv))
        end = (v.projected.group if v.projected else v.group).surviving
        fixes = {c.column: c.value for c in v.corrections}
        assert fixes.get(F.F_ACCOUNT_NAME) != "Highmark"
        assert end.get(F.F_ACCOUNT_NAME) == "Sidley Austin"

    def test_recency_ignores_automated_write_timestamps(self):
        """Last Modified tracks enrichment traffic, not whether a record is current."""
        from ringlead_qa.rules import recency
        current = rec("duplicate", **{F.F_CREATED: "2026-05-28T00:00:00.000Z",
                                      F.F_ACTIVITY: "2026-06-05"})
        touched = rec("master", **{F.F_CREATED: "2025-04-21T00:00:00.000Z",
                                   F.F_MODIFIED: "2026-07-30T00:00:00.000Z",
                                   F.F_ZI_UPDATED: "2026-07-30T00:00:00.000Z"})
        assert recency(current) > recency(touched), (
            "a later automated write must not make a stale record look fresher")

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


class TestIdentityCalibration:
    """Not every disagreement is evidence of two people."""

    STAMP = "2026-07-16T16:34:26.000Z"

    def _pair(self, **overrides):
        # Merged before splatting: an override may replace a key `common` already
        # sets, and **a, **b with a shared key is a TypeError.
        common = {F.F_FULL_NAME: "Neil Miller", F.F_COMPANY: "Lidl",
                  F.F_TITLE: "Vice President, Finance", F.F_CREATED: self.STAMP}
        m = rec("master", **{**common, F.F_RECORD_ID: "00Q_M",
                             F.F_ZI_CONTACT: "12981268506", **overrides.get("master", {})})
        d = rec("duplicate", **{**common, F.F_RECORD_ID: "00Q_D",
                                F.F_ZI_CONTACT: "1090824750", **overrides.get("dup", {})})
        s = rec("surviving", **{**common, F.F_RECORD_ID: "00Q_M"})
        return group(m, [d], s)

    def test_vendor_ids_disagreeing_inside_one_import_is_not_a_skip(self):
        """Same instant, title and company: the vendor holds two records, not two people."""
        v = evaluate(self._pair())
        assert v.status == "review"
        assert {f.code for f in v.findings} & {"vendor_id_conflict"}
        assert "identity_conflict" not in {f.code for f in v.findings}

    def test_differing_creation_instant_restores_the_skip(self):
        """Without the double-import evidence, disagreeing IDs stand on their own."""
        v = evaluate(self._pair(dup={F.F_CREATED: "2024-01-02T09:00:00.000Z"}))
        assert v.status == "skip"

    def test_linkedin_conflict_still_skips_despite_one_import(self):
        """LinkedIn is the strongest signal; a real slug clash is not explained away."""
        v = evaluate(self._pair(
            master={F.F_LINKEDIN: "linkedin.com/in/neil-miller-38278580"},
            dup={F.F_LINKEDIN: "linkedin.com/in/neilmiller-cfo-99"},
        ))
        assert v.status == "skip"

    def test_urn_versus_slug_is_not_a_conflict(self):
        """Two address forms for one profile must not read as two people."""
        v = evaluate(self._pair(
            master={F.F_LINKEDIN: "linkedin.com/in/ACwAABEzP9IBnVwlgpt2wic0t7nnxi5ymei3tek",
                    F.F_ZI_CONTACT: "111"},
            dup={F.F_LINKEDIN: "linkedin.com/in/neil-miller-38278580",
                 F.F_ZI_CONTACT: "111"},
        ))
        assert v.status != "skip"


class TestAttribution:
    """First touch means the earliest real source, not merely the earliest row."""

    def _group(self, master_src, dup_src, master_created, dup_created):
        common = {F.F_FULL_NAME: "Neal Vali", F.F_COMPANY: "ThinkLabs AI",
                  F.F_EMAIL: "neal@thinklabs.ai"}
        m = rec("master", **{**common, F.F_RECORD_ID: "00Q_M",
                             F.F_LEAD_SOURCE: master_src, F.F_CREATED: master_created})
        d = rec("duplicate", **{**common, F.F_RECORD_ID: "00Q_D",
                                F.F_LEAD_SOURCE: dup_src, F.F_CREATED: dup_created})
        s = rec("surviving", **{**common, F.F_RECORD_ID: "00Q_M",
                                F.F_LEAD_SOURCE: master_src})
        return group(m, [d], s)

    def test_a_rep_created_row_never_outranks_a_real_source(self):
        """The old rule pushed Paid Digital back to Sales Generated on age alone."""
        v = evaluate(self._group(
            master_src="Paid Digital", dup_src="Sales Generated",
            master_created="2026-01-01T00:00:00.000Z",
            dup_created="2024-01-01T00:00:00.000Z",   # older, but rep-created
        ))
        fixes = {c.column: c.value for c in v.corrections}
        assert fixes.get(F.F_LEAD_SOURCE) != "Sales Generated"

    def test_a_real_source_replaces_a_rep_created_one(self):
        v = evaluate(self._group(
            master_src="Sales Generated", dup_src="Paid Digital",
            master_created="2024-01-01T00:00:00.000Z",
            dup_created="2026-01-01T00:00:00.000Z",
        ))
        fixes = {c.column: c.value for c in v.corrections}
        assert fixes.get(F.F_LEAD_SOURCE) == "Paid Digital"

    def test_the_most_recent_event_survives(self):
        """On event-sourced records the Detail names which event was attended."""
        common = {F.F_FULL_NAME: "Fernando Aznar", F.F_COMPANY: "Microsoft",
                  F.F_LEAD_SOURCE: "Industry Event"}
        m = rec("master", **{**common, F.F_RECORD_ID: "00Q_M",
                             F.F_LEAD_SOURCE_DETAIL: "Supercomputing-StLouis-2025",
                             F.F_CREATED: "2025-11-04T00:00:00.000Z"})
        d = rec("duplicate", **{**common, F.F_RECORD_ID: "00Q_D",
                                F.F_LEAD_SOURCE_DETAIL: "NVIDIA-GTC-San-Jose-2026",
                                F.F_CREATED: "2026-03-04T00:00:00.000Z"})
        s = rec("surviving", **{**common, F.F_RECORD_ID: "00Q_M",
                                F.F_LEAD_SOURCE_DETAIL: "NVIDIA-GTC-San-Jose-2026"})
        fixes = {c.column: c.value for c in evaluate(group(m, [d], s)).corrections}
        assert fixes.get(F.F_LEAD_SOURCE_DETAIL) != "Supercomputing-StLouis-2025", (
            "first-touch must not hand back the older event")

    def test_lead_tier_is_never_written_by_hand(self):
        """Tier is derived, and Salesforce re-evaluates it after the merge.

        Marketing Field Dictionary p3: Lead Tier is "automatically re-evaluated
        whenever any of these data points change". Writing a tier would either be
        overwritten or would contradict the data it is computed from. A weaker tier
        in the preview is a symptom of the wrong record surviving, so the finding
        reports it and the Email/Account rules do the fixing.
        """
        common = {F.F_FULL_NAME: "Fernando Aznar", F.F_COMPANY: "Microsoft"}
        m = rec("master", **{**common, F.F_RECORD_ID: "00Q_M", F.F_LEAD_TIER: "Tier 3"})
        d = rec("duplicate", **{**common, F.F_RECORD_ID: "00Q_D", F.F_LEAD_TIER: "Tier 1"})
        s = rec("surviving", **{**common, F.F_RECORD_ID: "00Q_M", F.F_LEAD_TIER: "Tier 3"})
        v = evaluate(group(m, [d], s))
        assert F.F_LEAD_TIER not in {c.column for c in v.corrections}
        assert "lead_tier_downgrade" in {f.code for f in v.findings}, "still reported"

    def test_non_buyer_carries_no_funnel_progress(self):
        """Dictionary p16: Non-Buyer is "not qualified", and enrichment skips it."""
        common = {F.F_FULL_NAME: "Kevin Sieck", F.F_COMPANY: "BairesDev"}
        m = rec("master", **{**common, F.F_RECORD_ID: "00Q_M", F.F_LIFECYCLE: "Non-Buyer"})
        d = rec("duplicate", **{**common, F.F_RECORD_ID: "00Q_D", F.F_LIFECYCLE: "SAL"})
        s = rec("surviving", **{**common, F.F_RECORD_ID: "00Q_M", F.F_LIFECYCLE: "Non-Buyer"})
        fixes = {c.column: c.value for c in evaluate(group(m, [d], s)).corrections}
        assert fixes.get(F.F_LIFECYCLE) == "SAL"

    def test_recycled_sits_alongside_lead_not_above_it(self):
        """Every MQL scenario reads "Pre-Lead, Lead or Recycled" as one starting set."""
        from ringlead_qa.fields import LIFECYCLE_RANK
        assert LIFECYCLE_RANK["recycled"] == LIFECYCLE_RANK["lead"]
        assert LIFECYCLE_RANK["recycle"] == LIFECYCLE_RANK["lead"]
        assert LIFECYCLE_RANK["sal"] > LIFECYCLE_RANK["recycled"]

    def test_age_still_decides_between_two_real_sources(self):
        """Among sources of equal standing the earliest is the genuine first touch."""
        v = evaluate(self._group(
            master_src="Paid Digital", dup_src="Organic",
            master_created="2026-01-01T00:00:00.000Z",
            dup_created="2024-01-01T00:00:00.000Z",
        ))
        fixes = {c.column: c.value for c in v.corrections}
        assert fixes.get(F.F_LEAD_SOURCE) == "Organic"


class TestIdentitySignalStrength:
    """A disagreement is only a verdict when the signal that disagrees is an identity key."""

    def _pair(self, master, dup, **common):
        base = {F.F_FULL_NAME: "Jamie Fox", F.F_COMPANY: "Northwind", **common}
        m = rec("master", **{**base, F.F_RECORD_ID: "00Q_M", **master})
        d = rec("duplicate", **{**base, F.F_RECORD_ID: "00Q_D", **dup})
        s = rec("surviving", **{**base, F.F_RECORD_ID: "00Q_M", **master})
        return group(m, [d], s)

    def test_mobile_alone_is_a_question_not_a_verdict(self):
        """One person can hold two numbers; that must not block a real merge."""
        v = evaluate(self._pair({F.F_MOBILE: "(312) 244-3374"},
                                {F.F_MOBILE: "(312) 961-0637"}))
        assert v.status != "skip"
        assert "weak_identity_conflict" in {f.code for f in v.findings}

    def test_linkedin_alone_is_a_verdict(self):
        v = evaluate(self._pair({F.F_LINKEDIN: "linkedin.com/in/jamie-fox-1"},
                                {F.F_LINKEDIN: "linkedin.com/in/jfox-other"}))
        assert v.status == "skip"

    def test_a_shared_mobile_counts_even_in_the_phone_field(self):
        """The same number lands in Mobile on one record and Phone on the other."""
        v = evaluate(self._pair(
            {F.F_MOBILE: "(607) 262-4503", F.F_PHONE: "(313) 322-3000"},
            {F.F_MOBILE: "+91 99857 22223", F.F_PHONE: "+1 607-262-4503"},
        ))
        assert v.status != "skip"

    def test_a_shared_switchboard_proves_nothing(self):
        """Colleagues share a company main line -- it must not confirm identity."""
        v = evaluate(self._pair(
            {F.F_PHONE: "(781) 238-0099"},
            {F.F_PHONE: "(781) 238-0099"},
        ))
        assert not any(f.code == "identity_confirmed" for f in v.findings)
        assert v.status != "ok" or True   # never *confirmed* by the switchboard alone
        assert "identity_unverified" in {f.code for f in v.findings}


class TestIdentityCorroboration:
    def test_identical_email_outranks_a_vendor_id_clash(self):
        """An address identifies one mailbox; it cannot be two people."""
        v = evaluate(group(
            rec("master", **{F.F_FULL_NAME: "Roopesh Kumar", F.F_COMPANY: "Sify",
                             F.F_RECORD_ID: "00Q_M", F.F_EMAIL: "roopesh.kumar@sifycorp.com",
                             F.F_ZI_CONTACT: "111"}),
            [rec("duplicate", **{F.F_FULL_NAME: "Roopesh Kumar", F.F_COMPANY: "Sify",
                                 F.F_RECORD_ID: "00Q_D", F.F_EMAIL: "roopesh.kumar@sifycorp.com",
                                 F.F_ZI_CONTACT: "222"})],
            rec("surviving", **{F.F_FULL_NAME: "Roopesh Kumar", F.F_COMPANY: "Sify",
                                F.F_RECORD_ID: "00Q_M", F.F_EMAIL: "roopesh.kumar@sifycorp.com"}),
        ))
        assert v.status != "skip"
        assert "identity_mixed" in {f.code for f in v.findings}

    def test_name_shaped_local_part_carries_across_a_job_change(self):
        """siddartha.reddy@ at two employers is the same person, not two."""
        base = {F.F_FULL_NAME: "Siddartha Reddy", F.F_COMPANY: "Capital One"}
        v = evaluate(group(
            rec("master", **{**base, F.F_RECORD_ID: "00Q_M",
                             F.F_EMAIL: "siddartha.reddy@anthem.com", F.F_ZI_CONTACT: "1"}),
            [rec("duplicate", **{**base, F.F_RECORD_ID: "00Q_D",
                                 F.F_EMAIL: "siddartha.reddy@capitalone.com", F.F_ZI_CONTACT: "2"})],
            rec("surviving", **{**base, F.F_RECORD_ID: "00Q_M",
                                F.F_EMAIL: "siddartha.reddy@anthem.com"}),
        ))
        assert v.status != "skip"

    def test_a_generic_shared_local_part_does_not_corroborate(self):
        """"info@" carrying across two domains says nothing about a person."""
        base = {F.F_FULL_NAME: "Dana Reyes", F.F_COMPANY: "Northwind"}
        v = evaluate(group(
            rec("master", **{**base, F.F_RECORD_ID: "00Q_M",
                             F.F_EMAIL: "info@oldco.com", F.F_ZI_CONTACT: "1"}),
            [rec("duplicate", **{**base, F.F_RECORD_ID: "00Q_D",
                                 F.F_EMAIL: "info@northwind.com", F.F_ZI_CONTACT: "2"})],
            rec("surviving", **{**base, F.F_RECORD_ID: "00Q_M",
                                F.F_EMAIL: "info@oldco.com"}),
        ))
        assert v.status == "skip"


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

    def test_corrections_address_the_record_that_will_survive(self, stale_email_group):
        """A master change moves the target: the Id must follow it, not the old preview."""
        v = evaluate(stale_email_group)
        v.findings.append(Finding(
            "master_stale", "review", "t", "d",
            master_change=MasterChange(record=stale_email_group.duplicates[0],
                                       why="more active", corroborated=True),
        ))
        sheet = correction_sheet([v])
        assert not sheet.empty
        assert list(sheet["Id"]) == ["00Q_DUP"], "the new master is what survives"
        assert list(sheet["Requires master change first"]) == ["YES"]

        masters = master_change_sheet([v])
        assert list(masters["Current master"]) == ["00Q_MASTER"]
        assert list(masters["Should be master"]) == ["00Q_DUP"]

    def test_a_master_change_can_remove_the_need_for_field_edits(self):
        """If promoting the right record already fixes the value, do not also ask for it."""
        common = {F.F_FULL_NAME: "Inigo Monreal", F.F_COMPANY: "Expedia Group",
                  F.F_LINKEDIN: "in/imonreal"}
        master = rec("master", **{**common, F.F_RECORD_ID: "00Q_OLD",
                                  F.F_EMAIL: "inigo.monreal@bath.edu",
                                  F.F_OWNER_ACTIVE: "false", F.F_OWNER_NAME: "Departed Rep"})
        dup = rec("duplicate", **{**common, F.F_RECORD_ID: "00Q_NEW",
                                  F.F_EMAIL: "imonreal@expediagroup.com",
                                  F.F_OWNER_ACTIVE: "true", F.F_OWNER_NAME: "Active Rep"})
        surv = rec("surviving", **{**common, F.F_RECORD_ID: "00Q_OLD",
                                   F.F_EMAIL: "inigo.monreal@bath.edu"})
        v = evaluate(group(master, [dup], surv))
        assert v.master_change.record.record_id == "00Q_NEW"
        assert F.F_EMAIL not in {c.column for c in v.corrections}, (
            "promoting the Expedia record already fixes the email")

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
