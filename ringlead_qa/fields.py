"""Field catalog.

The export carries 217 columns, most of which are Salesforce plumbing that changes
on every record by definition (record IDs, modstamps, round-robin counters). Treating
those as "data lost in the merge" buries the handful of fields a human actually cares
about, so every column gets sorted into a tier here and the rules only look at the
tiers they should.
"""

PREFIX = "Salesforce Lead: "

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

# --- Named fields the rules reference directly --------------------------------
F_EMAIL = PREFIX + "Email"
F_DOMAIN = PREFIX + "Domain"
F_COMPANY_DOMAIN = PREFIX + "Company Domain Name"
F_COMPANY = PREFIX + "Company"
F_TITLE = PREFIX + "Title"
F_FULL_NAME = PREFIX + "Full Name"
F_FIRST_NAME = PREFIX + "First Name"
F_LAST_NAME = PREFIX + "Last Name"
F_LINKEDIN = PREFIX + "LinkedIn Profile"
F_ZI_CONTACT = PREFIX + "ZoomInfo Contact ID"
F_ZI_UPDATED = PREFIX + "ZoomInfo Last Updated"
F_ZI_ENRICH_DATE = PREFIX + "ZoomInfo Enrich Date"
F_MOBILE = PREFIX + "Mobile"
F_PHONE = PREFIX + "Phone"
F_ACCOUNT_ID = PREFIX + "Account :: ID"
F_ACCOUNT_NAME = PREFIX + "Account :: Name"
F_LIFECYCLE = PREFIX + "Lifecycle Stage"
F_LEAD_STATUS = PREFIX + "Lead Status (Deprecated)"
F_LEAD_TIER = PREFIX + "Lead Tier"
F_OWNER_NAME = PREFIX + "Owner :: Name"
F_OWNER_ACTIVE = PREFIX + "Owner :: IsActive"
F_AE_OWNER = PREFIX + "AE Owner :: Name"
F_BDR_OWNER = PREFIX + "BDR Owner :: Name"
F_ACTIVITY = PREFIX + "Most Recent Activity Date"
F_LAST_ACTIVITY = PREFIX + "Last Activity"
F_CREATED = PREFIX + "Created Date"
F_MODIFIED = PREFIX + "Last Modified Date"
F_LEAD_ID = PREFIX + "Lead ID"
F_LEAD_18_ID = PREFIX + "Lead 18 ID"
F_LEAD_NUMBER = PREFIX + "Lead Number"
F_NOTES = PREFIX + "Notes"
F_DESCRIPTION = PREFIX + "Description"
F_UNQUALIFIED = PREFIX + "Unqualified Reason"

# --- Identity: does this group describe one human? ----------------------------
# Coverage in the sample export: LinkedIn 83%, ZoomInfo Contact ID 88%, Mobile 77%.
# Phone is deliberately absent -- it is usually the company switchboard, so it
# changes when someone changes jobs and disagrees in 213/460 groups.
IDENTITY_STRONG = [F_LINKEDIN, F_ZI_CONTACT, F_MOBILE]

# --- Employment: what "current job" looks like --------------------------------
# ZoomInfo overwrites Company/Title across every record with the person's current
# employer, while Email/Domain/Account stay frozen at capture time. That asymmetry
# is what the stale-employment rules exploit.
EMPLOYMENT_CURRENT = [F_COMPANY, F_TITLE]
EMPLOYMENT_HISTORICAL = [F_EMAIL, F_DOMAIN, F_COMPANY_DOMAIN, F_ACCOUNT_ID, F_ACCOUNT_NAME]

# --- Historical fields: oldest wins, not newest -------------------------------
# Recency is only the right tiebreaker for "current state" fields. First-touch
# attribution describes how the lead originally arrived, so overwriting it with a
# later record's value destroys the answer rather than refreshing it.
HISTORICAL_FIELDS = [
    PREFIX + "Lead Source",
    PREFIX + "Lead Source Detail",
    PREFIX + "Original Source",
    PREFIX + "First Touch Conversion Action",
    PREFIX + "Inbound Date",
]

# --- Funnel position ----------------------------------------------------------
# Ordering for regression detection. Recycle/Non-Buyer are terminal-but-low: a
# record sitting there is *not* more advanced than a live Lead, so they rank equal.
LIFECYCLE_RANK = {
    "pre-lead": 0,
    "lead": 1,
    "recycle": 1,
    "non-buyer": 1,
    "mql": 2,
    "sal": 3,
    "sql": 4,
    "opportunity": 5,
    "customer": 6,
}

# --- Tiers --------------------------------------------------------------------
# HIGH_VALUE: losing one of these is worth a human's attention.
HIGH_VALUE = {
    F_EMAIL,
    F_MOBILE,
    F_LINKEDIN,
    F_TITLE,
    F_COMPANY,
    F_ACCOUNT_ID,
    F_ACCOUNT_NAME,
    F_LIFECYCLE,
    F_NOTES,
    F_DESCRIPTION,
    F_UNQUALIFIED,
    PREFIX + "Persona",
    PREFIX + "Primary Use Case",
    PREFIX + "Other use cases",
    PREFIX + "Other use case",
    PREFIX + "Lead Source",
    PREFIX + "Lead Source Detail",
    PREFIX + "Original Source",
    PREFIX + "MQL Date",
    PREFIX + "Annual Revenue",
    PREFIX + "No. of Employees",
    PREFIX + "Industry",
    PREFIX + "Website",
    PREFIX + "Budget",
    PREFIX + "Decision Timeframe",
    PREFIX + "Role in buying process",
    PREFIX + "Email Opt Out",
    PREFIX + "Do Not Call",
    PREFIX + "Email Bounced Date",
    PREFIX + "Email Bounced Reason",
}

