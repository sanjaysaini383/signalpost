# Known limitations

- **Website discovery is the main limit on external coverage.** Most companies in the universe register no
  website. Without a search key the agent can only use the registered website, the registered e-mail domain and
  name-derived domains. With `BRAVE_SEARCH_API_KEY` it can find more candidates, but every candidate still has to
  pass the identity tie.
- **JavaScript-only sites** (an empty HTML shell) cannot be verified, because there is no browser rendering.
  They end as `ambiguous` or `not_available`.
- **Sites behind bot protection** (for example Cloudflare challenges) are not bypassed.
- **Social platforms, job boards and review sites are not crawled.** Only the links a company publishes on its
  own site are recorded. Follower counts, ratings and reviews are therefore not collected.
- **Dated activity** comes only from the company's own RSS/Atom feed or JSON-LD articles. News pages without
  either are not parsed for dates.
- **Job postings** are found only as JSON-LD `JobPosting` on the site or careers page, plus links to recruiting
  platforms. Listings rendered by an embedded third-party widget are not read.
- **Group structures:** parent and subsidiary links come from the register (`parent_organisation`,
  `part_of_group`). A group's shared website is deliberately not attributed to its subsidiaries.
- **The optional model step** (`ANTHROPIC_API_KEY`) is covered by tests with a fake client but has not been run
  against the live API by the author.
- **Kunngjøringer (official announcements)** are not used: no structured open API was found.
- **Persistent storage between runs is not assumed.** Pass the previous envelopes with `--previous` to get a
  refresh diff. Otherwise the first run in a clean directory reports no changes.
