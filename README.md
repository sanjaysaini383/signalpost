# Signalpost - Norwegian company profile agent

Give it a Norwegian organisation number. It returns a JSON profile in which **every fact carries a source URL,
a retrieval date, an evidence snippet and an explanation of why it belongs to that company**, plus a plain-language
summary, an identity check and a list of what is missing and why.

## Run it

```bash
pip install -e .                                   # Python 3.10+
py -m signalpost run --input companies.txt         # one command: profile every org number in the file
```

(`python -m signalpost ...` on Linux/macOS.) Results land in `output/`:

| File | Content |
|---|---|
| `output/profiles/<orgno>.json` | one full profile per company |
| `output/profiles.jsonl` | the same profiles, one JSON object per line |
| `output/summary.csv` | one overview row per company |

Running it again refreshes every profile from the live sources and records what changed in
`changes_since_previous_run`.

Other commands:

```bash
py -m signalpost profile 923609016                 # one company, printed as JSON
py -m signalpost sample --n 1000 --output companies.txt   # draw random active org numbers
py -m signalpost validate --out output             # structural + wrong-company sanity checks
py -m signalpost report --out output               # self-contained HTML dashboard (report.html)
py -m pytest                                       # unit tests
```

Options for `run`: `--max-requests` (default 1800), `--time-limit-min` (default 40), `--workers` (default 8),
`--cache-ttl` (seconds, default 3600), `--no-website`, `--no-cache`.

## What a profile contains

About 40 facts per company on average (more for large companies):

- **Identity and status:** name, legal form, former names, founding/registration dates, bankrupt / in liquidation /
  forced dissolution flags and dates, deleted date, institutional sector, language form, parent organisation.
- **Location:** business and postal address, municipality, verified coordinates.
- **Business:** industry codes, activity description, statutory purpose, employees (with the date it was registered).
- **Contact:** phone, mobile, e-mail, website (from the register, or discovered and verified), social links.
- **Financials:** latest annual accounts (revenue, costs, profit, assets, equity, debt) plus two earlier years of the
  main figures, with the accounting standard and audit status.
- **People:** CEO, chair, board members, auditor and other registered roles.
- **Establishments:** registered sub-units with address and employees.
- **Explanations:** `summary`, `identity_check`, `coverage_notes`, `sources_used`, per-fact `explanation`.

## Sources

| Source | Used for |
|---|---|
| Enhetsregisteret API (`data.brreg.no`) | identity, status, address, industry, employees, contacts, capital, former names |
| Enhetsregisteret roles and sub-units | people and roles, establishments |
| Regnskapsregisteret API | annual accounts. Values are copied verbatim with their currency, never generated |
| Kartverket address API (`ws.geonorge.no`) | coordinates of the registered business address |
| The company's own website | contact details, social links, description, schema.org data (optional model summary) |

## How it avoids the wrong company

- Everything is keyed on the organisation number, validated with the mod-11 check digit before any request.
- The register record must carry exactly the requested number, otherwise nothing is published (`status: mismatch`).
- A deleted company (the register still answers for it, with a `slettedato`) is reported as `deleted`, never as active.
- A sub-unit is only attached if the register names this company as its parent. A sub-unit's own number is
  recognised and profiled as `sub_unit`.
- **Website:** used only if the page ties to the company. Strong tie: the organisation number appears on the page.
  For a site the register itself declares, weaker ties are accepted only in combination: company name + registered
  postal code, company name + registered phone number, or a domain that matches the company name + the name on the
  page. A name alone is never enough.
- **Discovered websites:** when the register lists none, a few name-derived domains are tried. One is accepted
  **only** if its home page shows this organisation number.
- Coordinates are kept only when street, postal code and municipality number equal the register values.
- Website e-mail addresses are kept only if their domain matches the site. `robots.txt` is respected.
- Model-extracted values (optional) are dropped unless their quote appears verbatim in a fetched page, and any
  figure the model states must be inside its own quote.

## How updates work

- Every run refetches from the live sources. The disk cache only lives for one hour (`--cache-ttl`), so a run
  tomorrow can never be served yesterday's answers.
- The previous profile is loaded and diffed: `changes_since_previous_run` lists added, changed and removed facts,
  and `status` changes (for example active -> bankrupt, or active -> deleted). Each fact keeps a `first_seen` time.
- If one source is down during a run, its earlier facts are kept and flagged `"stale": true` with their original
  retrieval time, instead of being reported as removed.

## Optional LLM step

If `ANTHROPIC_API_KEY` is set (see `.env.example`), the agent also asks Claude Haiku 5.5 to summarise what the
company's own website says (business summary, products/services, locations). Without a key the agent runs fully
and produces everything above. The model is never used for numbers or financial values.

## Limits and expected cost

| Limit | How it is enforced |
|---|---|
| 2,000 outbound requests per run | hard stop at 1,800 (`--max-requests`), shared across threads, LLM calls included |
| 45 minutes | stops starting new work after `--time-limit-min` (default 40) |
| $10 external API cost | the register and address APIs are free; only the optional LLM step costs money |

Measured on 100 random companies with an empty cache: **about 710 requests and under one minute.** The LLM step adds
one request per company with a website. Claude Haiku 5.5 costs $0.10 / $0.50 per million tokens, so it is well under
$0.10 per 100 companies.

## Layout

```
signalpost/orgno.py     organisation number validation
signalpost/budget.py    HTTP client: request/time budget, retries, one-hour cache
signalpost/brreg.py     register, roles, accounts, sub-unit facts
signalpost/geo.py       verified address coordinates
signalpost/website.py   website tie-in, discovery, structured data, optional LLM extraction
signalpost/summary.py   summary, identity check, coverage notes
signalpost/profile.py   profile assembly, history and diff
signalpost/report.py    HTML dashboard
signalpost/cli.py       command line
```
