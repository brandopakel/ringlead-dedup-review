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
from . import tokens
from .rules import Verdict

STATUS_LABEL = {"skip": "Skip", "critical": "Fix", "review": "Review", "ok": "Clean"}

STYLES = """
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:hsl(var(--background));color:hsl(var(--foreground));
  font:14px/1.5 ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased}
.wrap{max-width:1280px;margin:0 auto;padding:36px 24px 96px}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}
:focus-visible{outline:2px solid hsl(var(--ring));outline-offset:2px;border-radius:4px}

/* ---- header ---- */
h1{font-size:20px;font-weight:650;letter-spacing:-.025em;margin:0}
.brandrule{height:3px;width:64px;margin:9px 0 0;border-radius:2px;
  background:linear-gradient(90deg,hsl(var(--destructive)),hsl(var(--skip)),hsl(var(--info)))}
.sub{color:hsl(var(--muted-foreground));font-size:13px;margin:10px 0 0}
.head{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;
  flex-wrap:wrap;margin-bottom:24px}

/* ---- progress ---- */
.prog{min-width:230px}
.prog .lbl{display:flex;justify-content:space-between;font-size:12px;
  color:hsl(var(--muted-foreground));margin-bottom:6px}
.prog .lbl b{color:hsl(var(--foreground));font-weight:600}
.track{height:6px;border-radius:999px;background:hsl(var(--muted));overflow:hidden}
.fill{height:100%;background:hsl(var(--success));width:0;transition:width .25s ease;
  border-radius:999px}
.reset{font:inherit;font-size:11px;background:none;border:0;padding:4px 0 0;
  color:hsl(var(--muted-foreground));cursor:pointer;text-decoration:underline}
.reset:hover{color:hsl(var(--foreground))}

/* ---- cards ---- */
.cards{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:20px}
.card{background:hsl(var(--card));border:1px solid hsl(var(--border));
  border-radius:var(--radius);padding:16px 18px}
.card .n{font-size:26px;font-weight:600;line-height:1.1;letter-spacing:-.02em}
.card .l{color:hsl(var(--muted-foreground));font-size:12px;margin-top:4px}
.card.skip .n{color:hsl(var(--skip))}
.card.crit .n{color:hsl(var(--destructive))}
.card.rev .n{color:hsl(var(--warning))}
.card.ok .n{color:hsl(var(--success))}

/* ---- panel ---- */
.panel{background:hsl(var(--card));border:1px solid hsl(var(--border));
  border-radius:var(--radius);padding:18px;margin-bottom:20px}
.panel h2{font-size:14px;font-weight:600;margin:0 0 3px;letter-spacing:-.01em}
.panel .note{color:hsl(var(--muted-foreground));font-size:13px;margin:0 0 14px;max-width:74ch}
.sys{display:grid;grid-template-columns:auto 1fr;gap:0 14px;padding:11px 0;
  border-top:1px solid hsl(var(--border));align-items:baseline}
.sys .cnt{font-weight:600;font-size:13px;min-width:38px;text-align:right;
  color:hsl(var(--info))}
.sys code{font-size:12px;background:hsl(var(--muted));padding:1px 6px;
  border-radius:4px;font-family:ui-monospace,Menlo,monospace}
.sys .adv{color:hsl(var(--muted-foreground));display:block;margin-top:3px}

/* ---- toolbar ---- */
.bar{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-bottom:14px;
  position:sticky;top:0;background:hsl(var(--background));padding:14px 0 12px;z-index:20;
  border-bottom:1px solid hsl(var(--border))}
.btn{font:inherit;font-size:13px;font-weight:500;height:32px;padding:0 12px;
  display:inline-flex;align-items:center;gap:6px;white-space:nowrap;cursor:pointer;
  background:transparent;color:hsl(var(--foreground));
  border:1px solid transparent;border-radius:calc(var(--radius) - 2px)}
.btn:hover{background:hsl(var(--accent))}
.btn.outline{border-color:hsl(var(--border))}
.btn[aria-pressed=true]{background:hsl(var(--primary));color:hsl(var(--primary-foreground));
  border-color:hsl(var(--primary))}
.btn .cnt{font-size:11px;opacity:.65;font-variant-numeric:tabular-nums}
.input{font:inherit;font-size:13px;height:32px;padding:0 12px;
  border:1px solid hsl(var(--input));border-radius:calc(var(--radius) - 2px);
  background:hsl(var(--background));color:hsl(var(--foreground));min-width:230px}
.input::placeholder{color:hsl(var(--muted-foreground))}
.sep{width:1px;height:20px;background:hsl(var(--border));margin:0 4px}
.spacer{flex:1}
.tally{color:hsl(var(--muted-foreground));font-size:12px;white-space:nowrap}
.kbd{font-family:ui-monospace,Menlo,monospace;font-size:10px;
  border:1px solid hsl(var(--border));border-bottom-width:2px;border-radius:4px;
  padding:1px 5px;color:hsl(var(--muted-foreground));background:hsl(var(--muted))}

/* ---- group row ---- */
.grp{background:hsl(var(--card));border:1px solid hsl(var(--border));
  border-radius:var(--radius);margin-bottom:6px;overflow:hidden;
  transition:border-color .12s,opacity .12s}
.grp[open]{border-color:hsl(var(--ring))}
.grp.done{opacity:.45}
.grp.cursor{border-color:hsl(var(--info));box-shadow:0 0 0 1px hsl(var(--info))}
.gh{display:grid;
  grid-template-columns:14px 18px 74px minmax(140px,1.05fr) minmax(110px,.95fr) 2fr 96px;
  gap:12px;align-items:center;padding:11px 16px;cursor:pointer;user-select:none;
  list-style:none}
.gh::-webkit-details-marker{display:none}
.gh:hover{background:hsl(var(--accent))}
.chev{color:hsl(var(--muted-foreground));font-size:10px;transition:transform .15s}
.grp[open] .chev{transform:rotate(90deg)}
.chk{width:16px;height:16px;border:1px solid hsl(var(--border));border-radius:4px;
  display:grid;place-items:center;font-size:10px;color:transparent;
  background:hsl(var(--background))}
.chk:hover{border-color:hsl(var(--ring))}
.grp.done .chk{background:hsl(var(--success));border-color:hsl(var(--success));color:hsl(var(--on-status))}
.badge{font-size:11px;font-weight:500;padding:2px 0;border-radius:999px;
  text-align:center;border:1px solid transparent}
.badge.critical{color:hsl(var(--destructive));
  background:hsl(var(--destructive)/.1);border-color:hsl(var(--destructive)/.25)}
.badge.review{color:hsl(var(--warning));
  background:hsl(var(--warning)/.1);border-color:hsl(var(--warning)/.25)}
.badge.skip{color:hsl(var(--skip));
  background:hsl(var(--skip)/.12);border-color:hsl(var(--skip)/.3)}
.grp.skip{border-left:3px solid hsl(var(--skip))}
.gidbar{display:flex;align-items:center;gap:10px;padding:10px 0 2px;flex-wrap:wrap}
.gidlbl{font-size:11px;color:hsl(var(--muted-foreground))}
.gidval{font:inherit;font-family:ui-monospace,Menlo,monospace;font-size:13px;
  border:1px solid hsl(var(--input));border-radius:calc(var(--radius) - 2px);
  background:hsl(var(--muted));color:hsl(var(--foreground));padding:3px 9px;width:13ch}
.gidhint{font-size:11px;color:hsl(var(--muted-foreground));opacity:.75}
.badge.ok{color:hsl(var(--success));
  background:hsl(var(--success)/.1);border-color:hsl(var(--success)/.25)}
.gname{font-weight:500}
.gco,.ghl{color:hsl(var(--muted-foreground))}
.gname,.gco,.ghl{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.gid{color:hsl(var(--muted-foreground));text-align:right;opacity:.7}

/* ---- expanded body ---- */
.body{padding:4px 16px 16px;border-top:1px solid hsl(var(--border))}
.find{padding:12px 0;border-bottom:1px solid hsl(var(--border))}
.find:last-of-type{border-bottom:0}
.fhead{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
.dot{width:6px;height:6px;border-radius:50%;flex:none;transform:translateY(-1px)}
.find.critical .dot{background:hsl(var(--destructive))}
.find.review .dot{background:hsl(var(--warning))}
.find.contributor .dot{background:hsl(var(--muted-foreground))}
.ftitle{font-weight:500}
.fdetail{color:hsl(var(--muted-foreground))}
.ev{display:grid;grid-template-columns:92px 1fr;gap:4px 14px;margin:8px 0 0 14px;font-size:13px}
.ev dt{color:hsl(var(--muted-foreground));font-size:11px;padding-top:1px}
.ev dd{margin:0;overflow-wrap:anywhere}

/* ---- fixes ---- */
.fixes{margin-top:14px;border:1px solid hsl(var(--success)/.35);
  border-radius:calc(var(--radius) - 2px);background:hsl(var(--success)/.05);padding:13px 15px}
.fixes h3{font-size:12px;font-weight:600;margin:0 0 9px;color:hsl(var(--success))}
.fixes.has-master{border-color:hsl(var(--info)/.4);background:hsl(var(--info)/.05)}
.fixes.has-master h3{color:hsl(var(--info))}
.fixes table{width:auto}
.fixes th,.fixes td{border:0;padding:3px 14px 3px 0;font-size:13px;white-space:normal}
.fixes th{font-weight:400;color:hsl(var(--muted-foreground));text-align:left}
.fixes .was{color:hsl(var(--muted-foreground));text-decoration:line-through;
  text-decoration-color:hsl(var(--muted-foreground)/.5)}
.fixes .arrow{color:hsl(var(--muted-foreground));padding:0 2px}
.fixes .fix{color:hsl(var(--success));font-weight:500}
.fixes .mrow th,.fixes .mrow td{padding-bottom:8px}
.fixes .mrow th{font-weight:500;color:hsl(var(--foreground))}
.fixes .mrow .fix{color:hsl(var(--info));font-weight:600}
.fixes .subhead th{padding:12px 0 4px;font-size:11px;font-weight:600;
  color:hsl(var(--muted-foreground));text-transform:uppercase;letter-spacing:.05em}
.fixes .auto{color:hsl(var(--muted-foreground))}
.fixes .why{color:hsl(var(--muted-foreground));font-size:11px}
.fnote{color:hsl(var(--muted-foreground));font-size:11px;margin:9px 0 0;max-width:64ch}

/* ---- comparison table ---- */
.tw{overflow-x:auto;margin-top:14px;border:1px solid hsl(var(--border));
  border-radius:calc(var(--radius) - 2px)}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:6px 11px;text-align:left;border-bottom:1px solid hsl(var(--border));
  white-space:nowrap;max-width:300px;overflow:hidden;text-overflow:ellipsis}
tbody tr:last-child th,tbody tr:last-child td{border-bottom:0}
thead th{background:hsl(var(--muted));font-size:11px;font-weight:500;
  color:hsl(var(--muted-foreground))}
thead .sf{display:block;font-weight:400;opacity:.65;
  font-family:ui-monospace,Menlo,monospace;font-size:10px}
th.fld{font-weight:400;color:hsl(var(--muted-foreground));white-space:normal;
  width:180px;font-size:12px}
.col-master{border-left:2px solid hsl(var(--success));border-right:2px solid hsl(var(--success))}
.col-newmaster{border-left:2px solid hsl(var(--info));border-right:2px solid hsl(var(--info));
  color:hsl(var(--info))}
.col-surv{background:hsl(var(--muted));font-weight:500}
.col-fix{background:hsl(var(--success)/.07)}
td.fix{color:hsl(var(--success));font-weight:500}
td.won{background:hsl(var(--survive-bg))}
td.lost{background:hsl(var(--lost-bg));color:hsl(var(--destructive));
  text-decoration:line-through;text-decoration-color:hsl(var(--destructive)/.4)}
td.blank{color:hsl(var(--muted-foreground));opacity:.5}
tr.flagged th.fld{box-shadow:inset 3px 0 0 hsl(var(--info));
  color:hsl(var(--foreground));font-weight:500}
.foot{display:flex;gap:18px;flex-wrap:wrap;align-items:center;margin-top:10px;
  color:hsl(var(--muted-foreground));font-size:11px}
.foot i{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px;
  vertical-align:-1px}
.tgl{font:inherit;font-size:11px;background:none;border:0;color:hsl(var(--info));
  cursor:pointer;padding:0;text-decoration:underline;margin-left:auto}

.fixes.blocked{border-color:hsl(var(--warning)/.4);background:hsl(var(--warning)/.05)}
.fixes.blocked h3{color:hsl(var(--warning))}
.fixes.blocked .fnote{margin-top:0}
.empty{color:hsl(var(--muted-foreground));padding:40px;text-align:center;
  border:1px dashed hsl(var(--border));border-radius:var(--radius)}
.clean{columns:5;column-gap:16px}
.clean a{color:hsl(var(--muted-foreground));text-decoration:none;display:block;padding:2px 0}
.clean a:hover{color:hsl(var(--info))}
@media(max-width:900px){
  .cards{grid-template-columns:repeat(2,1fr)}
  .gh{grid-template-columns:14px 18px 70px 1fr 78px}
  .gco,.ghl{display:none}
  .clean{columns:2}
}
"""

