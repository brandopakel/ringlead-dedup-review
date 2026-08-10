"""Self-contained HTML report.

Layout rules, applied uniformly so the page stays scannable at 460 groups:

* Every group is one row on a fixed grid -- status, person, company, issue, id --
  so the columns line up down the whole page and can be read without stopping.
* Findings never render as prose. Each is a short title plus `evidence` rows on a
  shared two-column grid, so "Keeps / Discards" always appears in the same place.
* The comparison table reuses RingLead's colour language: green fill for a value
  that survives, pink strikethrough for one destroyed, green border on the master.

No external CSS, fonts, or scripts -- the file opens from disk with no network.
"""

from __future__ import annotations

import html
from collections import Counter
from datetime import datetime

from . import fields as F
from .rules import Verdict

STATUS_LABEL = {"critical": "Fix", "review": "Review", "ok": "Clean"}

# Patterns worth naming once at the top rather than 100 times in the queue: if a
# finding fires on a large share of groups it is a rule problem, not 100 mistakes.
SYSTEMIC_ADVICE = {
    "stale_email_kept":
        "Set Email survivorship to prefer the address whose domain matches Company, "
        "rather than always taking the master's value.",
    "master_owner_inactive":
        "Add “owner is active” as a master-selection criterion so leads stop landing "
        "with departed reps.",
    "master_stale":
        "Weight Most Recent Activity Date more heavily when choosing the master.",
    "identity_unverified":
        "These match on name and company alone. Consider requiring a second identifier "
        "— LinkedIn, ZoomInfo Contact ID, or mobile — in the match criteria.",
    "stale_title_kept":
        "Set Title survivorship to prefer the most recently updated record.",
    "stale_account_link":
        "Set Account survivorship to prefer the most recently updated record.",
    "original_source_overwritten":
        "Set Lead Source and Lead Source Detail survivorship to prefer the OLDEST "
        "record — first-touch attribution is history, not current state.",
}