# ROUTING: who owns the record. Worth showing, but reassignment during a merge is
# routine rather than alarming, so these only contribute to the score.
ROUTING = {
    F_OWNER_NAME,
    F_AE_OWNER,
    F_BDR_OWNER,
    PREFIX + "Owner ID",
    PREFIX + "AE Owner :: ID",
    PREFIX + "BDR Owner :: ID",
    PREFIX + "Territory :: ID",
    PREFIX + "Segment",
    PREFIX + "Geo",
    PREFIX + "Lead Tier",
    PREFIX + "Account Priority Tier",
    PREFIX + "Target Account",
    PREFIX + "Focus Account",
}

# SYSTEM_NOISE: differs on every record by construction. Never counted as loss.
SYSTEM_NOISE = {
    F_LEAD_ID,
    F_LEAD_18_ID,
    F_LEAD_NUMBER,
    F_CREATED,
    F_MODIFIED,
    PREFIX + "System Modstamp",
    PREFIX + "Last Viewed Date",
    PREFIX + "Last Referenced Date",
    PREFIX + "Last Processed Date",
    PREFIX + "Last Transfer Date",
    PREFIX + "Created By :: Name",
    PREFIX + "Created By ID",
    PREFIX + "Created By :: IsActive",
    PREFIX + "Last Modified By :: Name",
    PREFIX + "Last Modified By ID",
    PREFIX + "Last Modified By :: IsActive",
    PREFIX + "Age",
    PREFIX + "Round Robin",
    PREFIX + "Round Robin for old data",
    PREFIX + "Europe Round Robin",
    PREFIX + "Europe Round Robin Date/Time",
    PREFIX + "Lead Assignment Logic",
    PREFIX + "Set DML Options",
    PREFIX + "Data.com Key",
    PREFIX + "Jigsaw Contact ID",
    PREFIX + "RingLead App Field",
    PREFIX + "RingLead Archive",
    PREFIX + "Ringlead Id",
    PREFIX + "Running User Reporting Field",
    PREFIX + "Current Endpoint",
    PREFIX + "Deleted",
    PREFIX + "Unread By Owner",
    PREFIX + "Master Record ID",
    PREFIX + "Master Record :: Name",
    PREFIX + "Intellimize Record Identifier",
    PREFIX + "ZoomInfo First Updated",
    PREFIX + "ZoomInfo Last Updated",
    PREFIX + "ZoomInfo Enrich Date",
    PREFIX + "ZoomInfo Enrich Status",
    PREFIX + "ZoomInfo Opsos App Field",
    PREFIX + "ZoomInfo Opsos Current Endpoint",
    PREFIX + "ZoomInfo Opsos Last Processed Date",
    PREFIX + "ZoomInfo Non-Matched Reason",
    PREFIX + "Legacy HubSpot Lead ID",
    PREFIX + "Lead without Proper owner",
    PREFIX + "One Business Hour",
    PREFIX + "Remix Account",
    PREFIX + "Text",
    PREFIX + "Approval Status",
    PREFIX + "Lead Notification",
    PREFIX + "Contact Dupes Ignored",
    PREFIX + "Lead Dupes Ignored",
    PREFIX + "Nurture to New Toggle",
    PREFIX + "View in Leadfeeder",
    PREFIX + "View in Web Visitors",
    PREFIX + "Latest Leadfeeder Visit",
}
# Stage-transition timestamps: dozens of "Date Entered/Exited X" columns that are
# pure workflow bookkeeping.
SYSTEM_NOISE_PREFIXES = (
    PREFIX + "Date Entered ",
    PREFIX + "Date Exited ",
    PREFIX + "Individual Address (",
)

# Order fields appear in the report. Anything unlisted sorts after these.
DISPLAY_ORDER = [
    F_LEAD_ID,
    F_FULL_NAME,
    F_EMAIL,
    F_COMPANY,
    F_TITLE,
    F_ACCOUNT_NAME,
    F_ACCOUNT_ID,
    F_DOMAIN,
    F_LINKEDIN,
    F_ZI_CONTACT,
    F_MOBILE,
    F_PHONE,
    F_LIFECYCLE,
    F_LEAD_STATUS,
    F_LEAD_TIER,
    F_ACTIVITY,
    F_CREATED,
    F_OWNER_NAME,
    F_AE_OWNER,
    F_BDR_OWNER,
]


def is_noise(col: str) -> bool:
    """True for columns that differ mechanically and should never count as loss."""
    if col in META_COLS or col in SYSTEM_NOISE:
        return True
    return col.startswith(SYSTEM_NOISE_PREFIXES)


def tier(col: str) -> str:
    """Sort a column into the tier the scoring rules use."""
    if is_noise(col):
        return "noise"
    if col in HIGH_VALUE:
        return "high"
    if col in ROUTING:
        return "routing"
    return "standard"


def label(col: str) -> str:
    """Strip the redundant object prefix for display."""
    return col[len(PREFIX):] if col.startswith(PREFIX) else col


def display_rank(col: str) -> int:
    try:
        return DISPLAY_ORDER.index(col)
    except ValueError:
        return len(DISPLAY_ORDER) + {"high": 0, "standard": 1, "routing": 2, "noise": 3}[tier(col)]
