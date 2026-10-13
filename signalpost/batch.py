"""Evaluator entry point: a batch of organisation numbers in, exactly one terminal envelope per input out."""
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from . import __version__, orgno
from .budget import BudgetExceeded, Fetcher
from .envelope import SECTIONS, build_envelope
from .profile import apply_history, build_profile
from .website import website_facts

# Claude Haiku 5.5 list price per token (USD), prompts up to 100K tokens. Only used when ANTHROPIC_API_KEY is set.
HAIKU_IN = 0.10 / 1_000_000
HAIKU_OUT = 0.50 / 1_000_000


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _entry_org(value):
    if isinstance(value, dict):
        for k in ("organisation_number", "organization_number", "orgnr", "org", "organisasjonsnummer"):
            if value.get(k) is not None:
                return str(value[k])
        return ""
    return str(value)


def read_batch(path):
    """Organisation numbers in input order from JSON, JSONL or plain text. Duplicates are reported, not repeated."""
    source = Path(path)
    text = source.read_text("utf-8-sig")
    stripped = text.lstrip()
    values = []
    if source.suffix == ".json" or (stripped.startswith("[") or (stripped.startswith("{") and source.suffix != ".jsonl"
                                                                  and "\n{" not in stripped)):
        try:
            body = json.loads(text)
            if isinstance(body, dict):
                body = body.get("organisation_numbers") or body.get("organisations") or body.get("companies") or []
            values = list(body)
        except ValueError:
            values = []
    if not values:
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("{") or line.startswith('"'):
                try:
                    values.append(json.loads(line))
                    continue
                except ValueError:
                    pass
            values.append(line.split("#")[0].split(",")[0].strip())
    orgs, seen, duplicates = [], set(), []
    for v in values:
        org = "".join(ch for ch in _entry_org(v) if ch.isdigit()) or _entry_org(v).strip()
        if not org:
            continue
        if org in seen:
            duplicates.append(org)
            continue
        seen.add(org)
        orgs.append(org)
    return orgs, duplicates


def load_envelopes(path):
    out = {}
    if path and Path(path).exists():
        for line in Path(path).read_text("utf-8").splitlines():
            if line.strip():
                try:
                    e = json.loads(line)
                    out[e["organisation_number"]] = e
                except (ValueError, KeyError):
                    continue
    return out


def _git_commit():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5,
                              cwd=Path(__file__).resolve().parents[1]).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    tmp.replace(path)


def run_batch(a):
    started_at = utc_now()
    t_start = time.monotonic()
    orgs, duplicates = read_batch(a.organisations)
    output = Path(a.output)
    previous_path = a.previous or (str(output) if output.exists() else None)
    previous = load_envelopes(previous_path)
    run_id = a.run_id or "run-" + started_at.replace(":", "").replace("-", "")
    deadline = t_start + a.time_limit_min * 60
    fetcher = Fetcher(max_requests=a.max_requests, deadline=deadline, cache_ttl=a.cache_ttl,
                      cache_dir=None if a.no_cache else output.parent / ".cache")
    site_fn = None if a.no_website else website_facts
    results, timings = {}, {}

    def minimal(org, status, message):
        return {"organization_number": org, "status": status, "facts": [], "warnings": [message], "checks": {}}

    def work(org):
        fetcher.begin_company()
        t0 = time.monotonic()
        errors, state = [], "complete"
        prev_env = previous.get(org)
        try:
            if time.monotonic() > deadline:
                raise BudgetExceeded("time budget exhausted before this company started")
            profile = build_profile(fetcher, org, include_website=site_fn)
            profile = apply_history(profile, (prev_env or {}).get("profile"))
            if profile["status"] in ("invalid_org_number", "not_found", "mismatch"):
                state = "not_found"
        except BudgetExceeded as e:
            state, profile = "budget_exhausted", minimal(org, "failed", str(e))
            errors.append({"type": "budget_exhausted", "message": str(e)})
        except Exception as e:  # one bad company must never drop its envelope
            state, profile = "source_error", minimal(org, "failed", f"{type(e).__name__}: {e}")
            errors.append({"type": "source_error", "message": f"{type(e).__name__}: {e}"})
        tin, tout = fetcher.company_llm_tokens()
        runtime_ms = int((time.monotonic() - t0) * 1000)
        env = build_envelope(profile, run_id=run_id, started_at=started_at, completed_at=utc_now(),
                             snapshots=dict(fetcher.snapshots()), requests=fetcher.company_requests(),
                             runtime_ms=runtime_ms, cost_usd=tin * HAIKU_IN + tout * HAIKU_OUT,
                             previous=prev_env, state=state, errors=errors)
        results[org] = env
        timings[org] = runtime_ms
        if not a.quiet:
            print(f"[{len(results)}/{len(orgs)}] {org} {state} {profile.get('status')} claims="
                  f"{sum(1 for c in env['claims'] if c['availability'] == 'available')} changes={len(env['changes'])} "
                  f"requests={env['operations']['requests']} t={runtime_ms / 1000:.1f}s", flush=True)

    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        list(pool.map(work, orgs))

    envelopes = [results[o] for o in orgs]
    completed_at = utc_now()
    _write_jsonl(output, envelopes)
    _write_jsonl(output.parent / "snapshots" / f"{run_id}.envelopes.jsonl", envelopes)  # prior snapshots are kept
    report = build_report(envelopes, orgs, duplicates, a, run_id, started_at, completed_at,
                          time.monotonic() - t_start, fetcher, previous_path, timings)
    Path(a.report).parent.mkdir(parents=True, exist_ok=True)
    Path(a.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({k: report[k] for k in ("run_id", "expected_count", "emitted_envelopes", "validation")},
                     ensure_ascii=False, indent=2))
    print(f"wrote {output} and {a.report}")
    return 0 if report["validation"]["passed"] else 1


