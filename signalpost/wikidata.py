"""Wikidata items linked to an organisation number (property P2333). One SPARQL query covers 200 companies.

The link is made by Wikidata's own statement 'Norwegian organisation number = <org>', so the item is the exact
entity. Its official website is only a candidate and goes through the normal website tie; its social handles
are published as profiles attributed to Wikidata."""
import hashlib
import json

from .brreg import fact
from .budget import BudgetExceeded

SPARQL = "https://query.wikidata.org/sparql"
CHUNK = 200
# property -> (platform, URL template)
HANDLES = {
    "P4264": ("linkedin", "https://www.linkedin.com/company/{}"),
    "P2013": ("facebook", "https://www.facebook.com/{}"),
    "P2003": ("instagram", "https://www.instagram.com/{}"),
    "P2002": ("x", "https://x.com/{}"),
    "P2397": ("youtube", "https://www.youtube.com/channel/{}"),
    "P7085": ("tiktok", "https://www.tiktok.com/@{}"),
}


def _query(orgs):
    values = " ".join(f'"{o}"' for o in orgs)
    opts = " ".join(f"OPTIONAL {{ ?item wdt:{p} ?{p} }}" for p in HANDLES)
    return (f"SELECT ?org ?item ?site {' '.join('?' + p for p in HANDLES)} WHERE {{ VALUES ?org {{ {values} }} "
            f"?item wdt:P2333 ?org . OPTIONAL {{ ?item wdt:P856 ?site }} {opts} }}")


def prefetch(fetcher, orgs, errors):
    """{org: {"item": url, "sites": [...], "handles": {platform: url}, "sha256": ..., "retrieved_at": ...}}"""
    out = {}
    for i in range(0, len(orgs), CHUNK):
        chunk = orgs[i:i + CHUNK]
        try:
            status, text = fetcher.get(SPARQL, {"query": _query(chunk)}, accept="application/sparql-results+json",
                                       retries=2, timeout=60, record=False)
        except BudgetExceeded:
            raise
        except Exception as e:
            errors.append(f"wikidata query failed: {type(e).__name__}: {e}"[:300])
            continue
        if status != 200:
            errors.append(f"wikidata query returned HTTP {status}")
            continue
        try:
            bindings = json.loads(text)["results"]["bindings"]
        except (ValueError, KeyError):
            continue
        for b in bindings:
            org = b["org"]["value"]
            item = b["item"]["value"].replace("http://www.wikidata.org/entity/", "https://www.wikidata.org/wiki/")
            rec = out.setdefault(org, {"item": item, "sites": [], "handles": {}, "rows": []})
            if rec["item"] != item:
                rec["ambiguous"] = True  # two items claim the same number: publish nothing from Wikidata
            site = (b.get("site") or {}).get("value")
            if site and site not in rec["sites"]:
                rec["sites"].append(site)
            for prop, (platform, tmpl) in HANDLES.items():
                v = (b.get(prop) or {}).get("value")
                if v and platform not in rec["handles"]:
                    rec["handles"][platform] = tmpl.format(v)
            rec["rows"].append(b)
    for org, rec in out.items():
        rows = json.dumps(sorted(rec.pop("rows"), key=lambda r: json.dumps(r, sort_keys=True)), sort_keys=True)
        rec["sha256"] = hashlib.sha256(rows.encode("utf-8")).hexdigest()
    return out


def wikidata_facts(org, rec, retrieved_at):
    if not rec or rec.get("ambiguous"):
        return []
    why = f"Wikidata item {rec['item']} states Norwegian organisation number (P2333) = {org}"
    out = []

    def add(field, value, evidence, method="wikidata_sparql"):
        f = fact(field, value, rec["item"], evidence, why, retrieved_at)
        f.update({"span": evidence, "method": method, "source_class": "public_knowledge_base",
                  "content_sha256": rec["sha256"]})
        out.append(f)

    add("social:wikidata", rec["item"], f"P2333: {org}")
    for platform, url in sorted(rec["handles"].items()):
        add(f"social:{platform}", url, f"{platform} handle on Wikidata item: {url.rsplit('/', 1)[-1].lstrip('@')}")
    return out
