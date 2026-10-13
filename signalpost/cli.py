"""Command line interface: run, profile, sample."""
import argparse
import csv
import json
import random
import sys
import time
from pathlib import Path

from concurrent.futures import ThreadPoolExecutor

from . import brreg, orgno

for _stream in (sys.stdout, sys.stderr):  # company names contain letters the Windows console cannot print
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")
from .budget import BudgetExceeded, Fetcher
from .profile import apply_history, build_profile, load_previous, save_profile
from .website import website_facts

# Claude Haiku 5.5 list price per token (USD), prompts up to 100K tokens
HAIKU_IN = 0.10 / 1_000_000
HAIKU_OUT = 0.50 / 1_000_000


def read_orgs(path):
    seen, out = set(), []
    for line in Path(path).read_text("utf-8").splitlines():
        o = orgno.normalize(line.split("#")[0].split(",")[0].strip())
        if o and o not in seen:
            seen.add(o)
            out.append(o)
    return out


def write_aggregates(out_dir, orgs):
    """One JSON line per profile plus a flat CSV overview, so results can be read without opening 1,000 files."""
    out = Path(out_dir)
    rows, n = [], 0
    with (out / "profiles.jsonl").open("w", encoding="utf-8") as jl:
        for org in orgs:
            p = load_previous(out_dir, org)
            if not p:
                continue
            n += 1
            jl.write(json.dumps(p, ensure_ascii=False, separators=(",", ":")) + "\n")
            val = lambda field: next((f["value"] for f in p["facts"] if f["field"] == field), "")
            rev = val("financials:selskap:revenue") or val("financials:konsern:revenue")
            rows.append([org, p.get("name", ""), p["status"], len(p["facts"]), val("employees"),
                         rev.get("amount", "") if isinstance(rev, dict) else "", rev.get("currency", "") if isinstance(rev, dict) else "",
                         val("website"), val("industry_code"), val("municipality"), len(p.get("warnings", [])),
                         len(p.get("changes_since_previous_run", []))])
    with (out / "summary.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["organization_number", "name", "status", "facts", "employees", "revenue", "currency",
                    "website", "industry", "municipality", "warnings", "changes"])
        w.writerows(rows)
    return n


def cmd_run(a):
    orgs = read_orgs(a.input)
    deadline = time.monotonic() + a.time_limit_min * 60
    fetcher = Fetcher(max_requests=a.max_requests, cache_dir=None if a.no_cache else Path(a.out) / ".cache",
                      deadline=deadline, cache_ttl=a.cache_ttl)
    site_fn = None if a.no_website else website_facts
    stats = {"done": 0, "failed": 0, "changed": 0, "stopped": False}

    def work(item):
        i, org = item
        if stats["stopped"]:
            return
        t0 = time.monotonic()
        try:
            prev = load_previous(a.out, org)
            profile = apply_history(build_profile(fetcher, org, include_website=site_fn), prev)
            save_profile(a.out, profile)
            stats["done"] += 1
            stats["changed"] += bool(profile["changes_since_previous_run"])
            print(f"[{i}/{len(orgs)}] {org} {profile['status']} facts={len(profile['facts'])} "
                  f"changes={len(profile['changes_since_previous_run'])} requests={fetcher.requests_made} "
                  f"t={time.monotonic() - t0:.1f}s", flush=True)
        except BudgetExceeded as e:
            stats["stopped"] = True
            print(f"STOPPED: {e}", file=sys.stderr, flush=True)
        except Exception as e:  # one bad company must not kill the run
            stats["failed"] += 1
            print(f"[{i}/{len(orgs)}] {org} ERROR {e}", file=sys.stderr, flush=True)

    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        list(pool.map(work, enumerate(orgs, 1)))
    n_out = write_aggregates(a.out, orgs)
    cost = fetcher.llm_input_tokens * HAIKU_IN + fetcher.llm_output_tokens * HAIKU_OUT
    print(f"done={stats['done']}/{len(orgs)} failed={stats['failed']} with_changes={stats['changed']} "
          f"requests={fetcher.requests_made} llm_tokens={fetcher.llm_input_tokens}+{fetcher.llm_output_tokens} "
          f"est_llm_cost_usd={cost:.4f}")
    print(f"wrote {a.out}/profiles.jsonl and {a.out}/summary.csv ({n_out} profiles)")
    return 0


def cmd_profile(a):
    fetcher = Fetcher()
    prev = load_previous(a.out, orgno.normalize(a.org))
    profile = apply_history(build_profile(fetcher, a.org, include_website=website_facts), prev)
    save_profile(a.out, profile)
    print(json.dumps(profile, ensure_ascii=False, indent=2))
    return 0


