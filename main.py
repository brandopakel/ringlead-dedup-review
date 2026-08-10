"""Triage a RingLead deduplication resolution export.

Reads the CSV RingLead produces for a resolution, evaluates every group against the
merge-quality rules, and writes a self-contained HTML report so only the groups that
actually need a human get opened.

    python main.py                          # newest export in data/
    python main.py path/to/export.csv
    python main.py --open                   # write the report and open it
    python main.py --csv-out triage.csv     # also dump a flat triage sheet
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

from ringlead_qa import fields as F
from ringlead_qa.loader import load
from ringlead_qa.remediation import (
    correction_sheet,
    master_change_sheet,
    survivorship_changelist,
)
from ringlead_qa.report import render
from ringlead_qa.rules import evaluate

DATA_DIR = Path("data")
REPORT_DIR = Path("reports")


def newest_export() -> Path:
    """Most recently modified CSV in data/."""
    candidates = sorted(DATA_DIR.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        sys.exit(f"No CSV found in {DATA_DIR}/. Pass a path, or drop the export there.")
    return candidates[0]


def triage_frame(verdicts) -> pd.DataFrame:
    """Flat one-row-per-group sheet, for filtering in Excel or Sheets."""
    rows = []
    for v in verdicts:
        g = v.group
        rows.append({
            "Group ID": g.group_id,
            "Status": v.status,
            "Headline": v.headline,
            "Records": g.size,
            "Name": g.surviving.get(F.F_FULL_NAME),
            "Company": g.surviving.get(F.F_COMPANY),
            "Surviving Email": g.surviving.get(F.F_EMAIL),
            "Master Record ID": g.master.record_id,
            "Findings": "; ".join(f.title for f in v.findings if f.severity != "contributor"),
            "Codes": ",".join(sorted({f.code for f in v.findings})),
            "Contributor Score": v.contributor_score,
        })
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("csv", nargs="?", type=Path, help="RingLead export (default: newest in data/)")
    ap.add_argument("-o", "--out", type=Path, help="HTML report path")
    ap.add_argument("--csv-out", type=Path, help="also write a flat triage CSV")
    ap.add_argument("--open", action="store_true", help="open the report when done")
    ap.add_argument("--schema", action="store_true",
                    help="print how logical fields resolved for this export, then exit")
    args = ap.parse_args()

    src = args.csv or newest_export()
    if not src.exists():
        sys.exit(f"No such file: {src}")

    groups, df, schema = load(str(src))
    if args.schema:
        print(schema.report())
        return 0

    verdicts = [evaluate(g) for g in groups]
    counts = Counter(v.status for v in verdicts)
    queue = counts["critical"] + counts["review"]

    out = args.out or REPORT_DIR / f"{src.stem}_qa.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(verdicts, source=src.name, total_rows=len(df)), encoding="utf-8")

    # Handoff artifacts, written on every run: one for whoever owns the RingLead
    # criteria, one for whoever has Salesforce write access.
    changelist = out.with_name(f"{src.stem}_survivorship_changes.md")
    changelist.write_text(survivorship_changelist(verdicts, source=src.name), encoding="utf-8")

    corrections = correction_sheet(verdicts)
    corrections_path = out.with_name(f"{src.stem}_corrections.csv")
    corrections.to_csv(corrections_path, index=False)

    masters = master_change_sheet(verdicts)
    masters_path = out.with_name(f"{src.stem}_master_changes.csv")
    masters.to_csv(masters_path, index=False)

    if args.csv_out:
        args.csv_out.parent.mkdir(parents=True, exist_ok=True)
        triage_frame(verdicts).to_csv(args.csv_out, index=False)

    pct = round(counts["ok"] / len(verdicts) * 100) if verdicts else 0
    print(f"\n  {src.name}")
    print(f"  {schema.entity} · {len(df):,} rows · {len(groups)} groups")
    if schema.unresolved:
        print(f"  {len(schema.unresolved)} field(s) not found in this export "
              f"— run --schema for detail")
    print()
    print(f"  {counts['critical']:>4}  needs a fix")
    print(f"  {counts['review']:>4}  needs review")
    print(f"  {counts['ok']:>4}  clean, skip  ({pct}%)\n")
    print(f"  Review {queue} groups instead of {len(groups)}.\n")
    print(f"  {len(masters):>4}  groups need a different master (fix in RingLead first)")
    print(f"  {len(corrections):>4}  records need a field corrected after merge\n")
    print(f"  report   {out}")
    print(f"  changes  {changelist}")
    print(f"  masters  {masters_path}")
    print(f"  fixes    {corrections_path}")
    if args.csv_out:
        print(f"  triage   {args.csv_out}")
    print()

    if args.open:
        subprocess.run(["open", str(out)], check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
