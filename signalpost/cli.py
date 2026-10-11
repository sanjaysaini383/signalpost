"""Command line interface: run, profile, sample."""
import argparse
import json
import random
import sys
import time
from pathlib import Path

from . import brreg, orgno
from .budget import BudgetExceeded, Fetcher
from .profile import apply_history, build_profile, load_previous, save_profile


def read_orgs(path):
    seen, out = set(), []
    for line in Path(path).read_text("utf-8").splitlines():
        o = orgno.normalize(line.split("#")[0].split(",")[0].strip())
        if o and o not in seen:
            seen.add(o)
            out.append(o)
    return out


def cmd_run(a):
    orgs = read_orgs(a.input)
    deadline = time.monotonic() + a.time_limit_min * 60
    fetcher = Fetcher(max_requests=a.max_requests, cache_dir=None if a.no_cache else Path(a.out) / ".cache", deadline=deadline)
    done = failed = 0
    changed = 0
    for i, org in enumerate(orgs, 1):
        try:
            prev = load_previous(a.out, org)
            profile = apply_history(build_profile(fetcher, org), prev)
            save_profile(a.out, profile)
            done += 1
            changed += bool(profile["changes_since_previous_run"])
            print(f"[{i}/{len(orgs)}] {org} {profile['status']} facts={len(profile['facts'])} "
                  f"changes={len(profile['changes_since_previous_run'])} requests={fetcher.requests_made}")
        except BudgetExceeded as e:
            print(f"STOPPED: {e}. Processed {done}/{len(orgs)}.", file=sys.stderr)
            break
        except Exception as e:  # keep going; one bad company must not kill the run
            failed += 1
            print(f"[{i}/{len(orgs)}] {org} ERROR {e}", file=sys.stderr)
    print(f"done={done} failed={failed} with_changes={changed} requests={fetcher.requests_made}")
    return 0


def cmd_profile(a):
    fetcher = Fetcher()
    prev = load_previous(a.out, orgno.normalize(a.org))
    profile = apply_history(build_profile(fetcher, a.org), prev)
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


def main(argv=None):
    p = argparse.ArgumentParser(prog="signalpost", description="Profile Norwegian companies from public sources")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="build/update profiles for every org number in a file")
    r.add_argument("--input", required=True, help="text file with one organisation number per line")
    r.add_argument("--out", default="out")
    r.add_argument("--max-requests", type=int, default=1800)
    r.add_argument("--time-limit-min", type=float, default=40)
    r.add_argument("--no-cache", action="store_true")
    r.set_defaults(fn=cmd_run)
    q = sub.add_parser("profile", help="profile a single organisation number and print JSON")
    q.add_argument("org")
    q.add_argument("--out", default="out")
    q.set_defaults(fn=cmd_profile)
    s = sub.add_parser("sample", help="write a random list of valid, active organisation numbers")
    s.add_argument("--n", type=int, default=1000)
    s.add_argument("--seed", type=int, default=1)
    s.add_argument("--output", default="companies.txt")
    s.set_defaults(fn=cmd_sample)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
