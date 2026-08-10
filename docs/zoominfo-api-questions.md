# Questions for ZoomInfo / RingLead support

Send as-is. The goal is to find out whether the corrections this tool computes can be
applied programmatically, or whether they have to be applied by hand in the UI.

Answers to 1 and 2 determine everything else — if both are no, the settings changes in
`*_survivorship_changes.md` plus a post-merge Salesforce update are the only paths.

---

Subject: **Operations API access for Cleanse / Deduplicate resolutions**

We run recurring Deduplicate resolutions in Cleanse (Leads, Contacts, Accounts) and
review the groups before merging. We have built internal tooling that reads the
resolution CSV export and identifies groups where the merge preview is wrong — most
often where field-level survivorship picks a value from a former employer rather than
the current one. We would like to apply those corrections without editing each group
by hand in the UI.

1. **Is there an API that can act on a Deduplicate resolution's groups?**
   Specifically, for a group in "To resolve" status, can we programmatically:
   - set which record is the master?
   - override the surviving value for a specific field?
   - merge or skip a group?

2. **If yes, what does access require?** Is it included in our current entitlement, or
   a separate SKU / add-on? Where is the endpoint documentation, and what
   authentication does it use?

3. **Field survivorship options.** In *Configure Fields*, what selection rules are
   available per field? We specifically need:
   - prefer the record most recently modified or enriched (for Title, Account, Mobile)
   - prefer the *oldest* record (for Lead Source / Original Source — first-touch
     attribution should never be overwritten by a newer record)
   - conditional selection, e.g. prefer the email address whose domain matches the
     Company field

   If conditional selection is not supported, is there a supported workaround —
   a normalization step before dedupe, or a computed field we can match on?

4. **Master selection criteria.** Can master selection include "record owner is
   active"? We have leads merging onto records owned by deactivated users.

5. **Match criteria.** Can a match rule require a second identifier — LinkedIn
   Profile, ZoomInfo Contact ID, or Mobile — in addition to name and company? Our
   review found groups matched on name and company alone where the records appear to
   be different people.

6. **Archived values.** The `RingLead Archive` field appears on surviving records after
   a merge. Is the archived payload retrievable via API, and is its format documented?
   If so we may be able to recover overwritten values rather than preventing the
   overwrite.

Thanks.

---

## Notes for us

- Question 3's third bullet is the important one. 102 of 460 groups in our last run
  had this exact defect; if conditional survivorship exists, that bucket disappears.
- Question 6 is worth asking because it changes how urgent the rest is. If the merge
  archives what it destroys and we can read it back, "data lost in merge" becomes
  recoverable rather than permanent, and the review queue can shrink further.
- If the answer to 1 is no, nothing is blocked — `*_corrections.csv` still applies
  every correction via Data Loader after the merge runs. It just needs someone with
  Salesforce write access.
