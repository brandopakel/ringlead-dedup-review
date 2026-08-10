"""Turn a RingLead resolution export into Group objects.

Export shape (one resolution, "Status: To resolve"):

    Record Action = "master"            -> the winner RingLead picked
    Record Action = ""                  -> a duplicate that will be merged away
    Record Action = "Surviving Record"  -> the "After merge" preview column in the UI

Because the surviving row is included, nothing about the merge outcome has to be
inferred -- what survives and what is destroyed can both be read directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

import pandas as pd

from . import fields as F
from . import normalize as N

MASTER = "master"
SURVIVING = "Surviving Record"


@dataclass
class Record:
    """One Salesforce record inside a group (or the merge preview)."""

    role: str  # "master" | "duplicate" | "surviving"
    data: dict

    def get(self, col: str) -> str:
        return N.clean(self.data.get(col, ""))

    @property
    def lead_id(self) -> str:
        return self.get(F.F_LEAD_ID) or self.get(F.F_LEAD_18_ID)

    @property
    def label(self) -> str:
        return {"master": "Master", "surviving": "After merge"}.get(self.role, "Duplicate")


@dataclass
class Group:
    group_id: str
    surviving: Record
    master: Record
    duplicates: list[Record] = dc_field(default_factory=list)

    @property
    def records(self) -> list[Record]:
        """The real Salesforce records -- master first, then duplicates."""
        return [self.master, *self.duplicates]

    @property
    def size(self) -> int:
        return len(self.records)

    @property
    def columns(self) -> list[str]:
        return list(self.surviving.data.keys())

    def values(self, col: str, include_surviving: bool = False) -> list[str]:
        """Non-blank values for a column across the group's real records."""
        rows = self.records + ([self.surviving] if include_surviving else [])
        return [v for v in (r.get(col) for r in rows) if v]

    def populated_columns(self) -> list[str]:
        """Columns carrying a value on at least one row, in display order."""
        rows = [self.surviving, *self.records]
        cols = [c for c in self.columns if c not in F.META_COLS and any(r.get(c) for r in rows)]
        return sorted(cols, key=lambda c: (F.display_rank(c), F.label(c)))

    def differing_columns(self) -> list[str]:
        """Populated columns whose value is not the same on every row shown."""
        out = []
        for c in self.populated_columns():
            seen = {r.get(c) for r in [self.surviving, *self.records]}
            if len(seen) > 1:
                out.append(c)
        return out

    def lost_values(self, col: str) -> list[tuple[Record, str]]:
        """Values a duplicate holds that the surviving record does not carry.

        This is RingLead's pink "value that is lost during merge" highlight: the
        duplicate has something, and the merge output is not it.
        """
        survivor = self.surviving.get(col)
        out = []
        for rec in self.records:
            v = rec.get(col)
            if v and v != survivor:
                out.append((rec, v))
        return out


def load(path: str) -> tuple[list[Group], pd.DataFrame]:
    """Read the export and assemble it into groups.

    Returns the groups plus the raw frame, so callers can report on the file as a
    whole (row counts, entity type) without re-reading it.
    """
    df = pd.read_csv(path, dtype=str, keep_default_na=False)

    missing = {F.GROUP_ID, F.RECORD_ACTION} - set(df.columns)
    if missing:
        raise ValueError(
            f"{path} does not look like a RingLead resolution export "
            f"(missing column(s): {', '.join(sorted(missing))})"
        )

    df[F.RECORD_ACTION] = df[F.RECORD_ACTION].str.strip()

    groups: list[Group] = []
    for gid, sub in df.groupby(F.GROUP_ID, sort=True):
        master = surviving = None
        dups: list[Record] = []
        for row in sub.to_dict("records"):
            action = N.clean(row.get(F.RECORD_ACTION))
            if action == MASTER:
                master = Record("master", row)
            elif action == SURVIVING:
                surviving = Record("surviving", row)
            else:
                dups.append(Record("duplicate", row))
        if master is None or surviving is None:
            # A group missing either row can't be evaluated; surface it rather
            # than silently dropping a group the reviewer expects to see.
            raise ValueError(
                f"Group {gid} is malformed: "
                f"{'no master row' if master is None else 'no Surviving Record row'}"
            )
        groups.append(Group(group_id=str(gid), surviving=surviving, master=master, duplicates=dups))

    return groups, df
