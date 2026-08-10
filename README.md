# RingLead merge QA

Triages a RingLead deduplication resolution export so only the groups that actually
need a human get opened. On the first real export it cut a 460-group manual review
down to 222, and named nine systemic rule changes covering 218 groups — worth more
than the review itself.

## Running it

Every run, once set up:

```bash
cd ~/ringlead-dedup-review
source .venv/bin/activate       # prompt gains a (.venv) prefix
python main.py --open           # newest export in data/, opens the report
```

Drop the RingLead CSV export in `data/` first. The newest CSV there is used unless
you pass a path.

```bash
python main.py                        # newest export in data/
python main.py data/Accounts.csv      # a specific export
python main.py --csv-out triage.csv   # also write a flat one-row-per-group sheet
python main.py --schema               # show how fields resolved, then exit
python -m pytest                      # 57 tests
```

Without activating the venv, call its interpreter directly — same thing:

```bash
.venv/bin/python main.py --open
```

## First-time setup

`.venv/` is deliberately not in git, so a fresh clone needs it built once:

```bash
git clone https://github.com/brandopakel/ringlead-dedup-review.git
cd ringlead-dedup-review
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
mkdir -p data                   # put the RingLead export here
python main.py --open
```

Needs Python 3.10 or newer (`python3 --version` to check).

## Reading the report

Findings sort worst-first, and the four statuses mean four different actions:

| Status | What to do in RingLead |
| --- | --- |
| **Skip** | Do **not** merge. Independent identifiers disagree, so the records are probably different people. Confirm, then use Skip. |
| **Fix** | Merge, but correct the listed fields — the report names the value each should be. |
| **Review** | Can't be settled from the data. Open it and decide. |
| **Clean** | Nothing to do. |

Each expanded group shows its **Group ID** in a click-to-select box, so it can be
pasted straight into RingLead's search.

- `j` / `k` — move between groups, `Enter` — expand, `x` — mark reviewed, `/` — search
- Progress is saved in your browser per export file, so you can stop and resume
- **Hide reviewed** shrinks the queue as you work

`data/`, `reports/`, and every `*.csv` are gitignored — the exports are real
Salesforce PII and must never be committed.

## What every run produces

| File | For | Contents |
| --- | --- | --- |
| `*_qa.html` | you | the review queue, with a **Should be** column per flagged group |
| `*_do_not_merge.csv` | you | groups that should be **skipped** in RingLead, not merged — the records are probably different people |
| `*_survivorship_changes.md` | whoever owns the RingLead criteria | settings to change once, ranked by how many groups each clears |
| `*_master_changes.csv` | whoever owns the RingLead criteria | groups where a **different record should be master** — fix in RingLead *before* merging |
| `*_corrections.csv` | whoever has Salesforce write access | one row per surviving Lead ID with the fields to correct after the merge, Data Loader-shaped |

### Master changes are sequenced before field corrections

A correction edits a field on the record that survives. A **master change** changes
*which record survives* — the surviving Lead ID itself changes, and every field
correction computed against the current merge preview goes stale.

So groups recommending a new master are deliberately **held back** from
`*_corrections.csv`. Writing those rows would target a record that is about to be
deleted, updating the wrong row and leaving the real survivor untouched. The order is:

1. Apply the master changes in RingLead.
2. Re-export and re-run this tool.
3. Apply `*_corrections.csv` after the merge.

`master_change_sheet` reports how many field fixes each held-back group is carrying,
and each recommendation is marked `corroborated` (independent signals agree) or
`single signal` (confirm before changing). `tests/test_remediation.py` pins this
routing.

**RingLead's "After merge" column is a prediction, not a target.** It shows what *will*
happen, defects included — on one sample group it shows `slee@apple.com` surviving for
someone who works at Intuit. Wherever the correct value is derivable from the data, the
report states it in a separate **Should be** column and a per-group "Set these on the
surviving record" block. Where it isn't derivable — a possible false-positive match, a
master choice needing judgement — no target is offered, because guessing there would be
worse than saying nothing.

## What the export contains

RingLead emits three rows per group, which is what makes this checkable without
touching Salesforce:

| `Record Action` | Meaning |
| --- | --- |
| `master` | the record RingLead picked to survive |
| *(blank)* | a duplicate that will be merged away |
| `Surviving Record` | the merge preview — the "After merge" column in the UI |

Because the merge result is in the file, what survives and what is destroyed are both
read directly rather than inferred.

## How groups are triaged

Two independent questions get asked of every group.