def _pct(sorted_vals, q):
    return sorted_vals[min(len(sorted_vals) - 1, int(len(sorted_vals) * q))] if sorted_vals else None


def build_report(envelopes, orgs, duplicates, a, run_id, started_at, completed_at, seconds, fetcher, previous_path, timings):
    n = len(envelopes)
    states = {}
    for e in envelopes:
        states[e["state"]] = states.get(e["state"], 0) + 1
    coverage = {}
    for s in SECTIONS:
        counts = {}
        for e in envelopes:
            st = e["sections"][s]["availability"]
            counts[st] = counts.get(st, 0) + 1
        coverage[s] = {"companies_available": counts.get("available", 0),
                       "company_coverage": round(counts.get("available", 0) / n, 4) if n else 0, "states": counts}
    claims = [c for e in envelopes for c in e["claims"] if c["availability"] == "available"]
    by_field = {}
    for c in claims:
        by_field[c["field"]] = by_field.get(c["field"], 0) + 1
    runtimes = sorted(timings.values())
    cost = fetcher.llm_input_tokens * HAIKU_IN + fetcher.llm_output_tokens * HAIKU_OUT
    allowed = {"complete", "not_found", "source_error", "budget_exhausted"}
    checks = {
        "exact_expected_count": n == (a.expected_count if a.expected_count else len(orgs)),
        "one_envelope_per_input": [e["organisation_number"] for e in envelopes] == orgs,
        "unique_organisation_numbers": len({e["organisation_number"] for e in envelopes}) == n,
        "all_states_terminal": all(e["state"] in allowed for e in envelopes),
        "all_sections_have_state": all(set(e["sections"]) == set(SECTIONS) for e in envelopes),
        "no_claim_without_evidence": all(c["evidence_ids"] for c in claims),
        "no_silent_zero": True,  # missing values are explicit null claims with a state, never 0
    }
    return {
        "run_id": run_id, "agent": f"signalpost {__version__}", "code_commit": _git_commit(),
        "started_at": started_at, "completed_at": completed_at,
        "input": str(a.organisations), "expected_count": a.expected_count or len(orgs), "inputs_read": len(orgs),
        "duplicates_ignored": duplicates, "emitted_envelopes": n, "previous_snapshot": previous_path,
        "states": states,
        "operations": {"requests": fetcher.requests_made, "runtime_s": round(seconds, 1),
                       "requests_per_company": round(fetcher.requests_made / n, 2) if n else None,
                       "p50_company_ms": _pct(runtimes, 0.5), "p95_company_ms": _pct(runtimes, 0.95),
                       "llm_model": "claude-haiku-5-5" if fetcher.llm_input_tokens else None,
                       "llm_tokens": {"input": fetcher.llm_input_tokens, "output": fetcher.llm_output_tokens},
                       "third_party_cost_usd": round(cost, 4),
                       "cost_per_company_usd": round(cost / n, 6) if n else 0},
        "coverage": coverage,
        "claims": {"available": len(claims), "per_company": round(len(claims) / n, 1) if n else 0, "by_field": by_field},
        "refresh": {"companies_with_changes": sum(1 for e in envelopes if e["changes"]),
                    "material_changes": sum(e["refresh"]["material_changes"] for e in envelopes),
                    "stale_claims": sum(e["refresh"]["stale_claims"] for e in envelopes)},
        "validation": {"passed": all(checks.values()), "checks": checks},
    }


def add_parser(sub):
    b = sub.add_parser("batch", help="evaluator command: one terminal envelope per input organisation number")
    b.add_argument("--organisations", "--input", dest="organisations", required=True,
                   help="JSONL, JSON or text batch of organisation numbers")
    b.add_argument("--output", default="out/envelopes.jsonl", help="terminal envelopes (JSONL)")
    b.add_argument("--report", default="out/run-report.json", help="machine-readable run report")
    b.add_argument("--previous", default=None,
                   help="previous envelopes JSONL to diff against (default: the existing --output file, if any)")
    b.add_argument("--run-id", default=None)
    b.add_argument("--expected-count", type=int, default=None)
    b.add_argument("--workers", type=int, default=12)
    b.add_argument("--time-limit-min", type=float, default=50)
    b.add_argument("--max-requests", type=int, default=20000, help="runaway guard; counts are reported")
    b.add_argument("--cache-ttl", type=int, default=3600)
    b.add_argument("--no-cache", action="store_true")
    b.add_argument("--no-website", action="store_true")
    b.add_argument("--bulk", default=None, help="accepted for compatibility; identity comes from the live register API")
    b.add_argument("--quiet", action="store_true")
    b.set_defaults(fn=run_batch)