#: The stylesheet the report ships: token contract first, then rules that may only
#: reference those tokens. tests/test_tokens.py fails the build if a rule below
#: names a token this contract does not define, or writes a raw colour literal.
CSS = tokens.css_variables() + STYLES

JS = """
const groups=[...document.querySelectorAll('.grp')];
const q=document.getElementById('q');
const KEY='rlqa:'+document.body.dataset.source;
let done=new Set(JSON.parse(localStorage.getItem(KEY)||'[]'));
let status='all', code='all', hideDone=false, cursor=-1;

function save(){localStorage.setItem(KEY,JSON.stringify([...done]))}
function visible(){return groups.filter(g=>!g.hidden)}

function paint(){
  const queue=groups.filter(g=>g.dataset.status!=='ok');
  const n=queue.filter(g=>done.has(g.dataset.gid)).length;
  document.getElementById('pn').textContent=n;
  document.getElementById('pd').textContent=queue.length;
  document.getElementById('fill').style.width=(queue.length?n/queue.length*100:0)+'%';
}
function apply(){
  const term=q.value.trim().toLowerCase();
  let shown=0;
  for(const g of groups){
    const vis=(status==='all'||g.dataset.status===status)
           && (code==='all'||g.dataset.codes.split(' ').includes(code))
           && (!term||g.dataset.search.includes(term))
           && (!hideDone||!done.has(g.dataset.gid));
    g.hidden=!vis; if(vis) shown++;
  }
  document.getElementById('tally').textContent=shown+' shown';
  document.getElementById('none').hidden=shown>0;
  paint();
}
function toggle(g){
  const id=g.dataset.gid;
  done.has(id)?done.delete(id):done.add(id);
  g.classList.toggle('done',done.has(id));
  save();
  if(hideDone) apply(); else paint();
}
function focus(i){
  const vis=visible(); if(!vis.length) return;
  cursor=Math.max(0,Math.min(i,vis.length-1));
  groups.forEach(g=>g.classList.remove('cursor'));
  const g=vis[cursor]; g.classList.add('cursor');
  g.scrollIntoView({block:'nearest',behavior:'smooth'});
}

for(const g of groups){
  if(done.has(g.dataset.gid)) g.classList.add('done');
  g.querySelector('.chk').addEventListener('click',e=>{
    e.preventDefault(); e.stopPropagation(); toggle(g);
  });
}
for(const b of document.querySelectorAll('.btn[data-kind]')){
  b.onclick=()=>{
    const k=b.dataset.kind;
    if(k==='status') status=b.dataset.val; else code=b.dataset.val;
    for(const o of document.querySelectorAll(`.btn[data-kind="${k}"]`))
      o.setAttribute('aria-pressed',String(o===b));
    cursor=-1; apply();
  };
}
const hd=document.getElementById('hidedone');
hd.onclick=()=>{hideDone=!hideDone;hd.setAttribute('aria-pressed',String(hideDone));apply()};
document.getElementById('reset').onclick=()=>{
  if(!confirm('Clear review progress for this export?')) return;
  done=new Set(); save();
  groups.forEach(g=>g.classList.remove('done')); apply();
};
q.oninput=()=>{cursor=-1;apply()};
for(const g of document.querySelectorAll('.gidval')){
  g.onclick=e=>{e.stopPropagation(); g.select();};
}

for(const t of document.querySelectorAll('.tgl')){
  t.onclick=e=>{
    e.preventDefault(); e.stopPropagation();
    const tb=document.getElementById(t.dataset.target);
    const all=tb.classList.toggle('show-all');
    for(const r of tb.querySelectorAll('tr[data-same="1"]')) r.hidden=!all;
    t.textContent=all?'Show only differences':'Show all '+t.dataset.total+' fields';
  };
}
for(const a of document.querySelectorAll('.clean a')){
  a.onclick=e=>{e.preventDefault();q.value=a.textContent;apply();
    window.scrollTo({top:0,behavior:'smooth'})};
}
document.addEventListener('keydown',e=>{
  if(e.target.tagName==='INPUT'){if(e.key==='Escape')e.target.blur();return}
  if(e.metaKey||e.ctrlKey||e.altKey) return;
  const vis=visible();
  if(e.key==='j'){e.preventDefault();focus(cursor+1)}
  else if(e.key==='k'){e.preventDefault();focus(cursor-1)}
  else if(e.key==='x'&&vis[cursor]){e.preventDefault();toggle(vis[cursor])}
  else if(e.key==='Enter'&&vis[cursor]){e.preventDefault();vis[cursor].open=!vis[cursor].open}
  else if(e.key==='/'){e.preventDefault();q.focus()}
});
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
    cols = [c for c in g.populated_columns() if g.schema.tier(c) != "noise" or c in highlight]
    if v.status == "ok":
        # Clean groups exist for spot-checking, not reviewing. A short identity table
        # confirms the call at a glance and keeps 238 skippable groups from dominating
        # the page weight.
        cols = [c for c in cols if c in set(g.schema.display_columns)]
    differing = set(g.differing_columns())

    # "After merge" is RingLead's prediction of what will happen, defects included --
    # it is not a target. Where the right value is derivable, a "Should be" column
    # states it, so a reviewer knows what to set rather than only what is wrong.
    #
    # Corrections are keyed by logical field name; this table iterates real column
    # names. Resolve before matching or nothing ever lines up.
    #
    # A pending master change makes every value here provisional -- the surviving
    # record itself is about to change -- so the column is dropped, matching the
    # correction sheet, which holds those groups back for the same reason.
    fixes = {g.schema.resolve(c.column) or c.column: c.value for c in v.corrections}
    if v.projected:
        # Values the master change produces on its own belong here too -- the column
        # answers "what should this field end up as", not "what must you type".
        for col in g.populated_columns():
            if g.schema.tier(col) == "noise" or col in fixes:
                continue
            after = v.projected.group.surviving.get(col)
            if after != g.surviving.get(col):
                fixes[col] = after

    order = [g.surviving, g.master, *g.duplicates]
    heads = ['<th class="fld">Field</th>', '<th class="col-surv">After merge</th>']
    if fixes:
        heads.append('<th class="col-fix">Should be</th>')
    mc = v.master_change
    for rec in order[1:]:
        cls = "col-master" if rec.role == "master" else ""
        label = _esc(rec.label)
        if mc and rec.record_id == mc.record.record_id:
            cls = (cls + " col-newmaster").strip()
            label = "Should be master"
        elif mc and rec.role == "master":
            label = "Master (change)"
        heads.append(
            f'<th class="{cls}">{label}'
            f'<span class="sf">{_esc(rec.record_id)}</span></th>'
        )

    rows = []
    for col in cols:
        same = col not in differing and col not in highlight
        survivor = g.surviving.get(col)
        cells = [
            f'<th class="fld">{_esc(g.schema.label(col))}</th>',
            f'<td class="col-surv">{_esc(survivor) or "—"}</td>',
        ]
        if fixes:
            target = fixes.get(col)
            cells.append(
                f'<td class="col-fix fix">{_esc(target)}</td>'
                if target and target != survivor
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
        '<span><i style="background:hsl(var(--survive-bg));'
        'border:1px solid hsl(var(--success))"></i>Survives</span>'
        '<span><i style="background:hsl(var(--lost-bg));'
        'border:1px solid hsl(var(--destructive))"></i>Lost in merge</span>'
        '<span><i style="border:2px solid hsl(var(--success))"></i>Master record</span>'
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


def _auto_changes(v: Verdict) -> list[tuple[str, str, str]]:
    """Fields the master change fixes by itself: (label, today, after).

    RingLead recomputes the survivor once the master changes, so these need no
    manual action -- but showing them is what makes the recommendation legible.
    """
    if not v.projected:
        return []
    manual = {v.group.schema.resolve(c.column) or c.column for c in v.corrections}
    out = []
    for col in v.group.populated_columns():
        if v.group.schema.tier(col) == "noise" or col in manual:
            continue
        before, after = v.group.surviving.get(col), v.projected.group.surviving.get(col)
        if before != after:
            out.append((v.group.schema.label(col), before, after))
    return out


def _fixes(v: Verdict) -> str:
    """The complete end state: one pass, no re-export loop."""
    mc = v.master_change
    if v.corrections_blocked:
        return (
            '<div class="fixes blocked"><h3>No values recommended</h3>'
            f'<p class="fnote">{_esc(v.corrections_blocked)}</p></div>'
        )
    if not v.corrections and not mc:
        return ""

    sections = []
    if mc:
        sections.append(
            '<tr class="mrow"><th>Master record</th>'
            f'<td class="was">{_esc(v.group.master.record_id)}</td>'
            '<td class="arrow">&rarr;</td>'
            f'<td class="fix">{_esc(mc.record.record_id)}</td>'
            f'<td class="why">{_esc(mc.why)}'
            + ("" if mc.corroborated else " — single signal, confirm first")
            + "</td></tr>"
        )

    auto = _auto_changes(v)
    if auto:
        sections.append(
            '<tr class="subhead"><th colspan="5">RingLead recomputes these once the '
            "master changes — no action needed</th></tr>"
        )
        sections += [
            f"<tr><th>{_esc(label)}</th>"
            f'<td class="was">{_esc(before) or "—"}</td>'
            '<td class="arrow">&rarr;</td>'
            f'<td class="auto">{_esc(after) or "—"}</td><td class="why"></td></tr>'
            for label, before, after in auto[:12]
        ]

    if v.corrections:
        if mc:
            sections.append(
                '<tr class="subhead"><th colspan="5">Then set these by hand</th></tr>'
            )
        target = v.projected.group if v.projected else v.group
        sections += [
            f"<tr><th>{_esc(v.group.schema.label(c.column))}</th>"
            f'<td class="was">{_esc(target.surviving.get(c.column)) or "—"}</td>'
            '<td class="arrow">&rarr;</td>'
            f'<td class="fix">{_esc(c.value)}</td>'
            f'<td class="why">{_esc(c.why)}</td></tr>'
            for c in v.corrections
        ]

    heading = "Make these changes in RingLead" if mc else "Set these on the surviving record"
    return (
        f'<div class="fixes{" has-master" if mc else ""}"><h3>{heading}</h3>'
        f'<table>{"".join(sections)}</table></div>'
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
<details class="grp {v.status}" data-status="{v.status}" data-gid="{_esc(g.group_id)}"
         data-codes="{_esc(codes)}" data-search="{_esc(search)}">
  <summary class="gh">
    <span class="chev">&#9654;</span>
    <span class="chk" role="checkbox" aria-checked="false" title="Mark reviewed (x)">&#10003;</span>
    <span class="badge {v.status}">{STATUS_LABEL[v.status]}</span>
    <span class="gname">{_esc(name)}</span>
    <span class="gco">{_esc(company)}</span>
    <span class="ghl">{_esc(v.headline)}</span>
    <span class="gid mono">{_esc(g.group_id)}</span>
  </summary>
  <div class="body">
    <div class="gidbar">
      <span class="gidlbl">Group ID</span>
      <input class="gidval mono" value="{_esc(g.group_id)}" readonly
             aria-label="Group ID, click to select">
      <span class="gidhint">click to select, then copy</span>
    </div>
    {_findings(v)}{_fixes(v)}{_table(v, f"t{idx}")}
  </div>
</details>"""


