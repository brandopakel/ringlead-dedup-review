"""Turn a RingLead resolution export into Group objects.

Export shape, identical across Leads, Contacts and Accounts:

    Record Action = "master"            -> the winner RingLead picked
    Record Action = ""                  -> a duplicate that will be merged away
    Record Action = "Surviving Record"  -> the "After merge" preview column in the UI

Because the surviving row is included, nothing about the merge outcome has to be
inferred -- what survives and what is destroyed can both be read directly.

Column *names* differ by entity type, so every record reads through a
:class:`~ringlead_qa.fields.Schema` and rules ask for logical fields instead.
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
    schema: F.Schema

    def get(self, key: str) -> str:
        """Read a logical field (``F.F_EMAIL``) or a literal column name.

        A logical field this export doesn't have returns "" rather than raising, so
        rules that need it simply no-op -- an Account export has no mobile number.
        """
        col = self.schema.resolve(key)
        return N.clean(self.data.get(col, "")) if col else ""

    @property
    def record_id(self) -> str:
        return self.get(F.F_RECORD_ID) or self.get(F.F_RECORD_18_ID)

    @property
    def label(self) -> str:
        return {"master": "Master", "surviving": "After merge"}.get(self.role, "Duplicate")


@dataclass
class Group:
    group_id: str
    schema: F.Schema
    surviving: Record
    master: Record
    duplicates: list[Record] = dc_field(default_factory=list)

    @property
    def entity(self) -> str:
        return self.schema.entity

    @property
    def records(self) -> list[Record]:
        """The real Salesforce records -- master first, then duplicates."""
        return [self.master, *self.duplicates]

    @property
    def size(self) -> int:
        return len(self.records)

    def values(self, key: str, include_surviving: bool = False) -> list[str]:
        """Non-blank values for a field across the group's real records."""
        rows = self.records + ([self.surviving] if include_surviving else [])
        return [v for v in (r.get(key) for r in rows) if v]

    def populated_columns(self) -> list[str]:
        """Columns carrying a value on at least one row, in display order."""
        rows = [self.surviving, *self.records]
        cols = [
            c for c in self.schema.columns
            if c not in F.META_COLS and any(r.get(c) for r in rows)
        ]
        return sorted(cols, key=lambda c: (self.schema.display_rank(c), self.schema.label(c)))

    def differing_columns(self) -> list[str]:
        """Populated columns whose value is not the same on every row shown."""
        return [
            c for c in self.populated_columns()
            if len({r.get(c) for r in [self.surviving, *self.records]}) > 1
        ]

    def lost_values(self, key: str) -> list[tuple[Record, str]]:
        """Values a duplicate holds that the surviving record does not carry.

        This is RingLead's pink "value that is lost during merge" highlight.
        """
        survivor = self.surviving.get(key)
        return [
            (rec, v) for rec in self.records
            if (v := rec.get(key)) and v != survivor
        ]


def detect_entity(df: pd.DataFrame, path: str) -> str:
    """Read the entity type off the export, insisting it is unambiguous."""
    if F.ENTITY_TYPE not in df.columns:
        raise ValueError(f"{path} has no '{F.ENTITY_TYPE}' column; is it a RingLead export?")
    kinds = {N.clean(v) for v in df[F.ENTITY_TYPE] if N.clean(v)}
    if not kinds:
        raise ValueError(f"{path} has an empty '{F.ENTITY_TYPE}' column.")
    if len(kinds) > 1:
        raise ValueError(
            f"{path} mixes entity types ({', '.join(sorted(kinds))}). "
            "Export one resolution at a time."
        )
    return kinds.pop()


def load(path: str) -> tuple[list[Group], pd.DataFrame, F.Schema]:
    """Read the export and assemble it into groups.

    Returns the groups, the raw frame, and the resolved schema so callers can report
    on the file as a whole without re-reading it.
    """
    df = pd.read_csv(path, dtype=str, keep_default_na=False)

    missing = {F.GROUP_ID, F.RECORD_ACTION} - set(df.columns)
    if missing:
        raise ValueError(
            f"{path} does not look like a RingLead resolution export "
            f"(missing column(s): {', '.join(sorted(missing))})"
        )

    schema = F.Schema.build(detect_entity(df, path), list(df.columns))
    df[F.RECORD_ACTION] = df[F.RECORD_ACTION].str.strip()

    groups: list[Group] = []
    for gid, sub in df.groupby(F.GROUP_ID, sort=True):
        master = surviving = None
        dups: list[Record] = []
        for row in sub.to_dict("records"):
            action = N.clean(row.get(F.RECORD_ACTION))
            if action == MASTER:
                master = Record("master", row, schema)
            elif action == SURVIVING:
                surviving = Record("surviving", row, schema)
            else:
                dups.append(Record("duplicate", row, schema))
        if master is None or surviving is None:
            # A group missing either row can't be evaluated; surface it rather than
            # silently dropping a group the reviewer expects to see.
            raise ValueError(
                f"Group {gid} is malformed: "
                f"{'no master row' if master is None else 'no Surviving Record row'}"
            )
        groups.append(Group(group_id=str(gid), schema=schema, surviving=surviving,
                            master=master, duplicates=dups))

    return groups, df, schema
