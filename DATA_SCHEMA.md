# Data schema

## Envelope (one JSON line per input organisation number)

```json
{
  "schema": "signalpost-envelope/1",
  "organisation_number": "923609016",
  "state": "complete",
  "run": {"run_id": "...", "started_at": "...", "completed_at": "...", "terminal_status": "completed"},
  "legal_identity": {"organisation_number": "...", "legal_name": "...", "legal_form": "...", "status": "active",
                     "registered_address": "...", "municipality": "...", "industry": "...",
                     "public_brand": "...", "official_website": "https://..."},
  "sections": {"legal_identity": {"availability": "available", "claims": 38}, "official_website": {...}, ...},
  "summary": {"text": "...", "unknowns": ["..."], "identity_check": ["..."]},
  "claims": [...],
  "evidence": [...],
  "source_snapshots": [...],
  "changes": [...],
  "refresh": {"previous_run_id": "...", "previous_completed_at": "...", "material_changes": 0, "stale_claims": 0},
  "errors": [{"type": "warning", "message": "..."}],
  "operations": {"requests": 17, "runtime_ms": 13565, "third_party_cost_usd": 0.0},
  "profile": {"...": "internal profile, kept so the next run can diff against it"}
}
```

`state` is one of `complete`, `not_found` (invalid, unknown or mismatched number), `source_error` or
`budget_exhausted`. An envelope is written for every input in every case.

## Sections and availability

Eight sections are always present: `legal_identity`, `annual_accounts`, `leadership`, `registered_workplaces`,
`official_website`, `company_profiles`, `hiring`, `public_activity`. Each has an `availability`:

| State | Meaning |
|---|---|
| `available` | at least one supported claim |
| `not_available` | the source was checked and has nothing (for example no careers page on the verified site) |
| `blocked` | robots.txt, the public-URL policy or the platform's terms prevented access |
| `not_applicable` | does not apply to this entity (deleted company, sub-unit without its own accounts) |
| `ambiguous` | a candidate exists but does not tie to the exact entity, so nothing is published |
| `failed` | the source could not be reached during this run |

A section without claims also gets one explicit absence claim with `value: null`, its state and a note. Missing
values are never written as 0.

## Claim

```json
{"id": "cl-<hash of org, field, value>", "field": "revenue", "value": {"amount": 1234.0, "currency": "NOK"},
 "availability": "available", "confidence": 0.99, "evidence_ids": ["ev-..."], "section": "annual_accounts",
 "source_class": "official_annual_accounts", "scope": "company", "reporting_period": "2025-12-31",
 "explanation": "why this fact belongs to this organisation number", "observed_at": "...", "first_observed": "..."}
```

Claim ids are stable hashes, so re-running the same snapshot yields the same ids and no duplicates.
`stale: true` marks a claim carried over from the previous run because its source failed this time.

Main fields: `legal_name`, `legal_form`, `organisation_status`, `registered_address`, `postal_address`,
`municipality`, `industry`, `registered_employees`, `founded`, `former_names`, `share_capital`, `geo_location`,
`public_brand`, `phone`, `email`; accounts `revenue`, `operating_costs`, `operating_profit`, `profit_before_tax`,
`net_profit`, `total_assets`, `current_assets`, `fixed_assets`, `cash`, `equity`, `total_debt`, `current_debt`,
`long_term_debt`, `accounts_filing`; `role` (with `role_code`); `registered_workplace`; `registered_website`,
`official_website`; `company_profile` (with `platform`); `careers_page`, `job_posting`, `hiring_channel`;
`news_item`; optional `business_summary`, `product_or_service`.

`official_website` exists only when the site's pages tied to the entity. `registered_website` is the register's
own entry, published as a register fact either way.

## Evidence

```json
{"id": "ev-...", "source_url": "...", "final_url": "...", "source_class": "company_site",
 "retrieved_at": "...", "content_sha256": "<sha256 of the response body>", "http_status": 200,
 "claim_span": "literal text from the source", "selector": "/antallAnsatte",
 "extraction_method": "registry_json | html | json_ld | meta | feed | outbound_link | identity_tie | llm:<model>"}
```

For register JSON the `selector` is a JSON pointer into the API document. For web pages `claim_span` is text
that occurs in the fetched page.

## Change

```json
{"id": "chg-...", "claim_key": "registered_employees", "field": "registered_employees", "change_type": "changed",
 "materiality": "material", "previous_value": 5, "current_value": 9,
 "previous_evidence": [{"source_url": "...", "retrieved_at": "...", "content_sha256": "...", "claim_span": "..."}],
 "current_evidence": [...], "previous_observed_at": "...", "detected_at": "..."}
```

`change_type` is `added`, `changed` or `removed`. Evidence for both sides is kept, so earlier evidence is
preserved in the newer envelope as well as in the archived snapshot.

## Run report (`--report`)

`run_id`, `code_commit`, input and counts, `states`, `operations` (requests, runtime, requests per company,
p50/p95 per company, LLM tokens, third-party cost), per-section `coverage`, claim counts by field, refresh
counts, and `validation` with its checks.