CSS = """
:root{
  --bg:#f7f8fa; --panel:#fff; --ink:#11151b; --muted:#68727e; --faint:#98a2ad;
  --line:#e3e7ec; --line2:#eef1f4;
  --master:#0ca678; --master-bg:#dff5ec; --lost:#d6336c; --lost-bg:#fdeff4;
  --crit:#d6336c; --rev:#e8890c; --ok:#0ca678; --accent:#4263eb;
  --r:8px; --pad:16px;
}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){
  --bg:#0d1014; --panel:#151a20; --ink:#e6eaf0; --muted:#98a3b0; --faint:#6c7784;
  --line:#252c34; --line2:#1d232a;
  --master:#20c997; --master-bg:#0f3a2d; --lost:#ff6b9d; --lost-bg:#3a1224;
  --crit:#ff6b9d; --rev:#ffa94d; --ok:#20c997; --accent:#748ffc;
}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);
  font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  font-variant-numeric:tabular-nums}
.wrap{max-width:1240px;margin:0 auto;padding:32px 20px 80px}
h1{font-size:19px;font-weight:650;margin:0}
.sub{color:var(--muted);font-size:13px;margin:3px 0 24px}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}

/* ---- summary ---- */
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:20px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);padding:14px var(--pad)}
.card .n{font-size:24px;font-weight:650;line-height:1.15}
.card .l{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.05em;margin-top:3px}
.card.crit .n{color:var(--crit)} .card.rev .n{color:var(--rev)} .card.ok .n{color:var(--ok)}

/* ---- panels ---- */
.panel{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);
  padding:var(--pad);margin-bottom:20px}
.panel h2{font-size:11px;font-weight:650;margin:0 0 2px;text-transform:uppercase;
  letter-spacing:.05em;color:var(--muted)}
.panel .note{color:var(--muted);font-size:13px;margin:0 0 12px}
.sys{display:grid;grid-template-columns:52px 1fr;gap:0 12px;padding:10px 0;
  border-top:1px solid var(--line2);align-items:baseline}
.sys .cnt{font-weight:650;color:var(--accent);text-align:right}
.sys .adv{color:var(--muted);display:block;margin-top:1px}

/* ---- filter bar ---- */
.bar{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-bottom:12px;
  position:sticky;top:0;background:var(--bg);padding:12px 0;z-index:5;
  border-bottom:1px solid var(--line)}
button.f{font:inherit;font-size:13px;background:var(--panel);color:var(--ink);
  border:1px solid var(--line);border-radius:999px;padding:4px 12px;cursor:pointer;
  white-space:nowrap}
button.f:hover{border-color:var(--accent)}
button.f[aria-pressed=true]{background:var(--accent);border-color:var(--accent);color:#fff}
input.s{font:inherit;font-size:13px;padding:5px 11px;border:1px solid var(--line);
  border-radius:999px;background:var(--panel);color:var(--ink);min-width:210px}
.spacer{flex:1}
.tally{color:var(--muted);font-size:12px;white-space:nowrap}

/* ---- group row: one grid, aligned down the page ---- */
.grp{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);
  margin-bottom:6px;overflow:hidden}
.grp[open]{border-color:var(--accent)}
.gh{display:grid;grid-template-columns:16px 62px minmax(150px,1.1fr) minmax(120px,1fr) 2fr 92px;
  gap:12px;align-items:center;padding:11px var(--pad);cursor:pointer;user-select:none;
  list-style:none}
.gh::-webkit-details-marker{display:none}
.gh:hover{background:color-mix(in srgb,var(--accent) 4%,transparent)}
.chev{color:var(--faint);font-size:11px;transition:transform .12s}
.grp[open] .chev{transform:rotate(90deg)}
.badge{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;
  padding:3px 0;border-radius:4px;text-align:center}
.badge.critical{background:color-mix(in srgb,var(--crit) 13%,transparent);color:var(--crit)}
.badge.review{background:color-mix(in srgb,var(--rev) 15%,transparent);color:var(--rev)}
.badge.ok{background:color-mix(in srgb,var(--ok) 13%,transparent);color:var(--ok)}
.gname{font-weight:600}
.gco,.ghl{color:var(--muted)}
.gname,.gco,.ghl{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.gid{color:var(--faint);text-align:right}

/* ---- expanded body ---- */
.body{padding:2px var(--pad) var(--pad);border-top:1px solid var(--line2)}
.find{padding:12px 0;border-bottom:1px solid var(--line2)}
.find:last-of-type{border-bottom:0}
.fhead{display:flex;gap:8px;align-items:baseline}
.dot{width:6px;height:6px;border-radius:50%;flex:none;transform:translateY(-1px)}
.find.critical .dot{background:var(--crit)}
.find.review .dot{background:var(--rev)}
.find.contributor .dot{background:var(--faint)}
.ftitle{font-weight:600}
.fdetail{color:var(--muted)}
.ev{display:grid;grid-template-columns:88px 1fr;gap:3px 12px;margin:7px 0 0 14px;font-size:13px}
.ev dt{color:var(--faint);font-size:11px;text-transform:uppercase;letter-spacing:.04em;
  padding-top:2px}
.ev dd{margin:0;overflow-wrap:anywhere}

/* ---- comparison table ---- */
.tw{overflow-x:auto;margin-top:14px;border:1px solid var(--line);border-radius:6px}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:5px 10px;text-align:left;border-bottom:1px solid var(--line2);
  white-space:nowrap;max-width:300px;overflow:hidden;text-overflow:ellipsis}
tbody tr:last-child th,tbody tr:last-child td{border-bottom:0}
thead th{background:var(--line2);font-size:11px;font-weight:650;text-transform:uppercase;
  letter-spacing:.04em;color:var(--muted);white-space:nowrap}
thead .sf{display:block;font-weight:400;text-transform:none;letter-spacing:0;
  color:var(--faint);font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:10px}
th.fld{font-weight:500;color:var(--muted);white-space:normal;width:180px;font-size:12px}
.col-master{border-left:2px solid var(--master);border-right:2px solid var(--master)}
.col-surv{background:color-mix(in srgb,var(--accent) 5%,transparent);font-weight:600}
td.won{background:var(--master-bg)}
td.lost{background:var(--lost-bg);color:var(--lost);text-decoration:line-through;
  text-decoration-color:color-mix(in srgb,var(--lost) 40%,transparent)}
td.blank{color:var(--faint)}
tr.flagged th.fld{box-shadow:inset 3px 0 0 var(--accent);color:var(--ink);font-weight:600}
.foot{display:flex;gap:18px;flex-wrap:wrap;align-items:center;margin-top:9px;
  color:var(--faint);font-size:11px}
.foot i{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px;
  vertical-align:-1px}
.tgl{font:inherit;font-size:11px;background:none;border:0;color:var(--accent);
  cursor:pointer;padding:0;text-decoration:underline;margin-left:auto}
.col-fix{background:color-mix(in srgb,var(--master) 7%,transparent)}
td.fix{color:var(--master);font-weight:600}
.fixes{margin-top:14px;border:1px solid var(--master);border-radius:6px;
  background:color-mix(in srgb,var(--master) 5%,transparent);padding:11px 13px}
.fixes h3{font-size:11px;font-weight:650;margin:0 0 7px;text-transform:uppercase;
  letter-spacing:.05em;color:var(--master)}
.fixes table{width:auto}
.fixes th,.fixes td{border:0;padding:2px 12px 2px 0;font-size:13px}
.fixes th{font-weight:500;color:var(--muted);text-align:left}
.fixes .was{color:var(--muted);text-decoration:line-through;
  text-decoration-color:color-mix(in srgb,var(--muted) 45%,transparent)}
.fixes .arrow{color:var(--faint);padding:0 4px}
.fixes .fix{color:var(--master);font-weight:600}
.fixes .why{color:var(--faint);font-size:11px}
.fixes.has-master{border-color:var(--accent);
  background:color-mix(in srgb,var(--accent) 5%,transparent)}
.fixes.has-master h3{color:var(--accent)}
.fixes .mrow th,.fixes .mrow td{padding-bottom:7px;font-weight:600}
.fixes .mrow .fix{color:var(--accent)}
.fixes .mrow~tr th{font-weight:500}
.fnote{color:var(--muted);font-size:11px;margin:8px 0 0;max-width:62ch}
.col-newmaster{border-left:2px solid var(--accent);border-right:2px solid var(--accent);
  color:var(--accent)}
.empty{color:var(--muted);padding:32px;text-align:center}
.clean{columns:5;column-gap:14px}
.clean a{color:var(--faint);text-decoration:none;display:block;padding:1px 0}
.clean a:hover{color:var(--accent)}
@media(max-width:900px){
  .cards{grid-template-columns:repeat(2,1fr)}
  .gh{grid-template-columns:16px 58px 1fr 76px}
  .gco,.ghl{display:none}
  .clean{columns:3}
}
"""

