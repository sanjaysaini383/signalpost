"""Command line interface: batch (evaluator command), profile, report, universe-sample."""
import argparse
import json
import random
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):  # company names contain letters the Windows console cannot print
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from . import orgno  # noqa: E402
from .batch import add_parser as add_batch  # noqa: E402
from .budget import Fetcher  # noqa: E402
from .profile import build_profile  # noqa: E402
from .website import website_facts  # noqa: E402


def cmd_profile(a):
    """Research one company and print the internal profile as JSON."""
    profile = build_profile(Fetcher(), orgno.normalize(a.org), include_website=website_facts)
    print(json.dumps(profile, ensure_ascii=False, indent=2))
    return 0


def cmd_report(a):
    from .report import build_report
    n = build_report(None, a.output, a.limit, envelopes=a.envelopes)
    print(f"wrote {a.output} with {n} profiles ({Path(a.output).stat().st_size // 1024} KB)")
    return 0


def cmd_universe_sample(a):
    """Reproducible local test batch from the public Signalpost universe (same selection as the starter kit)."""
    import gzip
    path = Path(a.universe)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    chosen = random.Random(a.seed).sample(rows, a.count)
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    with open(a.output, "w", encoding="utf-8") as fh:
        for row in chosen:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"wrote {len(chosen)} companies to {a.output} (seed {a.seed}, universe {len(rows)} rows)")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="signalpost", description="Research Norwegian companies from public sources")
    sub = p.add_subparsers(dest="cmd", required=True)
    add_batch(sub)
    q = sub.add_parser("profile", help="research one organisation number and print its profile as JSON")
    q.add_argument("org")
    q.set_defaults(fn=cmd_profile)
    g = sub.add_parser("report", help="write a self-contained HTML dashboard from batch envelopes")
    g.add_argument("--envelopes", default="out/envelopes.jsonl", help="envelopes JSONL written by `batch`")
    g.add_argument("--output", default="out/dashboard.html")
    g.add_argument("--limit", type=int, default=None)
    g.set_defaults(fn=cmd_report)
    u = sub.add_parser("universe-sample", help="seeded local test batch from the public Signalpost universe")
    u.add_argument("--universe", required=True)
    u.add_argument("--count", type=int, default=100)
    u.add_argument("--seed", type=int, default=20260823)
    u.add_argument("--output", default="smoke/smoke-companies.jsonl")
    u.set_defaults(fn=cmd_universe_sample)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