def cmd_sample(a):
    """Draw random active companies from the Enhetsregisteret search API."""
    rng = random.Random(a.seed)
    fetcher = Fetcher(max_requests=500)
    forms = ["AS", "ENK", "NUF", "ANS", "DA", "SA", "FLI", "STI", "ASA", "BA", "KS", "SE"]
    weights = [50, 25, 6, 3, 3, 3, 4, 2, 1, 1, 1, 1]
    found = {}
    tries = 0
    while len(found) < a.n and tries < 400:
        tries += 1
        form = rng.choices(forms, weights)[0]
        page = rng.randrange(0, 100)  # the API only serves the first 10,000 hits per query
        status, data = fetcher.get_json(brreg.SEARCH_URL, {
            "organisasjonsform": form, "konkurs": "false", "underAvvikling": "false",
            "size": 100, "page": page, "sort": "organisasjonsnummer,desc" if rng.random() < .5 else "organisasjonsnummer,asc"})
        if not data:
            continue
        for u in data.get("_embedded", {}).get("enheter", []):
            if orgno.is_valid(u["organisasjonsnummer"]) and rng.random() < 0.3:
                found[u["organisasjonsnummer"]] = u.get("navn", "")
    items = list(found.items())[: a.n]
    rng.shuffle(items)
    Path(a.output).write_text("\n".join(f"{o}  # {n}" for o, n in items) + "\n", "utf-8")
    print(f"wrote {len(items)} organisation numbers to {a.output} ({fetcher.requests_made} requests)")
    return 0


def cmd_validate(a):
    """Check every saved profile for structural problems and wrong-company risks."""
    problems, n, facts_n = [], 0, 0
    for f in sorted((Path(a.out) / "profiles").glob("*.json")):
        p = json.loads(f.read_text("utf-8"))
        n += 1
        org = p.get("organization_number", "")
        if not orgno.is_valid(org) or f.stem != org:
            problems.append(f"{f.name}: bad or mismatched organisation number")
        for x in p.get("facts", []):
            facts_n += 1
            for k in ("field", "value", "source_url", "retrieved_at", "evidence", "explanation"):
                if x.get(k) in (None, ""):
                    problems.append(f"{org}: fact {x.get('field')} missing {k}")
            if "data.brreg.no" in x.get("source_url", "") and org not in x["source_url"]:
                problems.append(f"{org}: {x['field']} source URL does not reference the organisation number")
            if x.get("field", "").startswith("financials:") and not (x["value"] or {}).get("currency"):
                problems.append(f"{org}: {x['field']} has no currency")
            site_derived = x.get("field", "").startswith(("website_", "social:", "product_", "location", "business_summary"))
            if site_derived and x["field"] != "website_verified" and "website_verified" not in {y["field"] for y in p["facts"]}:
                problems.append(f"{org}: website-derived fact {x['field']} without verified website")
        if p.get("status") == "deleted" and any(x["field"].startswith(("financials:", "role:")) for x in p["facts"]):
            problems.append(f"{org}: deleted company still lists live financials or roles")
        for k in ("summary", "identity_check"):
            if p.get("status") in ("active", "sub_unit") and not p.get(k):
                problems.append(f"{org}: missing {k}")
    print(f"profiles={n} facts={facts_n} problems={len(problems)}")
    for line in problems[:50]:
        print("  " + line)
    return 1 if problems else 0


def cmd_report(a):
    from .report import build_report
    n = build_report(a.out, a.output, a.limit)
    print(f"wrote {a.output} with {n} profiles ({Path(a.output).stat().st_size // 1024} KB)")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="signalpost", description="Profile Norwegian companies from public sources")
    sub = p.add_subparsers(dest="cmd", required=True)
    from .batch import add_parser as add_batch
    add_batch(sub)
    r = sub.add_parser("run", help="build/update profiles for every org number in a file")
    r.add_argument("--input", default="companies.txt", help="text file with one organisation number per line")
    r.add_argument("--out", default="output")
    r.add_argument("--max-requests", type=int, default=1800)
    r.add_argument("--time-limit-min", type=float, default=40)
    r.add_argument("--no-cache", action="store_true")
    r.add_argument("--cache-ttl", type=int, default=3600, help="seconds a cached response may be reused")
    r.add_argument("--no-website", action="store_true", help="register data only")
    r.add_argument("--workers", type=int, default=8)
    r.set_defaults(fn=cmd_run)
    q = sub.add_parser("profile", help="profile a single organisation number and print JSON")
    q.add_argument("org")
    q.add_argument("--out", default="output")
    q.set_defaults(fn=cmd_profile)
    s = sub.add_parser("sample", help="write a random list of valid, active organisation numbers")
    s.add_argument("--n", type=int, default=1000)
    s.add_argument("--seed", type=int, default=1)
    s.add_argument("--output", default="companies.txt")
    s.set_defaults(fn=cmd_sample)
    v = sub.add_parser("validate", help="sanity-check saved profiles")
    v.add_argument("--out", default="output")
    v.set_defaults(fn=cmd_validate)
    g = sub.add_parser("report", help="write a self-contained HTML report of the saved profiles")
    g.add_argument("--out", default="output")
    g.add_argument("--output", default="report.html")
    g.add_argument("--limit", type=int, default=None)
    g.set_defaults(fn=cmd_report)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
