# Signalpost Build Plan

**Deadline:** 17 Oct 2026, 11:59 PM IST (register on Unstop + email submit@builderr.ai). Code revisions allowed until 18 Oct.

## Goal
A CLI that takes a Norwegian organisation number and returns a JSON profile. Every fact carries a source URL, retrieval date and evidence snippet. State is kept between daily runs so changes can be reported.

## Scoring and design response

| Criterion | Points | Design response |
|---|---|---|
| Coverage | 35 | Many fields per company: official registers plus the company website |
| Correct match with evidence | 30 | Key everything on the org number. Every fact has source URL, date and snippet |
| Updates | 20 | Persist the previous profile, diff against it, record changes with timestamps |
| Explanations | 10 | Short "why this fact belongs to this company" for each fact |
| Ease of use | 5 | One command, README, `.env.example` |

**Qualification:** at least 65/100 overall, 21/35 coverage.
**Disqualifiers:** a wrong-company publication or a fabricated financial value.
**Rule:** precision over recall. If a fact can't be verified, leave it out.

**Daily limits:** 45 minutes, 2,000 outbound requests, $10 declared API cost, 100 random companies.

## Data sources
Verify endpoint names and rate limits on the Brønnøysund developer pages before coding.

**Official**
- Enhetsregisteret API: name, org form, NACE code, address, employees, dates, website, bankruptcy/liquidation status. `oppdateringer/enheter` supports change tracking.
- Regnskapsregisteret API: annual accounts. Financial values come **only** from here, copied exactly, never LLM-generated.
- Roles endpoint: board, CEO, auditor.
- Kunngjøringer: bankruptcies, mergers, capital changes.

**Public web**
- Company website: contacts, product/service description, social links.
- Doffin (procurement): optional bonus.

## Architecture
```
org_no -> validate (9 digits, mod-11 checksum)
       -> fetch registers (deterministic, no LLM)
       -> find website (from register field only)
       -> verify website belongs to company
       -> fetch 2-3 pages -> LLM extracts structured fields (with quotes)
       -> verify each extracted value appears in the page text
       -> diff vs previous profile -> write profile.json
```

- **Wrong-company guard:** accept a website only if the register lists it, or the page contains the org number, or the exact name plus postal code. Otherwise discard website facts.
- **Quote check:** every LLM-extracted value must be a substring of the fetched page text, else drop it.
- **LLM role:** extraction only (Haiku 5.5). It never invents numbers.
- **Budget:** ~20 requests and ~27 s per company. Async fetching, a global request counter that hard-stops near 1,800, and a response cache.
- **Cost:** register APIs are free. LLM roughly $1-2 per 100 companies.

## Fact schema
```json
{ "field": "employees", "value": 42,
  "source_url": "...", "retrieved_at": "2026-10-12T...",
  "evidence": "antallAnsatte: 42",
  "explanation": "Matched by org no. 123456789 in Enhetsregisteret" }
```

## Schedule

| Day | Goal |
|---|---|
| Oct 11 | Scaffold project, register fetchers, org-number validator. Read Unstop page for exact submission format |
| Oct 12 | Financials, roles, announcements. Schema and evidence model |
| Oct 13 | Website discovery, verification, LLM extraction with quote check |
| Oct 14 | State store and diff for updates. Budget and time guards |
| Oct 15 | Generate 1,000+ profiles from random org numbers. Hand-audit ~50 for wrong-company errors |
| Oct 16 | README, cost estimate, model details. Clean up and tag commit |
| Oct 17 | Register on Unstop, email submission |
| Oct 18 | Buffer for revisions |

## Submission checklist
- [ ] At least 1,000 company profiles
- [ ] Repository link
- [ ] Exact commit hash
- [ ] One command to run (e.g. `python -m signalpost run --input companies.txt`)
- [ ] Model/API details
- [ ] Expected run costs
- [ ] Registered on Unstop with project link
- [ ] Emailed to submit@builderr.ai

## Open decisions
1. Language: Python (`httpx` + `asyncio`) recommended.
2. JBOX bonus ($500): check what JBOX is on the Unstop page and whether it's cheap to adopt.
3. Source of the 1,000 org numbers: sample active companies from the Enhetsregisteret bulk/search API.