JS = """
const groups=[...document.querySelectorAll('.grp')];
const q=document.getElementById('q');
let status='all', code='all';
function apply(){
  const term=q.value.trim().toLowerCase();
  let shown=0;
  for(const g of groups){
    const vis = (status==='all'||g.dataset.status===status)
             && (code==='all'||g.dataset.codes.split(' ').includes(code))
             && (!term||g.dataset.search.includes(term));
    g.hidden=!vis; if(vis) shown++;
  }
  document.getElementById('tally').textContent=shown+' shown';
  document.getElementById('none').hidden=shown>0;
}
for(const b of document.querySelectorAll('button.f')){
  b.onclick=()=>{
    const k=b.dataset.kind;
    if(k==='status') status=b.dataset.val; else code=b.dataset.val;
    for(const o of document.querySelectorAll(`button.f[data-kind="${k}"]`))
      o.setAttribute('aria-pressed', String(o===b));
    apply();
  };
}
q.oninput=apply;
for(const t of document.querySelectorAll('.tgl')){
  t.onclick=e=>{
    e.preventDefault(); e.stopPropagation();
    const tb=document.getElementById(t.dataset.target);
    const all=tb.classList.toggle('show-all');
    for(const r of tb.querySelectorAll('tr[data-same="1"]')) r.hidden=!all;
    t.textContent = all ? 'Show only differences' : 'Show all '+t.dataset.total+' fields';
  };
}
for(const a of document.querySelectorAll('.clean a')){
  a.onclick=e=>{e.preventDefault(); q.value=a.textContent; apply();
    window.scrollTo({top:0,behavior:'smooth'});};
}
apply();
"""


def _esc(v) -> str:
    return html.escape("" if v is None else str(v), quote=True)


def _cell(value: str, *, survivor: str, is_master: bool) -> str:
    """Class a cell the way RingLead colours it."""
    master_cls = "col-master " if is_master else ""
    if not value:
        return f'<td class="{master_cls}blank">—</td>'
    state = "won" if value == survivor else "lost"
    return f'<td class="{master_cls}{state}" title="{_esc(value)}">{_esc(value)}</td>'


