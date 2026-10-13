# What I need from you

Updated after Builderr's reply (Soham) and the official starter kit and evaluation contract.
**Unstop registration deadline: 17 Oct 2026, 11:59 PM IST. Last code revision: 18 Oct 2026.**
Up to five versions (first submission plus four revised commit hashes).

## 1. Blocking for the submission

- [ ] **Push the latest commit** and note its hash (`git rev-parse HEAD`). Builderr runs that exact commit.
- [ ] **Register on Unstop** and share the project link: https://github.com/sanjaysaini383/signalpost
- [ ] **Email submit@builderr.ai** with the items Builderr lists (draft below).
- [ ] **Hand-check the 3 verified websites and a sample of other profiles** in `smoke/dashboard.html` against
  https://virksomhet.brreg.no/. A wrong-company publication stops a run from becoming official, so a human look
  at the published external claims is worth the time.

## 2. Ask Builderr for scoring keys (they offered; do not use personal accounts)

Soham wrote that Builderr can provide an API key for scoring, and that a credential tied to your personal account
should not be relied on. Ask for:

- [ ] **A Brave Search API key** (`BRAVE_SEARCH_API_KEY`). This is the biggest lever on the 50 recall points:
  without search, only 3 of 100 smoke-test companies got a verified website, and with it the agent has candidates
  for many more. The starter kit uses the same provider and the same variable name. Ask which request rate
  their key allows, so `BRAVE_MIN_INTERVAL` can be set to match.
- [ ] **An Anthropic API key** (`ANTHROPIC_API_KEY`), optional, for the website summary (synthesis points).

If they can provide only one, ask for the search key.

## 3. Decisions for you

- [ ] **The old `output/` folder** (1,000 profiles in the earlier format, about 40 MB). The official brief says
  precomputed profiles are neither submitted nor scored, so I recommend deleting it from the repo. I have not
  deleted it. Say the word and I will.
- [ ] **JBOX bonus:** Builderr says the criteria are not published yet. Ignore it until they clarify.

## 4. Email draft (fill in the brackets)

> **To:** submit@builderr.ai
> **Subject:** Signalpost entry – [agent name] – version 1
>
> Hello Builderr team,
>
> Here is my Signalpost entry.
>
> - **Repository:** https://github.com/sanjaysaini383/signalpost
> - **Exact commit:** [paste `git rev-parse HEAD`]
> - **Install step:** `uv sync --frozen` (Python 3.12+, dependencies pinned in `uv.lock`)
> - **Run command:** `uv run signalpost batch --organisations <batch.jsonl> --output out/envelopes.jsonl --report out/run-report.json`
>   (accepts the JSONL batch; writes exactly one terminal envelope per input; `--previous <envelopes.jsonl>` for refresh)
> - **Smoke-test result:** `smoke/` in the repository (`SMOKE_TEST.md`, `envelopes.jsonl`, `run-report.json`,
>   `rerun-report.json`). 100/100 envelopes, 829 requests, 71 s, $0. The re-run found 0 changes (idempotent).
> - **Models/APIs/licences:** Brønnøysund Enhetsregisteret and Regnskapsregisteret APIs (NLOD), Kartverket
>   address API (CC BY 4.0), the companies' own websites (robots.txt respected). Optional: Brave Search API
>   (`BRAVE_SEARCH_API_KEY`, candidate discovery only) and Anthropic Claude Haiku 5.5 (`ANTHROPIC_API_KEY`,
>   website summary). Details in `SOURCES_AND_POLICY.md`.
> - **Expected cost per official batch (1,000 companies):** $0 without keys. 8,553 requests and 9 min 10 s (measured). With the optional keys: at most one search query per company without a verified website, and one
>   Haiku call per verified website.
> - **Source rights, secrets and URL policy:** `SOURCES_AND_POLICY.md`
> - **Agent name:** [name]
> - **Contact for results:** [name, email]
>
> Could you provide a Brave Search API key (and optionally an Anthropic key) for scoring, as offered? The agent
> reads them from `BRAVE_SEARCH_API_KEY` and `ANTHROPIC_API_KEY` and runs fully without them.
>
> Best regards,
> [name]

Check the numbers against `smoke/SMOKE_TEST.md` and the 1,000-company scale test before sending.