def render(verdicts: list[Verdict], *, source: str, total_rows: int) -> str:
    verdicts = sorted(verdicts, key=lambda v: v.sort_key)
    counts = Counter(v.status for v in verdicts)
    total = len(verdicts) or 1
    code_counts = Counter(f.code for v in verdicts for f in v.findings if v.needs_review)


    filters = "".join(
        f'<button class="btn outline" data-kind="code" data-val="{_esc(c)}">'
        f'{_esc(c)} <span class="cnt">{n}</span></button>'
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
<style>{CSS}</style></head><body data-source="{_esc(source)}"><div class="wrap">

<div class="head">
  <div>
    <h1>RingLead merge QA</h1>
    <div class="brandrule"></div>
    <p class="sub">{_esc(source)} · {total_rows:,} rows · {len(verdicts)} groups · {generated}</p>
  </div>
  <div class="prog">
    <div class="lbl"><span>Review progress</span>
      <span><b id="pn">0</b> of <b id="pd">0</b></span></div>
    <div class="track"><div class="fill" id="fill"></div></div>
    <button class="reset" id="reset">Clear progress</button>
  </div>
</div>

<div class="cards">
  <div class="card skip"><div class="n">{counts['skip']}</div><div class="l">Do not merge</div></div>
  <div class="card crit"><div class="n">{counts['critical']}</div><div class="l">Needs a fix</div></div>
  <div class="card rev"><div class="n">{counts['review']}</div><div class="l">Needs review</div></div>
  <div class="card ok"><div class="n">{counts['ok']}</div><div class="l">Clean — skip</div></div>
  <div class="card"><div class="n">{round(counts['ok'] / total * 100)}%</div><div class="l">Of the file skipped</div></div>
</div>


<div class="bar">
  <button class="btn" data-kind="status" data-val="all" aria-pressed="true">All <span class="cnt">{len(verdicts)}</span></button>
  <button class="btn" data-kind="status" data-val="skip">Skip <span class="cnt">{counts['skip']}</span></button>
  <button class="btn" data-kind="status" data-val="critical">Fix <span class="cnt">{counts['critical']}</span></button>
  <button class="btn" data-kind="status" data-val="review">Review <span class="cnt">{counts['review']}</span></button>
  <button class="btn" data-kind="status" data-val="ok">Clean <span class="cnt">{counts['ok']}</span></button>
  <span class="sep"></span>
  <button class="btn outline" id="hidedone" aria-pressed="false">Hide reviewed</button>
  <span class="sep"></span>
  <button class="btn outline" data-kind="code" data-val="all" aria-pressed="true">Any issue</button>
  {filters}
  <span class="spacer"></span>
  <input class="input" id="q" placeholder="Search name, company, email, ID">
  <span class="tally" id="tally"></span>
  <span class="kbd">j</span><span class="kbd">k</span><span class="kbd">x</span><span class="kbd">/</span>
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