def _table(v: Verdict, tid: str) -> str:
    g = v.group
    highlight = set(v.highlight_fields())
    # Noise-tier columns (record IDs, modstamps, round-robin counters) differ on every
    # record by construction. Rendering them triples the page weight and hides the
    # fields a reviewer can act on, so they never reach the table.
    cols = [c for c in g.populated_columns() if F.tier(c) != "noise" or c in highlight]
    if v.status == "ok":
        # Clean groups exist for spot-checking, not reviewing. A short identity table
        # confirms the call at a glance and keeps 238 skippable groups from dominating
        # the page weight.
        cols = [c for c in cols if c in F.DISPLAY_ORDER]
    differing = set(g.differing_columns())

    # "After merge" is RingLead's prediction of what will happen, defects included --
    # it is not a target. Where the right value is derivable, a "Should be" column
    # states it, so a reviewer knows what to set rather than only what is wrong.
    fixes = {c.column: c for c in v.corrections}

    order = [g.surviving, g.master, *g.duplicates]
    heads = ['<th class="fld">Field</th>', '<th class="col-surv">After merge</th>']
    if fixes:
        heads.append('<th class="col-fix">Should be</th>')
    mc = v.master_change
    for rec in order[1:]:
        cls = "col-master" if rec.role == "master" else ""
        label = _esc(rec.label)
        if mc and rec.lead_id == mc.record.lead_id:
            cls = (cls + " col-newmaster").strip()
            label = "Should be master"
        elif mc and rec.role == "master":
            label = "Master (change)"
        heads.append(
            f'<th class="{cls}">{label}'
            f'<span class="sf">{_esc(rec.lead_id)}</span></th>'
        )

    rows = []
    for col in cols:
        same = col not in differing and col not in highlight
        survivor = g.surviving.get(col)
        cells = [
            f'<th class="fld">{_esc(F.label(col))}</th>',
            f'<td class="col-surv">{_esc(survivor) or "—"}</td>',
        ]
        if fixes:
            fix = fixes.get(col)
            cells.append(
                f'<td class="col-fix fix" title="{_esc(fix.why)}">{_esc(fix.value)}</td>'
                if fix and fix.value != survivor
                else '<td class="col-fix blank">—</td>'
            )
        cells += [
            _cell(rec.get(col), survivor=survivor, is_master=rec.role == "master")
            for rec in order[1:]
        ]
        rows.append(
            f'<tr class="{"flagged" if col in highlight else ""}" '
            f'data-same="{1 if same else 0}"{" hidden" if same else ""}>'
            + "".join(cells) + "</tr>"
        )

    return (
        f'<div class="tw"><table id="{tid}"><thead><tr>{"".join(heads)}</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div>'
        '<div class="foot">'
        '<span><i style="background:var(--master-bg);border:1px solid var(--master)"></i>Survives</span>'
        '<span><i style="background:var(--lost-bg);border:1px solid var(--lost)"></i>Lost in merge</span>'
        '<span><i style="border:2px solid var(--master)"></i>Master record</span>'
        f'<button class="tgl" data-target="{tid}" data-total="{len(cols)}">'
        f'Show all {len(cols)} fields</button>'
        '</div>'
    )


def _findings(v: Verdict) -> str:
    if not v.findings:
        return '<div class="find"><div class="fdetail">No issues detected.</div></div>'
    out = []
    for f in v.findings:
        ev = "".join(
            f"<dt>{_esc(k)}</dt><dd>{_esc(val)}</dd>" for k, val in f.evidence if val
        )
        out.append(
            f'<div class="find {f.severity}">'
            f'<div class="fhead"><span class="dot"></span>'
            f'<span class="ftitle">{_esc(f.title)}</span>'
            f'<span class="fdetail">{_esc(f.detail)}</span></div>'
            + (f'<dl class="ev">{ev}</dl>' if ev else "")
            + "</div>"
        )
    return "".join(out)


def _fixes(v: Verdict) -> str:
    """The corrected values, stated plainly before the field-by-field table."""
    mc = v.master_change
    if not v.corrections and not mc:
        return ""

    master_row = ""
    if mc:
        master_row = (
            '<tr class="mrow"><th>Master record</th>'
            f'<td class="was">{_esc(v.group.master.lead_id)}</td>'
            '<td class="arrow">&rarr;</td>'
            f'<td class="fix">{_esc(mc.record.lead_id)}</td>'
            f'<td class="why">{_esc(mc.why)}'
            + ("" if mc.corroborated else " — single signal, confirm before changing")
            + "</td></tr>"
        )

    rows = master_row + "".join(
        f"<tr><th>{_esc(F.label(c.column))}</th>"
        f'<td class="was">{_esc(v.group.surviving.get(c.column)) or "—"}</td>'
        f'<td class="arrow">&rarr;</td>'
        f'<td class="fix">{_esc(c.value)}</td>'
        f'<td class="why">{_esc(c.why)}</td></tr>'
        for c in v.corrections
    )
    # A master change is applied in RingLead before merging; the field values below it
    # are computed against the *current* preview, so they have to be re-read afterwards.
    note = (
        '<p class="fnote">Changing the master changes which record survives. Re-run this '
        'report after the change — the field values below are computed against the '
        'current merge preview.</p>' if mc else ""
    )
    heading = "Change the master, then re-check" if mc else "Set these on the surviving record"
    return (
        f'<div class="fixes{" has-master" if mc else ""}"><h3>{heading}</h3>'
        f"<table>{rows}</table>{note}</div>"
    )


