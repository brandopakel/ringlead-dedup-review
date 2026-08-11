"""Field catalog, resolved per entity type.

RingLead exports Leads, Contacts and Accounts in the same three-row shape but with
different column names -- `Salesforce Lead: Email` vs `Salesforce Contact: Email`, and
an Account has no email at all. So the rules never name a column directly. They ask for
a *logical* field (``EMAIL``, ``FULL_NAME``) and a :class:`Schema` resolves it against
the columns the file actually has.

Two consequences worth knowing:

* An unresolved field reads as empty, so rules that depend on it no-op rather than
  crash. An Account export simply skips the checks that need a mobile number.
* What could not be resolved is reported rather than swallowed -- ``Schema.unresolved``
  and ``python main.py --schema`` say exactly which logical fields found no column,
  which is how a new export's naming gets fixed quickly instead of failing silently.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

# --- Structural columns RingLead adds to every export -------------------------
GROUP_ID = "Group ID"
RECORD_ACTION = "Record Action"
ENTITY_TYPE = "Entity Type"

META_COLS = {
    GROUP_ID,
    ENTITY_TYPE,
    RECORD_ACTION,
    "Group Status",
    "Merge Occurred",
    "Salesforce Error",
    "Salesforce Status Code",
    "Error Description",
}

# --- Logical field names ------------------------------------------------------
# Rules reference these, never raw column names.
F_RECORD_ID = "record_id"
F_RECORD_18_ID = "record_18_id"
F_RECORD_NUMBER = "record_number"
F_EMAIL = "email"
F_DOMAIN = "domain"
F_COMPANY_DOMAIN = "company_domain"
F_COMPANY = "company"
F_TITLE = "title"
F_FULL_NAME = "full_name"
F_FIRST_NAME = "first_name"
F_LAST_NAME = "last_name"
F_LINKEDIN = "linkedin"
F_ZI_CONTACT = "zi_contact_id"
F_ZI_COMPANY = "zi_company_id"
F_ZI_UPDATED = "zi_last_updated"
F_ZI_ENRICH_DATE = "zi_enrich_date"
F_MOBILE = "mobile"
F_PHONE = "phone"
F_WEBSITE = "website"
F_ACCOUNT_ID = "account_id"
F_ACCOUNT_NAME = "account_name"
F_BILLING_STREET = "billing_street"
F_BILLING_CITY = "billing_city"
F_LIFECYCLE = "lifecycle"
F_LEAD_STATUS = "lead_status"
F_LEAD_TIER = "lead_tier"
F_OWNER_NAME = "owner_name"
F_OWNER_ACTIVE = "owner_active"
F_AE_OWNER = "ae_owner"
F_BDR_OWNER = "bdr_owner"
F_ACTIVITY = "activity"
F_LAST_ACTIVITY = "last_activity"
F_CREATED = "created"
F_MODIFIED = "modified"
F_NOTES = "notes"
F_DESCRIPTION = "description"
F_UNQUALIFIED = "unqualified_reason"
F_LEAD_SOURCE = "lead_source"
F_LEAD_SOURCE_DETAIL = "lead_source_detail"

# Fields shared across every entity type. Values are candidate column labels, tried
# in order -- the first that exists in the file wins.
_COMMON = {
    F_EMAIL: ["Email"],
    F_TITLE: ["Title"],
    F_FULL_NAME: ["Full Name", "Name"],
    F_FIRST_NAME: ["First Name"],
    F_LAST_NAME: ["Last Name"],
    F_LINKEDIN: ["LinkedIn Profile", "LinkedIn", "LinkedIn URL"],
    F_ZI_CONTACT: ["ZoomInfo Contact ID"],
    F_ZI_COMPANY: ["ZoomInfo Company ID"],
    F_ZI_UPDATED: ["ZoomInfo Last Updated"],
    F_ZI_ENRICH_DATE: ["ZoomInfo Enrich Date"],
    F_MOBILE: ["Mobile", "Mobile Phone"],
    F_PHONE: ["Phone"],
    F_WEBSITE: ["Website"],
    F_DOMAIN: ["Domain"],
    F_COMPANY_DOMAIN: ["Company Domain Name"],
    F_LIFECYCLE: ["Lifecycle Stage"],
    F_LEAD_TIER: ["Lead Tier"],
    F_OWNER_NAME: ["Owner :: Name"],
    F_OWNER_ACTIVE: ["Owner :: IsActive"],
    F_AE_OWNER: ["AE Owner :: Name"],
    F_BDR_OWNER: ["BDR Owner :: Name"],
    F_ACTIVITY: ["Most Recent Activity Date"],
    F_LAST_ACTIVITY: ["Last Activity"],
    F_CREATED: ["Created Date"],
    F_MODIFIED: ["Last Modified Date"],
    F_LEAD_SOURCE: ["Lead Source"],
    F_LEAD_SOURCE_DETAIL: ["Lead Source Detail"],
    F_NOTES: ["Notes"],
    F_DESCRIPTION: ["Description"],
}

# --- Per-entity specifications ------------------------------------------------
# `identity` lists the fields that prove two records are the same thing, in the
# order they should be reported. `historical` lists fields where the OLDEST value is
# correct and a newer one overwriting it is a defect.


@dataclass(frozen=True)
class EntitySpec:
    prefix: str
    fields: dict[str, list[str]]
    identity: list[tuple[str, str, str, str]]  # (logical, normalizer, name, strength)
    historical: list[str]
    noise_labels: frozenset[str] = frozenset()


LEAD = EntitySpec(
    prefix="Salesforce Lead: ",
    fields={
        **_COMMON,
        F_RECORD_ID: ["Lead ID"],
        F_RECORD_18_ID: ["Lead 18 ID"],
        F_RECORD_NUMBER: ["Lead Number"],
        F_COMPANY: ["Company"],
        F_ACCOUNT_ID: ["Account :: ID"],
        F_ACCOUNT_NAME: ["Account :: Name"],
        F_LEAD_STATUS: ["Lead Status (Deprecated)", "Lead Status", "Status"],
        F_UNQUALIFIED: ["Unqualified Reason"],
    },
    identity=[
        # "key" identifiers name one person and are minted once; "weak" ones are
        # attributes a person can legitimately have two of, so a disagreement there
        # is a question rather than a verdict.
        (F_LINKEDIN, "linkedin", "LinkedIn profile", "key"),
        (F_ZI_CONTACT, "lower", "ZoomInfo Contact ID", "key"),
        (F_MOBILE, "phone_digits", "mobile number", "weak"),
    ],
    historical=["Lead Source", "Lead Source Detail", "Original Source",
                "First Touch Conversion Action", "Inbound Date"],
)

CONTACT = EntitySpec(
    prefix="Salesforce Contact: ",
    fields={
        **_COMMON,
        F_RECORD_ID: ["Contact ID"],
        F_RECORD_18_ID: ["Contact 18 ID"],
        F_RECORD_NUMBER: ["Contact Number"],
        # A Contact's employer is its parent Account, not a free-text Company field.
        F_COMPANY: ["Account :: Name", "Account Name", "Company"],
        F_ACCOUNT_ID: ["Account :: ID", "Account ID"],
        F_ACCOUNT_NAME: ["Account :: Name", "Account Name"],
        F_LEAD_STATUS: ["Contact Status", "Status"],
        F_UNQUALIFIED: ["Unqualified Reason"],
    },
    identity=[
        (F_LINKEDIN, "linkedin", "LinkedIn profile", "key"),
        (F_ZI_CONTACT, "lower", "ZoomInfo Contact ID", "key"),
        (F_MOBILE, "phone_digits", "mobile number", "weak"),
    ],
    historical=["Lead Source", "Lead Source Detail", "Original Source",
                "First Touch Conversion Action", "Inbound Date"],
)

ACCOUNT = EntitySpec(
    prefix="Salesforce Account: ",
    fields={
        **_COMMON,
        F_RECORD_ID: ["Account ID"],
        F_RECORD_18_ID: ["Account 18 ID"],
        F_RECORD_NUMBER: ["Account Number"],
        # An Account *is* the company, so name and company are the same field.
        F_COMPANY: ["Account Name", "Name"],
        F_FULL_NAME: ["Account Name", "Name"],
        F_ACCOUNT_ID: ["Account ID"],
        F_ACCOUNT_NAME: ["Account Name", "Name"],
        F_BILLING_STREET: ["Billing Street", "Billing Address (Street)"],
        F_BILLING_CITY: ["Billing City", "Billing Address (City)"],
        F_DOMAIN: ["Domain", "Website"],
    },
    identity=[
        # An Account has no person to identify. Sameness rests on the company's own
        # identifiers: its web domain and its enrichment IDs.
        (F_WEBSITE, "domain_only", "website domain", "key"),
        (F_ZI_COMPANY, "lower", "ZoomInfo Company ID", "key"),
        (F_PHONE, "phone_digits", "phone number", "weak"),
    ],
    historical=["Lead Source", "Original Source", "First Touch Conversion Action"],
)

ENTITY_SPECS = {"Lead": LEAD, "Contact": CONTACT, "Account": ACCOUNT}

# --- Tiers, keyed by unprefixed label so they apply to every entity type -------

HIGH_VALUE_LABELS = frozenset({
    "Email", "Mobile", "Mobile Phone", "LinkedIn Profile", "Title", "Company",
    "Account :: ID", "Account :: Name", "Account Name", "Lifecycle Stage",
    "Notes", "Description", "Unqualified Reason", "Persona", "Primary Use Case",
    "Other use cases", "Other use case", "Lead Source", "Lead Source Detail",
    "Original Source", "MQL Date", "Annual Revenue", "No. of Employees",
    "Number of Employees", "Industry", "Website", "Budget", "Decision Timeframe",
    "Role in buying process", "Email Opt Out", "Do Not Call", "Email Bounced Date",
    "Email Bounced Reason", "Billing Street", "Billing City", "Parent Account :: Name",
    "Type", "Rating",
})

ROUTING_LABELS = frozenset({
    "Owner :: Name", "Owner ID", "AE Owner :: Name", "AE Owner :: ID",
    "BDR Owner :: Name", "BDR Owner :: ID", "Territory :: ID", "Segment", "Geo",
    "Lead Tier", "Account Priority Tier", "Target Account", "Focus Account",
})

# Differ on every record by construction; never counted as data loss.
SYSTEM_NOISE_LABELS = frozenset({
    "Lead ID", "Lead 18 ID", "Lead Number", "Contact ID", "Contact 18 ID",
    "Account ID", "Account 18 ID", "Account Number", "Created Date",
    "Last Modified Date", "System Modstamp", "Last Viewed Date",
    "Last Referenced Date", "Last Processed Date", "Last Transfer Date",
    "Created By :: Name", "Created By ID", "Created By :: IsActive",
    "Last Modified By :: Name", "Last Modified By ID", "Last Modified By :: IsActive",
    "Age", "Round Robin", "Round Robin for old data", "Europe Round Robin",
    "Europe Round Robin Date/Time", "Lead Assignment Logic", "Set DML Options",
    "Data.com Key", "Jigsaw Contact ID", "RingLead App Field", "RingLead Archive",
    "Ringlead Id", "Running User Reporting Field", "Current Endpoint", "Deleted",
    "Unread By Owner", "Master Record ID", "Master Record :: Name",
    "Intellimize Record Identifier", "ZoomInfo First Updated", "ZoomInfo Last Updated",
    "ZoomInfo Enrich Date", "ZoomInfo Enrich Status", "ZoomInfo Opsos App Field",
    "ZoomInfo Opsos Current Endpoint", "ZoomInfo Opsos Last Processed Date",
    "ZoomInfo Non-Matched Reason", "Legacy HubSpot Lead ID",
    "Lead without Proper owner", "One Business Hour", "Remix Account", "Text",
    "Approval Status", "Lead Notification", "Contact Dupes Ignored",
    "Lead Dupes Ignored", "Nurture to New Toggle", "View in Leadfeeder",
    "View in Web Visitors", "Latest Leadfeeder Visit",
})

# Dozens of workflow-bookkeeping timestamps, matched by label prefix.
SYSTEM_NOISE_LABEL_PREFIXES = ("Date Entered ", "Date Exited ", "Individual Address (")

#: How much acquisition information a Lead Source actually carries.
#:
#: "Sales Generated", "Outbound" and "List Build" record that a rep created the row.
#: They are the *absence* of marketing attribution, not an alternative to it, so a
#: real source always outranks them however old the rep-created record is. Anything
#: not listed here defaults to 1, a genuine source. Give real sources distinct ranks
#: here if some should outrank others -- the rule reads this map, nothing else.
LEAD_SOURCE_RANK = {
    "sales generated": 0,
    "outbound": 0,
    "list build": 0,
}
DEFAULT_LEAD_SOURCE_RANK = 1

#: A Lead Source naming an event ("Industry Event", "MinIO Event"). First-touch logic
#: inverts for these: the latest event someone attended is the useful fact, whereas
#: the channel they originally arrived through is history.
EVENT_SOURCE_MARKER = "event"

# --- Funnel position ----------------------------------------------------------
# Recycle/Non-Buyer are terminal-but-low: a record sitting there is not more advanced
# than a live Lead, so they rank equal rather than above.
LIFECYCLE_RANK = {
    "pre-lead": 0, "lead": 1, "recycle": 1, "non-buyer": 1, "mql": 2,
    "sal": 3, "sql": 4, "opportunity": 5, "customer": 6,
}

# Order fields appear in the report; anything unlisted sorts after these.
DISPLAY_ORDER_LOGICAL = [
    F_RECORD_ID, F_FULL_NAME, F_EMAIL, F_COMPANY, F_TITLE, F_ACCOUNT_NAME,
    F_ACCOUNT_ID, F_WEBSITE, F_DOMAIN, F_LINKEDIN, F_ZI_CONTACT, F_ZI_COMPANY,
    F_MOBILE, F_PHONE, F_LIFECYCLE, F_LEAD_STATUS, F_LEAD_TIER, F_ACTIVITY,
    F_CREATED, F_OWNER_NAME, F_AE_OWNER, F_BDR_OWNER,
]


@dataclass
class Schema:
    """Logical field names resolved against one file's actual columns."""

    entity: str
    spec: EntitySpec
    columns: list[str]
    _map: dict[str, str] = dc_field(default_factory=dict)
    unresolved: list[str] = dc_field(default_factory=list)

    @classmethod
    def build(cls, entity: str, columns: list[str]) -> "Schema":
        spec = ENTITY_SPECS.get(entity)
        if spec is None:
            raise ValueError(
                f"Unsupported entity type {entity!r}. "
                f"Known types: {', '.join(sorted(ENTITY_SPECS))}."
            )
        present = set(columns)
        mapping, missing = {}, []
        for logical, candidates in spec.fields.items():
            for label in candidates:
                col = spec.prefix + label
                if col in present:
                    mapping[logical] = col
                    break
                if label in present:  # tolerate an export without the object prefix
                    mapping[logical] = label
                    break
            else:
                missing.append(logical)
        return cls(entity=entity, spec=spec, columns=list(columns),
                   _map=mapping, unresolved=sorted(missing))

    # -- resolution ------------------------------------------------------------
    def col(self, logical: str) -> str | None:
        """Actual column for a logical field, or None if this export lacks it."""
        return self._map.get(logical)

    def resolve(self, key: str) -> str | None:
        """Accept either a logical name or a literal column name."""
        if key in self._map:
            return self._map[key]
        return key if key in self.columns else None

    def label(self, col: str) -> str:
        """Strip the object prefix for display."""
        if col in self._map:
            col = self._map[col]
        return col[len(self.spec.prefix):] if col.startswith(self.spec.prefix) else col

    # -- tiers -----------------------------------------------------------------
    def is_noise(self, col: str) -> bool:
        if col in META_COLS:
            return True
        lab = self.label(col)
        return lab in SYSTEM_NOISE_LABELS or lab.startswith(SYSTEM_NOISE_LABEL_PREFIXES)

    def tier(self, col: str) -> str:
        if self.is_noise(col):
            return "noise"
        lab = self.label(col)
        if lab in HIGH_VALUE_LABELS:
            return "high"
        if lab in ROUTING_LABELS:
            return "routing"
        return "standard"

    def display_rank(self, col: str) -> int:
        for i, logical in enumerate(DISPLAY_ORDER_LOGICAL):
            if self._map.get(logical) == col:
                return i
        base = len(DISPLAY_ORDER_LOGICAL)
        return base + {"high": 0, "standard": 1, "routing": 2, "noise": 3}[self.tier(col)]

    # -- per-entity rule inputs ------------------------------------------------
    @property
    def identity_signals(self) -> list[tuple[str, str, str]]:
        """Identity fields this export actually carries."""
        return [sig for sig in self.spec.identity if self.col(sig[0])]

    @property
    def display_columns(self) -> list[str]:
        """Resolved columns for the short identity table shown on clean groups."""
        return [c for c in (self.col(lg) for lg in DISPLAY_ORDER_LOGICAL) if c]

    @property
    def historical_fields(self) -> list[str]:
        """Columns where the OLDEST value is the correct one."""
        cols = (self.spec.prefix + lab for lab in self.spec.historical)
        return [c for c in cols if c in self.columns]

    def report(self) -> str:
        """Human-readable resolution summary, for `main.py --schema`."""
        lines = [
            f"Entity type : {self.entity}",
            f"Prefix      : {self.spec.prefix!r}",
            f"Columns     : {len(self.columns)}",
            f"Resolved    : {len(self._map)} of {len(self.spec.fields)} logical fields",
            "",
        ]
        for logical in sorted(self._map):
            lines.append(f"  {logical:<18} -> {self.label(self._map[logical])}")
        if self.unresolved:
            lines += ["", "  NOT FOUND (checks needing these will be skipped):"]
            lines += [
                f"    {lg:<18}    tried: {', '.join(self.spec.fields[lg])}"
                for lg in self.unresolved
            ]
        return "\n".join(lines)
