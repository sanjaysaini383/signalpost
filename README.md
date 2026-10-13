# Signalpost agent

Give it a batch of Norwegian organisation numbers. For each one it researches the official registers and the
company's own website and returns **exactly one terminal envelope**: legal identity, annual accounts, leadership,
registered workplaces, verified official website, company-owned profiles, hiring and dated public activity. Every
claim has evidence (source URL, retrieval time, content hash, claim span), every section has an explicit
availability state, and a re-run reports what changed against the previous snapshot.

## Install (one step)

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --frozen
```

## Run (evaluator command)

```bash
uv run signalpost batch --organisations batch.jsonl --output out/envelopes.jsonl --report out/run-report.json
```

- `--organisations` accepts JSONL (`{"organisation_number": "..."}` per line, extra fields ignored), a JSON list or
  `{"organisation_numbers": [...]}`, or plain text with one number per line.
- `--previous <envelopes.jsonl>` diffs against an earlier run. If omitted and `--output` already exists, that file
  is used as the previous snapshot. Every run is also archived to `out/snapshots/<run_id>.envelopes.jsonl`.
- Optional: `--run-id`, `--expected-count`, `--workers` (12), `--time-limit-min` (50), `--no-website`.
- Exit code 0 when the run report's validation passes (one envelope per input, all states terminal, every claim
  has evidence).

Clean-install check, as the evaluator runs it: clone at the pinned commit, `uv sync --frozen`, then the command
above. This was verified on a fresh clone.

## Environment variables (all optional)

| Variable | Effect |
|---|---|
| `BRAVE_SEARCH_API_KEY` | Brave Search is used to find candidate websites for companies without a verified one. Results are candidates only (see `SOURCES_AND_POLICY.md`). |
| `BRAVE_MIN_INTERVAL` | Seconds between search calls (default 1.05, safe for the free tier). |
| `ANTHROPIC_API_KEY` | Claude Haiku 5.5 summarises the verified website (business summary, products/services). Quotes must appear verbatim on the page. |
| `SIGNALPOST_MODEL` | Override the model id (default `claude-haiku-5-5`). |

Without any key the agent runs fully on official registers and company websites, at zero third-party cost.
Keys are read only from the environment and never written to output, logs or snapshots.

## Smoke test (100 companies)

`smoke/` holds the required 100-company smoke test, drawn from the public Signalpost universe with the starter
kit's seed (`uv run signalpost universe-sample --universe signalpost-company-universe-2025.jsonl.gz --count 100`):

| File | Content |
|---|---|
| `smoke/smoke-companies.jsonl` | the input batch |
| `smoke/envelopes.jsonl` | one terminal envelope per input |
| `smoke/run-report.json` | requests, runtime, p50/p95, cost, per-section coverage, validation |
| `smoke/rerun-report.json` | the same batch re-run against the first run: idempotency and refresh check |
| `smoke/dashboard.html` | the profiles in the browsable dashboard |

See `smoke/SMOKE_TEST.md` for the measured numbers.

## Cost and load per run

Measured with no cache and 12 workers (`smoke/SMOKE_TEST.md`): the 100-company smoke batch took 829 outbound
requests (8.3 per company) and 71 s, with per-company p50 2.8 s and p95 22.5 s. A 1,000-company batch took 8,553
requests and 9 min 10 s. Third-party cost is $0 without keys. With
`BRAVE_SEARCH_API_KEY`, at most one search query per company that has no verified website. With
`ANTHROPIC_API_KEY`, one Haiku call per company with a verified website (a few thousand tokens, well under
$0.001 per company at $0.10 / $0.50 per million tokens).

## What a profile contains

| Section | Source | Examples |
|---|---|---|
| Legal identity | Enhetsregisteret | legal name, form, status, addresses, industry, employees, founded, former names, coordinates (Kartverket) |
| Annual accounts | Regnskapsregisteret | latest revenue, costs, profit, assets, equity, debt (company and group) plus two earlier years, with reporting period and currency |
| Leadership | Enhetsregisteret roles | CEO, chair, board, auditor, accountant |
| Registered workplaces | Enhetsregisteret sub-units | establishments with address and employees |
| Official website | register, register e-mail domain, name-derived domains, optional search | verified only when the pages tie to the exact entity |
| Company-owned profiles | links on the verified site, JSON-LD `sameAs` | LinkedIn, Facebook, Instagram, X, YouTube, TikTok |
| Hiring | verified site | careers page, JSON-LD `JobPosting`, links to recruiting platforms (Webcruiter, Jobbnorge, Teamtailor, ...) |
| Public activity | verified site | dated items from the company's RSS/Atom feed and JSON-LD articles |

Each envelope also carries a plain-language `summary` (what the company is, key numbers, who leads it), the
`identity_check` that was applied, `unknowns` (what is missing and why) and `changes` since the previous run.

## Other commands

```bash
uv run signalpost profile 923609016                      # one company, internal profile as JSON
uv run signalpost report --envelopes out/envelopes.jsonl  # self-contained HTML dashboard
uv run signalpost universe-sample --universe <universe.jsonl.gz> --count 100 --output batch.jsonl
uv run pytest -q                                          # tests
```

## Documentation

- `DATA_SCHEMA.md` - envelope, claims, evidence, changes, run report
- `SOURCES_AND_POLICY.md` - sources and their terms, identity rules, robots, URL safety, secrets
- `LIMITATIONS.md` - known gaps

## Layout

```
signalpost/batch.py     evaluator command, run report
signalpost/envelope.py  envelope, claims, evidence, availability states, changes
signalpost/profile.py   profile assembly and history
signalpost/brreg.py     Enhetsregisteret, Regnskapsregisteret, roles, sub-units
signalpost/geo.py       verified address coordinates (Kartverket)
signalpost/website.py   site resolution and identity tie, profiles, hiring, activity, optional search and LLM
signalpost/budget.py    HTTP: budgets, retries, cache, snapshots, public-URL policy
signalpost/summary.py   summary, identity check, unknowns
signalpost/report.py    dashboard
signalpost/cli.py       command line
```
