# Signalpost - Norwegian company profile agent

Give it a Norwegian organisation number. It returns a JSON profile where **every fact has a source URL,
a retrieval date, an evidence snippet and an explanation of why it belongs to that company**.

## Run it

```bash
pip install -e .                                   # Python 3.10+
py -m signalpost run --input companies.txt         # one command: profile every org number in the file
```

Output goes to `output/profiles/<orgno>.json`. Running it again updates the profiles and records what
changed in `changes_since_previous_run`.

Other commands:

```bash
py -m signalpost profile 923609016                 # one company, printed as JSON
py -m signalpost sample --n 1000 --output companies.txt   # draw random active org numbers
py -m signalpost validate --out output             # structural + wrong-company sanity checks
py -m pytest                                       # unit tests
```

Options for `run`: `--max-requests` (default 1800), `--time-limit-min` (default 40), `--workers` (default 8),
`--no-website`, `--no-cache`.

## Optional LLM step

If `ANTHROPIC_API_KEY` is set (see `.env.example`), the agent also asks Claude Haiku 5.5 to summarise what the
company's own website says (business summary, products/services, locations). Without a key the agent still runs and
produces everything else. Each model-extracted value must come with a quote, and the value is **dropped unless the
quote appears verbatim in a page that was fetched**. The model is never used for numbers.

## Sources

| Source | Used for |
|---|---|
| Enhetsregisteret API (`data.brreg.no`) | identity, status flags (bankrupt / liquidation), address, industry code, employees, contacts, share capital, website |
| Enhetsregisteret roles | CEO, chair, board, auditor |
| Enhetsregisteret sub-units | establishments / branches registered under the parent |
| Regnskapsregisteret API | latest annual accounts. Values are copied verbatim with their currency, never generated |
| Company website declared in the register | contact details, social links, description (only after the page is tied to the company) |

## How it avoids the wrong company

- Everything is keyed on the organisation number, validated with the mod-11 check digit before any request.
- A sub-unit is only attached if the register names this company as its parent.
- A website is only used if the register declares it for this org number **and** the fetched page contains the
  org number or the company name. Otherwise all website facts are discarded and a warning is recorded.
- Website e-mail addresses are kept only if their domain matches the site.
- `robots.txt` is respected for website pages.

## How updates work

Each run loads the previous profile for the company, rebuilds it from live sources, and diffs the two. Each fact
keeps a `first_seen` timestamp, and `changes_since_previous_run` lists added / changed / removed facts. Companies
that are bankrupt or deleted get a `status` change.

## Limits and expected cost

| Limit | How it is enforced |
|---|---|
| 2,000 outbound requests per run | hard stop at 1,800 (`--max-requests`), shared across threads, LLM calls included |
| 45 minutes | stops starting new work after `--time-limit-min` (default 40) |
| $10 external API cost | the Brønnøysund APIs are free; only the optional LLM step costs money |

Typical load is about 4 requests per company without the LLM step (about 1 more for the LLM call), so 100
companies need roughly 400-600 requests. LLM cost for Claude Haiku 5.5 ($0.10 / $0.50 per million tokens) is
well under $0.10 per 100 companies. Responses are cached in `output/.cache`.

## Layout

```
signalpost/orgno.py     organisation number validation
signalpost/budget.py    HTTP client with request/time budget, retries and cache
signalpost/brreg.py     register, roles, accounts and sub-unit facts
signalpost/website.py   website verification, deterministic extraction, optional LLM extraction
signalpost/profile.py   profile assembly, history and diff
signalpost/cli.py       command line
```