**Is this one person?** Name and company alone can't answer that — in the sample
export, 293 of 460 groups had completely different corporate email domains, because
ZoomInfo overwrites `Company`/`Title` with the person's *current* employer while
`Email`/`Domain`/`Account` stay frozen at capture time. So identity is judged on
LinkedIn slug, ZoomInfo Contact ID, mobile, and exact email instead. Those have 77–88%
coverage and agree overwhelmingly (LinkedIn: 374 agree / 4 disagree), which is what
makes most groups safely skippable.

**Is the merge output right?** Independent of identity: does the survivor keep the
current employer's email, the freshest job title, the furthest funnel stage, the
active owner.

**How recency is used.** Most Recent Activity Date is the intuitive freshness signal
but it appears on only 34% of records — in 212 of 460 groups *neither* record has one,
so it cannot carry weight alone. Freshness is therefore a composite of ZoomInfo Last
Updated → Enrich Date → Last Modified → Created, which has ~100% coverage.

Recency is applied per field class, not globally. Fields describing **current state**
(email, title, company, Account link, mobile) should take the freshest value; fields
describing **history** (`HISTORICAL_FIELDS` in `fields.py` — Lead Source, Original
Source, first-touch) should take the *oldest*, and overwriting them is its own defect.
Raw "the fresher record's value was discarded" fires on 316 of 460 groups, so it is
never a trigger on its own.

Findings carry one of three severities:

- **critical** — demonstrably wrong output (e.g. the survivor works at Intuit but
  keeps `slee@apple.com` while discarding `sangjin_lee@intuit.com`)
- **review** — unresolvable from the data; a person has to look
- **contributor** — suspicious but routine; only matters stacked with others

A group enters the queue on any critical or review finding, or when contributors pass
`REVIEW_THRESHOLD` (`ringlead_qa/rules.py`).

The weighting rule of thumb: **a contributor that fires on more than a quarter of the
file is describing the routine merge shape, not evidence of a problem**, so it gets
weight 0 — it still renders as context but can never push a group into the queue. In
the sample export that zeroes `owner_change` (250/460), `original_source_overwritten`
(169), `account_conflict` (160) and `high_value_loss` (135). Skipping this discipline
flags over half the file and defeats the tool.

## Reading the report

The colour language matches RingLead's own, so it reads the same way the UI does:

- green fill — the value that survives the merge
- pink strikethrough — a value destroyed by the merge
- green border — the master record's column

Tables open showing only fields that differ; the toggle expands to everything. Clean
groups render a short identity table for spot-checking rather than the full field set.

The **Systemic patterns** panel at the top is usually the highest-value part. When one
finding fires on 100+ groups, that is a survivorship-rule problem, not 100 separate
mistakes — fixing the rule in RingLead is cheaper than fixing the groups.

## Layout

```
main.py                  CLI
ringlead_qa/fields.py    field catalog — tiers, lifecycle ranking, display order
ringlead_qa/normalize.py comparison primitives (email, domain, phone, LinkedIn, names)
ringlead_qa/loader.py    CSV -> Group objects
ringlead_qa/rules.py     the checks, severities, and scoring
ringlead_qa/report.py    self-contained HTML
tests/                   pytest — run with `python -m pytest`
```

## Tuning

Most adjustments are data, not code:

- **Field importance** — `HIGH_VALUE`, `ROUTING`, `SYSTEM_NOISE` in `fields.py`.
  A field in `SYSTEM_NOISE` never counts as data loss and never reaches the report.
- **Funnel order** — `LIFECYCLE_RANK` in `fields.py` drives regression detection.
  `Recycle` and `Non-Buyer` deliberately rank equal to `Lead`, not above it.
- **Queue size** — `REVIEW_THRESHOLD` in `rules.py`, and the per-finding `weight`s.
- **Free/role email lists** — `normalize.py`.

Run `python -m pytest` after changing `normalize.py`; those tests pin the comparison
behaviour that decides which groups get auto-approved.

## Known limits

- Domain aliases that share no letters with the company name can't be inferred
  (`Fortescue` / `fmgl.com.au`). These surface as review items rather than being
  silently matched.
- Title freshness uses ZoomInfo enrichment dates as the recency proxy, falling back to
  Last Modified Date. A record that was never enriched can't win a freshness contest.
- Only Lead exports have been exercised. Account and Contact resolutions use the same
  three-row structure, but their field names differ, so `fields.py` needs an
  equivalent catalog per entity type before the rules mean anything there.