def _group_row(v: Verdict, idx: int) -> str:
    g = v.group
    name = g.surviving.get(F.F_FULL_NAME) or g.surviving.get(F.F_EMAIL) or "(no name)"
    company = g.surviving.get(F.F_COMPANY)
    codes = " ".join(sorted({f.code for f in v.findings}))
    search = " ".join(
        [g.group_id, name, company, g.surviving.get(F.F_EMAIL), codes]
    ).lower()

    return f"""
<details class="grp {v.status}" data-status="{v.status}" data-codes="{_esc(codes)}"
         data-search="{_esc(search)}">
  <summary class="gh">
    <span class="chev">&#9654;</span>
    <span class="badge {v.status}">{STATUS_LABEL[v.status]}</span>
    <span class="gname">{_esc(name)}</span>
    <span class="gco">{_esc(company)}</span>
    <span class="ghl">{_esc(v.headline)}</span>
    <span class="gid mono">{_esc(g.group_id)}</span>
  </summary>
  <div class="body">{_findings(v)}{_fixes(v)}{_table(v, f"t{idx}")}</div>
</details>"""


def render(verdicts: list[Verdict], *, source: str, total_rows: int) -> str:
    verdicts = sorted(verdicts, key=lambda v: v.sort_key)
    counts = Counter(v.status for v in verdicts)
    total = len(verdicts) or 1
    code_counts = Counter(f.code for v in verdicts for f in v.findings if v.needs_review)

    systemic = "".join(
        f'<div class="sys"><span class="cnt">{n}</span><span><b>{_esc(code)}</b>'
        f'<span class="adv">{_esc(SYSTEMIC_ADVICE[code])}</span></span></div>'
        for code, n in code_counts.most_common()
        if code in SYSTEMIC_ADVICE and n >= 15
    )
    systemic_panel = (
        '<div class="panel"><h2>Systemic patterns</h2>'
        '<p class="note">These repeat across many groups. Changing the survivorship rule '
        'in RingLead clears the whole bucket at once — cheaper than fixing the groups.</p>'
        f"{systemic}</div>" if systemic else ""
    )

    filters = "".join(
        f'<button class="f" data-kind="code" data-val="{_esc(c)}">{_esc(c)} · {n}</button>'
        for c, n in code_counts.most_common(6)
    )
    rows = "".join(_group_row(v, i) for i, v in enumerate(verdicts))
    clean = "".join(
        f'<a href="#" class="mono">{_esc(v.group.group_id)}</a>'
        for v in verdicts if not v.needs_review
    )
    generated = datetime.now().strftime("%b %-d, %Y at %-I:%M %p")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RingLead merge QA — {_esc(source)}</title>
<style>{CSS}</style></head><body><div class="wrap">

<h1>RingLead merge QA</h1>
<p class="sub">{_esc(source)} · {total_rows:,} rows · {len(verdicts)} groups · {generated}</p>

<div class="cards">
  <div class="card crit"><div class="n">{counts['critical']}</div><div class="l">Needs a fix</div></div>
  <div class="card rev"><div class="n">{counts['review']}</div><div class="l">Needs review</div></div>
  <div class="card ok"><div class="n">{counts['ok']}</div><div class="l">Clean — skip</div></div>
  <div class="card"><div class="n">{round(counts['ok'] / total * 100)}%</div><div class="l">Of the file skipped</div></div>
</div>

{systemic_panel}

<div class="bar">
  <button class="f" data-kind="status" data-val="all" aria-pressed="true">All {len(verdicts)}</button>
  <button class="f" data-kind="status" data-val="critical">Fix {counts['critical']}</button>
  <button class="f" data-kind="status" data-val="review">Review {counts['review']}</button>
  <button class="f" data-kind="status" data-val="ok">Clean {counts['ok']}</button>
  <button class="f" data-kind="code" data-val="all" aria-pressed="true">Any issue</button>
  {filters}
  <span class="spacer"></span>
  <input class="s" id="q" placeholder="Search name, company, email, ID">
  <span class="tally" id="tally"></span>
</div>

{rows}
<div class="empty" id="none" hidden>No groups match these filters.</div>

<div class="panel" style="margin-top:22px">
  <h2>Clean — no review needed</h2>
  <p class="note">{counts['ok']} groups passed every check. Click an ID to pull it up.</p>
  <div class="clean">{clean}</div>
</div>

<script>{JS}</script>
</div></body></html>"""
