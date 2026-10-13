# Sources, rights and safety policy

## Sources

| Source | Access | Use | Terms (as published by the provider; re-check before relying on them) |
|---|---|---|---|
| Enhetsregisteret API, `data.brreg.no/enhetsregisteret` | open API, no key | identity, status, addresses, industry, employees, contacts, roles, sub-units | Brønnøysundregistrene open data, Norwegian licence for open government data (NLOD) |
| Regnskapsregisteret API, `data.brreg.no/regnskapsregisteret` | open API, no key | filed annual accounts | Brønnøysundregistrene open data (NLOD) |
| Kartverket address API, `ws.geonorge.no/adresser/v1` | open API, no key | coordinates of the registered address | Kartverket open data (CC BY 4.0) |
| The company's own website | public pages, robots.txt respected | official website, contacts, company-owned profiles, careers, jobs, news feed | the company's own published content |
| Brave Search API (optional) | API key in `BRAVE_SEARCH_API_KEY` | candidate websites only | Brave Search API terms |
| Anthropic API (optional) | API key in `ANTHROPIC_API_KEY` | summary of the verified website | Anthropic API terms |

No platform is scraped. Social profiles, recruiting platforms and job boards are recorded only as links the
company publishes on its own verified site. Their pages are not fetched.

## Identity: what is published under an organisation number

1. The organisation number is validated (mod-11) and is the key for every request.
2. The register record must carry exactly the requested number, otherwise nothing is published.
3. Deleted entities (the register still answers with a `slettedato`) are reported as deleted.
4. Sub-units are attached only when the register names this number as their parent.
5. A website is published as `official_website` only when its pages tie to the exact entity:
   - registered website: the organisation number on the page, or the company name together with the registered
     postal code, registered phone number, or a domain equal to the company name;
   - domain of the registered e-mail address: the organisation number, or a domain equal to the company name
     with the name on the page (a parent or group site listing the subsidiary's address is not enough);
   - name-derived domain guesses: the organisation number on the page only;
   - search results: the organisation number on the page, or a domain equal to the company name plus the
     registered postal code or phone on the page.
   Parent, franchise, portfolio and service-provider sites therefore end as `ambiguous`, never as published.
6. Everything else from the website (profiles, jobs, news, contacts) is published only from a verified site.
7. Coordinates are kept only when street, postal code and municipality number equal the register values.
8. Financial values are copied verbatim from Regnskapsregisteret with their currency and period. The optional
   model is never used for numbers, and any figure in a model-extracted value must be inside its verbatim quote.

## Crawling rules

- robots.txt is read before any page on a site (RFC 9309: 4xx = no rules, 5xx or unreachable = disallow).
- At most about eight pages per company site (home, contact/about pages, one careers page, one news page, one
  feed), within a 40-second allowance per company, 10-second timeout and 2 MB cap per response.
- The User-Agent names the agent and links to this repository.
- Register API calls are retried with backoff on 429/5xx. Website calls are tried once per URL form.

## Safe URL handling

Website URLs come from third parties (the register, links on pages, search results) and are treated as
untrusted. Before every request, and for every redirect hop, the agent:

- allows only `http` and `https`, default ports, no credentials in the URL;
- resolves the host and refuses it unless every address is public (no private, loopback, link-local, reserved
  or multicast ranges, which also blocks cloud metadata endpoints);
- follows at most 5 redirects, re-checking each target.

Feeds are parsed with plain pattern matching, without XML entity expansion.

## Secrets

- Keys are read only from the environment variables listed in the README. No key is needed for a full run.
- Keys are sent only to their own provider, in a request header. They are not written to envelopes, snapshots,
  caches, logs or reports.
- `.env` is git-ignored. No credential tied to a personal account is required to reproduce a run.

## Caching

Responses are cached for one hour in `out/.cache` (`--cache-ttl`, `--no-cache`), only to avoid refetching
within a run. A run on a later day always refetches from the live sources.
