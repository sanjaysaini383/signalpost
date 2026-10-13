"""Generate a single self-contained HTML dashboard from batch envelopes (no server, no dependencies)."""
import json
from pathlib import Path

TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Signalpost Report</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{--bg:#f4f5f7;--panel:#ffffff;--text:#101828;--muted:#667085;--faint:#98a2b3;--line:#e4e7ec;--soft:#f9fafb;
--accent:#3b5bdb;--accent-soft:#eef2ff;--ok:#067647;--ok-soft:#ecfdf3;--warn:#b54708;--warn-soft:#fffaeb;--bad:#b42318;--bad-soft:#fef3f2;
--shadow:0 1px 2px rgba(16,24,40,.05);--sans:'Inter',system-ui,-apple-system,'Segoe UI',sans-serif;--mono:'JetBrains Mono',ui-monospace,Consolas,monospace}
@media (prefers-color-scheme:dark){:root{--bg:#0c111d;--panel:#141b2b;--text:#f2f4f7;--muted:#98a3b3;--faint:#667085;--line:#232c3f;--soft:#101726;
--accent:#8ea2ff;--accent-soft:#1b2447;--ok:#47cd89;--ok-soft:#10261b;--warn:#fdb022;--warn-soft:#2b2110;--bad:#f97066;--bad-soft:#2e1513;--shadow:none}}
*{box-sizing:border-box}html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 var(--sans);-webkit-font-smoothing:antialiased}
.app{display:grid;grid-template-rows:auto 1fr;height:100vh}
header{background:var(--panel);border-bottom:1px solid var(--line);padding:14px 24px;display:flex;align-items:center;gap:28px;flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:10px;font-weight:700;font-size:16px;letter-spacing:-.01em}
.logo{width:26px;height:26px;border-radius:7px;background:var(--accent);color:#fff;display:grid;place-items:center;font-size:14px}
.brand span{color:var(--muted);font-weight:500;margin-left:2px}
.kpis{display:flex;gap:10px;flex-wrap:wrap;margin-left:auto}
.kpi{padding:6px 14px;border:1px solid var(--line);border-radius:10px;background:var(--soft);min-width:96px}
.kpi b{display:block;font-size:17px;font-weight:600;line-height:1.2;font-variant-numeric:tabular-nums}
.kpi small{color:var(--muted);font-size:11.5px}
main{display:grid;grid-template-columns:360px 1fr;min-height:0}
aside{background:var(--panel);border-right:1px solid var(--line);display:flex;flex-direction:column;min-height:0}
.tools{padding:14px;display:grid;gap:10px;border-bottom:1px solid var(--line)}
input,select{width:100%;height:36px;padding:0 12px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--text);font:inherit;outline:none}
input:focus,select:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
.count{font-size:12px;color:var(--muted);padding:0 2px}
#list{overflow:auto;flex:1}
.row{padding:11px 16px;border-bottom:1px solid var(--line);cursor:pointer;border-left:3px solid transparent}
.row:hover{background:var(--soft)}.row.sel{background:var(--accent-soft);border-left-color:var(--accent)}
.row .n{font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.row .m{display:flex;gap:8px;color:var(--muted);font-size:12px;margin-top:2px}.row .m .mono{font-family:var(--mono)}
section#detail{overflow:auto;padding:28px 36px 56px}
.wrap{max-width:900px;margin:0 auto}
.empty{color:var(--muted);text-align:center;padding:90px 20px}
.hero{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:22px 24px;box-shadow:var(--shadow)}
.hero h2{margin:0 0 10px;font-size:22px;font-weight:600;letter-spacing:-.015em}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.chip{display:inline-flex;align-items:center;gap:6px;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:500;background:var(--soft);color:var(--muted);border:1px solid var(--line)}
.chip.mono{font-family:var(--mono);font-size:11.5px}.chip.ok{background:var(--ok-soft);color:var(--ok);border-color:transparent}
.chip.warn{background:var(--warn-soft);color:var(--warn);border-color:transparent}.chip.bad{background:var(--bad-soft);color:var(--bad);border-color:transparent}
.secs{margin-top:10px}
.sum{margin:14px 0 0;color:var(--text);line-height:1.6;max-width:72ch}
.note{margin-top:14px;padding:10px 14px;border-radius:10px;font-size:13px;background:var(--warn-soft);color:var(--warn)}
.card{margin-top:18px;background:var(--panel);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);overflow:hidden}
.card>h3{margin:0;padding:12px 20px;font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);background:var(--soft);border-bottom:1px solid var(--line);display:flex;justify-content:space-between}
.card>h3 span{font-weight:500;letter-spacing:0;text-transform:none}
.kv{display:grid;grid-template-columns:200px 1fr;gap:4px 24px;padding:12px 20px;border-bottom:1px solid var(--line)}
.kv:last-child{border-bottom:0}
.k{color:var(--muted);font-size:13px;padding-top:1px}
.v{min-width:0;overflow-wrap:anywhere}.v .main{font-weight:500}
.v .as{color:var(--faint);font-size:12px;margin-left:8px;font-weight:400}
details{margin-top:6px}summary{cursor:pointer;color:var(--accent);font-size:12px;font-weight:500;list-style:none;user-select:none}
summary::-webkit-details-marker{display:none}summary::before{content:'\25B8';display:inline-block;margin-right:5px;transition:transform .15s}
details[open]>summary::before{transform:rotate(90deg)}
.ev{margin-top:8px;padding:10px 12px;background:var(--soft);border:1px solid var(--line);border-radius:8px;font-size:12.5px;display:grid;gap:4px}
.ev .l{display:inline-block;min-width:110px;color:var(--faint)}.ev .mono{font-family:var(--mono);font-size:12px}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.chg{display:flex;gap:10px;padding:10px 20px;border-bottom:1px solid var(--line);font-size:13px}.chg:last-child{border-bottom:0}
@media (max-width:860px){main{grid-template-columns:1fr;grid-template-rows:42vh 1fr}aside{border-right:0;border-bottom:1px solid var(--line)}
section#detail{padding:18px 14px 40px}.kv{grid-template-columns:1fr;gap:2px}.kpis{margin-left:0}header{padding:12px 14px}}
</style></head><body>
<div class="app">
<header><div class="brand"><div class="logo">S</div>Signalpost<span>Company profiles</span></div><div class="kpis" id="kpis"></div></header>
<main>
<aside><div class="tools">
<input id="q" placeholder="Search by name or org number" aria-label="Search">
<select id="f" aria-label="Filter"><option value="">All companies</option><option value="warn">With warnings</option>
<option value="chg">Changed since previous run</option><option value="site">Verified website</option><option value="fin">Has financials</option></select>
<div class="count" id="count"></div></div><div id="list"></div></aside>
<section id="detail"><div class="empty">Select a company to see its facts and evidence.</div></section>
</main></div>
<script id="data" type="application/json">__DATA__</script>
<script>
const P=JSON.parse(document.getElementById('data').textContent);
const $=id=>document.getElementById(id);
const has=(p,pre)=>p.facts.some(f=>f.field.startsWith(pre));
const fmt=v=>{if(v&&typeof v==='object'){if('amount'in v)return Number(v.amount).toLocaleString('en')+' '+(v.currency||'');
 if('role'in v)return v.name;if('address'in v)return[v.name,v.address,v.employees!=null?v.employees+' employees':''].filter(Boolean).join(' · ');return JSON.stringify(v)}
 if(v===true)return'Yes';if(v===false)return'No';return String(v)};
const label=s=>{let t=s;if(t.startsWith('financials:'))t=t.split(':').slice(1).reverse().join(' ');else if(t.startsWith('role:'))t=t.slice(5);else if(t.startsWith('social:'))t=t.slice(7);
 return t.replace(/[_:]/g,' ').trim().replace(/^./,c=>c.toUpperCase())};
const el=(t,c,x)=>{const e=document.createElement(t);if(c)e.className=c;if(x!=null)e.textContent=x;return e};
const link=u=>{if(!/^https?:\/\//.test(u))return el('span','mono',u);const a=el('a','mono',u.replace(/^https?:\/\//,'').slice(0,70));a.href=u;a.target='_blank';a.rel='noopener noreferrer';return a};
function kpis(){const n=P.length,f=P.reduce((s,p)=>s+p.facts.length,0);
 const items=[['Companies',n.toLocaleString('en')],['Facts',f.toLocaleString('en')],['Avg facts',(f/Math.max(n,1)).toFixed(1)],
 ['Warnings',P.filter(p=>p.warnings.length).length],['Changed',P.filter(p=>(p.changes_since_previous_run||[]).length).length],
 ['Websites',P.filter(p=>has(p,'website_verified')).length],['Financials',P.filter(p=>has(p,'financials:')).length]];
 $('kpis').replaceChildren(...items.map(([k,v])=>{const d=el('div','kpi');d.append(el('b',null,v),el('small',null,k));return d}))}
function filtered(){const q=$('q').value.trim().toLowerCase(),f=$('f').value;
 return P.filter(p=>(!q||(p.name||'').toLowerCase().includes(q)||p.organization_number.includes(q))&&
 (!f||(f==='warn'&&p.warnings.length)||(f==='chg'&&(p.changes_since_previous_run||[]).length)||(f==='site'&&has(p,'website_verified'))||(f==='fin'&&has(p,'financials:'))))}
function renderList(){const L=filtered();$('count').textContent=L.length.toLocaleString('en')+' of '+P.length.toLocaleString('en')+' companies';
 const box=$('list');box.replaceChildren(...L.slice(0,500).map(p=>{const r=el('div','row');r.append(el('div','n',p.name||'(unnamed)'));
 const m=el('div','m');m.append(el('span','mono',p.organization_number),el('span',null,p.facts.length+' facts'));if(p.status!=='active')m.append(el('span',null,p.status));r.append(m);
 r.onclick=()=>{document.querySelectorAll('.row.sel').forEach(x=>x.classList.remove('sel'));r.classList.add('sel');show(p)};return r}));
 if(L.length>500)box.append(el('div','empty','Showing first 500. Narrow the search.'))}
function factRow(f){const row=el('div','kv');row.append(el('div','k',label(f.field)));const v=el('div','v');const m=el('div','main',fmt(f.value));
 if(f.as_of)m.append(el('span','as','as of '+f.as_of));if(f.stale)m.append(el('span','chip warn','stale: source unavailable on last run'));v.append(m);
 const det=document.createElement('details');det.append(el('summary',null,'Evidence'));const ev=el('div','ev');
 const add=(l,node)=>{const r=el('div');r.append(el('span','l',l));r.append(node);ev.append(r)};
 add('Source',link(f.source_url));add('Retrieved',el('span','mono',f.retrieved_at));add('Evidence',el('span',null,f.evidence));add('Why this company',el('span',null,f.explanation));
 det.append(ev);v.append(det);row.append(v);return row}
function show(p){const d=$('detail');d.replaceChildren();const w=el('div','wrap');d.append(w);
 const hero=el('div','hero');hero.append(el('h2',null,p.name||p.organization_number));const c=el('div','chips');
 c.append(el('span','chip mono','Org '+p.organization_number),el('span','chip '+(p.status==='active'?'ok':'bad'),p.status));
 const flag=['bankrupt','under_liquidation','under_forced_dissolution'].find(k=>p.facts.some(f=>f.field===k&&f.value===true));if(flag)c.append(el('span','chip bad',label(flag)));
 c.append(el('span','chip',p.facts.length+' facts'),el('span','chip','Generated '+p.generated_at));if(p.previous_run)c.append(el('span','chip','Previous run '+p.previous_run));
 hero.append(c);
 if(p.sections){const st=el('div','chips secs');for(const[k,v]of Object.entries(p.sections)){const cls=v.availability==='available'?'ok':(v.availability==='not_available'||v.availability==='not_applicable')?'':'warn';
  const ch=el('span','chip '+cls,k.replace(/_/g,' ')+': '+v.availability.replace('_',' '));if(v.note)ch.title=v.note;st.append(ch)}hero.append(st)}
 if(p.summary)hero.append(el('p','sum',p.summary));p.warnings.forEach(x=>hero.append(el('div','note',x)));w.append(hero);
 const ic=(p.identity_check||[]),cn=(p.coverage_notes||[]);
 if(ic.length||cn.length){const k=el('div','card');k.append(el('h3',null,'Identity and coverage'));
  ic.forEach(x=>{const r=el('div','chg');r.append(el('span','chip ok','verified'),el('span',null,x));k.append(r)});
  cn.forEach(x=>{const r=el('div','chg');r.append(el('span','chip','missing'),el('span',null,x));k.append(r)});w.append(k)}
 const ch=p.changes_since_previous_run||[];if(ch.length){const k=el('div','card');k.append(el('h3',null,'Changes since previous run'));
  ch.forEach(x=>{const r=el('div','chg');r.append(el('span','chip warn',x.change),el('span',null,label(x.field)+': '+(x.old!==undefined?fmt(x.old)+' → ':'')+(x.new!==undefined?fmt(x.new):'')));k.append(r)});w.append(k)}
 const G={};p.facts.forEach(f=>{const g=f.field.startsWith('financials:')?'Financials':f.field.startsWith('role:')?'Roles':f.field==='establishment'?'Establishments':
  /^(website|social)/.test(f.field)||/^(business_summary|product_or_service|location)$/.test(f.field)?'Website':'Register';(G[g]=G[g]||[]).push(f)});
 for(const g of['Register','Financials','Roles','Establishments','Website']){if(!G[g])continue;const k=el('div','card');const h=el('h3',null,g);h.append(el('span',null,G[g].length+' facts'));k.append(h);G[g].forEach(f=>k.append(factRow(f)));w.append(k)}
 d.scrollTop=0}
$('q').oninput=renderList;$('f').onchange=renderList;kpis();renderList();
</script></body></html>
"""


def _from_envelope(env):
    p = dict(env.get("profile") or {})
    p.setdefault("organization_number", env["organisation_number"])
    p.setdefault("facts", [])
    p.setdefault("warnings", [])
    p.setdefault("status", (env.get("legal_identity") or {}).get("status") or env.get("state"))
    p["name"] = p.get("name") or (env.get("legal_identity") or {}).get("legal_name")
    p["sections"] = env.get("sections")
    p["generated_at"] = (env.get("run") or {}).get("completed_at")
    p["previous_run"] = (env.get("refresh") or {}).get("previous_completed_at")
    p["changes_since_previous_run"] = [{"field": c["field"], "change": c["change_type"], "old": c.get("previous_value"),
                                        "new": c.get("current_value")} for c in env.get("changes", [])]
    return p


def build_report(out_dir, dest, limit=None, envelopes=None):
    profiles = [_from_envelope(json.loads(line)) for line in Path(envelopes).read_text("utf-8").splitlines() if line.strip()]
    if limit:
        profiles = profiles[:limit]
    # </ would end the script element; escape it so profile text can never break out of the data block
    data = json.dumps(profiles, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    Path(dest).write_text(TEMPLATE.replace("__DATA__", data), "utf-8")
    return len(profiles)
