"""Generate a single self-contained HTML report from saved profiles (no server, no dependencies)."""
import json
from pathlib import Path

TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Signalpost Report</title>
<style>
:root{--bg:#f6f7f9;--panel:#fff;--text:#1b1f24;--muted:#5f6b7a;--line:#e3e7ec;--accent:#2457d6;--warn:#b45309;--ok:#15803d;--chip:#eef1f6}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0f1318;--panel:#171c23;--text:#e6e9ee;--muted:#98a3b3;--line:#2a323d;--accent:#7aa2ff;--warn:#f0b35a;--ok:#5fcf8a;--chip:#222a35}}
:root[data-theme=dark]{--bg:#0f1318;--panel:#171c23;--text:#e6e9ee;--muted:#98a3b3;--line:#2a323d;--accent:#7aa2ff;--warn:#f0b35a;--ok:#5fcf8a;--chip:#222a35}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 system-ui,sans-serif}
header{padding:14px 16px;border-bottom:1px solid var(--line);background:var(--panel);display:flex;flex-wrap:wrap;gap:8px 20px;align-items:baseline}
h1{font-size:17px;margin:0}.stat{color:var(--muted)}.stat b{color:var(--text)}
main{display:grid;grid-template-columns:minmax(260px,340px) 1fr;height:calc(100vh - 56px)}
aside{border-right:1px solid var(--line);background:var(--panel);display:flex;flex-direction:column;min-height:0}
.tools{padding:10px;border-bottom:1px solid var(--line);display:grid;gap:8px}
input,select{width:100%;padding:7px 9px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--text);font:inherit}
#list{overflow:auto;flex:1}.row{padding:9px 12px;border-bottom:1px solid var(--line);cursor:pointer}
.row:hover,.row.sel{background:var(--chip)}.row small{color:var(--muted);display:block}
section#detail{overflow:auto;padding:16px 20px;min-width:0}
.chip{display:inline-block;padding:1px 8px;border-radius:10px;background:var(--chip);color:var(--muted);font-size:12px;margin-right:6px}
.chip.warn{color:var(--warn)}.chip.ok{color:var(--ok)}
h2{margin:0 0 4px;font-size:20px}h3{margin:20px 0 6px;font-size:13px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:8px}
td,th{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{width:210px;font-weight:500;color:var(--muted)}td .val{word-break:break-word}
a{color:var(--accent)}details summary{cursor:pointer;color:var(--muted);font-size:12px}details div{margin-top:4px;font-size:12px;color:var(--muted)}
.chg{padding:6px 10px;border-left:3px solid var(--warn);background:var(--panel);margin:4px 0}
.empty{color:var(--muted);padding:40px}
@media (max-width:760px){main{grid-template-columns:1fr;height:auto}aside{max-height:45vh}th{width:120px}}
</style></head><body>
<header><h1>Signalpost report</h1><span class="stat" id="stats"></span></header>
<main>
<aside><div class="tools">
<input id="q" placeholder="Search name or org number" aria-label="Search">
<select id="f" aria-label="Filter"><option value="">All companies</option><option value="warn">With warnings</option>
<option value="chg">With changes since previous run</option><option value="site">With verified website</option><option value="fin">With financials</option></select>
</div><div id="list"></div></aside>
<section id="detail"><div class="empty">Select a company on the left.</div></section>
</main>
<script id="data" type="application/json">__DATA__</script>
<script>
const P=JSON.parse(document.getElementById('data').textContent);
const $=id=>document.getElementById(id);
const has=(p,pre)=>p.facts.some(f=>f.field.startsWith(pre));
const fmt=v=>{if(v&&typeof v==='object'){if('amount'in v)return Number(v.amount).toLocaleString('en')+' '+(v.currency||'');
 if('role'in v)return v.name; if('address'in v)return [v.name,v.address,v.employees!=null?v.employees+' employees':''].filter(Boolean).join(' - ');return JSON.stringify(v)}return String(v)};
const el=(t,c,x)=>{const e=document.createElement(t);if(c)e.className=c;if(x!=null)e.textContent=x;return e};
const link=(u)=>{if(!/^https?:\/\//.test(u))return el('span',null,u);const a=el('a',null,u.replace(/^https?:\/\//,'').slice(0,60));a.href=u;a.target='_blank';a.rel='noopener noreferrer';return a};
function stats(){const n=P.length,f=P.reduce((s,p)=>s+p.facts.length,0),w=P.filter(p=>p.warnings.length).length,c=P.filter(p=>(p.changes_since_previous_run||[]).length).length;
 const parts=[['companies',n],['facts',f],['avg facts/company',(f/Math.max(n,1)).toFixed(1)],['with warnings',w],['with changes',c],['verified website',P.filter(p=>has(p,'website_verified')).length],['with financials',P.filter(p=>has(p,'financials:')).length]];
 $('stats').replaceChildren(...parts.flatMap(([k,v])=>{const s=el('span','stat');s.append(k+': ',el('b',null,v));return[s]}))}
function filtered(){const q=$('q').value.trim().toLowerCase(),f=$('f').value;
 return P.filter(p=>(!q||(p.name||'').toLowerCase().includes(q)||p.organization_number.includes(q))&&
 (!f||(f==='warn'&&p.warnings.length)||(f==='chg'&&(p.changes_since_previous_run||[]).length)||(f==='site'&&has(p,'website_verified'))||(f==='fin'&&has(p,'financials:'))))}
function renderList(){const L=filtered();const box=$('list');box.replaceChildren(...L.slice(0,500).map(p=>{const r=el('div','row');r.append(el('div',null,p.name||'(unnamed)'),el('small',null,p.organization_number+' - '+p.facts.length+' facts'+(p.status!=='active'?' - '+p.status:'')));
 r.onclick=()=>{document.querySelectorAll('.row.sel').forEach(x=>x.classList.remove('sel'));r.classList.add('sel');show(p)};return r}));
 if(L.length>500)box.append(el('div','empty','Showing first 500 of '+L.length+'. Narrow the search.'))}
function show(p){const d=$('detail');d.replaceChildren();d.append(el('h2',null,p.name||p.organization_number));
 const meta=el('div');meta.append(el('span','chip',p.organization_number),el('span','chip '+(p.status==='active'?'ok':'warn'),p.status),el('span','chip','generated '+p.generated_at));
 if(p.previous_run)meta.append(el('span','chip','previous run '+p.previous_run));d.append(meta);
 p.warnings.forEach(w=>d.append(el('div','chg','Warning: '+w)));
 const ch=p.changes_since_previous_run||[];if(ch.length){d.append(el('h3',null,'Changes since previous run'));ch.forEach(c=>d.append(el('div','chg',c.field+' '+c.change+': '+(c.old!==undefined?fmt(c.old)+' -> ':'')+(c.new!==undefined?fmt(c.new):''))))}
 const groups={};p.facts.forEach(f=>{const g=f.field.startsWith('financials:')?'Financials':f.field.startsWith('role:')?'Roles':f.field==='establishment'?'Establishments':/^(website|social)/.test(f.field)||/^(business_summary|product_or_service|location)$/.test(f.field)?'Website':'Register';(groups[g]=groups[g]||[]).push(f)});
 for(const g of['Register','Financials','Roles','Establishments','Website']){if(!groups[g])continue;d.append(el('h3',null,g+' ('+groups[g].length+')'));
  const t=el('table');groups[g].forEach(f=>{const tr=el('tr');tr.append(el('th',null,f.field.replace(/^(financials|role):/,'')));const td=el('td');const v=el('div','val',fmt(f.value));td.append(v);
   if(f.as_of){td.append(el('span','chip','as of '+f.as_of))}
   const det=document.createElement('details');det.append(el('summary',null,'evidence'));const inner=el('div');inner.append('Source: ',link(f.source_url),el('br'),'Retrieved: '+f.retrieved_at,el('br'),'Evidence: '+f.evidence,el('br'),'Why this company: '+f.explanation);det.append(inner);td.append(det);tr.append(td);t.append(tr)});d.append(t)}}
$('q').oninput=renderList;$('f').onchange=renderList;stats();renderList();
</script></body></html>
"""


def build_report(out_dir, dest, limit=None):
    files = sorted((Path(out_dir) / "profiles").glob("*.json"))
    if limit:
        files = files[:limit]
    profiles = []
    for f in files:
        p = json.loads(f.read_text("utf-8"))
        p.setdefault("warnings", [])
        profiles.append(p)
    # </ would end the script element; escape it so profile text can never break out of the data block
    data = json.dumps(profiles, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    Path(dest).write_text(TEMPLATE.replace("__DATA__", data), "utf-8")
    return len(profiles)
