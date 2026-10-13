# 100-company smoke test

Input: `smoke-companies.jsonl`, 100 companies drawn from the public Signalpost universe
(`signalpost-company-universe-2025.jsonl.gz`, SHA-256 of the archive verified) with the starter kit's seed 20260823:

```bash
uv run signalpost universe-sample --universe signalpost-company-universe-2025.jsonl.gz --count 100 --output smoke/smoke-companies.jsonl
uv run signalpost batch --organisations smoke/smoke-companies.jsonl --output smoke/envelopes.jsonl --report smoke/run-report.json --run-id smoke-001 --expected-count 100 --no-cache
uv run signalpost batch --organisations smoke/smoke-companies.jsonl --output smoke/rerun-envelopes.jsonl --previous smoke/envelopes.jsonl --report smoke/rerun-report.json --run-id smoke-002 --expected-count 100 --no-cache
```

Run on 13 October 2026, no API keys set (registers and company websites only), empty cache, 12 workers.

| | First run (`run-report.json`) | Re-run against the first (`rerun-report.json`) |
|---|---|---|
| Envelopes | 100 / 100, all `complete` | 100 / 100, all `complete` |
| Validation | passed | passed |
| Outbound requests | 829 (8.3 per company) | 829 |
| Wall-clock runtime | 71.4 s | 65.8 s |
| Per-company p50 / p95 | 2.8 s / 22.5 s | 2.9 s / 22.9 s |
| Third-party cost | $0 | $0 |
| Changes reported | n/a (first run) | **0** (idempotent, no false changes) |

Section coverage (companies with at least one supported claim, first run):

| Section | Companies |
|---|---|
| Legal identity | 100 |
| Annual accounts | 100 |
| Leadership | 100 |
| Registered workplaces | 73 (27 have no registered sub-unit) |
| Official website (verified) | 3 |
| Company-owned profiles | 0 |
| Hiring | 0 |
| Public activity | 0 |

Average 48.8 supported claims per company. Of the 100 companies, 7 register a website and 18 register an e-mail
address on their own domain. Most of those candidates were rejected as not tying to the exact entity: empty
JavaScript shells, Cloudflare challenges, parked or expired domains, a franchise chain, a parent utility and a
housing co-operative's umbrella site. They are reported as `ambiguous` or `failed`, not published. External
coverage on this random sample is therefore limited by how many companies have a verifiable website at all. A
search key (`BRAVE_SEARCH_API_KEY`) adds candidates.

`dashboard.html` shows the 100 profiles with section states, evidence and source links.

## Scale test (1,000 companies, not submitted)

The official batch is 1,000 companies, so the same command was also run on 1,000 companies drawn from the
universe with seed 7 (no keys, empty cache, 12 workers): 1,000 / 1,000 envelopes, validation passed,
8,553 outbound requests, 9 min 10 s wall-clock, per-company p95 21.5 s, $0.

| Section | Companies (of 1,000) |
|---|---|
| Legal identity | 1,000 |
| Annual accounts | 999 (1 deleted entity: `not_applicable`) |
| Leadership | 999 |
| Registered workplaces | 761 |
| Official website (verified) | 73 |
| Company-owned profiles | 35 |
| Hiring | 11 |
| Public activity | 21 |

A second run of that batch against the first reported changes for 13 companies. These were the identity rules
being tightened between the runs: four websites on group or sister-brand domains were withdrawn, together with
the group-level profiles and news attached to them. That shows refresh reporting removals with evidence for both
sides.
